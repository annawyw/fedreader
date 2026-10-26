"""Plain page header for the public Fed Reader: a text title and the page menu (no logo)."""
from __future__ import annotations

import streamlit as st

FONTS = ("https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500"
         "&family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap")
FED_BLUE = "#1f4fd1"


def header(title: str = "Fed Reader", tagline: str = "") -> None:
    """Title line in the site's type; hides the sidebar (navigation is the page menu below)."""
    st.html(f"""
<style>
  @import url("{FONTS}");
  [data-testid="stMain"] h1, [data-testid="stMain"] h2,
  [data-testid="stMain"] h3, [data-testid="stMain"] h4 {{
    font-family:"IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif !important;
    letter-spacing:-.01em; line-height:1.15 !important; }}
  [data-testid="stMain"] h1, [data-testid="stMain"] h2 {{
    font-size:30px !important; font-weight:700 !important; padding-top:.2rem; }}
  [data-testid="stMain"] h3 {{ font-size:22px !important; font-weight:600 !important; }}
  [data-testid="stMain"] h4 {{ font-size:18px !important; font-weight:600 !important; }}
  [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
  [data-testid="stSidebarNav"], [data-testid="collapsedControl"] {{ display: none !important; }}
  .fr-bar {{ display:flex; align-items:baseline; gap:16px; flex-wrap:wrap;
    padding:0 0 14px; margin:-8px 0 14px; border-bottom:1px solid rgba(128,128,128,.25); }}
  .fr-title {{ font:700 44px/1 "IBM Plex Sans Condensed","Arial Narrow",system-ui,sans-serif;
    letter-spacing:-.01em; color:{FED_BLUE}; }}
  .fr-tag {{ font-size:15px; opacity:.7; }}
  @media (max-width:560px) {{ .fr-title {{ font-size:32px; }} }}
</style>
<div class="fr-bar"><span class="fr-title">{title}</span><span class="fr-tag">{tagline}</span></div>""")


def page_menu(pages: list, current) -> None:
    """Horizontal page menu."""
    if len(pages) < 2:
        return
    titles = [p.title for p in pages]
    choice = st.pills("Page", titles, default=current.title, label_visibility="collapsed",
                      key=f"fr_pg_{current.url_path}")
    if choice and choice != current.title:
        st.switch_page(pages[titles.index(choice)])
