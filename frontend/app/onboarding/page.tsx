"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Compass, Loader2 } from "lucide-react";
import { api, type Meta, type Prefs, type RegionMode } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import { Button, Label, Separator } from "@/components/ui/primitives";
import { Checkbox } from "@/components/ui/controls";
import { CountryPicker } from "@/components/country-picker";

const MODES: { value: RegionMode; label: string; hint: string }[] = [
  { value: "india", label: "India", hint: "Jobs located in India" },
  { value: "countries", label: "Specific countries", hint: "Pick the countries you'd move to" },
  { value: "all", label: "All countries", hint: "Everything we scrape" },
];

export default function OnboardingPage() {
  const router = useRouter();
  const { me, loading } = useMe({ requireOnboarded: false });
  const [meta, setMeta] = useState<Meta | null>(null);
  const [mode, setMode] = useState<RegionMode>("india");
  const [countries, setCountries] = useState<string[]>([]);
  const [includeRemote, setIncludeRemote] = useState(true);
  const [remoteScope, setRemoteScope] = useState("any");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!me) return;
    void api.get<Meta>("/meta").then(setMeta);
    if (me.prefs) {
      setMode(me.prefs.region_mode);
      setCountries(me.prefs.countries);
      setIncludeRemote(me.prefs.include_remote);
      setRemoteScope(me.prefs.remote_scope);
    }
  }, [me]);

  async function save() {
    setBusy(true);
    try {
      const prefs: Prefs = {
        region_mode: mode,
        countries: mode === "countries" ? countries : [],
        include_remote: includeRemote,
        remote_scope: remoteScope,
        boards: me?.prefs?.boards ?? {},
      };
      await api.put("/me/prefs", prefs);
      router.replace("/");
    } finally {
      setBusy(false);
    }
  }

  if (loading || !me) {
    return (
      <main className="flex min-h-dvh items-center justify-center">
        <Loader2 className="size-5 animate-spin text-muted-foreground" />
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-lg px-4 py-10">
      <div className="mb-8 flex items-center gap-2">
        <Compass className="size-5 text-primary" />
        <span className="text-lg font-semibold tracking-tight">JobScout</span>
      </div>

      <h1 className="text-xl font-semibold tracking-tight">Where do you want jobs from?</h1>
      <p className="mt-1 text-sm text-muted-foreground">You can change this at any time from the top bar.</p>

      <div className="mt-6 space-y-2">
        {MODES.map((m) => (
          <label
            key={m.value}
            className={`flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors ${
              mode === m.value ? "border-primary bg-primary/5" : "hover:bg-accent"
            }`}
          >
            <input
              type="radio"
              name="region"
              className="mt-1 accent-[hsl(var(--primary))]"
              checked={mode === m.value}
              onChange={() => setMode(m.value)}
            />
            <span>
              <span className="block text-sm font-medium">{m.label}</span>
              <span className="block text-xs text-muted-foreground">{m.hint}</span>
            </span>
          </label>
        ))}
      </div>

      {mode === "countries" && meta && (
        <div className="mt-4">
          <Label className="mb-2 block">Countries</Label>
          <CountryPicker countries={meta.countries} value={countries} onChange={setCountries} />
        </div>
      )}

      <Separator className="my-6" />

      <label className="flex items-center gap-2">
        <Checkbox checked={includeRemote} onCheckedChange={(v) => setIncludeRemote(v === true)} />
        <span className="text-sm font-medium">Include remote jobs</span>
      </label>

      {includeRemote && (
        <div className="mt-3 flex flex-wrap gap-2 pl-6">
          {[
            { v: "any", l: "Anywhere" },
            { v: "IN", l: "Remote in India" },
            { v: "mine", l: "Remote in my countries" },
          ].map((o) => (
            <button
              key={o.v}
              type="button"
              onClick={() => setRemoteScope(o.v)}
              className={`rounded-md border px-2.5 py-1 text-xs transition-colors ${
                remoteScope === o.v ? "border-primary bg-primary/10 text-primary" : "hover:bg-accent"
              }`}
            >
              {o.l}
            </button>
          ))}
        </div>
      )}

      <Button className="mt-8 w-full" onClick={save} disabled={busy || (mode === "countries" && !countries.length)}>
        {busy && <Loader2 className="animate-spin" />}
        Continue
      </Button>
    </main>
  );
}
