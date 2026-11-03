"""LinkedIn / Naukri / Indeed via JobSpy (logged-out public pages only).

Rules: no login, no captcha bypass, low volume, store snippet + link, scrub personal contact data.
"""
import asyncio
import logging
import math
import re

from . import db, tasks
from .adapters.base import parse_date, raw_job
from .config import BOARDS
from .normalize import normalize
from .store import close_stale_board_jobs, upsert

log = logging.getLogger("boards")
SNIPPET = 1500
MAX_RESULTS = 300
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?:\+?\d[\d\s().-]{8,}\d)")
_LOCKS = {b: asyncio.Lock() for b in BOARDS}  # one scrape per board at a time -> fewer blocks

INDEED_COUNTRY = {"IN": "india", "US": "usa", "GB": "uk", "CA": "canada", "AU": "australia", "DE": "germany",
                  "FR": "france", "SG": "singapore", "AE": "united arab emirates", "NL": "netherlands", "IE": "ireland"}


def _val(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) or str(v) in ("nan", "NaT", "None") else v


def _scrape(board: str, q: str, location: str, country_code: str | None, hours_old: int | None, results: int):
    from jobspy import scrape_jobs  # heavy import (pandas) — only inside the worker thread
    kw = dict(site_name=[board], search_term=q, location=location or None, results_wanted=results,
              hours_old=hours_old, verbose=0, description_format="markdown")
    if board == "linkedin":
        kw["linkedin_fetch_description"] = True
    if board == "indeed":
        kw["country_indeed"] = INDEED_COUNTRY.get(country_code or "", "usa")
    df = scrape_jobs(**kw)
    return df.to_dict("records") if df is not None else []


async def run_board(task: dict):
    p = task["payload"]
    board = p["board"]
    flag = await db.fetchone("SELECT enabled FROM feature_flags WHERE key=%s", board)
    if not (flag and flag["enabled"]):
        return await tasks.finish(task["id"], False, f"{board} is disabled by admin")
    await tasks.progress(task["id"], phase="searching", board=board)
    try:
        async with _LOCKS[board]:
            rows = await asyncio.to_thread(_scrape, board, p["q"], p.get("location", ""), p.get("country_code"),
                                           p.get("hours_old"), min(int(p.get("results", 100)), MAX_RESULTS))
    except Exception as e:  # noqa: BLE001 — jobspy raises varied errors; 429/403 = blocked
        msg = f"{type(e).__name__}: {e}"[:400]
        blocked = any(s in msg for s in ("429", "403", "blocked", "captcha", "Too Many"))
        await db.execute("INSERT INTO scrape_runs (task_id, adapter, finished_at, blocked, error) VALUES (%s,%s,now(),%s,%s)",
                         task["id"], board, blocked, msg)
        return await tasks.finish(task["id"], False, ("Source temporarily blocked us. " if blocked else "") + msg)

    out = []
    for r in rows:
        r = {k: _val(v) for k, v in r.items()}
        desc = _PHONE.sub("[phone removed]", _EMAIL.sub("[email removed]", r.get("description") or ""))
        raw = raw_job(
            external_id=r.get("id") or r.get("job_url"), title=r.get("title") or "", url=r.get("job_url"),
            apply_url=r.get("job_url_direct") or r.get("job_url"), company_name=r.get("company"),
            description=desc, location_raw=r.get("location"), country_hint=p.get("country_code") if not r.get("location") else None,
            remote_hint=bool(r.get("is_remote")) or None, employment_type=r.get("job_type"),
            posted_at=parse_date(str(r["date_posted"])) if r.get("date_posted") else None,
            salary_min=r.get("min_amount"), salary_max=r.get("max_amount"), salary_currency=r.get("currency"),
            salary_period=r.get("interval"), exp_hint=r.get("experience_range") or r.get("job_level"),
        )
        if not raw["title"]:
            continue
        row = normalize(raw, board)
        row["company_id"] = None
        row["description"] = desc[:SNIPPET]  # snippet only; full text lives on the source (link back)
        out.append(row)

    async with db.pool.connection() as conn:
        ins, upd = await upsert(conn, out)
        await close_stale_board_jobs(conn)
    await db.execute("INSERT INTO scrape_runs (task_id, adapter, finished_at, complete, fetched, inserted, updated) "
                     "VALUES (%s,%s,now(),true,%s,%s,%s)", task["id"], board, len(out), ins, upd)
    await tasks.finish(task["id"], True, phase="done", found=len(out), inserted=ins, updated=upd)
