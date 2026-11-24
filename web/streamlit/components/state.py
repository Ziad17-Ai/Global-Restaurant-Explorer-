"""Shared `st.session_state` initialization and cached data loaders."""

from __future__ import annotations

import streamlit as st

from web.streamlit.api_client import (
    AnalyticsSummary,
    CitiesResponse,
    CountriesResponse,
    CuisinesResponse,
    DestinationProfile,
    PipelineStatus,
    RestaurantDetailResponse,
    RestaurantItem,
    get_api_client,
)
from web.streamlit.constants import MAX_COMPARE_ITEMS, MAX_JOURNEY_STOPS
from web.streamlit.settings import settings


def ensure_session_state() -> None:
    """Initialize all shared session-state keys if absent."""
    if "saved_restaurants" not in st.session_state:
        st.session_state["saved_restaurants"] = {}
    if "compare_ids" not in st.session_state:
        st.session_state["compare_ids"] = []
    if "journey_stops" not in st.session_state:
        st.session_state["journey_stops"] = []
    if "selected_restaurant_id" not in st.session_state:
        st.session_state["selected_restaurant_id"] = None
    if "explore_offset" not in st.session_state:
        st.session_state["explore_offset"] = 0
    if "map_focus_restaurant" not in st.session_state:
        st.session_state["map_focus_restaurant"] = None
    if "nl_last_query" not in st.session_state:
        st.session_state["nl_last_query"] = ""
    if "nl_last_response" not in st.session_state:
        st.session_state["nl_last_response"] = None


def toggle_saved_restaurant(restaurant: RestaurantItem) -> None:
    """Bookmark or unbookmark a restaurant in session state."""
    ensure_session_state()
    saved: dict[int, RestaurantItem] = st.session_state["saved_restaurants"]
    rid = restaurant["restaurant_id"]
    if rid in saved:
        del saved[rid]
        st.toast(f"Removed {restaurant['name']} from Saved.")
    else:
        saved[rid] = restaurant
        st.toast(f"Saved {restaurant['name']}.")


def add_to_compare(restaurant: RestaurantItem) -> None:
    """Add or remove a restaurant from the side-by-side comparison tray."""
    ensure_session_state()
    saved: dict[int, RestaurantItem] = st.session_state["saved_restaurants"]
    compare_ids: list[int] = st.session_state["compare_ids"]
    rid = restaurant["restaurant_id"]
    if rid in compare_ids:
        compare_ids.remove(rid)
        st.toast(f"Removed {restaurant['name']} from Compare.")
        return
    if len(compare_ids) >= MAX_COMPARE_ITEMS:
        st.toast(f"Compare tray supports up to {MAX_COMPARE_ITEMS} venues.")
        return
    compare_ids.append(rid)
    if rid not in saved:
        saved[rid] = restaurant
    st.toast(f"Added {restaurant['name']} to Compare.")


def add_to_journey(restaurant: RestaurantItem) -> None:
    """Append a restaurant to the ordered Journey Planner itinerary."""
    ensure_session_state()
    stops: list[RestaurantItem] = st.session_state["journey_stops"]
    rid = restaurant["restaurant_id"]
    if any(stop["restaurant_id"] == rid for stop in stops):
        st.toast(f"{restaurant['name']} is already in your Journey.")
        return
    if len(stops) >= MAX_JOURNEY_STOPS:
        st.toast(f"Journey Planner supports up to {MAX_JOURNEY_STOPS} stops.")
        return
    stops.append(restaurant)
    st.toast(f"Added {restaurant['name']} to Journey.")


def focus_on_map(restaurant: RestaurantItem) -> None:
    """Stage a restaurant as the active focus target for Map Explorer."""
    ensure_session_state()
    st.session_state["map_focus_restaurant"] = restaurant


@st.cache_data(ttl=settings.streamlit_cache_ttl_seconds, show_spinner=False)
def load_countries() -> CountriesResponse:
    """Load cached country metadata from the backend."""
    return get_api_client().list_countries()


@st.cache_data(ttl=settings.streamlit_cache_ttl_seconds, show_spinner=False)
def load_cities(country: str | None = None) -> CitiesResponse:
    """Load cached city metadata from the backend."""
    return get_api_client().list_cities(country=country)


@st.cache_data(ttl=settings.streamlit_cache_ttl_seconds, show_spinner=False)
def load_cuisines() -> CuisinesResponse:
    """Load cached canonical cuisine metadata from the backend."""
    return get_api_client().list_cuisines()


@st.cache_data(ttl=settings.streamlit_cache_ttl_seconds, show_spinner=False)
def load_analytics(country: str | None = None) -> AnalyticsSummary:
    """Load cached analytics summary metrics from the backend."""
    return get_api_client().get_analytics(country=country)


@st.cache_data(ttl=settings.streamlit_cache_ttl_seconds, show_spinner=False)
def load_destination_profile(country: str) -> DestinationProfile:
    """Load cached editorial destination guide for a country."""
    return get_api_client().get_destination_profile(country)


@st.cache_data(ttl=settings.streamlit_cache_ttl_seconds, show_spinner=False)
def load_pipeline_status() -> PipelineStatus:
    """Load cached pipeline run and freshness status."""
    return get_api_client().get_pipeline_status()


@st.cache_data(ttl=settings.streamlit_cache_ttl_seconds, show_spinner=False)
def load_restaurant_detail(restaurant_id: int) -> RestaurantDetailResponse:
    """Load cached restaurant detail, nearby, and similar records."""
    return get_api_client().get_restaurant(restaurant_id)
