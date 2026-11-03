// Thin client over the FastAPI backend. Requests go to /api/* and Next rewrites them to the
// Python service, so the session cookie stays same-origin.

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

function detailOf(body: unknown, fallback: string): string {
  if (typeof body !== "object" || body === null) return fallback;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of {loc, msg}
  if (Array.isArray(detail)) {
    const msgs = detail.map((d) => (d as { msg?: string }).msg).filter(Boolean);
    if (msgs.length) return msgs.join("; ");
  }
  return fallback;
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`/api${path}`, {
    credentials: "include",
    headers: init.body instanceof FormData ? undefined : { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    let body: unknown = null;
    try {
      body = await res.json();
    } catch {
      /* non-JSON error page */
    }
    throw new ApiError(detailOf(body, `Request failed (${res.status})`), res.status);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  get: <T>(path: string) => req<T>(path),
  post: <T>(path: string, body?: unknown) =>
    req<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    req<T>(path, { method: "PUT", body: body === undefined ? undefined : JSON.stringify(body) }),
  patch: <T>(path: string, body?: unknown) =>
    req<T>(path, { method: "PATCH", body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => req<T>(path, { method: "DELETE" }),
  upload: <T>(path: string, file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<T>(path, { method: "POST", body: fd });
  },
};

// ───────────────────────── types ─────────────────────────
export type RegionMode = "india" | "countries" | "all";

export interface Prefs {
  region_mode: RegionMode;
  countries: string[];
  include_remote: boolean;
  remote_scope: string;
  boards: Record<string, boolean>;
}

export interface Me {
  id: number;
  email: string;
  role: "admin" | "user";
  daily_quota: number;
  prefs: Prefs | null;
  onboarded: boolean;
}

export interface Job {
  id: number;
  source: string;
  company_name: string | null;
  title: string;
  url: string | null;
  apply_url: string | null;
  department: string | null;
  location_raw: string | null;
  country_code: string | null;
  countries: string[];
  city: string | null;
  is_remote: boolean;
  work_arrangement: string | null;
  employment_type: string | null;
  exp_min: number | null;
  exp_max: number | null;
  exp_level: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: string | null;
  salary_inr_year: number | null;
  skills: string[];
  visa_sponsorship: boolean | null;
  posted_at: string | null;
  first_seen_at: string;
  status: "active" | "closed";
  is_new: boolean;
  also_on: string[] | null;
  match_score: number | null;
}

export interface JobDetail extends Job {
  description: string | null;
  skills_matched?: string[];
  skills_missing?: string[];
}

export interface JobPage {
  items: Job[];
  total: number;
  limit: number;
  offset: number;
}

export type Facet = { v: string; n: number };
export type Facets = Record<string, Facet[]>;

export interface Meta {
  countries: { code: string; name: string }[];
  work_arrangements: string[];
  employment_types: string[];
  exp_levels: string[];
  sources: string[];
}

export interface ScrapeResult {
  url: string;
  status: "queued" | "cached" | "added" | "invalid" | "unsupported" | "workday_disabled";
  message?: string;
  ats?: string;
  company_id?: number;
  company?: string | null;
  task_id?: number | null;
  job_count?: number;
}

export interface Task {
  id: number;
  kind: string;
  payload: Record<string, unknown>;
  status: "queued" | "running" | "done" | "error";
  progress: { phase?: string; found?: number; total?: number | null; inserted?: number; closed?: number };
  error: string | null;
}

export interface Company {
  id: number;
  name: string | null;
  careers_url: string;
  ats_type: string;
  status: string;
  last_scraped_at: string | null;
  last_error: string | null;
  job_count: number;
}

export interface Application {
  application_id: number;
  stage: "saved" | "applied" | "interview" | "offer" | "rejected";
  notes: string | null;
  updated_at: string;
}

/** `id` is the JOB id (LIST_COLS wins); the row id is `application_id`. */
export type ApplicationRow = Application & Job;

export interface Resume {
  id: number;
  filename: string;
  skills: string[];
  created_at: string;
  ready: boolean;
}

export interface Health {
  adapters: { adapter: string; runs: number; ok: number; blocked: number; last_run: string | null; success_pct: number | null }[];
  problem_companies: Company[];
  queue_24h: { status: string; n: number }[];
  totals: { active_jobs: number; all_jobs: number; companies: number };
}
