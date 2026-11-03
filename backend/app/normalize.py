"""raw_job dict -> jobs row fields. Rules only (free, deterministic)."""
import hashlib
import re

from .geo import COUNTRY, ISO2, fold, parse_location

# ponytail: static FX snapshot; swap for a daily fetch (frankfurter.app) if salary sorting precision matters
FX_INR = {"INR": 1, "USD": 84, "EUR": 91, "GBP": 108, "CAD": 61, "AUD": 55, "SGD": 63, "AED": 23, "CHF": 95,
          "JPY": 0.56, "SEK": 7.9, "PLN": 21, "NZD": 50, "HKD": 10.8, "NOK": 7.8, "DKK": 12.2, "BRL": 15, "MXN": 4.5}
PERIOD_MULT = {"year": 1, "month": 12, "week": 52, "day": 260, "hour": 2080}

SKILLS = {
    "Python": r"python", "Java": r"java(?!\s*script)", "JavaScript": r"javascript|\bjs\b", "TypeScript": r"typescript",
    "Go": r"\bgolang\b|\bgo\s+(?:lang|developer|engineer)", "Rust": r"\brust\b", "C++": r"c\+\+", "C#": r"c#|\.net\b",
    "Kotlin": r"kotlin", "Swift": r"\bswift\b", "Scala": r"\bscala\b", "Ruby": r"\bruby\b|rails", "PHP": r"\bphp\b",
    "SQL": r"\bsql\b", "PostgreSQL": r"postgres", "MySQL": r"mysql", "MongoDB": r"mongo", "Redis": r"\bredis\b",
    "React": r"\breact(?:\.js|js)?\b", "Next.js": r"next\.?js", "Angular": r"angular", "Vue": r"\bvue",
    "Node.js": r"node\.?js", "Django": r"django", "Flask": r"\bflask\b", "FastAPI": r"fastapi", "Spring": r"\bspring\b",
    "AWS": r"\baws\b|amazon web services", "Azure": r"\bazure\b", "GCP": r"\bgcp\b|google cloud", "Docker": r"docker",
    "Kubernetes": r"kubernetes|\bk8s\b", "Terraform": r"terraform", "Linux": r"\blinux\b", "CI/CD": r"ci/cd|jenkins|github actions",
    "Kafka": r"kafka", "Spark": r"\bspark\b", "Airflow": r"airflow", "Snowflake": r"snowflake", "Databricks": r"databricks",
    "Hadoop": r"hadoop", "dbt": r"\bdbt\b", "Tableau": r"tableau", "Power BI": r"power\s?bi", "Excel": r"\bexcel\b",
    "Machine Learning": r"machine learning|\bml\b", "Deep Learning": r"deep learning", "NLP": r"\bnlp\b|natural language",
    "Computer Vision": r"computer vision", "PyTorch": r"pytorch", "TensorFlow": r"tensorflow", "LLM": r"\bllms?\b|large language",
    "Generative AI": r"generative ai|gen\s?ai", "Data Science": r"data scien", "Data Engineering": r"data engineer",
    "Statistics": r"statistic", "Figma": r"figma", "Salesforce": r"salesforce", "SAP": r"\bsap\b", "Selenium": r"selenium",
    "Android": r"android", "iOS": r"\bios\b", "Flutter": r"flutter", "React Native": r"react native",
    "GraphQL": r"graphql", "REST": r"\brest(?:ful)?\b", "Microservices": r"microservice", "Git": r"\bgit\b",
    "Cybersecurity": r"cyber\s?security|information security|infosec", "DevOps": r"devops", "SRE": r"\bsre\b|site reliability",
    "Embedded": r"embedded", "Verilog": r"verilog|systemverilog", "CUDA": r"\bcuda\b", "Agile": r"agile|scrum",
    "Product Management": r"product manage", "Sales": r"\bsales\b", "Marketing": r"marketing", "SEO": r"\bseo\b",
}
_SKILL_RE = {k: re.compile(v, re.I) for k, v in SKILLS.items()}
# Job families, not skills: nearly every ad mentions sales or marketing somewhere, so these match on
# the title/department only — otherwise they crowd out real skills in the filter.
TITLE_ONLY = {"Sales", "Marketing", "Product Management", "SEO"}

_REMOTE = re.compile(r"\bremote\b|work from home|\bwfh\b|anywhere|telecommut|0 days / week in-office", re.I)
# "Remote, EMEA" is not "remote, anywhere". Order matters: first match wins, so the explicitly
# global wording is checked before the regional tokens.
_ANY_SCOPE = re.compile(r"\bglobal(?:ly)?\b|worldwide|world wide|anywhere|any location|\bww\b", re.I)
_REGION_SCOPES = [
    ("EMEA", r"\bemea\b"),
    ("APAC", r"\bapac\b|asia[\s-]*pac"),
    ("LATAM", r"\blatam\b|latin america|south america"),
    ("NAMER", r"\bnamer\b|north america"),
    ("AMER", r"\bamers?\b|\bamericas\b"),
    ("DACH", r"\bdach\b"),
    ("BENELUX", r"\bbenelux\b"),
    ("NORDICS", r"\bnordics?\b|scandinavia"),
    ("UKI", r"\buk\s*&\s*i\b|uk and ireland"),
    ("ANZ", r"\banz\b|australia and new zealand"),
    ("MENA", r"\bmena\b|middle east"),
    ("AFRICA", r"\bafrica\b"),
    ("EU", r"\beu\b|european union|\beea\b"),
    ("EUROPE", r"\beurope(?:an)?\b"),
    ("ASIA", r"\basia\b"),
]
_REGION_SCOPE_RE = [(name, re.compile(pat, re.I)) for name, pat in _REGION_SCOPES]
_HYBRID = re.compile(r"hybrid|\d days / week in-office", re.I)
_ONSITE = re.compile(r"on-?site|in-?office|fully on-site", re.I)
_EMP = [("Internship", r"intern"), ("Apprenticeship", r"apprentic"), ("Part-time", r"part[\s_-]?time"),
        ("Contract", r"contract|freelance|fixed[\s_-]?term"), ("Temporary", r"temp"),
        ("Full-time", r"full[\s_-]?time|fulltime|permanent|regular")]
_EXP_RANGE = re.compile(r"(\d{1,2})\s*(?:\+|-|–|to)\s*(\d{1,2})?\s*\+?\s*(?:years|yrs|year)", re.I)
_EXP_MIN = re.compile(r"(?:at least|minimum(?: of)?|min\.?)\s*(\d{1,2})\s*\+?\s*(?:years|yrs)", re.I)
_EXP_PLAIN = re.compile(r"(\d{1,2})\+?\s*(?:years|yrs)(?:'|’)?\s*(?:of\s+)?(?:\w+\s+){0,3}experience", re.I)
_VISA_YES = re.compile(r"visa sponsorship (?:is )?(?:available|provided|offered)|will sponsor|sponsorship available|"
                       r"relocation (?:support|assistance|package)|we (?:can |do )?sponsor", re.I)
_VISA_NO = re.compile(r"(?:not|unable to|cannot|can't|no|without)\s+(?:\w+\s+){0,3}(?:visa\s+)?sponsor", re.I)
_SAL_LPA = re.compile(r"(?:₹|inr|rs\.?)?\s*(\d+(?:\.\d+)?)\s*(?:-|–|to)\s*(\d+(?:\.\d+)?)\s*(?:lpa|lakhs?|l\b)", re.I)
_SAL_CUR = re.compile(r"(\$|€|£|usd|eur|gbp|cad|aud|sgd)\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?\s*(?:-|–|to)\s*"
                      r"(?:\$|€|£|usd|eur|gbp|cad|aud|sgd)?\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?", re.I)
_SYM = {"$": "USD", "€": "EUR", "£": "GBP"}


def _country(hint) -> str | None:
    if not hint:
        return None
    h = str(hint).strip()
    if len(h) == 2 and h.upper() in ISO2:
        return h.upper()
    return COUNTRY.get(fold(h))


def _period(p) -> str:
    p = fold(str(p or "year"))
    for k in PERIOD_MULT:
        if k in p:
            return k
    return "month" if "mon" in p else "year"


# "$5,690 - $11,210 per month" is not an annual salary. Without this the figure is stored as /year
# and salary_inr_year comes out 12x low, which wrecks the salary sort and filter.
_PERIOD_NEAR = re.compile(r"\b(?:per|a|an|/|each)?\s*(hour|hr|month|mo|week|wk|year|yr|annum|annually|monthly|"
                          r"weekly|hourly)\b", re.I)
_PERIOD_WORD = {"hour": "hour", "hr": "hour", "hourly": "hour", "month": "month", "mo": "month",
                "monthly": "month", "week": "week", "wk": "week", "weekly": "week", "year": "year",
                "yr": "year", "annum": "year", "annually": "year"}


def _period_near(text: str, pos: int) -> str | None:
    """Read the pay period from the words right after an amount."""
    m = _PERIOD_NEAR.search(text[pos:pos + 40])
    return _PERIOD_WORD.get(m.group(1).lower()) if m else None


def _salary(raw, text):
    lo, hi, cur, per = raw["salary_min"], raw["salary_max"], raw["salary_currency"], raw["salary_period"]
    if lo is None and hi is None:
        if m := _SAL_LPA.search(text):
            lo, hi, cur, per = float(m.group(1)) * 1e5, float(m.group(2)) * 1e5, "INR", "year"
        elif m := _SAL_CUR.search(text):
            k1, k2 = 1000 if m.group(3) else 1, 1000 if (m.group(5) or m.group(3)) else 1
            lo, hi = float(m.group(2).replace(",", "")) * k1, float(m.group(4).replace(",", "")) * k2
            cur = _SYM.get(m.group(1), m.group(1).upper())
            per = _period_near(text, m.end()) or ("hour" if hi < 500 else "year")
            if hi < lo or lo < 10:
                return None, None, None, None, None
    if lo is None and hi is None:
        return None, None, None, None, None
    cur, per = (cur or "USD").upper(), _period(per)
    mid = (float(lo or hi) + float(hi or lo)) / 2
    inr = mid * FX_INR[cur] * PERIOD_MULT[per] if cur in FX_INR else None
    return lo, hi, cur, per, round(inr) if inr else None


def _experience(raw, title, desc):
    lo = hi = None
    hint = str(raw["exp_hint"] or "")
    for text in (hint, desc[:6000]):
        if m := _EXP_RANGE.search(text) or re.match(r"^(\d{1,2})\s*-\s*(\d{1,2})$", text.strip()):
            lo, hi = int(m.group(1)), int(m.group(2)) if m.group(2) else None
        elif m := _EXP_MIN.search(text) or _EXP_PLAIN.search(text):
            lo = int(m.group(1))
        if lo is not None:
            break
    if lo is not None and (lo > 25 or (hi is not None and (hi < lo or hi > 30))):
        lo = hi = None
    t = f"{title} {hint}".lower()
    if re.search(r"\bintern", t):
        level = "intern"
    elif re.search(r"graduate|new grad|trainee|fresher|entry|campus|\bassociate\b", t):
        level = "fresher"
    elif re.search(r"\bjunior\b|\bjr\.?\b", t):
        level = "junior"
    elif re.search(r"principal|staff|\blead\b|architect|director|head of|\bvp\b|vice president", t):
        level = "lead"
    elif re.search(r"senior|\bsr\.?\b|\biii\b|mid-senior", t):
        level = "senior"
    elif lo is not None:
        level = "fresher" if lo == 0 else "junior" if lo <= 2 else "mid" if lo <= 5 else "senior" if lo <= 8 else "lead"
    else:
        level = None
    return lo, hi, level


def remote_scope(countries: list[str], text: str) -> str:
    """Where a remote job may actually be done.

    A country we parsed wins. Otherwise look for a region token, so "Remote, EMEA" stays EMEA
    instead of falling through to ANY and leaking into every region's feed.
    """
    if countries:
        return countries[0]
    if _ANY_SCOPE.search(text):
        return "ANY"
    for name, rx in _REGION_SCOPE_RE:
        if rx.search(text):
            return name
    return "ANY"


def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", fold(s or "")).strip()


def normalize(raw: dict, source: str) -> dict:
    title = (raw["title"] or "").strip()
    desc = raw["description"] or ""
    locs = raw["locations"] or []
    loc_text = "; ".join(filter(None, [raw["location_raw"], *[l for l in locs if l != raw["location_raw"]]]))
    countries, city = parse_location(raw["location_raw"], *locs)
    if (hc := _country(raw["country_hint"])) and hc not in countries:
        countries.insert(0, hc)
    city = raw["city_hint"] or city

    wp = f"{raw['workplace_hint'] or ''} {loc_text} {title}"
    if raw["remote_hint"] is True or _REMOTE.search(wp):
        arrangement = "Remote"
    elif _HYBRID.search(wp):
        arrangement = "Hybrid"
    elif _ONSITE.search(str(raw["workplace_hint"] or "")):
        arrangement = "On-site"
    else:
        arrangement = None
    is_remote = arrangement == "Remote"

    emp_src = f"{raw['employment_type'] or ''} {title}"
    employment = next((label for label, pat in _EMP if re.search(pat, emp_src, re.I)), None)

    exp_min, exp_max, exp_level = _experience(raw, title, desc)
    sal_lo, sal_hi, cur, per, inr = _salary(raw, desc[:8000])
    hay = f"{title}\n{desc}"
    head = f"{title}\n{raw['department'] or ''}"
    skills = [k for k, rx in _SKILL_RE.items() if rx.search(head if k in TITLE_ONLY else hay)]
    visa = False if _VISA_NO.search(desc) else True if _VISA_YES.search(desc) else None
    country = countries[0] if countries else None
    company = raw["company_name"] or ""

    return {
        "source": source, "external_id": str(raw["external_id"]), "company_name": company, "url": raw["url"],
        "apply_url": raw["apply_url"] or raw["url"], "title": title, "department": raw["department"],
        "description": desc, "location_raw": loc_text or None, "country_code": country, "countries": countries,
        "city": city, "is_remote": is_remote,
        "remote_scope": remote_scope(countries, f"{loc_text} {title}") if is_remote else None,
        "work_arrangement": arrangement, "employment_type": employment, "exp_min": exp_min, "exp_max": exp_max,
        "exp_level": exp_level, "salary_min": sal_lo, "salary_max": sal_hi, "salary_currency": cur,
        "salary_period": per, "salary_inr_year": inr, "skills": skills, "visa_sponsorship": visa,
        "posted_at": raw["posted_at"],
        "content_hash": hashlib.sha1(f"{title}|{loc_text}|{desc}".encode()).hexdigest(),
        "dedupe_key": hashlib.sha1(f"{_norm_key(company)}|{_norm_key(title)}|{country}|{_norm_key(city or '')}".encode()).hexdigest(),
    }


if __name__ == "__main__":
    from .adapters.base import raw_job

    r = normalize(raw_job(external_id=1, title="Senior Data Engineer (Remote - India)", company_name="Acme",
                          description="We need 5+ years of experience with Python, Spark and AWS. CTC 25-35 LPA. "
                                      "We are unable to provide visa sponsorship.",
                          location_raw="Bengaluru, Karnataka, India", employment_type="Full time"), "greenhouse")
    assert r["countries"] == ["IN"] and r["city"] == "Bengaluru", r
    assert r["is_remote"] and r["work_arrangement"] == "Remote" and r["remote_scope"] == "IN", r
    assert r["employment_type"] == "Full-time" and r["exp_min"] == 5 and r["exp_level"] == "senior", r
    assert {"Python", "Spark", "AWS"} <= set(r["skills"]), r["skills"]
    r_sec = normalize(raw_job(external_id=9, title="Security Architect", company_name="Acme", department="Security",
                              description="Partner with our sales and marketing teams on REST APIs."), "greenhouse")
    assert not {"Sales", "Marketing"} & set(r_sec["skills"]), r_sec["skills"]
    r_sales = normalize(raw_job(external_id=10, title="Enterprise Sales Manager", company_name="Acme",
                                description="Own the pipeline."), "greenhouse")
    assert "Sales" in r_sales["skills"], r_sales["skills"]

    # Remote scope: a region-locked role must not be stamped "anywhere".
    from .geo import scopes_for
    assert remote_scope([], "Remote, EMEA") == "EMEA"
    assert remote_scope([], "Remote - APAC") == "APAC"
    assert remote_scope([], "Remote, Global") == "ANY"
    assert remote_scope([], "Remote") == "ANY"
    assert remote_scope([], "Remote (Americas)") == "AMER"
    assert remote_scope(["IN"], "Remote - India") == "IN"
    assert remote_scope(["US"], "Remote, EMEA") == "US", "a parsed country beats a region word"
    assert remote_scope([], "Remote, Europe") == "EUROPE"

    emea = normalize(raw_job(external_id=11, title="Account Executive DACH (German-Speaking)",
                             company_name="Supabase", description="Sell things.",
                             location_raw="Remote, EMEA"), "ashby")
    assert emea["is_remote"] and emea["remote_scope"] == "EMEA", emea["remote_scope"]
    assert emea["remote_scope"] not in scopes_for(["IN"]), "EMEA-only must stay out of an India feed"
    assert emea["remote_scope"] in scopes_for(["DE"]), "...but show for someone watching Germany"

    glob = normalize(raw_job(external_id=12, title="Engineer", company_name="X",
                             description="d", location_raw="Remote, Global"), "ashby")
    assert glob["remote_scope"] == "ANY" and glob["remote_scope"] in scopes_for(["IN"])

    # Pay period comes from the words after the amount, not from its magnitude.
    intern = normalize(raw_job(external_id=13, title="SWE Intern", company_name="Microsoft",
                               description="The base pay range for this internship is USD $5,690.00 - "
                                           "$11,210.00 per month. Other ranges apply elsewhere.",
                               location_raw="Redmond, WA"), "eightfold")
    assert intern["salary_period"] == "month", intern["salary_period"]
    assert intern["salary_inr_year"] == round((5690 + 11210) / 2 * 84 * 12), intern["salary_inr_year"]
    yearly = normalize(raw_job(external_id=14, title="Engineer", company_name="X",
                               description="Salary $120,000 - $160,000 per year.",
                               location_raw="Austin, TX"), "greenhouse")
    assert yearly["salary_period"] == "year", yearly["salary_period"]
    hourly = normalize(raw_job(external_id=15, title="Engineer", company_name="X",
                               description="Pay is $40 - $55 per hour.", location_raw="Austin, TX"), "greenhouse")
    assert hourly["salary_period"] == "hour", hourly["salary_period"]
    bare = normalize(raw_job(external_id=16, title="Engineer", company_name="X",
                             description="Range: $120,000 - $160,000.", location_raw="Austin, TX"), "greenhouse")
    assert bare["salary_period"] == "year", "no period word -> fall back to magnitude"
    assert r["salary_currency"] == "INR" and r["salary_inr_year"] == 3_000_000, r
    assert r["visa_sponsorship"] is False
    r2 = normalize(raw_job(external_id=2, title="Software Engineer Intern", company_name="X", description="$40 - $55 per hour",
                           location_raw="Seattle, WA", workplace_hint="hybrid"), "lever")
    assert r2["countries"] == ["US"] and r2["work_arrangement"] == "Hybrid" and r2["exp_level"] == "intern", r2
    assert r2["employment_type"] == "Internship" and r2["salary_period"] == "hour", r2
    r3 = normalize(raw_job(external_id=3, title="Backend Engineer", description="Requires 2-4 years experience",
                           location_raw="Berlin", salary_min=60000, salary_max=80000, salary_currency="EUR",
                           salary_period="1 YEAR"), "ashby")
    assert r3["exp_min"] == 2 and r3["exp_max"] == 4 and r3["exp_level"] == "junior" and r3["salary_inr_year"] == 70000 * 91, r3
    print("normalize OK")
