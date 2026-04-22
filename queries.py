"""
queries.py
Databricks SQL data-access layer for the Malawi Health Access dashboard.

Two new public methods added in this revision:
  • get_base_dashboard_data(location, distance_km)
        → fetches center coords, boundary WKT, baseline access %, and total
          new facilities from base_dashboard_data_mwi for any location
          (country or province) and distance value.

  • get_accessibility_results_for_location(location, distance_km)
        → resolves the correct result table name and fetches MCLP results.
          Handles all 44 tables (11 sessions × 4 km bands).

Table-naming convention (44 tables total):
  Country (Malawi):
    Driving  → lgu_accessibility_results_mwi_5km / _10km
    Walking  → lgu_accessibility_results_mwi_30min / _1hr

  Province (10 × 4):
    Driving  → lgu_accessibility_results_mwi_{slug}_province_5km / _10km
    Walking  → lgu_accessibility_results_mwi_{slug}_province_2km / _4km
               (2 km ≈ 30 min walk; 4 km ≈ 1 hr walk)
"""

import os
import time
import logging
import threading
import pandas as pd
from databricks import sql
from databricks.sdk.core import Config, oauth_service_principal
from typing import Dict, Optional, Tuple

try:
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logging.info("Loaded environment from .env file")
except ImportError:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    logging.warning("python-dotenv not installed — reading env vars from system only")

MALAWI_CATALOG    = os.getenv("MALAWI_CATALOG",    "prd_mega")
FACILITIES_SCHEMA = os.getenv("FACILITIES_SCHEMA", "sgpbpi163")
RESULTS_SCHEMA    = os.getenv("RESULTS_SCHEMA",    "sgpbpi163")

QUERY_CACHE_TTL_SECONDS = int(os.getenv("QUERY_CACHE_TTL_SECONDS", "300"))
QUERY_CACHE_MAX_ENTRIES = int(os.getenv("QUERY_CACHE_MAX_ENTRIES", "256"))

SERVER_HOSTNAME = os.getenv("DATABRICKS_SERVER_HOSTNAME")

_REQUIRED = {
    "DATABRICKS_SERVER_HOSTNAME": SERVER_HOSTNAME,
    "DATABRICKS_HTTP_PATH":       os.getenv("DATABRICKS_HTTP_PATH"),
    "DATABRICKS_CLIENT_ID":       os.getenv("DATABRICKS_CLIENT_ID"),
    "DATABRICKS_CLIENT_SECRET":   os.getenv("DATABRICKS_CLIENT_SECRET"),
}
_missing = [k for k, v in _REQUIRED.items() if not v]
if _missing:
    raise EnvironmentError(
        "\n\nMissing required environment variables:\n"
        + "\n".join(f"  {k}" for k in _missing)
        + "\n\nCreate a .env file in the project folder with:\n"
        + "  DATABRICKS_SERVER_HOSTNAME=adb-xxxx.azuredatabricks.net\n"
        + "  DATABRICKS_HTTP_PATH=/sql/1.0/warehouses/abc123\n"
        + "  DATABRICKS_CLIENT_ID=your-client-id\n"
        + "  DATABRICKS_CLIENT_SECRET=your-client-secret\n"
    )


def credentials_provider():
    """OAuth2 service-principal credentials for Databricks SQL connector."""
    config = Config(
        host          = f"https://{SERVER_HOSTNAME}",
        client_id     = os.getenv("DATABRICKS_CLIENT_ID"),
        client_secret = os.getenv("DATABRICKS_CLIENT_SECRET"),
    )
    return oauth_service_principal(config)


class QueryService:
    """
    Singleton data-access object with in-memory TTL query cache.

    Thread-safe: uses a lock around cache reads/writes so multiple Dash
    worker threads share a single cache without race conditions.
    """

    _instance = None

    @staticmethod
    def get_instance() -> "QueryService":
        if QueryService._instance is None:
            QueryService._instance = QueryService()
        return QueryService._instance

    def __init__(self):
        # {sql_string: (expires_at_epoch, dataframe)}
        self._cache: Dict[str, Tuple[float, pd.DataFrame]] = {}
        self._lock  = threading.Lock()

    # ── Cache helpers ──────────────────────────────────────────────────────────

    def _cache_get(self, key: str) -> Optional[pd.DataFrame]:
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if not entry:
                return None
            expires_at, df = entry
            if now >= expires_at:
                del self._cache[key]
                return None
            return df

    def _cache_set(self, key: str, df: pd.DataFrame) -> None:
        expires_at = time.time() + QUERY_CACHE_TTL_SECONDS
        with self._lock:
            if len(self._cache) >= QUERY_CACHE_MAX_ENTRIES:
                oldest = next(iter(self._cache))
                del self._cache[oldest]
            self._cache[key] = (expires_at, df)

    def clear_cache(self) -> None:
        """Flush the entire query cache."""
        with self._lock:
            self._cache.clear()
        logging.info("Query cache cleared")

    def invalidate_query(self, query: str) -> None:
        """Remove a single query's cached result."""
        with self._lock:
            removed = self._cache.pop(query, None) is not None
        if removed:
            logging.info("Invalidated cache for query: %s", query[:80])

    # ── Core executor ─────────────────────────────────────────────────────────

    def execute_query(self, query: str) -> pd.DataFrame:
        """
        Execute a SQL query against Databricks and return a pandas DataFrame.
        Results are cached for QUERY_CACHE_TTL_SECONDS seconds.
        """
        cached = self._cache_get(query)
        if cached is not None:
            logging.info("CACHE HIT (TTL=%ss): %s…", QUERY_CACHE_TTL_SECONDS, query[:60])
            return cached.copy(deep=True)

        t0 = time.time()
        with sql.connect(
            server_hostname      = SERVER_HOSTNAME,
            http_path            = os.getenv("DATABRICKS_HTTP_PATH"),
            credentials_provider = credentials_provider,
        ) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            rows    = cursor.fetchall()
            columns = [desc[0] for desc in cursor.description]
            df      = pd.DataFrame(rows, columns=columns)

        logging.info(
            "DB MISS — queried in %.2fs: %s…",
            time.time() - t0,
            query[:60],
        )
        self._cache_set(query, df)
        return df.copy(deep=True)

    # ── Domain queries ────────────────────────────────────────────────────────

    def get_existing_facilities(self) -> pd.DataFrame:
        """
        Backward-compat wrapper — returns all national facilities.
        Prefer get_existing_facilities_for_location() for province-scoped views.
        """
        return self.get_existing_facilities_for_location("malawi")

    def get_existing_facilities_for_location(self, location: str = "malawi") -> pd.DataFrame:
        """
        Fetch existing health facilities for the given location.

        Table resolution:
          Malawi (country)  → health_facilities_mwi
          Province          → health_facilities_mwi_osm_{slug}_province

        Each province has its own dedicated OSM-derived facility table so that
        the map only shows facilities relevant to the selected province — no
        country-wide scatter bleed.

        location: "malawi" for the full national table, or a province display
                  name (e.g. "Central", "North-Western") for the province table.
        """
        from constants import PROVINCE_SLUGS

        loc = (location or "malawi").strip()

        if loc.lower() == "malawi":
            table = "health_facilities_mwi"
        else:
            slug  = PROVINCE_SLUGS.get(
                loc,
                loc.lower().replace("-", "").replace(" ", "_"),
            )
            table = f"health_facilities_mwi_osm_{slug}_province"

        logging.info("Fetching existing facilities from table: %s", table)

        query = f"""
            SELECT id, lat, lon, name
            FROM {MALAWI_CATALOG}.{FACILITIES_SCHEMA}.{table}
            ORDER BY id ASC
        """
        df = self.execute_query(query)
        df["lat"]  = pd.to_numeric(df["lat"],  errors="coerce")
        df["lon"]  = pd.to_numeric(df["lon"],  errors="coerce")
        df["name"] = df["name"].fillna("Health Facility")
        logging.info(
            "Fetched %d existing facilities for location='%s' (table=%s)",
            len(df), loc, table,
        )
        return df.dropna(subset=["lat", "lon"]).reset_index(drop=True)

    def get_accessibility_results(self) -> pd.DataFrame:
        """Backward-compat wrapper — fetches the default 10 km Malawi results."""
        return self.get_accessibility_results_for_location("malawi", 10)

    def get_accessibility_results_by_distance(self, distance_km=10) -> pd.DataFrame:
        """Backward-compat wrapper — fetches Malawi-level results for the given distance."""
        return self.get_accessibility_results_for_location("malawi", distance_km)

    # ── NEW: location-aware queries ───────────────────────────────────────────

    def get_base_dashboard_data(
        self,
        location: str = "malawi",
        distance_km=5,
    ) -> dict:
        """
        Fetch map-center coordinates, boundary WKT, baseline access %, and
        total new facilities from base_dashboard_data_mwi for the given
        location and distance value.

        location   : "malawi" for the whole country; province display name
                     (e.g. "Lusaka", "Central") for a province view.
        distance_km: 5 | 10 | "30min" | "1hr"

        Returns a plain dict with keys:
          center_lat, center_lon, zoom, geometry_wkt,
          current_access, total_new_facilities, location
        """
        from constants import (
            DISTANCE_KM_MAP,
            MALAWI_CENTER_LAT, MALAWI_CENTER_LON,
            MAP_ZOOM, PROVINCE_ZOOM,
        )

        # The table stores distance_km as integers; map walk-time bands to km.
        dist_int = DISTANCE_KM_MAP.get(
            distance_km if distance_km is not None else 5, 5
        )

        if location.lower() == "malawi":
            province_clause = "province IS NULL"
            default_zoom    = MAP_ZOOM
        else:
            # Escape single quotes defensively
            safe_province   = location.replace("'", "''")
            province_clause = f"province = '{safe_province}'"
            default_zoom    = PROVINCE_ZOOM

        query = f"""
            SELECT central_lat, central_long, current_access,
                   total_new_facilities, geometry_wkt
            FROM {MALAWI_CATALOG}.{FACILITIES_SCHEMA}.base_dashboard_data_mwi
            WHERE country = 'Malawi'
              AND {province_clause}
              AND distance_km = {dist_int}
            LIMIT 1
        """
        df = self.execute_query(query)

        fallback = {
            "center_lat":          MALAWI_CENTER_LAT,
            "center_lon":          MALAWI_CENTER_LON,
            "zoom":                default_zoom,
            "geometry_wkt":        None,
            "current_access":      62.24,
            "total_new_facilities": 50,
            "location":            location,
        }
        if df.empty:
            logging.warning(
                "base_dashboard_data_mwi returned no rows for location=%s dist=%s",
                location, dist_int,
            )
            return fallback

        row = df.iloc[0]

        def _safe_float(val, default):
            try:
                return float(val) if pd.notna(val) else default
            except (TypeError, ValueError):
                return default

        def _safe_int(val, default):
            try:
                return int(val) if pd.notna(val) else default
            except (TypeError, ValueError):
                return default

        return {
            "center_lat":          _safe_float(row.get("central_lat"),          MALAWI_CENTER_LAT),
            "center_lon":          _safe_float(row.get("central_long"),          MALAWI_CENTER_LON),
            "zoom":                default_zoom,
            "geometry_wkt":        str(row["geometry_wkt"]) if pd.notna(row.get("geometry_wkt")) else None,
            "current_access":      _safe_float(row.get("current_access"),        62.24),
            "total_new_facilities": _safe_int(row.get("total_new_facilities"),   50),
            "location":            location,
        }

    def get_accessibility_results_for_location(
        self,
        location: str = "malawi",
        distance_km=5,
    ) -> pd.DataFrame:
        """
        Fetch MCLP optimisation results for the given location and distance.

        Table-name resolution:
          Malawi country, Driving 5 km   → lgu_accessibility_results_mwi_5km
          Malawi country, Driving 10 km  → lgu_accessibility_results_mwi_10km
          Malawi country, Walking 30 min → lgu_accessibility_results_mwi_2km
          Malawi country, Walking 1 hr   → lgu_accessibility_results_mwi_4km

          Province, Driving 5 km         → lgu_accessibility_results_mwi_{slug}_province_5km
          Province, Driving 10 km        → lgu_accessibility_results_mwi_{slug}_province_10km
          Province, Walking 30 min       → lgu_accessibility_results_mwi_{slug}_province_2km
          Province, Walking 1 hr         → lgu_accessibility_results_mwi_{slug}_province_4km
        """
        from constants import PROVINCE_SLUGS

        loc = (location or "malawi").strip()

        if loc.lower() == "malawi":
            # Country-level: keep explicit 30min / 1hr table names
            suffix_map = {5: "5km", 10: "10km", "30min": "2km", "1hr": "4km"}
            suffix = suffix_map.get(distance_km, "5km")
            table  = f"lgu_accessibility_results_mwi_{suffix}"
        else:
            # Province-level: walking maps to 2 km / 4 km equivalents
            slug       = PROVINCE_SLUGS.get(loc, loc.lower().replace("-", "_").replace(" ", "_"))
            suffix_map = {5: "5km", 10: "10km", "30min": "2km", "1hr": "4km"}
            suffix     = suffix_map.get(distance_km, "5km")
            table      = f"lgu_accessibility_results_mwi_{slug}_province_{suffix}"

        logging.info("Fetching results from table: %s", table)

        query = f"""
            SELECT
                total_facilities,
                new_facility,
                lat,
                lon,
                total_population_access_pct,
                district
            FROM {MALAWI_CATALOG}.{RESULTS_SCHEMA}.{table}
            ORDER BY total_facilities ASC
        """
        df = self.execute_query(query)
        df["lat"] = pd.to_numeric(df["lat"], errors="coerce")
        df["lon"] = pd.to_numeric(df["lon"], errors="coerce")
        df["district"] = df["district"].fillna("—")
        df["total_population_access_pct"] = pd.to_numeric(
            df["total_population_access_pct"], errors="coerce"
        )
        return df.dropna(subset=["lat", "lon"]).reset_index(drop=True)

    def get_user_credentials(self) -> Dict[str, str]:
        query = f"""
            SELECT username, password_hash
            FROM {MALAWI_CATALOG}.{FACILITIES_SCHEMA}.user_credentials
        """
        df = self.execute_query(query)
        return dict(zip(df["username"], df["password_hash"]))

    def get_gadm_boundary_wkt(self) -> Optional[str]:
        """
        Return the Malawi national boundary geometry as a WKT string.
        Kept for backward compatibility; prefer get_base_dashboard_data().
        """
        query = f"""
            SELECT geometry_wkt
            FROM {MALAWI_CATALOG}.{FACILITIES_SCHEMA}.gadm_boundaries_mwi
            LIMIT 1
        """
        df = self.execute_query(query)
        if df.empty:
            logging.warning("gadm_boundaries_mwi returned no rows")
            return None
        val = df["geometry_wkt"].iloc[0]
        if val is None:
            logging.warning("gadm_boundaries_mwi geometry_wkt is NULL")
            return None
        return str(val)