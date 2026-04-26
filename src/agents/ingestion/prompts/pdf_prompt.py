PDF_EXTRACTION_PROMPT = """
You are analyzing a residential utility bill PDF to extract energy consumption data.

Extract the following information and return it as a JSON object:
{
  "annual_kwh": <total annual consumption in kWh — if not stated, estimate from monthly data or period data>,
  "monthly_breakdown": [
    {"month": 1, "kwh": <January kWh>},
    ... (all 12 months, every month 1–12 MUST be present)
  ],
  "tariff": {
    "currency": "<EUR|GBP|USD|CHF>",
    "rate_per_kwh": <unit rate>,
    "feed_in_tariff_per_kwh": <export rate if present, else null>,
    "time_of_use": {
      "peak_rate": <peak rate>,
      "off_peak_rate": <off-peak rate>,
      "peak_hours_start": <hour 0-23>,
      "peak_hours_end": <hour 0-23>
    } or null
  },
  "heating_fuel": "<gas|oil|electric|lpg|district|none>",
  "annual_heating_kwh": <heating consumption if separate, else null>,
  "has_ev": <true|false|null>,
  "bill_period_start": "<YYYY-MM-DD>",
  "bill_period_end": "<YYYY-MM-DD>"
}

CRITICAL: monthly_breakdown MUST contain exactly 12 entries (months 1–12).
- If per-month data is shown in the bill, use those exact values.
- If only an annual total is shown, distribute it evenly: each month = annual_kwh / 12.
- If only a partial period is shown, extrapolate to 12 months proportionally.
- Never return an empty monthly_breakdown array.

Return ONLY the JSON object, no additional text.
Confidence score (0.0-1.0): include as "confidence_score".
"""
