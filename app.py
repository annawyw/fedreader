"""Fed Reader: FOMC statements, minutes, speeches, projections and policy rules.

Run locally:  streamlit run app.py
Optional keys (Streamlit secrets or environment variables):
  FRED_API_KEY                      faster, more reliable FRED downloads
  CME_API_ID + CME_API_SECRET       CME FedWatch probabilities (paid; else a T-bill proxy is shown)
  (or CME_ACCESS_TOKEN; CME_TOKEN_URL to override the OAuth token address)
"""
import streamlit as st

st.set_page_config(page_title="Fed Reader", layout="wide", initial_sidebar_state="collapsed")

import header  # noqa: E402
import fed_dashboard as fed  # noqa: E402
import policy_rules  # noqa: E402

PAGES = [
    st.Page(fed.page(fed.overview_page), title="Next meeting", url_path="next-meeting", default=True),
    st.Page(fed.page(fed.statements_page), title="Statements", url_path="statements"),
    st.Page(fed.page(fed.speakers_page), title="Speakers", url_path="speakers"),
    st.Page(fed.page(fed.projections_page), title="Projections & dots", url_path="projections"),
    st.Page(policy_rules.page, title="Policy rules", url_path="policy-rules"),
    st.Page(fed.page(fed.minutes_page), title="Minutes", url_path="minutes"),
]
current = st.navigation(PAGES, position="hidden")
header.header("Fed Reader", "FOMC statements, minutes, speeches, projections and policy rules")
header.page_menu(PAGES, current)
current.run()
