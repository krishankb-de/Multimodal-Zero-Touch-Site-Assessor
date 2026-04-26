# Multimodal Zero-Touch Site Assessor

An agentic AI system that converts homeowner-provided media — a roofline video, an electrical panel photo, and a utility bill PDF — into a complete, engineering-grade solar + heat pump proposal, without a physical site visit.

---

## What it does

A homeowner uploads three files through a web interface:

| Input | What it tells the system |
|---|---|
| Roofline video (MP4/MOV) | Roof geometry: face count, tilt, azimuth, usable area, obstacles; building envelope dimensions |
| Electrical panel photo (JPG/PNG) | Panel amperage, phases, breaker inventory, spare ways |
| Utility bill PDF | Annual/monthly consumption, tariff rate, heating fuel, EV presence |
| `location` field (optional) | Address or city name → location-specific historical weather data |

The system runs an 8-agent AI pipeline and produces:

- Solar PV system design (kWp, panel count, string config)
- Battery storage recommendation
- Heat pump sizing (DIN EN 12831)
- 3D roof mesh (when reconstruction succeeds)
- Financial summary (cost, annual savings, payback period)
- Single-line electrical diagram (SLD)
- **Location-specific weather analysis** (when `location` is provided)
- **Building envelope dimensions** (ridge/eave height, footprint, wall area, volume)
- **Visual installation plan** (panel grid on building outline, when dimensions available)
- Human installer sign-off workflow

No proposal reaches the customer without an installer approving it.

---

## Architecture

```
                       ┌─────────────────────────────────────┐
 Video ──►             │           INGESTION AGENT            │
 Photo ──►  ──────────►│  Gemini 1.5 Pro (multimodal)        │
 PDF   ──►             │  Frame extraction → 3D reconstruction│
                       └──────────────┬──────────────────────┘
                                      │ SpatialData / ElectricalData / ConsumptionData
                              ┌───────▼───────┐
                              │ SAFETY GATE 1 │  (validates every handoff)
                              └───────┬───────┘
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
    ┌─────────▼──────┐   ┌────────────▼───────┐  ┌──────────▼─────────┐
    │  STRUCTURAL    │   │   THERMODYNAMIC    │  │   ELECTRICAL       │
    │  Panel layout  │   │   DIN EN 12831     │  │   Panel assessment │
    │  Shading sim   │   │   Heat load calc   │  │   Upgrade check    │
    └────────┬───────┘   └─────────┬──────────┘  └──────────┬─────────┘
             │                     │                         │
    ┌─────────▼──────┐             │                         │
    │  BEHAVIORAL    │             │                         │
    │  Occupancy     │             │                         │
    │  Battery sizing│             │                         │
    └────────┬───────┘             │                         │
             └─────────────────────┼─────────────────────────┘
                                   │ ModuleLayout / ThermalLoad / ElectricalAssessment / BehavioralProfile
                           ┌───────▼───────┐
                           │ SAFETY GATE 2 │
                           └───────┬───────┘
                                   │
                         ┌─────────▼──────────┐
                         │  DESIGN SYNTHESIS  │
                         │  Pioneer SLM       │
                         │  Reonic dataset    │
                         │  SLD generator     │
                         └─────────┬──────────┘
                                   │ FinalProposal
                           ┌───────▼───────┐
                           │ SAFETY GATE 3 │
                           └───────┬───────┘
                                   │
                      ┌────────────▼───────────┐
                      │  HUMAN INSTALLER       │
                      │  Sign-off (mandatory)  │
                      └────────────────────────┘
```

The Safety Agent intercepts **every** handoff between agents. No proposal bypasses human review — this is enforced in code.

---

## 3D Reconstruction Pipeline

When a roofline video is uploaded, the system attempts 3D mesh reconstruction in four tiers with a hard 90-second time budget:

```
Tier 1  pycolmap Structure-from-Motion (SfM) on keyframes → dense mesh
   ↓ (timeout or failure)
Tier 2  Pioneer SLM geometric inference (stub — pending API confirmation)
   ↓ (failure)
Tier 3  Gemini multi-frame depth estimation → coarse mesh
   ↓ (failure)
Tier 4  Silent 2D-only fallback — pipeline still produces a full proposal
```

The generated `.glb` mesh is served to the frontend and rendered as an interactive 3D viewer.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, Pydantic v2 (strict mode) |
| Frontend | Next.js 14, React 18, TypeScript, Tailwind CSS |
| 3D Viewer | Three.js, @react-three/fiber, @react-three/drei |
| AI (multimodal) | Google Gemini 1.5 Pro via `google-genai` SDK |
| AI (pricing/design) | Pioneer SLM (`deepseek-ai/DeepSeek-V3.1`) |
| 3D Reconstruction | pycolmap (optional), trimesh, OpenCV |
| Layout Engine | Shapely (polygon clipping), custom Sutherland-Hodgman |
| Shading | Hand-rolled sun-path model (Spencer equations) |
| Thermal calc | DIN EN 12831 simplified |
| Validation | JSON Schema Draft 2020-12, Pydantic strict mode |
| Testing | pytest, pytest-asyncio (256 tests) |

---

## Requirements

### System

- **Python 3.12+**
- **Node.js 18+** and **npm** (for the frontend)
- **ffmpeg** installed and on PATH (used by frame extraction)

Install ffmpeg:
```bash
# macOS
brew install ffmpeg

# Ubuntu / Debian
sudo apt install ffmpeg

# Windows (via Scoop)
scoop install ffmpeg
```

### API Keys

| Key | Where to get it | Required for |
|---|---|---|
| `GEMINI_API_KEY` | [Google AI Studio](https://aistudio.google.com/app/apikey) | All video/photo/PDF analysis |
| `PIONEER_API_KEY` | Fastino Labs / Pioneer | Pricing + design synthesis (has rule-based fallback) |

---

## Setup — Step by Step

### 1. Clone the repository

```bash
git clone <repo-url>
cd clean-repo
```

### 2. Create and activate the Python virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate        # macOS / Linux
# .venv\Scripts\activate         # Windows
```

### 3. Install Python dependencies

```bash
pip install -e ".[dev]"
```

### 4. Create your `.env` file

```bash
cp .env.example .env             # if provided, otherwise create manually
```

Edit `.env`:

```env
# Required
GEMINI_API_KEY=your_gemini_api_key_here

# Optional — Pioneer SLM (falls back to rule-based pricing if not set)
PIONEER_API_KEY=your_pioneer_api_key_here
PIONEER_API_URL=https://api.pioneer.ai/v1
PIONEER_MODEL=deepseek-ai/DeepSeek-V3.1

# Optional — defaults shown
GEMINI_MODEL_NAME=gemini-2.5-flash
APP_ENV=development
LOG_LEVEL=DEBUG
DEFAULT_MARKET=DE
DEFAULT_CURRENCY=EUR
REGION=Hamburg

# Optional — 3D reconstruction
RECONSTRUCTION_BUDGET_S=90       # seconds before SfM falls back to next tier
VISION_PROVIDER=gemini           # set to "pioneer" to try Pioneer first
```

### 5. Install frontend dependencies

```bash
cd src/web/frontend
npm install
cd ../../..
```

### 6. Verify everything works

```bash
python -m pytest tests/ --ignore=tests/test_integration_live.py -q
```

Expected: **273 passed**.

---

## Running the Application

You need two terminals.

### Terminal 1 — Backend API

```bash
source .venv/bin/activate
make dev
# or directly:
uvicorn src.web.app:app --reload --host 0.0.0.0 --port 8000
```

API is now at `http://localhost:8000`
Interactive docs at `http://localhost:8000/docs`

### Terminal 2 — Frontend

```bash
cd src/web/frontend
npm run dev
```

Dashboard is now at `http://localhost:3000`

---

## Using the Application

1. Open `http://localhost:3000`
2. Go to the **Upload** page
3. Upload:
   - A roofline video (MP4 or MOV)
   - An electrical panel photo (JPG or PNG)
   - A utility bill PDF
4. Click **Assess** — the pipeline runs (up to ~5 minutes on first run)
5. When complete, you are redirected to the **Proposal** page which shows:
   - 3D roof mesh viewer (if reconstruction succeeded)
   - System design (PV, battery, heat pump)
   - Financial summary
   - Compliance notes
   - Installer sign-off buttons (Approve / Reject)

Sample media files are in `Datasets/Sample_house_video/` and `Datasets/Videos/`.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/assess` | Upload video + photo + bill, run pipeline |
| `GET` | `/api/v1/proposals/{run_id}` | Fetch a generated proposal |
| `POST` | `/api/v1/proposals/{run_id}/signoff` | Approve or reject a proposal |
| `GET` | `/api/v1/artifacts/{run_id}/{filename}` | Stream a reconstruction artifact (mesh.glb, point_cloud.ply, reconstruction.json) |
| `GET` | `/docs` | Auto-generated Swagger UI |

### Example: submit an assessment via curl

```bash
# Without location (backward-compatible — uses static regional climate data)
curl -X POST http://localhost:8000/api/v1/assess \
  -F "video=@path/to/roof.mp4" \
  -F "photo=@path/to/panel.jpg" \
  -F "bill=@path/to/bill.pdf"

# With location (uses historical weather data from Open-Meteo)
curl -X POST http://localhost:8000/api/v1/assess \
  -F "video=@path/to/roof.mp4" \
  -F "photo=@path/to/panel.jpg" \
  -F "bill=@path/to/bill.pdf" \
  -F "location=Berlin, Germany"
```

Response (without location):
```json
{
  "pipeline_run_id": "abc123",
  "status": "completed",
  "mesh_uri": "/api/v1/artifacts/abc123/mesh.glb",
  "point_cloud_uri": null,
  "weather_profile_available": false
}
```

Response (with location):
```json
{
  "pipeline_run_id": "def456",
  "status": "completed",
  "mesh_uri": "/api/v1/artifacts/def456/mesh.glb",
  "point_cloud_uri": null,
  "weather_profile_available": true
}
```

---

## Project Structure

```
clean-repo/
├── src/
│   ├── agents/
│   │   ├── ingestion/          # Video/photo/PDF → structured data
│   │   │   ├── agent.py        # Main entry point (process_video/photo/pdf)
│   │   │   ├── frame_extractor.py   # Keyframe sampling from video
│   │   │   ├── dimension_estimator.py  # ★ Building envelope dimensions from video
│   │   │   ├── reconstruction.py    # 4-tier 3D mesh reconstruction
│   │   │   ├── roof_segmenter.py    # RANSAC plane fitting on mesh
│   │   │   ├── media_handler.py     # File format validation
│   │   │   └── prompts/        # Gemini prompts (video/photo/pdf)
│   │   │       └── dimension_prompt.py  # ★ Dedicated dimension estimation prompt
│   │   ├── structural/         # Solar panel layout engine
│   │   │   ├── agent.py        # Orchestrates layout + shading (★ uses WeatherProfile lat)
│   │   │   ├── layout_engine.py     # 2D bin-pack + 3D polygon clipping
│   │   │   └── shading.py      # Sun-path shading simulation
│   │   ├── thermodynamic/      # Heat load calculation (DIN EN 12831)
│   │   │   ├── agent.py        # ★ Uses WeatherProfile temp + HouseDimensions
│   │   │   └── din_en_12831.py # ★ Dimension-aware transmission/ventilation loss
│   │   ├── electrical/         # Panel assessment + upgrade recommendations
│   │   ├── behavioral/         # Occupancy + battery sizing + TOU arbitrage
│   │   ├── synthesis/          # Final proposal assembly
│   │   │   ├── agent.py        # ★ Uses WeatherProfile irradiance + generates InstallationPlan
│   │   │   ├── pioneer_client.py    # Pioneer SLM pricing API
│   │   │   └── reonic_dataset.py   # Historical project matching
│   │   ├── safety/             # Validation agent (intercepts every handoff)
│   │   │   ├── validator.py    # JSON schema validation (★ WeatherProfile registered)
│   │   │   └── guardrails.py   # Domain-specific safety rules (★ WeatherProfile checks)
│   │   ├── orchestrator/       # Pipeline execution and DAG
│   │   │   └── agent.py        # ★ Runs weather fetch concurrently with ingestion
│   │   └── hems/               # Post-install telemetry reoptimisation
│   ├── common/
│   │   ├── schemas.py          # All Pydantic inter-agent schemas (★ WeatherProfile, HouseDimensions, InstallationPlan)
│   │   ├── config.py           # Environment-based configuration
│   │   ├── artifact_store.py   # Per-run artifact directory management
│   │   ├── vision_provider.py  # Pioneer/Gemini provider abstraction
│   │   ├── climate.py          # Regional irradiance + temperature data (static fallback)
│   │   ├── glb_validator.py    # GLB cross-check against regional models
│   │   └── sld_generator.py    # Single-line diagram generator
│   ├── services/               # ★ New: external service integrations
│   │   └── weather/
│   │       ├── service.py      # ★ Main orchestrator (geocode → fetch → analyze → cache)
│   │       ├── geocoding.py    # ★ Open-Meteo Geocoding API client
│   │       ├── historical.py   # ★ Open-Meteo Archive API client (5yr daily data)
│   │       ├── analysis.py     # ★ Aggregation engine (monthly means, rankings, schedule)
│   │       └── cache.py        # ★ In-memory coordinate-keyed cache
│   └── web/
│       ├── app.py              # FastAPI application
│       ├── routes/
│       │   ├── assess.py       # POST /assess (★ accepts optional location field)
│       │   ├── proposals.py    # GET/POST proposals
│       │   ├── artifacts.py    # GET artifacts (mesh.glb etc.)
│       │   └── installations.py
│       └── frontend/           # Next.js installer dashboard
│           └── src/app/
│               ├── page.tsx            # Proposals list
│               ├── upload/page.tsx     # File upload
│               ├── proposals/[id]/page.tsx  # Proposal detail + sign-off
│               └── components/
│                   └── RoofMeshViewer.tsx   # Interactive 3D GLB viewer
├── tests/                      # 273 unit + integration + property-based tests
│   ├── test_weather_pbt.py             # ★ Property-based tests (Properties 1–8)
│   ├── test_weather_service.py         # ★ Weather service unit tests
│   ├── test_thermodynamic_dimensions.py # ★ Property-based tests (Property 9)
│   ├── test_backward_compatibility.py  # ★ API backward compatibility tests
│   └── test_weather_integration.py     # ★ Full pipeline integration tests
├── Datasets/
│   ├── Exp 3D-Modells/         # Regional reference GLBs (Brandenburg, Hamburg, etc.)
│   ├── Project Data/           # Reonic historical project CSVs
│   ├── Sample_house_video/     # Sample input media
│   └── Videos/
├── artifacts/                  # Generated per-run meshes (auto-created)
├── sld_output/                 # Generated single-line diagrams
├── pyproject.toml
├── Makefile
└── .env                        # Your API keys (never commit this)
```

★ = modified or added by the Weather Intelligence & House Dimensions feature

---

## Make Targets

```bash
make setup          # Create .venv and install all dependencies
make test           # Run full offline test suite (256 tests)
make test-live      # Run live Gemini API tests (needs GEMINI_API_KEY)
make test-live-video VIDEO_PATH=/path/to/roof.mp4
                    # Run full 3D pipeline against a real video
make dev            # Start FastAPI backend on port 8000
make frontend       # Start Next.js frontend on port 3000
make lint           # Run ruff linter
make typecheck      # Run mypy strict type check
make clean          # Remove __pycache__ and build artifacts
```

---

## Safety Guardrails

The Safety Agent enforces these rules on **every** agent handoff. Violations halt the pipeline:

| Rule | Limit | Action |
|---|---|---|
| DC string voltage | ≤ 1000 V | HALT pipeline |
| Roof area density | ≤ 0.22 kWp/m² | REJECT layout |
| Heat pump capacity | 2–50 kW | REJECT thermal calc |
| Battery capacity | 0.5–50 kWh | REJECT sizing |
| COP | 1.0–7.0 | REJECT thermal recommendation |
| Gemini confidence | ≥ 0.6 | FLAG for manual review |
| Human sign-off | always required = true | Cannot be overridden |
| Mesh + 3D polygons | ≥ 80% of faces need vertices when mesh present | REJECT |
| WeatherProfile latitude | 47.0–55.5°N (Germany bbox) | REJECT profile, fall back to static |
| WeatherProfile longitude | 5.5–15.5°E (Germany bbox) | REJECT profile, fall back to static |
| WeatherProfile irradiance | 700–1400 kWh/m²/yr | REJECT profile, fall back to static |
| WeatherProfile monthly arrays | exactly 12 elements each | REJECT profile, fall back to static |
| WeatherProfile quarter rankings | permutation of [1,2,3,4] | REJECT profile, fall back to static |

---

## Optional Dependencies

These unlock additional capability but are not required for the core pipeline:

| Package | Purpose | Install |
|---|---|---|
| `pycolmap` | Structure-from-Motion (Tier 1 3D reconstruction) | `pip install pycolmap` |
| `open3d` | Poisson surface meshing (improves Tier 1 output) | `pip install open3d` |
| `DracoPy` | Decode Draco-compressed regional GLBs for geometry cross-check | `pip install DracoPy` |
| `scipy` | Convex hull for roof face polygon segmentation | `pip install scipy` |

---

## Environment Variables Reference

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | — | **Required.** Google Gemini API key |
| `GEMINI_MODEL_NAME` | `gemini-2.5-flash` | Gemini model to use |
| `PIONEER_API_KEY` | — | Pioneer SLM key (pricing/design) |
| `PIONEER_API_URL` | `https://api.pioneer.ai/v1` | Pioneer API base URL |
| `PIONEER_MODEL` | `deepseek-ai/DeepSeek-V3.1` | Pioneer model name |
| `APP_ENV` | `development` | `development` or `production` |
| `LOG_LEVEL` | `DEBUG` | Python logging level |
| `DEFAULT_MARKET` | `DE` | Market (affects regulatory defaults) |
| `DEFAULT_CURRENCY` | `EUR` | Currency for financials |
| `REGION` | `Hamburg` | Climate region (Brandenburg / Hamburg / North Germany / Ruhr) |
| `RECONSTRUCTION_BUDGET_S` | `90` | Seconds before SfM falls back to next tier |
| `VISION_PROVIDER` | `gemini` | `gemini` or `pioneer` (primary vision model) |

---

## Running Tests

```bash
# All offline tests (no API keys needed)
python -m pytest tests/ --ignore=tests/test_integration_live.py -v

# Specific test files
python -m pytest tests/test_safety_agent.py -v
python -m pytest tests/test_video_3d_pipeline.py -v
python -m pytest tests/test_frame_extractor.py -v

# Weather Intelligence feature tests
python -m pytest tests/test_weather_pbt.py -v           # Property-based tests
python -m pytest tests/test_weather_service.py -v       # Service unit tests
python -m pytest tests/test_thermodynamic_dimensions.py -v  # Heat load PBT
python -m pytest tests/test_backward_compatibility.py -v    # API compatibility
python -m pytest tests/test_weather_integration.py -v       # Pipeline integration

# Live integration tests (requires GEMINI_API_KEY)
GEMINI_API_KEY=your_key python -m pytest tests/test_integration_live.py -v

# Full 3D pipeline against a real video
make test-live-video VIDEO_PATH=Datasets/Sample_house_video/roof.mp4
```

---

## How the Proposal is Priced

1. The Synthesis Agent calls Pioneer SLM with the total kWp, battery kWh, and heat pump kW.
2. Pioneer returns component models and costs grounded in the Reonic historical project dataset (`Datasets/Project Data/`).
3. If Pioneer is unavailable, a rule-based fallback uses market-average prices.
4. Financial summary = hardware cost + electrical upgrade cost; savings = PV yield × tariff + heat pump savings vs gas.

---

## Weather Intelligence & House Dimensions

This feature replaces the static 4-region climate table with location-specific historical weather data and adds building envelope dimension estimation from the roofline video. Both capabilities are **optional and fully backward-compatible** — the pipeline falls back to existing behavior when no location is provided or when estimation fails.

### How it works

```
POST /api/v1/assess
  ├── video + photo + bill  (existing)
  └── location: "Berlin, Germany"  (new, optional)
          │
          ▼
  ┌─────────────────────────────────────────────────────────┐
  │  Stage 1 — runs concurrently                            │
  │                                                         │
  │  Ingestion Agent          Weather Intelligence Service  │
  │  ─────────────────        ────────────────────────────  │
  │  process_video()    ◄──►  1. Geocode location           │
  │    └─ Gemini vision       2. Check in-memory cache      │
  │    └─ Dimension           3. Fetch 5yr historical data  │
  │       Estimator ──►       4. Aggregate → WeatherProfile │
  │       HouseDimensions     5. Cache result               │
  │  process_photo()                                        │
  │  process_pdf()                                          │
  └─────────────────────────────────────────────────────────┘
          │
          ▼
  Safety Gate 1 — validates WeatherProfile (if present)
  • lat/lon within Germany bbox (47–55.5°N, 5.5–15.5°E)
  • all 12 monthly arrays present
  • irradiance in plausible range (700–1400 kWh/m²/yr)
  • quarter_rankings is a permutation of [1,2,3,4]
  • invalid profile → soft failure, falls back to static data
          │
          ▼
  Stage 2 — Domain agents receive WeatherProfile + HouseDimensions
  ┌──────────────────────────────────────────────────────────┐
  │  Structural Agent                                        │
  │  • uses weather_profile.latitude for sun-path shading    │
  │  • uses eave/ridge height for tilt validation            │
  │                                                          │
  │  Thermodynamic Agent                                     │
  │  • uses min(monthly_avg_temperature_c) as design temp    │
  │  • uses estimated_wall_area_m2 for transmission loss     │
  │  • uses estimated_volume_m3 for ventilation loss         │
  │    (replaces roof-area proxy when dimensions available)  │
  └──────────────────────────────────────────────────────────┘
          │
          ▼
  Stage 3 — Synthesis Agent
  • uses annual_irradiance_kwh_m2 instead of static table
  • applies cloud cover correction factor to PV yield
  • generates InstallationPlan (panel grid on building outline)
    when HouseDimensions are available
  • records data source in compliance notes
          │
          ▼
  AssessResponse
  {
    "pipeline_run_id": "...",
    "status": "completed",
    "weather_profile_available": true   ← new field
  }
```

### Submitting a location

Add the optional `location` field to the multipart form:

```bash
curl -X POST http://localhost:8000/api/v1/assess \
  -F "video=@roof.mp4" \
  -F "photo=@panel.jpg" \
  -F "bill=@bill.pdf" \
  -F "location=Berlin, Germany"
```

Any human-readable address, city name, or postal code works. The system geocodes it via the [Open-Meteo Geocoding API](https://open-meteo.com/en/docs/geocoding-api) and validates the result is within Germany.

Without the `location` field the pipeline behaves identically to before — static regional climate data is used and `weather_profile_available` is `false`.

### What the WeatherProfile contains

After geocoding, the service fetches 5 years of daily data from the [Open-Meteo Historical Weather Archive](https://open-meteo.com/en/docs/historical-weather-api) (no API key required) and aggregates it into:

| Field | Description |
|---|---|
| `monthly_sunshine_hours` | Average daily sunshine hours for each of the 12 months |
| `monthly_precipitation_mm` | Average monthly precipitation (mm) |
| `monthly_cloud_cover_pct` | Average monthly cloud cover (%) |
| `monthly_wind_speed_ms` | Average monthly wind speed (m/s) |
| `monthly_avg_temperature_c` | Average monthly ambient temperature (°C) |
| `annual_irradiance_kwh_m2` | Annual PV irradiance derived from shortwave radiation sum |
| `sunny_days_per_year` | Days with sunshine > 6 hours |
| `seasonal_sunshine_hours` | Quarterly averages [Q1, Q2, Q3, Q4] |
| `optimal_installation_quarter` | Best quarter for installation (lowest precip + wind, highest sun) |
| `quarter_rankings` | All 4 quarters ranked best → worst |
| `cleaning_schedule` | Recommended cleaning frequency and months |

### How PV yield improves

Without location:
```
annual_yield = total_kwp × static_irradiance(region) × 0.80 × shading_factor
```

With location:
```
annual_yield = total_kwp × location_irradiance × 0.80 × cloud_correction × shading_factor

cloud_correction = 1.0 − (avg_cloud_cover_pct / 100) × 0.5
# e.g. 50% cloud cover → correction factor 0.75
```

The data source (location-specific or static regional) is recorded in `compliance.regulatory_notes` of every proposal.

### House Dimension Estimation

When a roofline video is processed, the Dimension Estimator sends keyframes to Gemini with a dedicated prompt that instructs the model to use visual scale references (standard door height ≈ 2.1 m, window proportions, garage doors) to estimate:

| Dimension | Description |
|---|---|
| `ridge_height_m` | Highest point of roof above ground |
| `eave_height_m` | Lowest roof edge above ground |
| `footprint_width_m` | Building width |
| `footprint_depth_m` | Building depth |
| `estimated_wall_area_m2` | Total external wall area (derived) |
| `estimated_volume_m3` | Heated building volume (derived) |
| `confidence` | Per-dimension confidence score (0.0–1.0) |

If Gemini cannot determine dimensions from the frames, `house_dimensions` is `null` and the pipeline continues with the existing roof-area proxy for heat load calculations.

When dimensions are available, the Synthesis Agent generates an `InstallationPlan` — a structured JSON object showing panel positions as a coordinate grid relative to the building footprint, included in the `FinalProposal`.

### Fallback behavior

| Scenario | Behavior |
|---|---|
| No `location` field | Static regional climate data, `weather_profile_available: false` |
| Geocoding fails (unknown place) | HTTP 422 returned to caller |
| Location outside Germany | HTTP 422 returned to caller |
| Open-Meteo API unreachable | Soft failure, falls back to static data |
| WeatherProfile fails Safety Gate 1 | Soft failure, falls back to static data |
| Dimension estimation fails | `house_dimensions: null`, roof-area proxy used |

### New files added

```
src/
├── services/
│   └── weather/
│       ├── service.py          # Main orchestrator (geocode → fetch → analyze → cache)
│       ├── geocoding.py        # Open-Meteo Geocoding API client
│       ├── historical.py       # Open-Meteo Archive API client (5yr daily data)
│       ├── analysis.py         # Aggregation engine (monthly means, rankings, schedule)
│       └── cache.py            # In-memory coordinate-keyed cache (2 d.p. precision)
└── agents/
    └── ingestion/
        ├── dimension_estimator.py      # Gemini-based building dimension extraction
        └── prompts/
            └── dimension_prompt.py     # Dedicated Gemini prompt for dimension estimation

tests/
├── test_weather_pbt.py             # Property-based tests (Properties 1–8)
├── test_weather_service.py         # Unit tests for service fallback behavior
├── test_thermodynamic_dimensions.py # Property-based tests (Property 9)
├── test_backward_compatibility.py  # API backward compatibility + schema validation
└── test_weather_integration.py     # Full pipeline integration tests
```

---

## Regions Supported

Climate data (irradiance, design temperatures) and reference 3D models are available for four German regions:

| Region | Design Temp | Irradiance |
|---|---|---|
| Brandenburg | −14 °C | 1050 kWh/m²/yr |
| Hamburg | −12 °C | 960 kWh/m²/yr |
| North Germany | −10 °C | 940 kWh/m²/yr |
| Ruhr | −10 °C | 970 kWh/m²/yr |

Set your region with `REGION=Hamburg` in `.env`. When a `location` is provided at request time, location-specific weather data takes precedence over the static regional table.

---

## License

MIT
