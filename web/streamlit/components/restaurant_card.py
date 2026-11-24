"""Editorial restaurant card component with safe text rendering and actions."""

from __future__ import annotations

import streamlit as st

from web.streamlit.api_client import RestaurantItem
from web.streamlit.components.formatters import (
    build_directions_url,
    escape_markdown,
    format_cost,
    format_distance_m,
    format_price_tier,
    format_rating,
    format_source_attribution,
)
from web.streamlit.components.state import (
    add_to_compare,
    add_to_journey,
    ensure_session_state,
    focus_on_map,
    toggle_saved_restaurant,
)


def _format_location_line(restaurant: RestaurantItem) -> str:
    parts = [
        restaurant.get("locality") or "",
        restaurant.get("city_name") or "",
        restaurant.get("country_name") or "",
    ]
    return ", ".join(part for part in parts if part.strip())


def render_restaurant_card(
    restaurant: RestaurantItem,
    *,
    key_prefix: str,
    show_details_button: bool = False,
) -> bool:
    """Render a single restaurant card inside a bordered container.

    Args:
        restaurant: Restaurant payload returned by the FastAPI backend.
        key_prefix: Unique prefix to avoid duplicate widget keys across lists.
        show_details_button: Whether to include a Details button returning True.

    Returns:
        True if the user clicked the Details button on this run, else False.
    """
    ensure_session_state()
    rid = restaurant["restaurant_id"]
    saved_map: dict[int, RestaurantItem] = st.session_state["saved_restaurants"]
    compare_ids: list[int] = st.session_state["compare_ids"]
    journey_stops: list[RestaurantItem] = st.session_state["journey_stops"]

    is_saved = rid in saved_map
    is_comparing = rid in compare_ids
    in_journey = any(stop["restaurant_id"] == rid for stop in journey_stops)

    details_clicked = False
    with st.container(border=True):
        st.markdown(f"**{escape_markdown(restaurant['name'])}**")
        location_line = _format_location_line(restaurant)
        if location_line:
            st.text(location_line)

        cuisines = restaurant.get("cuisines") or []
        cuisines_text = (
            escape_markdown(", ".join(cuisines)) if cuisines else "Cuisine unlisted"
        )
        st.caption(cuisines_text)

        rating_str = format_rating(
            restaurant.get("rating"),
            restaurant.get("rating_text"),
        )
        votes = restaurant.get("votes")
        votes_str = f" · {votes:,} votes" if votes is not None else ""
        cost_str = format_cost(
            restaurant.get("avg_cost_for_two"),
            restaurant.get("currency_code"),
            restaurant.get("avg_cost_for_two_usd"),
        )
        tier_str = format_price_tier(restaurant.get("price_range"))

        st.markdown(
            f"**Rating:** {escape_markdown(rating_str)}{votes_str}  \n"
            f"**Cost:** {escape_markdown(cost_str)} · {escape_markdown(tier_str)}"
        )

        service_flags: list[str] = []
        if restaurant.get("has_table_booking"):
            service_flags.append("Table booking")
        if restaurant.get("has_online_delivery"):
            service_flags.append("Online delivery")
        distance_label = format_distance_m(restaurant.get("distance_m"))
        if distance_label:
            service_flags.append(f"{distance_label} away")
        if service_flags:
            st.caption(" · ".join(service_flags))

        if restaurant.get("address"):
            st.text(restaurant["address"])

        attribution = format_source_attribution(
            restaurant.get("source_name"),
            restaurant.get("source_license"),
        )
        st.caption(f"Source: {escape_markdown(attribution)}")

        with st.container(horizontal=True):
            if st.button(
                "Map",
                key=f"{key_prefix}_map_{rid}",
                icon=":material/map:",
                help="Focus this restaurant on Map Explorer",
            ):
                focus_on_map(restaurant)
                st.switch_page("pages/map_explorer.py")

            save_label = "Saved" if is_saved else "Save"
            save_icon = (
                ":material/bookmark_added:" if is_saved else ":material/bookmark:"
            )
            if st.button(
                save_label,
                key=f"{key_prefix}_save_{rid}",
                icon=save_icon,
            ):
                toggle_saved_restaurant(restaurant)

            compare_label = "Comparing" if is_comparing else "Compare"
            if st.button(
                compare_label,
                key=f"{key_prefix}_cmp_{rid}",
                icon=":material/compare_arrows:",
            ):
                add_to_compare(restaurant)

            journey_label = "In Journey" if in_journey else "+Journey"
            if st.button(
                journey_label,
                key=f"{key_prefix}_jrn_{rid}",
                icon=":material/route:",
            ):
                add_to_journey(restaurant)

            if show_details_button and st.button(
                "Details",
                key=f"{key_prefix}_det_{rid}",
                icon=":material/info:",
            ):
                details_clicked = True

            directions_url = build_directions_url(restaurant)
            if directions_url:
                st.link_button(
                    "Directions",
                    url=directions_url,
                    icon=":material/directions:",
                )

    return details_clicked
