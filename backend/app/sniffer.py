"""Tier 3: learn how an unknown career site loads its jobs, then replay that call over plain HTTP.

Logged-out browsing only. We watch the page's own XHR/fetch traffic, keep the response that looks
like a job list, and save a `recipe` so later scrapes need no browser.
"""
import asyncio
import hashlib
import json
import re
import sys
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from .adapters.base import client, html_to_text, parse_date, raw_job, request
from .config import USER_AGENT
from .detect import ats_in_text, jobs_link

MAX_REPLAY_PAGES = 100
MAX_JOBS = 5000
_MIN_ITEMS = 5            # an array shorter than this is probably not a job list
# Images, fonts and video are dead weight. Stylesheets are NOT: aborting them stopped Wipro's
# SuccessFactors widget from ever requesting its jobs, so the one response worth having was
# never made. Never block something the page's own scripts might be waiting on.
_BLOCK = ("image", "font", "media")

# Order matters: each key serves one field, first claim wins (see build_field_map). "remote" is
# resolved before "location" so an arrangement field like `workplace_type` ("onsite"/"remote") is
# not mistaken for a place — that mapping leaves every job with no country.
FIELDS = {
    "title": r"^(job)?(title|name|position(title|name)?|role)$",
    "id": r"^(job|req(uisition)?|external|post(ing)?)?_?(id|number|code|slug|uid|path)$|^id$|^_id$",
    "url": r"(job|apply|absolute|canonical|detail|posting)?_?(url|link|permalink|href)$",
    "description": r"^(job)?_?(description|content|summary|body|text|details)$",
    "remote": r"(remote|telecommut|work_?model|workplace_?type|work_?location|workplace)",
    "employment": r"(employment|job|work|contract)_?(type|time|schedule)$|^schedule$",
    "location": r"(location|city|office|region|country|place|geo|address)",
    "department": r"(department|team|category|function|business_?unit|discipline)",
    "posted": r"(post(ed)?|creat(ed)?|publish(ed)?|start|first)_?(at|on|date|time|ts)?$|^date$",
}
# When several keys match a field, a key named exactly like the thing beats a fuzzy match, so
# `location` wins over `location_id` and `title` over `job_title_text`.
EXACT_NAMES = {
    "title": ("title", "name", "position", "role"),
    "id": ("id", "_id", "job_id", "jobid", "slug", "path"),
    "url": ("url", "link", "href", "permalink"),
    "description": ("description", "content", "body", "summary"),
    "location": ("location", "city", "country", "address", "locations"),
    "department": ("department", "team", "category"),
    "posted": ("posted_at", "created_at", "published_at", "date", "posted_on"),
    "employment": ("employment_type", "job_type", "work_type", "schedule"),
    "remote": ("remote", "workplace_type", "work_model", "is_remote"),
}
_FIELD_RE = {k: re.compile(v, re.I) for k, v in FIELDS.items()}
_TITLE_RE = _FIELD_RE["title"]
# A job list says what the job *is*: where it is, which team, when it was posted, what it pays.
# A name plus an id or a URL proves nothing — every tracker and directory payload has those, which is
# how amazon.jobs once learned Qualtrics survey intercepts and zoho.com an employee-portfolio JSON.
_JOBISH = re.compile(r"(location|city|country|office|remote|department|team|category|function|"
                     r"description|summary|employment|salary|compensation|post(ed)?|publish|apply)", re.I)


# ───────────────────────── scoring a captured response ─────────────────────────
def _arrays(node, path=(), depth=0):
    """Yield (path, list-of-dicts) for every array of objects in a JSON tree."""
    if depth > 4:
        return
    if isinstance(node, list):
        if len(node) >= _MIN_ITEMS and all(isinstance(x, dict) for x in node[:_MIN_ITEMS]):
            yield path, node
            # Some APIs wrap every hit in a single key — SuccessFactors returns
            # [{"response": {...}}, ...] — so offer the unwrapped rows as a candidate too, or every
            # real field stays one level out of reach and the array scores zero.
            keys = {k for x in node[:_MIN_ITEMS] for k in x}
            if len(keys) == 1:
                k = keys.pop()
                inner = [x[k] for x in node if isinstance(x.get(k), dict)]
                if len(inner) >= _MIN_ITEMS:
                    yield path + (k,), inner
        return
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _arrays(v, path + (k,), depth + 1)


def score_array(items: list[dict]) -> int:
    """0 = not a job list. Higher = more likely. Needs a title-ish key plus one job-describing key."""
    keys = {k for it in items[:5] if isinstance(it, dict) for k in it}
    if not any(_TITLE_RE.match(k) for k in keys):
        return 0
    if not any(_JOBISH.search(k) for k in keys):
        return 0
    titles = [it.get(next(k for k in it if _TITLE_RE.match(k)), "") for it in items[:5] if isinstance(it, dict)]
    if not all(isinstance(t, str) and t.strip() for t in titles):
        return 0
    return len(items)


def best_candidate(body) -> tuple[tuple, list[dict], int]:
    """Pick the highest-scoring job array in one JSON body. Returns (path, items, score)."""
    best = ((), [], 0)
    for path, items in _arrays(body):
        if (s := score_array(items)) > best[2]:
            best = (path, items, s)
    return best


# ───────────────────────── field map ─────────────────────────
def _keys(items: list[dict]) -> list[str]:
    seen = []
    for it in items[:10]:
        for k in it:
            if k not in seen:
                seen.append(k)
    return seen


def build_field_map(items: list[dict], root: tuple) -> dict:
    """Heuristic key-name mapping. Admin can hand-edit the saved recipe when a site maps wrong."""
    keys = _keys(items)
    fm: dict = {"root": list(root)}
    used: set[str] = set()
    for field, rx in _FIELD_RE.items():  # FIELDS order decides who claims a shared key first
        hits = [k for k in keys if k not in used and (rx.match(k) if field == "title" else rx.search(k))]
        if field == "id":  # prefer a short scalar id over a nested object
            hits = [k for k in hits if isinstance(items[0].get(k), (str, int, float))] or hits
        exact = [k for k in hits if k.lower() in EXACT_NAMES.get(field, ())]
        hits = exact or hits
        if hits:
            fm[field] = hits[0]
            used.add(hits[0])
    return fm


def flat(v, base_url: str | None = None) -> str | None:
    """Values arrive as scalars, {name:…}, or lists of either. Flatten to a readable string."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, str):
        return urljoin(base_url, v) if base_url and v.startswith("/") else v
    if isinstance(v, dict):
        for k in ("name", "label", "text", "value", "title", "fullLocation", "city", "descriptor"):
            if (inner := v.get(k)) is not None:
                return flat(inner, base_url)
        return None
    if isinstance(v, list):
        return "; ".join(filter(None, (flat(x, base_url) for x in v))) or None
    return None


def item_to_raw(item: dict, fm: dict, page_url: str, company: str) -> dict | None:
    g = lambda f: item.get(fm[f]) if fm.get(f) else None  # noqa: E731
    title = flat(g("title"))
    if not title:
        return None
    url = flat(g("url"), page_url) or page_url
    desc = flat(g("description")) or ""
    remote = g("remote")
    # a stable id matters more than a pretty one: Python's hash() is salted per process, which would
    # make every scrape look like a brand-new job and insert duplicates.
    ident = flat(g("id")) or hashlib.sha1(f"{title}|{flat(g('location'))}|{url}".encode()).hexdigest()[:16]
    return raw_job(
        external_id=str(ident), title=title,
        url=url, apply_url=url, company_name=company, department=flat(g("department")),
        description=html_to_text(desc) if "<" in desc else desc, location_raw=flat(g("location")),
        remote_hint=remote if isinstance(remote, bool) else None,
        workplace_hint=None if isinstance(remote, bool) else flat(remote),
        employment_type=flat(g("employment")), posted_at=parse_date(g("posted")),
    )


# ───────────────────────── pagination ─────────────────────────
def _num(s):
    return int(s) if isinstance(s, str) and s.lstrip("-").isdigit() else s if isinstance(s, int) else None


def diff_pagination(a: dict, b: dict) -> dict:
    """Two calls to the same endpoint -> which numeric param advanced, and by how much.

    a/b are {"url": str, "body": dict|None}. Returns a pagination spec for replay().
    """
    qa, qb = dict(parse_qsl(urlparse(a["url"]).query, keep_blank_values=True)), dict(parse_qsl(urlparse(b["url"]).query, keep_blank_values=True))
    for k in qa:
        na, nb = _num(qa.get(k)), _num(qb.get(k))
        if na is not None and nb is not None and nb > na:
            return {"kind": "query", "param": k, "start": na, "step": nb - na}
    ba, bb = a.get("body") or {}, b.get("body") or {}
    if isinstance(ba, dict) and isinstance(bb, dict):
        for k in ba:
            na, nb = _num(ba.get(k)), _num(bb.get(k))
            if na is not None and nb is not None and nb > na:
                return {"kind": "body", "param": k, "start": na, "step": nb - na}
    return {"kind": "none"}


_PAGE_KEY = re.compile(r"^(offset|start|from|skip|page|page_?num(ber)?|page_?index|pg|p)$", re.I)
_SIZE_KEY = re.compile(r"^(limit|size|count|num|per_?page|page_?size|rows|max)$", re.I)
_BY_SIZE = re.compile(r"^(offset|start|from|skip)$", re.I)   # advances by a page of rows, not by 1


def infer_pagination(req: dict, n_items: int) -> dict:
    """Only one call was seen: read the page parameter off that call instead of guessing blind."""
    bags = [("query", dict(parse_qsl(urlparse(req["url"]).query, keep_blank_values=True)))]
    if isinstance(req.get("body"), dict):
        bags.append(("body", req["body"]))
    for kind, bag in bags:
        param = next((k for k in bag if _PAGE_KEY.match(k) and _num(bag[k]) is not None), None)
        if not param:
            continue
        size = next((_num(bag[k]) for k in bag if _SIZE_KEY.match(k) and _num(bag[k])), None) or n_items
        return {"kind": kind, "param": param, "start": _num(bag[param]),
                "step": size if _BY_SIZE.match(param) else 1}
    return {"kind": "none"}


def page_request(req: dict, pg: dict, n: int) -> tuple[str, dict | None]:
    """Nth page of a learned request (n = 0 is the page we captured)."""
    url, body = req["url"], req.get("body")
    if pg["kind"] == "none" or n == 0:
        return url, body
    value = pg["start"] + pg["step"] * n
    if pg["kind"] == "query":
        u = urlparse(url)
        q = dict(parse_qsl(u.query, keep_blank_values=True))
        q[pg["param"]] = str(value)
        return urlunparse(u._replace(query=urlencode(q))), body
    return url, {**(body or {}), pg["param"]: value}


# ───────────────────────── learn (browser) ─────────────────────────
_KEEP_HEADER = re.compile(r"^(content-type|accept|accept-language|x-|origin|referer)", re.I)
_MORE = ("button:has-text('Load more')", "button:has-text('Show more')", "button:has-text('More jobs')",
         "a:has-text('Next')", "button:has-text('Next')", "[aria-label*='next' i]")


async def capture(url: str, timeout_ms: int = 45000) -> tuple[list[dict], str]:
    """Browse the page in a worker thread on its own loop.

    Windows forces this: psycopg async needs the selector loop, Playwright needs subprocess support
    (Proactor). A private loop inside a thread gives Playwright what it needs without touching the
    process-wide policy the rest of the worker depends on.
    """
    return await asyncio.to_thread(_capture_blocking, url, timeout_ms)


def _capture_blocking(url: str, timeout_ms: int) -> list[dict]:
    loop = asyncio.ProactorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_capture(url, timeout_ms))
    finally:
        loop.close()


IDLE_MS = 12000           # ceiling on waiting for the network to go quiet
SETTLE_MS = 2000          # a last beat after it does, for the request the quiet triggered


async def _settle(page):
    """Wait for the page to stop fetching, not for a fixed beat.

    A fixed wait is what lost SuccessFactors: Wipro boots its search widget from hcm55.sapsf.eu and
    only then POSTs /services/recruiting/v1/jobs, which lands after the four seconds we used to give
    it, so the one response worth having was never seen. networkidle never arrives on a page that
    polls, so it is capped rather than trusted.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=IDLE_MS)
    except Exception:  # noqa: BLE001 — a page that never goes quiet is normal, carry on
        pass
    await page.wait_for_timeout(SETTLE_MS)


async def _capture(url: str, timeout_ms: int) -> tuple[list[dict], str]:
    """Open the page, note every JSON XHR, scroll/click once to provoke a second page.

    Hands back the rendered HTML as well: when no feed turns up, that markup is the only place
    a JS-only board (Zoho) shows its job links at all, and Tier 4 reads it.
    """
    from playwright.async_api import async_playwright

    seen: list[dict] = []
    html = ""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()  # no anti-detection flags: we identify as JobScoutBot
        ctx = await browser.new_context(user_agent=USER_AGENT, viewport={"width": 1280, "height": 900})
        await ctx.route("**/*", lambda route: route.abort() if route.request.resource_type in _BLOCK else route.continue_())
        page = await ctx.new_page()

        async def on_response(resp):
            req = resp.request
            if req.resource_type not in ("xhr", "fetch") or not resp.ok:
                return
            if "json" not in (resp.headers.get("content-type") or ""):
                return
            try:
                body = await resp.json()
            except Exception:  # noqa: BLE001 — streamed/invalid bodies are not candidates
                return
            try:
                post = json.loads(req.post_data) if req.post_data else None
            except ValueError:
                post = None
            seen.append({"method": req.method, "url": req.url, "body": post,
                         "headers": {k: v for k, v in req.headers.items() if _KEEP_HEADER.match(k)},
                         "json": body})

        page.on("response", on_response)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await _settle(page)
            # JS-only landing pages (Swiggy) render their "View jobs" link only in the browser: follow it once.
            link = None if derive(seen) else jobs_link(await page.content(), page.url)
            if link and link.rstrip("/") != page.url.rstrip("/"):
                await page.goto(link, wait_until="domcontentloaded", timeout=timeout_ms)
                await _settle(page)
            for sel in _MORE:  # one nudge is enough to expose the pagination parameter
                try:
                    btn = page.locator(sel).first
                    if await btn.count() and await btn.is_visible():
                        await btn.click(timeout=4000)
                        await page.wait_for_timeout(3500)
                        break
                except Exception:  # noqa: BLE001 — selector miss is expected on most sites
                    continue
            else:
                await page.mouse.wheel(0, 20000)
                await page.wait_for_timeout(3500)
            html = await page.content()
        finally:
            await ctx.close()
            await browser.close()
    return seen, html


def derive(captures: list[dict]) -> tuple[dict, list[dict]] | None:
    """Captured traffic -> (recipe, items from the best page). None if nothing looked like a job list."""
    scored = []
    for cap in captures:
        path, items, s = best_candidate(cap["json"])
        if s:
            scored.append((s, cap, path, items))
    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    _, cap, path, items = scored[0]
    same = [c for c in captures if urlparse(c["url"]).path == urlparse(cap["url"]).path and c["method"] == cap["method"]]
    req = {"method": cap["method"], "url": cap["url"], "headers": cap["headers"], "body": cap["body"]}
    pg = diff_pagination(same[0], same[1]) if len(same) > 1 else {"kind": "none"}
    if pg["kind"] == "none":  # the page never asked for a second page — read the parameter off this call
        pg = infer_pagination(req, len(items))
    recipe = {
        "mode": "http",
        "request": req,
        "pagination": pg,
        "field_map": build_field_map(items, path),
    }
    merged, seen_ids = [], set()
    for s, c, p, its in scored:  # keep every page of the winning endpoint
        if urlparse(c["url"]).path == urlparse(cap["url"]).path:
            for it in its:
                key = json.dumps(it, sort_keys=True, default=str)[:400]
                if key not in seen_ids:
                    seen_ids.add(key)
                    merged.append(it)
    return recipe, merged


def dig(body, root: list):
    """Walk a saved root path to the job array.

    A key applied to a list maps over it, which is how the unwrap in _arrays replays: the root
    ["jobSearchResult", "response"] first selects the list, then pulls each hit out of its wrapper.
    """
    for k in root:
        if isinstance(body, list):
            body = [x[k] for x in body if isinstance(x, dict) and isinstance(x.get(k), dict)]
        elif isinstance(body, dict):
            body = body.get(k)
        else:
            return []
    return body if isinstance(body, list) else []


async def verify(recipe: dict) -> bool:
    """Replay page 2 with plain HTTP. False means the call is cookie/token bound -> browser mode."""
    if recipe["pagination"]["kind"] == "none":
        n = 0
    else:
        n = 1
    req, fm = recipe["request"], recipe["field_map"]
    url, body = page_request(req, recipe["pagination"], n)
    try:
        async with client(headers=req.get("headers") or {}) as c:
            r = await request(c, req["method"], url, json=body if body is not None else None)
            items = dig(r.json(), fm["root"])
    except Exception:  # noqa: BLE001 — any failure means HTTP replay is not available
        return False
    return bool(items) and score_array(items) > 0


async def learn(url: str):
    """Watch the site once.

    Returns (result, rendered html), where result is (recipe, items), a Detected ATS the site's own
    feed links to (Swiggy's jobs.json points at SmartRecruiters), or None if no job list was visible.
    The HTML comes back either way so the caller still has something to fall back on.
    """
    caps, html = await capture(url)
    out = derive(caps)
    if not out:
        # Feed we can't read as a job list, but it links to a known ATS (Swiggy -> SmartRecruiters): use that.
        # Not preferred when the feed IS readable: PhonePe's feed lists 532 jobs, its SmartRecruiters board only 142.
        return ats_in_text(json.dumps([c["json"] for c in caps])), html
    recipe, items = out
    if not await verify(recipe):
        recipe["mode"] = "browser"
    return (recipe, items), html


async def replay(recipe: dict, page_url: str, company: str, progress):
    """Paginate a saved http recipe. Yields raw_job dicts."""
    req, pg, fm = recipe["request"], recipe["pagination"], recipe["field_map"]
    out, seen = 0, set()
    async with client(headers=req.get("headers") or {}) as c:
        for n in range(MAX_REPLAY_PAGES):
            url, body = page_request(req, pg, n)
            r = await request(c, req["method"], url, json=body if body is not None else None, delay=0.5 if n else 0)
            items = dig(r.json(), fm["root"])
            fresh = 0
            for it in items:
                raw = item_to_raw(it, fm, page_url, company)
                if raw and raw["external_id"] not in seen:
                    seen.add(raw["external_id"])
                    fresh += 1
                    out += 1
                    yield raw
            await progress(out, None)
            if not items or not fresh or pg["kind"] == "none" or out >= MAX_JOBS:
                return


if __name__ == "__main__":
    body = {"data": {"jobs": [{"id": i, "name": f"Engineer {i}", "location": {"city": "Pune"},
                               "url": f"/j/{i}", "postedOn": "2026-10-01", "team": "Core"} for i in range(8)]}}
    path, items, s = best_candidate(body)
    assert path == ("data", "jobs") and s == 8, (path, s)
    fm = build_field_map(items, path)
    assert fm["root"] == ["data", "jobs"] and fm["title"] == "name" and fm["id"] == "id", fm
    assert fm["location"] == "location" and fm["url"] == "url" and fm["department"] == "team", fm
    r = item_to_raw(items[0], fm, "https://acme.com/careers", "Acme")
    assert r["title"] == "Engineer 0" and r["external_id"] == "0" and r["location_raw"] == "Pune", r
    assert r["url"] == "https://acme.com/j/0" and r["department"] == "Core", r
    assert dig(body, ["data", "jobs"]) == items and dig(body, ["nope"]) == []

    assert score_array([{"foo": 1}] * 6) == 0, "no title key"
    assert score_array([{"title": "x"}] * 6) == 0, "title alone is not enough"
    # Real misfires: a Qualtrics survey-intercept payload and Zoho's "humans of" portfolio both look
    # like {name, id, url} and were learned as job feeds. Neither says anything about a job.
    assert score_array([{"Name": "CSAT Survey Intercept", "InterceptID": "SI_1"}] * 6) == 0, "tracker payload"
    assert score_array([{"name": "Kiran Kumar S", "id": 3, "href": "kiran.html"}] * 6) == 0, "staff directory"
    assert score_array([{"title": "Backend Engineer", "location": "Pune"}] * 6) == 6, "title + location is a job list"

    pg = diff_pagination({"url": "https://a/api?offset=0&q=", "body": None},
                         {"url": "https://a/api?offset=20&q=", "body": None})
    assert pg == {"kind": "query", "param": "offset", "start": 0, "step": 20}, pg
    assert page_request({"url": "https://a/api?offset=0&q=", "body": None}, pg, 2)[0] == "https://a/api?offset=40&q="
    pgb = diff_pagination({"url": "https://a/api", "body": {"page": 1}}, {"url": "https://a/api", "body": {"page": 2}})
    assert pgb == {"kind": "body", "param": "page", "start": 1, "step": 1}, pgb
    assert page_request({"url": "https://a/api", "body": {"page": 1}}, pgb, 3)[1] == {"page": 4}
    assert diff_pagination({"url": "https://a/api", "body": None}, {"url": "https://a/api", "body": None})["kind"] == "none"

    # inferred pagination: offset advances by the page size, a page number advances by 1
    assert infer_pagination({"url": "https://a/api", "body": {"offset": 0, "limit": 20}}, 20) ==         {"kind": "body", "param": "offset", "start": 0, "step": 20}
    assert infer_pagination({"url": "https://a/api?page=1&size=50", "body": None}, 50) ==         {"kind": "query", "param": "page", "start": 1, "step": 1}
    assert infer_pagination({"url": "https://a/api?start=0", "body": None}, 15)["step"] == 15, "fall back to item count"
    assert infer_pagination({"url": "https://a/api", "body": {"q": "x"}}, 10) == {"kind": "none"}

    # a key maps to one field only: "locationsText" is a location, not a description
    wd = [{"title": "Engineer", "externalPath": "/job/1", "locationsText": "2 Locations",
           "postedOn": "Posted Today", "bulletFields": ["JR1"]}] * 6
    fmwd = build_field_map(wd, ("jobPostings",))
    assert fmwd.get("location") == "locationsText" and "description" not in fmwd, fmwd
    assert fmwd["title"] == "title" and fmwd["posted"] == "postedOn", fmwd
    assert fmwd["id"] == "externalPath", fmwd

    # Infor: `workplace_type` ("onsite") appears before `location`, and claiming it as the location
    # left all 237 jobs with no country, so none could show in a region feed.
    infor = [{"id": 1, "title": "Engineer", "employment_type": "full_time", "workplace_type": "onsite",
              "workplace_type_text": "Onsite", "url": "https://x/p/1", "description": "d",
              "location": {"id": "7", "city": "Hyderabad", "name": "Hyderabad", "province": "Telangana"}}] * 6
    fmi = build_field_map(infor, ("data",))
    assert fmi["location"] == "location", fmi
    assert fmi["remote"] == "workplace_type", fmi
    assert fmi["employment"] == "employment_type", fmi
    r_infor = item_to_raw(infor[0], fmi, "https://careers.infor.com/", "Infor")
    assert r_infor["location_raw"] == "Hyderabad", r_infor["location_raw"]
    # a key named exactly for the field beats a longer fuzzy match
    pick = build_field_map([{"location_id": 1, "location": "Pune", "job_title_text": "x", "title": "T"}] * 6, ())
    assert pick["location"] == "location" and pick["title"] == "title", pick

    # ids must be reproducible across processes, or every scrape re-inserts the same jobs
    noid = [{"name": "Analyst", "city": "Pune"}] * 6
    fmn = build_field_map(noid, ())
    a = item_to_raw(noid[0], fmn, "https://x/careers", "X")["external_id"]
    b = item_to_raw(dict(noid[0]), fmn, "https://x/careers", "X")["external_id"]
    assert a == b and len(a) == 16 and a.isalnum(), (a, b)
    print("sniffer OK")
