"""Job persistence: upsert, cross-source clustering, close-diff."""
from .config import BOARDS

COLS = ("source", "external_id", "company_id", "company_name", "url", "apply_url", "title", "department", "description",
        "location_raw", "country_code", "countries", "city", "is_remote", "remote_scope", "work_arrangement",
        "employment_type", "exp_min", "exp_max", "exp_level", "salary_min", "salary_max", "salary_currency",
        "salary_period", "salary_inr_year", "skills", "visa_sponsorship", "posted_at", "content_hash", "dedupe_key")
_UPDATABLE = [c for c in COLS if c not in ("source", "external_id", "posted_at")]  # posted_at has its own COALESCE below

UPSERT = f"""
INSERT INTO jobs ({", ".join(COLS)}) VALUES ({", ".join(["%s"] * len(COLS))})
ON CONFLICT (source, external_id) DO UPDATE SET
  {", ".join(f"{c} = EXCLUDED.{c}" for c in _UPDATABLE)},
  embedding = CASE WHEN jobs.content_hash IS DISTINCT FROM EXCLUDED.content_hash THEN NULL ELSE jobs.embedding END,
  posted_at = COALESCE(EXCLUDED.posted_at, jobs.posted_at),
  last_seen_at = now(), status = 'active', closed_at = NULL
RETURNING id, (xmax = 0) AS inserted
"""

CLUSTER = """
UPDATE jobs j SET cluster_id = c.cid
FROM (SELECT dedupe_key,
             COALESCE(min(id) FILTER (WHERE source <> ALL(%s)), min(id)) AS cid
      FROM jobs WHERE dedupe_key = ANY(%s) AND status = 'active' AND first_seen_at > now() - interval '30 days'
      GROUP BY dedupe_key) c
WHERE j.dedupe_key = c.dedupe_key AND j.status = 'active'
"""


async def upsert(conn, rows: list[dict]) -> tuple[int, int]:
    """Insert/update a batch. Returns (inserted, updated)."""
    if not rows:
        return 0, 0
    ins = upd = 0
    async with conn.transaction():
        for r in rows:
            row = await (await conn.execute(UPSERT, [r[c] for c in COLS])).fetchone()
            ins += row["inserted"]
            upd += not row["inserted"]
        await conn.execute(CLUSTER, (list(BOARDS), list({r["dedupe_key"] for r in rows})))
    return ins, upd


async def close_missing(conn, company_id: int, run_started) -> int:
    """Only call after a COMPLETE scrape: jobs not seen in this run are closed."""
    cur = await conn.execute(
        "UPDATE jobs SET status='closed', closed_at=now() WHERE company_id=%s AND status='active' AND last_seen_at < %s",
        (company_id, run_started))
    return cur.rowcount


async def close_stale_board_jobs(conn, days: int = 7) -> int:
    """Board results are search-based: absence != closed. Close only after N days unseen."""
    cur = await conn.execute(
        "UPDATE jobs SET status='closed', closed_at=now() WHERE source = ANY(%s) AND status='active' "
        "AND last_seen_at < now() - make_interval(days => %s)", (list(BOARDS), days))
    return cur.rowcount


async def touch(conn, source: str, external_ids: list[str]):
    """Mark unchanged jobs as seen in this run (keeps them out of close-diff)."""
    if external_ids:
        await conn.execute("UPDATE jobs SET last_seen_at=now() WHERE source=%s AND external_id = ANY(%s)",
                           (source, external_ids))
