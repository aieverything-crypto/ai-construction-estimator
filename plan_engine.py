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

def limit_text(text, max_chars=12000):
    if not text:
        return ""
    return text[:max_chars]
    
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
    if "adu" in t or "accessory dwelling unit" in t:
        return "ADU"
    if "duplex" in t:
        return "Duplex"
    if "multifamily" in t or "multi-family" in t or "apartment" in t:
        return "Multifamily Residential"
    if "residence" in t or "house" in t or "dwelling" in t:
        return "Residential"
    if "office" in t:
        return "Office"
    if "restaurant" in t:
        return "Restaurant"
    if "retail" in t or "storefront" in t:
        return "Retail"
    if "warehouse" in t:
        return "Warehouse"

    return None


def detect_build_method(text):
    t = (text or "").lower()

    if "factory-built modular" in t or "modular single family residence" in t:
        return "modular_prefab"
    if "factory built" in t or "factory-built" in t:
        return "modular_prefab"
    if "panelized" in t:
        return "panelized"
    if "site-built" in t or "site built" in t:
        return "traditional"

    return "traditional"


def detect_materials_hint(text):
    t = (text or "").lower()
    hints = []

    if "2x6 wood studs" in t or "2 x 6 wood studs" in t or "wood framing" in t or "type v-b" in t:
        hints.append("wood framing")
    if "steel frame" in t or "steel framing" in t or "structural steel" in t:
        hints.append("steel framing")
    if "cmu" in t or "concrete masonry" in t or "masonry" in t:
        hints.append("masonry")
    if "concrete" in t or "foundation" in t or "slab" in t:
        hints.append("concrete foundation")
    if "standing metal seam" in t or "standing seam metal" in t:
        hints.append("standing seam metal roofing")
    if "composite roofing" in t or "composition shingle" in t:
        hints.append("composite roofing")
    if "tile roof" in t:
        hints.append("tile roofing")
    if "siding" in t:
        hints.append("siding")
    if "stucco" in t:
        hints.append("stucco exterior")
    if "glass" in t or "curtain wall" in t:
        hints.append("glass-heavy exterior")

    if not hints:
        return None

    seen = set()
    deduped = []
    for item in hints:
        if item not in seen:
            seen.add(item)
            deduped.append(item)

    return ", ".join(deduped)


def extract_bed_bath_counts(text):
    t = text or ""

    bedrooms = find_number([
        r"(\d+(?:\.\d+)?)\s*bed(?:room)?s?\b",
        r"bedrooms?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*br\b"
    ], t)

    bathrooms = find_number([
        r"(\d+(?:\.\d+)?)\s*bath(?:room)?s?\b",
        r"bathrooms?\s*[:\-]?\s*(\d+(?:\.\d+)?)",
        r"(\d+(?:\.\d+)?)\s*ba\b"
    ], t)

    return bedrooms, bathrooms


def detect_foundation_type(text):
    t = (text or "").lower()

    if "slab on grade" in t or "slab-on-grade" in t:
        return "slab_on_grade"
    if "crawlspace" in t or "crawl space" in t:
        return "crawlspace"
    if "basement" in t:
        return "basement"
    if "pier and beam" in t:
        return "pier_and_beam"
    if "mat foundation" in t:
        return "mat_foundation"
    if "spread footing" in t or "continuous footing" in t or "footing" in t:
        return "footings"
    if "deep foundation" in t or "caisson" in t or "pile" in t:
        return "deep_foundation"

    return None


def detect_roof_type(text):
    t = (text or "").lower()

    if "flat roof" in t:
        return "flat"
    if "gable roof" in t:
        return "gable"
    if "hip roof" in t:
        return "hip"
    if "shed roof" in t:
        return "shed"
    if "standing seam metal" in t:
        return "standing_seam_metal"

    return None


def extract_outdoor_features(text):
    t = text or ""
    items = []

    pairs = [
        ("deck", r"\bdeck\b"),
        ("porch", r"\bporch\b"),
        ("patio", r"\bpatio\b"),
        ("balcony", r"\bbalcony\b"),
        ("terrace", r"\bterrace\b"),
        ("canopy", r"\bcanopy\b"),
        ("carport", r"\bcarport\b"),
        ("garage", r"\bgarage\b"),
        ("retaining wall", r"retaining wall"),
        ("site stairs", r"exterior stair|site stair"),
        ("fence", r"\bfence\b"),
    ]

    for label, pattern in pairs:
        if re.search(pattern, t, re.IGNORECASE):
            items.append(label)

    return items


def extract_structural_flags(text):
    t = text or ""
    items = []

    pairs = [
        ("retaining wall", r"retaining wall"),
        ("shear wall", r"shear wall"),
        ("moment frame", r"moment frame"),
        ("steel frame", r"structural steel|steel frame|steel framing"),
        ("large openings", r"large opening|opening width|slider doors|multi-slide"),
        ("cantilever", r"cantilever"),
        ("tall walls", r"10['’]?\s*-\s*0|12['’]?\s*-\s*0|high wall|tall wall"),
        ("multi-story structure", r"2 story|two story|3 story|three story|number of stories"),
        ("seismic retrofit", r"seismic retrofit|retrofit"),
    ]

    for label, pattern in pairs:
        if re.search(pattern, t, re.IGNORECASE):
            items.append(label)

    return items


def extract_site_constraints(text):
    t = text or ""
    items = []

    pairs = [
        ("hillside site", r"hillside|slope|steep"),
        ("limited access", r"limited access|tight lot|urban infill"),
        ("grading required", r"\bgrading\b"),
        ("drainage work", r"\bdrainage\b"),
        ("flood zone", r"flood zone|zone [a-z0-9\-]+"),
        ("setback constraints", r"\bsetback\b"),
        ("erosion control", r"erosion control"),
        ("remote logistics", r"\bremote\b|\bisland\b"),
    ]

    for label, pattern in pairs:
        if re.search(pattern, t, re.IGNORECASE):
            items.append(label)

    return items


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
        ("electrical service", r"panel|electrical service|main service"),
        ("plumbing fixtures", r"plumbing fixture|fixture schedule|water heater"),
        ("grading/drainage", r"grading|drainage"),
        ("retaining walls", r"retaining wall"),
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
        ("energy recovery ventilator", r"energy recovery ventilator|\berv\b"),
        ("air handler", r"air handler"),
        ("hybrid heat pump water heater", r"hybrid/heat pump water heater|heat pump water heater"),
        ("tankless water heater", r"tankless water heater"),
        ("induction cooktop", r"induction cooktop"),
        ("mini split system", r"mini split|mini-split"),
        ("solar PV", r"solar|pv system"),
        ("fire sprinkler system", r"sprinkler|nfpa 13d"),
    ]

    for label, pattern in pairs:
        if re.search(pattern, t, re.IGNORECASE):
            systems.append(label)

    return systems


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

    if extracted.get("bathrooms") and extracted["bathrooms"] >= 3:
        add_unique(complexity_factors, "high fixture count")

    if extracted.get("foundation_type") in ["deep_foundation", "basement", "crawlspace"]:
        add_unique(complexity_factors, "special foundation conditions")

    if extracted.get("roof_type") in ["flat", "hip", "standing_seam_metal"]:
        add_unique(complexity_factors, "roofing complexity")

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

    if "natural gas is not permitted" in t or "all-electric" in t or "all electric" in t:
        add_unique(complexity_factors, "all-electric design")
        add_unique(risk_flags, "electrical service sizing")

    if "heat pump" in t:
        add_unique(complexity_factors, "heat pump mechanical system")

    if "energy recovery ventilator" in t or "erv" in t:
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

    if "hillside" in t or "slope" in t or "steep" in t:
        add_unique(risk_flags, "site access and excavation complexity")

    if "retaining wall" in t:
        add_unique(complexity_factors, "retaining structure")
        add_unique(risk_flags, "earth retention coordination")

    return complexity_factors, risk_flags


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
        r"NUMBER OF STORIES[\s\S]{0,80}?PROPOSED NUMBER OF STORIES\s*:\s*([\d.]+)",
        r"(\d+)\s*STORY",
        r"(\d+)\s*STORIES"
    ], text)

    if stories is not None:
        try:
            stories = int(float(stories))
        except Exception:
            stories = None

    bedrooms, bathrooms = extract_bed_bath_counts(text)
    foundation_type = detect_foundation_type(text)
    roof_type = detect_roof_type(text)
    outdoor_features = extract_outdoor_features(text)
    structural_flags = extract_structural_flags(text)
    site_constraints = extract_site_constraints(text)

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
        r"([A-Z][a-zA-Z ]+,\s*CA\s*\d{5})"
    ], text)

    address = find_first([
        r"PROJECT ADDRESS\s*[\s:]*([^\n]+)"
    ], text)

    sprinkler_required = bool(re.search(r"NFPA\s*13D|FIRE SPRINKLER", text, re.IGNORECASE))
    solar_required = bool(re.search(r"SOLAR|PV SYSTEM", text, re.IGNORECASE))
    all_electric = bool(re.search(r"NATURAL GAS IS NOT PERMITTED|ALL[- ]ELECTRIC", text, re.IGNORECASE))

    build_method = detect_build_method(text)
    materials_hint = detect_materials_hint(text)
    mechanical_systems = extract_mechanical_systems(text)
    scope_of_work = extract_scope_items(text)

    estimated_size_sqft = gross_floor_area or conditioned_area or first_floor

    complexity_factors, risk_flags = build_complexity_and_risks(text, {
        "build_method": build_method,
        "stories": stories,
        "garage_sqft": garage_sqft,
        "bathrooms": bathrooms,
        "foundation_type": foundation_type,
        "roof_type": roof_type
    })

    garage_present = bool(garage_sqft or re.search(r"\bgarage\b", text, re.IGNORECASE))

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
        "bedrooms": bedrooms,
        "bathrooms": bathrooms,
        "garage": {
            "present": garage_present,
            "sqft": garage_sqft
        },
        "foundation_type": foundation_type,
        "roof_type": roof_type,
        "outdoor_features": outdoor_features,
        "structural_flags": structural_flags,
        "site_constraints": site_constraints,
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
                item_key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item)
                if item not in (None, "", [], {}) and item_key not in seen:
                    seen.add(item_key)
                    combined.append(item)
            merged[key] = combined
        else:
            if value not in (None, "", [], {}):
                merged[key] = value

    return merged
    
def sanitize_plan_data(data):
    # Bedrooms sanity
    if data.get("bedrooms"):
        if data["bedrooms"] < 0 or data["bedrooms"] > 20:
            data["bedrooms"] = None

    # Bathrooms sanity
    if data.get("bathrooms"):
        if data["bathrooms"] < 0 or data["bathrooms"] > 20:
            data["bathrooms"] = None

    # Stories sanity
    if data.get("stories"):
        if data["stories"] > 10:
            data["stories"] = None

    # Sqft sanity
    if data.get("estimated_size_sqft"):
        if data["estimated_size_sqft"] < 200 or data["estimated_size_sqft"] > 20000:
            data["estimated_size_sqft"] = None

    return data

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
  "bedrooms": number,
  "bathrooms": number,
  "garage": {{
    "present": true,
    "sqft": number
  }},
  "foundation_type": "...",
  "roof_type": "...",
  "outdoor_features": [],
  "structural_flags": [],
  "site_constraints": [],
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
{extracted_text[:12000]}
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
  "bedrooms": number,
  "bathrooms": number,
  "garage": {
    "present": true,
    "sqft": number
  },
  "foundation_type": "...",
  "roof_type": "...",
  "outdoor_features": [],
  "structural_flags": [],
  "site_constraints": [],
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

    try:
        # -------------------------
        # PDF PATH
        # -------------------------
        if is_pdf:
            extracted_text = extract_pdf_text(file_bytes)

            if extracted_text and len(extracted_text.strip()) > 50:
                pre_data = pre_extract_plan_data(extracted_text)

                try:
                    safe_text = limit_text(extracted_text, 12000)
                    raw, ai_parsed = analyze_pdf_text_with_ai(client, safe_text, pre_data)
                    merged = merge_plan_data(pre_data, ai_parsed)

                    return {
                        "mode": "pdf_no_text",
                        "raw": "This PDF appears to be scanned or image-based. Text extraction could not read it. Try uploading a clearer PDF or image screenshot.",
                        "parsed": {
                        "notes": "No readable PDF text extracted. This may be a scanned plan."
                        },
                        "pre_extracted": {}
                    }

                except Exception as e:
                    return {
                        "mode": "pdf_text_preextract_only",
                        "raw": str(e),
                        "parsed": pre_data,
                        "pre_extracted": pre_data
                    }

            return {
                "mode": "pdf_no_text",
                "raw": "PDF uploaded, but no usable text was extracted.",
                "parsed": {},
                "pre_extracted": {}
            }

        # -------------------------
        # IMAGE PATH
        # -------------------------
        try:
            raw, parsed = analyze_image_with_ai(client, file_bytes)

            return {
                "mode": "image",
                "raw": raw,
                "parsed": parsed or {},
                "pre_extracted": {}
            }

        except Exception as e:
            return {
                "mode": "image_error",
                "raw": str(e),
                "parsed": {},
                "pre_extracted": {}
            }

    except Exception as e:
        return {
            "mode": "plan_analysis_error",
            "raw": str(e),
            "parsed": {},
            "pre_extracted": {}
        }

    # =========================
    # IMAGE FALLBACK
    # =========================
    try:
        raw, parsed = analyze_image_with_ai(client, file_bytes)
        return {
            "mode": "image",
            "raw": raw,
            "parsed": parsed,
            "pre_extracted": {}
        }
    except Exception as e:
        return {
            "mode": "error",
            "raw": str(e),
            "parsed": {},
            "pre_extracted": {}
        }
