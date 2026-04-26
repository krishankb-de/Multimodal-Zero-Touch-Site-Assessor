const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "";

export interface AssessResponse {
  pipeline_run_id: string;
  status: string;
  mesh_uri: string | null;
  point_cloud_uri: string | null;
  reconstruction_confidence: number | null;
  weather_profile_available: boolean | null;
}

export interface FinalProposal {
  system_design: {
    pv: {
      total_kwp: number;
      panel_count: number;
      panel_model?: string;
      inverter_type: string;
      inverter_model?: string;
      annual_yield_kwh?: number;
    };
    battery: {
      included: boolean;
      capacity_kwh: number;
      model?: string;
    };
    heat_pump: {
      included: boolean;
      capacity_kw: number;
      type: string;
      model?: string;
      cop?: number;
      cylinder_litres?: number;
    };
    ev_charger?: {
      included: boolean;
      capacity_kw?: number;
    };
  };
  financial_summary: {
    total_cost_eur: number;
    annual_savings_eur: number;
    payback_years: number;
    roi_percent?: number;
  };
  compliance: {
    electrical_upgrades: string[];
    regulatory_notes: string[];
    single_line_diagram_ref?: string;
  };
  human_signoff: {
    required: true;
    status: "pending" | "approved" | "rejected" | "revision_requested";
    installer_id?: string;
    signed_at?: string;
    notes?: string;
  };
  metadata: {
    version: string;
    generated_at: string;
    pipeline_run_id: string;
    all_validations_passed?: boolean;
  };
}

// Module-level singleton — holds the in-flight pipeline request across route navigations.
// Cleared after the result is consumed (or on error) so stale promises don't leak.
let _pending: Promise<AssessResponse> | null = null;

export function startAssessment(formData: FormData): void {
  _pending = fetch(`${API_BASE}/api/v1/assess`, {
    method: "POST",
    body: formData,
  }).then(async (res) => {
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      const msg =
        typeof body.detail === "string"
          ? body.detail
          : (body.detail as { message?: string } | undefined)?.message ?? `HTTP ${res.status}`;
      throw new Error(msg);
    }
    return res.json() as Promise<AssessResponse>;
  });
}

export function consumePendingAssessment(): Promise<AssessResponse> | null {
  const p = _pending;
  _pending = null;
  return p;
}

export async function fetchProposal(runId: string): Promise<FinalProposal> {
  const res = await fetch(`${API_BASE}/api/v1/proposals/${runId}`);
  if (!res.ok) throw new Error(`Proposal not found (${res.status})`);
  return res.json() as Promise<FinalProposal>;
}

export interface CleaningSchedule {
  frequency_per_year: number;
  recommended_months: number[];
}

export interface WeatherProfile {
  latitude: number;
  longitude: number;
  data_source: string;
  date_range_start: string;
  date_range_end: string;
  monthly_sunshine_hours: number[];       // 12 values, index 0 = Jan
  monthly_precipitation_mm: number[];
  monthly_cloud_cover_pct: number[];
  monthly_wind_speed_ms: number[];
  monthly_avg_temperature_c: number[];
  annual_irradiance_kwh_m2: number;
  sunny_days_per_year: number;
  seasonal_sunshine_hours: number[];      // 4 values [Q1, Q2, Q3, Q4]
  optimal_installation_quarter: number;   // 1-indexed
  quarter_rankings: number[];
  cleaning_schedule: CleaningSchedule;
}

export async function fetchWeather(runId: string): Promise<WeatherProfile> {
  const res = await fetch(`${API_BASE}/api/v1/proposals/${runId}/weather`);
  if (!res.ok) throw new Error(`Weather profile not available (${res.status})`);
  return res.json() as Promise<WeatherProfile>;
}

export async function signoffProposal(
  runId: string,
  action: "approve" | "reject",
  notes?: string,
): Promise<FinalProposal> {
  const res = await fetch(`${API_BASE}/api/v1/proposals/${runId}/signoff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, notes }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const msg =
      typeof body.detail === "string"
        ? body.detail
        : (body.detail as { message?: string } | undefined)?.message ?? `HTTP ${res.status}`;
    throw new Error(msg);
  }
  return res.json() as Promise<FinalProposal>;
}

export function artifactUrl(runId: string, filename: string): string {
  return `${API_BASE}/api/v1/artifacts/${runId}/${filename}`;
}
