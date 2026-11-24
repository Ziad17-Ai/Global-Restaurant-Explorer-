"""Map Explorer page with spatial radius filtering and dataframe view."""

from __future__ import annotations

import contextlib

import streamlit as st

from web.streamlit.api_client import (
    APIError,
    MapPointsResponse,
    RestaurantItem,
    get_api_client,
)
from web.streamlit.components.feedback import (
    render_api_error,
    render_empty_state,
    render_freshness_banner,
)
from web.streamlit.components.formatters import escape_markdown, is_valid_coordinate
from web.streamlit.components.maps_and_charts import render_restaurant_map
from web.streamlit.components.state import (
    ensure_session_state,
    load_cities,
    load_countries,
    load_cuisines,
    load_pipeline_status,
)
from web.streamlit.constants import (
    DEFAULT_MAP_CENTER_LAT,
    DEFAULT_MAP_CENTER_LON,
    DEFAULT_MAP_POINTS_LIMIT,
    DEFAULT_RADIUS_M,
    MAP_POINTS_MIN_LIMIT,
    MAP_POINTS_STEP,
    MAX_ABS_LATITUDE,
    MAX_ABS_LONGITUDE,
    MAX_MAP_POINTS_LIMIT,
    MAX_RADIUS_M,
    MAX_RATING,
    MIN_RADIUS_M,
    MIN_RATING,
    PRICE_RANGE_OPTIONS,
    PRICE_TIER_LABELS,
    RADIUS_STEP_M,
    RATING_STEP,
)

ensure_session_state()

st.title("Map Explorer", anchor=False)
st.caption(
    "Inspect geolocated restaurants across cities and spatial search radii. "
    "Venues missing coordinates are excluded from spatial plots."
)

with contextlib.suppress(APIError):
    render_freshness_banner(load_pipeline_status())

focus_item: RestaurantItem | None = st.session_state.get("map_focus_restaurant")
focus_point: tuple[float, float, str] | None = None
default_lat = DEFAULT_MAP_CENTER_LAT
default_lon = DEFAULT_MAP_CENTER_LON
default_use_radius = False

if focus_item is not None:
    f_lat = focus_item.get("latitude")
    f_lon = focus_item.get("longitude")
    if is_valid_coordinate(f_lat, f_lon) and f_lat is not None and f_lon is not None:
        focus_point = (float(f_lat), float(f_lon), focus_item["name"])
        default_lat = float(f_lat)
        default_lon = float(f_lon)
        default_use_radius = True
    focus_col, clear_col = st.columns([4, 1], vertical_alignment="center")
    with focus_col:
        st.info(
            f"Focused on **{escape_markdown(focus_item['name'])}** "
            f"({escape_markdown(focus_item['city_name'])}, "
            f"{escape_markdown(focus_item['country_name'])}).",
            icon=":material/my_location:",
        )
    with clear_col:
        if st.button("Clear focus", icon=":material/close:", width="stretch"):
            st.session_state["map_focus_restaurant"] = None
            st.rerun()

countries_list: list[str] = []
cities_list: list[str] = []
cuisines_list: list[str] = []
try:
    countries_list = [item["country_name"] for item in load_countries()["items"]]
    cuisines_list = sorted({item["cuisine_name"] for item in load_cuisines()["items"]})
except APIError as exc:
    render_api_error(exc)

with st.form("map_filters_form"):
    row_top = st.columns(3, wrap=True)
    with row_top[0]:
        selected_country = st.selectbox(
            "Country",
            options=["All countries", *countries_list],
        )
    country_param = None if selected_country == "All countries" else selected_country
    if countries_list:
        try:
            cities_list = [
                item["city_name"]
                for item in load_cities(country=country_param)["items"]
            ]
        except APIError:
            cities_list = []

    with row_top[1]:
        selected_city = st.selectbox("City", options=["All cities", *cities_list])
    with row_top[2]:
        selected_cuisines = st.multiselect(
            "Cuisines",
            options=cuisines_list,
            placeholder="Any cuisine",
        )

    row_mid = st.columns(3, wrap=True)
    with row_mid[0]:
        min_rating = st.slider(
            "Minimum rating (0.0 includes Unrated)",
            min_value=MIN_RATING,
            max_value=MAX_RATING,
            value=MIN_RATING,
            step=RATING_STEP,
        )
    with row_mid[1]:
        price_options = [
            "All price tiers",
            *[str(tier) for tier in PRICE_RANGE_OPTIONS],
        ]
        selected_price = st.selectbox(
            "Price tier",
            options=price_options,
            format_func=lambda val: (
                val if val == "All price tiers" else PRICE_TIER_LABELS[int(val)]
            ),
        )
    with row_mid[2]:
        point_limit = st.slider(
            "Maximum markers",
            min_value=MAP_POINTS_MIN_LIMIT,
            max_value=MAX_MAP_POINTS_LIMIT,
            value=DEFAULT_MAP_POINTS_LIMIT,
            step=MAP_POINTS_STEP,
        )

    with st.expander("Spatial radius filter", expanded=default_use_radius):
        use_radius = st.checkbox(
            "Filter within radius around coordinates",
            value=default_use_radius,
        )
        radius_cols = st.columns(3, wrap=True)
        with radius_cols[0]:
            center_lat = st.number_input(
                "Center latitude",
                min_value=-MAX_ABS_LATITUDE,
                max_value=MAX_ABS_LATITUDE,
                value=default_lat,
                format="%.6f",
            )
        with radius_cols[1]:
            center_lon = st.number_input(
                "Center longitude",
                min_value=-MAX_ABS_LONGITUDE,
                max_value=MAX_ABS_LONGITUDE,
                value=default_lon,
                format="%.6f",
            )
        with radius_cols[2]:
            radius_m = st.slider(
                "Radius (meters)",
                min_value=MIN_RADIUS_M,
                max_value=MAX_RADIUS_M,
                value=DEFAULT_RADIUS_M,
                step=RADIUS_STEP_M,
            )

    st.form_submit_button(
        "Update map",
        type="primary",
        icon=":material/map:",
        width="stretch",
    )

city_param = None if selected_city == "All cities" else selected_city
price_param = None if selected_price == "All price tiers" else int(selected_price)
min_rating_param = None if min_rating <= MIN_RATING else min_rating

map_resp: MapPointsResponse | None = None
try:
    with st.spinner("Loading spatial map points..."):
        map_resp = get_api_client().get_map_points(
            country=country_param,
            city=city_param,
            cuisine=selected_cuisines or None,
            min_rating=min_rating_param,
            price_range=price_param,
            latitude=float(center_lat) if use_radius else None,
            longitude=float(center_lon) if use_radius else None,
            radius_m=float(radius_m) if use_radius else None,
            limit=point_limit,
        )
except APIError as exc:
    render_api_error(exc)

if map_resp is not None:
    points = map_resp["items"]
    total = map_resp["total"]
    st.markdown(
        f"Loaded **{len(points):,}** geolocated markers (total matching: **{total:,}**)"
    )

    if not points:
        render_empty_state(
            "No geolocated venues found",
            "No restaurants with valid coordinates match your current map filters.",
            "Try expanding the spatial radius or clearing city/cuisine filters.",
            icon=":material/location_off:",
        )
    else:
        render_restaurant_map(
            points,
            key="map_explorer_deck",
            alt_text="Interactive map of filtered restaurants with unrated markers",
            focus_point=focus_point,
        )
