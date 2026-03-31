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
    """
    Extract text from PDF using PyMuPDF.
    Returns None safely if extraction fails.
    """
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
    if raw is None:
        return None
    return safe_float(raw)


def normalize_project_type(text):
    t = (text or "").lower()

    if "single family residence" in t or "single-family residence" in t:
        return "Single Family Residence"
    if "residence" in t:
        return "Residential"
    if "garage" in t and "residence" in t:
        return "Single Family Residence"
    return None


def detect_build_method(text):
    t = (text or "").lower()
    if "factory-built modular" in t or "modular single family residence" in t:
        return "modular_prefab"
    if "factory built" in t or "factory-built" in t:
        return "modular_prefab"
    return "traditional"


def detect_materials_hint(text):
    t = (text or "").lower()
    hints = []

    if "2x6 wood studs" in t or "wood framing" in t or "type v-b" in t:
        hints.append("wood framing")
    if "concrete" in t or "foundation" in t or "slab" in t:
        hints.append("concrete foundation")
    if "standing metal seam" in t:
        hints.append("standing seam metal roofing")
    if "composite roofing" in t:
        hints.append("composite roofing")
    if "siding" in t:
        hints.append("siding")

    if not hints:
        return None

    # de-duplicate while preserving order
    seen = set()
    deduped = []
    for item in hints:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    return ", ".join(deduped)


def build_complexity_and_risks(text, extracted):
    t = (text or "").lower()
    complexity_factors = []
    risk_flags = []

    def add_unique(lst, value):
        if value and value not in lst:
            lst.append(value)

    if extracted.get("build_method") == "modular_prefab":
        add_unique(complexity_factors, "modular prefab coordination")
        add_unique(risk_flags, "factory/site coordination risk")

    if extracted.get("stories") and extracted["stories"] >= 2:
        add_unique(complexity_factors, "multi-story construction")

    if extracted.get("garage_sqft"):
        add_unique(complexity_factors, "garage construction")

    if "deck" in t:
        add_unique(complexity_factors, "deck construction")

    if "demolition" in t:
        add_unique(complexity_factors, "demolition scope")
        add_unique(risk_flags, "demo and rebuild sequencing")

    if "sprinkler" in t or "nfpa 13d" in t:
        add_unique(complexity_factors, "fire sprinkler system")
        add_unique(risk_flags, "fire code compliance")

    if "solar" in t or "pv system" in t:
        add_unique(complexity_factors, "solar integration")
        add_unique(risk_flags, "separate solar permit coordination")

    if "natural gas is not permitted" in t or "all-electric" in t or "electric." in t:
        add_unique(complexity_factors, "all-electric design")
        add_unique(risk_flags, "electrical service sizing")

    if "heat pump" in t:
        add_unique(complexity_factors, "heat pump mechanical system")

    if "energy recovery ventilator" in t:
        add_unique(complexity_factors, "advanced ventilation system")

    if "flood zone" in t:
        add_unique(risk_flags, "flood zone review required")

    if "zone d" in t:
        add_unique(risk_flags, "flood zone considerations")

    if "setback" in t:
        add_unique(complexity_factors, "setback constraints")

    if "grading" in t or "drainage" in t:
        add_unique(complexity_factors, "site grading and drainage")

    if "type v-b" in t:
        add_unique(risk_flags, "wood-frame fire/life-safety compliance")

    return complexity_factors, risk_flags


def extract_scope_items(text):
    t = text or ""
    items = []

    candidates = [
        ("demolition", r"demolition"),
        ("foundation work", r"foundation"),
        ("crawlspace", r"crawlspace"),
        ("garage slab", r"garage slab|garage"),
        ("module connections", r"module to module|foundation and modules|module connections"),
        ("stairs", r"stair"),
        ("windows/sliders", r"window and slider|slider doors"),
        ("metal canopy", r"metal canopy|canopy"),
        ("deck construction", r"deck|decking"),
        ("roofing", r"roofing|roof panels|roof"),
        ("siding", r"\bsiding\b"),
        ("fire sprinklers", r"sprinkler|nfpa 13d"),
        ("solar", r"solar|pv system"),
        ("hvac", r"heat pump|air handler|hvac"),
    ]

    for label, pattern in candidates:
        if re.search(pattern, t, re.IGNORECASE):
            items.append(label)

    return items


def extract_mechanical_systems(text):
    t = text or ""
    systems = []

    pairs = [
        ("heat pump HVAC", r"heat pump"),
        ("energy recovery ventilator", r"energy recovery ventilator"),
        ("air handler", r"air handler"),
        ("hybrid heat pump water heater", r"hybrid/heat pump water heater|heat pump water heater"),
        ("induction cooktop", r"induction cooktop"),
    ]

    for label, pattern in pairs:
        if re.search(pattern, t, re.IGNORECASE):
            systems.append(label)

    return systems


def pre_extract_plan_data(text):
    """
    Deterministic extraction layer before AI.
    """
    if not text:
        return {}

    project_type = normalize_project_type(text)

    gross_floor_area = find_number([
        r"PROPOSED GROSS FLOOR AREA\s*=\s*[\d,.\s()A-Z+-]*?=\s*([\d,]+\.\d+|[\d,]+)\s*SF",
        r"GROSS FLOOR AREA\s*PROPOSED\s*[-–]\s*([\d,]+\.\d+|[\d,]+)\s*SF",
        r"PROPOSED\s*[-–]\s*([\d,]+\.\d+|[\d,]+)\s*SF\*"
    ], text)

    first_floor = find_number([
        r"1ST FLOOR GROSS AREA\s*([\d,]+\.\d+|[\d,]+)\s*SF",
        r"FIRST FLOOR GROSS AREA\s*([\d,]+\.\d+|[\d,]+)\s*SF"
    ], text)

    second_floor = find_number([
        r"2ND FLOOR GROSS AREA\s*([\d,]+\.\d+|[\d,]+)\s*SF",
        r"SECOND FLOOR GROSS AREA\s*([\d,]+\.\d+|[\d,]+)\s*SF"
    ], text)

    garage_sqft = find_number([
        r"GARAGE FLOOR AREA\s*PROPOSED\s*[-–]\s*([\d,]+\.\d+|[\d,]+)\s*SF",
        r"GARAGE FLOOR AREA[\s\S]{0,100}?PROPOSED\s*[-–]\s*([\d,]+\.\d+|[\d,]+)\s*SF"
    ], text)

    lot_area = find_number([
        r"LOT AREA\s*=\s*([\d,]+\.\d+|[\d,]+)\s*SF",
        r"LOT AREA\s*([\d,]+\.\d+|[\d,]+)\s*SF"
    ], text)

    conditioned_area = find_number([
        r"ENERGY MODEL CONDITIONED AREA[\s\S]{0,60}?=\s*([\d,]+\.\d+|[\d,]+)\s*SF"
    ], text)

    stories = find_number([
        r"PROPOSED NUMBER OF STORIES\s*:\s*([\d.]+)",
        r"NUMBER OF STORIES[\s\S]{0,80}?PROPOSED NUMBER OF STORIES\s*:\s*([\d.]+)"
    ], text)

    if stories is not None:
        try:
            stories = int(float(stories))
        except Exception:
            stories = None

    construction_type = find_first([
        r"CONSTRUCTION TYPE\s*[:\s]\s*(TYPE\s*[A-Z0-9\-]+)",
        r"TYPE OF CONSTRUCTION\s*[:\s]\s*([A-Z0-9\-]+)"
    ], text)

    occupancy = find_first([
        r"OCCUPANCY CLASS\s*[:\s]\s*(GROUP\s*[A-Z0-9\-\/]+)",
        r"OCCUPANCY GROUP\(S\)\s*([A-Z0-9\-\/]+)"
    ], text)

    flood_zone = find_first([
        r"FLOOD ZONE\s*[:\s]\s*(ZONE\s*[A-Z0-9\-]+)",
        r"FLOOD ZONE\s*[:\s]\s*([A-Z0-9\-]+)"
    ], text)

    city = find_first([
        r"PROJECT ADDRESS\s*[\s:]*([^\n,]+,\s*[A-Z][a-zA-Z ]+,\s*CA\s*\d{5})",
        r"(San Jose,\s*CA\s*\d{5})"
    ], text)

    address = find_first([
        r"PROJECT ADDRESS\s*[\s:]*([^\n]+)",
        r"(1828\s+NESTORITA\s+WAY,\s*SAN\s+JOSE,\s*CA\s*95124)"
    ], text)

    sprinkler_required = bool(re.search(r"NFPA\s*13D|FIRE SPRINKLER", text, re.IGNORECASE))
    solar_required = bool(re.search(r"SOLAR|PV SYSTEM", text, re.IGNORECASE))
    all_electric = bool(re.search(r"NATURAL GAS IS NOT PERMITTED", text, re.IGNORECASE))

    build_method = detect_build_method(text)
    materials_hint = detect_materials_hint(text)
    complexity_factors, risk_flags = build_complexity_and_risks(text, {
        "build_method": build_method,
        "stories": stories,
        "garage_sqft": garage_sqft
    })

    scope_of_work = extract_scope_items(text)
    mechanical_systems = extract_mechanical_systems(text)

    estimated_size_sqft = gross_floor_area or conditioned_area or first_floor

    result = {
        "project_type": project_type,
        "estimated_size_sqft": estimated_size_sqft,
        "area_breakdown": {
            "first_floor_sqft": first_floor,
            "second_floor_sqft": second_floor,
            "garage_sqft": garage_sqft,
            "total_sqft": gross_floor_area,
            "conditioned_sqft": conditioned_area
        },
        "stories": stories,
        "construction_type": construction_type,
        "occupancy_class": occupancy,
        "build_method": build_method,
        "materials_hint": materials_hint,
        "location_data": {
            "address": address,
            "city": city,
            "lot_area_sqft": lot_area,
            "flood_zone": flood_zone
        },
        "requirements": {
            "sprinklers_required": sprinkler_required,
            "solar_required": solar_required,
            "all_electric": all_electric
        },
        "mechanical_systems": mechanical_systems,
        "scope_of_work": scope_of_work,
        "complexity_factors": complexity_factors,
        "risk_flags": risk_flags,
        "notes": None
    }

    return result


def strip_code_fences(raw_text):
    if not raw_text:
        return raw_text

    cleaned = raw_text.strip()

    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    return cleaned.strip()


def parse_json_response(raw):
    cleaned = strip_code_fences(raw)

    try:
        return json.loads(cleaned)
    except Exception:
        return None


def merge_plan_data(pre, ai):
    """
    Merge deterministic extraction with AI output.
    Deterministic values win when present.
    """
    if not isinstance(pre, dict):
        pre = {}
    if not isinstance(ai, dict):
        ai = {}

    merged = dict(ai)

    for key, value in pre.items():
        if isinstance(value, dict):
            existing = merged.get(key, {})
            if not isinstance(existing, dict):
                existing = {}
            combined = dict(existing)
            for sub_key, sub_value in value.items():
                if sub_value not in (None, "", [], {}):
                    combined[sub_key] = sub_value
            merged[key] = combined
        elif isinstance(value, list):
            existing = merged.get(key, [])
            if not isinstance(existing, list):
                existing = []
            combined = []
            seen = set()
            for item in value + existing:
                if item and item not in seen:
                    seen.add(item)
                    combined.append(item)
            merged[key] = combined
        else:
            if value not in (None, "", [], {}):
                merged[key] = value

    return merged


def build_ai_prompt(extracted_text, pre_data):
    pre_json = json.dumps(pre_data, indent=2)

    return f"""
Analyze this construction plan text and return ONLY valid JSON.

Use the pre-extracted fields below as strong hints, but correct them if the plan text clearly proves something else.
Prefer explicit values from the document over guesses.

Return this exact shape:

{{
  "project_type": "...",
  "estimated_size_sqft": number,
  "area_breakdown": {{
    "first_floor_sqft": number,
    "second_floor_sqft": number,
    "garage_sqft": number,
    "total_sqft": number,
    "conditioned_sqft": number
  }},
  "stories": number,
  "construction_type": "...",
  "occupancy_class": "...",
  "build_method": "...",
  "materials_hint": "...",
  "location_data": {{
    "address": "...",
    "city": "...",
    "lot_area_sqft": number,
    "flood_zone": "..."
  }},
  "requirements": {{
    "sprinklers_required": true,
    "solar_required": true,
    "all_electric": true
  }},
  "mechanical_systems": [],
  "scope_of_work": [],
  "complexity_factors": [],
  "risk_flags": [],
  "notes": "..."
}}

Rules:
- Return ONLY JSON
- Be conservative and realistic
- Use exact document values when present
- Do not invent values that are not reasonably supported
- If unsure, keep fields null or use cautious wording in notes

PRE_EXTRACTED_HINTS:
{pre_json}

PLAN_TEXT:
{extracted_text[:22000]}
"""


def analyze_pdf_text_with_ai(client, extracted_text, pre_data):
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": "You extract structured contractor intelligence from architectural plans and permit sets."
            },
            {
                "role": "user",
                "content": build_ai_prompt(extracted_text, pre_data)
            }
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
        messages=[
            {
                "role": "system",
                "content": "You extract structured construction data from plan images."
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": """
Return ONLY valid JSON in this shape:

{
  "project_type": "...",
  "estimated_size_sqft": number,
  "area_breakdown": {
    "first_floor_sqft": number,
    "second_floor_sqft": number,
    "garage_sqft": number,
    "total_sqft": number,
    "conditioned_sqft": number
  },
  "stories": number,
  "construction_type": "...",
  "occupancy_class": "...",
  "build_method": "...",
  "materials_hint": "...",
  "location_data": {
    "address": "...",
    "city": "...",
    "lot_area_sqft": number,
    "flood_zone": "..."
  },
  "requirements": {
    "sprinklers_required": true,
    "solar_required": true,
    "all_electric": true
  },
  "mechanical_systems": [],
  "scope_of_work": [],
  "complexity_factors": [],
  "risk_flags": [],
  "notes": "..."
}
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
        temperature=0.1
    )

    raw = response.choices[0].message.content.strip()
    parsed = parse_json_response(raw)
    return raw, parsed


def analyze_uploaded_plan(client, file_obj):
    file_bytes = file_obj.read()
    filename = getattr(file_obj, "filename", "").lower()
    is_pdf = filename.endswith(".pdf")

    # =========================
    # PDF PATH
    # =========================
    if is_pdf:
        extracted_text = extract_pdf_text(file_bytes)

        if extracted_text and len(extracted_text.strip()) > 50:
            pre_data = pre_extract_plan_data(extracted_text)

            try:
                raw, ai_parsed = analyze_pdf_text_with_ai(client, extracted_text, pre_data)
                merged = merge_plan_data(pre_data, ai_parsed)

               enriched = enrich_for_estimator(merged, extracted_text)

               return {
                   "mode": "pdf_text_hybrid",
                   "raw": raw,
                   "parsed": enriched,
                   "pre_extracted": pre_data
                }
            except Exception as e:
            
                enriched = enrich_for_estimator(pre_data, extracted_text)

                return {
                    "mode": "pdf_text_preextract_only",
                    "raw": str(e),
                    "parsed": enriched,
                    "pre_extracted": pre_data
                }

    # =========================
    # IMAGE FALLBACK
    # =========================
    try:
        raw, parsed = analyze_image_with_ai(client, file_bytes)
        
        enriched = enrich_for_estimator(parsed, "")

        return {
            "mode": "image",
            "raw": raw,
            "parsed": enriched,
            "pre_extracted": {}
        }
    except Exception as e:
        return {
            "mode": "error",
            "raw": str(e),
            "parsed": None,
            "pre_extracted": {}
        }
# =========================
# ESTIMATOR ENRICHMENT LAYER (SAFE ADD-ON)
# =========================

def extract_room_counts(text):
    t = (text or "").lower()

    bathrooms = 0
    kitchens = 0

    # Detect bathrooms
    matches = re.findall(r"(\d+)\s*bath", t)
    if matches:
        try:
            bathrooms = max(int(x) for x in matches)
        except:
            bathrooms = 1
    elif "bathroom" in t:
        bathrooms = 1

    # Detect kitchens
    if "kitchen" in t:
        kitchens = 1

    return {
        "bathrooms": bathrooms,
        "kitchens": kitchens
    }


def enrich_for_estimator(plan_data, raw_text):
    """
    Adds estimator-friendly fields WITHOUT breaking existing structure
    """
    if not isinstance(plan_data, dict):
        return plan_data

    enriched = dict(plan_data)

    rooms = extract_room_counts(raw_text)

    enriched["rooms"] = rooms

    enriched["estimator_inputs"] = {
        "bathrooms": rooms.get("bathrooms", 1),
        "kitchens": rooms.get("kitchens", 1),
        "size_sqft": plan_data.get("estimated_size_sqft"),
        "project_type": plan_data.get("project_type"),
        "materials": plan_data.get("materials_hint"),
        "city": (plan_data.get("location_data") or {}).get("city")
    }

    return enriched
