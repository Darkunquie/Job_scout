"""FastAPI backend.  Run:  uvicorn app.api:app --reload --port 8010   (docs at /docs)"""
import asyncio
import io
import json
import re
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal
from urllib.parse import urlparse

import bcrypt
import jwt
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, Field, field_validator

from . import db, embed, tasks
from .config import ADMIN_EMAIL, ADMIN_PASSWORD, BOARDS, COOKIE_SECURE, FRONTEND_ORIGIN, JWT_SECRET, REFRESH_MINUTES
from .detect import Detected, assert_public_url, detect, find_embedded
from .geo import scopes_for
from .seeds import SEEDS

COOKIE = "js_session"


@asynccontextmanager
async def lifespan(_):
    await db.open_pool()
    if not await db.fetchone("SELECT 1 FROM users LIMIT 1"):
        await db.execute("INSERT INTO users (email, password_hash, role, daily_quota) VALUES (%s,%s,'admin',100000)",
                         ADMIN_EMAIL, _hash(ADMIN_PASSWORD))
    yield
    await db.pool.close()


app = FastAPI(title="JobScout API", version="0.1", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=[FRONTEND_ORIGIN], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ───────────────────────── auth ─────────────────────────
def _hash(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def _set_session(resp: Response, user: dict):
    token = jwt.encode({"uid": user["id"], "role": user["role"],
                        "exp": datetime.now(timezone.utc) + timedelta(days=7)}, JWT_SECRET, algorithm="HS256")
    resp.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=COOKIE_SECURE, max_age=7 * 86400)


async def current_user(request: Request) -> dict:
    token = request.cookies.get(COOKIE) or request.headers.get("authorization", "").removeprefix("Bearer ")
    try:
        uid = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])["uid"]
    except Exception:
        raise HTTPException(401, "Not signed in")
    user = await db.fetchone("SELECT id, email, role, active, daily_quota FROM users WHERE id=%s", uid)
    if not user or not user["active"]:
        raise HTTPException(401, "Account disabled")
    return user


async def admin_user(user=Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only")
    return user


class Login(BaseModel):
    email: str  # plain str: default admin uses a .local address
    password: str


# Failed logins per account. ponytail: in-process, so it resets on restart and assumes one API process;
# move to a DB table if the API ever runs as several replicas.
LOGIN_FAILS: dict[str, list[float]] = {}
LOGIN_MAX, LOGIN_WINDOW = 10, 15 * 60


def _login_blocked(key: str) -> bool:
    cutoff = time.monotonic() - LOGIN_WINDOW
    LOGIN_FAILS[key] = [t for t in LOGIN_FAILS.get(key, []) if t > cutoff]
    return len(LOGIN_FAILS[key]) >= LOGIN_MAX


@app.post("/api/auth/login")
async def login(body: Login, resp: Response):
    key = body.email.strip().lower()
    if _login_blocked(key):
        raise HTTPException(429, "Too many failed sign-ins. Try again in 15 minutes.")
    u = await db.fetchone("SELECT * FROM users WHERE lower(email)=lower(%s)", body.email)
    if not u or not u["active"] or not u["password_hash"] or not bcrypt.checkpw(body.password.encode(), u["password_hash"].encode()):
        LOGIN_FAILS[key].append(time.monotonic())
        raise HTTPException(401, "Wrong email or password")
    LOGIN_FAILS.pop(key, None)
    _set_session(resp, u)
    return {"id": u["id"], "email": u["email"], "role": u["role"]}


@app.post("/api/auth/logout")
async def logout(resp: Response):
    resp.delete_cookie(COOKIE, httponly=True, samesite="lax", secure=COOKIE_SECURE)
    return {"ok": True}


@app.get("/api/auth/me")
async def me(user=Depends(current_user)):
    prefs = await db.fetchone("SELECT * FROM user_prefs WHERE user_id=%s", user["id"])
    return {**user, "prefs": prefs, "onboarded": prefs is not None}


class AcceptInvite(BaseModel):
    token: str
    password: str = Field(min_length=8)


@app.post("/api/auth/accept-invite")
async def accept_invite(body: AcceptInvite, resp: Response):
    inv = await db.fetchone("SELECT * FROM invites WHERE token=%s AND used_at IS NULL AND expires_at > now()", body.token)
    if not inv:
        raise HTTPException(400, "Invite is invalid or expired")
    u = await db.fetchone(
        "INSERT INTO users (email, password_hash, role) VALUES (%s,%s,%s) "
        "ON CONFLICT (email) DO UPDATE SET password_hash=EXCLUDED.password_hash, active=true RETURNING *",
        inv["email"], _hash(body.password), inv["role"])
    await db.execute("UPDATE invites SET used_at=now() WHERE token=%s", body.token)
    _set_session(resp, u)
    return {"id": u["id"], "email": u["email"], "role": u["role"]}


# ───────────────────────── prefs ─────────────────────────
class Prefs(BaseModel):
    region_mode: Literal["india", "countries", "all"] = "india"
    countries: list[str] = []
    include_remote: bool = True
    remote_scope: str = "any"
    boards: dict[str, bool] = {}


@app.put("/api/me/prefs")
async def put_prefs(p: Prefs, user=Depends(current_user)):
    countries = [c.upper()[:2] for c in p.countries]
    await db.execute("""
        INSERT INTO user_prefs (user_id, region_mode, countries, include_remote, remote_scope, boards)
        VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (user_id) DO UPDATE SET region_mode=EXCLUDED.region_mode, countries=EXCLUDED.countries,
          include_remote=EXCLUDED.include_remote, remote_scope=EXCLUDED.remote_scope, boards=EXCLUDED.boards""",
        user["id"], p.region_mode, countries, p.include_remote, p.remote_scope, json.dumps(p.boards))
    return {"ok": True}


# ───────────────────────── scraping ─────────────────────────
async def _check_quota(user, n: int):
    if user["role"] == "admin":
        return
    used = await db.fetchone("SELECT count(*) AS n FROM scrape_tasks WHERE user_id=%s AND created_at > now() - interval '1 day'",
                             user["id"])
    if used["n"] + n > user["daily_quota"]:
        raise HTTPException(429, f"Daily scrape limit reached ({user['daily_quota']}). Try again tomorrow.")


async def _add_company(url: str, user_id: int | None, seed: bool = False, queue: bool = True) -> dict:
    url = url.strip()
    try:
        assert_public_url(url)
        d = detect(url) or await find_embedded(url)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "status": "invalid", "message": str(e)[:200]}
    if not d:  # unknown host -> smart mode: Tier 2 JSON-LD/sitemap, then Tier 3 sniffer+recipe
        d = Detected("generic", urlparse(url if "://" in url else "https://" + url).hostname or url, {"url": url})
    if d.ats == "workday":
        flag = await db.fetchone("SELECT enabled FROM feature_flags WHERE key='workday'")
        if not flag["enabled"]:
            return {"url": url, "status": "workday_disabled", "ats": "workday", "message": "Enable Workday to scrape this portal"}
    co = await db.fetchone("""
        INSERT INTO companies (careers_url, host, ats_type, ats_slug, ats_extra, is_seed) VALUES (%s,%s,%s,%s,%s,%s)
        ON CONFLICT (ats_type, ats_slug) DO UPDATE SET is_seed = companies.is_seed OR EXCLUDED.is_seed
        RETURNING *""", url, urlparse(url if "://" in url else "https://" + url).hostname, d.ats, d.slug,
        json.dumps(d.extra), seed)
    if user_id:
        await db.execute("INSERT INTO user_companies (user_id, company_id) VALUES (%s,%s) "
                         "ON CONFLICT (user_id, company_id) DO UPDATE SET added_at=now()", user_id, co["id"])
    fresh = co["last_scraped_at"] and co["status"] == "ok" and \
        co["last_scraped_at"] > datetime.now(timezone.utc) - timedelta(minutes=REFRESH_MINUTES)
    task_id = None
    if not fresh and queue:
        task_id = await tasks.active_company_task(co["id"])
        if task_id:
            await tasks.promote(task_id, user_id)   # a queued background refresh becomes user work
        else:
            task_id = await tasks.enqueue("company", {"company_id": co["id"]}, user_id)
    status = "cached" if fresh else "queued" if task_id else "added"
    return {"url": url, "status": status, "ats": d.ats, "company_id": co["id"],
            "company": co["name"], "task_id": task_id, "job_count": co["job_count"]}


class UrlsIn(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)


@app.post("/api/scrape/urls")
async def scrape_urls(body: UrlsIn, user=Depends(current_user)):
    urls = list(dict.fromkeys(u.strip() for u in body.urls if u.strip()))
    await _check_quota(user, len(urls))
    return await asyncio.gather(*[_add_company(u, user["id"]) for u in urls])


@app.post("/api/scrape/detect")
async def detect_urls(body: UrlsIn, user=Depends(current_user)):
    """Cheap, no-network preview for chips under the URL box."""
    out = []
    for u in body.urls:
        d = detect(u.strip())
        out.append({"url": u, "ats": d.ats if d else None, "slug": d.slug if d else None})
    return out


class BoardsIn(BaseModel):
    boards: list[Literal["linkedin", "naukri", "indeed"]] = Field(min_length=1)
    q: str = Field(min_length=2, max_length=100)
    location: str = ""
    country_code: str | None = None
    hours_old: int | None = Field(default=None, ge=1, le=720)
    results: int = Field(default=100, ge=10, le=300)


@app.post("/api/scrape/boards")
async def scrape_boards(body: BoardsIn, user=Depends(current_user)):
    await _check_quota(user, len(body.boards))
    flags = {r["key"]: r["enabled"] for r in await db.fetch("SELECT * FROM feature_flags")}
    out = []
    for b in body.boards:
        if not flags.get(b):
            out.append({"board": b, "status": "disabled"})
            continue
        tid = await tasks.enqueue("board", {"board": b, **body.model_dump(exclude={"boards"})}, user["id"])
        out.append({"board": b, "status": "queued", "task_id": tid})
    return out


async def _task(task_id: int, user) -> dict:
    t = await db.fetchone("SELECT id, kind, payload, status, progress, error, created_at, finished_at, user_id "
                          "FROM scrape_tasks WHERE id=%s", task_id)
    if not t or (user["role"] != "admin" and t["user_id"] not in (None, user["id"])):
        raise HTTPException(404, "Task not found")
    return t


@app.get("/api/scrape/tasks")
async def get_tasks(ids: str, user=Depends(current_user)):
    return [await _task(int(i), user) for i in ids.split(",") if i.strip().isdigit()][:50]


@app.get("/api/scrape/tasks/{task_id}/stream")
async def stream_task(task_id: int, user=Depends(current_user)):
    await _task(task_id, user)

    async def gen():
        last = None
        while True:
            t = await db.fetchone("SELECT status, progress, error FROM scrape_tasks WHERE id=%s", task_id)
            payload = json.dumps(t, default=str)
            if payload != last:
                yield f"data: {payload}\n\n"
                last = payload
            if t["status"] in ("done", "error"):
                return
            await asyncio.sleep(1)

    return StreamingResponse(gen(), media_type="text/event-stream")


# ───────────────────────── companies ─────────────────────────
@app.get("/api/companies")
async def my_companies(user=Depends(current_user)):
    return await db.fetch("""
        SELECT c.id, c.name, c.careers_url, c.ats_type, c.status, c.last_scraped_at, c.last_error, c.job_count, uc.added_at
        FROM user_companies uc JOIN companies c ON c.id = uc.company_id WHERE uc.user_id=%s ORDER BY uc.added_at DESC""",
        user["id"])


@app.delete("/api/companies/{company_id}")
async def remove_company(company_id: int, user=Depends(current_user)):
    await db.execute("DELETE FROM user_companies WHERE user_id=%s AND company_id=%s", user["id"], company_id)
    return {"ok": True}


@app.post("/api/companies/{company_id}/refresh")
async def refresh_company(company_id: int, user=Depends(current_user)):
    await _check_quota(user, 1)
    if tid := await tasks.active_company_task(company_id):
        await tasks.promote(tid, user["id"])
    else:
        tid = await tasks.enqueue("company", {"company_id": company_id}, user["id"])
    return {"task_id": tid}


# ───────────────────────── jobs search ─────────────────────────
def _csv(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split(",") if x.strip()]


class JobFilters:
    def __init__(
        self,
        scope: Literal["all", "mine", "default"] = "all",
        region: Literal["india", "countries", "all", "prefs"] = "prefs",
        countries: str | None = None,
        include_remote: bool | None = None,
        q: str | None = None,
        city: str | None = None,
        sources: str | None = Query(None, description="csv: portal,linkedin,naukri,indeed,greenhouse,workday…"),
        work_arrangement: str | None = Query(None, description="csv: Remote,Hybrid,On-site,Unspecified"),
        employment_type: str | None = None,
        exp_level: str | None = Query(None, description="csv: intern,fresher,junior,mid,senior,lead,unspecified"),
        exp_min: int | None = None,
        exp_max: int | None = None,
        posted_days: int | None = None,
        salary_min: float | None = Query(None, description="INR per year"),
        salary_max: float | None = None,
        include_undisclosed_salary: bool = True,
        skills: str | None = None,
        companies: str | None = None,
        exclude_companies: str | None = None,
        company_id: int | None = None,
        visa: bool | None = None,
        include_closed: bool = False,
        collapse_duplicates: bool = True,
    ):
        self.__dict__.update(locals())
        del self.__dict__["self"]


async def _where(f: JobFilters, user) -> tuple[str, list]:
    w, a = [], []
    if not f.include_closed:
        w.append("j.status = 'active'")
    if f.scope == "mine":
        w.append("j.company_id IN (SELECT company_id FROM user_companies WHERE user_id=%s)")
        a.append(user["id"])
    elif f.scope == "default":
        w.append("j.company_id IN (SELECT id FROM companies WHERE is_seed)")
    if f.company_id:
        w.append("j.company_id = %s")
        a.append(f.company_id)

    mode, countries, inc_remote = f.region, [c.upper() for c in _csv(f.countries)], f.include_remote
    if mode == "prefs":
        p = await db.fetchone("SELECT * FROM user_prefs WHERE user_id=%s", user["id"])
        mode = p["region_mode"] if p else "all"
        countries = countries or (p["countries"] if p else [])
        inc_remote = p["include_remote"] if (p and inc_remote is None) else inc_remote
    inc_remote = True if inc_remote is None else inc_remote
    if mode == "india":
        countries = ["IN"]
    if mode in ("india", "countries") and countries:
        # Remote rows join on remote_scope only: 'ANY', one of the chosen countries, or a region that
        # contains one. No fallback on empty j.countries — that let Remote-EMEA roles into every feed.
        remote = " OR (j.is_remote AND j.remote_scope = ANY(%s))" if inc_remote else ""
        w.append(f"(j.countries && %s::text[]{remote})")
        a.append(countries)
        if inc_remote:
            a.append(scopes_for(countries))

    if f.q:
        w.append("(j.search @@ plainto_tsquery('simple', %s) OR j.title ILIKE %s OR j.company_name ILIKE %s)")
        a += [f.q, f"%{f.q}%", f"%{f.q}%"]
    if f.city:
        w.append("(j.city ILIKE %s OR j.location_raw ILIKE %s)")
        a += [f"%{f.city}%", f"%{f.city}%"]
    if src := _csv(f.sources):
        parts = []
        if "portal" in src:
            parts.append("j.source <> ALL(%s)")
            a.append(list(BOARDS))
        rest = [s for s in src if s != "portal"]
        if rest:
            parts.append("j.source = ANY(%s)")
            a.append(rest)
        w.append("(" + " OR ".join(parts) + ")")
    if wa := _csv(f.work_arrangement):
        cond = ["j.work_arrangement = ANY(%s)"]
        a.append(wa)
        if "Unspecified" in wa:
            cond.append("j.work_arrangement IS NULL")
        w.append("(" + " OR ".join(cond) + ")")
    if et := _csv(f.employment_type):
        cond = ["j.employment_type = ANY(%s)"]
        a.append(et)
        if "Unspecified" in et:
            cond.append("j.employment_type IS NULL")
        w.append("(" + " OR ".join(cond) + ")")
    if el := _csv(f.exp_level):
        cond = ["j.exp_level = ANY(%s)"]
        a.append(el)
        if "unspecified" in el:
            cond.append("j.exp_level IS NULL")
        w.append("(" + " OR ".join(cond) + ")")
    if f.exp_min is not None:
        w.append("(j.exp_max IS NULL OR j.exp_max >= %s) AND j.exp_min IS NOT NULL")
        a.append(f.exp_min)
    if f.exp_max is not None:
        w.append("j.exp_min <= %s")
        a.append(f.exp_max)
    if f.posted_days:
        w.append("COALESCE(j.posted_at, j.first_seen_at) > now() - make_interval(days => %s)")
        a.append(f.posted_days)
    if f.salary_min is not None or f.salary_max is not None:
        cond = []
        if f.salary_min is not None:
            cond.append("j.salary_inr_year >= %s")
            a.append(f.salary_min)
        if f.salary_max is not None:
            cond.append("j.salary_inr_year <= %s")
            a.append(f.salary_max)
        s = " AND ".join(cond)
        w.append(f"(({s}) OR j.salary_inr_year IS NULL)" if f.include_undisclosed_salary else f"({s})")
    if sk := _csv(f.skills):
        w.append("j.skills @> %s::text[]")
        a.append(sk)
    if co := _csv(f.companies):
        w.append("j.company_name = ANY(%s)")
        a.append(co)
    if ex := _csv(f.exclude_companies):
        w.append("NOT (j.company_name = ANY(%s))")
        a.append(ex)
    if f.visa is not None:
        w.append("j.visa_sponsorship IS TRUE" if f.visa else "j.visa_sponsorship IS NOT TRUE")
    if f.collapse_duplicates and not _csv(f.sources):
        w.append("(j.cluster_id IS NULL OR j.cluster_id = j.id)")
    return (" AND ".join(w) or "true"), a


SORTS = {
    "match": "match_score DESC NULLS LAST, j.id DESC",
    "posted": "COALESCE(j.posted_at, j.first_seen_at) DESC, j.id DESC",
    "salary": "j.salary_inr_year DESC NULLS LAST, j.id DESC",
    "company": "j.company_name, j.title",
    "random": "md5(j.id::text || current_date::text)",
}
LIST_COLS = """j.id, j.source, j.company_name, j.title, j.url, j.apply_url, j.department, j.location_raw, j.country_code,
  j.countries, j.city, j.is_remote, j.work_arrangement, j.employment_type, j.exp_min, j.exp_max, j.exp_level,
  j.salary_min, j.salary_max, j.salary_currency, j.salary_period, j.salary_inr_year, j.skills, j.visa_sponsorship,
  j.posted_at, j.first_seen_at, j.status, (j.first_seen_at > now() - interval '24 hours') AS is_new,
  (SELECT array_agg(DISTINCT s.source) FROM jobs s WHERE s.cluster_id = j.cluster_id AND s.status='active') AS also_on"""


# 0.7 cosine + 0.3 skill overlap: pure cosine ranks oddly, skill overlap makes the number explainable.
MATCH_EXPR = """, round((0.7 * (1 - (j.embedding <=> %s::vector)) + 0.3 * COALESCE(
     cardinality(ARRAY(SELECT unnest(j.skills) INTERSECT SELECT unnest(%s::text[])))::float
     / NULLIF(cardinality(j.skills), 0), 0))::numeric, 4) AS match_score"""
NO_MATCH = ", NULL::numeric AS match_score"

Sort = Literal["posted", "salary", "company", "random", "match"]


async def _resume(user) -> dict | None:
    return await db.fetchone("SELECT id, skills, embedding FROM resumes WHERE user_id=%s AND embedding IS NOT NULL "
                             "ORDER BY id DESC LIMIT 1", user["id"])


async def _scored_cols(user, sort: str) -> tuple[str, list]:
    """Add match_score to the select list when the user has an embedded resume."""
    r = await _resume(user)
    if not r:
        if sort == "match":
            raise HTTPException(400, "Upload a resume first to sort by match")
        return LIST_COLS + NO_MATCH, []
    return LIST_COLS + MATCH_EXPR, [r["embedding"], r["skills"]]


@app.get("/api/jobs")
async def list_jobs(f: JobFilters = Depends(), sort: Sort = "posted",
                    limit: int = Query(50, le=100), offset: int = Query(0, ge=0), user=Depends(current_user)):
    cols, pre = await _scored_cols(user, sort)
    where, args = await _where(f, user)
    items = await db.fetch(f"SELECT {cols} FROM jobs j WHERE {where} ORDER BY {SORTS[sort]} LIMIT %s OFFSET %s",
                           *pre, *args, limit, offset)
    total = (await db.fetchone(f"SELECT count(*) AS n FROM jobs j WHERE {where}", *args))["n"]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# Fields where "no value" is a real, filterable answer. The label must match what _where() expects.
UNSPECIFIED = {"work_arrangement": "Unspecified", "exp_level": "unspecified", "employment_type": "Unspecified"}


@app.get("/api/jobs/facets")
async def facets(f: JobFilters = Depends(), user=Depends(current_user)):
    where, args = await _where(f, user)
    out = {}
    for key, expr in {"country": "unnest(j.countries)", "source": "j.source", "work_arrangement": "j.work_arrangement",
                      "employment_type": "j.employment_type", "exp_level": "j.exp_level", "company": "j.company_name",
                      "skills": "unnest(j.skills)", "city": "j.city"}.items():
        rows = await db.fetch(f"SELECT {expr} AS v, count(*) AS n FROM jobs j WHERE {where} GROUP BY 1 ORDER BY 2 DESC LIMIT 60", *args)
        # Most ATSs leave these blank. Dropping the NULL bucket hid more than half the feed from the
        # filter rail, so surface it under the same label the filter understands.
        blank = UNSPECIFIED.get(key)
        out[key] = [{"v": blank if r["v"] is None else r["v"], "n": r["n"]}
                    for r in rows if r["v"] is not None or blank]
    return out


EXPORT_COLS = [("Title", "title"), ("Company", "company_name"), ("Location", "location_raw"), ("City", "city"),
               ("Countries", "countries"), ("Work arrangement", "work_arrangement"), ("Employment type", "employment_type"),
               ("Experience level", "exp_level"), ("Exp min (yrs)", "exp_min"), ("Exp max (yrs)", "exp_max"),
               ("Salary min", "salary_min"), ("Salary max", "salary_max"), ("Currency", "salary_currency"),
               ("Period", "salary_period"), ("Salary INR/yr (est.)", "salary_inr_year"), ("Skills", "skills"),
               ("Visa sponsorship", "visa_sponsorship"), ("Department", "department"), ("Source", "source"),
               ("Posted", "posted_at"), ("First seen", "first_seen_at"), ("Apply URL", "apply_url")]


@app.get("/api/jobs/export.xlsx", include_in_schema=True)
async def export(f: JobFilters = Depends(), ids: str | None = None, sort: Sort = "posted",
                 user=Depends(current_user)):
    cols, pre = await _scored_cols(user, sort)
    if ids:
        rows = await db.fetch(f"SELECT {cols} FROM jobs j WHERE j.id = ANY(%s) ORDER BY {SORTS[sort]}",
                              *pre, [int(i) for i in _csv(ids) if i.isdigit()][:50000])
    else:
        where, args = await _where(f, user)
        rows = await db.fetch(f"SELECT {cols} FROM jobs j WHERE {where} ORDER BY {SORTS[sort]} LIMIT 50000", *pre, *args)
    wb = Workbook()
    ws = wb.active
    ws.title = "Jobs"
    ws.append([h for h, _ in EXPORT_COLS])
    for c in ws[1]:
        c.font, c.fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="4F46E5")
    for r in rows:
        vals = []
        for _, k in EXPORT_COLS:
            v = r[k]
            if isinstance(v, list):
                v = ", ".join(map(str, v))
            elif isinstance(v, datetime):
                v = v.replace(tzinfo=None)
            vals.append(v)
        ws.append(vals)
        ws.cell(ws.max_row, len(EXPORT_COLS)).hyperlink = r["apply_url"]
    for i, (h, _) in enumerate(EXPORT_COLS, 1):
        ws.column_dimensions[ws.cell(1, i).column_letter].width = 40 if h in ("Title", "Location", "Skills", "Apply URL") else 16
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    name = f"jobscout-{datetime.now():%Y%m%d-%H%M}.xlsx"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/api/jobs/{job_id}")
async def job_detail(job_id: int, user=Depends(current_user)):
    cols, pre = await _scored_cols(user, "posted")
    j = await db.fetchone(f"SELECT {cols}, j.description FROM jobs j WHERE j.id=%s", *pre, job_id)
    if not j:
        raise HTTPException(404, "Job not found")
    if r := await _resume(user):
        mine = set(r["skills"] or [])
        j["skills_matched"] = [s for s in (j["skills"] or []) if s in mine]
        j["skills_missing"] = [s for s in (j["skills"] or []) if s not in mine]
    return j


# ───────────────────────── resume ─────────────────────────
@app.post("/api/resume")
async def upload_resume(file: UploadFile = File(...), user=Depends(current_user)):
    try:
        text = embed.extract_text(file.filename or "", await file.read())
    except ValueError as e:
        raise HTTPException(400, str(e))
    r = await db.fetchone("INSERT INTO resumes (user_id, filename, text) VALUES (%s,%s,%s) RETURNING id",
                          user["id"], file.filename, text)
    tid = await tasks.enqueue("resume", {"resume_id": r["id"]}, user["id"])
    return {"resume_id": r["id"], "task_id": tid, "chars": len(text)}


@app.get("/api/resume")
async def my_resume(user=Depends(current_user)):
    r = await db.fetchone("SELECT id, filename, skills, created_at, (embedding IS NOT NULL) AS ready "
                          "FROM resumes WHERE user_id=%s ORDER BY id DESC LIMIT 1", user["id"])
    if not r:
        raise HTTPException(404, "No resume uploaded yet")
    return r


@app.delete("/api/resume/{resume_id}")
async def delete_resume(resume_id: int, user=Depends(current_user)):
    await db.execute("DELETE FROM resumes WHERE id=%s AND user_id=%s", resume_id, user["id"])
    return {"ok": True}


# ───────────────────────── tracker ─────────────────────────
class AppIn(BaseModel):
    job_id: int
    stage: Literal["saved", "applied", "interview", "offer", "rejected"] = "saved"
    notes: str | None = None


@app.get("/api/applications")
async def list_apps(user=Depends(current_user)):
    # a.id is aliased: LIST_COLS already selects j.id, and two columns called "id" is a trap for callers.
    return await db.fetch(f"SELECT a.id AS application_id, a.stage, a.notes, a.updated_at, {LIST_COLS} "
                          "FROM applications a JOIN jobs j ON j.id=a.job_id WHERE a.user_id=%s "
                          "ORDER BY a.updated_at DESC", user["id"])


@app.put("/api/applications")
async def upsert_app(body: AppIn, user=Depends(current_user)):
    return await db.fetchone("""
        INSERT INTO applications (user_id, job_id, stage, notes) VALUES (%s,%s,%s,%s)
        ON CONFLICT (user_id, job_id) DO UPDATE SET stage=EXCLUDED.stage, notes=COALESCE(EXCLUDED.notes, applications.notes),
          updated_at=now() RETURNING *""", user["id"], body.job_id, body.stage, body.notes)


@app.delete("/api/applications/{job_id}")
async def delete_app(job_id: int, user=Depends(current_user)):
    await db.execute("DELETE FROM applications WHERE user_id=%s AND job_id=%s", user["id"], job_id)
    return {"ok": True}


# ───────────────────────── shortlists ─────────────────────────
class ShortlistIn(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=500)


@app.post("/api/shortlists")
async def create_shortlist(body: ShortlistIn, user=Depends(current_user)):
    token = secrets.token_urlsafe(12)
    await db.execute("INSERT INTO shortlists (token, user_id, job_ids, expires_at) VALUES (%s,%s,%s, now() + interval '30 days')",
                     token, user["id"], body.job_ids)
    return {"token": token, "url": f"{FRONTEND_ORIGIN}/s/{token}"}


@app.get("/api/shortlists/{token}")
async def get_shortlist(token: str):
    s = await db.fetchone("SELECT * FROM shortlists WHERE token=%s AND expires_at > now()", token)
    if not s:
        raise HTTPException(404, "Shortlist not found or expired")
    return await db.fetch(f"SELECT {LIST_COLS} FROM jobs j WHERE j.id = ANY(%s)", s["job_ids"])


# ───────────────────────── admin ─────────────────────────
# JobScout never sends mail - an invite produces a link the admin copies - so strict deliverability
# checking only gets in the way. EmailStr rejects reserved TLDs, which would stop an admin whose own
# account is admin@jobscout.local from inviting a colleague on that same domain.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class InviteIn(BaseModel):
    email: str
    role: Literal["user", "admin"] = "user"

    @field_validator("email")
    @classmethod
    def _shaped_like_an_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter an email address like name@company.com")
        return v


@app.post("/api/admin/invites")
async def create_invite(body: InviteIn, admin=Depends(admin_user)):
    token = secrets.token_urlsafe(24)
    await db.execute("INSERT INTO invites (token, email, role, created_by, expires_at) VALUES (%s,%s,%s,%s, now() + interval '7 days')",
                     token, body.email.lower(), body.role, admin["id"])
    return {"token": token, "url": f"{FRONTEND_ORIGIN}/invite/{token}", "expires_in_days": 7}


@app.get("/api/admin/users")
async def list_users(_=Depends(admin_user)):
    return await db.fetch("""
        SELECT u.id, u.email, u.role, u.active, u.daily_quota, u.created_at,
          (SELECT count(*) FROM scrape_tasks t WHERE t.user_id=u.id AND t.created_at > now() - interval '1 day') AS scrapes_today
        FROM users u ORDER BY u.created_at""")


class UserPatch(BaseModel):
    active: bool | None = None
    role: Literal["user", "admin"] | None = None
    daily_quota: int | None = Field(None, ge=0, le=100000)


@app.patch("/api/admin/users/{uid}")
async def patch_user(uid: int, body: UserPatch, admin=Depends(admin_user)):
    if uid == admin["id"] and (body.active is False or body.role == "user"):
        raise HTTPException(400, "You can't disable or demote yourself")
    for k, v in body.model_dump(exclude_none=True).items():
        await db.execute(f"UPDATE users SET {k}=%s WHERE id=%s", v, uid)  # k is from the fixed model fields
    return {"ok": True}


@app.get("/api/admin/flags")
async def get_flags(_=Depends(current_user)):
    return {r["key"]: r["enabled"] for r in await db.fetch("SELECT * FROM feature_flags")}


@app.patch("/api/admin/flags")
async def patch_flags(body: dict[Literal["workday", "linkedin", "naukri", "indeed"], bool], _=Depends(admin_user)):
    for k, v in body.items():
        await db.execute("UPDATE feature_flags SET enabled=%s WHERE key=%s", v, k)
    return {r["key"]: r["enabled"] for r in await db.fetch("SELECT * FROM feature_flags")}


@app.post("/api/admin/seed")
async def add_seed(body: UrlsIn, _=Depends(admin_user)):
    return await asyncio.gather(*[_add_company(u, None, seed=True) for u in body.urls])


@app.post("/api/admin/seed/defaults")
async def add_default_seeds(_=Depends(admin_user)):
    """Load the shipped seed list (app/seeds.py). Idempotent.

    Rows only — the refresh scheduler scrapes them a few at a time instead of all at once.
    """
    return await asyncio.gather(*[_add_company(u, None, seed=True, queue=False) for u in SEEDS])


@app.get("/api/admin/seed")
async def list_seed(_=Depends(admin_user)):
    return await db.fetch("SELECT id, name, careers_url, ats_type, status, job_count, last_scraped_at FROM companies "
                          "WHERE is_seed ORDER BY name")


@app.delete("/api/admin/seed/{company_id}")
async def remove_seed(company_id: int, _=Depends(admin_user)):
    await db.execute("UPDATE companies SET is_seed=false WHERE id=%s", company_id)
    return {"ok": True}


@app.get("/api/healthz")
async def healthz():
    """Liveness for Docker/Coolify: the process answers and the database does too."""
    await db.fetchone("SELECT 1")
    return {"ok": True}


@app.get("/api/admin/health")
async def health(_=Depends(admin_user)):
    adapters = await db.fetch("""
        SELECT adapter, count(*) AS runs, count(*) FILTER (WHERE complete) AS ok,
               count(*) FILTER (WHERE blocked) AS blocked, max(finished_at) AS last_run,
               round(100.0 * count(*) FILTER (WHERE complete) / NULLIF(count(*),0), 1) AS success_pct
        FROM scrape_runs WHERE started_at > now() - interval '7 days' GROUP BY adapter ORDER BY adapter""")
    problems = await db.fetch("SELECT id, name, careers_url, ats_type, status, last_error, last_scraped_at FROM companies "
                              "WHERE status IN ('error','blocked','needs_attention') ORDER BY last_scraped_at DESC NULLS LAST LIMIT 100")
    queue = await db.fetch("SELECT status, count(*) AS n FROM scrape_tasks WHERE created_at > now() - interval '1 day' GROUP BY status")
    totals = await db.fetchone("SELECT count(*) FILTER (WHERE status='active') AS active_jobs, count(*) AS all_jobs, "
                               "count(DISTINCT company_id) AS companies FROM jobs")
    return {"adapters": adapters, "problem_companies": problems, "queue_24h": queue, "totals": totals}


@app.get("/api/admin/runs")
async def runs(limit: int = Query(100, le=500), _=Depends(admin_user)):
    return await db.fetch("SELECT r.*, c.name AS company FROM scrape_runs r LEFT JOIN companies c ON c.id=r.company_id "
                          "ORDER BY r.id DESC LIMIT %s", limit)


@app.get("/api/meta")
async def meta(_=Depends(current_user)):
    """Static option lists for the frontend filters."""
    import pycountry
    return {
        "countries": sorted(({"code": c.alpha_2, "name": getattr(c, "common_name", c.name)} for c in pycountry.countries),
                            key=lambda c: c["name"]),
        "work_arrangements": ["Remote", "Hybrid", "On-site", "Unspecified"],
        "employment_types": ["Full-time", "Part-time", "Internship", "Contract", "Temporary", "Apprenticeship",
                             "Unspecified"],
        "exp_levels": ["intern", "fresher", "junior", "mid", "senior", "lead", "unspecified"],
        "sources": ["portal", *BOARDS],
    }
