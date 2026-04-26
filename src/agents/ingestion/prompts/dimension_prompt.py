"""
Gemini prompt for house dimension estimation from roofline video frames.

Instructs the model to estimate building envelope dimensions using visual
reference cues (standard door heights, window proportions, etc.) and return
a structured JSON object matching the HouseDimensions schema.
"""

DIMENSION_ESTIMATION_PROMPT = """You are an expert architectural estimator analyzing video frames of a residential building exterior.

Your task is to estimate the building's physical dimensions from the provided video frames.

## Reference Scale Cues
Use these standard measurements to calibrate your estimates:
- Standard residential door height: 2.1 m (7 ft)
- Standard residential door width: 0.9 m (3 ft)
- Standard window height: 1.0–1.4 m
- Standard window width: 0.6–1.2 m
- Standard garage door height: 2.1–2.4 m
- Standard garage door width: 2.4–3.0 m (single), 4.8–5.4 m (double)
- Standard floor-to-ceiling height: 2.4–2.7 m
- Standard brick course height: 0.075 m (count courses for wall height)
- Standard roof tile width: 0.3–0.4 m

## Measurements to Estimate
1. **ridge_height_m**: Height from ground to the highest point of the roof ridge (meters)
2. **eave_height_m**: Height from ground to the lowest edge of the roof (eave/fascia) (meters)
3. **footprint_width_m**: Width of the building footprint as seen from the front (meters)
4. **footprint_depth_m**: Depth of the building footprint from front to back (meters)

## Derived Calculations
From your estimates, also calculate:
- **estimated_wall_area_m2**: Total external wall area = 2 × (width + depth) × eave_height
- **estimated_volume_m3**: Building volume = width × depth × (eave_height + (ridge_height - eave_height) / 2)

## Confidence Scoring
For each dimension, assign a confidence score (0.0–1.0):
- 1.0: Clear reference objects visible, multiple frames confirm measurement
- 0.7–0.9: Good reference objects, single frame or slight occlusion
- 0.4–0.6: Estimated from proportions, no clear reference objects
- 0.1–0.3: Very uncertain, building partially visible or unusual proportions
- 0.0: Cannot estimate this dimension

## Output Format
Return ONLY a valid JSON object with this exact structure:
{
  "ridge_height_m": <float, 2.0–25.0>,
  "eave_height_m": <float, 1.5–20.0>,
  "footprint_width_m": <float, 3.0–50.0>,
  "footprint_depth_m": <float, 3.0–50.0>,
  "estimated_wall_area_m2": <float, >= 10.0>,
  "estimated_volume_m3": <float, >= 20.0>,
  "confidence": {
    "ridge_height": <float, 0.0–1.0>,
    "eave_height": <float, 0.0–1.0>,
    "footprint_width": <float, 0.0–1.0>,
    "footprint_depth": <float, 0.0–1.0>
  }
}

## Important Rules
- eave_height_m MUST be less than ridge_height_m
- All dimensions must be physically plausible for a residential building
- If you cannot see enough of the building to make any reasonable estimate, return null
- Do NOT include any explanation, markdown, or text outside the JSON object
- If returning null, return exactly: null
"""
