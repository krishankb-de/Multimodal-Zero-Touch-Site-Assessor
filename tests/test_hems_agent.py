"""
Tests for the HEMS quarterly adaptive optimizer.

Covers:
- Occupancy drift detection via export-fraction heuristic
- Occupancy drift detection via seasonal ratio (≥ 6 months)
- No-drift path (same occupancy → delta still returned, drift_detected=False)
- ConsumptionData patching (telemetry months replace baseline months)
- OptimizationDelta schema validity
- API endpoints: register → telemetry → reoptimize
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient

from src.agents.hems import agent as hems_agent
from src.common.schemas import (
    BatteryRecommendation,
    BehavioralProfile,
    Breaker,
    BreakerType,
    ConsumptionData,
    Currency,
    ElectricalData,
    IngestionMetadata,
    InstallationRecord,
    MainSupply,
    MonthlyConsumption,
    OccupancyPattern,
    OptimizationDelta,
    OptimizationFrequency,
    OptimizationSchedule,
    SimpleMetadata,
    SourceType,
    Tariff,
    TelemetryPoint,
)
from src.web.app import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_monthly_breakdown(base_kwh: float = 300.0) -> list[MonthlyConsumption]:
    """12 months of uniform consumption."""
    return [MonthlyConsumption(month=m, kwh=base_kwh) for m in range(1, 13)]


def _make_consumption_data(base_kwh: float = 300.0) -> ConsumptionData:
    return ConsumptionData(
        annual_kwh=base_kwh * 12,
        monthly_breakdown=_make_monthly_breakdown(base_kwh),
        tariff=Tariff(currency=Currency.EUR, rate_per_kwh=0.30),
        metadata=IngestionMetadata(
            source_type=SourceType.PDF,
            confidence_score=0.9,
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )


def _make_baseline_profile(occupancy: OccupancyPattern = OccupancyPattern.AWAY_DAYTIME) -> BehavioralProfile:
    return BehavioralProfile(
        occupancy_pattern=occupancy,
        self_consumption_ratio=0.36,
        battery_recommendation=BatteryRecommendation(
            capacity_kwh=3.0,
            rationale="baseline sizing",
        ),
        optimization_schedule=OptimizationSchedule(
            frequency=OptimizationFrequency.QUARTERLY,
            next_review=date(2026, 7, 1),
        ),
        estimated_annual_savings_eur=800.0,
        metadata=SimpleMetadata(timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc)),
    )


def _ts(month: int, day: int = 15) -> datetime:
    return datetime(2026, month, day, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Unit tests — drift detection
# ---------------------------------------------------------------------------


class TestOccupancyInference:
    def test_high_export_fraction_gives_away_daytime(self):
        readings = [
            TelemetryPoint(timestamp=_ts(4), kwh_imported=50.0, kwh_exported=80.0),
            TelemetryPoint(timestamp=_ts(5), kwh_imported=40.0, kwh_exported=90.0),
        ]
        pattern, reason = hems_agent._infer_occupancy_from_telemetry(readings)
        assert pattern == OccupancyPattern.AWAY_DAYTIME
        assert "export fraction" in reason

    def test_low_export_fraction_gives_home_all_day(self):
        readings = [
            TelemetryPoint(timestamp=_ts(4), kwh_imported=200.0, kwh_exported=10.0),
            TelemetryPoint(timestamp=_ts(5), kwh_imported=180.0, kwh_exported=8.0),
        ]
        pattern, reason = hems_agent._infer_occupancy_from_telemetry(readings)
        assert pattern == OccupancyPattern.HOME_ALL_DAY
        assert "export fraction" in reason

    def test_medium_export_fraction_gives_mixed(self):
        readings = [
            TelemetryPoint(timestamp=_ts(4), kwh_imported=100.0, kwh_exported=30.0),
        ]
        pattern, reason = hems_agent._infer_occupancy_from_telemetry(readings)
        assert pattern == OccupancyPattern.MIXED

    def test_empty_readings_gives_unknown(self):
        pattern, reason = hems_agent._infer_occupancy_from_telemetry([])
        assert pattern == OccupancyPattern.UNKNOWN

    def test_seasonal_ratio_used_when_six_months_available(self):
        # Winter months (Nov-Feb) high, summer months (May-Aug) low → HOME_ALL_DAY
        readings = []
        for month in [1, 2, 5, 6, 11, 12]:
            kwh = 400.0 if month in {1, 2, 11, 12} else 100.0  # ratio = 4.0 > 1.5
            readings.append(TelemetryPoint(timestamp=_ts(month), kwh_imported=kwh, kwh_exported=10.0))
        pattern, reason = hems_agent._infer_occupancy_from_telemetry(readings)
        assert pattern == OccupancyPattern.HOME_ALL_DAY
        assert "seasonal ratio" in reason


# ---------------------------------------------------------------------------
# Unit tests — ConsumptionData patching
# ---------------------------------------------------------------------------


class TestConsumptionPatching:
    def test_telemetry_months_replace_baseline(self):
        baseline = _make_consumption_data(base_kwh=300.0)
        readings = [
            TelemetryPoint(timestamp=_ts(1), kwh_imported=500.0, kwh_exported=20.0),
            TelemetryPoint(timestamp=_ts(1, day=25), kwh_imported=100.0, kwh_exported=5.0),  # same month
        ]
        patched = hems_agent._patch_consumption_data(baseline, readings)
        jan = next(m for m in patched.monthly_breakdown if m.month == 1)
        assert jan.kwh == pytest.approx(600.0)  # 500 + 100

    def test_untouched_months_unchanged(self):
        baseline = _make_consumption_data(base_kwh=300.0)
        readings = [TelemetryPoint(timestamp=_ts(6), kwh_imported=250.0, kwh_exported=0.0)]
        patched = hems_agent._patch_consumption_data(baseline, readings)
        feb = next(m for m in patched.monthly_breakdown if m.month == 2)
        assert feb.kwh == pytest.approx(300.0)

    def test_annual_kwh_recalculated(self):
        baseline = _make_consumption_data(base_kwh=300.0)  # 3600 annual
        readings = [TelemetryPoint(timestamp=_ts(1), kwh_imported=600.0, kwh_exported=0.0)]
        patched = hems_agent._patch_consumption_data(baseline, readings)
        assert patched.annual_kwh == pytest.approx(3900.0)


# ---------------------------------------------------------------------------
# Unit tests — full HEMS run
# ---------------------------------------------------------------------------


class TestHEMSAgentRun:
    def test_drift_detected_when_occupancy_changes(self):
        baseline_consumption = _make_consumption_data()
        # Baseline: away_daytime. Telemetry shows high self-consumption → home_all_day
        baseline_profile = _make_baseline_profile(OccupancyPattern.AWAY_DAYTIME)
        readings = [
            TelemetryPoint(timestamp=_ts(m), kwh_imported=200.0, kwh_exported=5.0)
            for m in [1, 2, 3]
        ]
        delta = hems_agent.run(
            installation_id="test-install-01",
            baseline_consumption=baseline_consumption,
            baseline_profile=baseline_profile,
            readings=readings,
        )
        assert isinstance(delta, OptimizationDelta)
        assert delta.drift_detected is True
        assert delta.old_occupancy == OccupancyPattern.AWAY_DAYTIME
        assert delta.new_occupancy == OccupancyPattern.HOME_ALL_DAY

    def test_no_drift_when_occupancy_matches(self):
        baseline_consumption = _make_consumption_data()
        baseline_profile = _make_baseline_profile(OccupancyPattern.AWAY_DAYTIME)
        # High export fraction → still away_daytime
        readings = [
            TelemetryPoint(timestamp=_ts(m), kwh_imported=50.0, kwh_exported=90.0)
            for m in [4, 5, 6]
        ]
        delta = hems_agent.run(
            installation_id="test-install-02",
            baseline_consumption=baseline_consumption,
            baseline_profile=baseline_profile,
            readings=readings,
        )
        assert delta.drift_detected is False

    def test_delta_fields_populated(self):
        baseline_consumption = _make_consumption_data()
        baseline_profile = _make_baseline_profile(OccupancyPattern.AWAY_DAYTIME)
        readings = [
            TelemetryPoint(timestamp=_ts(m), kwh_imported=200.0, kwh_exported=5.0)
            for m in [1, 2, 3]
        ]
        delta = hems_agent.run(
            installation_id="test-install-03",
            baseline_consumption=baseline_consumption,
            baseline_profile=baseline_profile,
            readings=readings,
        )
        assert delta.old_battery_kwh == pytest.approx(3.0)
        assert delta.new_battery_kwh > 0
        assert delta.battery_delta_kwh == pytest.approx(delta.new_battery_kwh - delta.old_battery_kwh, abs=1e-3)
        assert delta.new_profile is not None
        assert delta.optimized_at is not None


# ---------------------------------------------------------------------------
# API endpoint tests
# ---------------------------------------------------------------------------


BASELINE_CONSUMPTION_PAYLOAD = {
    "annual_kwh": 3600.0,
    "monthly_breakdown": [{"month": m, "kwh": 300.0} for m in range(1, 13)],
    "tariff": {"currency": "EUR", "rate_per_kwh": 0.30},
    "metadata": {
        "source_type": "pdf",
        "confidence_score": 0.9,
        "timestamp": "2026-01-01T00:00:00Z",
    },
}

BASELINE_PROFILE_PAYLOAD = {
    "occupancy_pattern": "away_daytime",
    "self_consumption_ratio": 0.36,
    "battery_recommendation": {
        "capacity_kwh": 3.0,
        "rationale": "baseline sizing",
    },
    "optimization_schedule": {
        "frequency": "quarterly",
        "next_review": "2026-07-01",
    },
    "estimated_annual_savings_eur": 800.0,
    "metadata": {"timestamp": "2026-01-01T00:00:00Z"},
}


class TestInstallationAPI:
    def test_register_installation(self):
        resp = client.post("/api/v1/installations", json={
            "pipeline_run_id": "run-abc-123",
            "baseline_consumption": BASELINE_CONSUMPTION_PAYLOAD,
            "baseline_profile": BASELINE_PROFILE_PAYLOAD,
        })
        assert resp.status_code == 201
        body = resp.json()
        assert "installation_id" in body
        assert body["pipeline_run_id"] == "run-abc-123"

    def test_get_installation(self):
        reg = client.post("/api/v1/installations", json={
            "pipeline_run_id": "run-get-test",
            "baseline_consumption": BASELINE_CONSUMPTION_PAYLOAD,
            "baseline_profile": BASELINE_PROFILE_PAYLOAD,
        })
        iid = reg.json()["installation_id"]
        resp = client.get(f"/api/v1/installations/{iid}")
        assert resp.status_code == 200
        assert resp.json()["installation_id"] == iid

    def test_get_installation_404(self):
        resp = client.get("/api/v1/installations/does-not-exist")
        assert resp.status_code == 404

    def test_ingest_telemetry(self):
        reg = client.post("/api/v1/installations", json={
            "pipeline_run_id": "run-telemetry-test",
            "baseline_consumption": BASELINE_CONSUMPTION_PAYLOAD,
            "baseline_profile": BASELINE_PROFILE_PAYLOAD,
        })
        iid = reg.json()["installation_id"]

        readings = [
            {"timestamp": f"2026-0{m}-15T12:00:00Z", "kwh_imported": 200.0, "kwh_exported": 5.0}
            for m in [1, 2, 3]
        ]
        resp = client.post(f"/api/v1/installations/{iid}/telemetry", json={"readings": readings})
        assert resp.status_code == 200
        body = resp.json()
        assert body["readings_accepted"] == 3
        assert body["total_readings"] == 3

    def test_reoptimize_returns_delta(self):
        reg = client.post("/api/v1/installations", json={
            "pipeline_run_id": "run-reopt-test",
            "baseline_consumption": BASELINE_CONSUMPTION_PAYLOAD,
            "baseline_profile": BASELINE_PROFILE_PAYLOAD,
        })
        iid = reg.json()["installation_id"]

        # High self-consumption → drifts to home_all_day
        readings = [
            {"timestamp": f"2026-0{m}-15T12:00:00Z", "kwh_imported": 200.0, "kwh_exported": 5.0}
            for m in [1, 2, 3]
        ]
        client.post(f"/api/v1/installations/{iid}/telemetry", json={"readings": readings})

        resp = client.post(f"/api/v1/installations/{iid}/reoptimize")
        assert resp.status_code == 200
        delta = resp.json()
        assert delta["drift_detected"] is True
        assert delta["old_occupancy"] == "away_daytime"
        assert delta["new_occupancy"] == "home_all_day"
        assert "battery_delta_kwh" in delta
        assert delta["new_profile"]["battery_recommendation"]["capacity_kwh"] > 0

    def test_reoptimize_without_telemetry_returns_422(self):
        reg = client.post("/api/v1/installations", json={
            "pipeline_run_id": "run-no-telemetry",
            "baseline_consumption": BASELINE_CONSUMPTION_PAYLOAD,
            "baseline_profile": BASELINE_PROFILE_PAYLOAD,
        })
        iid = reg.json()["installation_id"]
        resp = client.post(f"/api/v1/installations/{iid}/reoptimize")
        assert resp.status_code == 422

    def test_optimization_history(self):
        reg = client.post("/api/v1/installations", json={
            "pipeline_run_id": "run-history-test",
            "baseline_consumption": BASELINE_CONSUMPTION_PAYLOAD,
            "baseline_profile": BASELINE_PROFILE_PAYLOAD,
        })
        iid = reg.json()["installation_id"]

        readings = [{"timestamp": "2026-04-15T12:00:00Z", "kwh_imported": 50.0, "kwh_exported": 90.0}]
        client.post(f"/api/v1/installations/{iid}/telemetry", json={"readings": readings})
        client.post(f"/api/v1/installations/{iid}/reoptimize")
        client.post(f"/api/v1/installations/{iid}/reoptimize")

        resp = client.get(f"/api/v1/installations/{iid}/optimizations")
        assert resp.status_code == 200
        assert len(resp.json()) == 2
