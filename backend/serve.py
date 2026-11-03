"""Start the API (Windows-safe: psycopg async needs the selector event loop)."""
import asyncio
import sys

import uvicorn

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config("app.api:app", host="127.0.0.1", port=8010, log_level="info"))
    asyncio.run(server.serve())
