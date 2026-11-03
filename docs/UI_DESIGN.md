# JobScout — UI / UX Design

Status: draft v1 (2026-10-31). Frontend is built **after** the backend. Visual mockups (Stitch MCP + shadcn MCP) get generated at the start of the frontend phase from this spec.

---

## 1. What the references tell us

| Reference | What works | Take for JobScout |
|---|---|---|
| **HiringCafe** (ATS-sourced aggregator, closest to us) | Users praise very granular filters (experience, salary, schedule, …) and a clean, uncluttered list that puts the job first. Criticism: "rough around the edges", learning curve. AI summary per job. | Granular filters **but** grouped + collapsible so it's not overwhelming. Job-first cards. Short auto-summary line (rules-based). |
| **Otta / Welcome to the Jungle** | Clean, well-organised sections; tech stack shown as tags on each job makes scanning fast. Complaint: many jobs lack salary. | Skill tags on every card. Show salary when present, "Not disclosed" chip otherwise + filter to include/exclude undisclosed. |
| **Simplify** | Save a filter combination and revisit it. | "Saved views" (no alerts — dropped). |
| **Job-board UX guides** (Jobboardly, Niceboard, ux-patterns) | Start with all results unfiltered; show active filters as a summary beside results; left-column collapsible facets on desktop; on mobile, sticky filter chips that open a bottom sheet; filter by seniority, skills, location, company size, remote. | Exactly this layout. |
| **Stack Overflow Jobs case study** | Search + filter must stay visible while scrolling long lists. | Sticky search bar + sticky filter rail. |

Gap: no published research found on list/detail split view for job boards specifically — we use it anyway (Gmail/LinkedIn-style pattern, proven for scanning many items).

Sources:
- [HiringCafe Review 2026 — Jobright](https://jobright.ai/blog/hiringcafe-review-2026-features-pros-cons-and-alternatives/)
- [HiringCafe review — Scoutify](https://scoutify.com/blog/hiringcafe-review)
- [HiringCafe — Trustpilot](https://dk.trustpilot.com/review/hiring.cafe)
- [r/hiringcafe feature requests](https://cal1.lr.ggtyler.dev/r/hiringcafe/comments/1j2tziz/march_feature_request_thread_help_shape_hiringcafe)
- [Welcome to the Jungle (Otta) — Trustpilot](https://ie.trustpilot.com/review/otta.com?page=2)
- [Otta — Capterra](https://www.capterra.co.uk/software/1036497/otta)
- [Searching and Filtering Jobs on Simplify](https://help.simplify.jobs/articles/8339467-searching-and-filtering-jobs-on-simplify)
- [Best Practices for Job Search Design — Jobboardly](https://jobboardly.com/blog/best-practices-for-job-search-design)
- [Job board design: what works 2025 — Jobboardly](https://www.jobboardly.com/blog/job-board-design-what-works-2025)
- [Job seeker UX best practices — Niceboard](https://niceboard.co/learn/marketing/job-seeker-ux-best-practices-job-board)
- [Search results pattern — ux-patterns-for-developers](https://skills.sh/thedaviddias/ux-patterns-for-developers/search-results)
- [Case study: Job Search at Stack Overflow](https://medium.com/swlh/case-study-job-search-at-stack-overflow-ba63f417be1d)

Caveat: most sources are vendor blogs/reviews, not formal usability studies.

---

## 2. Design direction

- **Feel:** data tool, not a marketing site. Dense but calm — think Linear / Vercel dashboard, not a job-ad portal.
- **Theme:** light + dark. Neutral zinc base, one accent (indigo `#4F46E5`), semantic colours for status (green = new, amber = blocked/warning, rose = closed/error).
- **Type:** Inter (UI), JetBrains Mono (counts, IDs, URLs).
- **Radius 8px**, 1px borders, almost no shadows.
- **Components:** shadcn/ui + TanStack Table + lucide icons.
- **Accessibility:** keyboard nav in list (`j/k` move, `Enter` open, `s` save, `/` focus search), focus rings, 4.5:1 contrast.

---

## 3. Screens

### 3.1 Login (invite-only)
Email + password. "Have an invite? Set password" via token link. No signup.

### 3.2 Onboarding — region picker (first login, editable later)
```
Where do you want jobs from?
 ( ) India
 ( ) Specific countries   [ multi-select with search: 🇺🇸 US  🇩🇪 DE  🇦🇪 AE … ]
 ( ) All countries
 [x] Include remote jobs   scope: ( ) Anywhere ( ) India ( ) My countries
                                          [Continue]
```

### 3.3 Main — Jobs workspace (the core screen)
```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ◆ JobScout   [ 🔍 Search title, company, skill…  / ]   Region: India ▾  👤  │
├─────────────────────────────────────────────────────────────────────────────┤
│ ┌ SCRAPE BAR ───────────────────────────────────────────────────────────┐   │
│ │ Paste careers URLs (one per line)              Sources:               │   │
│ │ ┌───────────────────────────────────────┐      [●] Company portals    │   │
│ │ │ https://jobs.careers.microsoft.com/…  │      [○] LinkedIn  keyword[ ]│   │
│ │ │ https://boards.greenhouse.io/okta     │      [○] Naukri            │   │
│ │ └───────────────────────────────────────┘      [○] Indeed            │   │
│ │ ✓ Microsoft · Eightfold   ✓ Okta · Greenhouse  [○] Workday           │   │
│ │ [ ⬆ CSV ]                                        [ Scrape now ▶ ]     │   │
│ │ ▓▓▓▓▓▓▓▓░░░ Microsoft 812/1,340 · Okta ✓ 214 jobs (37 new)            │   │
│ └───────────────────────────────────────────────────────────────────────┘   │
├──────────────┬───────────────────────────────────┬──────────────────────────┤
│ FILTERS      │ 2,184 jobs · India + Remote        │ JOB DETAIL              │
│ Active:      │ [Remote ×][0–2 yrs ×][Python ×]    │ Senior Data Engineer    │
│ [Clear all]  │ Sort: Newest ▾  Match ▾  [⬇ Excel] │ Microsoft · Hyderabad   │
│              │ ─────────────────────────────────  │ 🟢 NEW · Hybrid · 5–8y  │
│ ▾ Location   │ ● Senior Data Engineer      NEW    │ ₹38–52 L/yr             │
│   Country    │   Microsoft · Hyderabad · Hybrid   │ Match 82% ▓▓▓▓▓▓▓▓░     │
│   City       │   Python  Spark  Azure   ₹38–52L   │  ✓ Python ✓ Spark       │
│   Remote     │   2h ago · Company portal  82%     │  ✗ Kafka                │
│ ▾ Work type  │ ─────────────────────────────────  │ Sources: Portal LinkedIn│
│ ▾ Experience │ ○ Backend Engineer                 │ [Apply ↗] [☆ Save]      │
│ ▾ Posted     │   Okta · Bengaluru · Remote-IN     │ [+ Tracker]             │
│ ▾ Salary     │   Java  AWS        Not disclosed   │ ─────────────           │
│ ▾ Skills     │   1d ago · Greenhouse       64%    │ Description…            │
│ ▾ Company    │ ...                                │                         │
│ ▾ Source     │ [ Load more ]                      │                         │
│ ▾ Visa       │                                    │                         │
│ [Save view]  │                                    │                         │
└──────────────┴───────────────────────────────────┴──────────────────────────┘
```
- **Empty state (no URL yet):** list shows the shuffled **default feed** with a banner: "Showing popular companies. Paste a careers URL above to scrape a specific company."
- URL box detects ATS **as you paste** (chip per URL: ✓ detected / ⚠ unknown → will use smart mode / ✗ invalid).
- Source toggles = scrape trigger + view filter. LinkedIn/Naukri/Indeed reveal a keyword input; disabled with tooltip if admin flag off.
- Progress: one row per running task, live via SSE; collapses to a summary toast when done.
- **Table/Card toggle:** cards by default; dense table mode (TanStack) for power users with column chooser.
- Badges: `NEW` (first seen < 24h), `CLOSED` (greyed, hidden by default), `REPOSTED ×3`, source icons.

### 3.4 Filters (all from spec)
| Group | Controls |
|---|---|
| Location | Country multi-select (with "All"), City search, Remote: Any / Remote only / Hybrid / On-site, Remote scope |
| Work type | Full-time, Part-time, Internship, Contract, Temporary, Apprenticeship, Graduate program |
| Experience | Fresher, 0–2, 3–5, 5–8, 8+ ; min/max years inputs |
| Posted | 24h, 3d, 7d, 14d, 30d, any |
| Salary | INR/yr range slider; include undisclosed toggle |
| Skills | tag picker (top skills + search) |
| Company | include / exclude multi-select; company size |
| Source | Company portal, LinkedIn, Naukri, Indeed, per-ATS |
| Visa | Sponsorship offered |
| Status | Active (default), include closed |
Facet counts next to every option. Mobile: chips row + bottom sheet.

### 3.5 My companies
Table of companies user added: name, ATS, jobs count, last scraped, status (OK / error / unsupported / blocked), [Refresh] [Remove]. Bulk add.

### 3.6 Resume match
Upload PDF/DOCX → extracted skills shown as editable chips → "Sort jobs by match" enabled everywhere.

### 3.7 Tracker
Kanban: Saved → Applied → Interview → Offer → Rejected. Drag cards. Notes per card. Export.

### 3.8 Admin
- **Users:** invite (copy link), role, active, daily quota.
- **Feature flags:** Workday, LinkedIn, Naukri, Indeed.
- **Seed companies:** manage default-feed list.
- **Scraper health:** per adapter/board: success %, blocked count, last run, recipes needing attention (edit recipe JSON).
- **Runs log.**

---

## 4. Mobile
Single column: search + region sticky → scrape box collapsed into "+ Add URLs" button → chips row → job cards → tap opens full-screen detail sheet.

---

## 5. Frontend build plan (after backend)
1. Generate screen mockups with **Stitch MCP** from §3 (workspace, onboarding, admin, tracker) → review with client.
2. Pull components via **shadcn MCP** (data-table, sheet, command, multi-select, slider, badge, tabs, toast, kanban).
3. 21st-magic MCP — currently not authenticated (API key missing); re-auth if we want its component variants.
4. Build Next.js against the FastAPI backend's OpenAPI.
