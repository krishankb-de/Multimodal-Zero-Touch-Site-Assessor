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
