import os

# APP_ENV=production refuses the dev defaults below: a deploy that forgot its .env must not boot
# with a public JWT secret and a known admin password.
PRODUCTION = os.environ.get("APP_ENV", "development") == "production"
_DEV = {
    "DATABASE_URL": "postgresql://jobscout:jobscout@localhost:5435/jobscout",
    "JWT_SECRET": "dev-only-change-me",
    "ADMIN_EMAIL": "admin@jobscout.local",
    "ADMIN_PASSWORD": "admin12345",
}


def _secret(name: str, min_len: int = 0) -> str:
    v = os.environ.get(name)
    if not PRODUCTION:
        return v or _DEV[name]
    if not v or v == _DEV[name] or len(v) < min_len:
        raise SystemExit(f"{name} must be set in production" + (f" (min {min_len} chars)" if min_len else ""))
    return v


DATABASE_URL = _secret("DATABASE_URL")
JWT_SECRET = _secret("JWT_SECRET", 32)
ADMIN_EMAIL = _secret("ADMIN_EMAIL")
ADMIN_PASSWORD = _secret("ADMIN_PASSWORD", 12)
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")
# Secure cookies need HTTPS; on by default in production, off for http://localhost.
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1" if PRODUCTION else "0") == "1"

USER_AGENT = os.environ.get("USER_AGENT", "JobScoutBot/0.1 (+contact: admin@jobscout.local)")
REFRESH_MINUTES = 60
REFRESH_BATCH = 15      # companies enqueued per 5-minute scheduler tick
WORKER_SLOTS = 4
# Wall clock per background scrape. One tenant must not hold a slot while the queue waits behind it;
# what it read by then is saved, the run is marked partial, and nothing is closed on it.
TASK_SECONDS = int(os.environ.get("TASK_SECONDS", 45 * 60))
BOARDS = ("linkedin", "naukri", "indeed")

# Local LLM (Ollama). Optional: with it off, Tier 4 and field enrichment simply never run.
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:3b")
LLM_TIMEOUT = float(os.environ.get("LLM_TIMEOUT", "120"))
LLM_ENABLED = os.environ.get("LLM_ENABLED", "1") != "0"
