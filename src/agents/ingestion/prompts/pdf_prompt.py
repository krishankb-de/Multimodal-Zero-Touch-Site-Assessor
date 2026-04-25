PDF_EXTRACTION_PROMPT = """
You are analyzing a residential utility bill PDF to extract energy consumption data.

Extract the following information and return it as a JSON object:
{
  "annual_kwh": <total annual consumption in kWh>,
  "monthly_breakdown": [
    {"month": 1, "kwh": <January kWh>},
    ... (all 12 months)
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

Return ONLY the JSON object, no additional text.
Confidence score (0.0-1.0): include as "confidence_score".
"""
