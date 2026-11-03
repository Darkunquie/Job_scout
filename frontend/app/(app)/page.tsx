"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Download, Filter, LayoutGrid, Loader2, Rows3, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { api, type Company, type Facets, type Job, type JobPage, type Meta } from "@/lib/api";
import { useDebounced, useMe, useMediaQuery } from "@/lib/hooks";
import { activeChips, emptyFilters, toQuery, type Filters, type Sort } from "@/lib/filters";
import { Badge, Button } from "@/components/ui/primitives";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Sheet,
  SheetContent,
  SheetTitle,
  SheetTrigger,
} from "@/components/ui/controls";
import { ScrapeBar, type Board } from "@/components/scrape-bar";
import { ScrapeProgress } from "@/components/scrape-progress";
import { FiltersRail } from "@/components/filters-rail";
import { JobCard, JobDetailPane } from "@/components/job";
import { JobTable } from "@/components/job-table";

const PAGE = 50;

export default function WorkspacePage() {
  const { me } = useMe();
  const params = useSearchParams();
  const urlQ = params.get("q") ?? "";

  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [sort, setSort] = useState<Sort>("posted");
  const [view, setView] = useState<"cards" | "table">("cards");
  const [boards, setBoards] = useState<Board[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [selected, setSelected] = useState<number | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);
  // At xl the detail pane is already on screen, so the sheet must not exist at all.
  const wideEnoughForPane = useMediaQuery("(min-width: 1280px)");
  const [facets, setFacets] = useState<Facets | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [hasCompanies, setHasCompanies] = useState<boolean | null>(null);
  const [taskIds, setTaskIds] = useState<number[]>([]);
  const [taskLabels, setTaskLabels] = useState<Record<number, string>>({});

  // The board toggles double as view filters, exactly as the spec describes.
  const effective = useMemo<Filters>(
    () => ({ ...filters, q: urlQ, sources: boards.length ? boards : filters.sources }),
    [filters, urlQ, boards],
  );
  const query = useDebounced(toQuery(effective, { sort, limit: PAGE }), 250);

  useEffect(() => {
    void api.get<Meta>("/meta").then(setMeta).catch(() => {});
    void api
      .get<Company[]>("/companies")
      .then((c) => setHasCompanies(c.length > 0))
      .catch(() => setHasCompanies(null));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const page = await api.get<JobPage>(`/jobs?${query}`);
      setJobs(page.items);
      setTotal(page.total);
      setOffset(page.items.length);
      setSelected((cur) => (cur && page.items.some((j) => j.id === cur) ? cur : (page.items[0]?.id ?? null)));
    } catch {
      toast.error("Could not load jobs");
    } finally {
      setLoading(false);
    }
    void api
      .get<Facets>(`/jobs/facets?${query}`)
      .then(setFacets)
      .catch(() => {});
  }, [query]);

  useEffect(() => {
    void load();
  }, [load]);

  async function loadMore() {
    setLoadingMore(true);
    try {
      const page = await api.get<JobPage>(`/jobs?${query}&offset=${offset}`);
      setJobs((prev) => [...prev, ...page.items]);
      setOffset((o) => o + page.items.length);
    } finally {
      setLoadingMore(false);
    }
  }

  // j/k to walk the list, Enter to open the posting.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = document.activeElement?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;
      if (!["j", "k", "Enter"].includes(e.key)) return;
      const i = jobs.findIndex((j) => j.id === selected);
      if (e.key === "Enter") {
        const job = jobs[i];
        if (job?.apply_url) window.open(job.apply_url, "_blank", "noopener");
        return;
      }
      e.preventDefault();
      const next = e.key === "j" ? Math.min(jobs.length - 1, i + 1) : Math.max(0, i - 1);
      if (jobs[next]) setSelected(jobs[next].id);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [jobs, selected]);

  const chips = activeChips(effective);
  const regionLabel =
    effective.countries.length > 0
      ? effective.countries.join(", ")
      : me?.prefs?.region_mode === "india"
        ? "India"
        : me?.prefs?.region_mode === "all"
          ? "All countries"
          : (me?.prefs?.countries.join(", ") ?? "—");

  if (!me) return null;

  return (
    <>
      <ScrapeBar
        me={me}
        boards={boards}
        onBoardsChange={setBoards}
        onQueued={(ids, labels) => {
          setTaskIds(ids);
          setTaskLabels((p) => ({ ...p, ...labels }));
        }}
      />

      <ScrapeProgress ids={taskIds} labels={taskLabels} onFinished={load} onClear={() => setTaskIds([])} />

      <div className="grid min-h-0 flex-1 lg:grid-cols-[216px_minmax(0,1fr)] xl:grid-cols-[216px_minmax(0,1.05fr)_minmax(0,1fr)]">
        <div className="hidden min-h-0 overflow-hidden border-r lg:block">
          <FiltersRail filters={effective} setFilters={setFilters} facets={facets} meta={meta} />
        </div>

        <section className="flex min-h-0 min-w-0 flex-col border-r">
          <div className="shrink-0 space-y-2 border-b px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <Sheet>
                <SheetTrigger asChild>
                  <Button variant="outline" size="sm" className="lg:hidden">
                    <Filter />
                    Filters
                    {chips.length > 0 && <Badge>{chips.length}</Badge>}
                  </Button>
                </SheetTrigger>
                <SheetContent side="bottom" className="lg:hidden">
                  <SheetTitle>Filters</SheetTitle>
                  <FiltersRail filters={effective} setFilters={setFilters} facets={facets} meta={meta} />
                </SheetContent>
              </Sheet>

              <p className="text-sm">
                <span className="font-semibold tabular">{total.toLocaleString()}</span>{" "}
                <span className="text-muted-foreground">jobs · {regionLabel}</span>
              </p>

              <div className="ml-auto flex flex-wrap items-center gap-1.5">
                <Select value={sort} onValueChange={(v) => setSort(v as Sort)}>
                  <SelectTrigger className="h-8 w-[150px]">
                    <SlidersHorizontal className="size-3.5 opacity-60" />
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="posted">Newest</SelectItem>
                    <SelectItem value="match">Best match</SelectItem>
                    <SelectItem value="salary">Top salary</SelectItem>
                    <SelectItem value="company">Company</SelectItem>
                    <SelectItem value="random">Shuffle</SelectItem>
                  </SelectContent>
                </Select>

                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={view === "cards" ? "Switch to table" : "Switch to cards"}
                  onClick={() => setView(view === "cards" ? "table" : "cards")}
                >
                  {view === "cards" ? <Rows3 /> : <LayoutGrid />}
                </Button>

                <Button asChild variant="outline" size="sm">
                  <a href={`/api/jobs/export.xlsx?${toQuery(effective, { sort })}`}>
                    <Download />
                    <span className="hidden sm:inline">Excel</span>
                  </a>
                </Button>
              </div>
            </div>

            {chips.length > 0 && (
              <div className="flex flex-wrap items-center gap-1">
                {chips.map((c) => (
                  <button key={c.key} onClick={() => setFilters(c.clear(filters))}>
                    <Badge variant="secondary">{c.label} ×</Badge>
                  </button>
                ))}
                <button
                  className="ml-1 text-xs text-muted-foreground underline hover:text-foreground"
                  onClick={() => setFilters(emptyFilters)}
                >
                  clear all
                </button>
              </div>
            )}

            {hasCompanies === false && chips.length === 0 && (
              <p className="rounded-md bg-primary/5 px-2.5 py-1.5 text-xs text-muted-foreground">
                Showing popular seed companies. Paste a careers URL above to scrape a specific company.
              </p>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex h-40 items-center justify-center">
                <Loader2 className="size-5 animate-spin text-muted-foreground" />
              </div>
            ) : jobs.length === 0 ? (
              <div className="p-8 text-center">
                <p className="text-sm font-medium">No jobs match these filters</p>
                <p className="mt-1 text-sm text-muted-foreground">
                  Clear a filter, widen the region, or scrape another careers URL.
                </p>
              </div>
            ) : view === "cards" ? (
              jobs.map((j) => (
                <JobCard
                  key={j.id}
                  job={j}
                  selected={selected === j.id}
                  onSelect={() => {
                    setSelected(j.id);
                    setDetailOpen(true);
                  }}
                />
              ))
            ) : (
              <JobTable
                jobs={jobs}
                selectedId={selected}
                onSelect={(id) => {
                  setSelected(id);
                  setDetailOpen(true);
                }}
              />
            )}

            {!loading && jobs.length < total && (
              <div className="p-3">
                <Button variant="outline" className="w-full" onClick={loadMore} disabled={loadingMore}>
                  {loadingMore && <Loader2 className="animate-spin" />}
                  Load more ({total - jobs.length} left)
                </Button>
              </div>
            )}
          </div>
        </section>

        {wideEnoughForPane && (
          <section className="min-h-0 min-w-0 overflow-hidden">
            <JobDetailPane jobId={selected} />
          </section>
        )}
      </div>

      {/* Below xl there is no detail column, so the job opens in a sheet instead. */}
      {!wideEnoughForPane && (
        <Sheet open={detailOpen && selected != null} onOpenChange={setDetailOpen}>
          <SheetContent side="right" className="p-0">
            <SheetTitle className="sr-only">Job detail</SheetTitle>
            <JobDetailPane jobId={selected} />
          </SheetContent>
        </Sheet>
      )}
    </>
  );
}
