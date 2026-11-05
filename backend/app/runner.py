"""Executes one scrape task end to end: fetch -> normalize -> upsert -> close-diff -> log."""
import asyncio
import logging
import re
import time

from . import db, tasks
from .adapters import ADAPTERS, Blocked, Unsupported
from .config import TASK_SECONDS
from .normalize import normalize
from .store import close_missing, touch, upsert

log = logging.getLogger("runner")
BATCH = 200


# Smart mode uses the hostname as the slug, so without this a company shows up as
# "Careers.Infor.Com" instead of "Infor".
_HOST_PREFIX = re.compile(r"^(?:www|careers?|jobs?|apply|talent|work|hiring|recruit(?:ing)?|join)\.", re.I)


def _pretty(slug: str) -> str:
    """Slug or hostname -> a human company name."""
    s = slug.strip("/")
    if "." in s and "/" not in s:
        s = _HOST_PREFIX.sub("", s).split(".")[0]
    return s.replace("-", " ").replace("_", " ").title()


if __name__ == "__main__":
    for raw, want in {"careers.infor.com": "Infor", "www.zoho.com": "Zoho", "jobs.example.co.uk": "Example",
                      "acme-corp": "Acme Corp", "some_company": "Some Company", "infor.com": "Infor"}.items():
        assert _pretty(raw) == want, (raw, _pretty(raw), want)
    print("runner OK")


async def run_company(task: dict):
    company_id = task["payload"]["company_id"]
    co = await db.fetchone("SELECT * FROM companies WHERE id=%s", company_id)
    if not co:
        return await tasks.finish(task["id"], False, "company deleted")
    if co["ats_type"] == "workday":
        flag = await db.fetchone("SELECT enabled FROM feature_flags WHERE key='workday'")
        if not (flag and flag["enabled"]):
            return await tasks.finish(task["id"], False, "Workday scraping is disabled by admin")

    adapter = ADAPTERS[co["ats_type"]]
    run = await db.fetchone("INSERT INTO scrape_runs (task_id, company_id, adapter) VALUES (%s,%s,%s) RETURNING id, started_at",
                            task["id"], company_id, co["ats_type"])
    known_rows = await db.fetch("SELECT external_id FROM jobs WHERE company_id=%s AND status='active' "
                                "AND description <> ''", company_id)
    extra = dict(co["ats_extra"], company=co["name"], company_id=company_id,
                 known={r["external_id"] for r in known_rows})
    touched: list[str] = []
    name = co["name"]
    fetched = ins = upd = 0
    batch: list[dict] = []

    async def on_progress(found, total):
        await tasks.progress(task["id"], found=found, total=total, phase="listing")

    deadline = time.monotonic() + TASK_SECONDS
    partial = False
    async with db.pool.connection() as conn:
        try:
            # Not `async for`: a tenant can spend the whole budget listing, before the adapter has
            # yielded once, so the clock has to run against each await rather than each row.
            rows = adapter(co["ats_slug"], extra, on_progress)
            while True:
                try:
                    raw = await asyncio.wait_for(anext(rows), timeout=deadline - time.monotonic())
                except StopAsyncIteration:
                    break
                except (TimeoutError, asyncio.CancelledError):
                    partial = True
                    log.warning("company %s hit the %d min cap — keeping %d rows, skipping close-diff",
                                company_id, TASK_SECONDS // 60, fetched)
                    await rows.aclose()
                    break
                fetched += 1
                if raw["touch_only"]:  # unchanged listing: skip detail fetch, just mark seen
                    touched.append(raw["external_id"])
                    continue
                if not name:
                    cn = raw["company_name"] or co["ats_slug"]
                    name = _pretty(cn) if cn == co["ats_slug"] else cn
                raw["company_name"] = name
                row = normalize(raw, co["ats_type"])
                row["company_id"] = company_id
                batch.append(row)
                if len(batch) >= BATCH:
                    i, u = await upsert(conn, batch)
                    ins, upd, batch = ins + i, upd + u, []
                    await tasks.progress(task["id"], phase="saving", saved=fetched, inserted=ins)
            i, u = await upsert(conn, batch)
            ins, upd = ins + i, upd + u
            await touch(conn, co["ats_type"], touched)
            # A run cut short never saw the whole board, so absence proves nothing: closing here would
            # retire every job the clock did not reach.
            closed = 0 if partial else await close_missing(conn, company_id, run["started_at"])
            status, ok, blocked = ("partial" if partial else "ok"), True, False
            err = f"stopped at the {TASK_SECONDS // 60} minute cap with {fetched} jobs read" if partial else None
        except Exception as e:  # noqa: BLE001 — record any failure, never crash the worker
            kind = "blocked" if isinstance(e, Blocked) else "unsupported" if isinstance(e, Unsupported) else "error"
            if kind == "error":
                log.exception("company %s failed", company_id)
            closed, status, ok, blocked = 0, kind, False, kind == "blocked"
            err = str(e)[:500] if kind != "error" else f"{type(e).__name__}: {e}"[:500]
            if batch:  # keep what we already parsed; never let salvage hide the real error
                try:
                    i, u = await upsert(conn, batch)
                    ins, upd = ins + i, upd + u
                except Exception:
                    log.exception("salvage upsert failed for company %s", company_id)

        if ok and not partial and fetched == 0 and (co["job_count"] or 0) > 5:
            status = "needs_attention"  # source used to have jobs, now empty -> probably changed
        await conn.execute(
            "UPDATE companies SET name=COALESCE(name,%s), status=%s, last_error=%s, last_scraped_at=now(), "
            "job_count=(SELECT count(*) FROM jobs WHERE company_id=%s AND status='active') WHERE id=%s",
            (name, status, err, company_id, company_id))
        await conn.execute(
            "UPDATE scrape_runs SET finished_at=now(), complete=%s, fetched=%s, inserted=%s, updated=%s, closed=%s, "
            "blocked=%s, error=%s WHERE id=%s", (ok, fetched, ins, upd, closed, blocked, err, run["id"]))
    await tasks.finish(task["id"], ok, err, phase="done", found=fetched, inserted=ins, updated=upd, closed=closed)
