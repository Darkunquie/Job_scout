"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ApiError, api, type Me } from "./api";

/** Current user. Sends anyone without a session to /login, and anyone unonboarded to /onboarding. */
export function useMe({ requireOnboarded = true } = {}) {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const m = await api.get<Me>("/auth/me");
      setOffline(false);
      setMe(m);
      if (requireOnboarded && !m.onboarded) router.replace("/onboarding");
    } catch (e) {
      // 401 means "sign in". Anything else means the backend is unreachable, which is a different
      // problem and must not render as a blank page.
      if (e instanceof ApiError && e.status === 401) router.replace("/login");
      else setOffline(true);
    } finally {
      setLoading(false);
    }
  }, [requireOnboarded, router]);

  useEffect(() => {
    void reload();
  }, [reload]);

  return { me, loading, offline, reload };
}

/**
 * Match a CSS media query from JS.
 *
 * Needed because Radix portals its dialog content to document.body: a `xl:hidden` class on the
 * wrapper does not hide it, so the detail sheet has to be left unmounted rather than hidden.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(query);
    const sync = () => setMatches(mql.matches);
    sync();
    mql.addEventListener("change", sync);
    return () => mql.removeEventListener("change", sync);
  }, [query]);
  return matches;
}

/** Debounce any fast-changing value (filter inputs, the search box). */
export function useDebounced<T>(value: T, ms = 300): T {
  const [out, setOut] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setOut(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return out;
}

/**
 * Follow running scrape tasks. One SSE stream per task; the server closes it when the task ends.
 * Returns tasks newest-first so the progress rows under the scrape bar stay stable.
 */
export function useTaskStream(ids: number[]) {
  const [tasks, setTasks] = useState<Record<number, TaskState>>({});

  useEffect(() => {
    // Open every stream this effect owns and close exactly those on cleanup. Do not guard with a
    // ref of "already opened" ids: StrictMode runs effect → cleanup → effect in dev, so the guard
    // would skip reopening the streams the cleanup just closed and no progress would ever arrive.
    const sources = ids.map((id) => {
      const es = new EventSource(`/api/scrape/tasks/${id}/stream`, { withCredentials: true });
      es.onmessage = (ev) => {
        const data = JSON.parse(ev.data) as TaskState;
        setTasks((prev) => ({ ...prev, [id]: data }));
        if (data.status === "done" || data.status === "error") es.close();
      };
      es.onerror = () => es.close();
      return es;
    });
    return () => sources.forEach((s) => s.close());
  }, [ids]);

  return tasks;
}

export interface TaskState {
  status: "queued" | "running" | "done" | "error";
  progress: { phase?: string; found?: number; total?: number | null; inserted?: number; closed?: number };
  error: string | null;
}
