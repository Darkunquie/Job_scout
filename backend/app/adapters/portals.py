"""Enterprise portals: Workday (hidden CXS API) and Eightfold PCSX (Microsoft and others)."""
import asyncio
import logging
import re

from .base import Blocked, Unsupported, client, detail_retry, get_json, html_to_text, parse_date, raw_job, request
from .generic import jsonld

log = logging.getLogger("portals")

WD_PAGE = 20      # Workday returns HTTP 400 above 20
WD_CAP = 2000     # Workday search stops reporting/serving past ~2000 results
# A location split is the one that actually reaches jobs the unfiltered search will not show.
WD_PREFERRED = ("locationMainGroup", "locationCountry", "Location_Country", "locationHierarchy1")


def _buckets(facet: dict) -> list[dict]:
    return [v for v in facet.get("values") or [] if v.get("id") and v.get("count")]


def pick_facet(facets, total: int) -> dict | None:
    """The facet worth partitioning by, or None to settle for the first WD_CAP jobs.

    Two tests, and the second one is the whole point.

    Every bucket must fit under the cap, or paging it hits the same ceiling we are trying to escape.
    And the buckets must *cover* the catalogue — add up to at least the capped total. Workday offers
    facets that are not partitions at all: `distance` is a search radius, and with no location set
    Accenture reports five buckets of one job each while the search still returns everything. Pick it
    and you re-list the same 2,000 jobs five times for nothing. Coverage is what separates a real
    split from a filter that happens to have few values.
    """
    usable = [f for f in facets or []
              if (vals := _buckets(f)) and all(v["count"] < WD_CAP for v in vals)
              and sum(v["count"] for v in vals) >= total]
    by_name = {f.get("facetParameter"): f for f in usable}
    return next((by_name[n] for n in WD_PREFERRED if n in by_name), usable[0] if usable else None)


async def workday(slug, extra, progress):
    tenant, wd = extra["tenant"], extra["wd"]
    site = slug.rsplit("/", 1)[-1]          # slug is "tenant/site"; the URLs want just the site
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}"
    sem = asyncio.Semaphore(3)
    async with client(headers={"Content-Type": "application/json"}) as c:

        async def list_all(facets: dict, seen: set[str]) -> tuple[list, dict]:
            """Page one search. `seen` spans the whole run and keeps the postings unique."""
            posts, offset, total, first = [], 0, None, None
            while total is None or offset < total:
                body = {"appliedFacets": facets, "limit": WD_PAGE, "offset": offset, "searchText": ""}
                d = await get_json(c, "POST", f"{api}/jobs", json=body, delay=0.5 if offset else 0)
                first = first or d
                if total is None:
                    total = d.get("total") or 0  # only page 0 carries the real total
                # Workday slips in entries without externalPath; they are not jobs we can open
                served = [j for j in (d.get("jobPostings") or []) if j.get("externalPath")]
                fresh = [p for p in served if p["externalPath"] not in seen]
                seen.update(p["externalPath"] for p in fresh)
                posts += fresh
                offset += WD_PAGE  # by the page Workday served, not the part of it that was new
                # Report unique postings for the whole run. Buckets overlap heavily, so a per-bucket
                # count sends the number backwards and a healthy run reads as a stuck one.
                await progress(len(seen), None)
                if not served:
                    break
            return posts, first or {}

        seen: set[str] = set()
        posts, first = await list_all({}, seen)
        total = first.get("total") or 0
        if total >= WD_CAP:
            if facet := pick_facet(first.get("facets"), total):
                buckets = _buckets(facet)
                log.info("workday %s: %d visible at the cap, partitioning by %s across %d buckets",
                         slug, total, facet.get("facetParameter"), len(buckets))
                for v in buckets:
                    more, _ = await list_all({facet["facetParameter"]: [v["id"]]}, seen)
                    posts += more
                    await progress(len(seen), None)
            else:
                # No facet both covers the catalogue and fits under the cap, so this run saw whatever
                # arbitrary slice the search chose to show. Tell the runner, or close-diff will retire
                # every job that happened to fall outside it and reopen them on the next refresh.
                extra["incomplete"] = True
                log.info("workday %s: capped at %d with no usable partition — sample only, not the board",
                         slug, total)
        await progress(len(posts), len(posts))

        known = extra.get("known") or set()
        for p in posts:
            if p["externalPath"] in known:
                yield raw_job(external_id=p["externalPath"], title=p["title"], touch_only=True)

        async def get(p):
            d = await get_json(c, "GET", f"{api}{p['externalPath']}", delay=0.3)
            return d.get("jobPostingInfo") or {}

        async def detail(p):
            async with sem:
                return p, await detail_retry(get, p)

        for coro in asyncio.as_completed([detail(p) for p in posts if p["externalPath"] not in known]):
            p, info = await coro
            locs = [info.get("location")] + (info.get("additionalLocations") or []) if info else []
            yield raw_job(
                external_id=p["externalPath"], title=info.get("title") or p["title"],
                url=info.get("externalUrl") or f"{host}/{site}{p['externalPath']}",
                apply_url=info.get("externalUrl") or f"{host}/{site}{p['externalPath']}",
                company_name=(extra.get("company") or tenant).title(), description=html_to_text(info.get("jobDescription")),
                location_raw=info.get("location") or p.get("locationsText"), locations=[l for l in locs if l],
                country_hint=(info.get("country") or {}).get("descriptor"), workplace_hint=info.get("remoteType"),
                employment_type=info.get("timeType"), posted_at=parse_date(info.get("startDate") or p.get("postedOn")),
            )


async def eightfold(slug, extra, progress):
    base, domain = extra["base"], extra["domain"]
    sem = asyncio.Semaphore(2)
    async with client(headers={"User-Agent": "Mozilla/5.0 (compatible; JobScoutBot/0.1)"}) as c:
        positions, start, total = [], 0, None
        try:
            while total is None or start < total:
                d = (await get_json(c, "GET", f"{base}/api/pcsx/search",
                                    params={"domain": domain, "query": "", "location": "", "start": start},
                                    delay=0.4 if start else 0))["data"]
                total = d.get("count") or 0
                page = d.get("positions") or []
                positions += page
                start += len(page) or 10
                await progress(len(positions), total)
                if not page:
                    break
        except Blocked as blocked:
            if positions:
                raise
            # Some white-label tenants (Qualcomm) refuse the search API to bots but publish every job
            # page in a robots-allowed sitemap with JobPosting markup. Read that instead.
            # ponytail: re-reads every job page each refresh; skip known URLs if the host starts throttling
            try:
                async for r in jsonld(f"{base}/careers", extra.get("company") or slug.title(), progress,
                                    cap=5000, job_path=re.compile(r"/careers/job/\d")):
                    yield r
            except Unsupported:
                raise blocked from None  # no sitemap (Microsoft): stay "blocked" so it retries, not "unsupported" forever
            return

        known = extra.get("known") or set()
        for p in positions:
            if str(p["id"]) in known:
                yield raw_job(external_id=str(p["id"]), title=p["name"], touch_only=True)

        async def get(p):
            d = await get_json(c, "GET", f"{base}/api/pcsx/position_details",
                               params={"position_id": p["id"], "domain": domain, "hl": "en"}, delay=0.3)
            return d.get("data") or {}

        async def detail(p):
            async with sem:
                return p, await detail_retry(get, p)

        for coro in asyncio.as_completed([detail(p) for p in positions if str(p["id"]) not in known]):
            p, info = await coro
            url = base + (p.get("positionUrl") or f"/careers/job/{p['id']}")
            yield raw_job(
                external_id=str(p["id"]), title=p["name"], url=url, apply_url=url,
                company_name=extra.get("company") or slug.title(), department=p.get("department"),
                description=html_to_text(info.get("jobDescription")),
                location_raw="; ".join(p.get("standardizedLocations") or p.get("locations") or []),
                locations=p.get("standardizedLocations") or p.get("locations"), workplace_hint=p.get("workLocationOption"),
                posted_at=parse_date(p.get("postedTs") or p.get("creationTs")),
            )


if __name__ == "__main__":
    # Accenture's real facet list, counts as the API returns them: 41,630 jobs in the catalogue but
    # only 2,000 visible, and `distance` reports five buckets of one job each.
    accenture = [
        {"facetParameter": "jobFamilyGroup", "values": [{"id": "a", "count": 19246}, {"id": "b", "count": 4353}]},
        {"facetParameter": "workerSubType", "values": [{"id": "w", "count": 2770}, {"id": "x", "count": 2571}]},
        {"facetParameter": "timeType", "values": [{"id": "ft", "count": 41599}, {"id": "pt", "count": 31}]},
        {"facetParameter": "locationMainGroup", "values": []},
        {"facetParameter": "distance", "values": [{"id": f"d{i}", "count": 1} for i in range(5)]},
    ]
    assert pick_facet(accenture, 2000) is None, "a radius filter is not a partition"

    real = {"facetParameter": "locationCountry",
            "values": [{"id": "IN", "count": 800}, {"id": "US", "count": 900}, {"id": "IE", "count": 400}]}
    assert pick_facet([real], 2000) is real, "buckets that cover the catalogue are a partition"
    assert pick_facet(accenture + [real], 2000) is real, "a real split beats giving up"

    other = {"facetParameter": "jobFamilyGroup", "values": [{"id": "eng", "count": 1200}, {"id": "ops", "count": 900}]}
    assert pick_facet([other, real], 2000) is real, "location is preferred over an equally valid facet"
    assert pick_facet([other], 2000) is other, "but any covering facet beats giving up"
    assert pick_facet([{"facetParameter": "x", "values": [{"id": "a", "count": 2000}]}], 2000) is None, "bucket at the cap"
    assert pick_facet([{"facetParameter": "x", "values": [{"id": "a", "count": 1999}]}], 2000) is None, "does not cover"
    assert pick_facet([], 2000) is None and pick_facet(None, 2000) is None
    assert _buckets({"values": [{"id": "a", "count": 5}, {"id": "b"}, {"count": 3}]}) == [{"id": "a", "count": 5}]
    print("portals OK")
