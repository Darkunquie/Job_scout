"""Local embeddings: fastembed (ONNX, CPU) + pgvector. No API key, no GPU, no per-call cost.

The model is ~130 MB on first use and is cached under the fastembed default cache dir.
"""
import asyncio
import logging
import re

from . import db
from .normalize import _SKILL_RE

log = logging.getLogger("embed")
MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384
BATCH = 128
EMBED_BATCH = 16           # rows per ONNX pass; this, not BATCH, sets peak memory
DESC_CHARS = 2000          # ~512 tokens: title + skills + the top of the description is enough for ranking

_model = None


def _get():
    global _model
    if _model is None:
        from fastembed import TextEmbedding  # heavy import (onnxruntime) — only when embedding runs
        log.info("loading %s", MODEL)
        _model = TextEmbedding(MODEL)
    return _model


def to_vec(values) -> str:
    """pgvector literal — avoids needing the pgvector-python adapter for psycopg."""
    return "[" + ",".join(f"{float(x):.6f}" for x in values) + "]"


def encode(texts: list[str]) -> list[str]:
    # onnxruntime keeps its memory arena at the size of the largest batch it has seen: one pass of
    # 128 x 512 tokens pinned the worker at 4.5 GB. 16 at a time costs little speed on CPU.
    return [to_vec(v) for v in _get().embed(texts, batch_size=EMBED_BATCH)]


def job_text(r) -> str:
    return "\n".join(filter(None, [r["title"], r["department"], ", ".join(r["skills"] or []),
                                   (r["description"] or "")[:DESC_CHARS]]))


def skills_of(text: str) -> list[str]:
    return [k for k, rx in _SKILL_RE.items() if rx.search(text or "")]


def overlap(resume_skills, job_skills) -> float:
    rs = set(resume_skills or [])
    js = set(job_skills or [])
    return len(rs & js) / len(js) if js else 0.0


async def embed_jobs(limit: int = BATCH) -> int:
    """Embed active jobs that have no vector yet (new or changed since the last run)."""
    rows = await db.fetch("SELECT id, title, department, skills, description FROM jobs "
                          "WHERE embedding IS NULL AND status='active' ORDER BY id LIMIT %s", limit)
    if not rows:
        return 0
    vecs = await asyncio.to_thread(encode, [job_text(r) for r in rows])
    async with db.pool.connection() as conn:
        async with conn.transaction():
            for r, v in zip(rows, vecs):
                await conn.execute("UPDATE jobs SET embedding = %s::vector WHERE id=%s", (v, r["id"]))
    return len(rows)


async def embed_resume(task: dict):
    """Worker task: turn stored resume text into skills + one vector."""
    from . import tasks
    rid = task["payload"]["resume_id"]
    r = await db.fetchone("SELECT id, text FROM resumes WHERE id=%s", rid)
    if not r:
        return await tasks.finish(task["id"], False, "resume deleted")
    text = r["text"] or ""
    skills = skills_of(text)
    (vec,) = await asyncio.to_thread(encode, [text[:8000]])
    await db.execute("UPDATE resumes SET skills=%s, embedding=%s::vector WHERE id=%s", skills, vec, rid)
    await tasks.finish(task["id"], True, phase="done", skills=len(skills))


# ───────────────────────── resume text extraction ─────────────────────────
MAX_UPLOAD = 10 * 1024 * 1024


def extract_text(filename: str, data: bytes) -> str:
    """PDF / DOCX / TXT -> plain text. Raises ValueError on anything else or an unreadable file."""
    name = (filename or "").lower()
    if len(data) > MAX_UPLOAD:
        raise ValueError("File is larger than 10 MB")
    if name.endswith(".pdf"):
        import io

        from pypdf import PdfReader
        text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
    elif name.endswith(".docx"):
        import io

        import docx
        text = "\n".join(p.text for p in docx.Document(io.BytesIO(data)).paragraphs)
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", "replace")
    else:
        raise ValueError("Upload a PDF, DOCX or TXT file")
    text = re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()
    if len(text) < 50:
        raise ValueError("Could not read any text from that file (is it a scanned image?)")
    return text


if __name__ == "__main__":
    assert to_vec([0.5, -0.25]) == "[0.500000,-0.250000]"
    assert skills_of("Built pipelines in Python and Spark on AWS") == ["Python", "AWS", "Spark"], skills_of("Python Spark AWS")
    assert overlap(["Python", "AWS"], ["Python", "Kafka"]) == 0.5
    assert overlap(["Python"], []) == 0.0 and overlap([], ["Python"]) == 0.0
    assert job_text({"title": "Data Engineer", "department": "Core", "skills": ["Python"],
                     "description": "x" * 5000}).endswith("x" * 10)
    assert len(job_text({"title": "T", "department": None, "skills": [], "description": "y" * 9000})) == DESC_CHARS + 2
    try:
        extract_text("a.exe", b"x" * 100)
        raise SystemExit("should have rejected .exe")
    except ValueError:
        pass
    assert extract_text("cv.txt", b"Senior  engineer\n\n\n\nPython, SQL and AWS experience across teams") \
        == "Senior engineer\n\nPython, SQL and AWS experience across teams"
    print("embed OK (model not loaded)")
