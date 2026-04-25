"""
Unit tests for the FastAPI web layer.

Tests cover:
- File upload with valid and invalid file types
- File size limit enforcement (HTTP 413)
- Proposal retrieval (HTTP 200 and HTTP 404)
- Signoff endpoint with approve and reject actions
- Authentication enforcement (HTTP 401)
- Pipeline failure returns HTTP 422 with validation errors

Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.7, 8.8
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import httpx
from fastapi.testclient import TestClient

from src.agents.orchestrator.agent import PipelineError
from src.common.schemas import (
    BatteryDesign,
    Compliance,
    FinalProposal,
    FinancialSummary,
    HeatPumpDesign,
    HumanSignoff,
    InverterType,
    ProposalMetadata,
    PVDesign,
    SignoffStatus,
    SystemDesign,
)
from src.web.app import app
from src.web.store import proposal_store


# ============================================================================
# Helpers
# ============================================================================


def _make_final_proposal(pipeline_run_id: str | None = None) -> FinalProposal:
    """Build a minimal valid FinalProposal for testing."""
    run_id = pipeline_run_id or str(uuid.uuid4())
    return FinalProposal(
        system_design=SystemDesign(
            pv=PVDesign(
                total_kwp=6.4,
                panel_count=16,
                inverter_type=InverterType.HYBRID.value,
            ),
            battery=BatteryDesign(included=True, capacity_kwh=10.0),
            heat_pump=HeatPumpDesign(included=True, capacity_kw=10.0),
        ),
        financial_summary=FinancialSummary(
            total_cost_eur=25000.0,
            annual_savings_eur=2780.0,
            payback_years=9.0,
        ),
        compliance=Compliance(
            electrical_upgrades=[],
            regulatory_notes=["Human installer sign-off required"],
        ),
        human_signoff=HumanSignoff(required=True, status=SignoffStatus.PENDING),
        metadata=ProposalMetadata(
            version="1.0.0",
            generated_at=datetime.now(timezone.utc),
            pipeline_run_id=run_id,
        ),
    )


def _make_pipeline_error(error_type: str = "agent_exception") -> PipelineError:
    """Build a PipelineError for testing failure paths."""
    return PipelineError(
        pipeline_run_id=str(uuid.uuid4()),
        stage="ingestion",
        agent_name="ingestion",
        error_type=error_type,
        message="Simulated pipeline failure",
        validation_errors=None,
    )


def _make_validation_pipeline_error() -> PipelineError:
    """Build a validation-failure PipelineError."""
    from src.common.schemas import ErrorSeverity, ValidationError as VError
    return PipelineError(
        pipeline_run_id=str(uuid.uuid4()),
        stage="ingestion",
        agent_name="ingestion",
        error_type="validation_failure",
        message="SpatialData failed Safety Gate 1 validation",
        validation_errors=[
            VError(
                code="AREA_INCONSISTENCY",
                message="Total usable area exceeds face areas",
                field="roof.total_usable_area_m2",
                severity=ErrorSeverity.ERROR,
            )
        ],
    )


def _upload_files(
    client: TestClient,
    video_name: str = "roof.mp4",
    photo_name: str = "panel.jpg",
    bill_name: str = "bill.pdf",
    video_content: bytes = b"fake_video",
    photo_content: bytes = b"fake_photo",
    bill_content: bytes = b"fake_bill",
):
    """Helper to POST /api/v1/assess with multipart files."""
    return client.post(
        "/api/v1/assess",
        files={
            "video": (video_name, video_content, "video/mp4"),
            "photo": (photo_name, photo_content, "image/jpeg"),
            "bill": (bill_name, bill_content, "application/pdf"),
        },
    )


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clear_proposal_store():
    """Clear the in-memory store before each test."""
    proposal_store.clear()
    yield
    proposal_store.clear()


@pytest.fixture
def client():
    """Synchronous TestClient for the FastAPI app."""
    return TestClient(app, raise_server_exceptions=False)


# ============================================================================
# Tests: POST /api/v1/assess — file upload
# ============================================================================


class TestAssessEndpoint:
    """Tests for POST /api/v1/assess."""

    def test_successful_upload_returns_pipeline_run_id(self, client):
        """Valid upload with successful pipeline returns pipeline_run_id and status."""
        proposal = _make_final_proposal()
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=proposal),
        ):
            response = _upload_files(client)

        assert response.status_code == 200
        data = response.json()
        assert "pipeline_run_id" in data
        assert data["status"] == "completed"
        assert data["pipeline_run_id"] == proposal.metadata.pipeline_run_id

    def test_successful_upload_stores_proposal(self, client):
        """Successful pipeline run stores the proposal in the store."""
        proposal = _make_final_proposal()
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=proposal),
        ):
            _upload_files(client)

        assert proposal.metadata.pipeline_run_id in proposal_store

    def test_file_size_limit_video_returns_413(self, client):
        """Video file exceeding 100 MB returns HTTP 413."""
        oversized = b"x" * (100 * 1024 * 1024 + 1)  # 100 MB + 1 byte
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=_make_final_proposal()),
        ):
            response = client.post(
                "/api/v1/assess",
                files={
                    "video": ("roof.mp4", oversized, "video/mp4"),
                    "photo": ("panel.jpg", b"photo", "image/jpeg"),
                    "bill": ("bill.pdf", b"bill", "application/pdf"),
                },
            )
        assert response.status_code == 413

    def test_file_size_limit_photo_returns_413(self, client):
        """Photo file exceeding 100 MB returns HTTP 413."""
        oversized = b"x" * (100 * 1024 * 1024 + 1)
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=_make_final_proposal()),
        ):
            response = client.post(
                "/api/v1/assess",
                files={
                    "video": ("roof.mp4", b"video", "video/mp4"),
                    "photo": ("panel.jpg", oversized, "image/jpeg"),
                    "bill": ("bill.pdf", b"bill", "application/pdf"),
                },
            )
        assert response.status_code == 413

    def test_file_size_limit_bill_returns_413(self, client):
        """Bill file exceeding 100 MB returns HTTP 413."""
        oversized = b"x" * (100 * 1024 * 1024 + 1)
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=_make_final_proposal()),
        ):
            response = client.post(
                "/api/v1/assess",
                files={
                    "video": ("roof.mp4", b"video", "video/mp4"),
                    "photo": ("panel.jpg", b"photo", "image/jpeg"),
                    "bill": ("bill.pdf", oversized, "application/pdf"),
                },
            )
        assert response.status_code == 413

    def test_413_error_message_is_descriptive(self, client):
        """HTTP 413 response must include a descriptive error message."""
        oversized = b"x" * (100 * 1024 * 1024 + 1)
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=_make_final_proposal()),
        ):
            response = client.post(
                "/api/v1/assess",
                files={
                    "video": ("roof.mp4", oversized, "video/mp4"),
                    "photo": ("panel.jpg", b"photo", "image/jpeg"),
                    "bill": ("bill.pdf", b"bill", "application/pdf"),
                },
            )
        assert response.status_code == 413
        detail = response.json().get("detail", "")
        assert "100 MB" in detail or "size" in detail.lower() or "video" in detail.lower()

    def test_pipeline_validation_failure_returns_422(self, client):
        """Pipeline validation failure returns HTTP 422 with error details."""
        error = _make_validation_pipeline_error()
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=error),
        ):
            response = _upload_files(client)

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_pipeline_validation_failure_includes_errors(self, client):
        """HTTP 422 response must include the validation errors from the Safety Agent."""
        error = _make_validation_pipeline_error()
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=error),
        ):
            response = _upload_files(client)

        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "errors" in detail
        assert len(detail["errors"]) > 0

    def test_pipeline_agent_exception_returns_500(self, client):
        """Non-validation pipeline failure returns HTTP 500."""
        error = _make_pipeline_error(error_type="agent_exception")
        with patch(
            "src.web.routes.assess.run_pipeline",
            new=AsyncMock(return_value=error),
        ):
            response = _upload_files(client)

        assert response.status_code == 500

    def test_missing_file_returns_422(self, client):
        """Missing required file field returns HTTP 422."""
        response = client.post(
            "/api/v1/assess",
            files={
                "video": ("roof.mp4", b"video", "video/mp4"),
                # photo and bill missing
            },
        )
        assert response.status_code == 422


# ============================================================================
# Tests: GET /api/v1/proposals/{pipeline_run_id}
# ============================================================================


class TestGetProposalEndpoint:
    """Tests for GET /api/v1/proposals/{pipeline_run_id}."""

    def test_get_existing_proposal_returns_200(self, client):
        """GET returns HTTP 200 and the FinalProposal for a known pipeline_run_id."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.get(f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["metadata"]["pipeline_run_id"] == proposal.metadata.pipeline_run_id

    def test_get_nonexistent_proposal_returns_404(self, client):
        """GET returns HTTP 404 for an unknown pipeline_run_id."""
        response = client.get("/api/v1/proposals/nonexistent-id-12345")
        assert response.status_code == 404

    def test_get_proposal_returns_full_proposal_structure(self, client):
        """GET response must include system_design, financial_summary, compliance, human_signoff."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.get(f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}")

        assert response.status_code == 200
        data = response.json()
        assert "system_design" in data
        assert "financial_summary" in data
        assert "compliance" in data
        assert "human_signoff" in data

    def test_get_proposal_human_signoff_required_is_true(self, client):
        """Retrieved proposal must have human_signoff.required = True."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.get(f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}")

        assert response.status_code == 200
        assert response.json()["human_signoff"]["required"] is True

    def test_get_proposal_404_message_is_descriptive(self, client):
        """HTTP 404 response must include a descriptive message."""
        response = client.get("/api/v1/proposals/missing-id")
        assert response.status_code == 404
        assert "detail" in response.json()


# ============================================================================
# Tests: POST /api/v1/proposals/{pipeline_run_id}/signoff
# ============================================================================


class TestSignoffEndpoint:
    """Tests for POST /api/v1/proposals/{pipeline_run_id}/signoff."""

    def test_approve_proposal_returns_200(self, client):
        """Approve action returns HTTP 200 with updated proposal."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "approve"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200

    def test_approve_updates_status_to_approved(self, client):
        """Approve action must update human_signoff.status to 'approved'."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "approve"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["human_signoff"]["status"] == "approved"

    def test_approve_sets_installer_id_and_signed_at(self, client):
        """Approve action must set installer_id and signed_at."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "approve", "installer_id": "installer-42"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["human_signoff"]["installer_id"] == "installer-42"
        assert data["human_signoff"]["signed_at"] is not None

    def test_reject_with_notes_returns_200(self, client):
        """Reject action with notes returns HTTP 200."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "reject", "notes": "Roof area measurements seem off"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["human_signoff"]["status"] == "rejected"
        assert data["human_signoff"]["notes"] == "Roof area measurements seem off"

    def test_reject_without_notes_returns_422(self, client):
        """Reject action without notes must return HTTP 422."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "reject"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 422

    def test_signoff_without_auth_returns_401(self, client):
        """Signoff without Authorization header must return HTTP 401."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "approve"},
            # No Authorization header
        )

        assert response.status_code == 401

    def test_signoff_nonexistent_proposal_returns_404(self, client):
        """Signoff on unknown pipeline_run_id returns HTTP 404."""
        response = client.post(
            "/api/v1/proposals/nonexistent-id/signoff",
            json={"action": "approve"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 404

    def test_signoff_persists_in_store(self, client):
        """Signoff must update the proposal in the store."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "approve"},
            headers={"Authorization": "Bearer test-token"},
        )

        stored = proposal_store[proposal.metadata.pipeline_run_id]
        assert stored.human_signoff.status == SignoffStatus.APPROVED

    def test_signoff_human_signoff_required_remains_true(self, client):
        """human_signoff.required must remain True after signoff."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "approve"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 200
        assert response.json()["human_signoff"]["required"] is True

    def test_invalid_action_returns_422(self, client):
        """Invalid action value (not 'approve' or 'reject') returns HTTP 422."""
        proposal = _make_final_proposal()
        proposal_store[proposal.metadata.pipeline_run_id] = proposal

        response = client.post(
            f"/api/v1/proposals/{proposal.metadata.pipeline_run_id}/signoff",
            json={"action": "delete"},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == 422
