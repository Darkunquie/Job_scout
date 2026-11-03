"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, type Company } from "@/lib/api";
import { sourceLabel, timeAgo } from "@/lib/format";
import { Badge, Button } from "@/components/ui/primitives";

const STATUS: Record<string, "success" | "warning" | "destructive" | "outline" | "secondary"> = {
  ok: "success",
  new: "secondary",
  error: "destructive",
  blocked: "warning",
  unsupported: "outline",
  needs_attention: "warning",
};

export default function CompaniesPage() {
  const [rows, setRows] = useState<Company[] | null>(null);
  const [busy, setBusy] = useState<number | null>(null);

  const load = useCallback(() => {
    void api
      .get<Company[]>("/companies")
      .then(setRows)
      .catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);

  async function refresh(id: number) {
    setBusy(id);
    try {
      await api.post(`/companies/${id}/refresh`);
      toast.success("Refresh queued");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not queue a refresh");
    } finally {
      setBusy(null);
    }
  }

  async function remove(id: number) {
    await api.del(`/companies/${id}`);
    setRows((r) => (r ?? []).filter((c) => c.id !== id));
  }

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-6">
      <h1 className="text-lg font-semibold tracking-tight">My companies</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Companies you&apos;ve scraped. These refresh themselves about once an hour.
      </p>

      {rows === null ? (
        <div className="flex h-32 items-center justify-center">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        </div>
      ) : rows.length === 0 ? (
        <p className="mt-6 rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">
          Nothing here yet.{" "}
          <Link href="/" className="text-primary underline">
            Paste a careers URL
          </Link>{" "}
          to add your first company.
        </p>
      ) : (
        <div className="mt-5 overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Company</th>
                <th className="px-3 py-2 text-left font-medium">ATS</th>
                <th className="px-3 py-2 text-right font-medium">Jobs</th>
                <th className="px-3 py-2 text-left font-medium">Last scraped</th>
                <th className="px-3 py-2 text-left font-medium">Status</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id} className="border-b last:border-0">
                  <td className="max-w-[28ch] px-3 py-2">
                    <span className="block truncate font-medium">{c.name ?? "—"}</span>
                    <a
                      href={c.careers_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block truncate font-mono text-xs text-muted-foreground hover:text-primary"
                    >
                      {c.careers_url}
                    </a>
                  </td>
                  <td className="whitespace-nowrap px-3 py-2">{sourceLabel(c.ats_type)}</td>
                  <td className="px-3 py-2 text-right tabular">{c.job_count.toLocaleString()}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{timeAgo(c.last_scraped_at)}</td>
                  <td className="px-3 py-2">
                    <Badge variant={STATUS[c.status] ?? "outline"}>{c.status.replace(/_/g, " ")}</Badge>
                    {c.last_error && (
                      <span className="mt-0.5 block max-w-[32ch] truncate text-xs text-muted-foreground" title={c.last_error}>
                        {c.last_error}
                      </span>
                    )}
                  </td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <Button variant="ghost" size="iconSm" onClick={() => refresh(c.id)} aria-label="Refresh" disabled={busy === c.id}>
                      {busy === c.id ? <Loader2 className="animate-spin" /> : <RefreshCw />}
                    </Button>
                    <Button variant="ghost" size="iconSm" onClick={() => remove(c.id)} aria-label="Remove">
                      <Trash2 />
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
