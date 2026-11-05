"use client";

import { Loader2, PlugZap } from "lucide-react";
import { useMe } from "@/lib/hooks";
import { TopNav } from "@/components/top-nav";
import { Button } from "@/components/ui/primitives";

export default function AppLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  const { me, loading, offline, reload } = useMe();

  if (offline && !me) {
    return (
      <main className="flex min-h-dvh items-center justify-center px-4">
        <div className="max-w-sm text-center">
          <PlugZap className="mx-auto size-6 text-muted-foreground" />
          <h1 className="mt-3 text-lg font-semibold">Can&apos;t reach the JobScout backend</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            The API isn&apos;t responding. Start it with{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">python serve.py</code> in{" "}
            <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">backend/</code>, then retry.
          </p>
          <Button className="mt-4" onClick={() => void reload()} disabled={loading}>
            {loading && <Loader2 className="animate-spin" />}
            Retry
          </Button>
        </div>
      </main>
    );
  }

  if (loading || !me) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </main>
    );
  }

  // Top nav over a content column. h-dvh with min-h-0 children so only the inner panes scroll.
  return (
    <div className="flex h-dvh flex-col overflow-hidden">
      <TopNav me={me} />
      {/* Jobs fills this exactly and scrolls its own panes; plain pages (admin, companies, ...) scroll here. */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto">{children}</div>
    </div>
  );
}
