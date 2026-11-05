"""Public job-board APIs of hosted ATSs. One function per ATS: async generator of raw_job dicts."""
import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from .base import client, detail_retry, get_json, html_to_text, parse_date, raw_job, request

log = logging.getLogger("ats")


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


# ───────────────────────── SAP SuccessFactors ─────────────────────────
SF_API = "/services/recruiting/v1/jobs"
SF_PAGE = 10        # the API ignores pageSize and always returns ten
SF_MAX_PAGES = 1500


def _sf_one(v):
    """SuccessFactors returns most fields as one-element lists, some as plain strings."""
    if isinstance(v, list):
        v = v[0] if v else None
    return v.strip() if isinstance(v, str) else v


def _sf_date(v):
    """Start dates come as M/D/YY in the site's own locale, which parse_date does not read."""
    s = _sf_one(v)
    if not s:
        return None
    try:
        return datetime.strptime(str(s), "%m/%d/%y").replace(tzinfo=timezone.utc)
    except ValueError:
        return parse_date(s)


async def successfactors(slug, extra, progress):
    """SAP SuccessFactors (Wipro and most large Indian IT).

    One POST per page of ten, paged by pageNumber. The search results carry no description and the
    job pages render theirs in the browser, so these rows are title, place and date only — worth
    having at 7,000 jobs a tenant, but do not expect skills off the back of them.
    """
    base = extra.get("base") or f"https://{slug}"
    found, total = 0, None
    async with client(headers={"Content-Type": "application/json"}) as c:
        for page in range(SF_MAX_PAGES):
            body = {"locale": "en_US", "pageNumber": page, "sortBy": "", "keywords": "", "location": "",
                    "facetFilters": {}, "brand": "", "skills": [], "categoryId": 0, "alertId": "",
                    "rcmCandidateId": ""}
            d = await get_json(c, "POST", f"{base}{SF_API}", json=body, delay=0.3 if page else 0)
            hits = [h.get("response") or {} for h in (d.get("jobSearchResult") or [])]
            if total is None:
                total = d.get("totalJobs") or 0
            if not hits:
                break
            for j in hits:
                jid = _sf_one(j.get("id"))
                title = _sf_one(j.get("unifiedStandardTitle"))
                if not jid or not title:
                    continue
                found += 1
                url = f"{base}/job/{_sf_one(j.get('unifiedUrlTitle')) or _sf_one(j.get('urlTitle'))}/{jid}-en_US"
                # jobLocationShort reads "Hyderabad, IND-36, IND, 500032<br/>" — keep the city and the
                # country name, drop the internal region code and the postcode they wrap it in.
                city, country = _sf_one(j.get("sfstd_jobLocation_obj")), _sf_one(j.get("jobLocationCountry"))
                place = ", ".join(filter(None, [city, _sf_one(j.get("jobLocationState")), country]))
                yield raw_job(
                    external_id=str(jid), title=title, url=url, apply_url=url,
                    company_name=extra.get("company"), department=_sf_one(j.get("custRMKMappingPicklist")),
                    location_raw=place or html_to_text(_sf_one(j.get("jobLocationShort"))),
                    city_hint=city, country_hint=country,
                    salary_currency=_sf_one(j.get("currency")),
                    posted_at=_sf_date(j.get("unifiedStandardStart")),
                )
            await progress(found, total)
            if total and found >= total:
                break
    await progress(found, found)


# ───────────────────────── Zoho Recruit ─────────────────────────
ZR_API = "/recruit/v2/public/Job_Openings"
ZR_SUSPECT = 200   # a round number back from a one-shot endpoint is worth a second look
# Tenants publish different location fields: careers.zohocorp.com sends Country1, the APAC site
# sends City/State/Country. Take whichever are present, in the order a person would read them.
ZR_PLACE = ("City", "State", "Province", "Country", "Country1", "Location")


def _zr_true(v) -> bool:
    return v is True or str(v).strip().lower() == "true"


async def zohorecruit(slug, extra, progress):
    """Zoho Recruit career sites, whether on zohorecruit.* or the company's own domain.

    One request: the endpoint returns the whole board, carries no paging counters in `info`, and
    answers 400 to a `page` parameter, so there is nothing to page through.
    """
    base = extra.get("base") or f"https://{slug}"
    async with client(headers={"Referer": base}) as c:
        d = await get_json(c, "GET", f"{base}{ZR_API}",
                           params={"pagename": extra.get("pagename") or "Careers", "source": "CareerSite",
                                   "extra_fields": '["Remote_Job","Job_Description"]'})
    rows = d.get("data") or []
    if len(rows) >= ZR_SUSPECT:
        # No tenant this big has been seen; if one shows up, check the board's own count before
        # trusting this number, because a silent cap would look exactly like a complete answer.
        log.warning("zoho recruit %s returned %d jobs in one call — verify none were dropped", slug, len(rows))
    await progress(len(rows), len(rows))

    for j in rows:
        # Publish=False is a draft. Keep_on_Career_Site is NOT a visibility flag despite the name:
        # both of Zoho's own live postings carry it as False while appearing on the site.
        if not _zr_true(j.get("Publish", True)):
            continue
        title = j.get("Posting_Title") or j.get("Job_Opening_Name")
        if not title:
            continue
        place = [str(j[k]).strip() for k in ZR_PLACE if j.get(k)]
        desc = j.get("Job_Description") or ""
        yield raw_job(
            external_id=str(j["id"]), title=title, url=j.get("$url"), apply_url=j.get("$url"),
            company_name=extra.get("company"), department=j.get("Industry"),
            description=html_to_text(desc) if "<" in desc else desc,
            location_raw=", ".join(place) or None, city_hint=j.get("City"),
            country_hint=j.get("Country") or j.get("Country1"),
            remote_hint=_zr_true(j.get("Remote_Job")) or None,
            employment_type=j.get("Job_Type"), posted_at=parse_date(j.get("Date_Opened") or j.get("Created_Time")),
        )


if __name__ == "__main__":
    # SuccessFactors field shapes, exactly as careers.wipro.com returns them: most values arrive as
    # one-element lists, the titles as plain strings, and some jobs carry no location at all.
    assert _sf_one(["Hyderabad"]) == "Hyderabad" and _sf_one("Configurator - L4") == "Configurator - L4"
    assert _sf_one([]) is None and _sf_one(None) is None and _sf_one(["  spaced  "]) == "spaced"
    assert _sf_date(["2/25/25"]).strftime("%Y-%m-%d") == "2025-02-25"
    assert _sf_date(["2026-01-09T00:00:00Z"]).strftime("%Y-%m-%d") == "2026-01-09"  # falls back to parse_date
    assert _sf_date([]) is None and _sf_date(["not a date"]) is None
    print("ats OK")
