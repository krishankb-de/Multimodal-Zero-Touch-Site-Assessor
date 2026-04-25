PHOTO_EXTRACTION_PROMPT = """
You are analyzing a photo of a residential electrical panel/consumer unit.

Extract the following information and return it as a JSON object:
{
  "main_supply": {
    "amperage_A": <main fuse/breaker rating in amps>,
    "phases": <1 or 3>,
    "voltage_V": <230 for single-phase, 400 for three-phase>
  },
  "breakers": [
    {
      "label": "<circuit label>",
      "rating_A": <breaker rating in amps>,
      "type": "<MCB|RCBO|RCD|MCCB|isolator|unknown>",
      "circuit_description": "<optional description>"
    }
  ],
  "board_condition": "<good|fair|poor|requires_replacement>",
  "spare_ways": <number of empty slots>
}

Only include standard breaker ratings: 6, 10, 13, 16, 20, 25, 32, 40, 50, 63, 80, 100, 125 amps.
Return ONLY the JSON object, no additional text.
Confidence score (0.0-1.0): include as "confidence_score".
"""
