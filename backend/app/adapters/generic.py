"""Tier 2 for unknown career sites: schema.org JobPosting from the page, then from the sitemap."""
import asyncio
import hashlib
import json
import logging
import re
from urllib.parse import urlparse

from selectolax.parser import HTMLParser

from .. import db
from .base import Blocked, Unsupported, client, html_to_text, parse_date, raw_job, request

log = logging.getLogger("generic")
MAX_PAGES = 300          # per-company cap on job pages fetched from a sitemap
MAX_SITEMAPS = 8         # per level; a sitemap index on a big site can name dozens
_JOB_PATH = re.compile(  # "/job-123" counts; "/opening-balances-for-customers" must not
    r"/(?:jobs?|vacanc\w*)[-/]|/(?:careers?|positions?|openings?|stellenangebote|offres)/", re.I)
_SITEMAP_HINT = re.compile(r"job|career|vacanc|position", re.I)


def _rank(urls) -> list[str]:
    """Job-looking sitemaps first — on a big corporate site the rest are product pages."""
    uniq = list(dict.fromkeys(urls))
    return sorted(uniq, key=lambda u: 0 if _SITEMAP_HINT.search(u) else 1)


def _flatten(node):
    """JSON-LD comes as an object, a list, or an @graph; walk it all."""
    if isinstance(node, list):
        for n in node:
            yield from _flatten(n)
    elif isinstance(node, dict):
        if g := node.get("@graph"):
            yield from _flatten(g)
        yield node


def _types(obj) -> set[str]:
    t = obj.get("@type") or obj.get("type") or ""
    return {str(x).lower() for x in (t if isinstance(t, list) else [t])}


def job_postings(html: str) -> list[dict]:
    tree = HTMLParser(html)
    out = []
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except (ValueError, TypeError):
            continue
        out += [_repair(o, tree) for o in _flatten(data) if "jobposting" in _types(o)]
    return out


def _repair(p: dict, tree) -> dict:
    """WordPress SEO plugins often fill JobPosting fields with the site name (Intellias: title, region and
    description all "Intellias"). Treat a field equal to the company as missing; take the title from <h1>."""
    org = p.get("hiringOrganization")
    org = str((org.get("name") if isinstance(org, dict) else org) or "").strip().lower()
    if not org:
        return p

    def junk(v):
        return isinstance(v, str) and (v.strip().lower() == org or v.strip().lower().startswith(f"what it's like to work at {org}".replace("'", "’")))

    if junk(p.get("title")) and (h1 := tree.css_first("h1")):
        p["title"] = h1.text(strip=True)
    if junk(p.get("description")):
        p["description"] = ""
    loc = _first(p.get("jobLocation"))
    addr = loc.get("address") if isinstance(loc, dict) else None
    if isinstance(addr, dict) and all(junk(v) or not isinstance(v, str) for k, v in addr.items() if k != "@type"):
        p.pop("jobLocation")
    return p


def _card_locations(html: str) -> dict[str, tuple[str, str | None]]:
    """Listing cards -> {job url: ("Poland, Ukraine", "Remote")}. The site cuts long lists ("Poland, Por..."):
    keep the countries shown in full, drop the cut one."""
    out = {}
    for a in HTMLParser(html).css("a.card_item[href]"):
        if loc := a.css_first(".location"):
            parts = [x.strip() for x in loc.text(separator=" ").replace(" ", " ").split(",")]
            parts = [x for x in parts if x and not x.endswith("...")]
            work = a.css_first(".type_work")
            out[a.attributes["href"].rstrip("/")] = (", ".join(parts), work and work.text(strip=True) or None)
    return out


async def _intellias(c) -> dict[str, tuple[str, str | None]]:
    """Intellias job pages carry no location, only its listing cards do; they load 12 at a time via admin-ajax."""
    out = {}
    for page in range(1, 40):
        r = await request(c, "POST", "https://career.intellias.com/wp-admin/admin-ajax.php",
                          data={"action": "fly_vacancies", "page": page}, delay=0.3)
        d = r.json()
        out |= _card_locations("".join(d.get("posts") or []))
        if d.get("end") or not d.get("posts"):
            break
    return out


# ponytail: per-site location readers for sites whose job pages omit location; add an entry per such site
_CARD_LOCATIONS = {"career.intellias.com": _intellias}


def _first(v):
    return v[0] if isinstance(v, list) and v else v


def _addr(posting) -> tuple[str | None, str | None, str | None]:
    """jobLocation -> (raw string, country hint, city hint)."""
    loc = _first(posting.get("jobLocation")) or {}
    if isinstance(loc, str):
        return loc, None, None
    a = loc.get("address") or {}
    if isinstance(a, str):
        return a, None, None
    country = a.get("addressCountry")
    country = country.get("name") if isinstance(country, dict) else country
    city, region = a.get("addressLocality"), a.get("addressRegion")
    return ", ".join(filter(None, [city, region, country])) or loc.get("name"), country, city


def _salary(posting):
    s = posting.get("baseSalary") or {}
    if isinstance(s, (int, float)):
        return s, s, None, None
    v = s.get("value") or {}
    if isinstance(v, (int, float)):
        v = {"value": v}
    one = v.get("value")
    return v.get("minValue") or one, v.get("maxValue") or one, s.get("currency") or v.get("currency"), v.get("unitText")


def to_raw(posting: dict, page_url: str, fallback_company: str) -> dict | None:
    title = (posting.get("title") or "").strip()
    if not title:
        return None
    url = str(posting.get("url") or page_url)
    ident = posting.get("identifier")
    if isinstance(ident, dict):
        ident = ident.get("value") or ident.get("name")
    org = posting.get("hiringOrganization") or {}
    emp = posting.get("employmentType")
    exp = posting.get("experienceRequirements")
    desc = posting.get("description") or ""
    loc_raw, country, city = _addr(posting)
    lo, hi, cur, per = _salary(posting)
    return raw_job(
        external_id=str(ident or hashlib.sha1(url.encode()).hexdigest()[:16]), title=title,
        url=url, apply_url=posting.get("applicationUrl") or url,
        company_name=(org.get("name") if isinstance(org, dict) else org) or fallback_company,
        department=_first(posting.get("occupationalCategory")) or None,
        description=html_to_text(desc) if "<" in desc else desc,
        location_raw=loc_raw, country_hint=country, city_hint=city,
        remote_hint="telecommute" in str(posting.get("jobLocationType") or "").lower() or None,
        employment_type=" ".join(emp) if isinstance(emp, list) else emp,
        posted_at=parse_date(posting.get("datePosted")),
        salary_min=lo, salary_max=hi, salary_currency=cur, salary_period=per,
        exp_hint=exp.get("monthsOfExperience") if isinstance(exp, dict) else exp,
    )


async def _sitemap_urls(c, start: str, cap: int = MAX_PAGES, job_path=_JOB_PATH) -> list[str]:
    """Collect job-looking page URLs from robots.txt / sitemap.xml (one level of sitemap index)."""
    u = urlparse(start)
    root = f"{u.scheme}://{u.netloc}"
    candidates = [f"{root}/sitemap.xml", f"{root}/sitemap_index.xml", f"{root}/job-sitemap.xml"]
    try:
        robots = (await request(c, "GET", f"{root}/robots.txt")).text
        candidates = re.findall(r"(?im)^\s*sitemap:\s*(\S+)", robots) + candidates
    except Exception:  # noqa: BLE001 — no robots.txt is normal
        pass

    seen, jobs, queue, depth = set(), [], _rank(candidates), 0
    while queue and depth < 2 and len(jobs) < cap:
        nxt = []
        for sm in queue[:MAX_SITEMAPS]:  # big sites list dozens of sitemaps; job-hinted ones come first
            if sm in seen:
                continue
            seen.add(sm)
            try:
                body = (await request(c, "GET", sm, delay=0.2)).text
            except Exception:  # noqa: BLE001 — a missing/broken sitemap just means no Tier 2 here
                continue
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", body)
            if "<sitemapindex" in body[:2000]:
                nxt += [x for x in locs if _SITEMAP_HINT.search(x)] or locs[:3]
            else:
                jobs += [x for x in locs if job_path.search(urlparse(x).path)]
            if len(jobs) >= cap:
                break
        queue, depth = _rank(nxt), depth + 1
    return list(dict.fromkeys(jobs))[:cap]


async def jsonld(start, company, progress, cap: int = MAX_PAGES, job_path=_JOB_PATH):
    """JSON-LD on the careers page -> JSON-LD on sitemap job pages. Raises Unsupported if neither works."""
    urls = []
    async with client() as c:
        postings = [(p, start) for p in job_postings((await request(c, "GET", start)).text)]
        await progress(len(postings), None)

        if len(postings) < 2:  # a single posting usually means we landed on one job page, not a board
            urls = await _sitemap_urls(c, start, cap, job_path)
            if not urls and not postings:
                raise Unsupported("no JobPosting markup and no job sitemap")
            sem = asyncio.Semaphore(4)
            done = failed = 0

            async def fetch(u):
                nonlocal done, failed
                async with sem:
                    try:
                        html = (await request(c, "GET", u, delay=0.25)).text
                    except Exception:  # noqa: BLE001 — skip a dead job page, keep the rest
                        failed += 1
                        return []
                done += 1
                if done % 20 == 0:
                    await progress(done, len(urls))
                return [(p, u) for p in job_postings(html)]

            for chunk in await asyncio.gather(*[fetch(u) for u in urls]):
                postings += chunk

    if not postings:
        raise Unsupported("job pages carry no JobPosting markup")
    await progress(len(postings), len(postings))
    card_locs = {}
    if reader := _CARD_LOCATIONS.get(urlparse(start).hostname or ""):
        try:
            async with client() as c:
                card_locs = await reader(c)
        except Exception as e:  # noqa: BLE001 — locations are a bonus; never fail the scrape over them
            log.warning("card location reader failed for %s: %s", start, e)
    seen = set()
    for p, page_url in postings:
        if (r := to_raw(p, page_url, company)) and r["external_id"] not in seen:
            seen.add(r["external_id"])
            if not r["location_raw"] and (card := card_locs.get(r["url"].rstrip("/"))):
                r["location_raw"], r["locations"] = card[0], card[0].split(", ")
                r["workplace_hint"] = r["workplace_hint"] or card[1]
            yield r
    if urls and failed > len(urls) // 20:
        # Rows above are already saved; raising marks the run incomplete so close-diff can't
        # close jobs whose pages were merely refused (throttling), and the host backs off.
        raise Blocked(f"{failed}/{len(urls)} job pages refused — partial scrape, retrying later")


async def _save(host: str, recipe: dict):
    await db.execute("""
        INSERT INTO recipes (host, mode, request, pagination, field_map, verified_at)
        VALUES (%s,%s,%s,%s,%s, now())
        ON CONFLICT (host) DO UPDATE SET mode=EXCLUDED.mode, request=EXCLUDED.request,
          pagination=EXCLUDED.pagination, field_map=EXCLUDED.field_map, verified_at=now(), fail_count=0""",
        host, recipe["mode"], json.dumps(recipe["request"]), json.dumps(recipe["pagination"]),
        json.dumps(recipe["field_map"]))


async def generic(slug, extra, progress):
    """Smart mode: Tier 2 JSON-LD/sitemap, else a saved or freshly learned Tier 3 recipe."""
    from ..sniffer import item_to_raw, learn, replay  # deferred: pulls in Playwright, and breaks an import cycle

    start, host = extra["url"], slug
    company = extra.get("company") or slug
    found = 0
    try:
        async for r in jsonld(start, company, progress):
            found += 1
            yield r
    except Unsupported:
        pass
    if found:
        return

    rec = await db.fetchone("SELECT * FROM recipes WHERE host=%s", host)
    if rec and rec["mode"] == "http":
        recipe = {"mode": rec["mode"], "request": rec["request"], "pagination": rec["pagination"],
                  "field_map": rec["field_map"]}
        try:
            async for r in replay(recipe, start, company, progress):
                found += 1
                yield r
        except Exception as e:  # noqa: BLE001 — site changed shape; fall through and re-learn once
            log.warning("recipe replay failed for %s: %s", host, e)
        if found:
            await db.execute("UPDATE recipes SET verified_at=now(), fail_count=0 WHERE host=%s", host)
            return
        await db.execute("UPDATE recipes SET fail_count=fail_count+1 WHERE host=%s", host)

    out, page = await learn(start)
    if not out:
        # Tier 4, last resort: there is no feed to replay, so let the local model read the page's own
        # links. It returns indexes into that list, never URLs, so it cannot invent a posting. The
        # markup is the browser's, not a plain GET: Zoho's board ships 1.8 MB of HTML with no anchors
        # in it until the page has run.
        from ..llm import jobs_from_page

        for row in await jobs_from_page(page, start):
            found += 1
            yield raw_job(external_id=hashlib.sha1(row["url"].encode()).hexdigest()[:16],
                          title=row["title"], url=row["url"], apply_url=row["url"],
                          company_name=company, location_raw=row["location"])
        if found:
            log.info("tier 4 (llm) read %d jobs from %s", found, host)
            return
        raise Unsupported("no job list found in the page's own network traffic")
    if not isinstance(out, tuple):  # the site's feed links to a known ATS: use that adapter from now on
        from . import ADAPTERS
        if cid := extra.get("company_id"):
            try:
                await db.execute("UPDATE companies SET ats_type=%s, ats_slug=%s, ats_extra=%s WHERE id=%s",
                                 out.ats, out.slug, json.dumps(out.extra), cid)
            except Exception as e:  # noqa: BLE001 — that ATS board already has its own row; just scrape it
                log.info("company %s already tracked as %s/%s: %s", cid, out.ats, out.slug, e)
        async for r in ADAPTERS[out.ats](out.slug, dict(out.extra, company=company), progress):
            yield r
        return
    recipe, items = out
    await _save(host, recipe)
    if recipe["mode"] == "http":
        async for r in replay(recipe, start, company, progress):
            found += 1
            yield r
    else:  # token/cookie-bound API: use what the browser already showed us
        await progress(len(items), len(items))
        for it in items:
            if r := item_to_raw(it, recipe["field_map"], start, company):
                found += 1
                yield r
    if not found:
        raise Unsupported("learned recipe returned no jobs")


if __name__ == "__main__":
    html = """<script type="application/ld+json">{"@context":"https://schema.org","@graph":[
      {"@type":"JobPosting","title":"Backend Engineer","identifier":{"value":"BE-7"},
       "description":"<p>5+ years with Python</p>","datePosted":"2026-10-01","employmentType":["FULL_TIME"],
       "hiringOrganization":{"@type":"Organization","name":"Acme"},"jobLocationType":"TELECOMMUTE",
       "jobLocation":{"address":{"addressLocality":"Bengaluru","addressRegion":"KA","addressCountry":"IN"}},
       "baseSalary":{"@type":"MonetaryAmount","currency":"INR",
                     "value":{"minValue":2000000,"maxValue":3000000,"unitText":"YEAR"}},
       "url":"https://acme.com/jobs/be-7"}]}</script>"""
    (p,) = job_postings(html)
    r = to_raw(p, "https://acme.com/careers", "Fallback")
    assert r["external_id"] == "BE-7" and r["title"] == "Backend Engineer" and r["company_name"] == "Acme", r
    assert r["location_raw"] == "Bengaluru, KA, IN" and r["country_hint"] == "IN" and r["city_hint"] == "Bengaluru", r
    assert r["remote_hint"] and r["employment_type"] == "FULL_TIME" and r["salary_max"] == 3000000, r
    assert r["description"] == "5+ years with Python", r
    assert job_postings("<html>no markup</html>") == []
    bad = """<h1>Senior Software Engineer</h1><script type="application/ld+json">{"@type":"JobPosting","title":"Intellias",
      "hiringOrganization":{"name":"Intellias"},"description":"Intellias",
      "jobLocation":{"@type":"Place","address":{"@type":"PostalAddress","addressRegion":"Intellias"}}}</script>"""
    r = to_raw(job_postings(bad)[0], "https://x.example/vacancy/1", "X")
    assert r["title"] == "Senior Software Engineer" and not r["location_raw"] and not r["description"], r
    card = """<a href="https://career.intellias.com/vacancy/x-1/" class="stb-item card_item"><div class="card_title">X</div>
      <div class="position font14">Senior</div><div class="location font14 df aic"><img src="pin.svg"> <span>Poland, Ukraine, Por...</span> </div>
      <div class="type_work">Remote</div></a>"""
    assert _card_locations(card) == {"https://career.intellias.com/vacancy/x-1": ("Poland, Ukraine", "Remote")}, _card_locations(card)
    print("generic OK")
