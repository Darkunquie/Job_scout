"""Careers URL -> (ats_type, slug, extra). Pure functions; no network except find_embedded()."""
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urljoin, urlparse

import httpx

from .config import USER_AGENT


@dataclass
class Detected:
    ats: str
    slug: str
    extra: dict = field(default_factory=dict)


_RULES = [
    # (ats, host regex, path regex) — named groups: slug / extra keys
    ("greenhouse", r"(?:job-)?boards(?:\.eu)?\.greenhouse\.io", r"^/(?:embed/job_board)?(?P<slug>[\w-]+)?"),
    ("lever", r"jobs(?P<eu>\.eu)?\.lever\.co", r"^/(?P<slug>[\w.-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com", r"^/(?P<slug>[^/?#]+)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com", r"^/(?P<slug>[\w-]+)"),
    ("workable", r"apply\.workable\.com", r"^/(?P<slug>[\w-]+)"),
    ("workday", r"(?P<tenant>[\w-]+)\.(?P<wd>wd\d+)\.myworkdayjobs\.com", r"^/(?:[a-z]{2}-[A-Z]{2}/)?(?P<slug>[\w-]+)"),
    ("eightfold", r"(?P<tenant>[\w-]+)\.eightfold\.ai", r""),
]
_HOST_RULES = [
    ("recruitee", r"(?P<slug>[\w-]+)\.recruitee\.com"),
    ("personio", r"(?P<slug>[\w-]+)\.jobs\.personio\.(?P<tld>de|com)"),
]
# Big custom portals that run on a known ATS under their own domain.
_KNOWN_HOSTS = {
    "careers.microsoft.com": Detected("eightfold", "microsoft", {"base": "https://apply.careers.microsoft.com", "domain": "microsoft.com"}),
    "jobs.careers.microsoft.com": Detected("eightfold", "microsoft", {"base": "https://apply.careers.microsoft.com", "domain": "microsoft.com"}),
    "apply.careers.microsoft.com": Detected("eightfold", "microsoft", {"base": "https://apply.careers.microsoft.com", "domain": "microsoft.com"}),
}


def detect(url: str) -> Detected | None:
    u = urlparse(url if "://" in url else "https://" + url)
    host, path = (u.hostname or "").lower(), u.path or "/"
    if host in _KNOWN_HOSTS:
        return _KNOWN_HOSTS[host]
    if "greenhouse.io" in host and (q := parse_qs(u.query).get("for")):
        return Detected("greenhouse", q[0], {"eu": ".eu." in host})
    for ats, host_re, path_re in _RULES:
        hm = re.fullmatch(host_re, host)
        if not hm:
            continue
        extra = {k: v for k, v in hm.groupdict().items() if v}
        if ats == "eightfold":
            return Detected(ats, extra["tenant"], {"base": f"https://{host}", "domain": parse_qs(u.query).get("domain", [""])[0]})
        pm = re.match(path_re, path)
        slug = pm and pm.group("slug")
        if not slug:
            return None
        if ats == "greenhouse":
            extra = {"eu": ".eu." in host}
        if ats == "lever":
            extra = {"eu": bool(extra.get("eu"))}
        if ats == "workday":
            # Site names repeat across tenants ("External" is both Intel's and Micron's), so the
            # tenant has to be part of the identity or two companies collapse into one row.
            slug = f"{extra['tenant']}/{slug}"
        return Detected(ats, slug, extra)
    for ats, host_re in _HOST_RULES:
        if hm := re.fullmatch(host_re, host):
            return Detected(ats, hm.group("slug"), {k: v for k, v in hm.groupdict().items() if k != "slug"})
    return None


_EMBED_RE = re.compile(
    r"https?://(?:[\w-]+\.)*(?:greenhouse\.io|lever\.co|ashbyhq\.com|smartrecruiters\.com|workable\.com|"
    r"recruitee\.com|personio\.(?:de|com)|myworkdayjobs\.com|eightfold\.ai)[^\s\"'<>)\\]*"
)


def assert_public_url(url: str) -> str:
    """SSRF guard: http(s) only, host must resolve to public IPs."""
    u = urlparse(url if "://" in url else "https://" + url)
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("Only http(s) URLs are allowed")
    try:
        addrs = socket.getaddrinfo(u.hostname, None)
    except socket.gaierror:  # the raw "[Errno 11001] getaddrinfo failed" means nothing to a user
        raise ValueError(f"Could not find {u.hostname} — check the address") from None
    for info in addrs:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise ValueError("URL points to a private network address")
    return u.geturl()


async def find_embedded(url: str) -> Detected | None:
    """Fetch a company careers page and look for a linked/iframed ATS board."""
    url = assert_public_url(url)
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=20, max_redirects=5) as c:
        r = await c.get(url)
        if d := _scan(r):
            return d
        # A careers *landing* page (PhonePe, Swiggy) often has no jobs, only a "View jobs" link one level down.
        if (link := jobs_link(r.text, str(r.url))) and link.rstrip("/") != str(r.url).rstrip("/"):
            assert_public_url(link)
            r2 = await c.get(link)
            return _scan(r2) or Detected("generic", r2.url.host, {"url": str(r2.url)})
    return None


def ats_in_text(text: str) -> Detected | None:
    """First known-ATS board referenced in arbitrary text (HTML, or a site's own JSON feed)."""
    for m in _EMBED_RE.finditer(text.replace("\\/", "/")):  # JSON may escape slashes
        if d := detect(m.group(0)):
            return d
    return None


# SuccessFactors career sites run on the company's own domain (careers.wipro.com), so no host rule
# can find them; the markup is what gives them away.
_SF_MARKERS = re.compile(r"successfactors|sapsf\.|/services/recruiting/v\d|rmk-jobs-search", re.I)


def _scan(r) -> Detected | None:
    if d := detect(str(r.url)):  # redirected straight to an ATS
        return d
    for m in _EMBED_RE.finditer(r.text):
        if d := detect(m.group(0)):
            return _own_host(d, r.url.host) if d.ats == "eightfold" else d
    if _SF_MARKERS.search(r.text):
        return Detected("successfactors", r.url.host, {"base": f"https://{r.url.host}"})
    return None


_JOBS_TEXT = re.compile(r"(?:view|explore|see|browse|search|find).{0,12}(?:jobs|roles|openings|positions|vacancies)"
                        r"|(?:current|open|job)\s+(?:openings|positions|roles|vacancies)", re.I)
_JOBS_PATH = re.compile(r"/(?:job-openings|explore-jobs|open-positions|openings|open-roles|jobs|vacancies)/?$", re.I)


def jobs_link(html: str, base: str) -> str | None:
    """The same-site link a careers landing page uses for its job list, if any."""
    from selectolax.parser import HTMLParser
    site = ".".join((urlparse(base).hostname or "").split(".")[-2:])
    for a in HTMLParser(html).css("a[href]"):
        href = urljoin(base, a.attributes.get("href") or "")
        host = urlparse(href).hostname or ""
        if host.endswith(site) and (_JOBS_TEXT.search(a.text(strip=True)) or _JOBS_PATH.search(urlparse(href).path)):
            return href.split("#")[0]
    return None


def _own_host(d: Detected, host: str) -> Detected:
    """Eightfold white-label portals (careers.qualcomm.com) serve the API on their own host, not app.eightfold.ai."""
    if host.endswith("eightfold.ai"):
        return d
    name = host.removeprefix("www.").removeprefix("careers.").removeprefix("jobs.").split(".")[0]
    return Detected("eightfold", name, {"base": f"https://{host}", "domain": d.extra["domain"] or ".".join(host.split(".")[-2:])})


if __name__ == "__main__":
    cases = {
        "https://boards.greenhouse.io/okta": ("greenhouse", "okta"),
        "https://job-boards.greenhouse.io/anthropic/jobs/123": ("greenhouse", "anthropic"),
        "https://boards.greenhouse.io/embed/job_board?for=stripe": ("greenhouse", "stripe"),
        "https://jobs.lever.co/notion": ("lever", "notion"),
        "https://jobs.eu.lever.co/acme/abc": ("lever", "acme"),
        "https://jobs.ashbyhq.com/tekion": ("ashby", "tekion"),
        "https://jobs.smartrecruiters.com/Visa": ("smartrecruiters", "Visa"),
        "https://apply.workable.com/huggingface/": ("workable", "huggingface"),
        "https://acme.recruitee.com/": ("recruitee", "acme"),
        "https://acme.jobs.personio.de/": ("personio", "acme"),
        "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite": ("workday", "nvidia/NVIDIAExternalCareerSite"),
        "https://jobs.careers.microsoft.com/global/en/search": ("eightfold", "microsoft"),
        "https://example.com/careers": None,
    }
    for url, want in cases.items():
        d = detect(url)
        got = (d.ats, d.slug) if d else None
        assert got == want, (url, got, want)
    assert detect("https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite").extra == {"tenant": "nvidia", "wd": "wd5"}
    m = _EMBED_RE.search('src:"https://app.eightfold.ai/careers?domain=qualcomm.com\\",')
    q = _own_host(detect(m.group(0)), "careers.qualcomm.com")
    assert (q.slug, q.extra) == ("qualcomm", {"base": "https://careers.qualcomm.com", "domain": "qualcomm.com"}), q
    class _R:  # SuccessFactors hides on the company's own domain; only the markup gives it away
        text, url = '<script src="//rmkcdn.successfactors.com/x.js"></script>', type("U", (), {"host": "careers.wipro.com"})()
    sf = _scan(_R())
    assert sf and (sf.ats, sf.slug, sf.extra) == ("successfactors", "careers.wipro.com",
                                                  {"base": "https://careers.wipro.com"}), sf
    _R.text = "<html>an ordinary careers page</html>"
    assert _scan(_R()) is None, "no marker, no guess"

    s = ats_in_text(r'{"u": "https:\/\/jobs.smartrecruiters.com\/SWIGGY\/6000-hod?trid=1"}')
    assert s and (s.ats, s.slug) == ("smartrecruiters", "SWIGGY"), s
    assert jobs_link('<a href="/careers/job-openings/">Current Openings</a>', "https://www.phonepe.com/careers/") \
        == "https://www.phonepe.com/careers/job-openings/"
    for bad, want in (("ftp://x.example.com", "http(s)"), ("http://localhost:8010/x", "private"),
                      ("http://169.254.169.254/meta", "private"), ("https://no-such-host.invalid/x", "Could not find")):
        try:
            assert_public_url(bad)
            raise SystemExit(f"should have rejected {bad}")
        except ValueError as e:
            assert want in str(e), (bad, str(e))
    # same site name, different tenants -> different identities
    assert detect("https://intel.wd1.myworkdayjobs.com/en-US/External").slug == "intel/External"
    assert detect("https://micron.wd1.myworkdayjobs.com/en-US/External").slug == "micron/External"
    print("detect OK")
