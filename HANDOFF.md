# JobScout — handoff

You are continuing the JobScout project in this folder (`D:\jobscout`). Read `docs/SYSTEM_DESIGN.md` and `docs/UI_DESIGN.md` first.

## What JobScout is
Invite-only job aggregator. Admin invites users. A user picks a region (India / specific countries / all, with remote included), pastes 1..N company careers URLs (e.g. Microsoft, a Greenhouse board) and clicks Scrape, and the system scrapes every job from that portal. Separate toggles for LinkedIn / Naukri / Indeed scrape only that board, plus a Workday on/off switch. Before the user adds any URL, show a default feed from admin-managed seed companies. The website has filters + Excel export. Refresh is hourly. Budget: free, so no paid APIs, LLMs or proxies. **Local first**: build and test on this Windows machine; no deployment until the client approves.

## Stack
- Backend: Python 3.13, FastAPI (`backend/app/api.py`), async worker (`backend/app/worker.py`), Postgres 16 + pgvector.
- Queue = Postgres `FOR UPDATE SKIP LOCKED` (no Redis).
- Frontend: Next.js 15 (App Router) + Tailwind + TanStack Table + lucide, in `frontend/`.
- venv: `backend/.venv` (deps in `backend/requirements.txt`).

## How to run it locally

```
docker compose up -d db                                  # Postgres 16 + pgvector on :5435
cd backend && .venv\Scripts\python serve.py              # API on 127.0.0.1:8010, docs at /docs
cd backend && set PYTHONPATH=. && .venv\Scripts\python -m app.worker
cd frontend && npm run dev                               # UI on http://localhost:3000
```

Ports matter on this machine: **5433 and 8000 are taken by other projects**, so the DB is on **5435**
and the API on **8010** (`docker-compose.yml`, `app/config.py`, `serve.py`). Default admin is
`admin@jobscout.local` / `admin12345` (created on first API start, from `config.py`).

The frontend talks to `/api/*` and `next.config.ts` rewrites that to the Python service. Don't "simplify"
this into direct cross-origin calls: the session cookie is `SameSite=Lax`, so a cross-origin fetch
would silently drop it and every request would 401.

**Never run `next build` while `next dev` is running.** They share `.next/`, and the build overwrites
what dev is serving — every route starts returning 500. Stop dev first, or build with a separate
`distDir`. Recovery: kill dev, `rm -rf .next`, restart dev.

Windows note: `serve.py` and `app/worker.py` set the selector event loop because psycopg async needs
it. Playwright needs the opposite (Proactor), so `app/sniffer.py` runs the browser on its own loop in
a worker thread — don't "simplify" that away.

## Verified working against a real DB
- **Greenhouse** (Okta): 388 jobs, normalized, exported.
- **Eightfold / Microsoft**: 2,237 jobs with descriptions.
- **LinkedIn board** via JobSpy: 20 jobs, snippet only, emails/phones scrubbed.
- **Workday** (NVIDIA): lists and partitions by facet past the 2,000 cap; a full run takes ~15 min
  (2,684 details at 3 concurrent). Progress now streams during the listing phase.
- **Excel export**: `/api/jobs/export.xlsx` streams a formatted workbook (48 KB for 388 rows).
- **Filters + facets**: region/skills/source/experience/salary all return sane counts.
- **Resume match**: upload → skills + 384-dim embedding → `sort=match`. On a sample data-engineer
  résumé the top five hits were all data-engineering roles (0.77–0.79).
- **Tier 2** (JSON-LD + sitemap): extracts real postings (verified on an okta.com job page);
  sitemap discovery found 300 job URLs on okta.com.
- **Tier 3** (Playwright sniffer → recipe): learned the Workday CXS API from browser traffic alone,
  inferred `offset`/20 pagination, verified plain-HTTP replay, and replayed 80 unique jobs.
- **Unknown sites degrade correctly**: phonepe.com and swiggy.com end as `unsupported` with a reason
  (both are static/server-rendered — no job JSON to find). 403s become `blocked`, never retried hard.
- **59 seed companies** loaded (`app/seeds.py`), each URL probed live before being added. The hourly
  scheduler worked through the whole list on its own: **13,699 active jobs, all embedded**, 49 of 61
  companies `ok`.
- **Frontend**, QA'd in a real browser (login → region picker → workspace → scrape → detail → export):
  - Login, invite-accept, region picker.
  - Jobs workspace: scrape bar with live ATS detection chips, CSV import, board toggles, SSE progress
    rows; filter rail with facet counts; card and dense table views; detail pane with match estimate
    and matched/missing skills; Excel export; `j`/`k`/`Enter`//` keyboard nav.
  - My companies, Resume upload, Tracker (kanban), Admin (health, users/invites, seed list, flags).
  - Light + dark, and a phone layout with no horizontal overflow.
  - Verified live: pasting `jobs.lever.co/porter` detected Lever, scraped, and streamed
    "22 jobs · 22 new" into the list. Export returned a 199 KB xlsx with the right MIME type.

## Bugs found and fixed during this pass
1. `EmailStr` rejected the default admin's `.local` address — nobody could log in.
2. `UPSERT` assigned `posted_at` twice → every company scrape died with a SQL syntax error.
3. Workday/Eightfold crashed on a throttle page served with HTTP 200 (`get_json` now raises `Blocked`).
4. Workday returned postings with no `externalPath` → `KeyError` mid-run.
5. Two Workday tenants sharing a site name ("External": Intel and Micron) collapsed into **one**
   company row. `ats_slug` is now `tenant/site`; existing rows were migrated.
6. The sniffer's fallback id used Python's salted `hash()` — every scrape would have re-inserted the
   same jobs as new. Now sha1.
7. The sniffer mapped `locationsText` as a description (unanchored regex); keys now serve one field.
8. A résumé upload queued behind a 20-minute company scrape; the worker now reserves a slot for
   light tasks and embeds jobs while idle.
9. Blocked companies were retried every scheduler tick (design says back off 30 min) — now enforced.
10. `schedule_refresh` enqueued every due company at once; capped at `REFRESH_BATCH` (15) per tick.
11. Job-family words ("sales", "marketing") matched in any job description and crowded out real
    skills; those now match on title/department only.
12. UI, found during browser QA: the sort dropdown truncated to "New…", the country filter listed all
    249 countries alphabetically instead of the ones with jobs, the dense table rendered 77px rows and
    overflowed its pane, and the phone layout scrolled sideways.
13. **Region filter leaked foreign remote jobs.** An India feed showed "Account Executive DACH ·
    Remote, EMEA". Two causes, both fixed:
    - `normalize` stamped `remote_scope='ANY'` whenever no country parsed, so "Remote, EMEA" became
      "anywhere". It now reads a region token (`EMEA`, `APAC`, `LATAM`, `DACH`, `NORDICS`, …) and only
      falls back to `ANY` for genuinely global wording or no signal at all.
    - `_where` had an `OR j.countries = '{}'` escape hatch that let every unparsed remote job into
      every region. Removed; remote rows now join on `remote_scope` alone, expanded through
      `geo.scopes_for()` (India → `ANY, IN, APAC, ASIA`; Germany → `ANY, DE, DACH, EU, EUROPE, EMEA`).
    41 region-locked remote jobs left the India feed. The same job still appears under "All countries"
    and for a user watching Germany. Self-tests: `app.geo` (scope→country matching) and `app.normalize`
    (scope derivation, including the exact Supabase row).

## Backend fixes from the parallel session (2026-11-02 / 03)
Another session made these while the frontend work was going on. Read the files before touching them;
nothing here should be reverted.

- **`detect.py`**
  - `_own_host()`: an Eightfold white-label portal serves the API on the company's own host
    (`careers.qualcomm.com`), not `app.eightfold.ai` — the embedded link only names the domain.
    Rewrites the detection to `base=https://<that host>`, slug from the hostname.
  - `jobs_link()`: a careers *landing* page often has no jobs, only a "View jobs" / "Current openings"
    link one level down. `find_embedded()` follows it once, same-site only.
  - `ats_in_text()`: finds a known ATS board inside arbitrary text, including a site's own JSON feed
    with escaped slashes (`https:\/\/jobs.smartrecruiters.com\/SWIGGY\/...`).
- **`adapters/base.py`**: `405` on a GET is a throttle, not a method error — nginx answers
  "405 Not Allowed" when it is shedding bots (Qualcomm). Now raises `Blocked`, so the host backs off
  instead of the run dying. A genuine 405 only happens on POST, which is left alone.
- **`adapters/portals.py`**: when Eightfold's search API refuses *and nothing has been yielded yet*,
  fall back to Tier 2 over the robots-allowed sitemap (`/careers/job/<id>` pages carry JobPosting
  markup). If there is no sitemap either (Microsoft), re-raise the original `Blocked` — never
  `Unsupported`, or the company would be parked forever instead of retried.
- **`adapters/generic.py`**
  - `_repair()`: WordPress SEO plugins fill JobPosting fields with the site name (Intellias shipped
    title, region and description all as "Intellias"). A field equal to the company name is treated as
    missing, and the title is taken from `<h1>`.
  - `_CARD_LOCATIONS`: per-host reader for sites whose job pages carry no location at all — only the
    listing cards do (Intellias loads them 12 at a time over `admin-ajax.php`). Failure is logged, never
    fatal: locations are a bonus.
  - Partial-scrape guard: if more than 5% of sitemap job pages fail, raise `Blocked` **after** yielding
    what was read. Rows already saved stay; the run is marked incomplete so close-diff cannot close jobs
    whose pages were merely refused.
  - `jsonld()` takes `cap` and `job_path`, so the Eightfold fallback can use its own page budget.
- **`sniffer.py`**: follows the jobs link inside the browser too (JS-only landing pages render it
  client-side); if the captured feed is not a readable job list but references a known ATS, `learn()`
  returns that `Detected` and `generic()` switches the company onto that adapter permanently
  (Swiggy → SmartRecruiters). `--disable-blink-features=AutomationControlled` was removed — we identify
  as JobScoutBot and do not pretend otherwise.
- **`tasks.py` + `api.py`**: `tasks.promote()` lifts an already-queued company refresh to HIGH priority
  and `run_after = now()`, so Scrape now / Refresh on a company the scheduler had queued doesn't inherit
  LOW priority and wait behind every other refresh.

Result of those fixes: **Qualcomm 2,054, Intellias 110, PhonePe 532, Swiggy 182 jobs.**

Ollama + `qwen2.5:3b` are installed on this machine but **not wired in** on purpose. Only add an LLM
fallback if a real careers URL still ends `unsupported` after all three tiers.

## Known gaps / next steps
1. Facet counts for `employment_type` are mostly empty: most ATSs don't send the field and the regex
   only reads the title. Consider reading the description's first paragraph.
2. `FX_INR` in `app/normalize.py` is a static snapshot; swap for frankfurter.app if salary sorting
   needs precision.
3. Cross-source dedupe is exact-key only (company+title+country+city). Fuzzy matching is phase 2.
4. The sniffer only learns JSON APIs. Sites that server-render their job lists fall through to
   `unsupported`; an HTML-table recipe mode would cover them.
5. Seed URLs rot. Re-run `python -m app.seeds` (one cheap request per company) and prune what fails.
6. Not re-tested since the fixes: a full NVIDIA Workday refresh end-to-end, and Microsoft's
   "skip details for known jobs" fast path.
7. Workday runs are slow — a tenant past the 2,000 cap partitions by facet, then fetches one detail
   page per job, so a big tenant takes 15–30 min. `companies.status` keeps the previous run's value
   until the current one finishes, which makes a healthy run look like a stuck failure. Check
   `scrape_tasks.progress->>'found'` before concluding anything is broken.
   (Resolved: the earlier `405 Method Not Allowed` with a doubled tenant, `/wday/cxs/citi/citi/2/jobs`,
   was a worker running the pre-`tenant/site` adapter against already-migrated slugs. If you see a
   doubled tenant again, the worker is on stale code — restart it.)
8. Drag-and-drop on the tracker: cards move with arrow buttons instead. Fine for now, and keyboard
   accessible, but the spec asks for drag.
9. Saved views (`docs/UI_DESIGN.md` §3.3) and the shortlist share-link UI are not built; the backend
   endpoints for shortlists exist.

## Self-tests
Every module with non-trivial logic has one. From `backend/`, with `PYTHONPATH=.`:
```
python -m app.detect ; python -m app.geo ; python -m app.normalize
python -m app.embed  ; python -m app.sniffer ; python -m app.adapters.generic
python -m app.seeds          # live: probes all 59 seed URLs, prints what to prune
python -m app.runner         # pure helpers (company naming from a hostname)
```
All of the above pass as of 2026-11-03. Two traps:
- `python -m app.worker` is **not** a self-test, it is the worker daemon. Running it "to check" starts a
  second worker competing for the same queue.
- `app.seeds` prints what to prune from one live request each, so a throttled host looks dead. On
  2026-11-03 it flagged `jobs.careers.microsoft.com`; that endpoint was answering **429**, not gone.
  Re-probe before deleting a seed.

## Rules
- Logged-out scraping only. Never bypass CAPTCHAs/logins. On 403/429, back off.
- Keep code lean, matching the existing style. Each module has an `if __name__ == "__main__"` assert
  self-test where logic is non-trivial.
- Build locally only; no deployment until the client approves.

## Layout (settled 2026-11-02)

The workspace uses the **original design from `docs/UI_DESIGN.md` §3.3**: top nav with text labels,
and the scrape box always open above the three panes.

```
┌────────────────────────────────────────────────┐
│ ◆ JobScout [search /] Jobs Companies Tracker … │  top-nav.tsx
├─────────────────────────┬─────────────────────┤
│ Paste careers URLs …      │ Sources: portals/LI │  scrape-bar.tsx
│ [CSV]      [Scrape now ▶] │ Naukri / Indeed      │
├─────────────────────────┴─────────────────────┤
│ Hugging Face ▓▓▓▓▓▓▓▓▓▓▓▓▓  6 jobs · 0 new  ✕ clear │  scrape-progress.tsx
├─────────┬────────────────────┬───────────────┤
│ FILTERS │ job list          │ job detail      │  filters-rail / job.tsx
└─────────┴────────────────────┴───────────────┘
```

Two alternatives were built and discarded (an icon rail, and a top nav with the scrape box collapsed
to one line). Only the shell differed, so switching again is mostly `app/(app)/layout.tsx` plus the
grid in `app/(app)/page.tsx`. Components are independent: `top-nav`, `scrape-bar`, `scrape-progress`,
`filters-rail`, `job`, `job-table`.

Worth keeping whatever the shell:

- **Progress is a separate component** (`ScrapeProgress`), not part of the scrape box. It renders
  between the box and the panes and streams over SSE until cleared. Progress state is in-memory, so
  a page reload clears the strip while the scrape keeps running on the worker.
- **The scrape box collapses on phones** behind an "Add URLs or job boards" toggle
  (`docs/UI_DESIGN.md` §4) and is always open from `lg` up.
- **Never wrap content in `<details>` just to group it.** `FacetList` did, with a hidden
  `<summary>`; a `<details>` without `open` hides its own children, so every facet group (work
  arrangement, work type, experience, skills, company, source) rendered empty and most of the
  filter rail was dead. Only `Group` and the "N more" expander should be `<details>`.
- **The detail pane and the detail sheet are mutually exclusive, decided in JS** (`useMediaQuery`,
  not a CSS class). Radix portals dialog content to `document.body`, so an `xl:hidden` wrapper does
  not hide it: at ≥1280px you got the pane *and* a popup showing the same job, and `JobDetailPane`
  mounted twice (two fetches per click). Keep the JS check if the breakpoint ever moves.

## QA results (pre-client pass, 2026-11-01)

Tested in a real browser as a **newly invited user** (`qa.tester@jobscout.test`), not just admin.
Screenshots in `.gstack/qa-reports/screenshots/`.

| # | Route / area | Check | Result | Fix |
|---|---|---|---|---|
| 1 | `/admin` → `/invite/[token]` | Admin creates invite, new user sets password | **fixed** | `EmailStr` rejected reserved TLDs, so an admin on `@jobscout.local` could not invite anyone on that domain. Invite email is now a shaped check, not deliverability. |
| 2 | `/invite/[token]` | Redirect to onboarding after accepting | pass | Earlier "no redirect" was browse reporting a stale URL during a Fast Refresh storm; retested clean. |
| 3 | `/onboarding` | India / countries / all + remote scope | pass | Continue stays disabled until a country is picked; chosen countries stay pinned while searching. |
| 4 | `/` scrape bar | Detect chips for Greenhouse, Lever, Workday, Eightfold, unknown | pass | All five correct, incl. "smart mode" for an unknown host. |
| 5 | `/` scrape bar | SSE progress updates live | **fixed** | `useTaskStream` guarded opens with a ref; StrictMode's effect→cleanup→effect left every stream closed, so rows sat at "0 found". Now opens and closes exactly the streams the effect owns. |
| 6 | worker | "Scrape now" waits behind hourly refreshes | **fixed** | Long Workday refreshes held every company slot. One slot is now reserved for user-priority work. |
| 7 | worker | Clicking a company the scheduler already queued | **fixed** | The user inherited the background task's LOW priority and waited indefinitely. `tasks.promote()` lifts it to user priority. |
| 8 | `/` board toggles | LinkedIn / Naukri / Indeed one at a time | pass | Toggle filters the view to that source and queues only that board (100 LinkedIn rows, zero Naukri/Indeed). |
| 9 | `/admin` flags | Workday off → Workday URL refused | pass | Returns `workday_disabled` + "Enable Workday to scrape this portal". |
| 10 | `/api/jobs` | Facet counts vs list total | **fixed** | Facets dropped the NULL bucket, hiding 8,736 jobs (work arrangement), 6,649 (employment type), 2,490 (experience). All four single-valued facets now sum exactly to the total. |
| 11 | `/api/jobs` | `employment_type` filter | **fixed** | No "Unspecified" option and no NULL branch, so 44% of jobs were unreachable. |
| 12 | normalizer | Salary period | **fixed** | "$5,690 - $11,210 **per month**" stored as `/year` — 12x low, wrecking salary sort and filter. Period now read from the words after the amount; 92 rows corrected. |
| 13 | region filter | "Remote Canada" in an India feed | **fixed** | `parse_location` only split on punctuation, so bare "Remote &lt;Country&gt;" lost the country and fell back to remote-anywhere. India+Python+Remote went 132 → 48. |
| 14 | geo | US state vs country name | **fixed** | "Remote - Georgia, USA" was tagged country GE. US-context detection added; 58 → 3 rows, and the 3 left are genuinely ambiguous. |
| 15 | geo | Regression from fix #13 | **fixed** | Stripping "Remote" dropped a token and made "Remote, AZ" read as Azerbaijan. Token count is now preserved. |
| 16 | `/api/jobs/export.xlsx` | Export matches filtered list | pass | 132→132, then 48→48 after the region fix. Correct MIME, headers, no excluded rows. |
| 17 | `/resume` | PDF + DOCX upload, match sort | pass | Both extract, 13 skills, auto-polls to "ready", `sort=match` tops out at 0.825 on matching roles, matched/missing shown in detail. |
| 18 | `/tracker` | Saved → applied → interview, survives reload | pass | Card persisted in Interview after a full reload. |
| 19 | `/s/[token]` | Shortlist opens logged-out | **fixed** | The API advertised a share URL with no frontend route (404). Public read-only page added; verified with no session and with a bad token. |
| 20 | `/api/scrape/urls` | Bad and hostile URLs | **fixed** | SSRF guard already blocked `localhost`, `169.254.169.254` and `ftp://`; a typo leaked `[Errno 11001] getaddrinfo failed`. Now "Could not find &lt;host&gt; — check the address". Self-tests added. |
| 21 | `/` | Empty filter state | pass | "No jobs match these filters" with a recovery hint. |
| 22 | all routes | API down | **fixed** | Rendered a completely blank page. Now shows "Can't reach the JobScout backend" with a working Retry. |
| 23 | all routes | 375px phone width | **fixed** | `/admin` overflowed (456px) because the 4-tab strip could not wrap. Tab strip scrolls; no page overflow on any route. |
| 24 | all routes | Dark mode | pass | Zinc/indigo tokens resolve correctly in dark on every page. |
| 25 | `/admin` | Deactivating a user | pass | Live session drops to 401 "Account disabled" on the next request. |
| 26 | `/admin` | Health, users, seeds, flags | pass | 61 companies, 59 seeds, per-adapter success rates. |

Not covered: a runs-log tab (the `/api/admin/runs` endpoint exists, no UI), drag-and-drop on the
tracker (arrow buttons instead), and saved views.

Backfills applied to existing rows so the fixes show without waiting for a re-scrape: 47 remote
scopes, 92 salary periods, 63 locations.
