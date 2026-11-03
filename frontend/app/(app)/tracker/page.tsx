"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, ChevronRight, ExternalLink, Loader2, Trash2 } from "lucide-react";
import { api, type ApplicationRow } from "@/lib/api";
import { place, timeAgo } from "@/lib/format";
import { Badge, Button } from "@/components/ui/primitives";

const STAGES = ["saved", "applied", "interview", "offer", "rejected"] as const;
type Stage = (typeof STAGES)[number];

export default function TrackerPage() {
  const [rows, setRows] = useState<ApplicationRow[] | null>(null);

  const load = useCallback(() => {
    void api
      .get<ApplicationRow[]>("/applications")
      .then(setRows)
      .catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);

  async function move(row: ApplicationRow, dir: -1 | 1) {
    const i = STAGES.indexOf(row.stage);
    const next = STAGES[Math.min(STAGES.length - 1, Math.max(0, i + dir))];
    if (next === row.stage) return;
    setRows((r) => (r ?? []).map((x) => (x.id === row.id ? { ...x, stage: next } : x)));
    await api.put("/applications", { job_id: row.id, stage: next });
  }

  async function remove(row: ApplicationRow) {
    setRows((r) => (r ?? []).filter((x) => x.id !== row.id));
    await api.del(`/applications/${row.id}`);
  }

  if (rows === null) {
    return (
      <main className="flex h-64 items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </main>
    );
  }

  return (
    <main className="w-full px-4 py-6">
      <h1 className="text-lg font-semibold tracking-tight">Application tracker</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Save a job from the detail pane, then walk it along with the arrows.
      </p>

      {rows.length === 0 ? (
        <p className="mt-6 rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Nothing saved yet.{" "}
          <Link href="/" className="text-primary underline">
            Find a job
          </Link>{" "}
          and hit Save.
        </p>
      ) : (
        <div className="mt-5 grid gap-3 md:grid-cols-3 xl:grid-cols-5">
          {STAGES.map((stage) => {
            const items = rows.filter((r) => r.stage === stage);
            return (
              <section key={stage} className="rounded-lg border bg-muted/20">
                <header className="flex items-center justify-between border-b px-3 py-2">
                  <h2 className="text-sm font-medium capitalize">{stage}</h2>
                  <Badge variant="outline" className="tabular">
                    {items.length}
                  </Badge>
                </header>
                <div className="space-y-2 p-2">
                  {items.map((row) => (
                    <article key={row.id} className="rounded-md border bg-background p-2">
                      <h3 className="text-sm font-medium leading-snug">{row.title}</h3>
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {row.company_name} · {place(row)}
                      </p>
                      <p className="mt-0.5 text-xs text-muted-foreground">updated {timeAgo(row.updated_at)}</p>
                      <div className="mt-2 flex items-center gap-0.5">
                        <Button
                          variant="ghost"
                          size="iconSm"
                          aria-label="Move back"
                          disabled={stage === STAGES[0]}
                          onClick={() => move(row, -1)}
                        >
                          <ChevronLeft />
                        </Button>
                        <Button
                          variant="ghost"
                          size="iconSm"
                          aria-label="Move forward"
                          disabled={stage === STAGES[STAGES.length - 1]}
                          onClick={() => move(row, 1)}
                        >
                          <ChevronRight />
                        </Button>
                        {row.apply_url && (
                          <Button asChild variant="ghost" size="iconSm" aria-label="Open posting">
                            <a href={row.apply_url} target="_blank" rel="noopener noreferrer">
                              <ExternalLink />
                            </a>
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="iconSm"
                          className="ml-auto"
                          aria-label="Remove"
                          onClick={() => remove(row)}
                        >
                          <Trash2 />
                        </Button>
                      </div>
                    </article>
                  ))}
                  {items.length === 0 && <p className="px-1 py-2 text-xs text-muted-foreground">Empty</p>}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </main>
  );
}
