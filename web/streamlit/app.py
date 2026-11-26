"""Main entrypoint for the Global Restaurant Explorer Streamlit application."""

from __future__ import annotations

import streamlit as st

from web.streamlit.api_client import APIError
from web.streamlit.components.state import ensure_session_state, load_pipeline_status
from web.streamlit.constants import APP_NAME, APP_SUBTITLE

st.set_page_config(
    page_title=APP_NAME,
    page_icon=":material/restaurant:",
    layout="wide",
    initial_sidebar_state="auto",
)

ensure_session_state()

pages = {
    "Discover": [
        st.Page(
            "pages/explore_restaurants.py",
            title="Explore Restaurants",
            icon=":material/restaurant_menu:",
            default=True,
            help=(
                "Search, filter, and sort verified restaurant records across "
                "countries, cities, cuisines, ratings, and USD-normalized costs."
            ),
        ),
        st.Page(
            "pages/map_explorer.py",
            title="Map Explorer",
            icon=":material/map:",
            help=(
                "Inspect geolocated venues on a theme-aware map with spatial "
                "radius filtering and explicit markers for unrated places."
            ),
        ),
        st.Page(
            "pages/nl_search.py",
            title="Natural Language Search",
            icon=":material/manage_search:",
            help=(
                "Query restaurants in plain English with transparent SearchParams "
                "inspection and deterministic rule-based fallback visibility."
            ),
        ),
    ],
    "Intelligence": [
        st.Page(
            "pages/analytics_briefing.py",
            title="Analytics Briefing",
            icon=":material/analytics:",
            help=(
                "Review dataset coverage, rated vs. unrated counts, cuisine "
                "leaders, and price-tier breakdowns with tabular equivalents."
            ),
        ),
        st.Page(
            "pages/destination_guides.py",
            title="Destination Guides",
            icon=":material/public:",
            help=(
                "Browse country culinary briefings, signature dishes, top cities, "
                "and highest-rated local restaurants."
            ),
        ),
    ],
    "Plan & Operations": [
        st.Page(
            "pages/journey_compare.py",
            title="Journey & Compare",
            icon=":material/route:",
            help=(
                "Compare shortlisted venues side-by-side and plan multi-stop "
                "dining routes with straight-line Haversine leg estimates."
            ),
        ),
        st.Page(
            "pages/pipeline_status.py",
            title="Pipeline Status",
            icon=":material/monitoring:",
            help=(
                "Monitor pipeline runs, 7-day Gold freshness compliance, "
                "and 15% quarantine quality-gate metrics."
            ),
        ),
    ],
}

current_page = st.navigation(pages, position="sidebar")

with st.sidebar:
    st.caption(APP_SUBTITLE)
    st.divider()
    saved_count = len(st.session_state["saved_restaurants"])
    compare_count = len(st.session_state["compare_ids"])
    journey_count = len(st.session_state["journey_stops"])
    st.caption(
        f"Saved: {saved_count} · Compare: {compare_count} · Journey: {journey_count}"
    )
    try:
        pipeline_state = load_pipeline_status()
        freshness_label = "Stale (>7d)" if pipeline_state.get("is_stale") else "Fresh"
        st.caption(
            f"Data status: {freshness_label} · "
            f"Mode: {pipeline_state.get('data_mode', 'database')}"
        )
    except APIError:
        st.caption("Data status: unavailable")

current_page.run()
