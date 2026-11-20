import html
import math
from typing import Any, Dict, List, Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from backend import (
    DESTINATION_CULTURE,
    NLPService,
    RestaurantService,
    SearchParams,
    build_directions_url,
    haversine_km,
    is_valid_coord,
)

APP_NAME = "EatoSphere"
APP_VERSION = "v3.0"

# ---------------------------------------------------------
# 1. Page Config & EatoSphere Culinary-Tech Design System
# ---------------------------------------------------------
st.set_page_config(
    page_title="EatoSphere — Global Culinary Intelligence",
    page_icon="🌐",
    layout="wide",
    initial_sidebar_state="expanded",
)


def inject_design_system() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        :root {
            --bg-base: #080B14;
            --surface: rgba(17, 23, 38, 0.82);
            --surface-alt: rgba(24, 32, 52, 0.90);
            --border: rgba(148, 163, 184, 0.16);
            --cream: #FFF8EB;
            --coral: #F97316;
            --gold: #EAB308;
            --cyan: #22D3EE;
            --emerald: #10B981;
            --muted: #94A3B8;
        }

        html, body, [class*="css"] {
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
            color: #F8FAFC;
        }

        .stApp {
            background:
                radial-gradient(circle at 86% 6%, rgba(249, 115, 22, 0.13) 0%, transparent 36%),
                radial-gradient(circle at 10% 15%, rgba(34, 211, 238, 0.08) 0%, transparent 40%),
                linear-gradient(180deg, #0A0E1A 0%, #060911 100%);
        }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0B1020 0%, #070A13 100%);
            border-right: 1px solid var(--border);
        }

        .es-header {
            background: linear-gradient(125deg, rgba(249,115,22,0.16) 0%, rgba(234,179,8,0.08) 45%, rgba(15,23,42,0.92) 100%);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 22px 28px;
            margin-bottom: 18px;
            box-shadow: 0 14px 32px rgba(0,0,0,0.28);
        }
        .es-kicker {
            font-size: 0.72rem;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            color: var(--gold);
            margin-bottom: 5px;
        }
        .es-title {
            font-size: 1.9rem;
            font-weight: 800;
            letter-spacing: -0.025em;
            color: var(--cream);
            margin: 0 0 6px 0;
        }
        .es-sub {
            color: var(--muted);
            font-size: 0.94rem;
            margin: 0;
        }

        .kpi-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px 18px;
            height: 100%;
            transition: transform 0.2s ease, border-color 0.2s ease;
        }
        .kpi-card:hover {
            transform: translateY(-2px);
            border-color: rgba(249,115,22,0.5);
        }
        .kpi-label {
            font-size: 0.72rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            color: var(--muted);
        }
        .kpi-val {
            font-size: 1.65rem;
            font-weight: 800;
            color: var(--cream);
            margin-top: 4px;
        }
        .kpi-meta {
            font-size: 0.78rem;
            color: var(--cyan);
            margin-top: 4px;
        }

        .rest-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 16px 18px;
            margin-bottom: 10px;
            transition: transform 0.18s ease, border-color 0.18s ease;
        }
        .rest-card:hover {
            transform: translateY(-2px);
            border-color: rgba(249,115,22,0.55);
        }
        .rest-head {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 10px;
            margin-bottom: 8px;
        }
        .rest-name {
            font-size: 1.08rem;
            font-weight: 700;
            color: var(--cream);
            margin: 0;
        }
        .pill {
            display: inline-block;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 0.74rem;
            font-weight: 600;
            margin-right: 6px;
            margin-bottom: 5px;
        }
        .pill-rating { background: rgba(16,185,129,0.16); color: #34D399; border: 1px solid rgba(16,185,129,0.32); }
        .pill-cost { background: rgba(234,179,8,0.14); color: #FACC15; border: 1px solid rgba(234,179,8,0.30); }
        .pill-loc { background: rgba(34,211,238,0.12); color: #22D3EE; border: 1px solid rgba(34,211,238,0.28); }
        .pill-src { background: rgba(148,163,184,0.12); color: #CBD5E1; border: 1px solid rgba(148,163,184,0.22); }

        .nav-group {
            font-size: 0.68rem;
            font-weight: 800;
            letter-spacing: 0.12em;
            color: #64748B;
            text-transform: uppercase;
            margin: 12px 0 5px 2px;
        }
        .status-chip {
            padding: 7px 11px;
            border-radius: 10px;
            font-size: 0.79rem;
            font-weight: 600;
            margin-bottom: 7px;
            border: 1px solid var(--border);
        }
        .st-ok { color: #34D399; background: rgba(16,185,129,0.09); border-color: rgba(16,185,129,0.30); }
        .st-warn { color: #FBBF24; background: rgba(245,158,11,0.09); border-color: rgba(245,158,11,0.30); }
        .st-info { color: #22D3EE; background: rgba(34,211,238,0.09); border-color: rgba(34,211,238,0.30); }

        .dest-hero {
            border-radius: 18px;
            padding: 24px 28px;
            border: 1px solid var(--border);
            margin-bottom: 18px;
        }
        .medallion-stage {
            background: var(--surface);
            border: 1px solid var(--border);
            border-top-width: 4px;
            border-radius: 14px;
            padding: 16px 18px;
            height: 100%;
        }
        .empty-box {
            background: rgba(15,23,42,0.58);
            border: 1px dashed rgba(148,163,184,0.28);
            border-radius: 14px;
            padding: 24px;
            text-align: center;
        }
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #F97316 0%, #EA580C 100%);
            border: none;
            color: #FFFFFF;
            font-weight: 600;
            border-radius: 10px;
        }
        .stButton > button {
            border-radius: 10px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


inject_design_system()


# ---------------------------------------------------------
# 2. Cached Services & Shared Session State
# ---------------------------------------------------------
@st.cache_resource
def load_services():
    svc = RestaurantService()
    nlp = NLPService(svc)
    return svc, nlp


service, nlp_service = load_services()


@st.cache_data(ttl=120, show_spinner=False)
def cached_analytics(_svc: RestaurantService, _bust: int) -> Dict[str, Any]:
    return _svc.get_analytics()


@st.cache_data(ttl=120, show_spinner=False)
def cached_filter_options(_svc: RestaurantService, _bust: int) -> Dict[str, List[str]]:
    return _svc.get_filter_options()


@st.cache_data(ttl=120, show_spinner=False)
def cached_cities(_svc: RestaurantService, country: Optional[str], _bust: int) -> List[str]:
    return _svc.get_cities(country)


@st.cache_data(ttl=120, show_spinner=False)
def cached_telemetry(_svc: RestaurantService, _bust: int):
    return _svc.get_pipeline_telemetry()


def init_state() -> None:
    defaults = {
        "page": "Global Map Hub",
        "cache_bust": 0,
        "selected_restaurant": None,
        "favorites": [],
        "compare_list": [],
        "journey_stops": [],
        "selected_destination": "Egypt",
        "map_override_df": None,
        "map_override_label": None,
        "exp_country": "All",
        "exp_city": "All",
        "exp_cuisines": [],
        "exp_rating": 0.0,
        "exp_name": "",
        "exp_locality": "",
        "exp_max_cost": 0,
        "exp_sort": "rating",
        "exp_page": 1,
        "ai_messages": [],
        "ai_last_df": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return row.to_dict() if hasattr(row, "to_dict") else dict(row)


def _add_unique(state_key: str, item: Dict[str, Any], max_items: int = 20) -> bool:
    existing = st.session_state[state_key]
    key_name = f"{item.get('name')}|{item.get('city')}"
    if any(f"{x.get('name')}|{x.get('city')}" == key_name for x in existing):
        return False
    if len(existing) >= max_items:
        return False
    existing.append(item)
    return True


def _fmt_cost(row: Dict[str, Any]) -> str:
    c = row.get("avg_cost_for_two")
    cur = str(row.get("currency") or "")
    if pd.notna(c):
        v = float(c)
        return f"{int(v):,} {cur} / 2" if v.is_integer() else f"{v:,.2f} {cur} / 2"
    return f"N/A {cur}".strip()


# ---------------------------------------------------------
# 3. Shared UI Components
# ---------------------------------------------------------
def render_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        f"""
        <div class="es-header">
            <div class="es-kicker">{html.escape(kicker)}</div>
            <h1 class="es-title">{html.escape(title)}</h1>
            <p class="es-sub">{html.escape(subtitle)}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_kpi(col, label: str, val: str, meta: str) -> None:
    col.markdown(
        f"""
        <div class="kpi-card">
            <div class="kpi-label">{html.escape(label)}</div>
            <div class="kpi-val">{html.escape(val)}</div>
            <div class="kpi-meta">{html.escape(meta)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_empty(title: str, desc: str) -> None:
    st.markdown(
        f'<div class="empty-box"><div style="font-weight:700;margin-bottom:4px;">{html.escape(title)}</div>'
        f'<div style="color:#94A3B8;font-size:0.88rem;">{html.escape(desc)}</div></div>',
        unsafe_allow_html=True,
    )


def render_restaurant_card(row: Any, key_prefix: str, show_actions: bool = True) -> None:
    r = _row_to_dict(row)
    name = html.escape(str(r.get("name") or "Unnamed"))
    rating = f"★ {float(r['rating']):.1f}" if pd.notna(r.get("rating")) else "★ N/A"
    votes = f" ({int(r['votes']):,} votes)" if pd.notna(r.get("votes")) and int(r["votes"]) > 0 else ""
    loc = html.escape(f"{r.get('locality', 'N/A')}, {r.get('city', 'N/A')} · {r.get('country', 'N/A')}")
    cuis = html.escape(str(r.get("cuisines") or "Various"))
    addr = html.escape(str(r.get("address") or "Address unavailable"))
    src = html.escape(str(r.get("source") or "dataset"))
    dist_badge = f'<span class="pill pill-loc">{r["straight_line_km"]} km straight-line</span>' if "straight_line_km" in r and pd.notna(r["straight_line_km"]) else ""

    st.markdown(
        f"""
        <div class="rest-card">
            <div class="rest-head">
                <h4 class="rest-name">{name}</h4>
                <span class="pill pill-rating">{rating}{html.escape(votes)}</span>
            </div>
            <div style="margin-bottom:8px;">
                <span class="pill pill-cost">{html.escape(_fmt_cost(r))}</span>
                <span class="pill pill-loc">📍 {loc}</span>
                {dist_badge}
                <span class="pill pill-src">{src}</span>
            </div>
            <div style="color:#E2E8F0;font-size:0.86rem;margin-bottom:3px;"><b>Cuisines:</b> {cuis}</div>
            <div style="color:#94A3B8;font-size:0.8rem;">{addr}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if show_actions:
        a1, a2, a3, a4 = st.columns(4)
        if a1.button("🗺️ Map", key=f"{key_prefix}_map", use_container_width=True):
            st.session_state["selected_restaurant"] = r
            st.session_state["page"] = "Global Map Hub"
            st.rerun()
        if a2.button("♥ Save", key=f"{key_prefix}_fav", use_container_width=True):
            added = _add_unique("favorites", r, max_items=30)
            st.toast("Saved to My Saved Places" if added else "Already in Saved Places")
        if a3.button("⚖ Compare", key=f"{key_prefix}_cmp", use_container_width=True):
            added = _add_unique("compare_list", r, max_items=4)
            st.toast("Added to Compare (max 4)" if added else "Already in Compare or limit reached")
        if a4.button("🧭 +Journey", key=f"{key_prefix}_jrn", use_container_width=True):
            added = _add_unique("journey_stops", r, max_items=8)
            st.toast("Added to Food Journey" if added else "Already in Journey or limit reached")


def build_plotly_map(
    df: pd.DataFrame,
    tile_style: str = "CartoDB dark_matter",
    selected: Optional[Dict[str, Any]] = None,
    route_stops: Optional[List[Dict[str, Any]]] = None,
    height: int = 560,
) -> Optional[go.Figure]:
    if df is None or df.empty or not {"latitude", "longitude"}.issubset(df.columns):
        return None
    vdf = df.copy()
    vdf["latitude"] = pd.to_numeric(vdf["latitude"], errors="coerce")
    vdf["longitude"] = pd.to_numeric(vdf["longitude"], errors="coerce")
    vdf = vdf.dropna(subset=["latitude", "longitude"])
    vdf = vdf[~((vdf["latitude"] == 0.0) & (vdf["longitude"] == 0.0))]
    vdf = vdf[vdf["latitude"].between(-90, 90) & vdf["longitude"].between(-180, 180)]
    if vdf.empty:
        return None

    style_map = {
        "CartoDB dark_matter": "carto-darkmatter",
        "CartoDB positron": "carto-positron",
        "OpenStreetMap": "open-street-map",
    }
    map_style = style_map.get(tile_style, "carto-darkmatter")

    center = None
    zoom = 3 if len(vdf) > 200 else 5
    if selected and is_valid_coord(selected.get("latitude"), selected.get("longitude")):
        center = {"lat": float(selected["latitude"]), "lon": float(selected["longitude"])}
        zoom = 12

    fig = px.scatter_map(
        vdf,
        lat="latitude",
        lon="longitude",
        hover_name="name",
        hover_data={
            "city": True,
            "locality": True,
            "cuisines": True,
            "rating": True,
            "avg_cost_for_two": True,
            "currency": True,
            "latitude": False,
            "longitude": False,
        },
        color="rating",
        color_continuous_scale="Turbo",
        center=center,
        zoom=zoom,
        height=height,
    )
    fig.update_traces(marker=dict(size=9, opacity=0.88))

    # Highlight selected restaurant marker
    if selected and is_valid_coord(selected.get("latitude"), selected.get("longitude")):
        fig.add_trace(
            go.Scattermap(
                lat=[float(selected["latitude"])],
                lon=[float(selected["longitude"])],
                mode="markers+text",
                marker=dict(size=18, color="#F97316"),
                text=[str(selected.get("name", "Selected"))],
                textposition="top center",
                name="Selected Restaurant",
            )
        )

    # Overlay itinerary stop sequence (clearly labeled as straight-line stop order)
    if route_stops:
        valid_stops = [s for s in route_stops if is_valid_coord(s.get("latitude"), s.get("longitude"))]
        if len(valid_stops) >= 2:
            fig.add_trace(
                go.Scattermap(
                    lat=[float(s["latitude"]) for s in valid_stops],
                    lon=[float(s["longitude"]) for s in valid_stops],
                    mode="lines+markers",
                    line=dict(width=3, color="#22D3EE"),
                    marker=dict(size=13, color="#22D3EE"),
                    text=[f"Stop {i+1}: {s.get('name')}" for i, s in enumerate(valid_stops)],
                    name="Journey Sequence (Straight-Line)",
                )
            )

    fig.update_layout(
        map_style=map_style,
        margin=dict(l=0, r=0, t=0, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, sans-serif", color="#E2E8F0"),
        legend=dict(bgcolor="rgba(15,23,42,0.78)"),
    )
    return fig


# ---------------------------------------------------------
# 4. Sidebar Navigation & Live System Telemetry
# ---------------------------------------------------------
NAV_ITEMS = [
    ("DISCOVER", "Global Map Hub", "🌐"),
    ("DISCOVER", "Restaurant Explorer", "🧭"),
    ("DISCOVER", "Explore Destinations", "🏛️"),
    ("PLAN", "Food Journey Planner", "🗺️"),
    ("PLAN", "Saved & Compare", "⚖️"),
    ("INTELLIGENCE", "AI Culinary Concierge", "✨"),
    ("INTELLIGENCE", "Global Culinary Dashboard", "📊"),
    ("PLATFORM", "Data Engineering Monitor", "🛠️"),
]

with st.sidebar:
    st.markdown(
        f"""
        <div style="padding: 4px 2px 10px 2px;">
            <div style="font-size:1.35rem; font-weight:800; color:#FFF8EB; letter-spacing:-0.02em;">🌐 {APP_NAME}</div>
            <div style="font-size:0.78rem; color:#94A3B8;">Global Culinary Intelligence · {APP_VERSION}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    last_group = None
    for grp, lbl, ico in NAV_ITEMS:
        if grp != last_group:
            st.markdown(f'<div class="nav-group">{grp}</div>', unsafe_allow_html=True)
            last_group = grp
        badge = ""
        if lbl == "Saved & Compare" and (st.session_state["favorites"] or st.session_state["compare_list"]):
            badge = f" ({len(st.session_state['favorites'])}/{len(st.session_state['compare_list'])})"
        elif lbl == "Food Journey Planner" and st.session_state["journey_stops"]:
            badge = f" ({len(st.session_state['journey_stops'])})"

        if st.button(
            f"{ico}  {lbl}{badge}",
            key=f"nav_{lbl}",
            use_container_width=True,
            type="primary" if st.session_state["page"] == lbl else "secondary",
        ):
            st.session_state["page"] = lbl
            st.rerun()

    st.divider()
    st.markdown('<div class="nav-group">SYSTEM STATUS</div>', unsafe_allow_html=True)
    if service.using_mysql:
        st.markdown('<div class="status-chip st-ok">● Azure MySQL: Connected</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="status-chip st-info">● Storage: Fallback Dataset</div>', unsafe_allow_html=True)

    if nlp_service.client:
        st.markdown(f'<div class="status-chip st-ok">● AI: {html.escape(nlp_service.model_id)}</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="status-chip st-warn">● AI: Rule-Based Fallback</div>', unsafe_allow_html=True)

    if st.button("🔄 Refresh Cache", key="btn_refresh_cache", use_container_width=True):
        st.session_state["cache_bust"] += 1
        st.rerun()


page = st.session_state["page"]


# ---------------------------------------------------------
# PAGE 1: GLOBAL MAP HUB (Heart of EatoSphere)
# ---------------------------------------------------------
if page == "Global Map Hub":
    render_header(
        "EATOSPHERE GEOSPATIAL WORKSPACE",
        "Global Map Hub",
        "Search, select restaurants, explore Haversine nearby alternatives, get directions, and build routes in one connected map experience.",
    )

    opts = cached_filter_options(service, st.session_state["cache_bust"])

    # Inline Map Filters
    with st.container(border=True):
        f1, f2, f3, f4, f5 = st.columns([1.2, 1.2, 1.4, 1.0, 1.2])
        m_country = f1.selectbox("Country", ["All"] + opts["countries"], key="hub_country")
        m_city = f2.selectbox("City", ["All"] + cached_cities(service, m_country, st.session_state["cache_bust"]), key="hub_city")
        m_cuisines = f3.multiselect("Cuisines", opts["cuisines"], key="hub_cuisines")
        m_rating = f4.slider("Min Rating", 0.0, 5.0, 0.0, 0.1, key="hub_rating")
        m_theme = f5.selectbox("Map Theme", ["CartoDB dark_matter", "CartoDB positron", "OpenStreetMap"], key="hub_theme")

        s1, s2, s3 = st.columns([2, 1.2, 1.2])
        m_search = s1.text_input("Search Restaurant Name", placeholder="e.g. Dishoom, Zuma, Kazoku...", key="hub_name")
        show_route = s2.checkbox("Overlay Journey Route", value=bool(st.session_state["journey_stops"]), key="hub_show_route")
        if st.session_state["map_override_df"] is not None:
            if s3.button("✖ Clear AI Map Filter", key="hub_clear_override", use_container_width=True):
                st.session_state["map_override_df"] = None
                st.session_state["map_override_label"] = None
                st.rerun()

    if st.session_state["map_override_df"] is not None:
        st.info(f"Showing results from: **{st.session_state['map_override_label']}**")
        map_df = st.session_state["map_override_df"]
    else:
        map_df = service.search_restaurants(
            SearchParams(
                country=m_country,
                city=m_city,
                cuisines=m_cuisines,
                min_rating=m_rating if m_rating > 0 else None,
                search_query=m_search.strip() or None,
            ),
            sort_by="rating",
        )

    left_col, right_col = st.columns([1.85, 1.15], gap="large")

    with left_col:
        st.caption(f"Displaying {len(map_df):,} matching restaurants.")
        fig = build_plotly_map(
            map_df,
            tile_style=m_theme,
            selected=st.session_state["selected_restaurant"],
            route_stops=st.session_state["journey_stops"] if show_route else None,
            height=580,
        )
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True, key="hub_main_map")
        else:
            render_empty("No Geolocated Restaurants", "Adjust your filters to display restaurants with valid coordinates.")

    with right_col:
        st.markdown("#### Interactive Restaurant Inspector")
        if not map_df.empty:
            labels = [f"{r['name']} ({r['city']}) — ★ {r['rating']}" for _, r in map_df.head(150).iterrows()]
            chosen_lbl = st.selectbox("Select a restaurant to inspect & center map", ["— Choose —"] + labels, key="hub_pick_rest")
            if chosen_lbl != "— Choose —":
                idx = labels.index(chosen_lbl)
                st.session_state["selected_restaurant"] = _row_to_dict(map_df.iloc[idx])

        sel = st.session_state["selected_restaurant"]
        if sel:
            render_restaurant_card(sel, key_prefix="hub_sel", show_actions=True)
            dir_url = build_directions_url(sel)
            if dir_url:
                st.link_button("📍 Open Directions in Google Maps", dir_url, use_container_width=True)
            else:
                st.caption("Precise navigation link unavailable (missing coordinates and address).")

            # Nearby Discovery directly inside the Map Hub
            if is_valid_coord(sel.get("latitude"), sel.get("longitude")):
                st.markdown("##### Nearby Alternatives (Straight-Line Haversine)")
                rad = st.select_slider("Radius (km)", options=[0.5, 1.0, 3.0, 5.0, 10.0], value=3.0, key="hub_nearby_rad")
                nearby_df = service.find_nearby_restaurants(
                    float(sel["latitude"]),
                    float(sel["longitude"]),
                    radius_km=float(rad),
                    exclude_name=sel.get("name"),
                    limit=5,
                )
                if nearby_df.empty:
                    st.caption(f"No other indexed restaurants within {rad} km straight-line distance.")
                else:
                    for i, (_, nrow) in enumerate(nearby_df.iterrows()):
                        render_restaurant_card(nrow, key_prefix=f"hub_nb_{i}", show_actions=True)
        else:
            render_empty("Select a Restaurant", "Pick any restaurant above to inspect details, get directions, and find nearby alternatives.")


# ---------------------------------------------------------
# PAGE 2: RESTAURANT EXPLORER
# ---------------------------------------------------------
elif page == "Restaurant Explorer":
    render_header(
        "DISCOVERY ENGINE",
        "Restaurant Explorer",
        "Filter across countries, cities, cuisines, ratings, and budgets with side-by-side comparison and CSV export.",
    )

    opts = cached_filter_options(service, st.session_state["cache_bust"])

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns(4)
        c_opts = ["All"] + opts["countries"]
        if st.session_state["exp_country"] not in c_opts:
            st.session_state["exp_country"] = "All"
        sel_c = c1.selectbox("Country", c_opts, index=c_opts.index(st.session_state["exp_country"]), key="ex_c")
        if sel_c != st.session_state["exp_country"]:
            st.session_state["exp_country"] = sel_c
            st.session_state["exp_city"] = "All"
            st.session_state["exp_page"] = 1

        city_opts = ["All"] + cached_cities(service, st.session_state["exp_country"], st.session_state["cache_bust"])
        if st.session_state["exp_city"] not in city_opts:
            st.session_state["exp_city"] = "All"
        sel_city = c2.selectbox("City", city_opts, index=city_opts.index(st.session_state["exp_city"]), key="ex_city")
        st.session_state["exp_city"] = sel_city

        sel_cuis = c3.multiselect("Cuisines", opts["cuisines"], default=[x for x in st.session_state["exp_cuisines"] if x in opts["cuisines"]], key="ex_cuis")
        st.session_state["exp_cuisines"] = sel_cuis

        sel_rtg = c4.slider("Minimum Rating", 0.0, 5.0, float(st.session_state["exp_rating"]), 0.1, key="ex_rtg")
        st.session_state["exp_rating"] = sel_rtg

        d1, d2, d3, d4 = st.columns([2, 1.3, 1.2, 1.4])
        st.session_state["exp_name"] = d1.text_input("Restaurant Name", value=st.session_state["exp_name"], key="ex_name")
        st.session_state["exp_locality"] = d2.text_input("Locality", value=st.session_state["exp_locality"], key="ex_loc")
        st.session_state["exp_max_cost"] = d3.number_input("Max Cost / 2", min_value=0, value=int(st.session_state["exp_max_cost"]), step=50, key="ex_cost")
        sort_map = {"rating": "★ Highest Rated", "votes": "🔥 Most Votes", "cost_low": "💰 Cost Low→High", "cost_high": "💎 Cost High→Low", "name": "🔤 Name"}
        st.session_state["exp_sort"] = d4.selectbox("Sort By", list(sort_map.keys()), format_func=lambda x: sort_map[x], key="ex_sort")

        if st.button("↺ Reset All Filters", key="ex_reset"):
            st.session_state.update({"exp_country": "All", "exp_city": "All", "exp_cuisines": [], "exp_rating": 0.0, "exp_name": "", "exp_locality": "", "exp_max_cost": 0, "exp_page": 1})
            st.rerun()

    guardrail = st.session_state["exp_max_cost"] > 0 and st.session_state["exp_country"] == "All"
    if guardrail:
        st.warning("Currency Guardrail: Select a specific Country before filtering by Max Cost so different currencies are not mixed.")

    res_df = service.search_restaurants(
        SearchParams(
            country=st.session_state["exp_country"],
            city=st.session_state["exp_city"],
            locality=st.session_state["exp_locality"].strip() or None,
            cuisines=st.session_state["exp_cuisines"],
            min_rating=st.session_state["exp_rating"] if st.session_state["exp_rating"] > 0 else None,
            max_cost_for_two=st.session_state["exp_max_cost"] if (st.session_state["exp_max_cost"] > 0 and not guardrail) else None,
            search_query=st.session_state["exp_name"].strip() or None,
        ),
        sort_by=st.session_state["exp_sort"],
    )

    h1, h2, h3 = st.columns([2.2, 1.3, 1.2])
    h1.subheader(f"Found {len(res_df):,} Restaurants")
    mode = h2.radio("View", ["Cards", "Table"], horizontal=True, label_visibility="collapsed", key="ex_mode")
    if not res_df.empty:
        h3.download_button("⬇ Export CSV", res_df.to_csv(index=False).encode("utf-8"), "eatosphere_results.csv", "text/csv", use_container_width=True)

    if res_df.empty:
        render_empty("No Matching Restaurants", "Try relaxing your filters or clearing your search query.")
    else:
        page_size = 8
        total_pages = max(1, math.ceil(len(res_df) / page_size))
        cur_page = st.number_input(f"Page (1–{total_pages})", 1, total_pages, min(st.session_state["exp_page"], total_pages), key="ex_pg")
        st.session_state["exp_page"] = int(cur_page)
        page_df = res_df.iloc[(cur_page - 1) * page_size : cur_page * page_size]

        if mode == "Cards":
            cl, cr = st.columns(2)
            for idx, (_, row) in enumerate(page_df.iterrows()):
                with (cl if idx % 2 == 0 else cr):
                    render_restaurant_card(row, key_prefix=f"ex_{cur_page}_{idx}", show_actions=True)
        else:
            cols = [c for c in ["name", "country", "city", "locality", "cuisines", "rating", "votes", "avg_cost_for_two", "currency"] if c in page_df.columns]
            st.dataframe(page_df[cols], use_container_width=True, hide_index=True)


# ---------------------------------------------------------
# PAGE 3: EXPLORE DESTINATIONS (Distinct Cultural Identity)
# ---------------------------------------------------------
elif page == "Explore Destinations":
    render_header(
        "CULTURAL & DESTINATION GUIDE",
        "Explore Destinations",
        "Experience each market's culinary identity, signature traditions, and real dataset coverage.",
    )

    opts = cached_filter_options(service, st.session_state["cache_bust"])
    countries = opts["countries"]
    if not countries:
        render_empty("No Destinations Available", "No country records found in the dataset.")
    else:
        default_idx = countries.index(st.session_state["selected_destination"]) if st.session_state["selected_destination"] in countries else 0
        sel_dest = st.selectbox("Choose a Destination", countries, index=default_idx, key="dest_selector")
        st.session_state["selected_destination"] = sel_dest

        profile = service.get_destination_profile(sel_dest)
        cult = profile["culture"]

        # Destination-specific themed hero banner
        st.markdown(
            f"""
            <div class="dest-hero" style="background:{cult['gradient']}; border-left: 5px solid {cult['accent']};">
                <div style="font-size:0.75rem; font-weight:800; letter-spacing:0.12em; color:{cult['accent']}; text-transform:uppercase;">DESTINATION PROFILE</div>
                <h2 style="margin:4px 0 8px 0; color:#FFF8EB; font-size:2rem;">{html.escape(sel_dest)}</h2>
                <p style="color:#E2E8F0; font-size:1rem; margin:0 0 10px 0;">{html.escape(cult['tagline'])}</p>
                <div style="color:#CBD5E1; font-size:0.88rem; margin-bottom:8px;"><b>Dining Tradition:</b> {html.escape(cult['dining_tradition'])}</div>
                <div style="color:#94A3B8; font-size:0.75rem;">Source: {html.escape(cult['attribution'])}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        k1, k2, k3, k4 = st.columns(4)
        render_kpi(k1, "Indexed Restaurants", f"{profile['count']:,}", f"In {sel_dest}")
        render_kpi(k2, "Cities Covered", f"{profile['city_count']:,}", ", ".join(profile["top_cities"][:3]) or "N/A")
        render_kpi(k3, "Average Rating", f"★ {profile['avg_rating']:.2f}", "Dataset Average")
        render_kpi(k4, "Top Cuisines", str(len(profile["top_cuisines"])), ", ".join(profile["top_cuisines"][:2]) or "N/A")

        st.write("")
        b1, b2 = st.columns(2)
        if b1.button(f"🧭 Explore All {sel_dest} Restaurants", use_container_width=True, type="primary"):
            st.session_state["exp_country"] = sel_dest
            st.session_state["exp_city"] = "All"
            st.session_state["page"] = "Restaurant Explorer"
            st.rerun()
        if b2.button(f"🌐 Open {sel_dest} on Global Map", use_container_width=True):
            st.session_state["map_override_df"] = profile["df"]
            st.session_state["map_override_label"] = f"Destination: {sel_dest}"
            st.session_state["page"] = "Global Map Hub"
            st.rerun()

        st.markdown("#### Signature Culinary Highlights")
        dish_pills = "".join(f'<span class="pill pill-cost">{html.escape(d)}</span>' for d in cult["signature_dishes"])
        st.markdown(dish_pills, unsafe_allow_html=True)

        st.markdown(f"#### Top-Rated Restaurants in {sel_dest}")
        top_dest = profile["df"].sort_values(by="rating", ascending=False).head(6)
        dl, dr = st.columns(2)
        for i, (_, row) in enumerate(top_dest.iterrows()):
            with (dl if i % 2 == 0 else dr):
                render_restaurant_card(row, key_prefix=f"dest_{i}", show_actions=True)


# ---------------------------------------------------------
# PAGE 4: FOOD JOURNEY PLANNER
# ---------------------------------------------------------
elif page == "Food Journey Planner":
    render_header(
        "PERSONAL ITINERARY BUILDER",
        "Food Journey Planner",
        "Organize your selected restaurants into a multi-stop culinary sequence, visualize on the map, and export your plan.",
    )

    stops: List[Dict[str, Any]] = st.session_state["journey_stops"]
    if not stops:
        render_empty(
            "Your Food Journey is Empty",
            "Add restaurants from the Global Map Hub, Restaurant Explorer, or ask the AI Culinary Concierge to build a food journey.",
        )
    else:
        left, right = st.columns([1.15, 1.35], gap="large")
        with left:
            st.markdown(f"#### Planned Stops ({len(stops)})")
            total_straight_km = 0.0
            for i, s in enumerate(stops):
                st.markdown(f"**Stop {i + 1}: {s.get('name')}** — {s.get('city')} (★ {s.get('rating')}, {_fmt_cost(s)})")
                if i > 0 and is_valid_coord(stops[i - 1].get("latitude"), stops[i - 1].get("longitude")) and is_valid_coord(s.get("latitude"), s.get("longitude")):
                    leg = haversine_km(float(stops[i - 1]["latitude"]), float(stops[i - 1]["longitude"]), float(s["latitude"]), float(s["longitude"]))
                    total_straight_km += leg
                    st.caption(f"↳ ~{leg:.2f} km straight-line from Stop {i}")
                c_up, c_dn, c_rm, c_dir = st.columns(4)
                if i > 0 and c_up.button("↑", key=f"j_up_{i}", use_container_width=True):
                    stops[i - 1], stops[i] = stops[i], stops[i - 1]
                    st.rerun()
                if i < len(stops) - 1 and c_dn.button("↓", key=f"j_dn_{i}", use_container_width=True):
                    stops[i + 1], stops[i] = stops[i], stops[i + 1]
                    st.rerun()
                if c_rm.button("✖", key=f"j_rm_{i}", use_container_width=True):
                    stops.pop(i)
                    st.rerun()
                d_url = build_directions_url(s)
                if d_url:
                    c_dir.link_button("Go", d_url, use_container_width=True)

            st.info(f"Approximate total straight-line span: **{total_straight_km:.2f} km** (not road distance).")
            plan_text = "\n".join(
                f"{i+1}. {s.get('name')} ({s.get('city')}) — {s.get('cuisines')} | ★ {s.get('rating')} | {s.get('address')}"
                for i, s in enumerate(stops)
            )
            st.download_button("⬇ Export Itinerary (.txt)", plan_text.encode("utf-8"), "eatosphere_journey.txt", "text/plain", use_container_width=True)
            if st.button("Clear Journey", key="j_clear_all", use_container_width=True):
                st.session_state["journey_stops"] = []
                st.rerun()

        with right:
            st.markdown("#### Journey Map Sequence")
            fig = build_plotly_map(pd.DataFrame(stops), route_stops=stops, height=520)
            if fig is not None:
                st.plotly_chart(fig, use_container_width=True, key="journey_map")


# ---------------------------------------------------------
# PAGE 5: SAVED PLACES, COMPARE & CULINARY PASSPORT
# ---------------------------------------------------------
elif page == "Saved & Compare":
    render_header(
        "PERSONAL COLLECTION & COMPARISON",
        "Saved Places, Compare & Culinary Passport",
        "Manage your session-saved favorites, compare restaurants side-by-side, and track your explored cuisines.",
    )

    t_fav, t_cmp, t_pass = st.tabs(["♥ Saved Places", "⚖ Compare Restaurants", "🛂 Culinary Passport"])

    with t_fav:
        favs = st.session_state["favorites"]
        if not favs:
            render_empty("No Saved Places Yet", "Click '♥ Save' on any restaurant card to build your session collection.")
        else:
            st.caption("Saved places persist for your current browser session.")
            fl, fr = st.columns(2)
            for i, item in enumerate(favs):
                with (fl if i % 2 == 0 else fr):
                    render_restaurant_card(item, key_prefix=f"fav_{i}", show_actions=True)
                    if st.button("Remove from Saved", key=f"rm_fav_{i}"):
                        favs.pop(i)
                        st.rerun()

    with t_cmp:
        cmps = st.session_state["compare_list"]
        if not cmps:
            render_empty("No Restaurants Selected for Comparison", "Click '⚖ Compare' on up to 4 restaurants to compare them side-by-side.")
        else:
            cdf = pd.DataFrame(cmps)
            if "currency" in cdf.columns and cdf["currency"].nunique() > 1:
                st.warning("Selected restaurants use different local currencies—avoid comparing raw cost numbers directly.")
            cols = [c for c in ["name", "country", "city", "locality", "cuisines", "rating", "votes", "avg_cost_for_two", "currency", "address"] if c in cdf.columns]
            st.dataframe(cdf[cols].set_index("name"), use_container_width=True)
            if st.button("Clear Comparison List", key="clear_cmp"):
                st.session_state["compare_list"] = []
                st.rerun()

    with t_pass:
        combined = st.session_state["favorites"] + st.session_state["journey_stops"]
        explored_countries = sorted({x.get("country") for x in combined if x.get("country")})
        explored_cuisines = sorted({c.strip() for x in combined for c in str(x.get("cuisines", "")).split(",") if c.strip()})
        p1, p2, p3 = st.columns(3)
        render_kpi(p1, "Saved Restaurants", str(len(st.session_state["favorites"])), "Current Session")
        render_kpi(p2, "Countries Explored", str(len(explored_countries)), ", ".join(explored_countries[:3]) or "None yet")
        render_kpi(p3, "Cuisines Collected", str(len(explored_cuisines)), ", ".join(explored_cuisines[:3]) or "None yet")


# ---------------------------------------------------------
# PAGE 6: AI CULINARY CONCIERGE (Action-Taking Assistant)
# ---------------------------------------------------------
elif page == "AI Culinary Concierge":
    render_header(
        "ACTION-ORIENTED AI ASSISTANT",
        "AI Culinary Concierge",
        "Ask in plain English to search, compare previous results, explore food culture, or generate a multi-stop itinerary grounded in real database records.",
    )

    ex1, ex2, ex3, ex4 = st.columns(4)
    quick_prompt = None
    if ex1.button("🍝 Italian in Cairo under 700", use_container_width=True):
        quick_prompt = "Find Italian restaurants in Cairo under 700"
    if ex2.button("🍛 Top Indian in London", use_container_width=True):
        quick_prompt = "Top rated Indian restaurants in London"
    if ex3.button("🗺️ 3-stop food journey in Dubai", use_container_width=True):
        quick_prompt = "Build a 3 stops food journey in Dubai"
    if ex4.button("🏛️ Food culture in Egypt", use_container_width=True):
        quick_prompt = "What traditional food culture should I try in Egypt?"

    user_msg = st.chat_input("Ask EatoSphere AI (e.g. 'Compare cheapest from above', 'Build a 3 stops food trip in Cairo')...")
    active_prompt = quick_prompt or user_msg

    if active_prompt:
        st.session_state["ai_messages"].append({"role": "user", "content": active_prompt})
        with st.spinner("Coordinating validated backend tools..."):
            resp = nlp_service.concierge_respond(
                active_prompt,
                last_results=st.session_state["ai_last_df"],
                selected_restaurant=st.session_state["selected_restaurant"],
            )
        if resp["results"] is not None and not resp["results"].empty:
            st.session_state["ai_last_df"] = resp["results"]
        st.session_state["ai_messages"].append({"role": "assistant", "payload": resp})

    if st.session_state["ai_messages"]:
        if st.button("Clear Conversation", key="ai_clear_chat"):
            st.session_state["ai_messages"] = []
            st.session_state["ai_last_df"] = None
            st.rerun()

    for m_idx, msg in enumerate(st.session_state["ai_messages"]):
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.write(msg["content"])
            else:
                p = msg["payload"]
                st.caption(f"Engine: {p['engine']} · Action: `{p['intent']}`")
                st.markdown(p["message"])
                with st.expander("Validated Pydantic Parameters", expanded=False):
                    st.json(p["params"].model_dump(exclude_none=True))

                res: pd.DataFrame = p["results"]
                if res is not None and not res.empty:
                    b_map, b_jrn = st.columns(2)
                    if b_map.button("🌐 Send These Results to Global Map Hub", key=f"ai_to_map_{m_idx}", use_container_width=True):
                        st.session_state["map_override_df"] = res
                        st.session_state["map_override_label"] = f"AI Concierge ({p['intent']})"
                        st.session_state["page"] = "Global Map Hub"
                        st.rerun()
                    if p.get("itinerary") is not None:
                        if b_jrn.button("🗺️ Load Itinerary into Journey Planner", key=f"ai_to_jrn_{m_idx}", use_container_width=True):
                            st.session_state["journey_stops"] = [_row_to_dict(r) for _, r in p["itinerary"].iterrows()]
                            st.session_state["page"] = "Food Journey Planner"
                            st.rerun()

                    c_a, c_b = st.columns(2)
                    for r_i, (_, row) in enumerate(res.head(6).iterrows()):
                        with (c_a if r_i % 2 == 0 else c_b):
                            render_restaurant_card(row, key_prefix=f"ai_{m_idx}_{r_i}", show_actions=True)


# ---------------------------------------------------------
# PAGE 7: GLOBAL CULINARY DASHBOARD
# ---------------------------------------------------------
elif page == "Global Culinary Dashboard":
    render_header(
        "GLOBAL CULINARY INTELLIGENCE",
        "Executive Analytics Dashboard",
        "Real-time coverage, cuisine intelligence, and rating analytics across the Gold serving layer.",
    )

    stats = cached_analytics(service, st.session_state["cache_bust"])
    df_all = stats["df"]

    k1, k2, k3, k4, k5 = st.columns(5)
    render_kpi(k1, "Indexed Restaurants", f"{stats['total_restaurants']:,}", "Gold Serving Layer")
    render_kpi(k2, "Countries", f"{stats['total_countries']:,}", f"{stats['total_cities']:,} Cities")
    render_kpi(k3, "Cuisines", f"{stats['total_cuisines']:,}", "Distinct Categories")
    render_kpi(k4, "Average Rating", f"★ {stats['avg_rating']:.2f}", f"{stats['total_votes']:,} Votes")
    render_kpi(k5, "Geolocated", f"{stats['valid_coords_count']:,}", "Valid Coordinates")

    st.write("")
    # Quick Drill-Down to Explorer
    d_col1, d_col2 = st.columns([2, 1])
    drill_country = d_col1.selectbox("Drill-down into a Country", ["— Select Country —"] + sorted(df_all["country"].dropna().unique().tolist()), key="dash_drill_c")
    if d_col2.button("Open in Explorer →", use_container_width=True, type="primary") and drill_country != "— Select Country —":
        st.session_state["exp_country"] = drill_country
        st.session_state["exp_city"] = "All"
        st.session_state["page"] = "Restaurant Explorer"
        st.rerun()

    ch1, ch2 = st.columns(2)
    with ch1:
        st.markdown("#### Top Cuisines")
        fig1 = px.bar(stats["top_cuisines"], x="restaurants", y="cuisine", orientation="h", color="restaurants", color_continuous_scale=["#FB923C", "#EA580C"])
        fig1.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.35)", font_color="#E2E8F0", height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig1, use_container_width=True)

    with ch2:
        st.markdown("#### Restaurants by Country")
        ctry_df = df_all["country"].value_counts().head(12).reset_index()
        ctry_df.columns = ["country", "restaurants"]
        fig2 = px.bar(ctry_df, x="country", y="restaurants", color="restaurants", color_continuous_scale=["#22D3EE", "#0284C7"])
        fig2.update_layout(coloraxis_showscale=False, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,23,42,0.35)", font_color="#E2E8F0", height=340, margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)


# ---------------------------------------------------------
# PAGE 8: DATA ENGINEERING MONITOR
# ---------------------------------------------------------
elif page == "Data Engineering Monitor":
    render_header(
        "PLATFORM OBSERVABILITY",
        "Data Engineering Monitor",
        "Stored telemetry for Bronze, Silver, and Gold Medallion layers, Apache Airflow DAG runs, and quarantined records.",
    )

    runs_df, quarantine_df = cached_telemetry(service, st.session_state["cache_bust"])
    latest = runs_df.iloc[0] if (runs_df is not None and not runs_df.empty) else None

    m1, m2, m3 = st.columns(3)
    m1.markdown(
        f"<div class='medallion-stage' style='border-top-color:#F59E0B;'><b>🥉 BRONZE — Azure Blob</b><br>"
        f"<span style='color:#94A3B8;'>Raw immutable CSV/Parquet</span><br><br>"
        f"<b>{int(latest['rows_ingested']):,} rows ingested</b></div>" if latest is not None else "<div class='medallion-stage'>Telemetry Unavailable</div>",
        unsafe_allow_html=True,
    )
    m2.markdown(
        f"<div class='medallion-stage' style='border-top-color:#22D3EE;'><b>🥈 SILVER — MySQL</b><br>"
        f"<span style='color:#94A3B8;'>Cleaned & deduplicated</span><br><br>"
        f"<b>{int(latest['rows_silver']):,} valid · {int(latest['rows_quarantined']):,} quarantined</b></div>" if latest is not None else "<div class='medallion-stage'>Telemetry Unavailable</div>",
        unsafe_allow_html=True,
    )
    m3.markdown(
        f"<div class='medallion-stage' style='border-top-color:#10B981;'><b>🥇 GOLD — MySQL</b><br>"
        f"<span style='color:#94A3B8;'>Indexed serving layer</span><br><br>"
        f"<b>Status: {html.escape(str(latest['status']))} ({latest['duration_sec']}s)</b></div>" if latest is not None else "<div class='medallion-stage'>Telemetry Unavailable</div>",
        unsafe_allow_html=True,
    )

    st.write("")
    st.markdown("#### Apache Airflow DAG Execution History")
    if runs_df is not None and not runs_df.empty:
        st.dataframe(runs_df, use_container_width=True, hide_index=True)
    else:
        render_empty("No Pipeline Runs", "No stored DAG execution records found.")

    st.markdown("#### Data Quality Quarantine Inspector")
    if quarantine_df is not None and not quarantine_df.empty:
        st.dataframe(quarantine_df, use_container_width=True, hide_index=True)
    else:
        render_empty("No Quarantined Records", "No data quality issues reported.")