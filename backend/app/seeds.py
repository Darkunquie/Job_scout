"""Default-feed companies. Admin-managed afterwards; this is the starting set.

`python -m app.seeds` probes every URL (one cheap request each) and prints which ones still work,
so the list can be pruned when a company moves ATS.
"""
import asyncio
import sys

SEEDS = [
    # ── India HQ ──
    "https://job-boards.greenhouse.io/razorpaysoftwareprivatelimited",
    "https://jobs.lever.co/meesho",
    "https://jobs.lever.co/cred",
    "https://boards.greenhouse.io/groww",
    "https://jobs.ashbyhq.com/tekion",
    "https://boards.greenhouse.io/zetaglobal",
    "https://boards.greenhouse.io/highradius",
    "https://boards.greenhouse.io/netradyne",
    "https://boards.greenhouse.io/druva",
    # ── Large India engineering centres ──
    "https://jobs.careers.microsoft.com/global/en/search",
    "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite",
    "https://salesforce.wd12.myworkdayjobs.com/en-US/External_Career_Site",
    "https://adobe.wd5.myworkdayjobs.com/en-US/external_experienced",
    "https://micron.wd1.myworkdayjobs.com/en-US/External",
    "https://intel.wd1.myworkdayjobs.com/en-US/External",
    "https://philips.wd3.myworkdayjobs.com/en-US/jobs-and-careers",
    "https://pwc.wd3.myworkdayjobs.com/en-US/Global_Experienced_Careers",
    "https://citi.wd5.myworkdayjobs.com/en-US/2",
    "https://target.wd5.myworkdayjobs.com/en-US/targetcareers",
    "https://workday.wd5.myworkdayjobs.com/en-US/Workday",
    "https://boards.greenhouse.io/rubrik",
    "https://boards.greenhouse.io/zscaler",
    "https://boards.greenhouse.io/mongodb",
    "https://boards.greenhouse.io/databricks",
    "https://boards.greenhouse.io/datadog",
    "https://boards.greenhouse.io/twilio",
    "https://boards.greenhouse.io/cloudflare",
    "https://boards.greenhouse.io/okta",
    # ── Global product companies ──
    "https://boards.greenhouse.io/stripe",
    "https://job-boards.greenhouse.io/anthropic",
    "https://boards.greenhouse.io/figma",
    "https://boards.greenhouse.io/reddit",
    "https://boards.greenhouse.io/discord",
    "https://boards.greenhouse.io/robinhood",
    "https://boards.greenhouse.io/coinbase",
    "https://boards.greenhouse.io/gitlab",
    "https://boards.greenhouse.io/dropbox",
    "https://boards.greenhouse.io/instacart",
    "https://boards.greenhouse.io/airbnb",
    "https://boards.greenhouse.io/asana",
    "https://boards.greenhouse.io/elastic",
    "https://boards.greenhouse.io/duolingo",
    "https://boards.greenhouse.io/wise",
    "https://boards.greenhouse.io/samsara",
    "https://boards.greenhouse.io/affirm",
    "https://jobs.lever.co/spotify",
    "https://jobs.lever.co/palantir",
    "https://jobs.ashbyhq.com/openai",
    "https://jobs.ashbyhq.com/ramp",
    "https://jobs.ashbyhq.com/linear",
    "https://jobs.ashbyhq.com/posthog",
    "https://jobs.ashbyhq.com/replit",
    "https://jobs.ashbyhq.com/supabase",
    "https://jobs.ashbyhq.com/clickhouse",
    "https://jobs.ashbyhq.com/cursor",
    "https://jobs.smartrecruiters.com/Ubisoft2",
    "https://apply.workable.com/huggingface",
    "https://bunq.recruitee.com",
    "https://1komma5grad.jobs.personio.de",
]


async def probe(url: str) -> tuple[str, str, str]:
    """One cheap request per company: does this URL still resolve to a readable board?"""
    from .adapters import ADAPTERS
    from .adapters.base import client, get_json
    from .detect import detect

    d = detect(url)
    if not d:
        return url, "no-ats", "detector found no known ATS"
    try:
        if d.ats == "workday":  # listing a big tenant is slow — just read page 0's total
            api = (f"https://{d.extra['tenant']}.{d.extra['wd']}.myworkdayjobs.com"
                   f"/wday/cxs/{d.extra['tenant']}/{d.slug.rsplit('/', 1)[-1]}/jobs")
            async with client(headers={"Content-Type": "application/json"}) as c:
                data = await get_json(c, "POST", api, json={"appliedFacets": {}, "limit": 20, "offset": 0,
                                                            "searchText": ""})
            n = data.get("total") or 0
            return url, ("ok" if n else "empty"), f"workday | {n} jobs"
        if d.ats == "eightfold":
            async with client(headers={"User-Agent": "Mozilla/5.0 (compatible; JobScoutBot/0.1)"}) as c:
                data = await get_json(c, "GET", f"{d.extra['base']}/api/pcsx/search",
                                      params={"domain": d.extra["domain"], "query": "", "location": "", "start": 0})
            n = (data.get("data") or {}).get("count") or 0
            return url, ("ok" if n else "empty"), f"eightfold | {n} jobs"
        async for raw in ADAPTERS[d.ats](d.slug, dict(d.extra), lambda *a: asyncio.sleep(0)):
            return url, "ok", f"{d.ats} | {raw['title'][:60]}"
        return url, "empty", f"{d.ats} | board has no open jobs"
    except Exception as e:  # noqa: BLE001 — a probe failure is the result, not a crash
        return url, "fail", f"{d.ats} | {type(e).__name__}: {e}"[:140]


async def _main():
    sem = asyncio.Semaphore(6)

    async def one(u):
        async with sem:
            return await asyncio.wait_for(probe(u), 90)

    results = await asyncio.gather(*[one(u) for u in SEEDS], return_exceptions=True)
    bad = []
    for url, r in zip(SEEDS, results):
        if isinstance(r, BaseException):
            status, note = "timeout", type(r).__name__
        else:
            _, status, note = r
        print(f"{status:8} {url:72} {note}")
        if status != "ok":
            bad.append(url)
    print(f"\n{len(SEEDS) - len(bad)}/{len(SEEDS)} usable")
    if bad:
        print("prune:", *bad, sep="\n  ")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # live job titles carry any character
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    sys.exit(asyncio.run(_main()))
