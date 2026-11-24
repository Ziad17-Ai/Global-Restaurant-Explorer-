"""Theme-aware maps and charts paired with accessible dataframe equivalents."""

from __future__ import annotations

from collections.abc import Sequence

import altair as alt
import pandas as pd
import pydeck as pdk
import streamlit as st

from web.streamlit.api_client import MapPointItem, RestaurantItem
from web.streamlit.components.formatters import (
    format_cost,
    format_rating,
    format_source_attribution,
    is_valid_coordinate,
)
from web.streamlit.constants import (
    BASEMAP_DARK,
    BASEMAP_LIGHT,
    CHART_HEIGHT_PX,
    CITY_MAP_ZOOM,
    COLOR_FOCUS,
    COLOR_HIGH_RATING,
    COLOR_LOW_RATING,
    COLOR_MID_RATING,
    COLOR_ROUTE_PATH,
    COLOR_UNRATED,
    DEFAULT_MAP_CENTER_LAT,
    DEFAULT_MAP_CENTER_LON,
    DEFAULT_MAP_ZOOM,
    DETAIL_MAP_ZOOM,
    FOCUS_MARKER_RADIUS_PX,
    MAP_HEIGHT_PX,
    MARKER_RADIUS_PX,
    RATING_TIER_HIGH,
    RATING_TIER_MID,
    UNRATED_LABEL,
)


def get_active_basemap() -> str:
    """Return a light or dark neutral CARTO basemap matching `st.context.theme`."""
    try:
        theme_type = getattr(st.context.theme, "type", None)
    except RuntimeError:
        theme_type = None
    if theme_type == "dark":
        return BASEMAP_DARK
    return BASEMAP_LIGHT


def _rating_color(rating: float | None) -> list[int]:
    if rating is None:
        return COLOR_UNRATED
    if rating >= RATING_TIER_HIGH:
        return COLOR_HIGH_RATING
    if rating >= RATING_TIER_MID:
        return COLOR_MID_RATING
    return COLOR_LOW_RATING


def _rating_tier_label(rating: float | None) -> str:
    if rating is None:
        return UNRATED_LABEL
    if rating >= RATING_TIER_HIGH:
        return "4.0+"
    if rating >= RATING_TIER_MID:
        return "3.0–3.9"
    return "Below 3.0"


def build_map_points_df(
    items: Sequence[RestaurantItem | MapPointItem],
) -> pd.DataFrame:
    """Convert restaurant/map point records into a validated PyDeck DataFrame."""
    rows: list[dict[str, object]] = []
    for item in items:
        lat = item.get("latitude")
        lon = item.get("longitude")
        if not is_valid_coordinate(lat, lon) or lat is None or lon is None:
            continue
        rating = item.get("rating")
        rating_text = item.get("rating_text")
        cuisines = item.get("cuisines") or []
        rows.append(
            {
                "restaurant_id": item["restaurant_id"],
                "name": item["name"],
                "country_name": item["country_name"],
                "city_name": item["city_name"],
                "locality": item.get("locality") or "",
                "latitude": float(lat),
                "longitude": float(lon),
                "rating": float(rating) if rating is not None else None,
                "rating_display": format_rating(rating, rating_text),
                "rating_tier": _rating_tier_label(rating),
                "cost_display": format_cost(
                    item.get("avg_cost_for_two"),
                    item.get("currency_code"),
                    item.get("avg_cost_for_two_usd"),
                ),
                "cuisines_text": ", ".join(cuisines) if cuisines else "Unlisted",
                "attribution": format_source_attribution(
                    item.get("source_name"),
                    item.get("source_license"),
                ),
                "marker_color": _rating_color(rating),
                "marker_radius": MARKER_RADIUS_PX,
            }
        )
    return pd.DataFrame(rows)


def render_restaurant_map(
    items: Sequence[RestaurantItem | MapPointItem],
    *,
    key: str,
    alt_text: str,
    height: int = MAP_HEIGHT_PX,
    focus_point: tuple[float, float, str] | None = None,
) -> None:
    """Render a theme-aware restaurant map paired with a dataframe equivalent."""
    points_df = build_map_points_df(items)
    if points_df.empty:
        st.info(
            "No restaurants with valid coordinates match the current view.",
            title="Map view unavailable",
            icon=":material/location_off:",
        )
        return

    map_tab, table_tab = st.tabs(["Map view", "Data table"])

    with map_tab:
        if focus_point is not None:
            center_lat, center_lon, focus_name = focus_point
            zoom = DETAIL_MAP_ZOOM
        else:
            center_lat = float(points_df["latitude"].mean())
            center_lon = float(points_df["longitude"].mean())
            zoom = (
                CITY_MAP_ZOOM
                if len(set(points_df["city_name"])) == 1
                else DEFAULT_MAP_ZOOM
            )
            if points_df.empty:
                center_lat = DEFAULT_MAP_CENTER_LAT
                center_lon = DEFAULT_MAP_CENTER_LON
                zoom = DEFAULT_MAP_ZOOM
            focus_name = ""

        layers: list[pdk.Layer] = [
            pdk.Layer(
                "ScatterplotLayer",
                data=points_df,
                id=f"{key}_points",
                get_position=["longitude", "latitude"],
                get_fill_color="marker_color",
                get_radius="marker_radius",
                radius_units="pixels",
                radius_min_pixels=5,
                radius_max_pixels=14,
                pickable=True,
            )
        ]

        if focus_point is not None:
            focus_df = pd.DataFrame(
                [
                    {
                        "name": focus_name,
                        "latitude": center_lat,
                        "longitude": center_lon,
                        "rating_display": "Focused venue",
                        "city_name": "",
                        "country_name": "",
                        "cost_display": "",
                        "attribution": "",
                    }
                ]
            )
            layers.append(
                pdk.Layer(
                    "ScatterplotLayer",
                    data=focus_df,
                    id=f"{key}_focus",
                    get_position=["longitude", "latitude"],
                    get_fill_color=COLOR_FOCUS,
                    get_radius=FOCUS_MARKER_RADIUS_PX,
                    radius_units="pixels",
                    stroked=True,
                    get_line_color=[255, 255, 255, 230],
                    line_width_min_pixels=2,
                    pickable=True,
                )
            )

        deck = pdk.Deck(
            layers=layers,
            initial_view_state=pdk.ViewState(
                latitude=center_lat,
                longitude=center_lon,
                zoom=zoom,
                pitch=0,
            ),
            map_style=get_active_basemap(),
            tooltip={
                "text": (
                    "{name}\n"
                    "{city_name}, {country_name}\n"
                    "Rating: {rating_display}\n"
                    "{cost_display}\n"
                    "Source: {attribution}"
                )
            },
        )
        st.pydeck_chart(
            deck,
            width="stretch",
            height=height,
            key=key,
            alt=alt_text,
        )
        st.caption(
            "Marker legend: Forest Green = 4.0+, Terracotta = 3.0–3.9, "
            "Amber = Below 3.0, Slate Gray = Unrated (no rating in source)."
        )

    with table_tab:
        display_columns = [
            "name",
            "city_name",
            "country_name",
            "locality",
            "cuisines_text",
            "rating_display",
            "rating_tier",
            "cost_display",
            "latitude",
            "longitude",
            "attribution",
        ]
        table_df = points_df[display_columns].rename(
            columns={
                "name": "Restaurant",
                "city_name": "City",
                "country_name": "Country",
                "locality": "Locality",
                "cuisines_text": "Cuisines",
                "rating_display": "Rating",
                "rating_tier": "Tier",
                "cost_display": "Cost for two",
                "latitude": "Latitude",
                "longitude": "Longitude",
                "attribution": "Source & License",
            }
        )
        st.dataframe(
            table_df,
            width="stretch",
            hide_index=True,
            alt=f"Tabular equivalent for: {alt_text}",
        )


def render_journey_route_map(
    stops: Sequence[RestaurantItem],
    legs_df: pd.DataFrame,
    *,
    key: str,
) -> None:
    """Render an ordered itinerary map with connecting segments and a leg table."""
    points_df = build_map_points_df(stops)
    if points_df.empty:
        st.info(
            "Selected itinerary stops do not include valid map coordinates.",
            title="Route map unavailable",
            icon=":material/location_off:",
        )
        return

    map_tab, table_tab = st.tabs(["Route map", "Leg breakdown table"])

    with map_tab:
        path_coords = [
            [float(row["longitude"]), float(row["latitude"])]
            for _, row in points_df.iterrows()
        ]
        layers: list[pdk.Layer] = [
            pdk.Layer(
                "ScatterplotLayer",
                data=points_df,
                id=f"{key}_stops",
                get_position=["longitude", "latitude"],
                get_fill_color="marker_color",
                get_radius=FOCUS_MARKER_RADIUS_PX,
                radius_units="pixels",
                pickable=True,
            )
        ]
        min_route_points = 2
        if len(path_coords) >= min_route_points:
            path_df = pd.DataFrame([{"name": "Planned route", "path": path_coords}])
            layers.insert(
                0,
                pdk.Layer(
                    "PathLayer",
                    data=path_df,
                    id=f"{key}_path",
                    get_path="path",
                    get_color=COLOR_ROUTE_PATH,
                    width_scale=1,
                    width_min_pixels=3,
                    pickable=False,
                ),
            )

        deck = pdk.Deck(
            layers=layers,
            initial_view_state=pdk.ViewState(
                latitude=float(points_df["latitude"].mean()),
                longitude=float(points_df["longitude"].mean()),
                zoom=CITY_MAP_ZOOM,
                pitch=0,
            ),
            map_style=get_active_basemap(),
            tooltip={"text": "{name}\nRating: {rating_display}\n{cost_display}"},
        )
        st.pydeck_chart(
            deck,
            width="stretch",
            height=MAP_HEIGHT_PX,
            key=key,
            alt="Planned restaurant journey route map",
        )

    with table_tab:
        st.dataframe(
            legs_df,
            width="stretch",
            hide_index=True,
            alt="Straight-line Haversine leg distances and travel estimates",
        )


def render_bar_chart_with_table(
    chart_df: pd.DataFrame,
    *,
    category_col: str,
    value_col: str,
    category_label: str,
    value_label: str,
    title: str,
    alt_text: str,
    key: str,
    horizontal: bool = True,
    sort_descending: bool = True,
) -> None:
    """Render a theme-inherited Altair bar chart paired with a dataframe tab."""
    if chart_df.empty:
        st.caption(f"No data available for {title}.")
        return

    st.subheader(title)
    chart_tab, table_tab = st.tabs(["Chart", "Table"])

    with chart_tab:
        sort_order = "-x" if (horizontal and sort_descending) else "-y"
        if not sort_descending:
            sort_order = "x" if horizontal else "y"

        if horizontal:
            x_enc = alt.X(f"{value_col}:Q", title=value_label)
            y_enc = alt.Y(
                f"{category_col}:N",
                title=category_label,
                sort=sort_order,
            )
        else:
            x_enc = alt.X(
                f"{category_col}:N",
                title=category_label,
                sort=sort_order,
            )
            y_enc = alt.Y(f"{value_col}:Q", title=value_label)

        chart = (
            alt.Chart(chart_df)
            .mark_bar()
            .encode(
                x=x_enc,
                y=y_enc,
                tooltip=[
                    alt.Tooltip(f"{category_col}:N", title=category_label),
                    alt.Tooltip(f"{value_col}:Q", title=value_label, format=","),
                ],
            )
            .properties(height=CHART_HEIGHT_PX)
        )
        st.altair_chart(
            chart,
            width="stretch",
            theme="streamlit",
            key=key,
            alt=alt_text,
        )

    with table_tab:
        st.dataframe(
            chart_df,
            width="stretch",
            hide_index=True,
            alt=f"Table view for {title}",
        )
