import base64
import json

# PDF support
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def extract_pdf_text(file_bytes):
    """
    Extracts text from PDF using PyMuPDF.
    Safe fallback if library not installed or fails.
    """
    if not fitz:
        return None

    try:
        text = ""
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            text += page.get_text()
        return text
    except Exception:
        return None


def analyze_uploaded_plan(client, file_obj):
    file_bytes = file_obj.read()
    filename = getattr(file_obj, "filename", "").lower()

    is_pdf = filename.endswith(".pdf")

    # =====================================
    # PATH 1 — PDF TEXT ANALYSIS (BEST PATH)
    # =====================================
    if is_pdf:
        extracted_text = extract_pdf_text(file_bytes)

        if extracted_text and len(extracted_text.strip()) > 50:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You extract structured construction data from architectural plans and engineering documents."
                        },
                        {
                            "role": "user",
                            "content": f"""
Analyze this construction plan text and return ONLY valid JSON:

{{
  "project_type": "...",
  "estimated_size_sqft": number,
  "materials_hint": "...",
  "notes": "..."
}}

Be conservative and realistic.

TEXT:
{extracted_text[:15000]}
"""
                        }
                    ],
                    temperature=0.2
                )

                raw = response.choices[0].message.content.strip()

                try:
                    parsed = json.loads(raw)
                except Exception:
                    parsed = None

                return {
                    "mode": "pdf_text",
                    "raw": raw,
                    "parsed": parsed
                }

            except Exception as e:
                # fallback to image path
                pass

    # =====================================
    # PATH 2 — IMAGE ANALYSIS (FALLBACK)
    # =====================================
    try:
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
Analyze this plan and return ONLY valid JSON:

{
  "project_type": "...",
  "estimated_size_sqft": number,
  "materials_hint": "...",
  "notes": "..."
}

Be conservative and realistic.
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

        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = None

        return {
            "mode": "image",
            "raw": raw,
            "parsed": parsed
        }

    except Exception as e:
        return {
            "mode": "error",
            "raw": str(e),
            "parsed": None
        }
