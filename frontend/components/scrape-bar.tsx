"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, Check, FileUp, Loader2, Play, Plus } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, type Me, type ScrapeResult } from "@/lib/api";
import { useDebounced } from "@/lib/hooks";
import { sourceLabel } from "@/lib/format";
import { Badge, Button, Input, Label, Textarea } from "@/components/ui/primitives";

const BOARDS = ["linkedin", "naukri", "indeed"] as const;
export type Board = (typeof BOARDS)[number];

interface Detected {
  url: string;
  ats: string | null;
  slug: string | null;
}

/** The scrape box from docs/UI_DESIGN.md §3.3: URL textarea on the left, source toggles on the right. */
export function ScrapeBar({
  me,
  boards,
  onBoardsChange,
  onQueued,
}: Readonly<{
  me: Me;
  boards: Board[];
  onBoardsChange: (next: Board[]) => void;
  onQueued: (ids: number[], labels: Record<number, string>) => void;
}>) {
  const [text, setText] = useState("");
  const [keyword, setKeyword] = useState("");
  const [flags, setFlags] = useState<Record<string, boolean>>({});
  const [detected, setDetected] = useState<Detected[]>([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false); // phones only; always open from lg up
  const file = useRef<HTMLInputElement>(null);

  const urls = useMemo(
    () =>
      text
        .split(/[\n,]/)
        .map((u) => u.trim())
        .filter(Boolean),
    [text],
  );
  const debouncedUrls = useDebounced(urls, 400);

  useEffect(() => {
    void api.get<Record<string, boolean>>("/admin/flags").then(setFlags).catch(() => {});
  }, []);

  useEffect(() => {
    if (!debouncedUrls.length) return setDetected([]);
    void api
      .post<Detected[]>("/scrape/detect", { urls: debouncedUrls.slice(0, 50) })
      .then(setDetected)
      .catch(() => setDetected([]));
  }, [debouncedUrls]);

  async function scrape() {
    setBusy(true);
    try {
      const ids: number[] = [];
      const names: Record<number, string> = {};

      if (urls.length) {
        const results = await api.post<ScrapeResult[]>("/scrape/urls", { urls: urls.slice(0, 50) });
        for (const r of results) {
          if (r.task_id) {
            ids.push(r.task_id);
            names[r.task_id] = r.company || hostOf(r.url);
          }
        }
        const cached = results.filter((r) => r.status === "cached");
        const bad = results.filter((r) => ["invalid", "unsupported", "workday_disabled"].includes(r.status));
        if (cached.length) toast.success(`${cached.length} company(s) already fresh — showing cached jobs`);
        for (const b of bad) toast.error(`${b.url}: ${b.message ?? b.status}`);
        if (results.some((r) => r.status === "queued")) setText("");
      }

      if (boards.length) {
        if (keyword.trim().length < 2) {
          toast.error("Job boards need a search keyword");
        } else {
          const res = await api.post<{ board: string; status: string; task_id?: number }[]>("/scrape/boards", {
            boards,
            q: keyword.trim(),
            location: me.prefs?.region_mode === "india" ? "India" : "",
            country_code: me.prefs?.region_mode === "india" ? "IN" : null,
            hours_old: 168,
            results: 100,
          });
          for (const r of res) {
            if (r.task_id) {
              ids.push(r.task_id);
              names[r.task_id] = sourceLabel(r.board);
            } else {
              toast.error(`${sourceLabel(r.board)} is disabled by the admin`);
            }
          }
        }
      }

      if (!urls.length && !boards.length) toast.error("Paste a careers URL or turn on a job board");
      if (ids.length) onQueued(ids, names);
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not start the scrape");
    } finally {
      setBusy(false);
    }
  }

  async function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    const body = await f.text();
    // A CSV export of careers links: take the first URL-looking cell on each line.
    const found = body
      .split(/\r?\n/)
      .flatMap((line) => line.split(/[,;\t]/))
      .map((c) => c.trim().replace(/^"|"$/g, ""))
      .filter((c) => /^https?:\/\//i.test(c) || /^[\w-]+(\.[\w-]+)+\//.test(c));
    setText((t) => [t, ...found].filter(Boolean).join("\n"));
    if (file.current) file.current.value = "";
    toast.success(`Added ${found.length} URL(s) from ${f.name}`);
  }

  return (
    <section className="shrink-0 border-b bg-card">
      {/* Phones collapse this to a button (docs/UI_DESIGN.md §4); desktop always shows it. */}
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-2 text-sm font-medium lg:hidden"
      >
        <Plus className={`size-4 transition-transform ${open ? "rotate-45" : ""}`} />
        {open ? "Hide scrape box" : "Add URLs or job boards"}
        {boards.length > 0 && <Badge className="ml-auto">{boards.length} board(s)</Badge>}
      </button>

      <div className={`${open ? "grid" : "hidden"} gap-3 px-4 pb-2 pt-2 lg:grid lg:grid-cols-[1fr_300px]`}>
        <div className="space-y-1.5">
          <Label htmlFor="urls" className="sr-only">Paste careers URLs, one per line</Label>
          <Textarea
            id="urls"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={"https://jobs.careers.microsoft.com/global/en/search\nhttps://boards.greenhouse.io/okta"}
            className="min-h-[44px] font-mono text-xs"
            spellCheck={false}
          />
          {detected.length > 0 && (
            <div className="flex flex-wrap gap-1">
              {detected.map((d, i) => (
                <Badge key={`${d.url}-${i}`} variant={d.ats ? "success" : "warning"} className="gap-1">
                  {d.ats ? <Check className="size-3" /> : <AlertTriangle className="size-3" />}
                  <span className="max-w-[18ch] truncate">{d.slug ?? hostOf(d.url)}</span>
                  <span className="opacity-70">{d.ats ? sourceLabel(d.ats) : "smart mode"}</span>
                </Badge>
              ))}
            </div>
          )}
          <div className="flex items-center gap-2">
            <input ref={file} type="file" accept=".csv,.txt" onChange={onFile} className="hidden" />
            <Button variant="outline" size="sm" onClick={() => file.current?.click()}>
              <FileUp />
              CSV
            </Button>
            <span className="text-xs text-muted-foreground">
              {urls.length ? `${urls.length} URL(s)` : "Up to 50 per scrape"}
            </span>
            <Button className="ml-auto" onClick={scrape} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" /> : <Play />}
              Scrape now
            </Button>
          </div>
        </div>

        <div className="space-y-1.5">
          <Label className="sr-only">Job boards</Label>
          <div className="space-y-1.5">
            <div className="flex gap-1.5">
              {BOARDS.map((b) => {
                const on = boards.includes(b);
                const allowed = flags[b] !== false;
                return (
                  <button
                    key={b}
                    type="button"
                    disabled={!allowed}
                    title={allowed ? undefined : "Disabled by the admin"}
                    onClick={() => onBoardsChange(on ? boards.filter((x) => x !== b) : [...boards, b])}
                    className={`flex flex-1 items-center justify-center gap-1.5 rounded-md border px-2 py-1 text-xs transition-colors disabled:opacity-50 ${
                      on ? "border-primary bg-primary/10 text-primary" : "bg-background hover:bg-accent"
                    }`}
                  >
                    <span className={`size-1.5 rounded-full ${on ? "bg-primary" : "bg-muted-foreground/30"}`} />
                    {sourceLabel(b)}
                  </button>
                );
              })}
            </div>
            {boards.length > 0 && (
              <Input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="Keyword, e.g. data engineer"
                aria-label="Board search keyword"
                className="h-7 text-xs"
              />
            )}
            <p className="text-xs text-muted-foreground">
              Company portals always on · Workday {flags.workday === false ? "off" : "on"}
              {me.role === "admin" && (
                <>
                  {" · "}
                  <button
                    className="underline hover:text-foreground"
                    onClick={async () => {
                      const next = await api.patch<Record<string, boolean>>("/admin/flags", {
                        workday: flags.workday === false,
                      });
                      setFlags(next);
                    }}
                  >
                    turn {flags.workday === false ? "on" : "off"}
                  </button>
                </>
              )}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}

function hostOf(url: string): string {
  try {
    return new URL(url.startsWith("http") ? url : `https://${url}`).hostname.replace(/^www\./, "");
  } catch {
    return url.slice(0, 24);
  }
}
