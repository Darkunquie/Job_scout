"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Compass, ExternalLink, Loader2 } from "lucide-react";
import { ApiError, api, type Job } from "@/lib/api";
import { experience, place, salary, sourceLabel, timeAgo } from "@/lib/format";
import { Badge } from "@/components/ui/primitives";

/** Public, read-only shortlist. No sign-in: the token is the whole credential, so it expires. */
export default function ShortlistPage() {
  const { token } = useParams<{ token: string }>();
  const [jobs, setJobs] = useState<Job[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void api
      .get<Job[]>(`/shortlists/${token}`)
      .then(setJobs)
      .catch((e) => setError(e instanceof ApiError ? e.message : "Could not open this shortlist"));
  }, [token]);

  if (error) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4">
        <div className="text-center">
          <h1 className="text-lg font-semibold">Shortlist unavailable</h1>
          <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          <p className="mt-1 text-sm text-muted-foreground">Share links expire after 30 days.</p>
        </div>
      </main>
    );
  }

  if (!jobs) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <div className="mb-6 flex items-center gap-2">
        <Compass className="size-5 text-primary" />
        <span className="text-sm font-semibold tracking-tight">JobScout</span>
        <Badge variant="outline" className="ml-auto">
          shared shortlist
        </Badge>
      </div>

      <h1 className="text-xl font-semibold tracking-tight">
        {jobs.length} job{jobs.length === 1 ? "" : "s"}
      </h1>
      <p className="mt-1 text-sm text-muted-foreground">
        A read-only list someone shared with you. Links go to the original postings.
      </p>

      <ul className="mt-5 divide-y rounded-lg border">
        {jobs.map((j) => {
          const pay = salary(j);
          const exp = experience(j);
          return (
            <li key={j.id} className="p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <h2 className="truncate text-sm font-medium">{j.title}</h2>
                  <p className="mt-0.5 truncate text-xs text-muted-foreground">
                    {j.company_name ?? "Unknown company"} · {place(j)}
                    {j.work_arrangement ? ` · ${j.work_arrangement}` : ""}
                  </p>
                  {j.skills.length > 0 && (
                    <div className="mt-1.5 flex flex-wrap gap-1">
                      {j.skills.slice(0, 6).map((s) => (
                        <Badge key={s} variant="secondary">
                          {s}
                        </Badge>
                      ))}
                    </div>
                  )}
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    {pay ?? "Not disclosed"}
                    {exp ? ` · ${exp}` : ""} · {timeAgo(j.posted_at ?? j.first_seen_at)} ·{" "}
                    {sourceLabel(j.source)}
                  </p>
                </div>
                {j.apply_url && (
                  <a
                    href={j.apply_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex shrink-0 items-center gap-1 rounded-md border px-2.5 py-1 text-xs font-medium hover:bg-accent"
                  >
                    Open
                    <ExternalLink className="size-3" />
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ul>
    </main>
  );
}
