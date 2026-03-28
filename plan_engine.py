import base64
import json


def analyze_uploaded_plan(client, file_obj):
    file_bytes = file_obj.read()
    encoded = base64.b64encode(file_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You extract structured construction data from drawings and plans."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """
Analyze this plan and return ONLY valid JSON in this shape:

{
  "project_type": "...",
  "estimated_size_sqft": number,
  "materials_hint": "...",
  "notes": "..."
}

Be conservative and realistic.
If unsure, make your best estimate.
"""
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/png;base64,{encoded}"
                        }
                    }
                ]
            }
        ],
        temperature=0.2
    )

    raw = response.choices[0].message.content.strip()

    parsed = None
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None

    return {
        "raw": raw,
        "parsed": parsed
    }
