import re


def safe_float(value):
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return None


def clean_label(value, max_len=60):
    if not value:
        return None

    cleaned = " ".join(str(value).split())
    cleaned = re.sub(r"[^a-zA-Z0-9\s\-/().#\"]", "", cleaned)

    return cleaned[:max_len].strip()

AREA_LABEL_MAP = {
    "garage": "garage_sqft",
    "garage area": "garage_sqft",
    "garage floor area": "garage_sqft",

    "living area": "living_sqft",
    "conditioned area": "conditioned_sqft",
    "conditioned floor area": "conditioned_sqft",
    "energy model conditioned area": "conditioned_sqft",

    "first floor": "first_floor_sqft",
    "1st floor": "first_floor_sqft",
    "first floor gross area": "first_floor_sqft",
    "1st floor gross area": "first_floor_sqft",

    "second floor": "second_floor_sqft",
    "2nd floor": "second_floor_sqft",
    "second floor gross area": "second_floor_sqft",
    "2nd floor gross area": "second_floor_sqft",

    "total building area": "total_building_sqft",
    "gross floor area": "gross_floor_sqft",
    "proposed gross floor area": "gross_floor_sqft",

    "lot area": "lot_area_sqft",

    "deck": "deck_sqft",
    "deck area": "deck_sqft",

    "patio": "patio_sqft",
    "patio area": "patio_sqft",

    "porch": "porch_sqft",
    "porch area": "porch_sqft",

    "roof area": "roof_sqft",
}

def classify_area_label(label):
    if not label:
        return None

    normalized = clean_label(label)
    if not normalized:
        return None

    normalized = normalized.lower().strip()

    # Exact match first
    if normalized in AREA_LABEL_MAP:
        return AREA_LABEL_MAP[normalized]

    # Strong phrase match
    for known_label, category in AREA_LABEL_MAP.items():
        if known_label in normalized:
            return category

    return None

def add_unique(items, item, key_fields):
    key = tuple(str(item.get(k, "")).lower().strip() for k in key_fields)

    for existing in items:
        existing_key = tuple(str(existing.get(k, "")).lower().strip() for k in key_fields)
        if existing_key == key:
            return

    items.append(item)

def build_area_summary(area_items):
    summary = {}

    for item in area_items or []:
        category = item.get("category")
        value = item.get("value")

        if not category or not value:
            continue

        # First strong contextual hit wins for now
        if category not in summary:
            summary[category] = value

    return summary

def extract_area_quantities(text):
    t = text or ""
    areas = []

    lines = [
        " ".join(line.strip().split())
        for line in t.splitlines()
        if line.strip()
    ]

    sf_pattern = re.compile(
        r"([\d,]+(?:\.\d+)?)\s*(?:SF|SQ\.?\s*FT\.?|SQUARE FEET)\b",
        re.IGNORECASE
    )

    for i, line in enumerate(lines):

        match = sf_pattern.search(line)
        if not match:
            continue

        value = safe_float(match.group(1))

        if not value or value < 10 or value > 200000:
            continue

        # First try to determine label from same line
        before_value = line[:match.start()].strip(" :=-")
        category = classify_area_label(before_value)
        label = before_value

        # If same line doesn't provide a useful label,
        # look at neighboring lines.
        if not category:
            candidate_lines = []

            if i > 0:
                candidate_lines.append(lines[i - 1])

            if i > 1:
                candidate_lines.append(lines[i - 2])

            if i + 1 < len(lines):
                candidate_lines.append(lines[i + 1])

            for candidate in candidate_lines:
                candidate_category = classify_area_label(candidate)

                if candidate_category:
                    category = candidate_category
                    label = candidate
                    break

        # Ignore unrecognized SF values rather than guessing
        if not category:
            continue

        item = {
            "label": clean_label(label),
            "category": category,
            "value": value,
            "unit": "sqft"
        }

        add_unique(
            areas,
            item,
            ["category", "value", "unit"]
        )

    return areas


LINEAR_LABEL_MAP = {
    "retaining wall": "retaining_wall",
    "stem wall": "stem_wall",
    "foundation wall": "foundation_wall",
    "footing": "footing",
    "continuous footing": "footing",
    "fence": "fence",
    "guardrail": "guardrail",
    "guard rail": "guardrail",
    "handrail": "handrail",
    "gutter": "gutter",
    "ridge": "roof_ridge",
    "valley": "roof_valley",
    "curb": "curb",
    "sewer lateral": "sewer_lateral",
    "water service": "water_service"
}


def classify_linear_label(label):
    if not label:
        return None

    normalized = clean_label(label)

    if not normalized:
        return None

    normalized = normalized.lower()

    for known_label, category in LINEAR_LABEL_MAP.items():
        if known_label in normalized:
            return category

    return None

def extract_linear_quantities(text):
    t = text or ""
    lengths = []

    lines = [
        " ".join(line.strip().split())
        for line in t.splitlines()
        if line.strip()
    ]

    lf_pattern = re.compile(
        r"([\d,]+(?:\.\d+)?)\s*(?:LF|L\.F\.|LINEAR FEET)\b",
        re.IGNORECASE
    )

    for i, line in enumerate(lines):
        match = lf_pattern.search(line)

        if not match:
            continue

        value = safe_float(match.group(1))

        if not value or value < 1 or value > 10000:
            continue

        before_value = line[:match.start()].strip(" :=-")

        category = classify_linear_label(before_value)
        label = before_value

        if not category:
            candidate_lines = []

            if i > 0:
                candidate_lines.append(lines[i - 1])

            if i > 1:
                candidate_lines.append(lines[i - 2])

            if i + 1 < len(lines):
                candidate_lines.append(lines[i + 1])

            for candidate in candidate_lines:
                candidate_category = classify_linear_label(candidate)

                if candidate_category:
                    category = candidate_category
                    label = candidate
                    break

        # Ignore weak / unlabeled measurements
        if not category:
            continue

        add_unique(
            lengths,
            {
                "label": clean_label(label),
                "category": category,
                "value": value,
                "unit": "lf"
            },
            ["category", "value", "unit"]
        )

    return lengths


def extract_structural_quantities(text):
    t = text or ""

    footings = []
    steel_beams = []
    wood_members = []

    footing_patterns = [
        r"\b(?:FOOTING|FTG)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*[\"']?\s*[xX]\s*(\d+(?:\.\d+)?)\s*[\"']?",
        r"\b(\d+(?:\.\d+)?)\s*[\"']?\s*[xX]\s*(\d+(?:\.\d+)?)\s*[\"']?\s*(?:FOOTING|FTG)\b"
    ]

    for pattern in footing_patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                footings,
                {
                    "width": safe_float(match.group(1)),
                    "depth": safe_float(match.group(2)),
                    "unit": "in"
                },
                ["width", "depth", "unit"]
            )

    for match in re.finditer(r"\b(W\d{1,2}\s*[xX]\s*\d{1,3})\b", t, re.IGNORECASE):
        add_unique(
            steel_beams,
            {
                "type": match.group(1).upper().replace(" ", ""),
                "material": "steel"
            },
            ["type", "material"]
        )

    wood_patterns = [
        r"\b(\d+\s*[xX]\s*\d+)\s*(?:JOIST|RAFTER|STUD|BEAM|HEADER)\b",
        r"\b(?:LVL|GLULAM|PSL)\s*[\w\s\"xX\-/.]+"
    ]

    for pattern in wood_patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                wood_members,
                {
                    "description": clean_label(match.group(0)),
                    "material": "wood"
                },
                ["description", "material"]
            )

    return {
        "footings": footings,
        "steel_beams": steel_beams,
        "wood_members": wood_members
    }


def extract_wall_quantities(text):
    t = text or ""
    walls = []

    if not re.search(r"retaining wall|stem wall|shear wall|foundation wall", t, re.IGNORECASE):
        return walls

    wall_type = "wall"
    if re.search(r"retaining wall", t, re.IGNORECASE):
        wall_type = "retaining wall"
    elif re.search(r"stem wall", t, re.IGNORECASE):
        wall_type = "stem wall"
    elif re.search(r"shear wall", t, re.IGNORECASE):
        wall_type = "shear wall"
    elif re.search(r"foundation wall", t, re.IGNORECASE):
        wall_type = "foundation wall"

    height = None
    length = None

    height_match = re.search(
        r"\b(?:HEIGHT|HT|HIGH)\s*[:=\-]?\s*(\d+(?:\.\d+)?)\s*(?:FT|FEET|')\b|\b(\d+(?:\.\d+)?)\s*(?:FT|FEET|')\s*(?:HIGH|HEIGHT|HT)\b",
        t,
        re.IGNORECASE
    )

    if height_match:
        height = safe_float(height_match.group(1) or height_match.group(2))

    length_match = re.search(
        r"\b(?:LENGTH|LEN)\s*[:=\-]?\s*(\d+(?:\.\d+)?)\s*(?:LF|FT|FEET|')\b|\b(\d+(?:\.\d+)?)\s*(?:LF|LINEAR FEET)\b",
        t,
        re.IGNORECASE
    )

    if length_match:
        length = safe_float(length_match.group(1) or length_match.group(2))

    add_unique(
        walls,
        {
            "type": wall_type,
            "length": length,
            "height": height,
            "length_unit": "lf" if length else None,
            "height_unit": "ft" if height else None
        },
        ["type", "length", "height"]
    )

    return walls


def extract_service_quantities(text):
    t = text or ""
    services = {
        "electrical": [],
        "water": [],
        "sewer": [],
        "gas": []
    }

    for match in re.finditer(r"\b([1248]\d{2})\s*(?:AMP|AMPS|A)\b", t, re.IGNORECASE):
        add_unique(
            services["electrical"],
            {
                "service_size": f"{match.group(1)}A"
            },
            ["service_size"]
        )

    water_patterns = [
        r'\b(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\s+(?:DOMESTIC\s+)?WATER\s+(?:SERVICE|LINE|MAIN)\b',
        r'\b(?:DOMESTIC\s+)?WATER\s+(?:SERVICE|LINE|MAIN)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\b'
    ]

    for pattern in water_patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                services["water"],
                {
                    "service_size": f'{match.group(1)}"'
                },
                ["service_size"]
            )

    if re.search(r"public sewer|sanitary sewer|sewer lateral", t, re.IGNORECASE):
        add_unique(services["sewer"], {"type": "public sewer / sewer lateral"}, ["type"])

    if re.search(r"septic", t, re.IGNORECASE):
        add_unique(services["sewer"], {"type": "septic"}, ["type"])

    if re.search(r"natural gas|gas service|gas meter", t, re.IGNORECASE):
        add_unique(services["gas"], {"type": "gas service"}, ["type"])

    if re.search(r"all[- ]electric|natural gas is not permitted|no gas", t, re.IGNORECASE):
        add_unique(services["gas"], {"type": "no gas / all-electric"}, ["type"])

    return services

def extract_pipe_sizes(text):
    t = text or ""
    pipes = []

    # -----------------------------
    # WATER
    # -----------------------------
    water_patterns = [
        r'\b(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\s+(?:DOMESTIC\s+)?WATER\s+(?:SERVICE|LINE|MAIN)\b',
        r'\b(?:DOMESTIC\s+)?WATER\s+(?:SERVICE|LINE|MAIN)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\b'
    ]

    for pattern in water_patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                pipes,
                {
                    "system": "water",
                    "size": f'{match.group(1)}"'
                },
                ["system", "size"]
            )

    # -----------------------------
    # SEWER
    # -----------------------------
    sewer_patterns = [
        r'\b(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\s+(?:SANITARY\s+)?SEWER\s+(?:LINE|LATERAL|MAIN|PIPE)?\b',
        r'\b(?:SANITARY\s+)?SEWER\s+(?:LINE|LATERAL|MAIN|PIPE)?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\b'
    ]

    for pattern in sewer_patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                pipes,
                {
                    "system": "sewer",
                    "size": f'{match.group(1)}"'
                },
                ["system", "size"]
            )

    # -----------------------------
    # STORM DRAIN
    # -----------------------------
    storm_patterns = [
        r'\b(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\s+(?:STORM\s+DRAIN|STORM\s+LINE|STORM\s+PIPE)\b',
        r'\b(?:STORM\s+DRAIN|STORM\s+LINE|STORM\s+PIPE)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\b'
    ]

    for pattern in storm_patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                pipes,
                {
                    "system": "storm drain",
                    "size": f'{match.group(1)}"'
                },
                ["system", "size"]
            )

    # -----------------------------
    # GAS
    # -----------------------------
    gas_patterns = [
        r'\b(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\s+GAS\s+(?:SERVICE|LINE|MAIN|PIPE)\b',
        r'\bGAS\s+(?:SERVICE|LINE|MAIN|PIPE)\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\b'
    ]

    for pattern in gas_patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                pipes,
                {
                    "system": "gas",
                    "size": f'{match.group(1)}"'
                },
                ["system", "size"]
            )

    return pipes


def extract_slab_thicknesses(text):
    t = text or ""
    slabs = []

    patterns = [
        r'\b(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\s+(?:THICK\s+)?SLAB\b',
        r'\bSLAB\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\b',
        r'\b(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\s+CONCRETE\s+SLAB\b'
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                slabs,
                {
                    "description": "concrete slab",
                    "thickness": safe_float(match.group(1)),
                    "unit": "in"
                },
                ["description", "thickness", "unit"]
            )

    return slabs


def extract_lumber_sizes(text):
    t = text or ""
    lumber = []

    patterns = [
        r"\b(2\s*[xX]\s*\d+|4\s*[xX]\s*\d+|6\s*[xX]\s*\d+|8\s*[xX]\s*\d+)\s*(STUD|JOIST|RAFTER|BEAM|HEADER|PLATE)?\b",
        r"\b(LVL|PSL|GLULAM)\s*[\w\s\"xX\-/.]{0,40}\b"
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            add_unique(
                lumber,
                {
                    "description": clean_label(match.group(0)),
                    "material": "wood"
                },
                ["description", "material"]
            )

    return lumber


def extract_roof_quantities(text):
    t = text or ""
    roof = {
        "area_sqft": None,
        "pitch": None,
        "materials": []
    }

    area = re.search(
        r"\bROOF\s+(?:AREA)?\s*[:=\-]?\s*([\d,]+(?:\.\d+)?)\s*(?:SF|SQ\.?\s*FT\.?|SQUARE FEET)\b",
        t,
        re.IGNORECASE
    )

    if area:
        roof["area_sqft"] = safe_float(area.group(1))

    pitch = re.search(r"\bROOF\s+PITCH\s*[:=\-]?\s*(\d+\s*[:/]\s*\d+)\b", t, re.IGNORECASE)
    if pitch:
        roof["pitch"] = pitch.group(1).replace(" ", "")

    material_patterns = [
        ("standing seam metal", r"standing seam metal"),
        ("composite roofing", r"composite roofing|composition shingle|asphalt shingle"),
        ("built-up roof", r"built[- ]up roof|granulated cap sheet"),
        ("tile roofing", r"tile roof|tile roofing")
    ]

    for label, pattern in material_patterns:
        if re.search(pattern, t, re.IGNORECASE):
            roof["materials"].append(label)

    roof["materials"] = list(dict.fromkeys(roof["materials"]))

    return roof


def extract_door_window_counts(text):
    t = text or ""

    counts = {
        "window_types_detected": None,
        "door_types_detected": None,
        "slider_mentions": None,
        "garage_door_mentions": None
    }

    window_marks = re.findall(
        r"\bW\d+\b",
        t,
        re.IGNORECASE
    )

    door_marks = re.findall(
        r"\bD\d+\b",
        t,
        re.IGNORECASE
    )

    if window_marks:
        counts["window_types_detected"] = len(
            set(m.upper() for m in window_marks)
        )

    if door_marks:
        counts["door_types_detected"] = len(
            set(m.upper() for m in door_marks)
        )

    sliders = re.findall(
        r"\bSLIDER\b|\bSLIDING DOOR\b|\bMULTI[- ]SLIDE\b",
        t,
        re.IGNORECASE
    )

    if sliders:
        counts["slider_mentions"] = len(sliders)

    garage_doors = re.findall(
        r"\bGARAGE DOOR\b",
        t,
        re.IGNORECASE
    )

    if garage_doors:
        counts["garage_door_mentions"] = len(garage_doors)

    return counts

def normalize_quantity_candidate(
    category,
    label,
    value,
    unit,
    page_number=None,
    page_type="unknown",
    context=None
):
    """
    Convert an extracted measurement into a standard candidate
    that can later be reconciled at the project level.
    """

    label_clean = (label or "").strip()
    label_upper = label_clean.upper()

    quantity_type = "unknown"
    scope = "unknown"

    # -------------------------
    # AREA CLASSIFICATION
    # -------------------------

    if category == "area":

        if "GARAGE" in label_upper:
            quantity_type = "garage_area"
            scope = "garage"

        elif "DECK" in label_upper:
            quantity_type = "deck_area"
            scope = "exterior"

        elif "PATIO" in label_upper:
            quantity_type = "patio_area"
            scope = "exterior"

        elif "PORCH" in label_upper:
            quantity_type = "porch_area"
            scope = "exterior"

        elif (
            "CONDITIONED" in label_upper
            or "LIVING AREA" in label_upper
        ):
            quantity_type = "conditioned_area"
            scope = "project"

        elif (
            "1ST FLOOR" in label_upper
            or "FIRST FLOOR" in label_upper
        ):
            quantity_type = "first_floor_area"
            scope = "floor"

        elif (
            "2ND FLOOR" in label_upper
            or "SECOND FLOOR" in label_upper
        ):
            quantity_type = "second_floor_area"
            scope = "floor"

        elif "GROSS FLOOR AREA" in label_upper:
            quantity_type = "gross_floor_area"
            scope = "project"

        elif "TOTAL" in label_upper:
            quantity_type = "total_area"
            scope = "project"

        else:
            quantity_type = "area"

    # -------------------------
    # WALL CLASSIFICATION
    # -------------------------

    elif category == "wall":
        quantity_type = "wall"
        scope = "building"

        if "RETAINING" in label_upper:
            quantity_type = "retaining_wall"

        elif "STEM WALL" in label_upper:
            quantity_type = "stem_wall"

        elif "SHEAR" in label_upper:
            quantity_type = "shear_wall"

    # -------------------------
    # CONCRETE
    # -------------------------

    elif category == "concrete":
        quantity_type = "concrete"
        scope = "building"

        if "SLAB" in label_upper:
            quantity_type = "concrete_slab"

        elif "FOOTING" in label_upper:
            quantity_type = "footing"

    # -------------------------
    # PIPE / UTILITIES
    # -------------------------

    elif category == "pipe":
        quantity_type = "pipe_size"
        scope = "utility"

    return {
        "category": category,
        "quantity_type": quantity_type,
        "label": label_clean,
        "value": value,
        "unit": unit,
        "page": page_number,
        "page_type": page_type or "unknown",
        "scope": scope,
        "context": context
    }

def extract_quantity_data(
    text,
    page_number=None,
    page_type="unknown"
):
    areas = extract_area_quantities(text)
    linear_lengths = extract_linear_quantities(text)
    walls = extract_wall_quantities(text)
    structural = extract_structural_quantities(text)
    services = extract_service_quantities(text)
    pipe_sizes = extract_pipe_sizes(text)
    slab_thicknesses = extract_slab_thicknesses(text)
    lumber_sizes = extract_lumber_sizes(text)
    roof_quantities = extract_roof_quantities(text)
    door_window_counts = extract_door_window_counts(text)

    # --------------------------------
    # PAGE-TYPE QUANTITY GATING
    # --------------------------------

    area_allowed = {
        "cover_sheet",
        "floor_plan",
        "site_civil",
        "roof_plan"
    }

    linear_allowed = {
        "site_civil",
        "foundation",
        "structural",
        "roof_plan",
        "plumbing"
    }

    wall_allowed = {
        "site_civil",
        "foundation",
        "structural"
    }

    structural_allowed = {
        "foundation",
        "structural"
    }

    service_allowed = {
        "cover_sheet",
        "site_civil",
        "electrical",
        "plumbing"
    }

    pipe_allowed = {
        "site_civil",
        "plumbing"
    }

    slab_allowed = {
        "foundation",
        "structural"
    }

    lumber_allowed = {
        "floor_plan",
        "foundation",
        "structural",
        "roof_plan"
    }

    roof_allowed = {
        "cover_sheet",
        "floor_plan",
        "roof_plan"
    }

    openings_allowed = {
        "floor_plan",
        "details"
    }

    if page_type not in area_allowed:
        areas = []

    if page_type not in linear_allowed:
        linear_lengths = []

    if page_type not in wall_allowed:
        walls = []

    if page_type not in structural_allowed:
        structural = {
            "footings": [],
            "steel_beams": [],
            "wood_members": []
        }

    if page_type not in service_allowed:
        services = {
            "electrical": [],
            "water": [],
            "sewer": [],
            "gas": []
        }

    if page_type not in pipe_allowed:
        pipe_sizes = []

    if page_type not in slab_allowed:
        slab_thicknesses = []

    if page_type not in lumber_allowed:
        lumber_sizes = []

    if page_type not in roof_allowed:
        roof_quantities = {
            "area_sqft": None,
            "pitch": None,
            "materials": []
        }

    if page_type not in openings_allowed:
        door_window_counts = {
            "window_types_detected": None,
            "door_types_detected": None,
            "slider_mentions": None,
            "garage_door_mentions": None
        }

    # --------------------------------
    # ATTACH SOURCE INFORMATION
    # --------------------------------

    for item in areas:
        item["source_page"] = page_number
        item["page_type"] = page_type

    for item in linear_lengths:
        item["source_page"] = page_number
        item["page_type"] = page_type

    for item in walls:
        item["source_page"] = page_number
        item["page_type"] = page_type

    for group in structural.values():
        for item in group:
            item["source_page"] = page_number
            item["page_type"] = page_type

    for group in services.values():
        for item in group:
            item["source_page"] = page_number
            item["page_type"] = page_type

    for item in pipe_sizes:
        item["source_page"] = page_number
        item["page_type"] = page_type

    for item in slab_thicknesses:
        item["source_page"] = page_number
        item["page_type"] = page_type

    for item in lumber_sizes:
        item["source_page"] = page_number
        item["page_type"] = page_type

    if roof_quantities.get("area_sqft") or roof_quantities.get("pitch") or roof_quantities.get("materials"):
        roof_quantities["source_page"] = page_number
        roof_quantities["page_type"] = page_type

    return {
        "areas": areas,
        "area_summary": build_area_summary(areas),
        "linear_lengths": linear_lengths,
        "walls": walls,
        "structural": structural,
        "services": services,
        "pipe_sizes": pipe_sizes,
        "slab_thicknesses": slab_thicknesses,
        "lumber_sizes": lumber_sizes,
        "roof_quantities": roof_quantities,
        "door_window_counts": door_window_counts
    }
