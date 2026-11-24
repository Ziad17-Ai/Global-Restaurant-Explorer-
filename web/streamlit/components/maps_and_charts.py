"""Theme-aware maps and charts paired with accessible dataframe equivalents."""

from __future__ import annotations

from collections.abc import Sequence

import altair as alt
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
    COLOR_BORDER_DARK,
    COLOR_BORDER_LIGHT,
    COLOR_DARK_FOCUS,
    COLOR_DARK_HIGH_RATING,
    COLOR_DARK_LOW_RATING,
    COLOR_DARK_MID_RATING,
    COLOR_DARK_ROUTE_PATH,
    COLOR_DARK_UNRATED,
    COLOR_FOCUS,
    COLOR_HIGH_RATING,
    COLOR_LOW_RATING,
    COLOR_MID_RATING,
    COLOR_ROUTE_PATH,
    COLOR_SURFACE_DARK,
    COLOR_SURFACE_LIGHT,
    COLOR_TEXT_DARK,
    COLOR_TEXT_LIGHT,
    COLOR_UNRATED,
    DEFAULT_MAP_CENTER_LAT,
    DEFAULT_MAP_CENTER_LON,
    DEFAULT_MAP_ZOOM,
    DETAIL_MAP_ZOOM,
    FOCUS_MARKER_SIZE_PX,
    MAP_HEIGHT_PX,
    MARKER_SIZE_PX,
    RATING_TIER_HIGH,
    RATING_TIER_MID,
    RATING_TIER_ORDER,
    UNRATED_LABEL,
)


def is_dark_theme() -> bool:
    """Return True when Streamlit reports dark mode via `st.context.theme`."""
    try:
        theme_type = getattr(st.context.theme, "type", None)
    except RuntimeError:
        theme_type = None
    return theme_type == "dark"


def get_active_basemap() -> str:
    """Return the OpenStreetMap basemap style for Plotly Scattermap."""
    return BASEMAP_DARK if is_dark_theme() else BASEMAP_LIGHT


def get_rating_color_map(*, dark_mode: bool) -> dict[str, str]:
    """Return rating-tier hex colors aligned with the active Editorial theme."""
    if dark_mode:
        return {
            "4.0+": COLOR_DARK_HIGH_RATING,
            "3.0–3.9": COLOR_DARK_MID_RATING,
            "Below 3.0": COLOR_DARK_LOW_RATING,
            UNRATED_LABEL: COLOR_DARK_UNRATED,
        }
    return {
        "4.0+": COLOR_HIGH_RATING,
        "3.0–3.9": COLOR_MID_RATING,
        "Below 3.0": COLOR_LOW_RATING,
        UNRATED_LABEL: COLOR_UNRATED,
    }


def _rating_color(rating: float | None, *, dark_mode: bool) -> str:
    color_map = get_rating_color_map(dark_mode=dark_mode)
    return color_map[_rating_tier_label(rating)]


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
    *,
    dark_mode: bool = False,
) -> pd.DataFrame:
    """Convert restaurant/map point records into a validated map DataFrame."""
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
                "marker_color": _rating_color(rating, dark_mode=dark_mode),
                "marker_size": MARKER_SIZE_PX,
            }
        )
    return pd.DataFrame(rows)


def _apply_map_chrome(
    fig: go.Figure,
    *,
    center_lat: float,
    center_lon: float,
    zoom: int,
    height: int,
    dark_mode: bool,
) -> None:
    """Apply OpenStreetMap layout and Paper & Ink / Warm Ink chrome to a figure."""
    surface = COLOR_SURFACE_DARK if dark_mode else COLOR_SURFACE_LIGHT
    text_color = COLOR_TEXT_DARK if dark_mode else COLOR_TEXT_LIGHT
    border_color = COLOR_BORDER_DARK if dark_mode else COLOR_BORDER_LIGHT
    fig.update_layout(
        map={
            "style": get_active_basemap(),
            "center": {"lat": center_lat, "lon": center_lon},
            "zoom": zoom,
        },
        height=height,
        margin={"l": 0, "r": 0, "t": 8, "b": 0},
        paper_bgcolor=surface,
        font={"color": text_color},
        legend={
            "title": {"text": "Rating tier"},
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "left",
            "x": 0.0,
            "bgcolor": surface,
            "bordercolor": border_color,
            "borderwidth": 1,
        },
        hoverlabel={
            "bgcolor": surface,
            "bordercolor": border_color,
            "font": {"color": text_color},
        },
    )


def render_restaurant_map(
    items: Sequence[RestaurantItem | MapPointItem],
    *,
    key: str,
    alt_text: str,
    height: int = MAP_HEIGHT_PX,
    focus_point: tuple[float, float, str] | None = None,
) -> None:
    """Render an OpenStreetMap restaurant map paired with a dataframe equivalent."""
    dark_mode = is_dark_theme()
    focus_color = COLOR_DARK_FOCUS if dark_mode else COLOR_FOCUS
    points_df = build_map_points_df(items, dark_mode=dark_mode)
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

        fig = px.scatter_map(
            points_df,
            lat="latitude",
            lon="longitude",
            color="rating_tier",
            color_discrete_map=get_rating_color_map(dark_mode=dark_mode),
            category_orders={"rating_tier": list(RATING_TIER_ORDER)},
            hover_name="name",
            hover_data={
                "city_name": True,
                "country_name": True,
                "rating_display": True,
                "cost_display": True,
                "attribution": True,
                "latitude": False,
                "longitude": False,
                "rating_tier": False,
            },
            labels={
                "city_name": "City",
                "country_name": "Country",
                "rating_display": "Rating",
                "cost_display": "Cost",
                "attribution": "Source",
            },
            zoom=zoom,
            center={"lat": center_lat, "lon": center_lon},
            map_style=get_active_basemap(),
            height=height,
        )
        fig.update_traces(marker={"size": MARKER_SIZE_PX, "opacity": 0.92})

        if focus_point is not None:
            fig.add_trace(
                go.Scattermap(
                    lat=[center_lat],
                    lon=[center_lon],
                    mode="markers",
                    name="Focused venue",
                    text=[focus_name],
                    hoverinfo="text",
                    marker={"size": FOCUS_MARKER_SIZE_PX, "color": focus_color},
                )
            )

        _apply_map_chrome(
            fig,
            center_lat=center_lat,
            center_lon=center_lon,
            zoom=zoom,
            height=height,
            dark_mode=dark_mode,
        )
        st.plotly_chart(
            fig,
            width="stretch",
            theme="streamlit",
            key=key,
            config={"scrollZoom": True, "displayModeBar": True},
            alt=alt_text,
        )
        st.caption(
            "Basemap: OpenStreetMap contributors · Click a rating tier in the legend "
            "above to toggle markers."
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
    """Render an ordered OpenStreetMap itinerary map with connecting segments."""
    dark_mode = is_dark_theme()
    route_color = COLOR_DARK_ROUTE_PATH if dark_mode else COLOR_ROUTE_PATH
    points_df = build_map_points_df(stops, dark_mode=dark_mode)
    if points_df.empty:
        st.info(
            "Selected itinerary stops do not include valid map coordinates.",
            title="Route map unavailable",
            icon=":material/location_off:",
        )
        return

    map_tab, table_tab = st.tabs(["Route map", "Leg breakdown table"])

    with map_tab:
        fig = go.Figure()
        min_route_points = 2
        if len(points_df) >= min_route_points:
            fig.add_trace(
                go.Scattermap(
                    lat=points_df["latitude"].tolist(),
                    lon=points_df["longitude"].tolist(),
                    mode="lines",
                    name="Planned route",
                    line={"width": 3, "color": route_color},
                    hoverinfo="skip",
                )
            )

        stop_labels = [
            f"{idx}. {row['name']} ({row['rating_display']} · {row['cost_display']})"
            for idx, (_, row) in enumerate(points_df.iterrows(), start=1)
        ]
        fig.add_trace(
            go.Scattermap(
                lat=points_df["latitude"].tolist(),
                lon=points_df["longitude"].tolist(),
                mode="markers+text",
                name="Itinerary stops",
                text=[str(idx) for idx in range(1, len(points_df) + 1)],
                textposition="top right",
                hovertext=stop_labels,
                hoverinfo="text",
                marker={
                    "size": FOCUS_MARKER_SIZE_PX,
                    "color": points_df["marker_color"].tolist(),
                    "opacity": 0.95,
                },
            )
        )

        _apply_map_chrome(
            fig,
            center_lat=float(points_df["latitude"].mean()),
            center_lon=float(points_df["longitude"].mean()),
            zoom=CITY_MAP_ZOOM,
            height=MAP_HEIGHT_PX,
            dark_mode=dark_mode,
        )
        st.plotly_chart(
            fig,
            width="stretch",
            theme="streamlit",
            key=key,
            config={"scrollZoom": True, "displayModeBar": True},
            alt="Planned restaurant journey route map",
        )
        st.caption("Basemap: OpenStreetMap contributors · Straight-line route preview.")

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
