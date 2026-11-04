"""Worker process: claims queued tasks, runs scrapes, schedules hourly refreshes.

Run:  python -m app.worker
"""
import asyncio
import logging
import time

from . import db, tasks
from .embed import embed_jobs, embed_resume
from .llm import enrich_jobs
from .config import REFRESH_BATCH, REFRESH_MINUTES, WORKER_SLOTS
from .boards import run_board
from .runner import run_company

log = logging.getLogger("worker")
RUNNERS = {"company": run_company, "board": run_board, "resume": embed_resume}


async def schedule_refresh():
    """Enqueue companies older than REFRESH_MINUTES that someone still cares about.

    Capped per tick so adding 60 seed companies does not fire 60 scrapes at once; the oldest go first,
    which spreads the load across the hour on its own.
    """
    rows = await db.fetch("""
        SELECT c.id FROM companies c
        WHERE c.status NOT IN ('unsupported')
          AND NOT (c.status = 'blocked' AND c.last_scraped_at > now() - interval '30 minutes')
          AND (c.last_scraped_at IS NULL OR c.last_scraped_at < now() - make_interval(mins => %s))
          AND (c.is_seed OR EXISTS (SELECT 1 FROM user_companies uc WHERE uc.company_id = c.id
                                     AND uc.added_at > now() - interval '30 days'))
          AND NOT EXISTS (SELECT 1 FROM scrape_tasks t WHERE t.kind='company' AND t.status IN ('queued','running')
                          AND (t.payload->>'company_id')::bigint = c.id)
        ORDER BY c.last_scraped_at NULLS FIRST
        LIMIT %s""", REFRESH_MINUTES, REFRESH_BATCH)
    for r in rows:
        await tasks.enqueue("company", {"company_id": r["id"]}, priority=tasks.LOW)
    if rows:
        log.info("scheduled %d refreshes", len(rows))


async def run_task(task):
    try:
        await RUNNERS[task["kind"]](task)
    except Exception as e:  # noqa: BLE001
        log.exception("task %s crashed", task["id"])
        await tasks.finish(task["id"], False, f"{type(e).__name__}: {e}"[:500])


ALL_KINDS = ("company", "board", "resume")
LIGHT_KINDS = ("board", "resume")          # a resume upload must not queue behind a 20-minute company scrape
COMPANY_SLOTS = max(1, WORKER_SLOTS - 1)


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    await db.open_pool()
    inflight: dict[asyncio.Task, tuple[str, int]] = {}
    last_sched = 0.0
    log.info("worker started, %d slots", WORKER_SLOTS)
    while True:
        if time.monotonic() - last_sched > 300:
            await tasks.requeue_stale()
            await schedule_refresh()
            last_sched = time.monotonic()
        for t in [t for t in inflight if t.done()]:
            del inflight[t]
        if len(inflight) >= WORKER_SLOTS:
            await asyncio.sleep(0.5)
            continue
        companies = sum(k == "company" for k, _ in inflight.values())
        low = sum(k == "company" and p < tasks.HIGH for k, p in inflight.values())
        if companies >= COMPANY_SLOTS:
            task = await tasks.claim(LIGHT_KINDS)
        elif low >= COMPANY_SLOTS - 1:
            # Hourly refreshes of big tenants run for 20+ minutes. Keep the last company slot for
            # work a user actually asked for, or "Scrape now" sits in the queue behind them.
            task = await tasks.claim(ALL_KINDS, min_priority=tasks.HIGH)
        else:
            task = await tasks.claim(ALL_KINDS)
        if not task:
            # Idle time: embeddings first (match sort needs them), then LLM enrichment, which is
            # slow and must never compete with a scrape for CPU.
            if not await embed_jobs() and not await enrich_jobs():
                await asyncio.sleep(1)
            continue
        log.info("task %s %s %s", task["id"], task["kind"], task["payload"])
        inflight[asyncio.create_task(run_task(task))] = (task["kind"], task["priority"])


if __name__ == "__main__":
    import sys
    if sys.platform == "win32":  # psycopg async needs selector loop on Windows
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
