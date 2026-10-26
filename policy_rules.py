"""Fed Reader page: the fed funds rate according to policy rules.

Compares three things on one chart:
  * the FOMC's latest dot plot (median year-end fed funds rate, read from federalreserve.gov),
  * "Your rule": the BE rule with inputs and weights you type in on the page,
  * the rule lines from the spreadsheet 'BE rule AI instruction.xlsx':
      BE Rule (pi*=2.0%)                        -> 'Projections (Fed SEP BE Sep (2)' column AI
      BE Rule in past 3 years (pi*=2.8%)        -> 'Projections (Fed SEP BE Sep 26)'  column AI
plus the actual policy rate (quarter-end midpoint of the target range, FRED DFEDTARL/DFEDTARU).

Every rule line follows the spreadsheet formula, quarter by quarter:
  rate_t = rho * rate_{t-1} + (1 - rho) * [ r*_t + pi_t + a*(pi_t - pi*_t) - b*(u_t - u*_t) + W_t ]
with rho = 0.85, a = 0.5, b = 2 in the spreadsheet. pi_t is core PCE inflation (4-quarter % change) plus
any adjustment. The spreadsheet lines stay fixed; only "Your rule" changes when you edit.
"""
from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

import fed_dashboard as fed

# ------------------------------------------------------------------ spreadsheet inputs
# Copied from 'BE rule AI instruction.xlsx' (rows 104-131 = 2022Q1-2028Q4).
QUARTERS = ['2022Q1', '2022Q2', '2022Q3', '2022Q4', '2023Q1', '2023Q2', '2023Q3', '2023Q4', '2024Q1', '2024Q2', '2024Q3', '2024Q4', '2025Q1', '2025Q2', '2025Q3', '2025Q4', '2026Q1', '2026Q2', '2026Q3', '2026Q4', '2027Q1', '2027Q2', '2027Q3', '2027Q4', '2028Q1', '2028Q2', '2028Q3', '2028Q4']
UNEMP = [3.8, 3.6, 3.5, 3.6, 3.5, 3.6, 3.7, 3.7, 3.8, 4.0, 4.2, 4.2, 4.1, 4.2, 4.3, 4.5, 4.3, 4.3, 4.2, 4.3, 4.3, 4.3, 4.3, 4.3, 4.2, 4.2, 4.2, 4.2]
CORE_PCE = [5.486013, 5.252729, 5.421554, 5.287741, 4.908707, 4.6, 3.8, 3.2, 2.9, 2.7, 2.7, 2.8, 2.8, 2.7, 2.9, 2.9, 3.1, 3.4, 3.3, 3.3, 2.7, 2.6, 2.5, 2.5, 2.5, 2.4, 2.2, 2.1]
BLUE_USTAR = [4.0, 4.2, 4.4, 4.5, 4.5, 4.4, 4.3, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2]
BLUE_RSTAR = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.55, 0.4, 0.35, 0.3, 0.25, 0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
BLUE_PISTAR = [2.0, 2.0, 2.0, 2.0, 2.8, 2.8, 2.8, 2.8, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0]
ORANGE_USTAR = [4.0, 4.2, 4.4, 4.5, 4.5, 4.4, 4.3, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2, 4.2]
ORANGE_RSTAR = [0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.55, 0.4, 0.35, 0.3, 0.25, 0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0]
ORANGE_PISTAR = [2.0, 2.0, 2.0, 2.0, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8, 2.8]
ACTUAL_SHEET = {"2020Q1": 0.125, "2020Q2": 0.125, "2020Q3": 0.125, "2020Q4": 0.125, "2021Q1": 0.125, "2021Q2": 0.125, "2021Q3": 0.125, "2021Q4": 0.125, "2022Q1": 0.375, "2022Q2": 1.625, "2022Q3": 3.125, "2022Q4": 4.375, "2023Q1": 4.875, "2023Q2": 5.125, "2023Q3": 5.375, "2023Q4": 5.375, "2024Q1": 5.375, "2024Q2": 5.375, "2024Q3": 4.875, "2024Q4": 4.375, "2025Q1": 4.375, "2025Q2": 4.375, "2025Q3": 4.125, "2025Q4": 3.625, "2026Q1": 3.625}

# Fallback if the Fed's website can't be reached: September 16, 2026 SEP medians.
FALLBACK_SEP = {"label": "Sep 2026", "url": "https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm",
                "ff": {2026: 4.1, 2027: 4.1, 2028: 3.9, 2029: 3.6},
                "ff_prev": {2026: 3.8, 2027: 3.6, 2028: 3.4}, "prev_label": "Jun 2026",
                "u": {2026: 4.1, 2027: 4.1, 2028: 4.1, 2029: 4.1},
                "core": {2026: 3.4, 2027: 2.5, 2028: 2.2, 2029: 2.0}}

# Policy-rate fallback when FRED can't be reached: spreadsheet column E, then FOMC decisions since
# (held at 3.50-3.75 through July 2026; raised to 3.75-4.00 on Sep 16, 2026).
ACTUAL_FALLBACK = {**ACTUAL_SHEET, "2026Q2": 3.625, "2026Q3": 3.875, "2026Q4": 3.875}

ELB_QUARTERS = [f"{y}Q{q}" for y in (2020, 2021) for q in (1, 2, 3, 4)]
EXTRA_QUARTERS = [f"2029Q{q}" for q in (1, 2, 3, 4)]  # your rule runs one year past the spreadsheet
MINE_QUARTERS = QUARTERS + EXTRA_QUARTERS
CARD_YEARS = [2026, 2027, 2028, 2029]
START_CHOICES = ["2021Q4"] + QUARTERS[:-1]
COEF_SHEET = {"rho": 0.85, "a": 0.5, "b": 2.0, "floor_on": False, "floor": 0.125}

LINES = {
    "blue": dict(
        name="BE Rule (π*=2.0%)", color="#2f8fe0", start="2021Q4", start_value=0.125,
        ustar=BLUE_USTAR, rstar=BLUE_RSTAR, pistar=BLUE_PISTAR, adj_from=None,
        source="'Projections (Fed SEP BE Sep (2)' column AI",
        about="The rule with the inflation target back at 2% from 2024 (π* is 2.8% in 2023)."),
    "orange": dict(
        name="BE Rule In Past 3 Years (π* = 2.8%)", color="#d2691e", start="2021Q4", start_value=0.125,
        ustar=ORANGE_USTAR, rstar=ORANGE_RSTAR, pistar=ORANGE_PISTAR, adj_from=None,
        source="'Projections (Fed SEP BE Sep 26)' column AI",
        about="How the Fed has set policy over the past three years: the rule with an implicit 2.8% target."),
}
MINE_NAME = "Your rule"
MINE_COLOR = "#0f9d58"
PI2_NAME = "Your rule with π* = 2.0%"
PI2_COLOR = "#7fcf9f"
ACTUAL_NAME = "Actual"

# Input table columns: internal name -> (label, help)
COLS = {
    "u": ("Unemployment (%)", "Unemployment rate"),
    "core": ("Core PCE (% y/y)", "Core PCE inflation, 4-quarter % change"),
    "adj": ("Core PCE adj. (pp)", "Added to core PCE for this rule only (e.g. −0.2 for a revised core PCE path)"),
    "ustar": ("u* (%)", "Natural rate of unemployment"),
    "rstar": ("r* (%)", "Neutral real interest rate"),
    "pistar": ("π* (%)", "Inflation target the rule aims at"),
    "W": ("Makeup W (pp)", "Makeup term for past inflation shortfalls"),
    "asym": ("No penalty if u < u*", "Apply the unemployment gap only when u is above u*"),
}
NUM_COLS = ["u", "core", "adj", "ustar", "rstar", "pistar", "W"]


def qdate(q: str) -> pd.Timestamp:
    return pd.Timestamp(int(q[:4]), 3 * (int(q[-1]) - 1) + 1, 1)


def date_q(d: pd.Timestamp) -> str:
    return f"{d.year}Q{(d.month - 1) // 3 + 1}"


def sheet_inputs(k: str, extend: bool = False) -> dict:
    """One spreadsheet line's full input table, starting quarter and starting rate. extend=True adds 2029
    rows (copies of 2028Q4, which the spreadsheet doesn't cover) for use as a starting point for your rule."""
    L = LINES[k]
    df = pd.DataFrame({"Quarter": QUARTERS, "u": UNEMP, "core": CORE_PCE, "adj": 0.0, "ustar": L["ustar"],
                       "rstar": L["rstar"], "pistar": L["pistar"], "W": 0.0,
                       "asym": [q in ("2022Q1", "2022Q2") for q in QUARTERS]})
    if L["adj_from"]:
        df.loc[df["Quarter"] >= L["adj_from"], "adj"] = -0.2
    if extend:
        last = df.iloc[[-1] * len(EXTRA_QUARTERS)].copy()
        last["Quarter"] = EXTRA_QUARTERS
        df = pd.concat([df, last], ignore_index=True)
    return {"df": df, "start": L["start"], "start_value": float(L["start_value"])}


# ------------------------------------------------------------------ the rule
def run_rule(inp: pd.DataFrame, start_q: str, start_v: float, coef: dict) -> pd.DataFrame:
    """The spreadsheet's inertial BE rule, one quarter at a time from the starting quarter."""
    a = inp.set_index("Quarter")
    rho, wa, wb = coef["rho"], coef["a"], coef["b"]
    rows = []
    if start_q <= "2021Q4":  # the spreadsheet holds the rule at the lower bound through 2021
        rows += [{"Quarter": q, "Rule rate (%)": start_v, "Note": "Held at lower bound"}
                 for q in ELB_QUARTERS if q < start_q]
    rows.append({"Quarter": start_q, "Rule rate (%)": start_v, "Note": "Starting value"})
    r = start_v
    for q in [q for q in inp["Quarter"] if q > start_q]:
        vals = [a.at[q, c] for c in ("u", "core", "ustar", "rstar", "pistar")]
        if any(pd.isna(v) for v in vals):
            break
        u, core, ustar, rstar, pistar = (float(v) for v in vals)
        adj = 0.0 if pd.isna(a.at[q, "adj"]) else float(a.at[q, "adj"])
        w = 0.0 if pd.isna(a.at[q, "W"]) else float(a.at[q, "W"])
        pi = core + adj
        gap = u - ustar
        pen_gap = 0.0 if (bool(a.at[q, "asym"]) and gap < 0) else gap
        target = rstar + pi + wa * (pi - pistar) - wb * pen_gap + w
        r = rho * r + (1 - rho) * target
        if coef.get("floor_on"):
            r = max(r, coef["floor"])
        rows.append({"Quarter": q, "Unemployment (%)": u, "u* (%)": ustar, "Core PCE used (%)": pi,
                     "π* (%)": pistar, "r* (%)": rstar, "Makeup W (pp)": w, "Unsmoothed rule (%)": target,
                     "Rule rate (%)": r, "Note": ""})
    out = pd.DataFrame(rows)
    out["date"] = out["Quarter"].map(qdate)
    return out


# ------------------------------------------------------------------ data from the Fed and FRED
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _actual_fred(bucket: str) -> pd.DataFrame:
    df = fed.F.fred(["DFEDTARL", "DFEDTARU"], "2020-01-01", fed.FRED_KEY).dropna()
    mid = ((df["DFEDTARL"] + df["DFEDTARU"]) / 2).resample("QS").last().dropna()
    return pd.DataFrame({"date": mid.index, "rate": mid.values})


def actual_rate() -> tuple[pd.DataFrame, str]:
    try:
        df = _actual_fred(fed._bucket())
        if len(df):
            return df, "FRED (DFEDTARL, DFEDTARU), quarter-end midpoint; latest quarter to date"
    except Exception:  # noqa: BLE001
        pass
    df = pd.DataFrame({"date": [qdate(q) for q in ACTUAL_FALLBACK], "rate": list(ACTUAL_FALLBACK.values())})
    return df, "spreadsheet column E plus 2026 FOMC decisions (FRED unavailable)"


def _years(med: pd.DataFrame, var: str, vintage: str) -> dict:
    row = med[(med["variable"] == var) & (med["vintage"] == vintage)]
    if row.empty:
        return {}
    r = row.iloc[0]
    return {int(c): float(r[c]) for c in med.columns if str(c).isdigit() and pd.notna(r[c])}


def latest_sep() -> tuple[dict, bool]:
    """Medians from the FOMC's most recent Summary of Economic Projections (live), else the fallback."""
    try:
        seps = fed.meetings_with("projections")
        d = seps.index[0]
        med = fed.sep(seps.iloc[0]["projections"])["medians"]
        ff = _years(med, "Federal funds rate", "Current")
        if ff:
            return {"label": f"{d:%b %Y}", "url": seps.iloc[0]["projections"], "ff": ff,
                    "ff_prev": _years(med, "Federal funds rate", "Previous"),
                    "prev_label": f"{seps.index[1]:%b %Y}" if len(seps) > 1 else "previous",
                    "u": _years(med, "Unemployment rate", "Current"),
                    "core": _years(med, "Core PCE inflation", "Current")}, True
    except Exception:  # noqa: BLE001
        pass
    return FALLBACK_SEP, False


def dots_frame(d: dict) -> pd.DataFrame:
    return pd.DataFrame({"year": list(d), "value": list(d.values()),
                         "date": [pd.Timestamp(int(y), 10, 1) for y in d]})


# ------------------------------------------------------------------ state for "Your rule"
def _mine_from(k: str) -> dict:
    s = sheet_inputs(k, extend=True)
    return {"df": s["df"], "start": s["start"], "start_value": s["start_value"], "template": k,
            "coef": dict(COEF_SHEET)}


def _state() -> dict:
    if st.session_state.get("pr_mine2", {}).get("template") not in (None, *LINES):  # line no longer offered
        st.session_state.pop("pr_mine2")
    if "pr_mine2" not in st.session_state:
        st.session_state["pr_mine2"] = _mine_from("orange")
        st.session_state["pr_ver"] = 0
    return st.session_state["pr_mine2"]


def changes(mine: pd.DataFrame, base: pd.DataFrame) -> list[str]:
    """Plain-English list of inputs that differ from the spreadsheet line, grouped into runs of quarters."""
    m, b = mine.set_index("Quarter"), base.set_index("Quarter")
    out = []
    for c in NUM_COLS + ["asym"]:
        def fmt(v, c=c):
            if c == "asym":
                return "on" if bool(v) else "off"
            return "blank" if pd.isna(v) else f"{float(v):.2f}"
        runs = []
        for q in m.index:
            new, old = fmt(m.at[q, c]), fmt(b.at[q, c]) if q in b.index else "–"
            key = (new, old) if new != old else None
            if runs and runs[-1][2] == key:
                runs[-1][1] = q
            else:
                runs.append([q, q, key])
        for q0, q1, key in runs:
            if key:
                when = q0 if q0 == q1 else f"{q0}–{q1}"
                out.append(f"{COLS[c][0]}, {when}: {key[0]} (spreadsheet {key[1]})")
    return out


# ------------------------------------------------------------------ chart
def chart(lines: dict, actual: pd.DataFrame, dots: pd.DataFrame, prev: pd.DataFrame | None,
          dots_name: str, prev_name: str, visible: list):
    """lines: {name: (result frame, colour, width)}."""
    domain = [dots_name] + ([prev_name] if prev is not None else []) + [ACTUAL_NAME] + list(lines)
    rng = [fed.HAWK] + (["#f29a9a"] if prev is not None else []) + [fed.INK] + [v[1] for v in lines.values()]
    color = alt.Color("series:N", scale=alt.Scale(domain=domain, range=rng),
                      legend=alt.Legend(orient="top", title=None, columns=2, labelLimit=420, symbolSize=120,
                                        labelFontSize=13))
    frames = []
    if ACTUAL_NAME in visible:
        frames.append(actual.rename(columns={"rate": "value"}).assign(series=ACTUAL_NAME, w=2.4))
    for name, (res, _, width) in lines.items():
        if name in visible:
            frames.append(res[["date", "Rule rate (%)"]].rename(columns={"Rule rate (%)": "value"})
                          .assign(series=name, w=width))
    lines_df = pd.concat(frames) if frames else pd.DataFrame(columns=["date", "value", "series", "w"])
    show_dots = dots_name in visible and len(dots)
    dd = pd.concat(([dots.assign(series=dots_name)] if show_dots else []) +
                   ([prev.assign(series=prev_name)] if prev is not None else []) or
                   [pd.DataFrame(columns=["date", "value", "year", "series"])])

    vals = pd.concat([lines_df["value"], dd["value"]]).astype(float)
    lo = min(0, int(vals.min() // 1)) if len(vals) else 0
    hi = max(6, int(-(-vals.max() // 1))) if len(vals) else 6
    end = pd.Timestamp("2028-12-31")
    if len(dd) and dd["date"].max() + pd.Timedelta(days=92) > end:
        end = dd["date"].max() + pd.Timedelta(days=92)
    x = alt.X("date:T", title=None, scale=alt.Scale(domain=[pd.Timestamp("2020-01-01").isoformat(), end.isoformat()]),
              axis=alt.Axis(format="%Y", tickCount="year", labelFontSize=12))
    y = alt.Y("value:Q", title="Fed funds rate, percent", scale=alt.Scale(domain=[lo, hi], nice=False),
              axis=alt.Axis(orient="right", values=list(range(lo, hi + 1)), labelFontSize=12, grid=True,
                            gridColor=fed.GRID))

    others = lines_df[lines_df["series"] != MINE_NAME]
    layers = [alt.Chart(others).mark_line().encode(
        x=x, y=y, color=color, detail="series:N", strokeWidth=alt.StrokeWidth("w:Q", scale=None, legend=None))]
    for name, shape in ((LINES["orange"]["name"], "square"),):
        part = lines_df[lines_df["series"] == name]
        if len(part):
            layers.append(alt.Chart(part).mark_point(shape=shape, filled=True, size=40).encode(x=x, y=y, color=color))
    mine_df = lines_df[lines_df["series"] == MINE_NAME]
    if len(mine_df):  # drawn last and dashed, so it stays visible when it sits on a spreadsheet line
        layers.append(alt.Chart(mine_df).mark_line(strokeWidth=3.5, strokeDash=[9, 5]).encode(x=x, y=y, color=color))

    # hover: one vertical rule listing every line's value for that quarter
    wide = pd.DataFrame({"date": sorted(set(lines_df["date"]) | set(dd["date"]))})
    tips = [alt.Tooltip("label:N", title="Quarter")]
    for name in [dots_name, prev_name]:  # dot plot medians appear in the Q4 hover box too
        s = dd[dd["series"] == name].set_index("date")["value"]
        if len(s):
            col = f"s{len(tips)}"
            wide[col] = wide["date"].map(s).map(lambda v: "–" if pd.isna(v) else f"{v:.2f}")
            tips.append(alt.Tooltip(f"{col}:N", title=name.replace(" (latest)", "") + ", year-end median"))
    for name in [ACTUAL_NAME] + list(lines):
        s = lines_df[lines_df["series"] == name].set_index("date")["value"]
        if len(s):
            col = f"s{len(tips)}"
            wide[col] = wide["date"].map(s).map(lambda v: "–" if pd.isna(v) else f"{v:.2f}")
            tips.append(alt.Tooltip(f"{col}:N", title=name))
    wide["label"] = wide["date"].map(date_q)
    hover = alt.selection_point(nearest=True, on="pointerover", fields=["date"], empty=False)
    layers.append(alt.Chart(wide).mark_rule(color="#8a8a8a").encode(
        x=x, opacity=alt.condition(hover, alt.value(0.7), alt.value(0)), tooltip=tips).add_params(hover))
    if len(dd):  # drawn after the hover rule so the dots get their own tooltip
        dd = dd.assign(label=dd["year"].map(lambda v: f"End-{int(v)}"))
        layers.append(alt.Chart(dd).mark_circle(size=190, opacity=1).encode(
            x=x, y=y, color=color,
            tooltip=[alt.Tooltip("series:N", title="Dot plot"), alt.Tooltip("label:N", title="Projection for"),
                     alt.Tooltip("value:Q", title="Median fed funds rate (%)", format=".2f")]))
    return alt.layer(*layers).properties(height=520)


def _num(label=None, align="right", **kw):
    """Number column with the given cell alignment. Falls back quietly on Streamlit versions
    without the `alignment` option."""
    try:
        return st.column_config.NumberColumn(label, alignment=align, **kw)
    except TypeError:
        return st.column_config.NumberColumn(label, **kw)


Q4_BG = "#e9e9e6"  # grey fill for fourth-quarter rows


def _is_q4(q) -> bool:
    q = str(q)
    return len(q) == 6 and q[:4].isdigit() and q.endswith("Q4")  # '2026Q4', not the 'Δ ... → 2026Q4' rows


def _q4_style(df: pd.DataFrame):
    """pandas Styler that greys every Q4 row (used by the editable table)."""
    return df.style.apply(lambda r: [f"background-color:{Q4_BG}" if _is_q4(r["Quarter"]) else ""] * len(r),
                          axis=1)


def _table(df: pd.DataFrame, fmt: dict | None = None, height: int | None = None):
    """Read-only HTML table: numeric headings and values right-aligned, Q4 rows greyed."""
    import html as h
    fmt = fmt or {}
    num = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and df[c].dtype != bool]
    pad = "padding:6px 10px;border-bottom:1px solid rgba(128,128,128,.18);white-space:nowrap;"
    head = "".join(f'<th style="{pad}text-align:{"right" if c in num else "left"}">{h.escape(str(c))}</th>'
                   for c in df.columns)
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            if not isinstance(v, str) and pd.isna(v):
                cell = "–"
            elif c in fmt:
                cell = fmt[c].format(v)
            else:
                cell = h.escape(str(v))
            cells.append(f'<td style="{pad}text-align:{"right" if c in num else "left"}">{cell}</td>')
        bg = f' style="background:{Q4_BG}"' if _is_q4(r.get("Quarter", "")) else ""
        body.append(f"<tr{bg}>" + "".join(cells) + "</tr>")
    mh = f"max-height:{height}px;" if height else "max-height:560px;"
    st.html(f"""<div style="overflow:auto;{mh}border:1px solid rgba(128,128,128,.25);border-radius:6px">
<table style="border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums">
<thead><tr style="position:sticky;top:0;background:#f6f6f4">{head}</tr></thead>
<tbody>{"".join(body)}</tbody></table></div>""")


def _colcfg(editable: bool) -> dict:
    cfg = {"Quarter": st.column_config.TextColumn("Quarter", disabled=True)}
    for c in NUM_COLS:
        cfg[c] = _num(COLS[c][0], align="left", help=COLS[c][1], step=0.01, format="%.2f",
                                               disabled=not editable)
    cfg["asym"] = st.column_config.CheckboxColumn(COLS["asym"][0], help=COLS["asym"][1], disabled=not editable)
    return cfg


TABLE_H = 35 * (len(QUARTERS) + 1) + 3  # tall enough to show every quarter without scrolling
MINE_TABLE_H = 35 * (len(MINE_QUARTERS) + 1) + 3


# ------------------------------------------------------------------ headline cards
def _bp(x: float) -> str:
    v = round(x * 100)
    return "0 bp" if v == 0 else f"{v:+d} bp"


def _year_rows(levels: dict, start_prev: float | None, note_missing: str = "–") -> list[tuple]:
    """(year, level text, change text) for each card year. levels: {year: year-end level}."""
    rows, prev = [], start_prev
    for y in CARD_YEARS:
        v = levels.get(y)
        p = levels.get(y - 1, prev if y == CARD_YEARS[0] else None)
        if v is None or pd.isna(v):
            rows.append((y, note_missing, ""))
        else:
            rows.append((y, f"{v:.2f}%", _bp(v - p) if p is not None and pd.notna(p) else ""))
    return rows


def _q4(res: pd.DataFrame) -> dict:
    r = res.set_index("Quarter")["Rule rate (%)"]
    return {y: r[f"{y}Q4"] for y in [CARD_YEARS[0] - 1] + CARD_YEARS if f"{y}Q4" in r.index}


def cards(act: pd.DataFrame, res_mine, res_pi2, res_sheet, template: str, sep: dict):
    """Headline numbers, each with a definition and its year-end path for 2026-2029."""
    import html as h
    last = act.dropna().iloc[-1]
    q_now = date_q(last["date"])
    rate_now = float(last["rate"])
    a = act.set_index(act["date"].map(date_q))["rate"]
    end_prev = a.get(f"{CARD_YEARS[0] - 1}Q4")
    yr = date.today().year

    def rule_card(title, color, res, definition, missing="–"):
        q4 = _q4(res)
        r = res.set_index("Quarter")["Rule rate (%)"]
        v = r.get(q_now)
        sub = f"{_bp(v - rate_now)} vs today's rate" if v is not None else ""
        return dict(title=title, color=color, value=f"{v:.2f}%" if v is not None else "–", sub=sub,
                    definition=definition, rows=_year_rows(q4, None, missing))

    act_rows = [(y, f"{rate_now:.2f}%" if y == yr else "–",
                 _bp(rate_now - end_prev) if y == yr and end_prev is not None else "") for y in CARD_YEARS]
    out = [
        dict(title="Fed funds rate today", color=fed.INK, value=f"{rate_now:.2f}%",
             sub=f"target range {rate_now - 0.125:.2f}–{rate_now + 0.125:.2f}%",
             definition=f"Midpoint of the FOMC's target range in {q_now} (latest data). The actual rate, "
                        f"no projection; its {yr} row is the year to date.", rows=act_rows),
        rule_card(MINE_NAME, MINE_COLOR, res_mine,
                  f"Rate the BE rule gives for {q_now} with the inputs and weights in your table below."),
        rule_card(PI2_NAME, PI2_COLOR, res_pi2,
                  f"Your rule exactly, except the inflation target π* is 2.0% in every quarter. Rate for {q_now}."),
        rule_card(f"Spreadsheet: {LINES[template]['name']}", LINES[template]["color"], res_sheet,
                  f"The spreadsheet's line, unchanged (the one your rule started from). Rate for {q_now}.",
                  missing="n/a"),
    ]
    if yr in sep["ff"]:
        ff = sep["ff"]
        out.append(dict(title=f"FOMC median, {sep['label']} dot plot", color=fed.HAWK, value=f"{ff[yr]:.2f}%",
                        sub=f"{_bp(ff[yr] - rate_now)} vs today's rate",
                        definition=f"Median FOMC participant's projection for the rate at the end of {yr} "
                                   "(midpoint of the target range).",
                        rows=_year_rows(ff, end_prev)))

    def card_html(c):
        rows = "".join(f"<tr><td>{y}</td><td>{h.escape(lv)}</td><td>{h.escape(ch)}</td></tr>" for y, lv, ch in c["rows"])
        return f"""<div class="prc" style="border-top-color:{c['color']}">
  <div class="prc-t">{h.escape(c['title'])}</div>
  <div class="prc-v">{h.escape(c['value'])}</div>
  <div class="prc-s">{h.escape(c['sub'])}</div>
  <div class="prc-d">{h.escape(c['definition'])}</div>
  <table class="prc-y"><thead><tr><th>Year-end</th><th>Rate</th><th>Change in year</th></tr></thead>
  <tbody>{rows}</tbody></table></div>"""

    st.html("""<style>
  .prg{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:6px 0 4px}
  .prc{border:1px solid rgba(128,128,128,.28);border-top:4px solid;border-radius:8px;padding:12px 14px;min-width:0}
  .prc-t{font-weight:600;font-size:14px;line-height:1.25;min-height:2.5em}
  .prc-v{font:600 34px/1.1 "IBM Plex Sans Condensed","Arial Narrow",sans-serif;margin-top:4px;
    font-variant-numeric:tabular-nums}
  .prc-s{font-size:12.5px;opacity:.75;min-height:1.3em}
  .prc-d{font-size:12px;opacity:.7;line-height:1.35;margin:6px 0 8px;min-height:4em}
  .prc-y{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums;white-space:nowrap}
  .prc-y th{font-weight:500;opacity:.6;text-align:right;padding:2px 0;border-bottom:1px solid rgba(128,128,128,.25)}
  .prc-y td{text-align:right;padding:2px 0}
  .prc-y th:first-child,.prc-y td:first-child{text-align:left}
</style><div class="prg">""" + "".join(card_html(c) for c in out) + "</div>")
    st.caption("Year-end = the rate in Q4 of each year. Change in year = year-end rate minus the previous "
               "year-end (Q4 to Q4); for the FOMC median, 2026's change is measured from the actual end-2025 rate. "
               "The spreadsheet's inputs stop at 2028Q4, so its 2029 is n/a.")


# ------------------------------------------------------------------ page
def page():
    """Entry point for app.py. Skips the shared 'Show history from' slider: this chart always starts
    in 2020, like the spreadsheet's."""
    fed.auto_refresh()
    rules_page()


def rules_page():
    st.title("Policy rules: where the fed funds rate should be")
    st.caption("Compare the FOMC's latest dot plot, the spreadsheet's Bloomberg Economics (BE) rule lines, and "
               "your own version of the rule: type over any input in the 'Your rule' table and the chart redraws.")
    mine = _state()
    ver = st.session_state["pr_ver"]
    sep, live = latest_sep()
    dots_name = f"FOMC dot plot, {sep['label']} (latest)"
    prev_name = f"FOMC dot plot, {sep['prev_label']}"
    sheet_names = [LINES[k]["name"] for k in LINES]
    actions: list = []

    c = st.columns([3.2, 1.1], vertical_alignment="center")
    all_series = [dots_name, MINE_NAME, PI2_NAME, ACTUAL_NAME] + sheet_names
    visible = c[0].pills("Show", all_series, selection_mode="multi",
                         default=[x for x in all_series if x != PI2_NAME], key="pr_vis4",
                         label_visibility="collapsed") or []
    show_prev = c[1].toggle(f"Also show {sep['prev_label']} dots", value=False, key="pr_prev",
                            disabled=not sep.get("ff_prev"))
    chart_slot = st.container()

    # ---------------------------------------------------------- inputs
    st.subheader("Inputs")
    st.latex(r"i_t=\rho\, i_{t-1}+(1-\rho)\Big[r^*_t+\pi_t+a\,(\pi_t-\pi^*_t)-b\,(u_t-u^*_t)+W_t\Big]")
    st.caption("i = rule rate · π = core PCE inflation (4-quarter % change) plus the core PCE adjustment · "
               "π* = inflation target · u = unemployment rate · u* = natural rate of unemployment · "
               "r* = neutral real rate · W = makeup term for past inflation shortfalls (zero in the spreadsheet "
               "since 2022). Spreadsheet weights: ρ = 0.85, a = 0.5, b = 2. 'No penalty if u < u*' applies the "
               "unemployment gap only when u is above u* (the spreadsheet does this in 2022Q1–Q2).")

    t_mine, t_sheet, t_res = st.tabs(["Your rule (editable)", "Spreadsheet inputs", "Results by quarter"])

    with t_mine:
        c = st.columns([2.2, 1, 1, 1], vertical_alignment="bottom")
        tmpl = c[0].selectbox("Start from the inputs of", list(LINES), index=list(LINES).index(mine["template"]),
                              format_func=lambda k: LINES[k]["name"], key=f"pr_tmpl_{ver}")
        if c[1].button("Copy these inputs", use_container_width=True,
                       help="Overwrite your table with this spreadsheet line's inputs, start and weights."):
            actions.append(("copy", tmpl))
        if c[2].button(f"Use {sep['label']} SEP outlook", use_container_width=True,
                       help="Fill unemployment and core PCE from the first SEP year's Q4 onward with the latest SEP "
                            "medians, interpolated linearly between year-ends."):
            actions.append(("sep",))
        if c[3].button("Undo my edits", use_container_width=True,
                       help="Go back to the inputs of the line you started from."):
            actions.append(("copy", mine["template"]))

        c = st.columns([1, 1, 1, 1, 1, 1.2], vertical_alignment="bottom")
        sq = c[0].selectbox("Start quarter", START_CHOICES, index=START_CHOICES.index(mine["start"]),
                            key=f"pr_sq_{ver}", help="The rule's recursion starts from this quarter's rate.")
        sv = c[1].number_input("Rate in start quarter (%)", value=mine["start_value"], step=0.05, format="%.4f",
                               key=f"pr_sv_{ver}")
        cb = mine["coef"]
        coef = {"rho": c[2].number_input("Smoothing ρ", 0.0, 0.99, cb["rho"], 0.05, format="%.2f", key=f"pr_rho_{ver}",
                                         help="Weight on last quarter's rate"),
                "a": c[3].number_input("Inflation weight a", -2.0, 5.0, cb["a"], 0.1, format="%.2f", key=f"pr_a_{ver}"),
                "b": c[4].number_input("Unemployment weight b", -2.0, 5.0, cb["b"], 0.1, format="%.2f",
                                       key=f"pr_b_{ver}")}
        coef["floor_on"] = c[5].checkbox("Floor at 0.125%", cb["floor_on"], key=f"pr_flon_{ver}",
                                         help="Never let the rule fall below the lower bound")
        coef["floor"] = 0.125
        st.caption("Click any cell to type over it. Paste works too (copy a column from Excel, click the first "
                   "cell, Ctrl+V). Quarters up to the start quarter are not used.")
        ed_kw = dict(key=f"pr_mine_df_{ver}", hide_index=True, use_container_width=True, height=MINE_TABLE_H,
                     column_config=_colcfg(True))
        try:  # Q4 rows greyed via a pandas Styler; plain table if this Streamlit version can't style the editor
            edited = st.data_editor(_q4_style(mine["df"]), **ed_kw)
        except Exception:  # noqa: BLE001
            edited = st.data_editor(mine["df"], **ed_kw)
        st.caption("Grey rows = fourth quarters (year-end). 2029 rows aren't in the spreadsheet: they start as copies of 2028Q4. Change them as you like.")
        base = sheet_inputs(mine["template"], extend=True)
        diff = changes(edited, base["df"])
        extra = []
        if sq != base["start"] or abs(sv - base["start_value"]) > 1e-9:
            extra.append(f"Start: {sq} at {sv:.4f}% (spreadsheet {base['start']} at {base['start_value']:.4f}%)")
        for k_, lab in (("rho", "ρ"), ("a", "a"), ("b", "b")):
            if abs(coef[k_] - COEF_SHEET[k_]) > 1e-9:
                extra.append(f"Weight {lab}: {coef[k_]:.2f} (spreadsheet {COEF_SHEET[k_]:.2f})")
        if coef["floor_on"]:
            extra.append("Floor at 0.125% on")
        allc = extra + diff
        if allc:
            with st.expander(f"{len(allc)} change{'s' if len(allc) != 1 else ''} from "
                             f"'{LINES[mine['template']]['name']}'", expanded=len(allc) <= 6):
                st.markdown("\n".join(f"- {x}" for x in allc))
        else:
            st.caption(f"No changes yet: your rule is identical to '{LINES[mine['template']]['name']}'.")

    with t_sheet:
        k_show = st.selectbox("Spreadsheet line", list(LINES), index=list(LINES).index(mine["template"]),
                              format_func=lambda k: LINES[k]["name"], key="pr_sheet_show")
        s = sheet_inputs(k_show)
        st.markdown(f"**{LINES[k_show]['name']}** · {LINES[k_show]['about']}")
        st.caption(f"Source: {LINES[k_show]['source']}. Starts in {s['start']} at {s['start_value']:.4f}%. "
                   "Weights ρ = 0.85, a = 0.5, b = 2. Read-only: copy it into 'Your rule' to change it.")
        view = s["df"].assign(asym=s["df"]["asym"].map(lambda v: "✓" if v else ""))
        view = view.rename(columns={c_: COLS[c_][0] for c_ in COLS})
        _table(view, fmt={COLS[c_][0]: "{:.2f}" for c_ in NUM_COLS}, height=TABLE_H + 40)

    # ---------------------------------------------------------- deferred actions
    if actions:
        a = actions[-1]
        if a[0] == "copy":
            st.session_state["pr_mine2"] = _mine_from(a[1])
        elif a[0] == "sep":
            df = edited.copy()
            for col in ("u", "core"):
                anchors = {f"{y}Q4": v for y, v in sep[col].items() if f"{y}Q4" in MINE_QUARTERS}
                if not anchors:
                    continue
                first = min(anchors)
                s_ = df.set_index("Quarter")[col].astype(float)
                s_[s_.index >= first] = float("nan")
                for q, v in anchors.items():
                    s_[q] = v
                df[col] = s_.reset_index(drop=True).interpolate().values
            st.session_state["pr_mine2"] = {"df": df, "start": sq, "start_value": float(sv), "template": mine["template"],
                                           "coef": dict(coef)}
        st.session_state["pr_ver"] = ver + 1
        st.rerun()

    # ---------------------------------------------------------- compute + draw
    res_mine = run_rule(edited, sq, sv, coef)
    res_pi2 = run_rule(edited.assign(pistar=2.0), sq, sv, coef)  # same as yours, with pi* = 2.0% throughout
    res_sheet = {k: run_rule(**{"inp": sheet_inputs(k)["df"], "start_q": LINES[k]["start"],
                                "start_v": LINES[k]["start_value"], "coef": COEF_SHEET}) for k in LINES}
    act, act_src = actual_rate()
    dots = dots_frame(sep["ff"])
    prev = dots_frame(sep["ff_prev"]) if show_prev and sep.get("ff_prev") else None
    lines = {MINE_NAME: (res_mine, MINE_COLOR, 4.0), PI2_NAME: (res_pi2, PI2_COLOR, 2.6)}
    lines.update({LINES[k]["name"]: (res_sheet[k], LINES[k]["color"], 2.2) for k in LINES})

    with chart_slot:
        fed.show(chart(lines, act, dots, prev, dots_name, prev_name, visible))
        st.caption(f"Quarterly. Actual: {act_src}. Dots: FOMC median projection for the year-end rate, plotted in Q4"
                   + ("" if live else " (the Fed's website didn't respond, so these are the Sep 2026 medians)")
                   + f" · [projection materials ↗]({sep['url']}). Spreadsheet lines use the spreadsheet's inputs "
                   "and never change; 'Your rule' uses the table below.")
        tname = LINES[mine["template"]]["name"]
        status = (f"You have made {len(allc)} change{'s' if len(allc) != 1 else ''} to it, listed under the table."
                  if allc else f"You haven't changed anything yet, so it sits exactly on the '{tname}' line.")
        st.html(
            f"""<div style="border-left:4px solid {MINE_COLOR};background:rgba(15,157,88,.07);padding:10px 14px;
border-radius:4px;font-size:14px;line-height:1.5;margin:4px 0 10px">
<b>What "Your rule" means.</b> It is the same Bloomberg Economics rule as the spreadsheet lines, with the same formula
(shown under Inputs below), but calculated from inputs you control: unemployment, core PCE inflation, the natural
rate of unemployment u*, the neutral real rate r*, the inflation target π*, the starting rate, and the weights
ρ, a and b. It starts as a copy of the spreadsheet's '{tname}' line and runs one year further, to 2029.
{status} <b>Your rule with π* = 2.0%</b> uses all of your inputs except that the inflation target is 2.0% in every
quarter. The spreadsheet lines never change.</div>""")
        cards(act, res_mine, res_pi2, res_sheet[mine["template"]], mine["template"], sep)

    with t_res:
        st.markdown(f"**Your rule** compared with **{LINES[mine['template']]['name']}** from the spreadsheet")
        cmp_ = res_mine.drop(columns=["date"]).merge(
            res_sheet[mine["template"]].set_index("Quarter")["Rule rate (%)"].rename("Spreadsheet rule (%)")
        .reset_index(), on="Quarter", how="left")
        cmp_["Difference (bp)"] = (cmp_["Rule rate (%)"] - cmp_["Spreadsheet rule (%)"]) * 100
        cmp_ = cmp_.rename(columns={"Rule rate (%)": "Your rule (%)"})
        order = ["Quarter", "Unemployment (%)", "u* (%)", "Core PCE used (%)", "π* (%)", "r* (%)", "Makeup W (pp)",
                 "Unsmoothed rule (%)", "Your rule (%)", "Spreadsheet rule (%)", "Difference (bp)", "Note"]
        cmp_ = cmp_[[c_ for c_ in order if c_ in cmp_.columns]]
        cmp_ = cmp_[cmp_["Quarter"] >= "2022Q1"].reset_index(drop=True)  # skip the 2020-21 lower-bound years
        # change rows at the bottom: Q4 to Q4 for each year (same units as the column: pp, or bp for the gap)
        num = [c_ for c_ in cmp_.columns if c_ not in ("Quarter", "Note")]
        byq = cmp_.set_index("Quarter")
        chg = []
        for y in CARD_YEARS:
            q1, q0 = f"{y}Q4", f"{y - 1}Q4"
            if q1 in byq.index and q0 in byq.index:
                row = {c_: pd.to_numeric(byq.at[q1, c_], errors="coerce") - pd.to_numeric(byq.at[q0, c_], errors="coerce")
                       for c_ in num}
                row.update({"Quarter": f"Δ {q0} → {q1}", "Note": "Change, Q4 to Q4 (pp; bp for the difference)"})
                chg.append(row)
        if chg:
            cmp_ = pd.concat([cmp_, pd.DataFrame(chg)], ignore_index=True)
        num_c = [c_ for c_ in cmp_.columns if c_ not in ("Quarter", "Note")]
        cmp_[num_c] = cmp_[num_c].apply(pd.to_numeric, errors="coerce")
        cmp_["Note"] = cmp_["Note"].fillna("")
        _table(cmp_, fmt={c_: ("{:+.0f}" if "bp" in c_ else "{:.2f}") for c_ in num_c},
                  height=37 * (len(cmp_) + 1) + 10)

    out = pd.DataFrame({"Quarter": [date_q(x) for x in act["date"]], ACTUAL_NAME: act["rate"].values})
    for name, (res, _, _) in lines.items():
        out = out.merge(res[["Quarter", "Rule rate (%)"]].rename(columns={"Rule rate (%)": name}),
                        on="Quarter", how="outer")
    st.download_button("Download the chart data (CSV)", out.sort_values("Quarter").to_csv(index=False),
                       "policy_rules.csv", "text/csv")
