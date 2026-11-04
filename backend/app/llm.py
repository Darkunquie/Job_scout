"""Local LLM (Ollama) — the last resort, never the first.

Two jobs, both optional. Everything here degrades to "did nothing" when Ollama is not running, so
the scraper and the worker behave exactly as before if the model is missing.

  Tier 4   a careers page no tier could read: let the model say which of the page's own links are
           job postings. It picks indexes, we supply the URLs, so it cannot invent one.
  enrich   fill employment type / experience / salary on jobs whose description states them but the
           regexes missed. Runs in worker idle time only, and never overwrites a scraped value.
"""
import asyncio
import json
import logging
import re
import time
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

from . import db
from .config import LLM_ENABLED, LLM_MODEL, LLM_TIMEOUT, OLLAMA_URL
from .normalize import _EMP, FX_INR, PERIOD_MULT

log = logging.getLogger("llm")

MAX_LINKS = 400          # a careers page worth reading lists its jobs well inside this
MIN_JOBS = 3             # fewer than this is noise, not a job board — see the Qualtrics misfire
DESC_CHARS = 2500        # ~600 tokens: pay and experience are stated near the top or not at all
EMPLOYMENT = ("Full-time", "Part-time", "Contract", "Internship", "Apprenticeship", "Temporary")

_down_until = 0.0        # don't retry a dead Ollama on every single job


async def ask_json(prompt: str, timeout: float = LLM_TIMEOUT):
    """One completion, forced to JSON. Returns None if Ollama is off, slow, or answers nonsense."""
    global _down_until
    if not LLM_ENABLED or time.monotonic() < _down_until:
        return None
    body = {"model": LLM_MODEL, "prompt": prompt, "format": "json", "stream": False,
            "options": {"temperature": 0, "num_ctx": 8192}}
    try:
        async with httpx.AsyncClient(timeout=timeout) as c:
            r = await c.post(f"{OLLAMA_URL}/api/generate", json=body)
            r.raise_for_status()
            return json.loads(r.json()["response"])
    except (httpx.ConnectError, httpx.ConnectTimeout):
        _down_until = time.monotonic() + 60  # Ollama is not up; stop knocking for a minute
        log.info("ollama unreachable at %s — LLM steps skipped", OLLAMA_URL)
    except Exception as e:  # noqa: BLE001 — a bad generation is a miss, never a crash
        log.warning("llm call failed: %s", e)
    return None


# ───────────────────────── Tier 4: read a page's links ─────────────────────────
def page_links(html: str, base_url: str, cap: int = MAX_LINKS) -> list[dict]:
    """Every distinct same-page link with visible text, in document order."""
    out, seen = [], set()
    for a in HTMLParser(html).css("a[href]"):
        text = " ".join(a.text(separator=" ").split())
        href = urljoin(base_url, a.attributes.get("href") or "").split("#")[0]
        if not text or len(text) > 120 or not href.startswith("http") or href in seen:
            continue
        seen.add(href)
        out.append({"text": text, "url": href})
        if len(out) >= cap:
            break
    return out


_PROMPT = """You are reading the links of a company careers page.

{listing}

Which of these links is an individual job posting (one open role someone can apply to)?
Ignore navigation, departments, locations, filters, login, legal and social links.

Reply with JSON only: {{"jobs": [{{"i": <index>, "title": "<role name>", "location": "<place or null>"}}]}}
Copy the title and the location from the link text. Do not invent either.
If none of the links are job postings, reply {{"jobs": []}}."""


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def pick_jobs(answer, links: list[dict]) -> list[dict]:
    """Model answer -> job rows, keeping only what the page actually says.

    The model chooses an index; the URL comes from our own list. A title or location it did not copy
    from that link's text is dropped, so a hallucinated role cannot reach the database.
    """
    rows, seen = [], set()
    for j in (answer or {}).get("jobs") or []:
        if not isinstance(j, dict) or not isinstance(j.get("i"), int):
            continue
        if not 0 <= j["i"] < len(links):
            continue
        link = links[j["i"]]
        if link["url"] in seen:
            continue
        title = str(j.get("title") or "").strip()
        if not title or _norm(title) not in _norm(link["text"]):
            title = link["text"]          # model paraphrased: trust the page, not the model
        loc = str(j.get("location") or "").strip()
        if loc and _norm(loc) not in _norm(link["text"]):
            loc = ""                      # same rule for the place
        seen.add(link["url"])
        rows.append({"title": title, "url": link["url"], "location": loc or None})
    return rows if len(rows) >= MIN_JOBS else []


async def jobs_from_page(html: str, base_url: str) -> list[dict]:
    links = page_links(html, base_url)
    if len(links) < MIN_JOBS:
        return []
    # The path goes in as well: on a board the postings share a shape (/jobs/Careers/<id>), and that
    # pattern is what lets the model spot the rest once it has recognised one.
    listing = "\n".join(f'{i}. {l["text"]}  [{urlparse(l["url"]).path}]' for i, l in enumerate(links))
    return pick_jobs(await ask_json(_PROMPT.format(listing=listing)), links)


# ───────────────────────── enrichment: fields the regexes missed ─────────────────────────
_ENRICH_PROMPT = """Read this job posting and extract only what it states in writing.

Title: {title}
---
{description}
---

Reply with JSON only:
{{"employment_type": {{"value": one of {emp}, "quote": "the sentence that says so"}} or null,
  "experience": {{"min": whole years, "max": upper end or null, "quote": "the sentence that says so"}} or null,
  "salary": {{"min": number, "max": number or null, "currency": "3-letter code",
             "period": one of ["hour","week","month","year"], "quote": "the sentence that says so"}} or null}}

Every quote must be copied word for word from the posting above.
Use null when the posting does not state something. Never estimate, infer or guess a typical value."""


def _int(v, lo, hi):
    return v if isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi else None


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
        return None
    return float(v)


def _grounded(block, description: str) -> str | None:
    """The quote this value came from, but only if the posting really contains it.

    A 3B model answers "Full-time, 5 years" for any senior-sounding title whether the posting says so
    or not — measured, not feared. Shape checks cannot see that; an unquotable claim can.
    """
    if not isinstance(block, dict):
        return None
    raw = str(block.get("quote") or "")
    # Compare on the normalised text so punctuation and whitespace never decide it, but hand back the
    # quote as written: normalising turns "$120,000" into "120 000", which would read as two numbers.
    q = _norm(raw)
    return raw if len(q) >= 12 and q in _norm(description) else None


def _numbers(text) -> set[int]:
    """Every number printed in a piece of text, separators folded in: "$120,000" -> 120000."""
    out = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", str(text)):
        try:
            out.add(int(float(m.group(0).replace(",", ""))))
        except ValueError:
            pass
    return out


def clean_fields(answer, description: str) -> dict:
    """Keep a value only when it is the right shape AND quotable from the posting."""
    a = answer if isinstance(answer, dict) else {}
    out: dict = {}

    emp = a.get("employment_type")
    quote = _grounded(emp, description)
    # The quote must name the arrangement itself: "40 hours a week" is a real sentence but it is the
    # model doing the arithmetic, and that is the inference this guard exists to stop.
    if quote and (v := emp.get("value")) in EMPLOYMENT and re.search(dict(_EMP)[v], quote, re.I):
        out["employment_type"] = v

    exp = a.get("experience")
    if quote := _grounded(exp, description):
        lo, hi = _int(exp.get("min"), 0, 25), _int(exp.get("max"), 0, 30)
        if hi is not None and lo is not None and hi < lo:
            hi = None
        # the number has to be printed in the sentence, not deduced from the seniority of the title
        nums = _numbers(quote)
        if lo is not None and lo in nums and (hi is None or hi in nums):
            out["exp_min"], out["exp_max"] = lo, hi

    sal = a.get("salary")
    if quote := _grounded(sal, description):
        s_lo, s_hi = _num(sal.get("min")), _num(sal.get("max"))
        cur, per = str(sal.get("currency") or "").upper(), str(sal.get("period") or "").lower()
        nums = _numbers(quote)
        shown = all(int(v) in nums for v in (s_lo, s_hi) if v)
        if (s_lo or s_hi) and cur in FX_INR and per in PERIOD_MULT and shown:
            if s_lo and s_hi and s_hi < s_lo:
                s_lo, s_hi = s_hi, s_lo
            mid = (s_lo or s_hi) if not (s_lo and s_hi) else (s_lo + s_hi) / 2
            out |= {"salary_min": s_lo or s_hi, "salary_max": s_hi or s_lo, "salary_currency": cur,
                    "salary_period": per, "salary_inr_year": round(mid * FX_INR[cur] * PERIOD_MULT[per])}
    return out


_MISSING = ("employment_type IS NULL", "exp_min IS NULL", "salary_min IS NULL")


async def enrich_jobs(limit: int = 4) -> int:
    """Fill blank fields on jobs whose description states them. Worker idle work only.

    Writes a column only when it is still NULL: a value the source published always wins over the
    model's reading of the prose.
    """
    if not LLM_ENABLED:
        return 0
    rows = await db.fetch(
        f"""SELECT id, title, description FROM jobs
            WHERE status='active' AND enriched_at IS NULL AND description <> ''
              AND ({" OR ".join(_MISSING)})
            ORDER BY id LIMIT %s""", limit)
    if not rows:
        return 0
    filled = 0
    for r in rows:
        desc = (r["description"] or "")[:DESC_CHARS]  # ground against exactly the text the model saw
        fields = clean_fields(
            await ask_json(_ENRICH_PROMPT.format(title=r["title"], description=desc,
                                                 emp=json.dumps(list(EMPLOYMENT)))), desc)
        sets = ", ".join(f"{k} = COALESCE({k}, %s)" for k in fields)
        await db.execute(f"UPDATE jobs SET {sets + ', ' if sets else ''}enriched_at = now() WHERE id = %s",
                         *fields.values(), r["id"])
        filled += bool(fields)
    log.info("enriched %d/%d jobs", filled, len(rows))
    return len(rows)  # rows read, not rows changed: the worker only needs to know it had work to do


if __name__ == "__main__":
    html = """<a href="/careers/jobs/1">Senior Backend Engineer, Pune</a>
              <a href="/careers/jobs/2">Data Analyst</a><a href="/careers/jobs/3">QA Lead</a>
              <a href="/about">About us</a><a href="/careers/jobs/1?src=nav">Senior Backend Engineer, Pune</a>"""
    links = page_links(html, "https://x.example/careers")
    assert [l["url"] for l in links][:2] == ["https://x.example/careers/jobs/1", "https://x.example/careers/jobs/2"], links
    assert len(links) == 5, links  # the ?src= duplicate is a different URL; dedupe happens on pick

    good = {"jobs": [{"i": 0, "title": "Senior Backend Engineer", "location": "Pune"},
                     {"i": 1, "title": "Data Analyst", "location": None},
                     {"i": 2, "title": "QA Lead", "location": "Mars"}]}
    rows = pick_jobs(good, links)
    assert len(rows) == 3 and rows[0]["url"].endswith("/jobs/1") and rows[0]["location"] == "Pune", rows
    assert rows[2]["location"] is None, "a location not printed on the link is dropped"

    made_up = {"jobs": [{"i": i, "title": "Chief Vibes Officer", "location": None} for i in (0, 1, 2)]}
    assert [r["title"] for r in pick_jobs(made_up, links)] == \
        ["Senior Backend Engineer, Pune", "Data Analyst", "QA Lead"], "titles must come from the page"
    dupes = {"jobs": [{"i": 0, "title": "Senior Backend Engineer"}] * 3}
    assert pick_jobs(dupes, links) == [], "the same link three times is still one job"
    assert pick_jobs({"jobs": [{"i": 99, "title": "x"}]}, links) == [], "index outside the list"
    assert pick_jobs({"jobs": [{"i": 0, "title": "Senior Backend Engineer"}]}, links) == [], "one hit is not a board"
    assert pick_jobs({"jobs": []}, links) == [] and pick_jobs(None, links) == []

    desc = ("We are hiring a Full-time Backend Engineer in Pune. "
            "You have 5 to 8 years of experience building services. "
            "The range for this role is $120,000 - $150,000 per year.")

    full = {"employment_type": {"value": "Full-time", "quote": "We are hiring a Full-time Backend Engineer in Pune."},
            "experience": {"min": 5, "max": 8, "quote": "You have 5 to 8 years of experience building services."},
            "salary": {"min": 120000, "max": 150000, "currency": "USD", "period": "year",
                       "quote": "The range for this role is $120,000 - $150,000 per year."}}
    got = clean_fields(full, desc)
    assert got["employment_type"] == "Full-time" and (got["exp_min"], got["exp_max"]) == (5, 8), got
    assert got["salary_inr_year"] == round(135000 * 84), got

    # The failure this guard exists for, taken from a real run: qwen2.5:3b answered Full-time and
    # "5 to 10 years" for an Okta account-executive posting that states neither.
    invented = {"employment_type": {"value": "Full-time", "quote": "This is a full-time position."},
                "experience": {"min": 5, "max": 10, "quote": "Requires 5 to 10 years of experience."}}
    assert clean_fields(invented, "A short posting that says none of that.") == {}, "unquotable claims are dropped"

    # Quote is real, but the number in it is not the number claimed.
    assert clean_fields({"experience": {"min": 7, "quote": "You have 5 to 8 years of experience building services."}},
                        desc) == {}, "the years must be printed in the sentence"
    # Quote is real and mentions hours, but it never names the arrangement.
    assert clean_fields({"employment_type": {"value": "Full-time", "quote": "You have 5 to 8 years of experience building services."}},
                        desc) == {}, "the quote must name the arrangement"
    # Right shape, wrong vocabulary and ranges.
    assert clean_fields({"employment_type": {"value": "Permanent", "quote": "We are hiring a Full-time Backend Engineer in Pune."}},
                        desc) == {}, "vocabulary is fixed"
    assert clean_fields({"salary": {"min": "competitive", "currency": "USD", "period": "year",
                                    "quote": "The range for this role is $120,000 - $150,000 per year."}}, desc) == {}
    assert clean_fields({"salary": {"min": 120000, "currency": "XYZ", "period": "year",
                                    "quote": "The range for this role is $120,000 - $150,000 per year."}}, desc) == {}
    assert clean_fields(None, desc) == {} and clean_fields("nope", desc) == {}
    assert _numbers("$120,000 - $150,000 per year") == {120000, 150000}, _numbers("$120,000")

    print("llm OK")
