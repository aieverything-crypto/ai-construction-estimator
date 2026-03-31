import base64
import json
import re

# PDF support
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


def safe_float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return None


def extract_pdf_text(file_bytes):
    if not fitz:
        return None

    try:
        text_parts = []
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        for page in doc:
            text_parts.append(page.get_text())
        return "\n".join(text_parts)
    except Exception:
        return None


def find_first(patterns, text, flags=re.IGNORECASE):
    for pattern in patterns:
        match = re.search(pattern, text, flags)
        if match:
            return match.group(1).strip()
    return None


def find_number(patterns, text, flags=re.IGNORECASE):
    raw = find_first(patterns, text, flags=flags)
    return safe_float(raw) if raw else None


def normalize_project_type(text):
    t = (text or "").lower()
    if "single family residence" in t:
        return "Single Family Residence"
    if "residence" in t:
        return "Residential"
    return None


def detect_build_method(text):
    t = (text or "").lower()
    if "modular" in t or "factory-built" in t:
        return "modular_prefab"
    return "traditional"


def detect_materials_hint(text):
    t = (text or "").lower()
    hints = []

    if "wood" in t:
        hints.append("wood framing")
    if "concrete" in t:
        hints.append("concrete foundation")
    if "metal" in t:
        hints.append("metal roofing")

    return ", ".join(hints) if hints else None


def extract_scope_items(text):
    t = text or ""
    items = []

    if "foundation" in t:
        items.append("foundation")
    if "roof" in t:
        items.append("roofing")
    if "hvac" in t:
        items.append("hvac")

    return items


def extract_mechanical_systems(text):
    t = text or ""
    systems = []

    if "heat pump" in t:
        systems.append("heat pump HVAC")

    return systems


def pre_extract_plan_data(text):
    if not text:
        return {}

    sqft = find_number([r"([\d,]+)\s*sf"], text)

    return {
        "project_type": normalize_project_type(text),
        "estimated_size_sqft": sqft,
        "materials_hint": detect_materials_hint(text),
        "scope_of_work": extract_scope_items(text),
        "mechanical_systems": extract_mechanical_systems(text),
        "location_data": {"city": None},
    }


def parse_json_response(raw):
    try:
        return json.loads(raw)
    except:
        return None


def merge_plan_data(pre, ai):
    merged = dict(ai or {})
    for k, v in (pre or {}).items():
        if v:
            merged[k] = v
    return merged


def analyze_pdf_text_with_ai(client, extracted_text, pre_data):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Extract construction plan data"},
            {"role": "user", "content": extracted_text[:15000]}
        ],
        temperature=0.1
    )

    raw = response.choices[0].message.content.strip()
    parsed = parse_json_response(raw)

    return raw, parsed


def analyze_image_with_ai(client, file_bytes):
    encoded = base64.b64encode(file_bytes).decode("utf-8")

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "Extract construction data as JSON"},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}}
            ]
        }],
        temperature=0.1
    )

    raw = response.choices[0].message.content.strip()
    parsed = parse_json_response(raw)
    return raw, parsed


# =========================
# ESTIMATOR ENRICHMENT
# =========================

def extract_room_counts(text):
    t = (text or "").lower()

    bathrooms = 1 if "bath" in t else 0
    kitchens = 1 if "kitchen" in t else 0

    return {
        "bathrooms": bathrooms,
        "kitchens": kitchens
    }


def enrich_for_estimator(plan_data, raw_text):
    if not isinstance(plan_data, dict):
        return plan_data

    rooms = extract_room_counts(raw_text)

    plan_data["rooms"] = rooms
    plan_data["estimator_inputs"] = {
        "bathrooms": rooms["bathrooms"],
        "kitchens": rooms["kitchens"],
        "size_sqft": plan_data.get("estimated_size_sqft"),
        "materials": plan_data.get("materials_hint"),
        "city": (plan_data.get("location_data") or {}).get("city")
    }

    return plan_data


def analyze_uploaded_plan(client, file_obj):
    file_bytes = file_obj.read()
    filename = getattr(file_obj, "filename", "").lower()

    if filename.endswith(".pdf"):
        extracted_text = extract_pdf_text(file_bytes)

        if extracted_text:
            pre_data = pre_extract_plan_data(extracted_text)

            try:
                raw, ai_parsed = analyze_pdf_text_with_ai(client, extracted_text, pre_data)
                merged = merge_plan_data(pre_data, ai_parsed)

                enriched = enrich_for_estimator(merged, extracted_text)

                return {
                    "mode": "pdf",
                    "raw": raw,
                    "parsed": enriched
                }

            except Exception as e:
                enriched = enrich_for_estimator(pre_data, extracted_text)

                return {
                    "mode": "pdf_fallback",
                    "raw": str(e),
                    "parsed": enriched
                }

    try:
        raw, parsed = analyze_image_with_ai(client, file_bytes)
        enriched = enrich_for_estimator(parsed, "")

        return {
            "mode": "image",
            "raw": raw,
            "parsed": enriched
        }

    except Exception as e:
        return {
            "mode": "error",
            "raw": str(e),
            "parsed": None
        }
