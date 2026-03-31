import base64
import json
import re

try:
    import fitz
except ImportError:
    fitz = None


def safe_float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except:
        return None


# =========================
# FAST PDF EXTRACTION (FIXED)
# =========================
def extract_pdf_text(file_bytes):
    if not fitz:
        return None

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        text_parts = []

        for i, page in enumerate(doc):
            if i > 15:
                break

            text = page.get_text()

            # prioritize useful pages
            if any(keyword in text.lower() for keyword in [
                "floor plan",
                "square feet",
                "sf",
                "area",
                "elevation",
                "plan",
                "section"
            ]):
                text_parts.append(text)

        # fallback if nothing matched
        if not text_parts:
            for i, page in enumerate(doc):
                if i > 10:
                    break
                text_parts.append(page.get_text())

        return "\n".join(text_parts)

    except Exception:
        return None

# =========================
# BASIC EXTRACTION
# =========================
def find_number(patterns, text):
    for pattern in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            return safe_float(m.group(1))
    return None


def detect_materials(text):
    t = (text or "").lower()
    if "wood" in t:
        return "wood framing"
    if "concrete" in t:
        return "concrete"
    return None



def pre_extract_plan_data(text):
    if not text:
        return {}

    t = text.lower()

    sqft = None

    patterns = [
        r"total.*?([\d,]+)\s*sf",
        r"living.*?([\d,]+)\s*sf",
        r"floor.*?([\d,]+)\s*sf",
        r"([\d,]+)\s*sf"
    ]

    for p in patterns:
        matches = re.findall(p, t)
        for m in matches:
            try:
                val = float(m.replace(",", ""))
                if val > 500:
                    sqft = val
                    break
            except:
                continue
        if sqft:
            break

    # detect structure
    materials = None
    if "type v" in t or "wood frame" in t:
        materials = "wood framing"
    elif "concrete" in t:
        materials = "concrete"

    # detect project type
    project_type = "residential"
    if "garage" in t:
        project_type = "residential_with_garage"

    return {
        "project_type": project_type,
        "estimated_size_sqft": sqft,
        "materials_hint": materials,
        "location_data": {"city": None}
    }


def parse_json_response(raw):
    try:
        return json.loads(raw)
    except:
        return None


# =========================
# 🔥 RESTORED STRONG AI ANALYSIS
# =========================
def analyze_pdf_text_with_ai(client, text, pre_data):

    trimmed = text[:20000]

    prompt = f"""
You are a senior construction estimator.

STRICT:
- Use ONLY real values
- No guessing
- No inflated assumptions
- Focus on cost-driving elements

DATA:
{json.dumps(pre_data, indent=2)}

PLANS:
{trimmed}

Return JSON:
{{
  "project_type": "...",
  "estimated_size_sqft": number,
  "materials_hint": "...",
  "complexity": [],
  "risks": [],
  "notes": "short contractor insight"
}}
"""

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You analyze construction plans like a contractor."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )

    raw = res.choices[0].message.content.strip()
    parsed = parse_json_response(raw)

    return raw, parsed


# =========================
# ROOM DETECTION (SAFE ADD)
# =========================
def extract_room_counts(text):
    t = (text or "").lower()

    baths = 0
    kitchens = 0

    matches = re.findall(r"(\d+\.?\d*)\s*bath", t)
    if matches:
        baths = int(float(matches[0]))

    if "kitchen" in t:
        kitchens = 1

    return {"bathrooms": baths, "kitchens": kitchens}


def enrich_for_estimator(data, text):
    if not isinstance(data, dict):
        return data

    rooms = extract_room_counts(text)

    data["rooms"] = rooms
    data["estimator_inputs"] = {
        "bathrooms": rooms["bathrooms"],
        "kitchens": rooms["kitchens"],
        "size_sqft": data.get("estimated_size_sqft"),
        "materials": data.get("materials_hint"),
        "city": (data.get("location_data") or {}).get("city")
    }

    return data


# =========================
# MAIN ENTRY
# =========================
def analyze_uploaded_plan(client, file_obj):
    file_bytes = file_obj.read()
    name = getattr(file_obj, "filename", "").lower()

    if name.endswith(".pdf"):
        text = extract_pdf_text(file_bytes)

        if text:
            pre = pre_extract_plan_data(text)

            try:
                raw, ai = analyze_pdf_text_with_ai(client, text, pre)
                merged = {**pre, **(ai or {})}

                enriched = enrich_for_estimator(merged, text)

                return {
                    "mode": "pdf",
                    "raw": raw,
                    "parsed": enriched
                }

            except Exception as e:
                enriched = enrich_for_estimator(pre, text)

                return {
                    "mode": "fallback",
                    "raw": str(e),
                    "parsed": enriched
                }

    return {"mode": "error", "parsed": None}
