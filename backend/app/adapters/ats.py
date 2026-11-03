"""Public job-board APIs of hosted ATSs. One function per ATS: async generator of raw_job dicts."""
import asyncio
import xml.etree.ElementTree as ET

from .base import client, detail_retry, html_to_text, parse_date, raw_job, request


async def greenhouse(slug, extra, progress):
    host = "boards-api.eu.greenhouse.io" if extra.get("eu") else "boards-api.greenhouse.io"
    async with client() as c:
        board = (await request(c, "GET", f"https://{host}/v1/boards/{slug}")).json()
        jobs = (await request(c, "GET", f"https://{host}/v1/boards/{slug}/jobs", params={"content": "true"})).json()["jobs"]
    await progress(len(jobs), len(jobs))
    for j in jobs:
        offices = [o.get("location") or o.get("name") for o in j.get("offices") or []]
        yield raw_job(
            external_id=str(j["id"]), title=j["title"], url=j.get("absolute_url"), apply_url=j.get("absolute_url"),
            company_name=board.get("name") or slug, department=", ".join(d["name"] for d in j.get("departments") or []) or None,
            description=html_to_text(j.get("content")), location_raw=(j.get("location") or {}).get("name"),
            locations=[o for o in offices if o], posted_at=parse_date(j.get("first_published") or j.get("updated_at")),
        )


async def lever(slug, extra, progress):
    host = "api.eu.lever.co" if extra.get("eu") else "api.lever.co"
    skip, found = 0, 0
    async with client() as c:
        while True:
            page = (await request(c, "GET", f"https://{host}/v0/postings/{slug}",
                                  params={"mode": "json", "skip": skip, "limit": 100}, delay=1.0 if skip else 0)).json()
            for j in page:
                cat = j.get("categories") or {}
                sal = j.get("salaryRange") or {}
                desc = "\n\n".join(filter(None, [j.get("descriptionPlain"),
                                                 *[f"{l.get('text')}\n{html_to_text(l.get('content'))}" for l in j.get("lists") or []],
                                                 j.get("additionalPlain")]))
                yield raw_job(
                    external_id=j["id"], title=j["text"], url=j.get("hostedUrl"), apply_url=j.get("applyUrl"),
                    company_name=slug, department=cat.get("team") or cat.get("department"), description=desc,
                    location_raw=cat.get("location"), locations=cat.get("allLocations"), country_hint=j.get("country"),
                    workplace_hint=j.get("workplaceType"), employment_type=cat.get("commitment"),
                    posted_at=parse_date(j.get("createdAt")), salary_min=sal.get("min"), salary_max=sal.get("max"),
                    salary_currency=sal.get("currency"), salary_period=sal.get("interval"),
                )
            found += len(page)
            await progress(found, None)
            if len(page) < 100:
                return
            skip += 100


async def ashby(slug, extra, progress):
    async with client() as c:
        data = (await request(c, "GET", f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
                              params={"includeCompensation": "true"})).json()
    jobs = data.get("jobs") or []
    await progress(len(jobs), len(jobs))
    for j in jobs:
        addr = ((j.get("address") or {}).get("postalAddress") or {})
        comp = next((s for s in ((j.get("compensation") or {}).get("summaryComponents") or [])
                     if s.get("compensationType") == "Salary"), {})
        yield raw_job(
            external_id=j["id"], title=j["title"], url=j.get("jobUrl"), apply_url=j.get("applyUrl"),
            company_name=slug, department=j.get("department") or j.get("team"),
            description=j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml")),
            location_raw=j.get("location"), locations=[s.get("location") for s in j.get("secondaryLocations") or []],
            country_hint=addr.get("addressCountry"), city_hint=addr.get("addressLocality"),
            remote_hint=j.get("isRemote"), workplace_hint=j.get("workplaceType"), employment_type=j.get("employmentType"),
            posted_at=parse_date(j.get("publishedAt")), salary_min=comp.get("minValue"), salary_max=comp.get("maxValue"),
            salary_currency=comp.get("currencyCode"), salary_period=comp.get("interval"),
        )


async def smartrecruiters(slug, extra, progress):
    base = f"https://api.smartrecruiters.com/v1/companies/{slug}/postings"
    sem = asyncio.Semaphore(5)
    async with client() as c:
        items, offset, total = [], 0, None
        while total is None or offset < total:
            page = (await request(c, "GET", base, params={"limit": 100, "offset": offset})).json()
            total = page.get("totalFound", 0)
            items += page.get("content") or []
            offset += 100
            await progress(len(items), total)
            if not page.get("content"):
                break

        known = extra.get("known") or set()
        for p in items:
            if p["id"] in known:
                yield raw_job(external_id=p["id"], title=p["name"], touch_only=True)

        async def get(p):
            return (await request(c, "GET", f"{base}/{p['id']}", delay=0.2)).json()

        async def detail(p):  # description lives on the per-posting endpoint
            async with sem:
                d = await detail_retry(get, p)
            secs = (d.get("jobAd") or {}).get("sections") or {}
            return p, "\n\n".join(html_to_text((secs.get(k) or {}).get("text"))
                                  for k in ("jobDescription", "qualifications", "additionalInformation") if secs.get(k))

        for coro in asyncio.as_completed([detail(p) for p in items if p["id"] not in known]):
            p, desc = await coro
            loc = p.get("location") or {}
            yield raw_job(
                external_id=p["id"], title=p["name"], url=f"https://jobs.smartrecruiters.com/{slug}/{p['id']}",
                apply_url=f"https://jobs.smartrecruiters.com/{slug}/{p['id']}",
                company_name=(p.get("company") or {}).get("name") or slug, department=(p.get("department") or {}).get("label"),
                description=desc, location_raw=loc.get("fullLocation") or ", ".join(filter(None, [loc.get("city"), loc.get("country")])),
                country_hint=loc.get("country"), city_hint=loc.get("city"), remote_hint=loc.get("remote"),
                workplace_hint="hybrid" if loc.get("hybrid") else None,
                employment_type=(p.get("typeOfEmployment") or {}).get("label"),
                exp_hint=(p.get("experienceLevel") or {}).get("label"), posted_at=parse_date(p.get("releasedDate")),
            )


async def workable(slug, extra, progress):
    async with client() as c:
        data = (await request(c, "GET", f"https://apply.workable.com/api/v1/widget/accounts/{slug}",
                              params={"details": "true"})).json()
    jobs = data.get("jobs") or []
    await progress(len(jobs), len(jobs))
    for j in jobs:
        locs = j.get("locations") or []
        first = locs[0] if locs else {}
        yield raw_job(
            external_id=j.get("shortcode") or j["url"], title=j["title"], url=j.get("url") or j.get("shortlink"),
            apply_url=j.get("application_url") or j.get("url"), company_name=data.get("name") or slug,
            department=j.get("department"), description=html_to_text(j.get("description")),
            location_raw=", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")])),
            locations=[", ".join(filter(None, [l.get("city"), l.get("country")])) for l in locs],
            country_hint=first.get("countryCode") or j.get("country"), city_hint=first.get("city") or j.get("city"),
            remote_hint=j.get("telecommuting"), employment_type=j.get("employment_type"),
            posted_at=parse_date(j.get("published_on") or j.get("created_at")),
        )


async def recruitee(slug, extra, progress):
    async with client() as c:
        data = (await request(c, "GET", f"https://{slug}.recruitee.com/api/offers/")).json()
    offers = data.get("offers") or []
    await progress(len(offers), len(offers))
    for o in offers:
        sal = o.get("salary") or {}
        yield raw_job(
            external_id=str(o["id"]), title=o["title"], url=o.get("careers_url"), apply_url=o.get("careers_apply_url"),
            company_name=o.get("company_name") or slug, department=o.get("department"),
            description="\n\n".join(filter(None, [html_to_text(o.get("description")), html_to_text(o.get("requirements"))])),
            location_raw=o.get("location"), country_hint=o.get("country_code"), city_hint=o.get("city"),
            remote_hint=o.get("remote"), workplace_hint="hybrid" if o.get("hybrid") else None,
            employment_type=o.get("employment_type_code"), posted_at=parse_date(o.get("published_at") or o.get("created_at")),
            salary_min=sal.get("min"), salary_max=sal.get("max"), salary_currency=sal.get("currency"), salary_period=sal.get("period"),
        )


async def personio(slug, extra, progress):
    tld = extra.get("tld", "de")
    async with client() as c:
        r = await request(c, "GET", f"https://{slug}.jobs.personio.{tld}/xml", params={"language": "en"})
    positions = ET.fromstring(r.content).findall("position")
    await progress(len(positions), len(positions))
    for p in positions:
        t = lambda k: (p.findtext(k) or "").strip() or None  # noqa: E731
        desc = "\n\n".join(f"{d.findtext('name') or ''}\n{html_to_text(d.findtext('value'))}"
                           for d in p.findall("jobDescriptions/jobDescription")) or t("keywords") or ""
        offices = [t("office")] + [o.text for o in p.findall("additionalOffices/office") if o.text]
        yield raw_job(
            external_id=t("id"), title=t("name"), url=f"https://{slug}.jobs.personio.{tld}/job/{t('id')}",
            apply_url=f"https://{slug}.jobs.personio.{tld}/job/{t('id')}", company_name=t("subcompany") or slug,
            department=t("department"), description=desc, location_raw=t("office"), locations=[o for o in offices if o],
            employment_type=t("employmentType") or t("schedule"), exp_hint=t("seniority") or t("yearsOfExperience"),
            posted_at=parse_date(t("createdAt")),
        )
