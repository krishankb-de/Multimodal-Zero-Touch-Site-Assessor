const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface AssessResponse {
  pipeline_run_id: string;
  status: string;
}

export async function uploadMedia(
  video: File,
  photo: File,
  bill: File,
): Promise<AssessResponse> {
  const formData = new FormData();
  formData.append("video", video);
  formData.append("photo", photo);
  formData.append("bill", bill);
  const res = await fetch(`${API_URL}/api/v1/assess`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(
      typeof err.detail === "object"
        ? err.detail.message ?? "Assessment failed"
        : err.detail ?? "Assessment failed",
    );
  }
  return res.json();
}

export interface FinalProposal {
  system_design: {
    pv: { total_kwp: number; panel_count: number; inverter_type: string };
    battery: { included: boolean; capacity_kwh: number };
    heat_pump: { included: boolean; capacity_kw: number; type?: string; cop?: number; cylinder_litres?: number };
  };
  financial_summary: {
    total_cost_eur: number;
    annual_savings_eur: number;
    payback_years: number;
  };
  compliance: {
    electrical_upgrades: string[];
    regulatory_notes: string[];
  };
  human_signoff: {
    required: boolean;
    status: "pending" | "approved" | "rejected" | "revision_requested";
    installer_id?: string;
    signed_at?: string;
    notes?: string;
  };
  metadata: {
    pipeline_run_id: string;
    generated_at: string;
    version: string;
  };
}

export async function getProposal(pipelineRunId: string): Promise<FinalProposal> {
  const res = await fetch(`${API_URL}/api/v1/proposals/${pipelineRunId}`);
  if (!res.ok) throw new Error(`Proposal not found: ${pipelineRunId}`);
  return res.json();
}

export async function signoffProposal(
  pipelineRunId: string,
  action: "approve" | "reject",
  notes?: string,
  installerId?: string,
  authToken?: string
): Promise<FinalProposal> {
  const res = await fetch(`${API_URL}/api/v1/proposals/${pipelineRunId}/signoff`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: authToken ? `Bearer ${authToken}` : "Bearer dev-token",
    },
    body: JSON.stringify({ action, notes, installer_id: installerId }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || "Signoff failed");
  }
  return res.json();
}
