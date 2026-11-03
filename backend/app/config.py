import os

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://jobscout:jobscout@localhost:5435/jobscout")
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-only-change-me")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@jobscout.local")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin12345")
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "http://localhost:3000")

USER_AGENT = "JobScoutBot/0.1 (+contact: admin@jobscout.local)"
REFRESH_MINUTES = 60
REFRESH_BATCH = 15      # companies enqueued per 5-minute scheduler tick
WORKER_SLOTS = 4
BOARDS = ("linkedin", "naukri", "indeed")
