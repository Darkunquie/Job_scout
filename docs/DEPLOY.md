# Deploying JobScout

One VPS (tested target: Hostinger KVM 2 — 2 vCPU, 8 GB RAM, no GPU), everything in Docker.

## What runs

| Service | Image | Memory (approx.) | Notes |
|---|---|---|---|
| `db` | pgvector/pgvector:pg16 | 1 GB | data in volume `pgdata` |
| `api` | built from `backend/` | 0.4 GB | FastAPI; applies `schema.sql` on start; `/api/healthz` |
| `worker` | same image as `api` | 1 GB | scraper + Playwright Chromium + embeddings |
| `web` | built from `frontend/` | 0.3 GB | Next.js; the only published port; proxies `/api/*` to `api` |
| `ollama` | ollama/ollama | 2.5 GB | local LLM on CPU, capped to 1 core |
| `ollama-pull` | ollama/ollama | — | one-shot: downloads the model, then exits |
| `backup` | pgvector/pgvector:pg16 | — | nightly `pg_dump`, 7 days kept in volume `backups` |

## Option A — Coolify (recommended)

1. Install Coolify on the VPS (`curl -fsSL https://cdn.coollabs.io/coolify/install.sh | bash`), open `http://<VPS-IP>:8000`, create the admin account.
2. Point your domain's DNS `A` record at the VPS IP.
3. Coolify → New resource → Public/Private GitHub repo → this repo → Build pack **Docker Compose** → compose file `docker-compose.prod.yml`.
4. Environment tab: fill in every variable from `.env.example` (`openssl rand -hex 32` for secrets).
5. On the `web` service set the domain (`https://jobs.yourdomain.com`), port 3000. Coolify issues the HTTPS certificate.
6. Deploy. First boot downloads the model (~2 GB) and the embedding model (~130 MB).
7. Sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`, then Admin → Seed companies → **Load shipped list**.

## Option B — plain Docker Compose

```bash
git clone <repo> jobscout && cd jobscout
cp .env.example .env && nano .env
docker compose -f docker-compose.prod.yml up -d --build
```

Then put HTTPS in front of `127.0.0.1:3000` (the port is bound to loopback only) (Caddy: `jobs.yourdomain.com { reverse_proxy localhost:3000 }`).

## Operations

```bash
docker compose -f docker-compose.prod.yml ps                       # health of every service
docker compose -f docker-compose.prod.yml logs -f worker           # scraper log
docker compose -f docker-compose.prod.yml up -d --build            # deploy a new version
docker compose -f docker-compose.prod.yml exec backup ls /backups  # list backups
```

Restore a backup:

```bash
docker compose -f docker-compose.prod.yml exec backup sh -c 'pg_restore --clean --if-exists -d jobscout /backups/jobscout-YYYY-MM-DD.dump'
```

Copy backups off the server from time to time; a backup on the same disk does not survive losing the disk.

## The local LLM on a CPU-only server

- Tier 4 (reading a page nothing else could read) is rare; ~30–60 s per page on CPU is fine.
- Enrichment runs only while the worker is idle; on CPU expect ~100–200 jobs/hour instead of thousands.
- Ollama is capped to one core (`cpus: 1.0`) so scraping always has the other.
- `LLM_ENABLED=0` switches both off; everything else keeps working.

## Security notes

- With `APP_ENV=production` (set by the compose file) the API refuses to start without real `JWT_SECRET` (32+ chars), `ADMIN_PASSWORD` (12+ chars), `ADMIN_EMAIL` and `DATABASE_URL`.
- Session cookies are `Secure` (HTTPS only). Set `COOKIE_SECURE=0` only for a temporary test over plain `http://IP`.
- Sign-in locks an account for 15 minutes after 10 failed attempts.
- Only `web` is published. The database, API and Ollama are reachable only inside the Docker network.
- The admin password in `.env` is used once, to create the first admin on an empty database. Changing it later does not change the existing account.
