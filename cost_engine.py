cost_per_sqft = {
    "residential": (180, 350),
    "commercial": (220, 500),
    "industrial": (250, 650),
    "remodel": (120, 300)
}


def detect_project_type(project, description):
    text = f"{project or ''} {description or ''}".lower()

    if any(word in text for word in ["warehouse", "factory", "industrial", "plant"]):
        return "industrial"

    if any(word in text for word in [
        "office", "retail", "store", "restaurant",
        "apartment", "complex", "multifamily",
        "mixed use", "commercial"
    ]):
        return "commercial"

    if any(word in text for word in ["remodel", "renovation", "addition", "tenant improvement"]):
        return "remodel"

    return "residential"


def adjustments(materials, city, timeline, description):
    material_factor = 1.0
    labor_factor = 1.0
    timeline_factor = 1.0
    site_factor = 1.0

    materials_text = (materials or "").lower()
    city_text = (city or "").lower()
    timeline_text = (timeline or "").lower()
    description_text = (description or "").lower()

    if "steel" in materials_text:
        material_factor += 0.15
    if "concrete" in materials_text:
        material_factor += 0.10
    if "luxury" in materials_text or "premium" in materials_text or "high end" in materials_text:
        material_factor += 0.20
    if "glass" in materials_text:
        material_factor += 0.08

    if any(x in city_text for x in ["san francisco", "new york", "seattle", "boston", "dubai"]):
        labor_factor += 0.30
    elif any(x in city_text for x in ["los angeles", "san jose", "san diego", "las vegas"]):
        labor_factor += 0.10

    if "rush" in timeline_text or "asap" in timeline_text:
        timeline_factor += 0.20

    if any(x in description_text for x in ["slope", "steep", "hillside"]):
        site_factor += 0.20
    if any(x in description_text for x in ["tight lot", "urban infill", "limited access"]):
        site_factor += 0.10
    if any(x in description_text for x in ["remote", "island", "antarctica"]):
        site_factor += 0.30

    return material_factor, labor_factor, timeline_factor, site_factor


def build_cost_summary(
    project_type,
    size_sqft,
    city,
    low,
    high,
    base_cost,
    total_cost,
    material_factor,
    labor_factor,
    timeline_factor,
    site_factor
):
    return {
        "project_type": project_type,
        "size_sqft": size_sqft,
        "city": city,
        "base_range_low_per_sqft": low,
        "base_range_high_per_sqft": high,
        "base_cost": base_cost,
        "total_cost": total_cost,
        "material_factor": material_factor,
        "labor_factor": labor_factor,
        "timeline_factor": timeline_factor,
        "site_factor": site_factor
    }


# -----------------------------
# SCOPE NORMALIZATION
# -----------------------------
def normalize_scope(scope_text):
    if not scope_text:
        return "ground_up"

    text = scope_text.lower()

    if any(x in text for x in ["ground", "full", "new build", "entire"]):
        return "ground_up"

    if "frame" in text:
        return "framing"

    if any(x in text for x in ["foundation", "footing", "slab"]):
        return "foundation"

    if any(x in text for x in ["retrofit", "remodel", "renovation"]):
        return "remodel"

    if any(x in text for x in ["roof", "shingle"]):
        return "roofing"

    if any(x in text for x in ["electrical", "wiring"]):
        return "electrical"

    if any(x in text for x in ["plumbing", "pipes"]):
        return "plumbing"

    if "hvac" in text:
        return "hvac"

    if any(x in text for x in ["interior", "finish", "drywall"]):
        return "interior"

    return "ground_up"


# -----------------------------
# FIXED SCOPE COST (IMPORTANT)
# -----------------------------
def apply_scope_cost(base_cost_per_sqft, scope, city=None):
    scope_costs = {
        "framing": (20, 45),
        "foundation": (15, 40),
        "roofing": (10, 30),
        "electrical": (10, 25),
        "plumbing": (12, 30),
        "hvac": (10, 25),
        "interior": (30, 80),
        "remodel": (60, 150)
    }

    if scope not in scope_costs:
        return base_cost_per_sqft if base_cost_per_sqft else 200

    low, high = scope_costs[scope]
    return (low + high) / 2


# -----------------------------
# ROOM COST ENGINE
# -----------------------------
def estimate_rooms(rooms, location_factor=1.0):
    room_costs = {
        "kitchen": (150, 300),
        "bathroom": (200, 400),
        "bedroom": (80, 150),
        "living_room": (100, 200)
    }

    results = []
    total = 0

    for r in rooms:
        r_type = r.get("type")
        count = r.get("count", 1)
        size = r.get("avg_size", 150)

        if r_type not in room_costs:
            continue

        low, high = room_costs[r_type]
        cost_per_sqft = (low + high) / 2

        room_total = cost_per_sqft * size * count * location_factor

        results.append({
            "type": r_type,
            "count": count,
            "size": size,
            "cost": round(room_total)
        })

        total += room_total

    return results, total
