/** Display helpers shared by the cards, the table and the detail pane. */

export function timeAgo(iso: string | null): string {
  if (!iso) return "—";
  const secs = (Date.now() - new Date(iso).getTime()) / 1000;
  if (secs < 90) return "just now";
  const mins = secs / 60;
  if (mins < 60) return `${Math.round(mins)}m ago`;
  const hours = mins / 60;
  if (hours < 24) return `${Math.round(hours)}h ago`;
  const days = hours / 24;
  if (days < 31) return `${Math.round(days)}d ago`;
  const months = days / 30.4;
  return months < 12 ? `${Math.round(months)}mo ago` : `${Math.round(months / 12)}y ago`;
}

const CURRENCY: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };

/** Keep the source currency — converting everything to rupees hides what the employer actually pays. */
export function salary(j: {
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string | null;
  salary_period: string | null;
}): string | null {
  const { salary_min: lo, salary_max: hi, salary_currency: cur, salary_period: per } = j;
  if (lo == null && hi == null) return null;
  const sym = CURRENCY[cur ?? ""] ?? (cur ? `${cur} ` : "");
  const unit = (n: number) => {
    if (cur === "INR" && n >= 1e5) return `${(n / 1e5).toFixed(n % 1e5 ? 1 : 0)}L`;
    if (n >= 1000) return `${Math.round(n / 1000)}k`;
    return String(Math.round(n));
  };
  const span = lo != null && hi != null && lo !== hi ? `${unit(lo)}–${unit(hi)}` : unit((lo ?? hi) as number);
  const suffix = per && per !== "year" ? `/${per === "hour" ? "hr" : per === "month" ? "mo" : per}` : "/yr";
  return `${sym}${span}${suffix}`;
}

export function experience(j: { exp_min: number | null; exp_max: number | null; exp_level: string | null }): string | null {
  if (j.exp_min != null) return j.exp_max != null ? `${j.exp_min}–${j.exp_max} yrs` : `${j.exp_min}+ yrs`;
  return j.exp_level ? j.exp_level.replace(/^\w/, (c) => c.toUpperCase()) : null;
}

export function place(j: { city: string | null; countries: string[]; location_raw: string | null }): string {
  if (j.city) return j.countries.length ? `${j.city}, ${j.countries[0]}` : j.city;
  if (j.countries.length) return j.countries.slice(0, 3).join(" · ");
  return j.location_raw?.split(";")[0]?.trim() || "Location not stated";
}

export const SOURCE_LABEL: Record<string, string> = {
  greenhouse: "Greenhouse",
  lever: "Lever",
  ashby: "Ashby",
  smartrecruiters: "SmartRecruiters",
  workable: "Workable",
  recruitee: "Recruitee",
  personio: "Personio",
  workday: "Workday",
  eightfold: "Company portal",
  generic: "Company site",
  linkedin: "LinkedIn",
  naukri: "Naukri",
  indeed: "Indeed",
};

export function sourceLabel(s: string): string {
  return SOURCE_LABEL[s] ?? s;
}
