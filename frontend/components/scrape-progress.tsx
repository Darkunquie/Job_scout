"use client";

import { useEffect, useRef } from "react";
import { X } from "lucide-react";
import { useTaskStream } from "@/lib/hooks";

/**
 * Live scrape progress, shown under the search bar rather than inside the scrape panel —
 * closing the panel must not hide a running scrape.
 */
export function ScrapeProgress({
  ids,
  labels,
  onFinished,
  onClear,
}: {
  ids: number[];
  labels: Record<number, string>;
  onFinished: () => void;
  onClear: () => void;
}) {
  const tasks = useTaskStream(ids);
  const settled = ids.filter((id) => tasks[id]?.status === "done" || tasks[id]?.status === "error").length;
  const running = ids.length - settled;

  // Refresh the list once, when every task in this run has settled.
  const seen = useRef(0);
  useEffect(() => {
    if (ids.length && settled === ids.length && settled !== seen.current) onFinished();
    seen.current = settled;
  }, [settled, ids.length, onFinished]);

  if (!ids.length) return null;

  return (
    <div className="shrink-0 space-y-1 border-b bg-card px-3 py-1.5">
      {ids.map((id) => {
        const t = tasks[id];
        const found = t?.progress?.found ?? 0;
        const total = t?.progress?.total ?? null;
        const pct = total ? Math.min(100, Math.round((found / total) * 100)) : null;
        const done = t?.status === "done";
        const failed = t?.status === "error";
        return (
          <div key={id} className="flex items-center gap-2 text-xs">
            <span className="w-28 shrink-0 truncate font-medium">{labels[id] ?? `Task ${id}`}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-secondary">
              <div
                className={`h-full rounded-full transition-all ${
                  failed ? "bg-destructive" : done ? "bg-success" : "bg-primary"
                }`}
                style={{ width: `${done ? 100 : (pct ?? 15)}%` }}
              />
            </div>
            <span className="w-48 shrink-0 truncate text-right tabular text-muted-foreground">
              {failed
                ? (t.error ?? "failed")
                : done
                  ? `${t.progress.found ?? 0} jobs · ${t.progress.inserted ?? 0} new`
                  : total
                    ? `${found}/${total} ${t?.progress?.phase ?? ""}`
                    : `${found} found ${t?.progress?.phase ?? "queued"}`}
            </span>
          </div>
        );
      })}
      {running === 0 && (
        <button
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
          onClick={onClear}
        >
          <X className="size-3" /> clear
        </button>
      )}
    </div>
  );
}
