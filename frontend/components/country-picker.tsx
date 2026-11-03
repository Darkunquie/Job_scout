"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import type { Meta } from "@/lib/api";
import { Badge, Input } from "@/components/ui/primitives";
import { Checkbox } from "@/components/ui/controls";

/** Searchable country multi-select. Used by onboarding and by the Location filter group. */
export function CountryPicker({
  countries,
  value,
  onChange,
  counts,
  className,
}: {
  countries: Meta["countries"];
  value: string[];
  onChange: (next: string[]) => void;
  /** Job counts per ISO code. Countries we actually have jobs for float to the top. */
  counts?: Record<string, number>;
  className?: string;
}) {
  const [q, setQ] = useState("");
  const selected = useMemo(() => new Set(value), [value]);

  const shown = useMemo(() => {
    const needle = q.trim().toLowerCase();
    const list = needle
      ? countries.filter((c) => c.name.toLowerCase().includes(needle) || c.code.toLowerCase() === needle)
      : counts
        ? [...countries].sort((a, b) => (counts[b.code] ?? 0) - (counts[a.code] ?? 0) || a.name.localeCompare(b.name))
        : countries;
    // keep chosen countries visible even when they don't match the search
    const chosen = countries.filter((c) => selected.has(c.code) && !list.includes(c));
    return [...chosen, ...list].slice(0, 120);
  }, [countries, q, selected, counts]);

  function toggle(code: string) {
    onChange(selected.has(code) ? value.filter((c) => c !== code) : [...value, code]);
  }

  return (
    <div className={className}>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search countries"
          className="pl-8"
          aria-label="Search countries"
        />
      </div>

      {value.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {value.map((code) => (
            <button key={code} type="button" onClick={() => toggle(code)} aria-label={`Remove ${code}`}>
              <Badge className="font-mono">{code} ×</Badge>
            </button>
          ))}
        </div>
      )}

      <div className="mt-2 max-h-56 overflow-y-auto rounded-md border">
        {shown.map((c) => (
          <label
            key={c.code}
            className="flex cursor-pointer items-center gap-2 px-2.5 py-1.5 text-sm hover:bg-accent"
          >
            <Checkbox checked={selected.has(c.code)} onCheckedChange={() => toggle(c.code)} />
            <span className="truncate">{c.name}</span>
            <span className="ml-auto shrink-0 font-mono text-xs text-muted-foreground">
              {counts?.[c.code] ? counts[c.code].toLocaleString() : c.code}
            </span>
          </label>
        ))}
        {shown.length === 0 && <p className="p-3 text-sm text-muted-foreground">No country matches “{q}”.</p>}
      </div>
    </div>
  );
}
