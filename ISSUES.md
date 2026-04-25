# ISSUES — Zero-Touch Site Assessor

Persistent backlog. Update on every session. Audit baseline: 2026-04-25.
Repo ~80% aligned with project description. Architecture & schemas solid; gaps mostly in customer UI, Reonic/Pioneer realism, and post-install adaptive loop.

## Legend
- `[ ]` open · `[~]` in progress · `[x]` done
- Severity: **P0** blocks description claim · **P1** correctness · **P2** polish/stretch

---

## Phase A — Persistence (this session)
- [x] **A0** Create this `ISSUES.md` (P0)
- [x] **A1** Save memory pointer so future Claude sessions read this file first (P0)

## Phase B — Critical description-blocking gaps

- [x] **B1 — Homeowner upload UI** (P0) ✓ 2026-04-25
  - `src/web/frontend/src/app/upload/page.tsx` (new): 4-screen flow — video → panel photo → utility bill → review & submit. Drag-and-drop or click-to-choose per step. Animated step indicator. Loading state while pipeline runs. Success screen with run ID + redirect to `/proposals/{id}`. Stores run ID in localStorage so dashboard picks it up.
  - `src/lib/api.ts`: added `uploadMedia(video, photo, bill)` — multipart POST to `/api/v1/assess`.
  - `src/app/page.tsx`: added "New Assessment" button → `/upload`.
  - TypeScript: 0 errors (`tsc --noEmit` clean).

- [x] **B2 — Reonic dataset integration** (P0) ✓ 2026-04-25
  - Files: `src/agents/synthesis/reonic_dataset.py` (new, ~270 LOC), `pioneer_client.py` (refactored), `agent.py` (threaded consumption_data + spatial_data)
  - 83 historical projects loaded + indexed; kNN over normalized `(log energy_demand, energy_price, has_ev, house_size)` with `heating_existing_type` as hard filter. `summarize_neighbors` returns median capacities + most-common brands.
  - Pioneer prompt now injects top-5 neighbors as few-shot context; output JSON extended with `panel_model / inverter_model / battery_model / heat_pump_model`. Rule-based fallback also pulls brand suggestions from Reonic neighbors.
  - Synthesis populates `PVDesign.panel_model/inverter_model`, `BatteryDesign.model`, `HeatPumpDesign.model` from retrieval; `compliance.regulatory_notes` records Reonic provenance + neighbor count.
  - **Note:** Reonic CSVs have no price column → published-market pricing constants (€1200/kWp, etc.) retained, documented as "informed by Reonic dataset of 2024 German installs". Capacities/brands ARE Reonic-grounded.
  - Tests: `tests/test_reonic_dataset.py` (9 tests, all green). Full suite: 173 passed.

- [x] **B3 — Pioneer SLM realism** (P0) ✓ 2026-04-25 (rolled into B2)
  - `pioneer_client.py` now uses `temperature=0`, `seed=42`, `response_format={"type":"json_object"}`. Reonic neighbors injected as few-shot. `PIONEER_API_URL` env var already in `config.py` for endpoint swap.

- [x] **B4 — HEMS quarterly adaptive optimizer** (P0) ✓ 2026-04-25
  - Files: `src/agents/hems/agent.py` (new), `src/web/routes/installations.py` (new), wired to `src/web/app.py`
  - Endpoints: `POST /api/v1/installations`, `GET /api/v1/installations/{id}`, `POST /api/v1/installations/{id}/telemetry`, `POST /api/v1/installations/{id}/reoptimize`, `GET /api/v1/installations/{id}/optimizations`
  - EEBus-compatible TelemetryPoint schema; drift detection via export-fraction (< 3 months) or winter/summer ratio (≥ 6 months); re-runs Behavioral Agent on patched ConsumptionData; returns OptimizationDelta with battery/savings delta + new BehavioralProfile. In-memory store for installations + OptimizationDelta history.
  - `TelemetryPoint`, `InstallationRecord`, `OptimizationDelta` added to `src/common/schemas.py`.
  - Tests: `tests/test_hems_agent.py` (18 tests, all green). Full suite: 192 passed.

## Phase C — Correctness nits

- [ ] **C1 — Pydantic strict=True** (P1)
  - File: `src/agents/safety/validator.py` (~line 85). CLAUDE.md mandates `strict=True`.
  - Acceptance: `pytest tests/test_safety_agent.py -v` green.

- [ ] **C2 — File existence pre-check** (P1)
  - File: `src/agents/orchestrator/agent.py`
  - Verify Path objects exist + size>0 before Gemini upload; raise `ValidationError` (HTTP 422) with field name.

- [ ] **C3 — Reject overlapping battery TOU windows** (P1)
  - File: `src/agents/safety/guardrails.py`. New error code `BATTERY_WINDOW_OVERLAP`. Currently only warns.

- [ ] **C4 — Geometric obstacle subtraction in layout engine** (P1)
  - File: `src/agents/structural/layout_engine.py`. Replace `ceil(area/panel_area)` with rectangle-clip per face.

- [ ] **C5 — Regional climate + PV yield** (P1)
  - File: `src/common/climate.py` (new). Tables for Brandenburg, Hamburg, Ruhr, North Germany (match GLBs). Wire into thermodynamic agent + synthesis financial calc.
  - Acceptance: synthesis ROI varies by region; design_outdoor_temp_c sourced from table, not config constant.

## Phase D — Test & infra

- [ ] **D1 — Offline E2E pipeline test** (P1)
  - File: `tests/test_pipeline_e2e.py` (new). Mock Gemini with pre-recorded JSON; full DAG → FinalProposal. No API key required.

- [ ] **D2 — Per-agent contract tests** (P2)
  - Round-trip strict-mode validation for every schema (input → output → re-parse).

- [ ] **D3 — Makefile / README quickstart** (P2)
  - `make test`, `make dev`, `make frontend`. Document mandatory `.venv` activation per CLAUDE.md.

## Phase E — Stretch

- [ ] **E1 — GLB-grounded roof validation** (P2)
  - Parse `Datasets/Exp 3D-Modells/*.glb`; cross-check Gemini-extracted faces (area / orientation tolerance).

- [ ] **E2 — Single-line diagram generator** (P2)
  - Compliance section already references `single_line_diagram_ref` — currently dangling.

---

## Non-issues (verified, do not "fix")
- `google-genai>=1.0.0` is the **new** Google GenAI SDK (replaces `google-generativeai`). Code correctly uses `google.genai as genai`.
- All 9 Pydantic models in `src/common/schemas.py` match CLAUDE.md JSON Schemas 1:1, with `extra="forbid"` on every nested model.
- All 10 mandatory safety guardrails are present in `src/agents/safety/guardrails.py`.
- Human sign-off is correctly enforced as un-bypassable.

## Resolved decisions (2026-04-25)
- Pioneer = DeepSeek + Reonic RAG surrogate (no Fastino endpoint).
- HEMS protocol = **EEBus** (European residential standard, matches project's EU market focus).
- Proposals = SQLite DB via SQLAlchemy (replace `src/web/store.py` in-memory dict).
- Execution order: **B2 → B3 → B4 → B1 → C → D → E**.

---

## Session Log
Append a dated entry at the end of each session. Keep it terse.

### 2026-04-25 — Session 1 (audit)
- Audited full repo vs project description. Verdict ~80% aligned.
- Created plan + this ISSUES.md. Phase A done.
- Next: pick B1 vs B2 ordering with user, then start Phase B.

### 2026-04-25 — Session 2 (B2 + B3)
- User decisions logged: Pioneer=DeepSeek+Reonic-RAG, HEMS=EEBus, proposals→DB, B2 first.
- **B2 done.** New `reonic_dataset.py` loader+kNN; Pioneer prompt now Reonic-grounded; synthesis attaches brand/model strings to FinalProposal. 9 new tests pass; 173/173 suite green.
- **B3 done** as part of B2 (deterministic JSON-mode, temp=0, seed=42).
- **B4 done.** EEBus-compatible telemetry ingest + drift detection (export-fraction + seasonal ratio) + Behavioral Agent re-run; 4 API endpoints; `OptimizationDelta` schema; 18 new tests pass; 192/192 suite green.
- **B1 done.** 4-step upload UI (`/upload`); drag-and-drop file zones; `uploadMedia` API helper; links dashboard → upload → proposal detail. TypeScript clean.
- Next: **Phase C** — C1 (Pydantic strict=True), C2 (file pre-check), C3 (battery window overlap reject).
