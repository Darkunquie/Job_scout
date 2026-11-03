import type { RegionMode } from "./api";

export type Sort = "posted" | "match" | "salary" | "company" | "random";

export interface Filters {
  scope: "all" | "mine" | "default";
  region: RegionMode | "prefs";
  countries: string[];
  include_remote?: boolean;
  q: string;
  city: string;
  sources: string[];
  work_arrangement: string[];
  employment_type: string[];
  exp_level: string[];
  exp_min?: number;
  exp_max?: number;
  posted_days?: number;
  salary_min?: number;
  salary_max?: number;
  include_undisclosed_salary: boolean;
  skills: string[];
  companies: string[];
  exclude_companies: string[];
  visa?: boolean;
  include_closed: boolean;
  collapse_duplicates: boolean;
}

export const emptyFilters: Filters = {
  scope: "all",
  region: "prefs",
  countries: [],
  q: "",
  city: "",
  sources: [],
  work_arrangement: [],
  employment_type: [],
  exp_level: [],
  include_undisclosed_salary: true,
  skills: [],
  companies: [],
  exclude_companies: [],
  include_closed: false,
  collapse_duplicates: true,
};

const CSV_KEYS = [
  "countries",
  "sources",
  "work_arrangement",
  "employment_type",
  "exp_level",
  "skills",
  "companies",
  "exclude_companies",
] as const;

/** Only send what differs from the server's defaults — keeps URLs short and cache keys stable. */
export function toQuery(f: Filters, extra: Record<string, string | number | undefined> = {}): string {
  const p = new URLSearchParams();
  if (f.scope !== "all") p.set("scope", f.scope);
  if (f.region !== "prefs") p.set("region", f.region);
  for (const k of CSV_KEYS) {
    const v = f[k];
    if (v.length) p.set(k, v.join(","));
  }
  if (f.include_remote !== undefined) p.set("include_remote", String(f.include_remote));
  if (f.q.trim()) p.set("q", f.q.trim());
  if (f.city.trim()) p.set("city", f.city.trim());
  for (const k of ["exp_min", "exp_max", "posted_days", "salary_min", "salary_max"] as const) {
    const v = f[k];
    if (v !== undefined) p.set(k, String(v));
  }
  if (!f.include_undisclosed_salary) p.set("include_undisclosed_salary", "false");
  if (f.visa !== undefined) p.set("visa", String(f.visa));
  if (f.include_closed) p.set("include_closed", "true");
  if (!f.collapse_duplicates) p.set("collapse_duplicates", "false");
  for (const [k, v] of Object.entries(extra)) if (v !== undefined) p.set(k, String(v));
  return p.toString();
}

/** Chips shown above the result list, each removable. */
export function activeChips(f: Filters): { key: string; label: string; clear: (f: Filters) => Filters }[] {
  const out: { key: string; label: string; clear: (f: Filters) => Filters }[] = [];
  const listChip = (key: (typeof CSV_KEYS)[number], prefix = "") =>
    f[key].forEach((v) =>
      out.push({
        key: `${key}:${v}`,
        label: `${prefix}${v}`,
        clear: (x) => ({ ...x, [key]: x[key].filter((i) => i !== v) }),
      }),
    );

  listChip("countries");
  listChip("skills");
  listChip("work_arrangement");
  listChip("employment_type");
  listChip("exp_level");
  listChip("sources");
  listChip("companies");
  listChip("exclude_companies", "not ");
  if (f.city.trim()) out.push({ key: "city", label: f.city, clear: (x) => ({ ...x, city: "" }) });
  if (f.posted_days) out.push({ key: "posted", label: `last ${f.posted_days}d`, clear: (x) => ({ ...x, posted_days: undefined }) });
  if (f.exp_min !== undefined || f.exp_max !== undefined) {
    out.push({
      key: "exp",
      label: `${f.exp_min ?? 0}–${f.exp_max ?? "∞"} yrs`,
      clear: (x) => ({ ...x, exp_min: undefined, exp_max: undefined }),
    });
  }
  if (f.salary_min !== undefined) {
    out.push({ key: "salary", label: `₹${(f.salary_min / 1e5).toFixed(0)}L+`, clear: (x) => ({ ...x, salary_min: undefined }) });
  }
  if (f.visa !== undefined) out.push({ key: "visa", label: "sponsors visa", clear: (x) => ({ ...x, visa: undefined }) });
  if (f.include_closed) out.push({ key: "closed", label: "incl. closed", clear: (x) => ({ ...x, include_closed: false }) });
  return out;
}

export function countActive(f: Filters): number {
  return activeChips(f).length;
}
