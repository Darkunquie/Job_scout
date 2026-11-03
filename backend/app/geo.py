"""Location string -> (countries[], city). Rules + small city table; no network."""
import re
import unicodedata

import pycountry


def fold(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).lower()

# ponytail: ~250 hand-picked cities; swap for GeoNames cities15000 if unknown-city rate gets high
_CITIES = {
    "IN": "Bengaluru|Bangalore|Hyderabad|Secunderabad|Chennai|Madras|Pune|Mumbai|Bombay|Navi Mumbai|Thane|Delhi|New Delhi|"
          "Noida|Greater Noida|Gurugram|Gurgaon|Faridabad|Ghaziabad|Kolkata|Calcutta|Kochi|Cochin|Ernakulam|Coimbatore|"
          "Visakhapatnam|Vizag|Vijayawada|Ahmedabad|Gandhinagar|Jaipur|Indore|Bhopal|Chandigarh|Mohali|Mysore|Mysuru|Nagpur|"
          "Bhubaneswar|Thiruvananthapuram|Trivandrum|Kozhikode|Madurai|Tiruchirappalli|Lucknow|Kanpur|Patna|Raipur|Guwahati|"
          "Dehradun|Surat|Vadodara|Nashik|Goa|Mangalore|Mangaluru|Tirupati|Warangal|Vellore|Ludhiana|Ranchi|Jamshedpur",
    "US": "New York|NYC|San Francisco|Seattle|Redmond|Bellevue|Austin|Boston|Chicago|Los Angeles|San Jose|Santa Clara|"
          "Mountain View|Sunnyvale|Palo Alto|Menlo Park|Cupertino|San Diego|Denver|Atlanta|Dallas|Houston|Miami|Washington DC|"
          "Arlington|Raleigh|Durham|Pittsburgh|Philadelphia|Portland|Hillsboro|Phoenix|Salt Lake City|Minneapolis|Detroit|Nashville",
    "GB": "London|Manchester|Edinburgh|Cambridge|Oxford|Bristol|Belfast|Glasgow|Reading|Birmingham|Leeds",
    "DE": "Berlin|Munich|München|Hamburg|Frankfurt|Cologne|Köln|Stuttgart|Düsseldorf|Dusseldorf|Leipzig",
    "FR": "Paris|Lyon|Marseille|Toulouse|Nantes|Lille|Grenoble",
    "NL": "Amsterdam|Rotterdam|Utrecht|Eindhoven|The Hague",
    "IE": "Dublin|Cork|Galway",
    "ES": "Madrid|Barcelona|Valencia|Malaga|Seville",
    "IT": "Milan|Rome|Turin",
    "PT": "Lisbon|Porto",
    "PL": "Warsaw|Krakow|Kraków|Wroclaw|Wrocław|Gdansk",
    "RO": "Bucharest|Cluj-Napoca|Iasi",
    "CH": "Zurich|Zürich|Geneva|Basel|Lausanne",
    "SE": "Stockholm|Gothenburg|Malmo",
    "DK": "Copenhagen|Aarhus",
    "NO": "Oslo",
    "FI": "Helsinki",
    "AT": "Vienna",
    "BE": "Brussels|Antwerp",
    "CZ": "Prague|Brno",
    "IL": "Tel Aviv|Haifa|Jerusalem|Herzliya",
    "AE": "Dubai|Abu Dhabi|Sharjah",
    "SA": "Riyadh|Jeddah",
    "QA": "Doha",
    "SG": "Singapore",
    "JP": "Tokyo|Osaka|Kyoto|Yokohama",
    "KR": "Seoul|Busan",
    "CN": "Beijing|Shanghai|Shenzhen|Guangzhou|Hangzhou",
    "HK": "Hong Kong",
    "TW": "Taipei|Hsinchu",
    "AU": "Sydney|Melbourne|Brisbane|Perth|Adelaide|Canberra",
    "NZ": "Auckland|Wellington",
    "CA": "Toronto|Vancouver|Montreal|Montréal|Ottawa|Calgary|Waterloo",
    "MX": "Mexico City|Guadalajara|Monterrey",
    "BR": "Sao Paulo|São Paulo|Rio de Janeiro|Belo Horizonte",
    "AR": "Buenos Aires",
    "CO": "Bogota|Bogotá|Medellin",
    "ZA": "Johannesburg|Cape Town",
    "NG": "Lagos",
    "KE": "Nairobi",
    "EG": "Cairo",
    "MY": "Kuala Lumpur|Penang",
    "PH": "Manila|Makati|Taguig|Cebu",
    "ID": "Jakarta",
    "VN": "Ho Chi Minh City|Hanoi",
    "TH": "Bangkok",
    "PK": "Karachi|Lahore|Islamabad",
    "BD": "Dhaka",
    "LK": "Colombo",
}
_CANON = {"bangalore": "Bengaluru", "madras": "Chennai", "bombay": "Mumbai", "calcutta": "Kolkata", "gurgaon": "Gurugram",
          "cochin": "Kochi", "vizag": "Visakhapatnam", "trivandrum": "Thiruvananthapuram", "mysore": "Mysuru",
          "mangalore": "Mangaluru", "new delhi": "Delhi", "secunderabad": "Hyderabad", "nyc": "New York", "münchen": "Munich",
          "köln": "Cologne"}
CITY = {name.lower(): (_CANON.get(name.lower(), name), cc) for cc, names in _CITIES.items() for name in names.split("|")}

US_STATES = set("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR "
                "PA RI SC SD TN TX UT VT VA WA WV WI WY DC".split())

COUNTRY = {}
for c in pycountry.countries:
    for n in (c.name, getattr(c, "common_name", None), getattr(c, "official_name", None), c.alpha_3):
        if n:
            COUNTRY[fold(n)] = c.alpha_2
COUNTRY.update({"usa": "US", "united states of america": "US", "america": "US", "uk": "GB", "england": "GB",
                "scotland": "GB", "great britain": "GB", "uae": "AE", "south korea": "KR", "korea": "KR",
                "russia": "RU", "vietnam": "VN", "czech republic": "CZ", "turkey": "TR", "taiwan": "TW", "iran": "IR",
                "deutschland": "DE", "bharat": "IN"})
for sub in pycountry.subdivisions:  # states/provinces -> country (IN states, US states, CA provinces…)
    if sub.country_code in ("IN", "US", "CA", "AU", "DE", "GB", "CN", "BR"):
        COUNTRY.setdefault(fold(sub.name), sub.country_code)
ISO2 = {c.alpha_2 for c in pycountry.countries}
# "Georgia" is both a US state and a country, and the country wins in COUNTRY above. Where the
# surrounding text is clearly American, read these as states instead.
US_STATE_NAMES = {fold(s.name) for s in pycountry.subdivisions.get(country_code="US")}
AMBIGUOUS_US_STATES = US_STATE_NAMES & set(COUNTRY)
_US_MARKER = re.compile(r"\b(?:usa|u\.s\.a?\.?|united states|us remote|remote - us\b)", re.I)


def _us_context(text: str) -> bool:
    """True when the text looks like a US listing: an explicit marker, or several state names."""
    if _US_MARKER.search(text):
        return True
    folded = fold(text)
    return sum(1 for name in US_STATE_NAMES if len(name) > 4 and name in folded) >= 2

_SPLIT = re.compile(r"\s*(?:[,;|/·•]| - | – |\(|\))\s*")
# "Remote Canada" has no separator to split on, so the country would be missed and the job would
# fall back to remote-anywhere and leak into every region's feed. Strip the arrangement word first.
_LEAD_ARRANGEMENT = re.compile(
    r"^\s*(?:fully\s+|100%\s+)?(?:remote|wfh|work\s+from\s+home|hybrid|on-?site|virtual|telecommute)\b[\s:._–-]*",
    re.I)


def country_of(token: str) -> str | None:
    t = fold(token.strip().strip("."))
    if not t:
        return None
    if t in CITY:
        return CITY[t][1]
    if t in COUNTRY:
        return COUNTRY[t]
    return token.strip().upper() if len(token.strip()) == 2 and token.strip().upper() in ISO2 else None


def parse_location(*texts) -> tuple[list[str], str | None]:
    """Return (ISO2 countries in order of appearance, first known city)."""
    countries, city = [], None
    for text in texts:
        if not text:
            continue
        us_ctx = _us_context(str(text))
        for part in re.split(r"\s*;\s*|\n", str(text)):
            # Keep a token that is *only* an arrangement word: dropping it changes the token count,
            # and the US-state rule below needs "Remote, AZ" to stay two tokens or AZ reads as Azerbaijan.
            toks = []
            for t in _SPLIT.split(part):
                if not t:
                    continue
                stripped = _LEAD_ARRANGEMENT.sub("", t)
                toks.append(stripped or t)
            if not toks:
                continue
            found = None
            for t in toks:
                lt = t.lower()
                if lt in CITY:
                    city = city or CITY[lt][0]
                    found = found or CITY[lt][1]
            for t in toks:
                if found:
                    break
                lt = fold(t.strip("."))
                if lt in AMBIGUOUS_US_STATES and us_ctx:
                    found = "US"
                elif lt in COUNTRY and len(lt) > 3:
                    found = COUNTRY[lt]
            if not found and len(toks) >= 2:
                last, first = toks[-1].strip(), toks[0].strip()
                if len(last) == 2 and last.isupper():
                    found = "US" if (len(toks) == 2 and last in US_STATES) else (last if last in ISO2 else None)
                if not found and len(first) == 2 and first.isupper() and first in ISO2:
                    found = first  # Workday "US, CA, Santa Clara"
                if not found and fold(toks[-1]) in COUNTRY:
                    found = COUNTRY[fold(toks[-1])]
            if not found and len(toks) == 1:
                found = country_of(toks[0])
            if found and found not in countries:
                countries.append(found)
    return countries, city


# Remote postings are often scoped to a trading region rather than a country ("Remote, EMEA").
# Stored in jobs.remote_scope as the token; expanded back to countries when filtering.
_REGION_MEMBERS = {
    "EU": "AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE",
    "UKI": "GB IE",
    "DACH": "DE AT CH",
    "BENELUX": "BE NL LU",
    "NORDICS": "SE NO DK FI IS",
    "ANZ": "AU NZ",
    "MENA": "AE SA QA KW BH OM IL JO LB EG MA TN DZ TR",
    "AFRICA": "ZA NG KE EG GH ET TZ UG MA DZ TN RW SN CI CM ZW ZM",
    "ASIA": "IN CN JP KR SG ID MY TH VN PH TW HK BD PK LK NP KH MM",
    "LATAM": "MX BR AR CL CO PE UY EC VE BO PY CR PA GT DO HN SV NI",
    "NAMER": "US CA MX",
}
REGIONS: dict[str, set[str]] = {k: set(v.split()) for k, v in _REGION_MEMBERS.items()}
REGIONS["EUROPE"] = REGIONS["EU"] | REGIONS["UKI"] | REGIONS["NORDICS"] | {"CH", "UA", "RS", "BA", "AL", "MK", "ME", "MD", "IS", "NO", "GB"}
REGIONS["EMEA"] = REGIONS["EUROPE"] | REGIONS["MENA"] | REGIONS["AFRICA"]
REGIONS["APAC"] = REGIONS["ASIA"] | REGIONS["ANZ"]
REGIONS["AMER"] = REGIONS["NAMER"] | REGIONS["LATAM"]
GLOBAL_SCOPE = "ANY"


def scopes_for(countries) -> list[str]:
    """remote_scope values a user watching `countries` should see.

    Global-anywhere roles, the countries themselves, and any region that contains one of them —
    nothing else. A Remote-EMEA role must not surface in an India feed.
    """
    want = {c.upper() for c in countries}
    out = [GLOBAL_SCOPE, *sorted(want)]
    out += sorted(name for name, members in REGIONS.items() if members & want)
    return out


def region_of(token: str) -> set[str] | None:
    return REGIONS.get(token.upper())


if __name__ == "__main__":
    india = scopes_for(["IN"])
    assert "ANY" in india and "IN" in india, india
    assert "APAC" in india and "ASIA" in india, india
    assert "EMEA" not in india and "EUROPE" not in india and "NAMER" not in india, india
    us = scopes_for(["US"])
    assert {"NAMER", "AMER"} <= set(us) and "EMEA" not in us and "APAC" not in us, us
    de = scopes_for(["DE"])
    assert {"EU", "EUROPE", "EMEA", "DACH"} <= set(de), de
    assert "APAC" not in de and "ASIA" not in de, de
    multi = scopes_for(["IN", "DE"])
    assert {"APAC", "EMEA"} <= set(multi), multi
    assert scopes_for([]) == ["ANY"], scopes_for([])
    assert "IN" in REGIONS["APAC"] and "IN" not in REGIONS["EMEA"]

    cases = {
        "Bengaluru, Karnataka, India": (["IN"], "Bengaluru"),
        "Bangalore": (["IN"], "Bengaluru"),
        "Santa Clara, CA": (["US"], "Santa Clara"),
        "Redmond, WA, US": (["US"], "Redmond"),
        "US, CA, Santa Clara": (["US"], "Santa Clara"),
        "Toronto, ON, CA": (["CA"], "Toronto"),
        "London, UK": (["GB"], "London"),
        "Remote - India": (["IN"], None),
        "Remote Canada": (["CA"], None),
        "Remote, AZ": (["US"], None),
        "Remote - Georgia, USA": (["US"], None),
        "Florida; Georgia; North Carolina; Tennessee": (["US"], None),
        "Tbilisi, Georgia": (["GE"], None),
        "Georgia": (["GE"], None),
        "Remote, GA": (["US"], None),
        "Remote - MA": (["US"], None),
        "Remote US": (["US"], None),
        "Fully Remote Germany": (["DE"], None),
        "Remote Bengaluru": (["IN"], "Bengaluru"),
        "Hybrid London": (["GB"], "London"),
        "Paris, Île-de-France, France": (["FR"], "Paris"),
        "Hyderabad, TS, India; Redmond, WA, United States": (["IN", "US"], "Hyderabad"),
        "Germany": (["DE"], None),
        "Maharashtra": (["IN"], None),
        "Remote": ([], None),
    }
    for s, want in cases.items():
        got = parse_location(s)
        assert got == want, (s, got, want)
    print("geo OK")
