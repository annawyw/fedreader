"""Data for the Fed Reader: FOMC calendar, statements, minutes, projections (SEP), speeches,
FRED rates and (optionally) CME FedWatch probabilities. No Streamlit here except caching
wrappers in fed_dashboard.py, so these functions can be tested on their own.
"""
from __future__ import annotations

import difflib
import html as htmllib
import io
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime

import pandas as pd
import requests
from bs4 import BeautifulSoup

FED = "https://www.federalreserve.gov"
CALENDAR_URL = f"{FED}/monetarypolicy/fomccalendars.htm"
FEEDS = {"Speech": f"{FED}/feeds/speeches.xml", "Testimony": f"{FED}/feeds/testimony.xml"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Second day of each scheduled meeting (decision day). Used for the countdown; the Fed's
# calendar page is the source for documents. 2027 dates are tentative.
SCHEDULE = [
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-10-28", "2026-12-09",
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-09", "2027-07-28", "2027-09-15",
    "2027-10-27", "2027-12-08",
]
SEP_MONTHS = {3, 6, 9, 12}


# ------------------------------------------------------------------ HTTP
def get(url: str, tries: int = 3, timeout=(10, 60)) -> str:
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise RuntimeError(f"Couldn't download {url}: {last}")


def _text(el) -> str:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip()


# ------------------------------------------------------------------ calendar
def parse_calendar(page: str) -> pd.DataFrame:
    """One row per meeting found on the Fed's calendar page, keyed by decision date."""
    rows = {}
    pats = {
        "statement": r"/newsevents/pressreleases/monetary(\d{8})a\.htm",
        "minutes": r"/monetarypolicy/fomcminutes(\d{8})\.htm",
        "projections": r"/monetarypolicy/fomcprojtabl(\d{8})\.htm",
        "presconf": r"/monetarypolicy/fomcpresconf(\d{8})\.htm",
    }
    for kind, pat in pats.items():
        for m in re.finditer(pat, page):
            d = pd.Timestamp(datetime.strptime(m.group(1), "%Y%m%d"))
            rows.setdefault(d, {})[kind] = FED + m.group(0)
    df = pd.DataFrame.from_dict(rows, orient="index").sort_index()
    df.index.name = "date"
    for c in pats:
        if c not in df.columns:
            df[c] = None
    # Statements that are not meeting decisions (e.g. longer-run strategy) have no minutes
    # or press conference; keep only dates that look like meetings.
    has_meeting_doc = df[["minutes", "presconf", "projections"]].notna().any(axis=1)
    sched = pd.to_datetime(SCHEDULE)
    df = df[has_meeting_doc | df.index.isin(sched)]
    return df


def next_meeting(today: date | None = None):
    today = pd.Timestamp(today or date.today())
    for d in pd.to_datetime(SCHEDULE):
        if d >= today:
            return d, (d - today).days, d.month in SEP_MONTHS
    return None, None, False


# ------------------------------------------------------------------ statements
def parse_statement(page: str) -> dict:
    """Statement paragraphs, vote, decision and target range from a press release page."""
    soup = BeautifulSoup(page, "html.parser")
    root = soup.find(id="article") or soup.find("div", class_="col-xs-12 col-sm-8 col-md-8") or soup
    paras = []
    for p in root.find_all("p"):
        t = _text(p)
        if not t:
            continue
        low = t.lower()
        if low.startswith(("for media inquiries", "implementation note", "for release at",
                           "last update", "back to top")):
            if paras:
                break
            continue
        if low.startswith(("share", "pdf")) or len(t) < 25:
            continue
        paras.append(t)
    text = "\n\n".join(paras)
    return {"paragraphs": paras, "text": text, **decision_from_text(text), **vote_from_text(text)}


_FRAC = {"1/4": .25, "1/2": .5, "3/4": .75, "1/8": .125, "3/8": .375, "5/8": .625, "7/8": .875}


def _num(s: str) -> float | None:
    s = s.strip().replace("‑", "-").replace("–", "-")
    m = re.fullmatch(r"(\d+)(?:-(\d/\d))?", s)
    if m:
        return int(m.group(1)) + _FRAC.get(m.group(2) or "", 0)
    m = re.fullmatch(r"(\d/\d)", s)
    if m:
        return _FRAC.get(m.group(1))
    try:
        return float(s)
    except ValueError:
        return None


def decision_from_text(text: str) -> dict:
    t = text.replace("‑", "-").replace("–", "-")
    m = re.search(r"decided to (raise|lower|maintain|reduce|increase)\s+the target range for the "
                  r"federal funds rate(?: by ([\d/\- ]+?) percentage point)?\s+(?:at|to)\s+"
                  r"([\d/\-]+(?:\s*[\d/]+)?)\s+to\s+([\d/\-]+(?:\s*[\d/]+)?)\s+percent", t, re.I)
    if not m:
        return {"action": None, "change_bp": None, "lower": None, "upper": None}
    verb = m.group(1).lower()
    action = {"raise": "Hike", "increase": "Hike", "lower": "Cut", "reduce": "Cut", "maintain": "Hold"}[verb]
    step = _num(m.group(2)) if m.group(2) else 0.0
    lo, hi = _num(m.group(3).replace(" ", "")), _num(m.group(4).replace(" ", ""))
    bp = 0 if action == "Hold" else round((step or 0) * 100) * (1 if action == "Hike" else -1)
    return {"action": action, "change_bp": bp, "lower": lo, "upper": hi}


def vote_from_text(text: str) -> dict:
    """Votes for/against from the 'Voting for ... Voting against ...' paragraph. Names contain
    periods (\"Jerome H. Powell\"), so the Fed's semicolon separators are used to count."""
    para = next((p for p in text.split("\n\n") if p.lower().startswith("voting for")), "")
    if not para:
        return {"votes_for": None, "votes_against": 0, "dissent": ""}
    for_part, _, against_part = para.partition("Voting against")
    for_list = re.sub(r"^Voting for (?:the|this) (?:monetary policy )?action were:?\s*", "", for_part.strip(), flags=re.I)
    n_for = len([x for x in for_list.split(";") if x.strip(" .")])
    dissent = ""
    if against_part:
        dissent = re.sub(r"^\s*(?:the|this) action (?:was|were):?\s*", "", against_part, flags=re.I).strip()
    names = [x for x in re.split(r";|\band\b", re.split(r",? who |,? each of whom ", dissent)[0] if dissent else "") if x.strip(" .,")]
    return {"votes_for": n_for, "votes_against": len(names), "dissent": dissent}


def redline_html(old: str, new: str) -> str:
    """Word-level diff of two statements as HTML: insertions green, deletions struck red."""
    tok = lambda s: re.findall(r"\S+|\n\n", s)  # noqa: E731
    a, b = tok(old), tok(new)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(_join(b[j1:j2]))
        if op in ("delete", "replace"):
            out.append(f'<del>{_join(a[i1:i2])}</del>')
        if op in ("insert", "replace"):
            out.append(f'<ins>{_join(b[j1:j2])}</ins>')
    return " ".join(x for x in out if x).replace(" \n\n ", "</p><p>").replace("\n\n", "</p><p>")


def _join(words):
    return htmllib.escape(" ".join(words)).replace(" \n\n ", "\n\n")


# ------------------------------------------------------------------ tone
HAWKISH = [
    "inflation remains elevated", "elevated inflation", "upside risks to inflation", "inflation risks",
    "further tightening", "additional policy firming", "policy firming", "raise the target range",
    "rate increase", "higher for longer", "sufficiently restrictive", "restrictive", "persistent",
    "persistence", "overheating", "tight labor market", "labor market remains tight", "strong demand",
    "wage pressures", "price pressures", "vigilant", "not yet confident", "premature", "reaccelerat",
    "re-accelerat", "upside risk", "inflationary", "highly attentive to inflation risks",
]
DOVISH = [
    "lower the target range", "rate cut", "rate reduction", "easing", "accommodative",
    "less restrictive", "downside risks", "downside risk", "softening", "softened", "cooling",
    "weakening", "weakened", "slowed", "slack", "unemployment has moved up", "rising unemployment",
    "labor market has weakened", "disinflation", "progress toward", "moved closer to 2 percent",
    "moderated", "risks to employment", "maximum employment", "layoffs", "job losses",
    "cut the target range", "reduce the target range",
]


def tone(text: str) -> dict:
    """Rough hawkish/dovish score in [-100, 100] from phrase counts (positive = hawkish)."""
    t = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    h = sum(t.count(w) for w in HAWKISH)
    d = sum(t.count(w) for w in DOVISH)
    score = 100 * (h - d) / (h + d) if (h + d) else 0.0
    return {"hawk": h, "dove": d, "score": round(score, 1)}


# ------------------------------------------------------------------ minutes
TOPICS = {
    "Inflation": ["inflation", "prices", "price pressures"],
    "Labor market": ["labor market", "unemployment", "employment", "payroll", "wages"],
    "Policy outlook": ["appropriate", "policy rate", "target range", "further adjustments", "restrictive",
                       "accommodat", "path of policy"],
    "Balance sheet": ["balance sheet", "securities holdings", "runoff", "reserves", "treasury securities"],
    "Risks": ["risk", "uncertain"],
}


def parse_minutes(page: str) -> dict:
    soup = BeautifulSoup(page, "html.parser")
    root = soup.find(id="article") or soup
    paras = [_text(p) for p in root.find_all("p")]
    paras = [p for p in paras if len(p) > 60]
    text = " ".join(paras)
    # The policy discussion is the most informative part: from "Participants' Views" on.
    start = next((i for i, p in enumerate(paras) if "participants" in p.lower() and "view" in p.lower()), 0)
    focus = paras[start:] or paras
    sentences = re.split(r"(?<=[.;])\s+(?=[A-Z])", " ".join(focus))
    picks = {}
    for topic, keys in TOPICS.items():
        hits = [s for s in sentences if any(k in s.lower() for k in keys) and 60 < len(s) < 600]
        ranked = sorted(hits, key=lambda s: -(tone(s)["hawk"] + tone(s)["dove"]))
        picks[topic] = ranked[:4]
    return {"text": text, "passages": picks}


# ------------------------------------------------------------------ projections (SEP)
SEP_VARS = {
    "change in real gdp": "Real GDP growth",
    "unemployment rate": "Unemployment rate",
    "pce inflation": "PCE inflation",
    "core pce inflation": "Core PCE inflation",
    "federal funds rate": "Federal funds rate",
}


def _f(x):
    x = x.replace("–", "-").replace("‑", "-").strip()
    try:
        return float(x)
    except ValueError:
        return None


def parse_sep(page: str) -> dict:
    """Table 1 medians (this SEP and the previous one) and the Figure 2 dot plot counts."""
    soup = BeautifulSoup(page, "html.parser")
    tables = soup.find_all("table")
    medians, dots, years = [], pd.DataFrame(), []
    for tb in tables:
        cap = _text(tb.find("caption")) if tb.find("caption") else ""
        if not years:
            head = _text(tb.find("thead")) if tb.find("thead") else ""
            years = re.findall(r"\b20\d\d\b|Longer run", head)
        if "Table 1" in cap or (not medians and "Median" in _text(tb)[:400] and "Core PCE" in _text(tb)):
            hdr = _text(tb.find("thead")) if tb.find("thead") else _text(tb.find("tr"))
            cols = list(dict.fromkeys(re.findall(r"\b20\d\d\b|Longer run", hdr)))
            current = None
            for tr in tb.find_all("tr"):
                cells = [_text(c) for c in tr.find_all(["th", "td"])]
                if not cells:
                    continue
                label = cells[0].lower().strip()
                label = re.sub(r"\s*\d+\s*$", "", label)  # footnote numbers
                key = next((k for k in SEP_VARS if label.startswith(k)), None)
                if key == "pce inflation" and label.startswith("core"):
                    key = "core pce inflation"
                if key:
                    current = SEP_VARS[key]
                    which = "Current"
                elif label.endswith("projection") and current:
                    which = "Previous"
                else:
                    continue
                vals = [_f(c) for c in cells[1:1 + len(cols)]]
                medians.append({"variable": current, "vintage": which, **dict(zip(cols, vals))})
        if "Figure 2" in cap or "Midpoint of target range" in cap:
            hdr = [_text(c) for c in (tb.find("thead") or tb.find("tr")).find_all(["th", "td"])]
            cols = [c for c in hdr[1:]]
            rows = []
            for tr in tb.find_all("tr"):
                cells = [_text(c) for c in tr.find_all(["th", "td"])]
                rate = _f(cells[0]) if cells else None
                if rate is None:
                    continue
                for c, v in zip(cols, cells[1:]):
                    n = _f(v)
                    if n:
                        rows.append({"horizon": c, "rate": rate, "count": int(n)})
            dots = pd.DataFrame(rows)
    return {"medians": pd.DataFrame(medians), "dots": dots}


# ------------------------------------------------------------------ speeches
def parse_feed(xml_text: str, kind: str) -> pd.DataFrame:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    rows = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        speaker, _, topic = title.partition(",")
        rows.append({
            "date": pd.to_datetime(it.findtext("pubDate"), utc=True).tz_convert(None).normalize()
            if it.findtext("pubDate") else pd.NaT,
            "speaker": speaker.strip(), "title": topic.strip() or title, "kind": kind,
            "link": (it.findtext("link") or "").strip(),
            "venue": htmllib.unescape(re.sub(r"<[^>]+>", "", it.findtext("description") or "")).strip(),
        })
    return pd.DataFrame(rows)


ROLE_RX = re.compile(r"\b(Chair(?:man)?|Vice Chair for Supervision|Vice Chair|Governor)\s+"
                     r"([A-Z][A-Za-z.\-' ]+?)\s*(?:<|\n|$|At\b|Before\b)")


def parse_speech(page: str) -> dict:
    soup = BeautifulSoup(page, "html.parser")
    root = soup.find(id="article") or soup
    head = _text(root)[:400]
    m = ROLE_RX.search(head + "\n")
    paras = [_text(p) for p in root.find_all("p")]
    text = " ".join(p for p in paras if len(p) > 40)
    return {"role": m.group(1) if m else "", "name": m.group(2).strip() if m else "", "text": text}


# ------------------------------------------------------------------ FRED
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_API = "https://api.stlouisfed.org/fred/series/observations"


def fred(ids, start: str, api_key: str = "") -> pd.DataFrame:
    frames = []
    if api_key:
        for sid in ids:
            r = requests.get(FRED_API, params={"series_id": sid, "api_key": api_key, "file_type": "json",
                                               "observation_start": start}, headers=HEADERS, timeout=(10, 60))
            r.raise_for_status()
            obs = r.json().get("observations", [])
            s = pd.Series({pd.Timestamp(o["date"]): pd.to_numeric(o["value"], errors="coerce") for o in obs},
                          name=sid, dtype=float)
            frames.append(s)
        return pd.concat(frames, axis=1).sort_index()
    r = requests.get(FRED_CSV, params={"id": ",".join(ids), "cosd": start}, headers=HEADERS, timeout=(10, 90))
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df = df.rename(columns={df.columns[0]: "date"})
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date").apply(pd.to_numeric, errors="coerce")


# ------------------------------------------------------------------ CME FedWatch (optional)
CME_BASE = "https://markets.api.cmegroup.com/fedwatch/v1"
CME_TOKEN_URL = "https://auth.cmegroup.com/as/token.oauth2"


def cme_token(client_id: str, secret: str, token_url: str = CME_TOKEN_URL) -> str:
    r = requests.post(token_url, data={"grant_type": "client_credentials"},
                      auth=(client_id, secret), timeout=(10, 30))
    r.raise_for_status()
    return r.json()["access_token"]


def cme_forecasts(token: str, meeting: str | None = None) -> pd.DataFrame:
    """FedWatch probabilities: one row per (meeting, reporting date, rate range)."""
    params = {"meetingDt": meeting} if meeting else {}
    rows, page = [], 1
    while True:
        r = requests.get(f"{CME_BASE}/forecasts", params={**params, "pageNumber": page, "pageSize": 1000},
                         headers={"Authorization": f"Bearer {token}"}, timeout=(10, 60))
        r.raise_for_status()
        js = r.json()
        for item in js.get("payload", []):
            for rr in item.get("rateRange", []):
                rows.append({"meeting": item.get("meetingDt"), "reported": item.get("reportingDt"),
                             "lower": rr.get("lowerRt"), "upper": rr.get("upperRt"),
                             "probability": rr.get("probability")})
        meta = js.get("metadata", {})
        if page >= int(meta.get("totalPages", 1) or 1):
            break
        page += 1
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in ("lower", "upper", "probability"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    if df["lower"].max() > 25:  # basis points -> percent
        df[["lower", "upper"]] = df[["lower", "upper"]] / 100
    if df["probability"].max() <= 1.0:
        df["probability"] = df["probability"] * 100
    df["meeting"] = pd.to_datetime(df["meeting"])
    df["reported"] = pd.to_datetime(df["reported"])
    return df


def secret_or_env(name: str, secrets=None) -> str:
    v = os.environ.get(name, "")
    if not v and secrets is not None:
        try:
            v = secrets.get(name, "") or ""
        except Exception:  # noqa: BLE001
            v = ""
    return str(v).strip()
