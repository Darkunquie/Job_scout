"use client";

import { ChevronDown } from "lucide-react";
import type { Facets, Meta } from "@/lib/api";
import type { Filters } from "@/lib/filters";
import { countActive } from "@/lib/filters";
import { sourceLabel } from "@/lib/format";
import { Button, Input, Label } from "@/components/ui/primitives";
import { Checkbox, Slider } from "@/components/ui/controls";
import { CountryPicker } from "@/components/country-picker";

const POSTED = [
  { d: 1, l: "24 hours" },
  { d: 3, l: "3 days" },
  { d: 7, l: "7 days" },
  { d: 14, l: "14 days" },
  { d: 30, l: "30 days" },
];
const LAKH = 100_000;

/** A collapsible facet group. <details> gives us keyboard support and open-state for free. */
function Group({ title, children, open = false }: { title: string; children: React.ReactNode; open?: boolean }) {
  return (
    <details open={open} className="group border-b px-3 py-2 [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between py-1 text-sm font-medium">
        {title}
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="space-y-2 pb-2 pt-1">{children}</div>
    </details>
  );
}

function FacetList({
  options,
  selected,
  onToggle,
  label = (v: string) => v,
  limit = 8,
}: {
  options: { v: string; n: number }[];
  selected: string[];
  onToggle: (v: string) => void;
  label?: (v: string) => string;
  limit?: number;
}) {
  if (!options.length) return <p className="text-xs text-muted-foreground">No data yet</p>;
  const chosen = options.filter((o) => selected.includes(o.v));
  const rest = options.filter((o) => !selected.includes(o.v));
  const shown = [...chosen, ...rest];
  const extra = Math.max(0, shown.length - limit);
  // Plain div, NOT <details>: a <details> without `open` hides its own children, so wrapping the
  // rows in one (even with a hidden <summary>) made every facet group render empty.
  return (
    <div className="space-y-1">
      <div className="space-y-1">
        {shown.slice(0, limit).map((o) => (
          <Row key={o.v} o={o} selected={selected} onToggle={onToggle} label={label} />
        ))}
      </div>
      {extra > 0 && (
        <details>
          <summary className="cursor-pointer text-xs text-primary hover:underline">{extra} more</summary>
          <div className="mt-1 max-h-48 space-y-1 overflow-y-auto">
            {shown.slice(limit).map((o) => (
              <Row key={o.v} o={o} selected={selected} onToggle={onToggle} label={label} />
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

function Row({
  o,
  selected,
  onToggle,
  label,
}: {
  o: { v: string; n: number };
  selected: string[];
  onToggle: (v: string) => void;
  label: (v: string) => string;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 text-sm">
      <Checkbox checked={selected.includes(o.v)} onCheckedChange={() => onToggle(o.v)} />
      <span className="truncate">{label(o.v)}</span>
      <span className="ml-auto shrink-0 tabular text-xs text-muted-foreground">{o.n}</span>
    </label>
  );
}

export function FiltersRail({
  filters,
  setFilters,
  facets,
  meta,
}: {
  filters: Filters;
  setFilters: (f: Filters) => void;
  facets: Facets | null;
  meta: Meta | null;
}) {
  const f = filters;
  const toggle = (key: keyof Filters) => (v: string) => {
    const cur = f[key] as string[];
    setFilters({ ...f, [key]: cur.includes(v) ? cur.filter((x) => x !== v) : [...cur, v] });
  };
  const active = countActive(f);

  return (
    <aside className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-sm font-semibold">
          Filters {active > 0 && <span className="text-muted-foreground">({active})</span>}
        </span>
        {active > 0 && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() =>
              setFilters({
                ...f,
                countries: [],
                city: "",
                sources: [],
                work_arrangement: [],
                employment_type: [],
                exp_level: [],
                exp_min: undefined,
                exp_max: undefined,
                posted_days: undefined,
                salary_min: undefined,
                salary_max: undefined,
                skills: [],
                companies: [],
                exclude_companies: [],
                visa: undefined,
                include_closed: false,
              })
            }
          >
            Clear all
          </Button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto">
        <Group title="Location" open>
          {meta && (
            <CountryPicker
              countries={meta.countries}
              value={f.countries}
              counts={Object.fromEntries((facets?.country ?? []).map((c) => [c.v, c.n]))}
              onChange={(countries) => setFilters({ ...f, countries, region: countries.length ? "countries" : "prefs" })}
            />
          )}
          <Input
            value={f.city}
            onChange={(e) => setFilters({ ...f, city: e.target.value })}
            placeholder="City"
            aria-label="City"
          />
          {facets?.city && <FacetList options={facets.city} selected={[]} onToggle={(v) => setFilters({ ...f, city: v })} limit={6} />}
        </Group>

        <Group title="Work arrangement" open>
          <FacetList
            options={
              facets?.work_arrangement?.length
                ? facets.work_arrangement
                : (meta?.work_arrangements ?? []).map((v) => ({ v, n: 0 }))
            }
            selected={f.work_arrangement}
            onToggle={toggle("work_arrangement")}
          />
        </Group>

        <Group title="Work type">
          <FacetList
            options={
              facets?.employment_type?.length
                ? facets.employment_type
                : (meta?.employment_types ?? []).map((v) => ({ v, n: 0 }))
            }
            selected={f.employment_type}
            onToggle={toggle("employment_type")}
          />
        </Group>

        <Group title="Experience">
          <FacetList
            options={facets?.exp_level?.length ? facets.exp_level : (meta?.exp_levels ?? []).map((v) => ({ v, n: 0 }))}
            selected={f.exp_level}
            onToggle={toggle("exp_level")}
            label={(v) => v.replace(/^\w/, (c) => c.toUpperCase())}
          />
          <div className="flex items-center gap-2 pt-1">
            <Input
              type="number"
              min={0}
              max={30}
              value={f.exp_min ?? ""}
              onChange={(e) => setFilters({ ...f, exp_min: e.target.value ? Number(e.target.value) : undefined })}
              placeholder="min"
              className="h-8"
              aria-label="Minimum years"
            />
            <span className="text-xs text-muted-foreground">to</span>
            <Input
              type="number"
              min={0}
              max={40}
              value={f.exp_max ?? ""}
              onChange={(e) => setFilters({ ...f, exp_max: e.target.value ? Number(e.target.value) : undefined })}
              placeholder="max"
              className="h-8"
              aria-label="Maximum years"
            />
            <span className="shrink-0 text-xs text-muted-foreground">yrs</span>
          </div>
        </Group>

        <Group title="Posted">
          <div className="flex flex-wrap gap-1">
            {POSTED.map((p) => (
              <button
                key={p.d}
                onClick={() => setFilters({ ...f, posted_days: f.posted_days === p.d ? undefined : p.d })}
                className={`rounded-md border px-2 py-1 text-xs transition-colors ${
                  f.posted_days === p.d ? "border-primary bg-primary/10 text-primary" : "hover:bg-accent"
                }`}
              >
                {p.l}
              </button>
            ))}
          </div>
        </Group>

        <Group title="Salary (INR/yr)">
          <Slider
            min={0}
            max={100}
            step={5}
            value={[f.salary_min ? f.salary_min / LAKH : 0]}
            onValueChange={([v]) => setFilters({ ...f, salary_min: v ? v * LAKH : undefined })}
            aria-label="Minimum salary in lakhs per year"
          />
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="tabular">{f.salary_min ? `₹${(f.salary_min / LAKH).toFixed(0)}L+` : "Any"}</span>
            <span>₹100L</span>
          </div>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={f.include_undisclosed_salary}
              onCheckedChange={(v) => setFilters({ ...f, include_undisclosed_salary: v === true })}
            />
            Include undisclosed
          </label>
        </Group>

        <Group title="Skills" open>
          <FacetList options={facets?.skills ?? []} selected={f.skills} onToggle={toggle("skills")} limit={10} />
        </Group>

        <Group title="Company">
          <FacetList options={facets?.company ?? []} selected={f.companies} onToggle={toggle("companies")} limit={8} />
        </Group>

        <Group title="Source">
          <FacetList
            options={facets?.source ?? []}
            selected={f.sources}
            onToggle={toggle("sources")}
            label={sourceLabel}
          />
        </Group>

        <Group title="Other">
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={f.visa === true}
              onCheckedChange={(v) => setFilters({ ...f, visa: v === true ? true : undefined })}
            />
            Sponsors a visa
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox checked={f.include_closed} onCheckedChange={(v) => setFilters({ ...f, include_closed: v === true })} />
            Include closed jobs
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-sm">
            <Checkbox
              checked={!f.collapse_duplicates}
              onCheckedChange={(v) => setFilters({ ...f, collapse_duplicates: v !== true })}
            />
            Show every duplicate
          </label>
          <div className="pt-1">
            <Label className="text-xs text-muted-foreground">Scope</Label>
            <div className="mt-1 flex gap-1">
              {(["all", "mine", "default"] as const).map((s) => (
                <button
                  key={s}
                  onClick={() => setFilters({ ...f, scope: s })}
                  className={`rounded-md border px-2 py-1 text-xs capitalize transition-colors ${
                    f.scope === s ? "border-primary bg-primary/10 text-primary" : "hover:bg-accent"
                  }`}
                >
                  {s === "default" ? "seed" : s}
                </button>
              ))}
            </div>
          </div>
        </Group>
      </div>
    </aside>
  );
}
