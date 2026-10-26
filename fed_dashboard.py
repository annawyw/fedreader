"""Fed Reader pages: next meeting, statements, speakers, projections, minutes.

Imported by app.py. Data comes from federalreserve.gov (calendar, statements, minutes,
projections, speech and testimony feeds), FRED, and optionally CME FedWatch.
"""
from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import fed_data as F

# Chart colours.
BLUE = "#2a78d6"
ORANGE = "#eb6834"
CATEGORICAL = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#8c6bd1", "#3fb7c9", "#a0785a"]
HAWK = "#d03b3b"   # hawkish / tighter
DOVE = "#2a78d6"   # dovish / easier
GREY = "#7a7974"
LABEL_INK = "#898781"
GRID = "#8987814d"
INK = "#3b3a37"
DAY = 24 * 3600
DEFAULT_START = 2022


def _key(name: str) -> str:
    try:
        return F.secret_or_env(name, st.secrets)
    except Exception:  # noqa: BLE001  (no secrets file)
        return F.secret_or_env(name)


FRED_KEY = _key("FRED_API_KEY")


# ------------------------------------------------------------------ release-day refresh
def _now_et():
    from datetime import datetime, timedelta, timezone
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("America/New_York"))
    except Exception:  # noqa: BLE001  (no time-zone database: assume US daylight time)
        return datetime.now(timezone(timedelta(hours=-4)))


def release_window() -> str:
    """'' normally; otherwise what may be released now. Decision days (statement, projections) and
    minutes days (three weeks later) from 1:55 pm to 6 pm Eastern."""
    now = _now_et()
    if not (now.hour == 13 and now.minute >= 55 or 14 <= now.hour < 18):
        return ""
    today = pd.Timestamp(now.date())
    sched = pd.to_datetime(F.SCHEDULE)
    if today in sched:
        return "statement" + (" and projections" if today.month in F.SEP_MONTHS else "")
    if today in sched + pd.Timedelta(days=21):
        return "minutes"
    return ""


REFRESH_SECONDS = 180  # how often to re-check the Fed's site during a release window


def _bucket() -> str:
    """Cache key: changes every 3 minutes during a release window, every 6 hours otherwise."""
    now = _now_et()
    if release_window():
        return now.strftime("%Y%m%d%H") + f"{now.minute // 3:02d}"
    return now.strftime("%Y%m%d") + str(now.hour // 6)


# ------------------------------------------------------------------ cached loaders
@st.cache_data(ttl=7 * 3600, show_spinner="Loading the FOMC calendar…")
def _calendar(bucket: str) -> pd.DataFrame:
    return F.parse_calendar(F.get(F.CALENDAR_URL))


def calendar() -> pd.DataFrame:
    return _calendar(_bucket())


def auto_refresh():
    """On release days, re-run the page every few minutes so new documents appear on their own."""
    what = release_window()
    if not what:
        return
    st.caption(f"🔄 FOMC {what} day: this page checks the Fed's website every "
               f"{REFRESH_SECONDS // 60} minutes until 6 pm ET.")
    if not hasattr(st, "fragment"):
        return

    @st.fragment(run_every=REFRESH_SECONDS)
    def _tick():
        key = "fed_tick_bucket"
        b = _bucket()
        if st.session_state.get(key) not in (None, b):
            st.session_state[key] = b
            st.rerun()
        st.session_state[key] = b

    _tick()


@st.cache_data(ttl=30 * DAY, show_spinner=False)
def statement(url: str) -> dict:
    return F.parse_statement(F.get(url))


@st.cache_data(ttl=30 * DAY, show_spinner=False)
def minutes(url: str) -> dict:
    return F.parse_minutes(F.get(url))


@st.cache_data(ttl=30 * DAY, show_spinner=False)
def sep(url: str) -> dict:
    return F.parse_sep(F.get(url))


@st.cache_data(ttl=3 * 3600, show_spinner="Loading Fed speeches…")
def feeds() -> pd.DataFrame:
    frames = []
    for kind, url in F.FEEDS.items():
        try:
            frames.append(F.parse_feed(F.get(url), kind))
        except Exception:  # noqa: BLE001
            pass
    if not frames:
        raise RuntimeError("Couldn't download the Fed's speech and testimony feeds.")
    return pd.concat(frames).sort_values("date", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=30 * DAY, show_spinner=False)
def speech(url: str) -> dict:
    return F.parse_speech(F.get(url))


@st.cache_data(ttl=6 * 3600, show_spinner="Loading rates from FRED…")
def fred(ids: tuple, start: str) -> pd.DataFrame:
    return F.fred(list(ids), start, FRED_KEY)


@st.cache_data(ttl=6 * 3600, show_spinner="Loading CME FedWatch…")
def fedwatch() -> pd.DataFrame:
    token = _key("CME_ACCESS_TOKEN")
    if not token:
        cid, sec = _key("CME_API_ID"), _key("CME_API_SECRET")
        if not (cid and sec):
            return pd.DataFrame()
        token = F.cme_token(cid, sec, _key("CME_TOKEN_URL") or F.CME_TOKEN_URL)
    return F.cme_forecasts(token)


# ------------------------------------------------------------------ helpers
def start_year() -> int:
    return int(st.session_state.get("fed_start", DEFAULT_START))


def controls():
    """Settings row at the top of every Fed Reader page (no sidebar)."""
    c1, c2 = st.columns([5, 1.3], vertical_alignment="bottom", gap="medium")
    c1.slider("Show history from", 2015, date.today().year, DEFAULT_START, key="fed_start")
    if c2.button("Refresh Data", key="fed_refresh", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


def page(fn):
    def run():
        controls()
        auto_refresh()
        fn()
    run.__name__ = fn.__name__
    return run


def or_stop(fn, what: str):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        st.error(f"Couldn't load {what}: {e}")
        st.info("The Fed's website or FRED may be slow right now. Click Refresh Data or try again shortly.")
        st.stop()


def axis_cfg(chart):
    return chart.configure_axis(grid=False, domain=False, tickColor=GRID, labelFontSize=11,
                                titleFontSize=11).configure_view(stroke=None)


def show(chart):
    st.altair_chart(axis_cfg(chart), use_container_width=True)


def fmt_range(lo, hi) -> str:
    if lo is None or hi is None or pd.isna(lo) or pd.isna(hi):
        return "–"
    return f"{lo:.2f}–{hi:.2f}%"


def meetings_with(col: str) -> pd.DataFrame:
    cal = calendar()
    return cal[cal[col].notna()].sort_index(ascending=False)


def tone_label(score: float) -> str:
    if score >= 20:
        return "Hawkish"
    if score <= -20:
        return "Dovish"
    return "Balanced"


def table(df: pd.DataFrame, fmt: dict | None = None, links: dict | None = None, height: int | None = None):
    """HTML table: numeric columns (and their headings) right-aligned; `links` maps a column
    holding URLs to the text to show for them."""
    import html as h
    fmt, links = fmt or {}, links or {}
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c not in links]
    pad = "padding:6px 10px;border-bottom:1px solid rgba(128,128,128,.18);white-space:nowrap;"
    head = "".join(f'<th style="{pad}text-align:{"right" if c in num else "left"}">{h.escape(str(c))}</th>'
                   for c in df.columns)
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            if c in links:
                cell = f'<a href="{h.escape(str(v))}" target="_blank" rel="noopener">{links[c]}</a>' if v else ""
            elif pd.isna(v) if not isinstance(v, str) else False:
                cell = "–"
            elif c in fmt:
                cell = fmt[c].format(v)
            else:
                cell = h.escape(str(v))
            cells.append(f'<td style="{pad}text-align:{"right" if c in num else "left"}">{cell}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    mh = f"max-height:{height}px;" if height else "max-height:560px;"
    st.html(f"""<div style="overflow:auto;{mh}border:1px solid rgba(128,128,128,.25);border-radius:6px">
<table style="border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums">
<thead><tr style="position:sticky;top:0;background:#f6f6f4">{head}</tr></thead>
<tbody>{"".join(body)}</tbody></table></div>""")


TONE_NOTE = ("Tone score: hawkish phrases minus dovish phrases as a share of both, from −100 "
             "(all dovish) to +100 (all hawkish). A simple word count, so read it as a direction, "
             "not a precise measure.")


# ================================================================== page 1: next meeting
def overview_page():
    st.title("Next meeting and the policy rate")
    st.caption("Federal Reserve, FRED and (if configured) CME FedWatch. Times are the decision day of each meeting.")

    nxt, days, has_sep = F.next_meeting()
    y0 = start_year()
    rates = or_stop(lambda: fred(("DFEDTARL", "DFEDTARU", "DFF", "DTB3", "DTB6", "DTB1YR"),
                                 f"{y0}-01-01"), "rates from FRED")
    rates = rates.ffill()
    last = rates.dropna(subset=["DFEDTARU"]).iloc[-1]
    lo, hi = last["DFEDTARL"], last["DFEDTARU"]
    mid = (lo + hi) / 2

    cal = or_stop(calendar, "the FOMC calendar")
    stm_rows = cal[cal["statement"].notna()]
    last_dec = None
    if len(stm_rows):
        d = stm_rows.index.max()
        last_dec = (d, statement(stm_rows.loc[d, "statement"]))

    c = st.columns(4)
    if nxt is not None:
        c[0].metric("Next FOMC decision", f"{nxt:%b %d, %Y}",
                    f"in {days} days" + (" · with projections" if has_sep else ""), delta_color="off")
    c[1].metric("Target range", fmt_range(lo, hi))
    c[2].metric("Effective fed funds rate", f"{last['DFF']:.2f}%",
                f"{(last['DFF'] - mid) * 100:+.0f} bp vs range midpoint", delta_color="off")
    if last_dec:
        d, s = last_dec
        act = s.get("action") or "—"
        bp = s.get("change_bp")
        txt = f"{act} {bp:+d} bp" if act in ("Hike", "Cut") and bp is not None else act
        dis = s.get("votes_against") or 0
        c[3].metric(f"Last decision ({d:%b %d})", txt,
                    f"{dis} dissent{'s' if dis != 1 else ''}" if s.get("votes_for") is not None else None,
                    delta_color="off")

    # ---------------------------------------------------------- market-implied path
    st.subheader("What markets expect")
    fw = pd.DataFrame()
    try:
        fw = fedwatch()
    except Exception as e:  # noqa: BLE001
        st.warning(f"CME FedWatch didn't respond ({e}). Showing the Treasury bill proxy instead.")
    if not fw.empty:
        latest = fw[fw["reported"] == fw["reported"].max()]
        latest = latest.assign(mid=(latest["lower"] + latest["upper"]) / 2,
                               label=latest.apply(lambda r: f"{r.lower:.2f}–{r.upper:.2f}", axis=1))
        first = latest["meeting"].min()
        nm = latest[latest["meeting"] == first]
        cc = st.columns([1, 1.4])
        with cc[0]:
            bars = alt.Chart(nm).mark_bar(color=BLUE).encode(
                x=alt.X("label:N", sort=alt.SortField("mid"), title="Target range (%)"),
                y=alt.Y("probability:Q", title="Probability (%)"),
                tooltip=["label", alt.Tooltip("probability:Q", format=".1f")])
            text = bars.mark_text(dy=-8, color=LABEL_INK, fontSize=11).encode(
                text=alt.Text("probability:Q", format=".0f"))
            st.markdown(f"**{first:%b %d, %Y} meeting**")
            show((bars + text).properties(height=280))
        with cc[1]:
            path = (latest.assign(w=latest["mid"] * latest["probability"] / 100)
                    .groupby("meeting").agg(expected=("w", "sum")).reset_index())
            line = alt.Chart(path).mark_line(point=True, color=BLUE).encode(
                x=alt.X("meeting:T", title=None), y=alt.Y("expected:Q", title="Expected rate (%)",
                                                          scale=alt.Scale(zero=False)),
                tooltip=[alt.Tooltip("meeting:T", format="%b %d, %Y"), alt.Tooltip("expected:Q", format=".2f")])
            now = alt.Chart(pd.DataFrame({"y": [mid]})).mark_rule(color=GREY, strokeDash=[4, 3]).encode(y="y:Q")
            st.markdown("**Expected policy rate by meeting** (probability-weighted midpoint)")
            show((now + line).properties(height=280))
        st.caption(f"CME FedWatch, as of {latest['reported'].max():%b %d, %Y}. Dashed line = today's range midpoint.")
    else:
        bills = rates[["DTB3", "DTB6", "DTB1YR"]].dropna(how="all").iloc[-1]
        cc = st.columns(3)
        for col, (sid, lab) in zip(cc, [("DTB3", "3-month bill"), ("DTB6", "6-month bill"), ("DTB1YR", "1-year bill")]):
            v = bills.get(sid)
            if pd.notna(v):
                col.metric(lab, f"{v:.2f}%", f"{(v - mid) * 100:+.0f} bp vs range midpoint", delta_color="off")
        st.caption("Without a CME FedWatch subscription this shows a rough proxy: Treasury bill yields above the "
                   "policy rate point to expected hikes, below it to expected cuts (bills also carry term and "
                   "supply effects). Add CME_API_ID and CME_API_SECRET to your key file for FedWatch "
                   "probabilities, or see [CME FedWatch](https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html) "
                   "and the [Atlanta Fed Market Probability Tracker](https://www.atlantafed.org/cenfis/market-probability-tracker).")

    # ---------------------------------------------------------- policy rate history
    st.subheader("Policy rate")
    h = rates.reset_index().rename(columns={rates.index.name or "index": "date"})
    h = h[h["date"] >= pd.Timestamp(f"{y0}-01-01")]
    band = alt.Chart(h).mark_area(opacity=0.25, color=BLUE).encode(
        x=alt.X("date:T", title=None), y=alt.Y("DFEDTARL:Q", title="%"), y2="DFEDTARU:Q")
    long = h.melt("date", ["DFF", "DTB6"], "series", "value").dropna()
    long["series"] = long["series"].map({"DFF": "Effective fed funds", "DTB6": "6-month T-bill"})
    lines = alt.Chart(long).mark_line(strokeWidth=2).encode(
        x="date:T", y="value:Q",
        color=alt.Color("series:N", scale=alt.Scale(domain=["Effective fed funds", "6-month T-bill"],
                                                    range=[BLUE, ORANGE]), legend=alt.Legend(orient="bottom", title=None)),
        tooltip=[alt.Tooltip("date:T"), "series", alt.Tooltip("value:Q", format=".2f")])
    show((band + lines).properties(height=320))
    st.caption("Shaded band = target range. Sources: FRED (DFEDTARL, DFEDTARU, DFF, DTB6).")

    # ---------------------------------------------------------- inflation vs target
    st.subheader("Inflation against the 2% goal")
    try:
        p = fred(("PCEPILFE", "PCEPI"), f"{y0 - 1}-01-01")
        yy = (p.pct_change(12, fill_method=None) * 100).dropna(how="all")
        yy = yy[yy.index >= pd.Timestamp(f"{y0}-01-01")].reset_index()
        yy = yy.rename(columns={yy.columns[0]: "date"}).melt("date", ["PCEPILFE", "PCEPI"], "series", "value").dropna()
        yy["series"] = yy["series"].map({"PCEPILFE": "Core PCE", "PCEPI": "PCE"})
        ch = alt.Chart(yy).mark_line(strokeWidth=2).encode(
            x=alt.X("date:T", title=None), y=alt.Y("value:Q", title="% y/y"),
            color=alt.Color("series:N", scale=alt.Scale(domain=["Core PCE", "PCE"], range=[ORANGE, GREY]),
                            legend=alt.Legend(orient="bottom", title=None)),
            tooltip=[alt.Tooltip("date:T", format="%b %Y"), "series", alt.Tooltip("value:Q", format=".2f")])
        goal = alt.Chart(pd.DataFrame({"y": [2.0]})).mark_rule(color=GREY, strokeDash=[4, 3]).encode(y="y:Q")
        layers = [goal, ch]
        seps = meetings_with("projections")
        if len(seps):
            med = sep(seps.iloc[0]["projections"])["medians"]
            core = med[(med["variable"] == "Core PCE inflation") & (med["vintage"] == "Current")]
            yr = str(date.today().year)
            if len(core) and yr in core.columns and pd.notna(core.iloc[0][yr]):
                pt = pd.DataFrame({"date": [pd.Timestamp(f"{yr}-12-01")], "value": [core.iloc[0][yr]]})
                layers.append(alt.Chart(pt).mark_point(shape="diamond", size=110, filled=True, color=HAWK).encode(
                    x="date:T", y="value:Q", tooltip=[alt.Tooltip("value:Q", title=f"Fed's {yr} core PCE projection")]))
        show(alt.layer(*layers).properties(height=300))
        st.caption("Dashed line = 2% goal. Diamond = the Fed's latest median projection for core PCE at the end of "
                   "this year.")
    except Exception as e:  # noqa: BLE001
        st.caption(f"Inflation data unavailable ({e}).")


# ================================================================== page 2: statements
def statements_page():
    st.title("FOMC statements: what changed")
    cal = or_stop(calendar, "the FOMC calendar")
    rows = cal[cal["statement"].notna()].sort_index(ascending=False)
    if len(rows) < 2:
        st.warning("Not enough statements found on the Fed's calendar page.")
        return
    dates = list(rows.index)
    c1, c2 = st.columns(2)
    cur = c1.selectbox("Statement", dates, index=0, format_func=lambda d: f"{d:%B %d, %Y}", key="st_cur")
    prev_default = dates.index(cur) + 1 if dates.index(cur) + 1 < len(dates) else 0
    prev = c2.selectbox("Compared with", dates, index=prev_default, format_func=lambda d: f"{d:%B %d, %Y}",
                        key=f"st_prev_{cur:%Y%m%d}")
    s_cur = or_stop(lambda: statement(rows.loc[cur, "statement"]), "the statement")
    s_prev = or_stop(lambda: statement(rows.loc[prev, "statement"]), "the earlier statement")

    t_cur, t_prev = F.tone(s_cur["text"]), F.tone(s_prev["text"])
    k = st.columns(4)
    act = s_cur.get("action") or "—"
    bp = s_cur.get("change_bp")
    k[0].metric("Decision", f"{act} {bp:+d} bp" if act in ("Hike", "Cut") and bp is not None else act)
    k[1].metric("Target range", fmt_range(s_cur.get("lower"), s_cur.get("upper")))
    vf, va = s_cur.get("votes_for"), s_cur.get("votes_against") or 0
    k[2].metric("Vote", f"{vf}–{va}" if vf is not None else "—")
    k[3].metric("Tone", f"{t_cur['score']:+.0f}", f"{t_cur['score'] - t_prev['score']:+.0f} vs compared",
                delta_color="inverse")
    if s_cur.get("dissent"):
        st.caption(f"Dissent: {s_cur['dissent']}")

    st.html("""<style>
  .fed-red {border:1px solid rgba(128,128,128,.3); border-radius:8px; padding:6px 22px; line-height:1.65;
    font-size:15.5px; max-height:640px; overflow:auto;}
  .fed-red ins {background:#0ca30c26; color:inherit; text-decoration:none; border-bottom:2px solid #0ca30c;}
  .fed-red del {background:#d03b3b1f; color:#9a2a2a; text-decoration:line-through;}
</style>""")
    st.markdown(f"**Redline:** {prev:%b %d, %Y} → {cur:%b %d, %Y}. Added text is "
                f"<ins style='text-decoration:none;border-bottom:2px solid #0ca30c'>underlined in green</ins>, "
                f"removed text <del style='color:#9a2a2a'>struck through in red</del>.", unsafe_allow_html=True)
    st.html(f'<div class="fed-red"><p>{F.redline_html(s_prev["text"], s_cur["text"])}</p></div>')
    st.markdown(f"[Statement on federalreserve.gov ↗]({rows.loc[cur, 'statement']})")

    # ---------------------------------------------------------- history
    st.subheader("Decisions and tone over time")
    hist = rows[rows.index >= pd.Timestamp(f"{start_year()}-01-01")].sort_index()
    recs = []
    prog = st.progress(0.0, text="Reading statements…") if len(hist) > 6 else None
    for i, (d, r) in enumerate(hist.iterrows()):
        try:
            s = statement(r["statement"])
        except Exception:  # noqa: BLE001
            continue
        t = F.tone(s["text"])
        recs.append({"date": d, "Decision": s.get("action") or "",
                     "Change (bp)": s.get("change_bp") if s.get("action") in ("Hike", "Cut") else None,
                     "Range": fmt_range(s.get("lower"), s.get("upper")), "Votes for": s.get("votes_for"),
                     "Dissents": s.get("votes_against") or 0, "Tone": t["score"], "Read": tone_label(t["score"])})
        if prog:
            prog.progress((i + 1) / len(hist), text="Reading statements…")
    if prog:
        prog.empty()
    df = pd.DataFrame(recs)
    if df.empty:
        return
    bars = alt.Chart(df).mark_bar().encode(
        x=alt.X("date:T", title=None), y=alt.Y("Tone:Q", title="Tone (− dovish / + hawkish)",
                                               scale=alt.Scale(domain=[-100, 100])),
        color=alt.condition("datum.Tone >= 0", alt.value(HAWK), alt.value(DOVE)),
        tooltip=[alt.Tooltip("date:T", format="%b %d, %Y"), "Decision", "Range", alt.Tooltip("Tone:Q", format="+.0f")])
    zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=LABEL_INK).encode(y="y:Q")
    show((zero + bars).properties(height=260))
    st.caption(TONE_NOTE)
    out = df.sort_values("date", ascending=False).assign(Date=lambda x: x["date"].dt.strftime("%b %d, %Y"))
    table(out[["Date", "Decision", "Change (bp)", "Range", "Votes for", "Dissents", "Tone", "Read"]],
          fmt={"Tone": "{:+.0f}", "Change (bp)": "{:+.0f}", "Votes for": "{:.0f}"})


# ================================================================== page 3: speakers
def speakers_page():
    st.title("Fed speakers")
    st.caption("Speeches and testimony by the Chair, Vice Chairs and Governors (all of whom vote at every meeting), "
               "from the Federal Reserve Board's feeds. Reserve Bank presidents publish on their own banks' sites "
               "and are not included.")
    fd = or_stop(feeds, "the Fed's speech feeds")
    fd = fd[fd["date"] >= pd.Timestamp(f"{start_year()}-01-01")]
    c1, c2 = st.columns([3, 2])
    n = c2.slider("Speeches to score", 10, min(150, max(10, len(fd))), min(40, max(10, len(fd))), key="sp_n",
                  help="Each speech is downloaded once and kept for 30 days.")
    kinds = c1.multiselect("Include", ["Speech", "Testimony"], default=["Speech", "Testimony"], key="sp_kind")
    fd = fd[fd["kind"].isin(kinds)].head(n)
    recs = []
    prog = st.progress(0.0, text="Reading speeches…")
    for i, r in enumerate(fd.itertuples()):
        try:
            sp = speech(r.link)
            t = F.tone(sp["text"])
            role, name = sp["role"], sp["name"] or r.speaker
        except Exception:  # noqa: BLE001
            t, role, name = {"score": None, "hawk": 0, "dove": 0}, "", r.speaker
        recs.append({"date": r.date, "Speaker": r.speaker, "Role": role, "Name": name, "Type": r.kind,
                     "Title": r.title, "Tone": t["score"], "Read": tone_label(t["score"]) if t["score"] is not None else "",
                     "Link": r.link})
        prog.progress((i + 1) / max(len(fd), 1), text="Reading speeches…")
    prog.empty()
    df = pd.DataFrame(recs)
    if df.empty:
        st.info("No speeches in this window.")
        return
    scored = df.dropna(subset=["Tone"])
    speakers = scored["Speaker"].value_counts().index.tolist()
    top = speakers[: len(CATEGORICAL)]
    scored = scored.assign(Who=scored["Speaker"].where(scored["Speaker"].isin(top), "Other"))
    domain = top + (["Other"] if (scored["Who"] == "Other").any() else [])
    rng = CATEGORICAL[: len(top)] + ([GREY] if "Other" in domain else [])

    cc = st.columns([1.6, 1])
    with cc[0]:
        pts = alt.Chart(scored).mark_circle(size=90, opacity=0.85).encode(
            x=alt.X("date:T", title=None), y=alt.Y("Tone:Q", title="Tone (− dovish / + hawkish)",
                                                   scale=alt.Scale(domain=[-100, 100])),
            color=alt.Color("Who:N", scale=alt.Scale(domain=domain, range=rng),
                            legend=alt.Legend(orient="bottom", title=None, columns=4)),
            tooltip=[alt.Tooltip("date:T", format="%b %d, %Y"), "Speaker", "Title", alt.Tooltip("Tone:Q", format="+.0f")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=LABEL_INK).encode(y="y:Q")
        st.markdown("**Tone of each speech**")
        show((zero + pts).properties(height=320))
    with cc[1]:
        recent = scored[scored["date"] >= scored["date"].max() - pd.Timedelta(days=120)]
        avg = recent.groupby("Speaker", as_index=False).agg(Tone=("Tone", "mean"), Speeches=("Tone", "size"))
        bars = alt.Chart(avg).mark_bar().encode(
            y=alt.Y("Speaker:N", sort="-x", title=None),
            x=alt.X("Tone:Q", title="Average tone, last 120 days", scale=alt.Scale(domain=[-100, 100])),
            color=alt.condition("datum.Tone >= 0", alt.value(HAWK), alt.value(DOVE)),
            tooltip=["Speaker", alt.Tooltip("Tone:Q", format="+.0f"), "Speeches"])
        st.markdown("**Who leans which way**")
        show(bars.properties(height=320))
    st.caption(TONE_NOTE)

    who = st.multiselect("Filter speakers", speakers, key="sp_who")
    view = df[df["Speaker"].isin(who)] if who else df
    view = view.assign(Date=view["date"].dt.strftime("%b %d, %Y"),
                       Speaker=view.apply(lambda r: f"{r.Role} {r.Name}".strip() or r.Speaker, axis=1))
    table(view[["Date", "Speaker", "Type", "Title", "Tone", "Read", "Link"]],
          fmt={"Tone": "{:+.0f}"}, links={"Link": "Read ↗"})


# ================================================================== page 4: projections
def projections_page():
    st.title("Projections and the dot plot")
    seps = or_stop(lambda: meetings_with("projections"), "the FOMC calendar")
    if seps.empty:
        st.warning("No Summary of Economic Projections found on the Fed's calendar page.")
        return
    d = st.selectbox("Projections from", list(seps.index), format_func=lambda x: f"{x:%B %Y} meeting", key="sep_d")
    url = seps.loc[d, "projections"]
    r = or_stop(lambda: sep(url), "the projections")
    med, dots = r["medians"], r["dots"]
    if med.empty:
        st.warning("Couldn't read the projections table on this page.")
        st.markdown(f"[Projection materials on federalreserve.gov ↗]({url})")
        return
    horizons = [c for c in med.columns if c not in ("variable", "vintage")]

    ff = med[med["variable"] == "Federal funds rate"]
    if not ff.empty:
        long = ff.melt(["variable", "vintage"], horizons, "Horizon", "Median").dropna()
        long["Vintage"] = long["vintage"].map({"Current": f"{d:%B %Y}", "Previous": "Previous projections"})
        c1, c2 = st.columns([1.3, 1])
        with c1:
            st.markdown("**The dot plot:** each dot is one participant's view of the appropriate year-end rate")
            if not dots.empty:
                dd = dots.loc[dots.index.repeat(dots["count"])].copy()
                dd["i"] = dd.groupby(["horizon", "rate"]).cumcount()
                dd["n"] = dd.groupby(["horizon", "rate"])["count"].transform("first")
                dd["offset"] = dd["i"] - (dd["n"] - 1) / 2
                pts = alt.Chart(dd).mark_circle(size=70, color=BLUE, opacity=0.9).encode(
                    x=alt.X("horizon:N", sort=horizons, title=None),
                    xOffset=alt.XOffset("offset:Q", scale=alt.Scale(domain=[-10, 10])),
                    y=alt.Y("rate:Q", title="Fed funds rate, % (midpoint)", scale=alt.Scale(zero=False)),
                    tooltip=["horizon", alt.Tooltip("rate:Q", format=".3f"), "count"])
                cur_med = long[long["vintage"] == "Current"]
                medm = alt.Chart(cur_med).mark_tick(color=HAWK, thickness=3, size=60).encode(
                    x=alt.X("Horizon:N", sort=horizons), y="Median:Q",
                    tooltip=["Horizon", alt.Tooltip("Median:Q", format=".2f", title="Median")])
                show((pts + medm).properties(height=380))
                st.caption("Red tick = median.")
            else:
                st.caption("Dot plot table not found on this page.")
        with c2:
            st.markdown("**Median rate path vs previous projections**")
            line = alt.Chart(long).mark_line(point=True, strokeWidth=2).encode(
                x=alt.X("Horizon:N", sort=horizons, title=None),
                y=alt.Y("Median:Q", title="%", scale=alt.Scale(zero=False)),
                color=alt.Color("Vintage:N", scale=alt.Scale(range=[BLUE, GREY]),
                                legend=alt.Legend(orient="bottom", title=None)),
                strokeDash=alt.StrokeDash("Vintage:N", legend=None),
                tooltip=["Vintage", "Horizon", alt.Tooltip("Median:Q", format=".2f")])
            show(line.properties(height=380))

    st.subheader("Median projections")
    tbl = med.copy()
    tbl["Projection"] = tbl["vintage"].map({"Current": f"{d:%b %Y}", "Previous": "Previous"})
    tbl = tbl[["variable", "Projection"] + horizons].rename(columns={"variable": "Variable"})
    table(tbl, fmt={h: "{:.1f}" for h in horizons})
    cur = med[med["vintage"] == "Current"].set_index("variable")
    prv = med[med["vintage"] == "Previous"].set_index("variable")
    if not prv.empty:
        chg = (cur[horizons] - prv.reindex(cur.index)[horizons]).round(2)
        st.markdown("**Change since the previous projections (percentage points)**")
        table(chg.reset_index().rename(columns={"variable": "Variable"}), fmt={h: "{:+.1f}" for h in horizons})
    st.markdown(f"[Projection materials on federalreserve.gov ↗]({url})")


# ================================================================== page 5: minutes
def minutes_page():
    st.title("FOMC minutes")
    rows = or_stop(lambda: meetings_with("minutes"), "the FOMC calendar")
    if rows.empty:
        st.warning("No minutes found on the Fed's calendar page yet.")
        return
    d = st.selectbox("Minutes of the meeting on", list(rows.index), format_func=lambda x: f"{x:%B %d, %Y}",
                     key="mn_d")
    url = rows.loc[d, "minutes"]
    m = or_stop(lambda: minutes(url), "the minutes")
    if not m["text"]:
        st.caption("Minutes are published three weeks after each meeting; this link may not be live yet.")
    t = F.tone(m["text"])
    k = st.columns(3)
    k[0].metric("Tone", f"{t['score']:+.0f}", tone_label(t["score"]), delta_color="off")
    k[1].metric("Hawkish phrases", t["hawk"])
    k[2].metric("Dovish phrases", t["dove"])
    st.caption(TONE_NOTE)

    st.subheader("Key passages")
    for topic, sents in m["passages"].items():
        with st.expander(f"{topic} ({len(sents)})", expanded=topic in ("Inflation", "Policy outlook")):
            if not sents:
                st.caption("Nothing notable found.")
            for s in sents:
                st.markdown(f"- {s}")
    st.markdown(f"[Full minutes on federalreserve.gov ↗]({url})")

    st.subheader("Tone of recent minutes")
    recent = rows[rows.index >= pd.Timestamp(f"{start_year()}-01-01")].head(12)
    recs = []
    for dd, r in recent.iterrows():
        try:
            tt = F.tone(minutes(r["minutes"])["text"])
            if tt["hawk"] + tt["dove"]:
                recs.append({"date": dd, "Tone": tt["score"]})
        except Exception:  # noqa: BLE001
            continue
    if recs:
        df = pd.DataFrame(recs)
        bars = alt.Chart(df).mark_bar().encode(
            x=alt.X("date:T", title=None), y=alt.Y("Tone:Q", scale=alt.Scale(domain=[-100, 100]),
                                                   title="Tone (− dovish / + hawkish)"),
            color=alt.condition("datum.Tone >= 0", alt.value(HAWK), alt.value(DOVE)),
            tooltip=[alt.Tooltip("date:T", format="%b %d, %Y"), alt.Tooltip("Tone:Q", format="+.0f")])
        zero = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color=LABEL_INK).encode(y="y:Q")
        show((zero + bars).properties(height=240))
