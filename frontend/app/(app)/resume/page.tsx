"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CheckCircle2, Loader2, Upload } from "lucide-react";
import { toast } from "sonner";
import { ApiError, api, type Resume } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { Badge, Button } from "@/components/ui/primitives";

export default function ResumePage() {
  const [resume, setResume] = useState<Resume | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null);

  async function load() {
    try {
      setResume(await api.get<Resume>("/resume"));
    } catch {
      setResume(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void load();
  }, []);

  // Embedding happens in the worker; poll until the vector lands.
  useEffect(() => {
    if (!resume || resume.ready) return;
    const t = setInterval(() => void load(), 2000);
    return () => clearInterval(t);
  }, [resume]);

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    try {
      await api.upload("/resume", f);
      toast.success("Resume uploaded — scoring jobs now");
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Could not read that file");
    } finally {
      setBusy(false);
      if (file.current) file.current.value = "";
    }
  }

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-6">
      <h1 className="text-lg font-semibold tracking-tight">Resume match</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        Your resume is turned into a local embedding — nothing leaves this machine, and no AI service is called.
        Jobs then get a match estimate you can sort by.
      </p>

      <div className="mt-6 rounded-lg border p-4">
        {loading ? (
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
        ) : resume ? (
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium">{resume.filename}</span>
              {resume.ready ? (
                <Badge variant="success">
                  <CheckCircle2 className="mr-1 size-3" />
                  ready
                </Badge>
              ) : (
                <Badge variant="warning">
                  <Loader2 className="mr-1 size-3 animate-spin" />
                  scoring…
                </Badge>
              )}
              <span className="ml-auto text-xs text-muted-foreground">uploaded {timeAgo(resume.created_at)}</span>
            </div>

            {resume.skills.length > 0 && (
              <div>
                <p className="mb-1.5 text-xs font-medium text-muted-foreground">
                  Skills we recognised ({resume.skills.length})
                </p>
                <div className="flex flex-wrap gap-1">
                  {resume.skills.map((s) => (
                    <Badge key={s} variant="secondary">
                      {s}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {resume.ready && (
              <p className="text-sm text-muted-foreground">
                Now sort by{" "}
                <Link href="/" className="text-primary underline">
                  Best match
                </Link>{" "}
                on the jobs screen.
              </p>
            )}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No resume uploaded yet.</p>
        )}

        <input ref={file} type="file" accept=".pdf,.docx,.txt,.md" onChange={upload} className="hidden" />
        <Button className="mt-4" onClick={() => file.current?.click()} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : <Upload />}
          {resume ? "Replace resume" : "Upload resume"}
        </Button>
        <p className="mt-2 text-xs text-muted-foreground">PDF, DOCX or TXT, up to 10 MB.</p>
      </div>

      <p className="mt-4 text-xs text-muted-foreground">
        The score is 70% semantic similarity plus 30% skill overlap. Treat it as a ranking aid, not a verdict on
        whether you&apos;ll get the job.
      </p>
    </main>
  );
}
