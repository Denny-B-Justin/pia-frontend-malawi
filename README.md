# Malawi Health Facility Accessibility Dashboard

A **Databricks Data App** built with Dash and Folium that visualises the location and population accessibility of health facilities across Malawi. It allows users to simulate the addition of up to 30 optimally-placed new facilities and instantly see the projected improvement in population coverage.

---
World Bank Data Analytics: https://datanalytics.worldbank.org/content/1cc36c57-f12d-4aa8-92a2-196bb0ea605f/

Malawi Geospatial Hub: https://mwi-geowb.hub.arcgis.com/apps/4914d79a40414336998281d0827847a3/explore

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Project Structure](#project-structure)
- [Architecture](#architecture)
- [Data Sources](#data-sources)
- [Prerequisites](#prerequisites)
- [Local Setup](#local-setup)
- [Environment Variables](#environment-variables)
- [Running the App](#running-the-app)
- [Deploying to Databricks Apps](#deploying-to-databricks-apps)
- [How the Optimisation Logic Works](#how-the-optimisation-logic-works)
- [Troubleshooting](#troubleshooting)

---

## Overview

This dashboard is part of the **GoAT (Geospatial Optimisation and Accessibility Tool)** initiative. It connects to Unity Catalog tables in Databricks to visualise:

- All **existing** health facilities in Malawi (~1,258 sites)
- **Proposed new** facility locations ranked by optimisation score
- **Population accessibility** percentage before and after simulated additions

The optimisation is pre-computed using an Integer Linear Programming (ILP) model (Gurobi) and stored in a results table. The app reads and visualises those results interactively.

---

## Features

- **Interactive Folium map** — dark-themed, with layer controls and hover tooltips
- **Orange markers** — existing health facilities
- **White markers (sky-blue ring)** — proposed new facilities
- **KPI scorecards** — existing count, new count, accessibility %, total facilities
- **Slider (0–30)** — simulate adding 1 to 30 new facilities in real time
- **In-memory TTL cache** — Databricks is queried once per session; subsequent interactions are instant
- **OAuth M2M authentication** — service principal credentials for secure production access

---

## Project Structure

```
your-app/
│
├── app.py            # Dash application — layout, callbacks, UI
├── queries.py        # QueryService singleton — Databricks SQL + cache
├── utils.py          # Map builder, KPI formatter, accessibility helpers
├── server.py         # Flask server + LoginManager
├── constants.py      # All project-wide configuration values
│
├── .env              # Local environment variables (never commit this)
├── requirements.txt  # Python dependencies
├── databricks.yml    # Databricks App entrypoint config
└── README.md
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                     Dash Frontend                        │
│                                                          │
│   Header (title + slider)                                │
│   ├── dcc.Store  ──────────────────────────────────┐    │
│   │   store-existing-facilities                    │    │
│   │   store-accessibility-results                  │    │
│   │                                                │    │
│   ├── KPI Scorecards (4 cards)                     │    │
│   ├── Legend + Status Bar                          │    │
│   └── Folium Map (html.Iframe srcDoc)              │    │
│                                                    │    │
└────────────────────────────────────────────────────┼────┘
                                                     │
                         Callbacks (app.py)          │
                                                     ▼
┌──────────────────────────────────────────────────────────┐
│                   QueryService (queries.py)              │
│                                                          │
│   In-memory TTL Cache (5 min, 256 entry max)            │
│   └── Databricks SQL Connector                          │
│       └── Unity Catalog (prd_mega)                      │
│           ├── sgpbpi163.health_facilities_mwi            │
│           └── sgpbpi163.lgu_accessibility_results_mwi  │
└──────────────────────────────────────────────────────────┘
```

**Key design decision — `dcc.Store` pattern:**
Data is fetched once on page load into Dash `dcc.Store` components. All subsequent slider interactions read from the store (in-browser memory), meaning zero additional database queries during a session.

---

## Data Sources

| Table | Schema | Description |
|---|---|---|
| `health_facilities_mwi` | `prd_mega.sgpbpi163` | All existing health facilities — `id`, `lat`, `lon`, `name` |
| `lgu_accessibility_results_mwi` | `prd_mega.sgpbpi163` | Optimisation results — ranked new facility locations with cumulative accessibility % |

**Population data:** WorldPop 2025 constrained 100m raster (pre-processed in `01_extract.ipynb`)

**Facility source:** OpenStreetMap via Overpass API (extracted in `01_extract.ipynb`)

**Optimisation method:** Integer Linear Programming via Gurobi (run in `02_transform.ipynb`)

---

## Prerequisites

- Python **3.10+**
- Access to the Databricks workspace with:
  - Read permission on `prd_mega.sgpbpi163.health_facilities_mwi`
  - Read permission on `prd_mega.sgpbpi163.lgu_accessibility_results_mwi`
  - A running **SQL Warehouse** (serverless recommended)
- Either a **Personal Access Token** (local dev) or **Service Principal** (production)

---

## Local Setup

**1. Clone the repository**
```bash
git clone <your-repo-url>
cd your-app
```

**2. Create and activate a virtual environment**
```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
pip install python-dotenv pyarrow
```

> `python-dotenv` loads your `.env` file automatically.  
> `pyarrow` is required by `databricks-sql-connector` v4.0+ for fetching results.

**4. Create your `.env` file**

Copy the template and fill in your values:
```bash
cp .env.example .env
```
Then edit `.env` — see the [Environment Variables](#environment-variables) section below.

---

## Environment Variables

Create a `.env` file in the project root with the following values:

```dotenv
# ── Databricks connection ──────────────────────────────────────────────────
DATABRICKS_SERVER_HOSTNAME= "YOUR_SERVER_HOSTNAME_HERE"
DATABRICKS_HTTP_PATH= "YOUR_HTTP_PATH_HERE"

DATABRICKS_CLIENT_ID= "YOUR_CLIENT_ID_HERE"
DATABRICKS_CLIENT_SECRET= "YOUR_CLIENT_SECRET_HERE"

# Generate with: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=<your-random-secret-key>

MALAWI_CATALOG=prd_mega
FACILITIES_SCHEMA=sgpbpi163
RESULTS_SCHEMA=sgpbpi163

QUERY_CACHE_TTL_SECONDS=300
QUERY_CACHE_MAX_ENTRIES=256
```

## Running the App

> This is a **Dash** app. Do **not** run it with `streamlit run`. Use `python` directly.

```bash
python app.py
```

Then open your browser at:
```
http://127.0.0.1:8050/
```

You should see the dashboard load with the map of Malawi and all existing facilities as orange dots. Use the slider in the header to simulate adding new facilities.

---
