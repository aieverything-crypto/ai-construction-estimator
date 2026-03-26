from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os
import re
import json

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# -----------------------------
# OPENAI INIT
# -----------------------------
client = None
try:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        client = OpenAI(api_key=api_key)
except Exception as e:
    print("OpenAI init error:", e)

# -----------------------------
# BASE COST DATABASE ($ / sqft)
# -----------------------------
cost_per_sqft = {
    "residential": (180, 350),
    "commercial": (220, 500),
    "industrial": (250, 650),
    "remodel": (120, 300)
}

# -----------------------------
# MARKET-DATA-READY TUNING
# Update these periodically from BLS/BEA later
# -----------------------------
MARKET_FACTORS = {
    "materials_index": 1.00,   # hook for BLS PPI
    "labor_index": 1.00,       # hook for BLS ECI / wage trend
    "general_inflation": 1.00  # hook for future escalation
}

# -----------------------------
# AI NORMALIZATION
# Converts messy human input into cleaner structured values.
# -----------------------------
def normalize_inputs_with_ai(project, size, materials, budget, timeline, city, description):
    if not client:
        return None

    user_input = f"""
Project: {project}
Size: {size}
Materials: {materials}
Budget: {budget}
Timeline: {timeline}
Location: {city}
Description: {description}
"""

    prompt = f"""
Convert this construction project input into JSON.

Rules:
- Convert all size inputs to square feet
- Convert all money inputs to USD
- Convert timeline to months
- If budget is invalid or not money, return null for budget_usd
- Preserve the location text
- Infer project category from context if possible

Return ONLY JSON in this shape:
{{
  "size_sqft": number or null,
  "budget_usd": number or null,
  "timeline_months": number or null,
  "location_text": string or null,
  "project_category": string or null
}}

Input:
{user_input}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print("AI normalization failed:", e)
        return None

# -----------------------------
# PARSE BUDGET
# Handles:
# 10^6 dollars
# 1e6
# 5 times 10 to the 7 usd
# 50 million
# 10M
# -----------------------------
def parse_budget(text):
    if not text:
        return 0

    text = str(text).lower().replace(",", "").strip()

    # invalid weight units for money
    if any(x in text for x in [" lb", " lbs", " pound", " pounds", " kg", " kilogram", " kilograms"]):
        return None

    # currency multipliers to USD (simple approximation)
    currency_multiplier = 1.0
    if "€" in text or " eur" in text or " euro" in text:
        currency_multiplier = 1.08
    elif "£" in text or " gbp" in text or " pound sterling" in text:
        currency_multiplier = 1.27
    elif " cad" in text or "canadian dollar" in text:
        currency_multiplier = 0.74
    elif " aud" in text or "australian dollar" in text:
        currency_multiplier = 0.66
    elif " jpy" in text or " yen" in text:
        currency_multiplier = 0.0067

    # 5 times 10 to the 7
    m = re.search(r"(\d+\.?\d*)\s*(times|x)\s*10\s*(to the|\^)\s*(\d+)", text)
    if m:
        base = float(m.group(1))
        exponent = int(m.group(4))
        return base * (10 ** exponent) * currency_multiplier

    # 10^6
    m = re.search(r"(\d+\.?\d*)\s*\^\s*(\d+)", text)
    if m:
        base = float(m.group(1))
        exponent = int(m.group(2))
        return (base ** exponent) * currency_multiplier

    # 1e6
    m = re.search(r"(\d+\.?\d*)e(\d+)", text)
    if m:
        base = float(m.group(1))
        exponent = int(m.group(2))
        return base * (10 ** exponent) * currency_multiplier

    nums = re.findall(r"\d+\.?\d*", text)
    if not nums:
        return 0

    value = float(nums[0])

    if any(x in text for x in ["billion", " bn", " b "]):
        value *= 1_000_000_000
    elif any(x in text for x in ["million", " mm", " m "]):
        value *= 1_000_000
    elif any(x in text for x in ["thousand", " k "]):
        value *= 1_000

    return value * currency_multiplier

# -----------------------------
# PARSE SIZE
# Handles:
# 3780 meters squared
# 3000 meter to the power of 2
# 3000 sqm / m2 / m^2
# 30x50 ft
# 30 by 50
# -----------------------------
def parse_size(text):
    if not text:
        return 2000

    raw = str(text).lower().replace(",", "").strip()

    normalized = raw
    normalized = normalized.replace("meters squared", "sqm")
    normalized = normalized.replace("meter squared", "sqm")
    normalized = normalized.replace("meters square", "sqm")
    normalized = normalized.replace("meter square", "sqm")
    normalized = normalized.replace("square meters", "sqm")
    normalized = normalized.replace("square meter", "sqm")
    normalized = normalized.replace("sq meters", "sqm")
    normalized = normalized.replace("sq meter", "sqm")
    normalized = normalized.replace("meter to the power of 2", "sqm")
    normalized = normalized.replace("meters to the power of 2", "sqm")
    normalized = normalized.replace("m^2", "sqm")
    normalized = normalized.replace("m2", "sqm")

    # direct sqm
    if "sqm" in normalized:
        nums = re.findall(r"\d+\.?\d*", normalized)
        if nums:
            return float(nums[0]) * 10.7639

    # metric dimensions like 20m x 30m
    if "x" in normalized and "m" in normalized:
        nums = re.findall(r"\d+\.?\d*", normalized)
        if len(nums) >= 2:
            sqm = float(nums[0]) * float(nums[1])
            return sqm * 10.7639

    # imperial dimensions
    tmp = normalized.replace("square feet", "sqft")
    tmp = tmp.replace("square foot", "sqft")
    tmp = tmp.replace("sq ft", "sqft")
    tmp = tmp.replace("feet", "ft")
    tmp = tmp.replace("foot", "ft")
    tmp = re.sub(r"\s*by\s*", "x", tmp)
    tmp = re.sub(r"\s*x\s*", "x", tmp)

    if "x" in tmp:
        nums = re.findall(r"\d+\.?\d*", tmp)
        if len(nums) >= 2:
            return float(nums[0]) * float(nums[1])

    nums = re.findall(r"\d+\.?\d*", tmp)
    return float(nums[0]) if nums else 2000

# -----------------------------
# PARSE TIMELINE
# Handles:
# 18 months
# 1.5 years
# 1 decade
# 1.5 decades
# -----------------------------
def parse_timeline(text):
    if not text:
        return 12

    text = str(text).lower().strip()
    nums = re.findall(r"\d+\.?\d*", text)
    if not nums:
        return 12

    value = float(nums[0])

    if "decade" in text:
        return value * 120
    if "year" in text or "yr" in text:
        return value * 12
    if "month" in text:
        return value

    return value

# -----------------------------
# PROJECT TYPE DETECTION
# -----------------------------
def detect_project_type(project, description, ai_project_category=None):
    if ai_project_category in cost_per_sqft:
        return ai_project_category

    text = f"{project or ''} {description or ''}".lower()

    if any(x in text for x in ["warehouse", "factory", "plant", "industrial"]):
        return "industrial"
    if any(x in text for x in ["office", "retail", "restaurant", "commercial", "store"]):
        return "commercial"
    if any(x in text for x in ["remodel", "renovation", "addition", "tenant improvement"]):
        return "remodel"
    return "residential"

# -----------------------------
# COMPLEXITY ENGINE
# -----------------------------
def get_project_complexity(project, description):
    text = f"{project or ''} {description or ''}".lower()

    factor = 1.0
    flags = []

    if "traditional japanese" in text or "japanese home" in text:
        factor += 0.35
        flags.append("specialized design / craftsmanship")

    if "luxury" in text or "high-end" in text or "estate" in text:
        factor += 0.50
        flags.append("luxury finishes")

    if "pond" in text or "koi" in text or "landscaping" in text:
        factor += 0.15
        flags.append("site / landscaping features")

    if "basement" in text:
        factor += 0.15
        flags.append("basement complexity")

    if "underground" in text or "bunker" in text:
        factor += 2.0
        flags.append("underground construction")

    if "hospital" in text or "lab" in text or "medical" in text:
        factor += 1.4
        flags.append("specialized MEP / compliance")

    if "steep slope" in text or "hillside" in text or "slope" in text:
        factor += 0.30
        flags.append("difficult site / slope work")

    return factor, flags

# -----------------------------
# LOCATION MULTIPLIER
# Market-data-ready approximation layer
# -----------------------------
def get_location_multiplier(city):
    if not city:
        return 1.0

    text = city.lower()

    # very high cost
    if any(x in text for x in ["hawaii", "honolulu", "maui", "kauai"]):
        return 1.40
    if any(x in text for x in ["san francisco", "new york city", "manhattan"]):
        return 1.35

    # high cost
    if any(x in text for x in ["california", "los angeles", "san diego", "san jose", "seattle", "boston", "london", "tokyo"]):
        return 1.25

    # slightly below average
    if any(x in text for x in ["texas", "arizona", "nevada", "florida"]):
        return 0.95

    # low cost
    if any(x in text for x in ["india", "vietnam", "mexico", "philippines"]):
        return 0.75

    return 1.00

# -----------------------------
# MATERIAL / LABOR / SCHEDULE ADJUSTMENTS
# -----------------------------
def get_adjustments(materials, timeline_months, description):
    text_materials = (materials or "").lower()
    text_description = (description or "").lower()

    material_factor = 1.0
    labor_factor = 1.0
    schedule_factor = 1.0
    site_factor = 1.0

    if "traditional japanese" in text_materials or "bamboo" in text_materials:
        material_factor += 0.12

    if "open to other materials" in text_materials or "reduce cost" in text_materials:
        material_factor -= 0.05

    if timeline_months and timeline_months < 8:
        schedule_factor += 0.15
    elif timeline_months and timeline_months < 14:
        schedule_factor += 0.05
    elif timeline_months and timeline_months > 60:
        schedule_factor -= 0.03

    if "pond" in text_description or "yard" in text_description:
        site_factor += 0.08

    return material_factor, labor_factor, schedule_factor, site_factor

# -----------------------------
# LEAD SCORE
# -----------------------------
def calculate_lead_score(total_cost, budget_val, timeline_months):
    score = 0

    if budget_val and total_cost:
        ratio = budget_val / total_cost

        if ratio >= 1.20:
            score += 5
        elif ratio >= 1.00:
            score += 4
        elif ratio >= 0.80:
            score += 3
        elif ratio >= 0.60:
            score += 2
        elif ratio >= 0.40:
            score += 1

    if timeline_months:
        if timeline_months >= 12:
            score += 1
        if timeline_months >= 60:
            score += 1

    return max(1, min(score, 10))

# -----------------------------
# DECISION LOGIC
# -----------------------------
def get_decision(lead_score):
    if lead_score >= 8:
        return "STRONG BID"
    if lead_score >= 5:
        return "CONSIDER"
    return "PASS"

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return {"status": "running"}

@app.route("/analyze", methods=["POST"])
def analyze():
    data = request.get_json(force=True)

    project = data.get("project", "")
    size = data.get("size", "")
    materials = data.get("materials", "")
    budget = data.get("budget", "")
    timeline = data.get("timeline", "")
    city = data.get("city", "")
    description = data.get("description", "")

    normalized = normalize_inputs_with_ai(
        project, size, materials, budget, timeline, city, description
    )

    # parser first
    size_val = parse_size(size)
    budget_val = parse_budget(budget)
    timeline_months = parse_timeline(timeline)

    # AI fallback if parser weak
    ai_project_category = None
    if normalized:
        ai_size = normalized.get("size_sqft")
        ai_budget = normalized.get("budget_usd")
        ai_timeline = normalized.get("timeline_months")
        ai_project_category = normalized.get("project_category")

        if not size_val or size_val < 500:
            if ai_size:
                size_val = ai_size

        if not budget_val or budget_val < 1000:
            if ai_budget:
                budget_val = ai_budget

        if not timeline_months or timeline_months < 1:
            if ai_timeline:
                timeline_months = ai_timeline

    if not size_val or size_val <= 0:
        size_val = 2000
    if budget_val is None or budget_val < 0:
        budget_val = 0
    if not timeline_months or timeline_months <= 0:
        timeline_months = 12

    project_type = detect_project_type(project, description, ai_project_category)
    complexity_factor, flags = get_project_complexity(project, description)
    location_factor = get_location_multiplier(city)
    material_factor, labor_factor, schedule_factor, site_factor = get_adjustments(
        materials, timeline_months, description
    )

    low, high = cost_per_sqft[project_type]
    base_mid = (size_val * low + size_val * high) / 2

    total_cost = (
        base_mid
        * complexity_factor
        * location_factor
        * material_factor
        * labor_factor
        * schedule_factor
        * site_factor
        * MARKET_FACTORS["materials_index"]
        * MARKET_FACTORS["labor_index"]
        * MARKET_FACTORS["general_inflation"]
    )

    material_cost = total_cost * 0.45
    labor_cost = total_cost * 0.55

    recommended_bid = total_cost * 1.25
    aggressive_bid = total_cost * 1.18
    minimum_bid = total_cost * 1.10

    budget_gap = budget_val - total_cost if budget_val else None

    lead_score = calculate_lead_score(total_cost, budget_val, timeline_months)
    decision = get_decision(lead_score)

    analysis_text = "AI unavailable."

    if client:
        try:
            prompt = f"""
You are a professional construction estimator.

Use the parsed values below as truth. Do not re-interpret the raw inputs.

Parsed values:
- Project type: {project_type}
- Size: {size_val:.0f} sqft
- Budget: ${budget_val:,.0f}
- Timeline: {timeline_months:.0f} months
- Location: {city}
- Estimated total cost: ${total_cost:,.0f}
- Recommended bid: ${recommended_bid:,.0f}
- Aggressive bid: ${aggressive_bid:,.0f}
- Minimum bid: ${minimum_bid:,.0f}
- Lead score: {lead_score}/10
- Decision: {decision}

Raw project description:
Project: {project}
Materials: {materials}
Description: {description}

Write a practical contractor-facing report with these sections:
1. Budget vs Cost
2. Timeline Feasibility
3. Key Risks
4. Bid Strategy

Keep it grounded in the parsed values above.
"""
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2
            )
            analysis_text = response.choices[0].message.content
        except Exception as e:
            analysis_text = str(e)

    return jsonify({
        "analysis": analysis_text,
        "data": {
            "project_type": project_type,
            "size_sqft": round(size_val, 2),
            "budget": round(budget_val, 2) if budget_val else None,
            "total_cost": round(total_cost, 2),
            "material_cost": round(material_cost, 2),
            "labor_cost": round(labor_cost, 2),
            "recommended_bid": round(recommended_bid, 2),
            "aggressive_bid": round(aggressive_bid, 2),
            "minimum_bid": round(minimum_bid, 2),
            "budget_gap": round(budget_gap, 2) if budget_gap is not None else None,
            "lead_score": lead_score,
            "decision": decision,
            "timeline_months": round(timeline_months, 2),
            "location_factor": round(location_factor, 2),
            "complexity_factor": round(complexity_factor, 2),
            "material_factor": round(material_factor, 2),
            "schedule_factor": round(schedule_factor, 2),
            "site_factor": round(site_factor, 2),
            "flags": flags
        }
    })

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
