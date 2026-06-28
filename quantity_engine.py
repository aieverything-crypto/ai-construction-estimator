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


def add_unique(items, item, key_fields):
    key = tuple(str(item.get(k, "")).lower().strip() for k in key_fields)

    for existing in items:
        existing_key = tuple(str(existing.get(k, "")).lower().strip() for k in key_fields)
        if existing_key == key:
            return

    items.append(item)


def extract_area_quantities(text):
    t = text or ""
    areas = []

    patterns = [
        r"\b([A-Za-z0-9 \-/]+?)\s*[:=\-]\s*([\d,]+(?:\.\d+)?)\s*(?:SF|SQ\.?\s*FT\.?|SQUARE FEET)\b",
        r"\b([\d,]+(?:\.\d+)?)\s*(?:SF|SQ\.?\s*FT\.?|SQUARE FEET)\s+([A-Za-z0-9 \-/]+)\b"
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            if len(match.groups()) < 2:
                continue

            # Pattern order can be label/value or value/label
            g1, g2 = match.group(1), match.group(2)

            if re.search(r"\d", g1):
                value = safe_float(g1)
                label = clean_label(g2)
            else:
                label = clean_label(g1)
                value = safe_float(g2)

            if not label or not value:
                continue

            if value < 10 or value > 200000:
                continue

            junk_labels = [
                "sheet",
                "scale",
                "date",
                "page",
                "drawing",
                "general notes",
                "index"
            ]

            if any(j in label.lower() for j in junk_labels):
                continue

            add_unique(
                areas,
                {
                    "label": label,
                    "value": value,
                    "unit": "sqft"
                },
                ["label", "value", "unit"]
            )

    return areas


def extract_linear_quantities(text):
    t = text or ""
    lengths = []

    patterns = [
        r"\b([A-Za-z0-9 \-/]+?)\s*[:=\-]\s*([\d,]+(?:\.\d+)?)\s*(?:LF|L\.F\.|LINEAR FEET)\b",
        r"\b([\d,]+(?:\.\d+)?)\s*(?:LF|L\.F\.|LINEAR FEET)\s+([A-Za-z0-9 \-/]+)\b"
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            g1, g2 = match.group(1), match.group(2)

            if re.search(r"\d", g1):
                value = safe_float(g1)
                label = clean_label(g2)
            else:
                label = clean_label(g1)
                value = safe_float(g2)

            if not label or not value:
                continue

            if value < 1 or value > 10000:
                continue

            add_unique(
                lengths,
                {
                    "label": label,
                    "value": value,
                    "unit": "lf"
                },
                ["label", "value", "unit"]
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

    for match in re.finditer(r"\b(\d+(?:\.\d+)?\s*(?:\"|IN|INCH))\s+(?:WATER|DOMESTIC WATER|WATER SERVICE)\b", t, re.IGNORECASE):
        add_unique(
            services["water"],
            {
                "service_size": clean_label(match.group(1))
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

    patterns = [
        r'\b(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\s+(WATER|DOMESTIC WATER|SEWER|SANITARY|STORM|DRAIN|GAS)\b',
        r'\b(WATER|DOMESTIC WATER|SEWER|SANITARY|STORM|DRAIN|GAS)\s+(?:LINE|PIPE|SERVICE)?\s*[:\-]?\s*(\d+(?:\.\d+)?)\s*(?:"|IN|INCH)\b'
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, t, re.IGNORECASE):
            g1, g2 = match.group(1), match.group(2)

            if re.search(r"\d", g1):
                size = g1
                system = g2
            else:
                system = g1
                size = g2

            add_unique(
                pipes,
                {
                    "system": clean_label(system).lower(),
                    "size": f'{size}"'
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
        "windows": None,
        "doors": None,
        "sliders": None,
        "garage_doors": None
    }

    window_marks = re.findall(r"\bW\d+\b", t, re.IGNORECASE)
    door_marks = re.findall(r"\bD\d+\b", t, re.IGNORECASE)

    if window_marks:
        counts["windows"] = len(set(m.upper() for m in window_marks))

    if door_marks:
        counts["doors"] = len(set(m.upper() for m in door_marks))

    sliders = re.findall(r"\bSLIDER|SLIDING DOOR|MULTI[- ]SLIDE\b", t, re.IGNORECASE)
    if sliders:
        counts["sliders"] = len(sliders)

    garage_doors = re.findall(r"\bGARAGE DOOR\b", t, re.IGNORECASE)
    if garage_doors:
        counts["garage_doors"] = len(garage_doors)

    return counts

def extract_quantity_data(text):
    t = text or ""

    return {
        "areas": extract_area_quantities(t),
        "linear_lengths": extract_linear_quantities(t),
        "walls": extract_wall_quantities(t),
        "structural": extract_structural_quantities(t),
        "services": extract_service_quantities(t),
        "pipe_sizes": extract_pipe_sizes(t),
        "slab_thicknesses": extract_slab_thicknesses(t),
        "lumber_sizes": extract_lumber_sizes(t),
        "roof_quantities": extract_roof_quantities(t),
        "door_window_counts": extract_door_window_counts(t)
    }

