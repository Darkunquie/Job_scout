import asyncio
import html
import re
from datetime import datetime, timedelta, timezone

import httpx

from ..config import USER_AGENT


class Blocked(Exception):
    """Source refused us (403/429/captcha). Never try to bypass — back off."""


class Unsupported(Exception):
    """No tier could read this site. Stop retrying it until an admin intervenes."""


def client(**kw) -> httpx.AsyncClient:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9"}
    headers.update(kw.pop("headers", {}))
    return httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=30, **kw)


async def request(c: httpx.AsyncClient, method: str, url: str, delay: float = 0.0, **kw) -> httpx.Response:
    """GET/POST with polite delay + 3 retries on 5xx/timeouts. 403/429 -> Blocked."""
    for attempt in range(3):
        if delay:
            await asyncio.sleep(delay)
        try:
            r = await c.request(method, url, **kw)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)
            continue
        # nginx throttles with "405 Not Allowed" on plain GETs (Qualcomm); a real 405 only happens on POST
        if r.status_code in (403, 429) or (r.status_code == 405 and method == "GET"):
            raise Blocked(f"{r.status_code} from {r.url.host}")
        if r.status_code >= 500 and attempt < 2:
            await asyncio.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r
    raise RuntimeError("unreachable")


async def get_json(c: httpx.AsyncClient, method: str, url: str, **kw):
    """request() + JSON parse. A throttle/maintenance page served with HTTP 200 is not a crash — back off."""
    for attempt in range(2):
        r = await request(c, method, url, **kw)
        try:
            return r.json()
        except ValueError:
            if attempt:
                raise Blocked(f"{r.url.host} served non-JSON ({r.headers.get('content-type')}, {len(r.text)}B)")
            await asyncio.sleep(5)


_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h\d|tr)[^>]*>", re.I)


def html_to_text(s: str | None) -> str:
    if not s:
        return ""
    s = html.unescape(s)  # greenhouse double-escapes
    s = _BLOCK.sub("\n", s)
    s = html.unescape(_TAG.sub("", s))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t\xa0]+", " ", s)).strip()


def parse_date(v) -> datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):  # epoch s or ms
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, tz=timezone.utc)
    s = str(v).strip()
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    return parse_relative(s)


def parse_relative(s: str) -> datetime | None:
    """'Posted 3 Days Ago', 'Posted Today', 'Posted 30+ Days Ago', '2 weeks ago'."""
    s = s.lower()
    now = datetime.now(timezone.utc)
    if "today" in s or "just" in s:
        return now
    if "yesterday" in s:
        return now - timedelta(days=1)
    m = re.search(r"(\d+)\+?\s*(minute|hour|day|week|month)", s)
    if not m:
        return None
    n, unit = int(m.group(1)), m.group(2)
    return now - timedelta(**{"minutes": n} if unit == "minute" else {"hours": n} if unit == "hour"
                           else {"days": n * {"day": 1, "week": 7, "month": 30}[unit]})


async def detail_retry(fn, *a):
    """Detail fetch with one slow retry when rate-limited; returns {} on failure (job kept without description)."""
    for wait in (0, 15):
        await asyncio.sleep(wait)
        try:
            return await fn(*a)
        except Blocked:
            continue
        except Exception:
            return {}
    return {}


def raw_job(**kw) -> dict:
    """Common shape every adapter yields. Missing keys -> None."""
    keys = ("external_id", "title", "url", "apply_url", "company_name", "department", "description",
            "location_raw", "locations", "country_hint", "city_hint", "remote_hint", "workplace_hint",
            "employment_type", "posted_at", "salary_min", "salary_max", "salary_currency", "salary_period",
            "exp_hint", "touch_only")
    unknown = set(kw) - set(keys)
    assert not unknown, unknown
    return {k: kw.get(k) for k in keys}
