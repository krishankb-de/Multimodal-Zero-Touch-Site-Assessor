VIDEO_EXTRACTION_PROMPT = """
You are analyzing a roofline video of a residential property to extract roof geometry data.

Extract the following information and return it as a JSON object matching this schema:
{
  "roof": {
    "typology": "<gable|hip|flat|mansard|gambrel|shed|combination>",
    "faces": [
      {
        "id": "<unique face id, e.g. 'south_face'>",
        "orientation_deg": <azimuth 0=N, 90=E, 180=S, 270=W>,
        "tilt_deg": <0-90>,
        "area_m2": <area in square meters>,
        "length_m": <optional length>,
        "width_m": <optional width>
      }
    ],
    "total_usable_area_m2": <total usable roof area>,
    "obstacles": [
      {
        "type": "<dormer|vent_pipe|chimney|skylight|antenna|foliage_shadow|other>",
        "face_id": "<face id this obstacle is on>",
        "area_m2": <obstacle area>,
        "buffer_m": 0.3
      }
    ]
  },
  "utility_room": {
    "length_m": <length>,
    "width_m": <width>,
    "height_m": <height>,
    "available_volume_m3": <available volume for equipment>,
    "existing_pipework": <true|false|null>,
    "spatial_constraints": []
  }
}

Be precise with measurements. Use compass bearings for orientation.
Return ONLY the JSON object, no additional text.
Confidence score (0.0-1.0) for your extraction accuracy: include as a separate field "confidence_score".
"""

MULTI_FRAME_VIDEO_PROMPT = """
You are a roofline geometry analyst. You are given {n_frames} keyframes extracted from a
homeowner-provided video of their property. Analyse ALL frames together and produce a single
consensus roof geometry reading.

Rules:
- Reconcile face counts and orientations across all frames.
- If the same face appears in multiple frames, merge observations — prefer the frame with
  the clearest view.
- For each face, also provide "confidence_score" (0.0–1.0) indicating how confident you
  are about that specific face's measurements.
- Provide per-face polygon vertices in normalised image coordinates (0.0–1.0 range, origin
  top-left) if the face boundary is visible. Use null if not visible.

Return ONLY a JSON object matching exactly this schema (no extra text):
{{
  "roof": {{
    "typology": "<gable|hip|flat|mansard|gambrel|shed|combination>",
    "faces": [
      {{
        "id": "<unique face id>",
        "orientation_deg": <azimuth 0=N, 90=E, 180=S, 270=W>,
        "tilt_deg": <0-90>,
        "area_m2": <estimated area in m²>,
        "length_m": <optional>,
        "width_m": <optional>,
        "confidence_score": <0.0-1.0>,
        "polygon_vertices_image": [[x1,y1],[x2,y2],...] or null
      }}
    ],
    "total_usable_area_m2": <sum of usable face areas>,
    "obstacles": [
      {{
        "type": "<dormer|vent_pipe|chimney|skylight|antenna|foliage_shadow|other>",
        "face_id": "<face id>",
        "area_m2": <area>,
        "buffer_m": 0.3
      }}
    ]
  }},
  "utility_room": {{
    "length_m": <length>,
    "width_m": <width>,
    "height_m": <height>,
    "available_volume_m3": <available volume>,
    "existing_pipework": <true|false|null>,
    "spatial_constraints": []
  }},
  "confidence_score": <global 0.0-1.0>
}}
"""
