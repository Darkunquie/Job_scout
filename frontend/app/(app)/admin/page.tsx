"use client";

import { useCallback, useEffect, useState } from "react";
import { Copy, Loader2, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, type Company, type Health } from "@/lib/api";
import { sourceLabel, timeAgo } from "@/lib/format";
import { Badge, Button, Input, Label } from "@/components/ui/primitives";
import { Checkbox, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/controls";

interface AdminUser {
  id: number;
  email: string;
  role: "admin" | "user";
  active: boolean;
  daily_quota: number;
  created_at: string;
  scrapes_today: number;
}

export default function AdminPage() {
  return (
    <main className="mx-auto w-full max-w-6xl px-4 py-6">
      <h1 className="text-lg font-semibold tracking-tight">Admin</h1>
      <Tabs defaultValue="health" className="mt-4">
        {/* Four tab labels do not fit a phone; let the strip scroll instead of the whole page. */}
        <TabsList className="max-w-full justify-start overflow-x-auto">
          <TabsTrigger value="health">Scraper health</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="seed">Seed companies</TabsTrigger>
          <TabsTrigger value="flags">Feature flags</TabsTrigger>
        </TabsList>
        <TabsContent value="health" className="mt-4">
          <HealthPanel />
        </TabsContent>
        <TabsContent value="users" className="mt-4">
          <UsersPanel />
        </TabsContent>
        <TabsContent value="seed" className="mt-4">
          <SeedPanel />
        </TabsContent>
        <TabsContent value="flags" className="mt-4">
          <FlagsPanel />
        </TabsContent>
      </Tabs>
    </main>
  );
}

function HealthPanel() {
  const [h, setH] = useState<Health | null>(null);
  useEffect(() => {
    void api
      .get<Health>("/admin/health")
      .then(setH)
      .catch(() => {});
  }, []);
  if (!h) return <Loader2 className="size-5 animate-spin text-muted-foreground" />;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-3">
        {[
          { l: "Active jobs", v: h.totals.active_jobs },
          { l: "All jobs ever", v: h.totals.all_jobs },
          { l: "Companies with jobs", v: h.totals.companies },
        ].map((s) => (
          <div key={s.l} className="rounded-lg border p-3">
            <p className="text-xs text-muted-foreground">{s.l}</p>
            <p className="mt-1 text-xl font-semibold tabular">{s.v.toLocaleString()}</p>
          </div>
        ))}
      </div>

      <section>
        <h2 className="mb-2 text-sm font-medium">Adapters (last 7 days)</h2>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full text-sm">
            <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
              <tr>
                <th className="px-3 py-2 text-left font-medium">Adapter</th>
                <th className="px-3 py-2 text-right font-medium">Runs</th>
                <th className="px-3 py-2 text-right font-medium">Complete</th>
                <th className="px-3 py-2 text-right font-medium">Blocked</th>
                <th className="px-3 py-2 text-right font-medium">Success</th>
                <th className="px-3 py-2 text-left font-medium">Last run</th>
              </tr>
            </thead>
            <tbody>
              {h.adapters.map((a) => (
                <tr key={a.adapter} className="border-b last:border-0">
                  <td className="px-3 py-2">{sourceLabel(a.adapter)}</td>
                  <td className="px-3 py-2 text-right tabular">{a.runs}</td>
                  <td className="px-3 py-2 text-right tabular">{a.ok}</td>
                  <td className="px-3 py-2 text-right tabular">{a.blocked}</td>
                  <td className="px-3 py-2 text-right tabular">
                    <Badge variant={(a.success_pct ?? 0) >= 80 ? "success" : (a.success_pct ?? 0) >= 40 ? "warning" : "destructive"}>
                      {a.success_pct ?? 0}%
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{timeAgo(a.last_run)}</td>
                </tr>
              ))}
              {h.adapters.length === 0 && (
                <tr>
                  <td colSpan={6} className="px-3 py-4 text-center text-muted-foreground">
                    No runs yet
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="mb-2 text-sm font-medium">Companies needing attention ({h.problem_companies.length})</h2>
        <div className="space-y-1">
          {h.problem_companies.map((c) => (
            <div key={c.id} className="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
              <span className="truncate font-medium">{c.name ?? c.careers_url}</span>
              <Badge variant={c.status === "blocked" ? "warning" : "destructive"}>{c.status.replace(/_/g, " ")}</Badge>
              <span className="ml-auto max-w-[40ch] truncate text-xs text-muted-foreground" title={c.last_error ?? ""}>
                {c.last_error}
              </span>
            </div>
          ))}
          {h.problem_companies.length === 0 && <p className="text-sm text-muted-foreground">All clear.</p>}
        </div>
      </section>
    </div>
  );
}

function UsersPanel() {
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"user" | "admin">("user");
  const [link, setLink] = useState<string | null>(null);

  const load = useCallback(() => {
    void api
      .get<AdminUser[]>("/admin/users")
      .then(setUsers)
      .catch(() => setUsers([]));
  }, []);
  useEffect(load, [load]);

  async function invite() {
    try {
      const res = await api.post<{ url: string }>("/admin/invites", { email, role });
      setLink(res.url);
      setEmail("");
      toast.success("Invite created — copy the link below");
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Could not create the invite");
    }
  }

  async function patch(u: AdminUser, body: Partial<AdminUser>) {
    try {
      await api.patch(`/admin/users/${u.id}`, body);
      load();
    } catch (e) {
      toast.error(e instanceof ApiError ? e.message : "Update failed");
    }
  }

  return (
    <div className="space-y-5">
      <section className="rounded-lg border p-3">
        <Label className="mb-2 block">Invite someone</Label>
        <div className="flex flex-wrap items-center gap-2">
          <Input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="person@company.com"
            className="max-w-xs"
          />
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as "user" | "admin")}
            className="h-9 rounded-md border border-input bg-background px-2 text-sm"
            aria-label="Role"
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <Button onClick={invite} disabled={!email.includes("@")}>
            <Plus />
            Create invite
          </Button>
        </div>
        {link && (
          <div className="mt-2 flex items-center gap-2 rounded-md bg-muted p-2">
            <code className="flex-1 truncate text-xs">{link}</code>
            <Button
              variant="ghost"
              size="iconSm"
              aria-label="Copy invite link"
              onClick={() => {
                void navigator.clipboard.writeText(link);
                toast.success("Copied");
              }}
            >
              <Copy />
            </Button>
          </div>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          There is no email sending — send the link yourself. It expires in 7 days.
        </p>
      </section>

      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full text-sm">
          <thead className="border-b bg-muted/40 text-xs text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left font-medium">Email</th>
              <th className="px-3 py-2 text-left font-medium">Role</th>
              <th className="px-3 py-2 text-right font-medium">Quota</th>
              <th className="px-3 py-2 text-right font-medium">Today</th>
              <th className="px-3 py-2 text-left font-medium">Active</th>
            </tr>
          </thead>
          <tbody>
            {(users ?? []).map((u) => (
              <tr key={u.id} className="border-b last:border-0">
                <td className="px-3 py-2">{u.email}</td>
                <td className="px-3 py-2">
                  <Badge variant={u.role === "admin" ? "default" : "secondary"}>{u.role}</Badge>
                </td>
                <td className="px-3 py-2 text-right">
                  <Input
                    type="number"
                    defaultValue={u.daily_quota}
                    onBlur={(e) => {
                      const v = Number(e.target.value);
                      if (v !== u.daily_quota) void patch(u, { daily_quota: v });
                    }}
                    className="ml-auto h-7 w-20 text-right"
                    aria-label={`Daily quota for ${u.email}`}
                  />
                </td>
                <td className="px-3 py-2 text-right tabular">{u.scrapes_today}</td>
                <td className="px-3 py-2">
                  <Checkbox checked={u.active} onCheckedChange={(v) => void patch(u, { active: v === true })} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SeedPanel() {
  const [rows, setRows] = useState<Company[] | null>(null);
  const [urls, setUrls] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    void api
      .get<Company[]>("/admin/seed")
      .then(setRows)
      .catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);

  async function add() {
    const list = urls.split(/[\n,]/).map((u) => u.trim()).filter(Boolean);
    if (!list.length) return;
    setBusy(true);
    try {
      await api.post("/admin/seed", { urls: list.slice(0, 50) });
      setUrls("");
      load();
      toast.success("Added to the default feed");
    } finally {
      setBusy(false);
    }
  }

  async function loadDefaults() {
    setBusy(true);
    try {
      const res = await api.post<{ status: string }[]>("/admin/seed/defaults");
      toast.success(`Registered ${res.length} shipped seed companies`);
      load();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-2">
        <Input
          value={urls}
          onChange={(e) => setUrls(e.target.value)}
          placeholder="https://boards.greenhouse.io/acme"
          className="max-w-md font-mono text-xs"
        />
        <Button onClick={add} disabled={busy || !urls.trim()}>
          <Plus />
          Add
        </Button>
        <Button variant="outline" onClick={loadDefaults} disabled={busy}>
          {busy && <Loader2 className="animate-spin" />}
          Load shipped list
        </Button>
      </div>

      <div className="overflow-x-auto rounded-lg border">
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
            {(rows ?? []).map((c) => (
              <tr key={c.id} className="border-b last:border-0">
                <td className="max-w-[26ch] truncate px-3 py-2">{c.name ?? c.careers_url}</td>
                <td className="px-3 py-2">{sourceLabel(c.ats_type)}</td>
                <td className="px-3 py-2 text-right tabular">{c.job_count.toLocaleString()}</td>
                <td className="whitespace-nowrap px-3 py-2 text-muted-foreground">{timeAgo(c.last_scraped_at)}</td>
                <td className="px-3 py-2">
                  <Badge variant={c.status === "ok" ? "success" : c.status === "new" ? "secondary" : "warning"}>
                    {c.status.replace(/_/g, " ")}
                  </Badge>
                </td>
                <td className="px-3 py-2 text-right">
                  <Button
                    variant="ghost"
                    size="iconSm"
                    aria-label="Remove from seed list"
                    onClick={async () => {
                      await api.del(`/admin/seed/${c.id}`);
                      load();
                    }}
                  >
                    <Trash2 />
                  </Button>
                </td>
              </tr>
            ))}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-3 py-4 text-center text-muted-foreground">
                  No seed companies yet — load the shipped list to fill the default feed.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function FlagsPanel() {
  const [flags, setFlags] = useState<Record<string, boolean> | null>(null);
  useEffect(() => {
    void api
      .get<Record<string, boolean>>("/admin/flags")
      .then(setFlags)
      .catch(() => {});
  }, []);

  async function toggle(key: string, value: boolean) {
    setFlags(await api.patch<Record<string, boolean>>("/admin/flags", { [key]: value }));
  }

  if (!flags) return <Loader2 className="size-5 animate-spin text-muted-foreground" />;

  return (
    <div className="max-w-md space-y-2">
      {Object.entries(flags).map(([key, on]) => (
        <label key={key} className="flex cursor-pointer items-center gap-3 rounded-md border p-3">
          <Checkbox checked={on} onCheckedChange={(v) => void toggle(key, v === true)} />
          <span className="text-sm font-medium capitalize">{sourceLabel(key)}</span>
          <Badge variant={on ? "success" : "outline"} className="ml-auto">
            {on ? "on" : "off"}
          </Badge>
        </label>
      ))}
      <p className="text-xs text-muted-foreground">
        Turning a board off stops new scrapes of it and hides its toggle for everyone.
      </p>
    </div>
  );
}
