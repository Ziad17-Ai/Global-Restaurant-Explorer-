import json
import math
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Literal, Optional, Tuple
from urllib.parse import quote_plus

import pandas as pd
import streamlit as st
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

try:
    from huggingface_hub import InferenceClient
except ImportError:
    InferenceClient = None


def get_secret(key: str, default: Optional[str] = None) -> Optional[str]:
    try:
        if key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


# ---------------------------------------------------------
# 1. Pydantic Models (Strict Validation & Tool Schemas)
# ---------------------------------------------------------
class SearchParams(BaseModel):
    country: Optional[str] = None
    city: Optional[str] = None
    locality: Optional[str] = None
    cuisines: List[str] = Field(default_factory=list)
    min_rating: Optional[float] = Field(default=None, ge=0.0, le=5.0)
    min_cost_for_two: Optional[float] = Field(default=None, ge=0.0)
    max_cost_for_two: Optional[float] = Field(default=None, ge=0.0)
    search_query: Optional[str] = None
    needs_clarification: Optional[str] = None


class ConciergeAction(BaseModel):
    intent: Literal["search", "compare", "itinerary", "nearby", "culture"] = "search"
    params: SearchParams = Field(default_factory=SearchParams)
    stop_count: int = Field(default=3, ge=2, le=6)
    radius_km: float = Field(default=5.0, ge=0.5, le=25.0)
    sort_by: Literal["rating", "votes", "cost_low", "cost_high", "name"] = "rating"
    target_country: Optional[str] = None
    target_city: Optional[str] = None


# ---------------------------------------------------------
# 2. Curated Cultural & Destination Metadata (Attributed)
# ---------------------------------------------------------
DESTINATION_CULTURE: Dict[str, Dict[str, Any]] = {
    "Egypt": {
        "tagline": "Nile-side street classics, warm spice blends, and late-night mezze culture.",
        "accent": "#D97706",
        "gradient": "linear-gradient(135deg, rgba(217,119,6,0.28) 0%, rgba(120,53,15,0.22) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Koshari", "Ful Medames", "Ta'ameya", "Molokhia", "Hawawshi"],
        "dining_tradition": "Communal dining centered around shared mezze, freshly baked baladi bread, and vibrant evening café culture.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
    "India": {
        "tagline": "A subcontinent of regional spice traditions, tandoor craft, and royal Mughlai kitchens.",
        "accent": "#EA580C",
        "gradient": "linear-gradient(135deg, rgba(234,88,12,0.28) 0%, rgba(154,52,18,0.22) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Biryani", "Butter Chicken", "Masala Dosa", "Chaat", "Rogan Josh"],
        "dining_tradition": "Deeply regional menus spanning North Indian tandoors, South Indian fermented batters, and vibrant street-food bazaars.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
    "UAE": {
        "tagline": "Cosmopolitan fine dining meets Emirati hospitality and Levantine spice routes.",
        "accent": "#EAB308",
        "gradient": "linear-gradient(135deg, rgba(234,179,8,0.25) 0%, rgba(14,116,144,0.20) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Machboos", "Shawarma", "Luqaimat", "Grilled Kebabs", "Global Tasting Menus"],
        "dining_tradition": "A global crossroads blending traditional Arabian hospitality with international chef-led dining districts.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
    "United Kingdom": {
        "tagline": "Historic gastropubs, world-class curry houses, and multicultural market kitchens.",
        "accent": "#38BDF8",
        "gradient": "linear-gradient(135deg, rgba(56,189,248,0.24) 0%, rgba(30,58,138,0.24) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Sunday Roast", "Fish & Chips", "British-Indian Curry", "Artisan Pies", "Afternoon Tea"],
        "dining_tradition": "Neighborhood pubs and historic food markets paired with one of the world's most diverse international dining scenes.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
    "United States": {
        "tagline": "Regional smokehouses, classic diners, and coastal farm-to-table innovation.",
        "accent": "#FB7185",
        "gradient": "linear-gradient(135deg, rgba(251,113,133,0.24) 0%, rgba(30,64,175,0.22) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Regional BBQ", "Craft Burgers", "Cajun Gumbo", "New York Pizza", "Seafood Boils"],
        "dining_tradition": "Distinct state-by-state culinary identities shaped by immigrant traditions, barbecue pits, and casual neighborhood grills.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
    "Brazil": {
        "tagline": "Flame-grilled churrasco, tropical coastal flavors, and lively neighborhood botecos.",
        "accent": "#10B981",
        "gradient": "linear-gradient(135deg, rgba(16,185,129,0.26) 0%, rgba(234,179,8,0.18) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Feijoada", "Churrasco", "Pão de Queijo", "Moqueca", "Açaí"],
        "dining_tradition": "Social, unhurried meals built around charcoal-grilled meats, cassava, fresh seafood, and neighborhood bakeries.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
    "Turkey": {
        "tagline": "Anatolian hearth cooking, Aegean olive-oil mezes, and centuries-old bazaar sweets.",
        "accent": "#F43F5E",
        "gradient": "linear-gradient(135deg, rgba(244,63,94,0.26) 0%, rgba(217,119,6,0.20) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Adana Kebab", "Meze Platters", "Pide", "Lahmacun", "Baklava"],
        "dining_tradition": "Generous multi-course tables starting with cold mezes and concluding with Turkish tea or coffee.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
    "Singapore": {
        "tagline": "UNESCO-recognized hawker heritage alongside precision modern Asian gastronomy.",
        "accent": "#22D3EE",
        "gradient": "linear-gradient(135deg, rgba(34,211,238,0.24) 0%, rgba(239,68,68,0.18) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Hainanese Chicken Rice", "Laksa", "Chilli Crab", "Char Kway Teow", "Satay"],
        "dining_tradition": "A fusion of Chinese, Malay, Indian, and Peranakan traditions celebrated in bustling hawker centers and fine dining rooms.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
    "Phillipines": {
        "tagline": "Savory-tangy adobo, wood-fired lechon, and warm island hospitality.",
        "accent": "#F59E0B",
        "gradient": "linear-gradient(135deg, rgba(245,158,11,0.25) 0%, rgba(56,189,248,0.20) 55%, rgba(15,23,42,0.92) 100%)",
        "signature_dishes": ["Adobo", "Sinigang", "Lechon", "Sisig", "Halo-Halo"],
        "dining_tradition": "Family-style feasts balancing vinegar, garlic, soy, and tropical citrus across coastal and urban kitchens.",
        "attribution": "Curated culinary reference (EatoSphere Editorial Metadata)",
    },
}

DEFAULT_CULTURE: Dict[str, Any] = {
    "tagline": "Local culinary traditions and international dining experiences represented in the dataset.",
    "accent": "#F97316",
    "gradient": "linear-gradient(135deg, rgba(249,115,22,0.22) 0%, rgba(34,211,238,0.14) 55%, rgba(15,23,42,0.92) 100%)",
    "signature_dishes": ["Regional Specialties", "Local Cafes", "International Dining"],
    "dining_tradition": "Explore represented cuisines, top-rated neighborhoods, and local dining spots directly from verified dataset records.",
    "attribution": "Derived from dataset coverage (EatoSphere)",
}


# ---------------------------------------------------------
# 3. Fallback Dataset (Used only when MySQL is unavailable)
# ---------------------------------------------------------
SAMPLE_RESTAURANTS = [
    {"restaurant_id": 101, "name": "Kazoku", "country": "Egypt", "city": "Cairo", "locality": "New Cairo", "address": "Swan Lake Residence, New Cairo", "cuisines": "Japanese, Sushi, Asian", "rating": 4.8, "votes": 1420, "avg_cost_for_two": 2200, "currency": "EGP", "price_tier": 4, "latitude": 30.0561, "longitude": 31.4913, "source": "egypt_restaurants"},
    {"restaurant_id": 102, "name": "Zooba", "country": "Egypt", "city": "Cairo", "locality": "Zamalek", "address": "26th of July Corridor, Zamalek", "cuisines": "Egyptian, Street Food", "rating": 4.5, "votes": 3180, "avg_cost_for_two": 480, "currency": "EGP", "price_tier": 2, "latitude": 30.0609, "longitude": 31.2197, "source": "egypt_restaurants"},
    {"restaurant_id": 103, "name": "Maison Thomas", "country": "Egypt", "city": "Cairo", "locality": "Zamalek", "address": "157 26th of July St, Zamalek", "cuisines": "Italian, Pizza, Cafe", "rating": 4.4, "votes": 2150, "avg_cost_for_two": 650, "currency": "EGP", "price_tier": 2, "latitude": 30.0626, "longitude": 31.2211, "source": "egypt_restaurants"},
    {"restaurant_id": 104, "name": "Eish & Malh", "country": "Egypt", "city": "Cairo", "locality": "Downtown", "address": "20 Adly St, Downtown Cairo", "cuisines": "Italian, Mediterranean, Bistro", "rating": 4.3, "votes": 1890, "avg_cost_for_two": 550, "currency": "EGP", "price_tier": 2, "latitude": 30.0494, "longitude": 31.2421, "source": "egypt_restaurants"},
    {"restaurant_id": 105, "name": "Sachi", "country": "Egypt", "city": "Cairo", "locality": "Heliopolis", "address": "3 Cleopatra St, Korba, Heliopolis", "cuisines": "Mediterranean, Asian Fusion, Fine Dining", "rating": 4.7, "votes": 1640, "avg_cost_for_two": 2400, "currency": "EGP", "price_tier": 4, "latitude": 30.0911, "longitude": 31.3249, "source": "egypt_restaurants"},
    {"restaurant_id": 106, "name": "Byblos", "country": "Egypt", "city": "Alexandria", "locality": "San Stefano", "address": "Four Seasons Hotel, San Stefano", "cuisines": "Lebanese, Middle Eastern", "rating": 4.7, "votes": 980, "avg_cost_for_two": 1600, "currency": "EGP", "price_tier": 4, "latitude": 31.2456, "longitude": 29.9668, "source": "egypt_restaurants"},
    {"restaurant_id": 107, "name": "Fish Market", "country": "Egypt", "city": "Alexandria", "locality": "Bahary", "address": "Corniche Rd, Bahary", "cuisines": "Seafood, Egyptian", "rating": 4.3, "votes": 2410, "avg_cost_for_two": 950, "currency": "EGP", "price_tier": 3, "latitude": 31.2089, "longitude": 29.8850, "source": "egypt_restaurants"},
    {"restaurant_id": 108, "name": "Ole Cafe & Bistro", "country": "Egypt", "city": "Alexandria", "locality": "Smouha", "address": "Fawzy Moaz St, Smouha", "cuisines": "Italian, Cafe, Breakfast", "rating": 4.2, "votes": 730, "avg_cost_for_two": 420, "currency": "EGP", "price_tier": 2, "latitude": 31.2156, "longitude": 29.9420, "source": "egypt_restaurants"},
    {"restaurant_id": 109, "name": "Indian Accent", "country": "India", "city": "New Delhi", "locality": "Lodhi Road", "address": "The Lodhi, Lodhi Road", "cuisines": "Modern Indian, Fine Dining", "rating": 4.9, "votes": 4210, "avg_cost_for_two": 4500, "currency": "INR", "price_tier": 4, "latitude": 28.5919, "longitude": 77.2377, "source": "zomato"},
    {"restaurant_id": 110, "name": "Karim's", "country": "India", "city": "New Delhi", "locality": "Jama Masjid", "address": "Gali Kababian, Old Delhi", "cuisines": "Mughlai, North Indian", "rating": 4.4, "votes": 6890, "avg_cost_for_two": 850, "currency": "INR", "price_tier": 2, "latitude": 28.6507, "longitude": 77.2334, "source": "zomato"},
    {"restaurant_id": 111, "name": "Bukhara", "country": "India", "city": "New Delhi", "locality": "Chanakyapuri", "address": "ITC Maurya, Diplomatic Enclave", "cuisines": "North Indian, Kebab, Fine Dining", "rating": 4.8, "votes": 5120, "avg_cost_for_two": 6500, "currency": "INR", "price_tier": 4, "latitude": 28.5973, "longitude": 77.1736, "source": "zomato"},
    {"restaurant_id": 112, "name": "Dishoom", "country": "United Kingdom", "city": "London", "locality": "Covent Garden", "address": "12 Upper St Martin's Ln, London", "cuisines": "Indian, Cafe, Street Food", "rating": 4.7, "votes": 8340, "avg_cost_for_two": 70, "currency": "GBP", "price_tier": 3, "latitude": 51.5125, "longitude": -0.1269, "source": "zomato"},
    {"restaurant_id": 113, "name": "Padella", "country": "United Kingdom", "city": "London", "locality": "Borough Market", "address": "6 Southwark St, London", "cuisines": "Italian, Pasta", "rating": 4.6, "votes": 5490, "avg_cost_for_two": 50, "currency": "GBP", "price_tier": 2, "latitude": 51.5051, "longitude": -0.0900, "source": "zomato"},
    {"restaurant_id": 114, "name": "Zuma", "country": "UAE", "city": "Dubai", "locality": "DIFC", "address": "Gate Village 06, DIFC", "cuisines": "Japanese, Sushi, Fine Dining", "rating": 4.8, "votes": 3910, "avg_cost_for_two": 680, "currency": "AED", "price_tier": 4, "latitude": 25.2121, "longitude": 55.2809, "source": "zomato"},
    {"restaurant_id": 115, "name": "Al Ustad Special Kabab", "country": "UAE", "city": "Dubai", "locality": "Al Fahidi", "address": "Al Mussallah Rd, Bur Dubai", "cuisines": "Persian, Middle Eastern, Kebab", "rating": 4.5, "votes": 4120, "avg_cost_for_two": 110, "currency": "AED", "price_tier": 1, "latitude": 25.2631, "longitude": 55.2972, "source": "zomato"},
]

SAMPLE_PIPELINE_RUNS = [
    {"run_id": "dag_run_20261119_0200", "dag_id": "restaurant_etl_pipeline", "status": "SUCCESS", "started_at": (datetime.now() - timedelta(hours=4)).strftime("%Y-%m-%d %H:%M"), "duration_sec": 42, "rows_ingested": 15420, "rows_silver": 14890, "rows_quarantined": 530},
    {"run_id": "dag_run_20261118_0200", "dag_id": "restaurant_etl_pipeline", "status": "SUCCESS", "started_at": (datetime.now() - timedelta(days=1, hours=4)).strftime("%Y-%m-%d %H:%M"), "duration_sec": 39, "rows_ingested": 15420, "rows_silver": 14890, "rows_quarantined": 530},
    {"run_id": "dag_run_20261117_0200", "dag_id": "restaurant_etl_pipeline", "status": "FAILED_RETRY_OK", "started_at": (datetime.now() - timedelta(days=2, hours=4)).strftime("%Y-%m-%d %H:%M"), "duration_sec": 68, "rows_ingested": 14900, "rows_silver": 14350, "rows_quarantined": 550},
]

SAMPLE_QUARANTINE = [
    {"batch_id": "batch_001", "source": "zomato", "raw_name": "Unknown Bistro", "issue_type": "INVALID_COORDINATES", "details": "latitude=0.0, longitude=0.0"},
    {"batch_id": "batch_001", "source": "zomato", "raw_name": "Spice Hub", "issue_type": "NEGATIVE_COST", "details": "avg_cost_for_two=-150"},
    {"batch_id": "batch_002", "source": "egypt_restaurants", "raw_name": "Cairo Grill", "issue_type": "OUT_OF_RANGE_RATING", "details": "rating=6.4 (max allowed 5.0)"},
    {"batch_id": "batch_002", "source": "egypt_restaurants", "raw_name": "Duplicate Entry #44", "issue_type": "DUPLICATE_NATURAL_KEY", "details": "hash collision with restaurant_id=102"},
]


# ---------------------------------------------------------
# 4. Geospatial Utilities (Accurate Straight-Line Haversine)
# ---------------------------------------------------------
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line (great-circle) distance in kilometers between two WGS84 points."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * r * math.asin(math.sqrt(min(1.0, a)))


def is_valid_coord(lat: Any, lon: Any) -> bool:
    try:
        la, lo = float(lat), float(lon)
        if math.isnan(la) or math.isnan(lo):
            return False
        if la == 0.0 and lo == 0.0:
            return False
        return -90.0 <= la <= 90.0 and -180.0 <= lo <= 180.0
    except Exception:
        return False


def build_directions_url(row: Dict[str, Any], origin_lat: Optional[float] = None, origin_lon: Optional[float] = None) -> Optional[str]:
    """Build an external Google Maps directions URL using verified coordinates or address."""
    lat, lon = row.get("latitude"), row.get("longitude")
    if is_valid_coord(lat, lon):
        dest = f"{float(lat):.6f},{float(lon):.6f}"
    elif row.get("address"):
        dest = quote_plus(f"{row.get('name', '')}, {row.get('address', '')}, {row.get('city', '')}")
    else:
        return None

    base = f"https://www.google.com/maps/dir/?api=1&destination={dest}"
    if is_valid_coord(origin_lat, origin_lon):
        base += f"&origin={float(origin_lat):.6f},{float(origin_lon):.6f}"
    return base


# ---------------------------------------------------------
# 5. Repository & Intelligence Service (MySQL + Fallback)
# ---------------------------------------------------------
class RestaurantService:
    def __init__(self):
        self.engine: Optional[Engine] = self._init_db_engine()
        self.using_mysql = self.engine is not None

    def _init_db_engine(self) -> Optional[Engine]:
        db_url = get_secret("DATABASE_URL")
        if not db_url:
            return None
        try:
            connect_args = {}
            ssl_ca = get_secret("MYSQL_SSL_CA")
            if ssl_ca:
                connect_args["ssl"] = {"ca": ssl_ca}
            engine = create_engine(
                db_url,
                pool_size=3,
                max_overflow=2,
                pool_pre_ping=True,
                connect_args=connect_args,
            )
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return engine
        except Exception:
            return None

    def _get_base_df(self) -> pd.DataFrame:
        if self.using_mysql and self.engine is not None:
            return pd.read_sql(text("SELECT * FROM gold_restaurant_search"), self.engine)
        return pd.DataFrame(SAMPLE_RESTAURANTS)

    def get_filter_options(self) -> Dict[str, List[str]]:
        df = self._get_base_df()
        countries = sorted(df["country"].dropna().unique().tolist())
        cuisines = sorted({c.strip() for row in df["cuisines"].dropna() for c in str(row).split(",") if c.strip()})
        return {"countries": countries, "cuisines": cuisines}

    def get_cities(self, country: Optional[str] = None) -> List[str]:
        df = self._get_base_df()
        if country and country != "All":
            df = df[df["country"] == country]
        return sorted(df["city"].dropna().unique().tolist())

    def get_analytics(self) -> Dict[str, Any]:
        df = self._get_base_df()
        cuisine_series = (
            df["cuisines"].dropna().astype(str).str.split(",").explode().str.strip()
        )
        cuisine_series = cuisine_series[cuisine_series != ""].value_counts().head(10)
        valid_coords = int(
            df.apply(lambda r: is_valid_coord(r.get("latitude"), r.get("longitude")), axis=1).sum()
        ) if not df.empty else 0

        return {
            "df": df,
            "total_restaurants": len(df),
            "total_countries": df["country"].nunique() if "country" in df.columns else 0,
            "total_cities": df["city"].nunique() if "city" in df.columns else 0,
            "total_localities": df["locality"].nunique() if "locality" in df.columns else 0,
            "total_cuisines": len({c.strip() for row in df["cuisines"].dropna() for c in str(row).split(",") if c.strip()}) if "cuisines" in df.columns else 0,
            "valid_coords_count": valid_coords,
            "avg_rating": round(float(pd.to_numeric(df["rating"], errors="coerce").mean()), 2) if not df.empty else 0.0,
            "total_votes": int(pd.to_numeric(df["votes"], errors="coerce").fillna(0).sum()) if "votes" in df.columns else 0,
            "top_cities": df["city"].value_counts().head(8).reset_index().rename(columns={"index": "city", "city": "city", "count": "restaurants"}),
            "top_cuisines": cuisine_series.reset_index().rename(columns={"cuisines": "cuisine", "count": "restaurants"}),
        }

    def search_restaurants(self, params: SearchParams, sort_by: str = "rating") -> pd.DataFrame:
        if self.using_mysql and self.engine is not None:
            return self._search_mysql(params, sort_by)

        df = self._get_base_df()
        if params.country and params.country != "All":
            df = df[df["country"].str.lower() == params.country.lower()]
        if params.city and params.city != "All":
            df = df[df["city"].str.lower() == params.city.lower()]
        if params.locality:
            df = df[df["locality"].str.contains(params.locality, case=False, na=False)]
        if params.cuisines:
            pattern = "|".join(re.escape(c) for c in params.cuisines)
            df = df[df["cuisines"].str.contains(pattern, case=False, na=False)]
        if params.min_rating is not None:
            df = df[df["rating"] >= params.min_rating]
        if params.min_cost_for_two is not None and params.min_cost_for_two > 0:
            if df["currency"].nunique() <= 1:
                df = df[df["avg_cost_for_two"] >= params.min_cost_for_two]
        if params.max_cost_for_two is not None and params.max_cost_for_two > 0:
            if df["currency"].nunique() <= 1:
                df = df[df["avg_cost_for_two"] <= params.max_cost_for_two]
        if params.search_query:
            df = df[df["name"].str.contains(params.search_query, case=False, na=False)]

        sort_map = {
            "rating": ("rating", False),
            "votes": ("votes", False),
            "cost_low": ("avg_cost_for_two", True),
            "cost_high": ("avg_cost_for_two", False),
            "name": ("name", True),
        }
        col, asc = sort_map.get(sort_by, ("rating", False))
        if col not in df.columns:
            col = "rating"
        return df.sort_values(by=col, ascending=asc).reset_index(drop=True)

    def _search_mysql(self, params: SearchParams, sort_by: str) -> pd.DataFrame:
        clauses = ["1=1"]
        bind: Dict[str, Any] = {}
        if params.country and params.country != "All":
            clauses.append("country = :country")
            bind["country"] = params.country
        if params.city and params.city != "All":
            clauses.append("city = :city")
            bind["city"] = params.city
        if params.locality:
            clauses.append("locality LIKE :locality")
            bind["locality"] = f"%{params.locality}%"
        if params.cuisines:
            cuisine_clauses = []
            for idx, c in enumerate(params.cuisines):
                key = f"cuisine_{idx}"
                cuisine_clauses.append(f"cuisines LIKE :{key}")
                bind[key] = f"%{c}%"
            clauses.append(f"({' OR '.join(cuisine_clauses)})")
        if params.min_rating is not None:
            clauses.append("rating >= :min_rating")
            bind["min_rating"] = params.min_rating
        if params.max_cost_for_two is not None and params.max_cost_for_two > 0:
            clauses.append("avg_cost_for_two <= :max_cost")
            bind["max_cost"] = params.max_cost_for_two
        if params.search_query:
            clauses.append("name LIKE :q")
            bind["q"] = f"%{params.search_query}%"

        allowed_sorts = {
            "rating": "rating DESC",
            "votes": "votes DESC",
            "cost_low": "avg_cost_for_two ASC",
            "cost_high": "avg_cost_for_two DESC",
            "name": "name ASC",
        }
        order_sql = allowed_sorts.get(sort_by, "rating DESC")
        sql = text(f"SELECT * FROM gold_restaurant_search WHERE {' AND '.join(clauses)} ORDER BY {order_sql}")
        return pd.read_sql(sql, self.engine, params=bind)

    def find_nearby_restaurants(
        self,
        lat: float,
        lon: float,
        radius_km: float = 5.0,
        exclude_name: Optional[str] = None,
        limit: int = 12,
    ) -> pd.DataFrame:
        """Return restaurants within straight-line radius_km using Haversine distance."""
        if not is_valid_coord(lat, lon):
            return pd.DataFrame()
        df = self._get_base_df().copy()
        if df.empty or not {"latitude", "longitude"}.issubset(df.columns):
            return pd.DataFrame()

        df["latitude"] = pd.to_numeric(df["latitude"], errors="coerce")
        df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce")
        df = df.dropna(subset=["latitude", "longitude"])
        df = df[~((df["latitude"] == 0.0) & (df["longitude"] == 0.0))]

        df["straight_line_km"] = df.apply(
            lambda r: round(haversine_km(lat, lon, float(r["latitude"]), float(r["longitude"])), 2),
            axis=1,
        )
        nearby = df[df["straight_line_km"] <= radius_km]
        if exclude_name:
            nearby = nearby[nearby["name"].str.lower() != exclude_name.lower()]
        return nearby.sort_values(by=["straight_line_km", "rating"], ascending=[True, False]).head(limit).reset_index(drop=True)

    def get_similar_restaurants(self, row: Dict[str, Any], limit: int = 6) -> pd.DataFrame:
        """Recommend similar restaurants based on shared cuisines, same city, and rating proximity."""
        df = self._get_base_df().copy()
        if df.empty:
            return pd.DataFrame()
        target_name = str(row.get("name", "")).lower()
        target_city = str(row.get("city", "")).lower()
        target_cuisines = {c.strip().lower() for c in str(row.get("cuisines", "")).split(",") if c.strip()}

        df = df[df["name"].astype(str).str.lower() != target_name]
        if target_city:
            city_df = df[df["city"].astype(str).str.lower() == target_city]
            if not city_df.empty:
                df = city_df

        def score_row(r: pd.Series) -> Tuple[int, float]:
            r_cuis = {c.strip().lower() for c in str(r.get("cuisines", "")).split(",") if c.strip()}
            overlap = len(target_cuisines & r_cuis)
            rating_val = float(r.get("rating", 0.0)) if pd.notna(r.get("rating")) else 0.0
            return overlap, rating_val

        scores = df.apply(score_row, axis=1)
        df["shared_cuisines"] = [s[0] for s in scores]
        df = df[df["shared_cuisines"] > 0]
        return df.sort_values(by=["shared_cuisines", "rating"], ascending=[False, False]).head(limit).reset_index(drop=True)

    def get_destination_profile(self, country: str) -> Dict[str, Any]:
        """Return curated cultural identity + real database statistics for a country."""
        df = self._get_base_df()
        sub = df[df["country"] == country].copy()
        culture = DESTINATION_CULTURE.get(country, DEFAULT_CULTURE)
        cuis_series = sub["cuisines"].dropna().astype(str).str.split(",").explode().str.strip()
        top_cuisines = cuis_series[cuis_series != ""].value_counts().head(8).index.tolist() if not cuis_series.empty else []
        top_cities = sub["city"].dropna().value_counts().head(6).index.tolist() if "city" in sub.columns else []
        return {
            "country": country,
            "culture": culture,
            "df": sub,
            "count": len(sub),
            "city_count": sub["city"].nunique() if "city" in sub.columns else 0,
            "avg_rating": round(float(pd.to_numeric(sub["rating"], errors="coerce").mean()), 2) if not sub.empty else 0.0,
            "top_cuisines": top_cuisines,
            "top_cities": top_cities,
        }

    def get_pipeline_telemetry(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        if self.using_mysql and self.engine is not None:
            try:
                runs = pd.read_sql(text("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT 20"), self.engine)
                quarantine = pd.read_sql(text("SELECT * FROM data_quality_issues LIMIT 100"), self.engine)
                return runs, quarantine
            except Exception:
                pass
        return pd.DataFrame(SAMPLE_PIPELINE_RUNS), pd.DataFrame(SAMPLE_QUARANTINE)


# ---------------------------------------------------------
# 6. Action-Oriented AI Concierge (Hugging Face + Fallback)
# ---------------------------------------------------------
class NLPService:
    def __init__(self, service: RestaurantService):
        self.service = service
        self.hf_token = get_secret("HF_TOKEN")
        self.model_id = get_secret("HF_MODEL_ID", "Qwen/Qwen3.8-27B")
        self.client = InferenceClient(api_key=self.hf_token) if (InferenceClient and self.hf_token) else None

    def parse_prompt(self, user_prompt: str) -> Tuple[SearchParams, str]:
        """Backward-compatible parameter extractor. Never executes raw SQL."""
        if self.client is not None:
            try:
                return self._parse_with_huggingface(user_prompt), f"Hugging Face LLM ({self.model_id})"
            except Exception as e:
                return self._parse_rule_based(user_prompt), f"Rule-Based Fallback (HF Error: {e})"
        return self._parse_rule_based(user_prompt), "Rule-Based Fallback Parser"

    def _parse_with_huggingface(self, user_prompt: str) -> SearchParams:
        opts = self.service.get_filter_options()
        cities = self.service.get_cities()
        system_prompt = (
            "You are a restaurant search parameter extractor. Return ONLY valid JSON matching this schema:\n"
            '{"country": str|null, "city": str|null, "locality": str|null, "cuisines": [str], '
            '"min_rating": float|null, "max_cost_for_two": float|null, "needs_clarification": str|null}\n'
            f"Valid countries: {opts['countries']}\n"
            f"Valid cities: {cities[:120]}\n"
            f"Valid cuisines: {opts['cuisines'][:120]}\n"
            "Do not invent values. Do not output markdown or explanations."
        )
        response = self.client.chat.completions.create(
            model=self.model_id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=800,
            temperature=0.0,
        )
        raw_content = response.choices[0].message.content.strip()
        raw_content = re.sub(r"<think>.*?</think>", "", raw_content, flags=re.DOTALL).strip()
        json_match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if not json_match:
            raise ValueError("No JSON object returned by LLM")
        data = json.loads(json_match.group(0))
        return SearchParams(**data)

    def _parse_rule_based(self, user_prompt: str) -> SearchParams:
        text_lower = user_prompt.lower()
        df = self.service._get_base_df()

        def match_whole_word(values):
            for v in sorted([str(x) for x in values if pd.notna(x)], key=len, reverse=True):
                if re.search(rf"\b{re.escape(v.lower())}\b", text_lower):
                    return v
            return None

        country = match_whole_word(df["country"].dropna().unique())
        city = match_whole_word(df["city"].dropna().unique())
        locality = match_whole_word(df["locality"].dropna().unique())

        all_cuisines = {c.strip() for row in df["cuisines"].dropna() for c in str(row).split(",") if c.strip()}
        cuisines = [c for c in all_cuisines if re.search(rf"\b{re.escape(c.lower())}\b", text_lower)]

        rating_match = re.search(r"(?:above|over|rating\s*[>=]*|at least)\s*(\d(?:\.\d)?)", text_lower)
        min_rating = float(rating_match.group(1)) if rating_match else None

        cost_match = re.search(r"(?:under|below|max|less than)\s*(\d+(?:\.\d+)?)", text_lower)
        max_cost = float(cost_match.group(1)) if cost_match else None

        clarification = None
        if not any([country, city, locality, cuisines, min_rating, max_cost]):
            clarification = "I couldn't match a known city, cuisine, or budget. Try e.g. 'Italian restaurants in Cairo above 4.2 under 700'."

        return SearchParams(
            country=country,
            city=city,
            locality=locality,
            cuisines=cuisines,
            min_rating=min_rating,
            max_cost_for_two=max_cost,
            needs_clarification=clarification,
        )

    def concierge_respond(
        self,
        user_prompt: str,
        last_results: Optional[pd.DataFrame] = None,
        selected_restaurant: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Action-oriented AI orchestrator: classifies intent, validates via Pydantic, executes approved tools."""
        text_lower = user_prompt.lower()
        params, engine_used = self.parse_prompt(user_prompt)

        # 1. Detect high-level action intent
        if any(w in text_lower for w in ["itinerary", "journey", "food trip", "one-day", "route", "plan a"]):
            intent = "itinerary"
        elif any(w in text_lower for w in ["compare", "cheapest", "best value", "which one", "most affordable"]):
            intent = "compare"
        elif any(w in text_lower for w in ["nearby", "around", "closest", "near me", "within"]):
            intent = "nearby"
        elif any(w in text_lower for w in ["culture", "traditional", "what should i try", "special about"]):
            intent = "culture"
        else:
            intent = "search"

        sort_by = "cost_low" if any(w in text_lower for w in ["cheap", "affordable", "budget", "cheapest"]) else "rating"
        stop_match = re.search(r"\b([2-6])\s*(?:stops|restaurants|places)\b", text_lower)
        stop_count = int(stop_match.group(1)) if stop_match else 3

        action = ConciergeAction(
            intent=intent,
            params=params,
            stop_count=stop_count,
            sort_by=sort_by,
            target_country=params.country,
            target_city=params.city,
        )

        # 2. Execute approved backend tools
        if action.intent == "compare" and last_results is not None and not last_results.empty:
            comp_df = last_results.copy()
            if sort_by == "cost_low" and comp_df["currency"].nunique() <= 1:
                comp_df = comp_df.sort_values(by="avg_cost_for_two", ascending=True)
            else:
                comp_df = comp_df.sort_values(by="rating", ascending=False)
            top = comp_df.head(4).reset_index(drop=True)
            best = top.iloc[0]
            msg = (
                f"Compared your previous {len(last_results)} results. "
                f"**{best['name']}** ({best['city']}) leads with ★ {best['rating']} "
                f"and {int(best['avg_cost_for_two']):,} {best['currency']} for two."
            )
            return {"intent": "compare", "engine": engine_used, "params": params, "message": msg, "results": top, "itinerary": None, "culture": None}

        if action.intent == "nearby" and selected_restaurant is not None:
            lat, lon = selected_restaurant.get("latitude"), selected_restaurant.get("longitude")
            if is_valid_coord(lat, lon):
                nearby_df = self.service.find_nearby_restaurants(float(lat), float(lon), radius_km=5.0, exclude_name=selected_restaurant.get("name"))
                msg = f"Found **{len(nearby_df)}** restaurants within **5 km (straight-line distance)** of **{selected_restaurant.get('name')}**."
                return {"intent": "nearby", "engine": engine_used, "params": params, "message": msg, "results": nearby_df, "itinerary": None, "culture": None}

        if action.intent == "culture" and params.country:
            profile = self.service.get_destination_profile(params.country)
            top_df = profile["df"].sort_values(by="rating", ascending=False).head(6).reset_index(drop=True)
            c = profile["culture"]
            msg = (
                f"**{params.country} Culinary Identity:** {c['tagline']} "
                f"Signature traditions include {', '.join(c['signature_dishes'][:4])}. "
                f"Below are top-rated places in our dataset ({profile['count']:,} indexed)."
            )
            return {"intent": "culture", "engine": engine_used, "params": params, "message": msg, "results": top_df, "itinerary": None, "culture": profile}

        if action.intent == "itinerary":
            params.needs_clarification = None
            candidates = self.service.search_restaurants(params, sort_by=action.sort_by)
            if candidates.empty:
                return {"intent": "itinerary", "engine": engine_used, "params": params, "message": "No matching restaurants found to build an itinerary. Try specifying a city like Cairo, Dubai, or London.", "results": pd.DataFrame(), "itinerary": None, "culture": None}
            # Pick diverse stops by cuisine where possible
            stops = candidates.drop_duplicates(subset=["cuisines"]).head(action.stop_count)
            if len(stops) < action.stop_count:
                stops = candidates.head(action.stop_count)
            stops = stops.reset_index(drop=True)
            loc_label = params.city or params.country or "your selected markets"
            msg = f"Built a **{len(stops)}-stop food journey** in **{loc_label}** using top-rated verified restaurants. You can send this directly to the Food Journey Planner or view it on the Map."
            return {"intent": "itinerary", "engine": engine_used, "params": params, "message": msg, "results": stops, "itinerary": stops, "culture": None}

        # Default: validated restaurant search
        if params.needs_clarification:
            return {"intent": "search", "engine": engine_used, "params": params, "message": params.needs_clarification, "results": pd.DataFrame(), "itinerary": None, "culture": None}

        results = self.service.search_restaurants(params, sort_by=action.sort_by)
        msg = f"Found **{len(results):,}** matching restaurants." if not results.empty else "No restaurants matched those exact filters. Try relaxing the rating or cuisine."
        return {"intent": "search", "engine": engine_used, "params": params, "message": msg, "results": results, "itinerary": None, "culture": None}