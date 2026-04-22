# ── Map defaults ──────────────────────────────────────────────────────────────
MALAWI_CENTER_LAT   = -13.211
MALAWI_CENTER_LON   = 34.303
MAP_ZOOM            = 5.25
PROVINCE_ZOOM       = 6.5          # default zoom when a province is selected

# ── Province list and slug mapping ────────────────────────────────────────────
PROVINCES = [
    "Central", "Northern", "Southern",
]

# Maps province display name → table slug used in result-table names
PROVINCE_SLUGS: dict = {
    "Central":       "central_region",
    "Northern":      "northern_region",
    "Southern":      "southern_region",
}

# ── Distance-value → km integer for base_dashboard_data_mwi queries ───────────
# The base_dashboard_data_mwi table stores distance_km as integers.
# Walking travel-time bands are stored by their km equivalents (2 km ≈ 30 min).
DISTANCE_KM_MAP: dict = {5: 5, 10: 10, "30min": 2, "1hr": 4}

# ── Marker sizes ──────────────────────────────────────────────────────────────
RADIUS_EXISTING_M   = 8_000
RADIUS_NEW_M        = 14_000

# ── Colours ───────────────────────────────────────────────────────────────────
COLOUR_EXISTING     = "#F97316"   # warm orange  — existing facilities
COLOUR_NEW          = "#FFFFFF"   # white fill   — new / proposed facilities
COLOUR_NEW_RING     = "#0EA5E9"   # sky blue ring — new / proposed facilities

# ── Slider bounds ─────────────────────────────────────────────────────────────
MAX_NEW_FACILITIES  = 50

# ── Fallback accessibility baselines ─────────────────────────────────────────
# Used only when the DB query for base_dashboard_data_mwi fails.
# Primary baseline is always fetched live from the UC table.
BASELINE_ACCESS_PCT      = 79.31   # 10 km — kept for backward compat
BASELINE_ACCESS_PCT_10KM = 79.31
BASELINE_ACCESS_PCT_5KM  = 62.24
BASELINE_ACCESS_PCT_30MIN = 39.52  # 30 min walking (≈ 2 km)
BASELINE_ACCESS_PCT_1HR   = 56.36  # 1 hr  walking (≈ 4 km)