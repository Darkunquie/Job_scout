"use client";

import { useEffect, useState } from "react";
import { Building2, ExternalLink, KanbanSquare, Loader2, MapPin, Star } from "lucide-react";
import { toast } from "sonner";
import { api, type Job, type JobDetail } from "@/lib/api";
import { experience, place, salary, sourceLabel, timeAgo } from "@/lib/format";
import { Badge, Button, Separator, Skeleton } from "@/components/ui/primitives";

function MatchBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  return (
    <span className="flex items-center gap-1.5" title="Resume match estimate">
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-secondary">
        <span className="block h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
      </span>
      <span className="tabular text-xs font-medium">{pct}%</span>
    </span>
  );
}

export function JobCard({
  job,
  selected,
  onSelect,
}: {
  job: Job;
  selected: boolean;
  onSelect: () => void;
}) {
  const pay = salary(job);
  const exp = experience(job);
  return (
    <button
      onClick={onSelect}
      aria-current={selected}
      className={`w-full border-b px-4 py-3 text-left transition-colors hover:bg-accent/50 focus:outline-none focus-visible:bg-accent ${
        selected ? "bg-accent" : ""
      } ${job.status === "closed" ? "opacity-60" : ""}`}
    >
      <div className="flex items-start gap-2">
        <span className={`mt-1.5 size-1.5 shrink-0 rounded-full ${selected ? "bg-primary" : "bg-transparent"}`} />
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-2">
            <h3 className="truncate text-sm font-medium">{job.title}</h3>
            <div className="flex shrink-0 items-center gap-1">
              {job.status === "closed" && <Badge variant="outline">CLOSED</Badge>}
              {job.is_new && job.status === "active" && <Badge variant="success">NEW</Badge>}
            </div>
          </div>

          <p className="mt-0.5 truncate text-xs text-muted-foreground">
            {job.company_name ?? "Unknown company"} · {place(job)}
            {job.work_arrangement ? ` · ${job.work_arrangement}` : ""}
          </p>

          {job.skills.length > 0 && (
            <div className="mt-1.5 flex flex-wrap gap-1">
              {job.skills.slice(0, 5).map((s) => (
                <Badge key={s} variant="secondary">
                  {s}
                </Badge>
              ))}
              {job.skills.length > 5 && <Badge variant="outline">+{job.skills.length - 5}</Badge>}
            </div>
          )}

          <div className="mt-1.5 flex items-center gap-2 text-xs text-muted-foreground">
            <span className={pay ? "font-medium text-foreground" : ""}>{pay ?? "Not disclosed"}</span>
            {exp && <span>· {exp}</span>}
            <span className="ml-auto flex items-center gap-2">
              <span>{timeAgo(job.posted_at ?? job.first_seen_at)}</span>
              <span>· {sourceLabel(job.source)}</span>
              {job.match_score != null && <MatchBar score={job.match_score} />}
            </span>
          </div>
        </div>
      </div>
    </button>
  );
}

const STAGES = ["saved", "applied", "interview", "offer", "rejected"] as const;

export function JobDetailPane({ jobId }: { jobId: number | null }) {
  const [job, setJob] = useState<JobDetail | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (jobId == null) return setJob(null);
    setLoading(true);
    void api
      .get<JobDetail>(`/jobs/${jobId}`)
      .then(setJob)
      .catch(() => setJob(null))
      .finally(() => setLoading(false));
  }, [jobId]);

  async function track(stage: (typeof STAGES)[number]) {
    if (!job) return;
    try {
      await api.put("/applications", { job_id: job.id, stage });
      toast.success(`Moved to ${stage}`);
    } catch {
      toast.error("Could not update the tracker");
    }
  }

  if (jobId == null) {
    return (
      <div className="flex h-full items-center justify-center p-8 text-center">
        <p className="max-w-[24ch] text-sm text-muted-foreground">Pick a job to see the full description here.</p>
      </div>
    );
  }
  if (loading || !job) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-5 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-20 w-full" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const pay = salary(job);
  const exp = experience(job);

  return (
    <article className="flex h-full flex-col">
      <div className="space-y-2 border-b p-4">
        <h2 className="text-base font-semibold leading-snug">{job.title}</h2>
        <p className="flex flex-wrap items-center gap-x-2 text-sm text-muted-foreground">
          <span className="flex items-center gap-1">
            <Building2 className="size-3.5" />
            {job.company_name ?? "Unknown company"}
          </span>
          <span className="flex items-center gap-1">
            <MapPin className="size-3.5" />
            {place(job)}
          </span>
        </p>

        <div className="flex flex-wrap items-center gap-1.5">
          {job.is_new && job.status === "active" && <Badge variant="success">NEW</Badge>}
          {job.status === "closed" && <Badge variant="destructive">CLOSED</Badge>}
          {job.work_arrangement && <Badge variant="outline">{job.work_arrangement}</Badge>}
          {job.employment_type && <Badge variant="outline">{job.employment_type}</Badge>}
          {exp && <Badge variant="outline">{exp}</Badge>}
          {job.visa_sponsorship === true && <Badge variant="success">Sponsors visa</Badge>}
          {job.department && <Badge variant="secondary">{job.department}</Badge>}
        </div>

        <p className="text-sm">
          <span className="font-medium">{pay ?? "Salary not disclosed"}</span>
          {job.salary_inr_year != null && job.salary_currency !== "INR" && (
            <span className="text-muted-foreground"> · ≈ ₹{(job.salary_inr_year / 1e5).toFixed(1)}L/yr</span>
          )}
        </p>

        {job.match_score != null && (
          <div className="rounded-md border bg-muted/40 p-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium">Match estimate</span>
              <MatchBar score={job.match_score} />
            </div>
            {/* Guard with a boolean: `0 || 0` is 0, and React renders that as a stray "0". */}
            {(job.skills_matched?.length ?? 0) + (job.skills_missing?.length ?? 0) > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1">
                {job.skills_matched?.map((s) => (
                  <Badge key={s} variant="success">
                    ✓ {s}
                  </Badge>
                ))}
                {job.skills_missing?.map((s) => (
                  <Badge key={s} variant="outline">
                    ✗ {s}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button asChild size="sm" disabled={!job.apply_url}>
            <a href={job.apply_url ?? "#"} target="_blank" rel="noopener noreferrer">
              Apply
              <ExternalLink />
            </a>
          </Button>
          <Button variant="outline" size="sm" onClick={() => track("saved")}>
            <Star />
            Save
          </Button>
          <Button variant="outline" size="sm" onClick={() => track("applied")}>
            <KanbanSquare />
            Mark applied
          </Button>
        </div>

        <p className="text-xs text-muted-foreground">
          {sourceLabel(job.source)}
          {job.also_on && job.also_on.length > 1 && ` · also on ${job.also_on.filter((s) => s !== job.source).map(sourceLabel).join(", ")}`}
          {" · seen "}
          {timeAgo(job.first_seen_at)}
        </p>
      </div>

      <div className="flex-1 overflow-y-auto p-4">
        {job.description ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{job.description}</p>
        ) : (
          <p className="text-sm text-muted-foreground">
            No description was published on the board.{" "}
            {job.url && (
              <a href={job.url} target="_blank" rel="noopener noreferrer" className="text-primary underline">
                Open the original posting
              </a>
            )}
          </p>
        )}
        <Separator className="my-4" />
        <p className="text-xs text-muted-foreground">
          Scraped from a public careers page. Always check the original posting before applying.
        </p>
      </div>
    </article>
  );
}

export function JobDetailSkeletonFallback() {
  return (
    <div className="flex h-full items-center justify-center">
      <Loader2 className="size-5 animate-spin text-muted-foreground" />
    </div>
  );
}
