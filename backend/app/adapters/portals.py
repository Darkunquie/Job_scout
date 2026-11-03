"""Enterprise portals: Workday (hidden CXS API) and Eightfold PCSX (Microsoft and others)."""
import asyncio
import re

from .base import Blocked, Unsupported, client, detail_retry, get_json, html_to_text, parse_date, raw_job, request
from .generic import jsonld

WD_PAGE = 20      # Workday returns HTTP 400 above 20
WD_CAP = 2000     # Workday search stops reporting/serving past ~2000 results


async def workday(slug, extra, progress):
    tenant, wd = extra["tenant"], extra["wd"]
    site = slug.rsplit("/", 1)[-1]          # slug is "tenant/site"; the URLs want just the site
    host = f"https://{tenant}.{wd}.myworkdayjobs.com"
    api = f"{host}/wday/cxs/{tenant}/{site}"
    sem = asyncio.Semaphore(3)
    async with client(headers={"Content-Type": "application/json"}) as c:

        async def list_all(facets: dict) -> tuple[list, dict]:
            posts, offset, total, first = [], 0, None, None
            while total is None or offset < total:
                body = {"appliedFacets": facets, "limit": WD_PAGE, "offset": offset, "searchText": ""}
                d = await get_json(c, "POST", f"{api}/jobs", json=body, delay=0.5 if offset else 0)
                first = first or d
                if total is None:
                    total = d.get("total") or 0  # only page 0 carries the real total
                # Workday slips in entries without externalPath; they are not jobs we can open
                page = [j for j in (d.get("jobPostings") or []) if j.get("externalPath")]
                posts += page
                offset += WD_PAGE
                await progress(len(posts), None)  # listing a big tenant takes minutes — keep the bar alive
                if not page:
                    break
            return posts, first or {}

        posts, first = await list_all({})
        if (first.get("total") or 0) >= WD_CAP:
            # ponytail: partition by the first facet whose buckets each fit under the cap; deeper nesting if a bucket still hits it
            for f in first.get("facets") or []:
                vals = [v for v in f.get("values") or [] if v.get("id") and v.get("count")]
                if vals and all(v["count"] < WD_CAP for v in vals):
                    seen = {p["externalPath"] for p in posts}
                    for v in vals:
                        more, _ = await list_all({f["facetParameter"]: [v["id"]]})
                        posts += [p for p in more if p["externalPath"] not in seen and not seen.add(p["externalPath"])]
                        await progress(len(posts), None)
                    break
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
