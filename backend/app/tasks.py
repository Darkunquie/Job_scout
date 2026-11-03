"""Postgres-backed task queue (FOR UPDATE SKIP LOCKED). No Redis needed at this scale."""
import json

from . import db

HIGH, LOW = 10, 0


async def enqueue(kind: str, payload: dict, user_id: int | None = None, priority: int = HIGH) -> int:
    row = await db.fetchone(
        "INSERT INTO scrape_tasks (kind, payload, user_id, priority) VALUES (%s, %s, %s, %s) RETURNING id",
        kind, json.dumps(payload), user_id, priority)
    return row["id"]


async def active_company_task(company_id: int) -> int | None:
    row = await db.fetchone(
        "SELECT id FROM scrape_tasks WHERE kind='company' AND status IN ('queued','running') "
        "AND (payload->>'company_id')::bigint = %s ORDER BY id DESC LIMIT 1", company_id)
    return row and row["id"]


async def promote(task_id: int, user_id: int | None):
    """A user asked for this scrape, so lift the pending refresh out of the background queue.

    Without this, clicking Scrape now on a company the scheduler already queued inherits LOW
    priority and waits behind every other refresh.
    """
    await db.execute(
        "UPDATE scrape_tasks SET priority = GREATEST(priority, %s), user_id = COALESCE(user_id, %s), "
        "run_after = LEAST(run_after, now()) "  # a click overrides a scheduled back-off: one try, now
        "WHERE id = %s AND status = 'queued'", HIGH, user_id, task_id)


async def claim(kinds: tuple[str, ...], min_priority: int = -1) -> dict | None:
    return await db.fetchone("""
        UPDATE scrape_tasks SET status='running', locked_at=now(), attempts=attempts+1
        WHERE id = (SELECT id FROM scrape_tasks WHERE status='queued' AND run_after <= now()
                      AND kind = ANY(%s) AND priority >= %s
                    ORDER BY priority DESC, id FOR UPDATE SKIP LOCKED LIMIT 1)
        RETURNING *""", list(kinds), min_priority)


async def progress(task_id: int, **p):
    await db.execute("UPDATE scrape_tasks SET progress = progress || %s::jsonb, locked_at=now() WHERE id=%s",
                     json.dumps(p, default=str), task_id)


async def finish(task_id: int, ok: bool, error: str | None = None, **p):
    await db.execute(
        "UPDATE scrape_tasks SET status=%s, error=%s, finished_at=now(), progress = progress || %s::jsonb WHERE id=%s",
        "done" if ok else "error", error, json.dumps(p, default=str), task_id)


async def requeue_stale(minutes: int = 20):
    """Worker crashed mid-task -> heartbeat (locked_at) goes stale -> retry up to 3 attempts."""
    await db.execute("""
        UPDATE scrape_tasks SET status = CASE WHEN attempts >= 3 THEN 'error' ELSE 'queued' END,
               error = CASE WHEN attempts >= 3 THEN 'worker timeout' ELSE error END
        WHERE status='running' AND locked_at < now() - make_interval(mins => %s)""", minutes)
