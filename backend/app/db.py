from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import DATABASE_URL

pool = AsyncConnectionPool(
    DATABASE_URL, open=False, min_size=1, max_size=10,
    kwargs={"row_factory": dict_row, "autocommit": True},
)


async def open_pool():
    await pool.open()
    async with pool.connection() as conn:
        await conn.execute((Path(__file__).parent / "schema.sql").read_text())


async def fetch(sql, *args):
    async with pool.connection() as conn:
        return await (await conn.execute(sql, args)).fetchall()


async def fetchone(sql, *args):
    async with pool.connection() as conn:
        return await (await conn.execute(sql, args)).fetchone()


async def execute(sql, *args):
    async with pool.connection() as conn:
        await conn.execute(sql, args)
