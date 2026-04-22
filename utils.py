"""
utils.py
Map, chart, and table helpers for the Zambia Health Access dashboard.

Map approach change:
  Folium + html.Iframe(srcDoc=...) was replaced with plotly go.Scattermap
  rendered as a standard dcc.Graph.  Folium/Leaflet relies on external CDN JS
  that can silently fail inside an iframe srcDoc, leaving a blank white panel.
  go.Scattermap uses the open-street-map tile style which requires no Mapbox
  token and renders reliably as a Plotly component inside Dash.

Chart x-axis:
  X-axis now shows actual total_facilities values from the results table
  (e.g. 80 → 110) rather than a 0-based new-facility count.

2025-07 revision:
  build_standard_map and build_map_figure now accept dynamic center_lat,
  center_lon, and zoom parameters so the map re-centres when the user
  switches between the country view and a province view.
"""
import logging
import pandas as pd
import plotly.graph_objects as go
from typing import Dict, List, Optional, Tuple
from constants import (
    BASELINE_ACCESS_PCT,
    ZAMBIA_CENTER_LAT,
    ZAMBIA_CENTER_LON,
    MAP_ZOOM,
)

# Zambia 2025 population estimate — used for "new people reached" calculation
ZAMBIA_POPULATION = 21_559_131

_CLR_BOUNDARY      = "#F97316"               # orange line
_CLR_BOUNDARY_FILL = "rgba(249,115,22,0.05)" # light beige/orange fill (low opacity)

# ── DMS conversion ────────────────────────────────────────────────────────────
def _boundary_wkt_to_coords(wkt_str: str) -> Tuple[List, List]:
    """
    Parse a WKT POLYGON / MULTIPOLYGON into parallel lat / lon lists suitable
    for a Plotly Scattermap line trace.

    Pure-Python implementation — no shapely or other spatial library needed.
    Ring segments are separated by None sentinels so Plotly draws each ring as
    an independent closed path with no cross-ring connecting artefacts.

    Supported WKT types: POLYGON(...) and MULTIPOLYGON(...)
    Falls back to ([], []) on any parse error.
    """
    import re

    if not wkt_str:
        return [], []
    try:
        lats: List = []
        lons: List = []

        # Extract every coordinate ring — contents of each innermost (…) group
        # that contains actual coordinate pairs (i.e. has at least one comma
        # between two numbers).
        ring_re   = re.compile(r"\(([^()]+)\)")
        coord_re  = re.compile(r"(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")

        for ring_match in ring_re.finditer(wkt_str):
            ring_str = ring_match.group(1)
            pairs    = coord_re.findall(ring_str)
            if len(pairs) < 2:          # skip degenerate / empty rings
                continue
            for lon_s, lat_s in pairs:
                lons.append(float(lon_s))
                lats.append(float(lat_s))
            # None sentinel → Plotly lifts the pen between rings
            lons.append(None)
            lats.append(None)

        return lats, lons
    except Exception as exc:
        logging.warning("Boundary WKT parse failed: %s", exc)
        return [], []


def _to_dms(decimal_deg: float, is_lat: bool) -> str:
    """Convert decimal-degree coordinate to DMS string, e.g. 28° 02' 26.67\" E."""
    direction = (
        ("N" if decimal_deg >= 0 else "S") if is_lat
        else ("E" if decimal_deg >= 0 else "W")
    )
    d       = abs(decimal_deg)
    deg     = int(d)
    minutes = (d - deg) * 60
    min_int = int(minutes)
    sec     = (minutes - min_int) * 60
    return f"{deg}° {min_int:02d}' {sec:05.2f}\" {direction}"


# ── Map (Plotly Scattermap) ───────────────────────────────────────────────────

def build_standard_map(
    existing_df: pd.DataFrame,
    boundary_wkt: Optional[str] = None,
    map_height_px: Optional[int] = None,
    uirevision: str = "standard",
    center_lat: float = ZAMBIA_CENTER_LAT,
    center_lon: float = ZAMBIA_CENTER_LON,
    zoom: float = MAP_ZOOM,
) -> go.Figure:
    """
    Build the baseline map: boundary + existing health facilities only.
    No proposed facilities.  Called on initial load, Clear Map, distance
    switches, and location switches — any state where only ground-truth
    data should be visible.

    center_lat / center_lon / zoom are dynamic so the map re-centres when
    the user switches from the whole-country view to a province view.

    Returns a fully configured go.Figure ready to hand to dcc.Graph.
    """
    fig = go.Figure()

    # ── Boundary fill & border ─────────────────────────────────────────────────
    if boundary_wkt:
        b_lats, b_lons = _boundary_wkt_to_coords(boundary_wkt)
        if b_lats:
            # Subtle fill inside the border
            fig.add_trace(go.Scattermap(
                lat=b_lats, lon=b_lons,
                mode="lines",
                fill="toself",
                fillcolor=_CLR_BOUNDARY_FILL,
                line=dict(color="rgba(0,0,0,0)", width=0),
                hoverinfo="skip",
                showlegend=False,
                name="boundary-fill",
            ))
            # Visible orange border
            fig.add_trace(go.Scattermap(
                lat=b_lats, lon=b_lons,
                mode="lines",
                line=dict(color=_CLR_BOUNDARY, width=2.5),
                hoverinfo="skip",
                showlegend=False,
                name="boundary-line",
            ))

    # ── Existing health facilities ─────────────────────────────────────────────
    if not existing_df.empty:
        hover_text = [
            f"<b>{row.get('name', 'Health Facility')}</b><br>"
            f"{row['lat']:.4f}° N, {row['lon']:.4f}° E"
            for _, row in existing_df.iterrows()
        ]
        fig.add_trace(go.Scattermap(
            lat=existing_df["lat"].tolist(),
            lon=existing_df["lon"].tolist(),
            mode="markers",
            marker=dict(size=7, color="#DC2626", opacity=0.75),
            text=hover_text,
            hoverinfo="text",
            name="Existing Facilities",
        ))

    # ── Layout ─────────────────────────────────────────────────────────────────
    layout_kwargs = dict(
        map_style="open-street-map",
        map=dict(
            center=dict(lat=center_lat, lon=center_lon),
            zoom=zoom,
        ),
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=False,
        paper_bgcolor="white",
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#E2E8F0",
            font=dict(family="Inter, sans-serif", size=12, color="#0F172A"),
        ),
        uirevision=uirevision,
    )
    if map_height_px is not None:
        layout_kwargs["height"] = map_height_px
    else:
        layout_kwargs["autosize"] = True

    fig.update_layout(**layout_kwargs)
    return fig


def build_map_figure(
    existing_df: pd.DataFrame,
    new_df: pd.DataFrame,
    boundary_wkt: Optional[str] = None,
    map_height_px: Optional[int] = None,
    uirevision: str = "map",
    center_lat: float = ZAMBIA_CENTER_LAT,
    center_lon: float = ZAMBIA_CENTER_LON,
    zoom: float = MAP_ZOOM,
) -> go.Figure:
    """
    Build the full optimisation map: existing facilities + proposed facilities.
    Starts from build_standard_map (boundary + existing), then layers proposed
    facilities on top as hollow numbered circles.

    Uses open-street-map tiles (no Mapbox token required).
    Rendered as dcc.Graph — no iframe or external CDN needed.
    """
    # ── Base: boundary + existing facilities ──────────────────────────────────
    fig = build_standard_map(
        existing_df,
        boundary_wkt=boundary_wkt,
        map_height_px=map_height_px,
        uirevision=uirevision,
        center_lat=center_lat,
        center_lon=center_lon,
        zoom=zoom,
    )

    # ── Proposed facilities (hollow numbered circles) ─────────────────────────
    # CRITICAL ARCHITECTURE NOTE — why exactly 3 traces, always:
    #
    # Plotly.react() — the Dash update mechanism for dcc.Graph — works by
    # diffing the old figure against the new one.  For Scattermap (MapLibre),
    # if the NUMBER OF TRACES changes between renders, MapLibre receives a
    # structural change it cannot process via react() and silently keeps the
    # old layers.  The frontend appears frozen even though the callback ran.
    #
    # Fix: exactly 3 proposed-facility traces regardless of N:
    #   Layer A — one marker trace,  all N green outer rings
    #   Layer B — one marker trace,  all N white inner fills  (hollow effect)
    #   Layer C — ONE text trace,    all N number labels
    #
    # Total trace count with boundary = 6, without boundary = 4 — always fixed.

    hover_texts = [
        f"<b>Proposed Facility #{i + 1}</b><br>"
        f"ID: {row.get('new_facility', 'N/A')}<br>"
        f"{row['lat']:.4f}° N, {row['lon']:.4f}° E"
        for i, (_, row) in enumerate(new_df.iterrows())
    ] if not new_df.empty else []

    lats   = new_df["lat"].tolist() if not new_df.empty else []
    lons   = new_df["lon"].tolist() if not new_df.empty else []
    labels = [str(i + 1) for i in range(len(new_df))]

    # Layer A — green outer ring
    fig.add_trace(go.Scattermap(
        lat=lats, lon=lons,
        mode="markers",
        marker=dict(size=26, color="#16A34A", opacity=1.0),
        hovertext=hover_texts,
        hoverinfo="text" if lats else "skip",
        name="Proposed Facilities",
        showlegend=False,
    ))

    # Layer B — white inner fill (creates the hollow look)
    fig.add_trace(go.Scattermap(
        lat=lats, lon=lons,
        mode="markers",
        marker=dict(size=17, color="#FFFFFF", opacity=1.0),
        hoverinfo="skip",
        showlegend=False,
    ))

    # Layer C — ONE text trace with all N number labels (fixed trace count)
    fig.add_trace(go.Scattermap(
        lat=lats, lon=lons,
        mode="text",
        text=labels,
        textfont=dict(color="#16A34A", size=11, family="Inter, sans-serif"),
        textposition="middle center",
        hoverinfo="skip",
        showlegend=False,
    ))

    return fig


# ── Accessibility helpers ─────────────────────────────────────────────────────

def get_new_facility_rows(results_df: pd.DataFrame, n: int) -> pd.DataFrame:
    """Return the first n rows from the optimisation results table."""
    if n == 0 or results_df.empty:
        return pd.DataFrame(columns=results_df.columns)
    return results_df.head(n).copy()


def get_true_baseline(results_df: pd.DataFrame, n_existing: int,
                      fallback_pct: float = BASELINE_ACCESS_PCT) -> float:
    """
    Return the true baseline accessibility % from the results table.

    Looks for the row where total_facilities == n_existing (i.e. zero new
    facilities added).  Falls back to the first row value, then to the
    hardcoded fallback constant.  This must be used instead of the externally-
    supplied baseline_pct wherever the chart or KPI cards need the baseline,
    because the external value can be scoped to the wrong location (e.g. the
    national figure while a province is selected).
    """
    if results_df.empty:
        return fallback_pct
    exact = results_df.loc[
        results_df["total_facilities"] == n_existing,
        "total_population_access_pct",
    ]
    if not exact.empty:
        return float(exact.iloc[0])
    return float(results_df["total_population_access_pct"].iloc[0])


def get_access_pct(
    results_df: pd.DataFrame,
    n: int,
    n_existing: int,
    baseline_pct: float = BASELINE_ACCESS_PCT,
) -> float:
    """
    Look up accessibility % for (n_existing + n) total facilities.
    Returns the true DB baseline when n == 0 (derived from results_df row
    where total_facilities == n_existing), falling back to baseline_pct only
    when results_df is empty.
    """
    if results_df.empty:
        return baseline_pct

    true_base = get_true_baseline(results_df, n_existing, baseline_pct)

    if n == 0:
        return true_base

    target = n_existing + n
    exact  = results_df.loc[
        results_df["total_facilities"] == target,
        "total_population_access_pct",
    ]
    if not exact.empty:
        return float(exact.iloc[0])

    fallback = results_df.head(n)["total_population_access_pct"]
    return float(fallback.iloc[-1]) if not fallback.empty else true_base


def format_delta(delta: float) -> str:
    """Return a signed, 2-decimal string for an accessibility delta."""
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.2f}%"


# ── Plotly accessibility chart ────────────────────────────────────────────────

def build_accessibility_chart(
    results_df: pd.DataFrame,
    n_new: int,
    n_existing: int,
    baseline_pct: float = BASELINE_ACCESS_PCT,
) -> go.Figure:
    """
    Smooth line chart: total_population_access_pct (Y) vs total_facilities (X).

    X-axis uses actual total_facilities column values (e.g. 163 → 222),
    starting from n_existing (baseline) rather than 0.
    The highlighted dot marks the currently selected slider position.

    Baseline anchor fix: the first chart point always uses the true DB baseline
    — the total_population_access_pct at total_facilities == n_existing (i.e.
    zero new facilities added).  We no longer inject the externally-supplied
    baseline_pct as a synthetic first point, because that value can come from
    the wrong scope (e.g. national fallback while a province is selected) and
    produces an abrupt near-vertical spike at the left edge of the chart.

    The externally-supplied baseline_pct is kept only as a last-resort fallback
    when the results table is empty.
    """
    if results_df.empty:
        # Nothing to plot — return a flat baseline line
        x_vals = [n_existing]
        y_vals = [baseline_pct]
        true_baseline = baseline_pct
    else:
        # Derive the true baseline directly from the results table:
        # the row where total_facilities equals n_existing represents the
        # accessibility BEFORE any new facility is added for this province/scope.
        baseline_row = results_df.loc[
            results_df["total_facilities"] == n_existing,
            "total_population_access_pct",
        ]
        if not baseline_row.empty:
            true_baseline = float(baseline_row.iloc[0])
        else:
            # Fallback: use the first row's value (smallest total_facilities)
            true_baseline = float(results_df["total_population_access_pct"].iloc[0])

        x_vals = list(results_df["total_facilities"])
        y_vals = list(results_df["total_population_access_pct"])

        # Prepend baseline anchor only if n_existing is not already the first x
        if x_vals[0] != n_existing:
            x_vals = [n_existing] + x_vals
            y_vals = [true_baseline] + y_vals

    current_x = n_existing + n_new
    current_y = (
        true_baseline
        if n_new == 0
        else get_access_pct(results_df, n_new, n_existing, true_baseline)
    )

    y_min = round(min(y_vals) - 0.5, 1)
    y_max = round(max(y_vals) + 0.5, 1)

    fig = go.Figure()

    # Shaded fill under the curve
    fig.add_trace(go.Scatter(
        x=x_vals,
        y=y_vals,
        fill="tozeroy",
        fillcolor="rgba(79,70,229,0.07)",
        line=dict(color="#4F46E5", width=2.5, shape="spline"),
        mode="lines",
        hovertemplate="Facilities: %{x}<br>Access: %{y:.2f}%<extra></extra>",
        name="Accessibility",
    ))

    # Current selection dot
    fig.add_trace(go.Scatter(
        x=[current_x],
        y=[current_y],
        mode="markers",
        marker=dict(
            color="#4F46E5",
            size=11,
            line=dict(color="white", width=2.5),
        ),
        hovertemplate=f"Facilities: {current_x}<br>Access: {current_y:.2f}%<extra></extra>",
        name="Current",
    ))

    fig.update_layout(
        paper_bgcolor="white",
        plot_bgcolor="white",
        margin=dict(l=48, r=12, t=10, b=44),
        xaxis=dict(
            title=dict(
                text="Number of Health Facilities",
                font=dict(size=10, color="#64748B", family="Inter, sans-serif"),
            ),
            gridcolor="#F1F5F9",
            zeroline=False,
            tickfont=dict(size=9, color="#94A3B8", family="Inter, sans-serif"),
            range=[min(x_vals) - 0.5, max(x_vals) + 0.5],
            tickmode="auto",
            nticks=8,
        ),
        yaxis=dict(
            tickformat=".0f",
            ticksuffix="%",
            gridcolor="#F1F5F9",
            zeroline=False,
            tickfont=dict(size=9, color="#94A3B8", family="Inter, sans-serif"),
            range=[y_min, y_max],
            title=dict(
                text="Accessibility",
                font=dict(size=10, color="#64748B", family="Inter, sans-serif"),
            ),
        ),
        showlegend=False,
        height=195,
        hoverlabel=dict(
            bgcolor="white",
            bordercolor="#E2E8F0",
            font=dict(family="Inter, sans-serif", size=11),
        ),
    )
    return fig


# ── Recommended locations table data ─────────────────────────────────────────

def get_recommended_table_rows(
    results_df: pd.DataFrame,
    n_new: int,
    baseline_pct: float = BASELINE_ACCESS_PCT,
) -> List[Dict]:
    """
    Return a list of row dicts for the Recommended Locations table.
    Keys: no, lon_dms, lat_dms, new_people
    """
    if n_new == 0 or results_df.empty:
        return []

    rows = results_df.head(n_new).reset_index(drop=True)

    # Per-facility accessibility delta → estimate new people reached
    access_vals = [baseline_pct] + list(rows["total_population_access_pct"])
    deltas      = [access_vals[i + 1] - access_vals[i] for i in range(len(rows))]

    result = []
    for i, (_, row) in enumerate(rows.iterrows()):
        result.append({
            "no":         i + 1,
            "lon_dms":    _to_dms(float(row["lon"]), is_lat=False),
            "lat_dms":    _to_dms(float(row["lat"]), is_lat=True),
            "district":   row.get("district") or "—",
            "new_people": max(0, int(deltas[i] / 100 * ZAMBIA_POPULATION)),
        })
    return result