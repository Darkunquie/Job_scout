"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTheme } from "next-themes";
import { Building2, Compass, FileText, KanbanSquare, LogOut, Moon, Search, Shield, Sun } from "lucide-react";
import { api, type Me } from "@/lib/api";
import { Badge, Button, Input } from "@/components/ui/primitives";

const NAV = [
  { href: "/", label: "Jobs", icon: Search },
  { href: "/companies", label: "Companies", icon: Building2 },
  { href: "/tracker", label: "Tracker", icon: KanbanSquare },
  { href: "/resume", label: "Resume", icon: FileText },
];

/** Search lives in the URL (?q=) so it survives reloads and can be shared. */
function GlobalSearch() {
  const router = useRouter();
  const params = useSearchParams();
  const [value, setValue] = useState(params.get("q") ?? "");
  const box = useRef<HTMLInputElement>(null);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = document.activeElement?.tagName;
      if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA") {
        e.preventDefault();
        box.current?.focus();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const next = new URLSearchParams(Array.from(params.entries()));
    next.delete("add");
    if (value.trim()) next.set("q", value.trim());
    else next.delete("q");
    router.replace(`/?${next.toString()}`);
  }

  return (
    <form onSubmit={submit} className="relative hidden min-w-0 flex-1 sm:block">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
      <Input
        ref={box}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder="Search title, company, skill…"
        className="h-8 pl-8 pr-10"
        aria-label="Search jobs"
      />
      <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border px-1.5 font-mono text-xs text-muted-foreground md:block">
        /
      </kbd>
    </form>
  );
}

export function TopNav({ me }: Readonly<{ me: Me }>) {
  const pathname = usePathname();
  const router = useRouter();
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const region = me.prefs
    ? me.prefs.region_mode === "india"
      ? "India"
      : me.prefs.region_mode === "all"
        ? "All countries"
        : `${me.prefs.countries.length} countries`
    : "—";

  async function logout() {
    await api.post("/auth/logout");
    router.replace("/login");
  }

  return (
    <header className="flex h-12 shrink-0 items-center gap-3 border-b bg-card px-3">
      <Link href="/" className="flex shrink-0 items-center gap-2">
        <Compass className="size-5 text-primary" />
        <span className="hidden text-sm font-semibold tracking-tight lg:inline">JobScout</span>
      </Link>

      <GlobalSearch />

      <nav className="flex shrink-0 items-center gap-0.5">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Button key={href} asChild variant={active ? "secondary" : "ghost"} size="sm" className="px-2">
              <Link href={href} title={label}>
                <Icon />
                <span className="hidden md:inline">{label}</span>
              </Link>
            </Button>
          );
        })}
        {me.role === "admin" && (
          <Button asChild variant={pathname.startsWith("/admin") ? "secondary" : "ghost"} size="sm" className="px-2">
            <Link href="/admin" title="Admin">
              <Shield />
              <span className="hidden md:inline">Admin</span>
            </Link>
          </Button>
        )}
      </nav>

      <Link href="/onboarding" title="Change region" className="hidden shrink-0 lg:block">
        <Badge variant="outline">{region}</Badge>
      </Link>

      <Button
        variant="ghost"
        size="icon"
        aria-label="Toggle dark mode"
        onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      >
        {mounted && resolvedTheme === "dark" ? <Sun /> : <Moon />}
      </Button>
      <Button variant="ghost" size="icon" onClick={logout} aria-label="Sign out" title={me.email}>
        <LogOut />
      </Button>
    </header>
  );
}
