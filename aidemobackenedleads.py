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
# COST DATABASE
# -----------------------------
cost_per_sqft = {
    "residential": (180, 350),
    "commercial": (220, 500),
    "industrial": (250, 650),
    "remodel": (120, 300)
}

# -----------------------------
# AI NORMALIZATION
# -----------------------------
def normalize_inputs_with_ai(user_input):
    if not client:
        return None

    try:
        prompt = f"""
Convert the following construction project input into structured JSON.

Rules:
- Convert ALL sizes to square feet
- Convert ALL money to USD
- Convert timeline to MONTHS
- If invalid (like pounds), return null

Input:
{user_input}

Output JSON ONLY:
{{
    "size_sqft": number,
    "budget_usd": number,
    "timeline_months": number
}}
"""
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
# FALLBACK PARSERS
# -----------------------------
def parse_budget(budget_input):
    if not budget_input:
        return 0

    text = str(budget_input).lower().replace(",", "").strip()

    if any(x in text for x in ["lb", "lbs", "pound", "kg"]):
        return None

    nums = re.findall(r"\d+\.?\d*", text)
    if not nums:
        return 0

    value = float(nums[0])

    if any(x in text for x in ["million", "m"]):
        value *= 1_000_000
    elif any(x in text for x in ["thousand", "k"]):
        value *= 1_000

    return value


def parse_size(size_input):
    if not size_input:
        return 2000

    text = str(size_input).lower().replace(",", "").strip()

    text = text.replace("meter to the power of 2", "sqm")
    text = text.replace("meters to the power of 2", "sqm")
    text = text.replace("square meters", "sqm")
    text = text.replace("sq meters", "sqm")

    if any(x in text for x in ["sqm", "m2", "m^2"]):
        nums = re.findall(r"\d+\.?\d*", text)
        if nums:
            return float(nums[0]) * 10.764

    nums = re.findall(r"\d+\.?\d*", text)
    return float(nums[0]) if nums else 2000

# -----------------------------
# PROJECT TYPE
# -----------------------------
def detect_project_type(project, description):
    text = f"{project} {description}".lower()

    if "warehouse" in text or "factory" in text:
        return "industrial"
    if "office" in text or "restaurant" in text:
        return "commercial"
    if "remodel" in text:
        return "remodel"
    return "residential"

# -----------------------------
# COMPLEXITY
# -----------------------------
def get_project_complexity(project, description):
    factor = 1.0
    text = f"{project} {description}".lower()

    if "luxury" in text:
        factor += 0.8
    if "underground" in text:
        factor += 2.0
    if "slope" in text:
        factor += 0.3

    return factor

# -----------------------------
# LEAD SCORE (NEW)
# -----------------------------
def calculate_lead_score(total_cost, budget_val, timeline):
    score = 0

    if budget_val and total_cost:
        ratio = budget_val / total_cost

        if ratio >= 1.2:
            score += 4
        elif ratio >= 1.0:
            score += 3
        elif ratio >= 0.8:
            score += 2
        elif ratio >= 0.5:
            score += 1

    if timeline:
        text = str(timeline).lower()
        if "rush" in text:
            score += 1
        elif "year" in text or "decade" in text:
            score += 2

    return min(score, 10)

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

    # -----------------------------
    # AI NORMALIZATION FIRST
    # -----------------------------
    combined_input = f"""
Project: {project}
Size: {size}
Materials: {materials}
Budget: {budget}
Timeline: {timeline}
Location: {city}
Description: {description}
"""

    normalized = normalize_inputs_with_ai(combined_input)

    if normalized:
        size_val = normalized.get("size_sqft") or parse_size(size)
        budget_val = normalized.get("budget_usd") or parse_budget(budget)
    else:
        size_val = parse_size(size)
        budget_val = parse_budget(budget)

    if not size_val or size_val <= 0:
        size_val = 2000

    if not budget_val or budget_val <= 0:
        budget_val = 0

    # -----------------------------
    # ESTIMATION
    # -----------------------------
    project_type = detect_project_type(project, description)
    complexity = get_project_complexity(project, description)

    low, high = cost_per_sqft[project_type]
    base_mid = (size_val * low + size_val * high) / 2

    total_cost = base_mid * complexity

    material_cost = total_cost * 0.45
    labor_cost = total_cost * 0.55

    recommended_bid = total_cost * 1.25
    minimum_bid = total_cost * 1.10
    aggressive_bid = total_cost * 1.18

    budget_gap = budget_val - total_cost if budget_val else None

    lead_score = calculate_lead_score(total_cost, budget_val, timeline)

    decision = "PASS"
    if lead_score >= 7:
        decision = "STRONG BID"
    elif lead_score >= 4:
        decision = "CONSIDER"

    # -----------------------------
    # AI REPORT
    # -----------------------------
    analysis_text = "AI unavailable."

    if client:
        try:
            prompt = f"""
You are a senior construction estimator.

Project: {project}
Size: {size_val:.0f} sqft
City: {city}
Budget: {budget_val}
Estimated Cost: {total_cost}

Explain:
1. Is cost realistic?
2. Key drivers
3. Risks
4. Bid strategy
"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )

            analysis_text = response.choices[0].message.content

        except Exception as e:
            analysis_text = str(e)

    # -----------------------------
    # RESPONSE
    # -----------------------------
    return jsonify({
        "analysis": analysis_text,
        "data": {
            "total_cost": round(total_cost, 2),
            "recommended_bid": round(recommended_bid, 2),
            "minimum_bid": round(minimum_bid, 2),
            "aggressive_bid": round(aggressive_bid, 2),
            "material_cost": round(material_cost, 2),
            "labor_cost": round(labor_cost, 2),
            "budget_gap": round(budget_gap, 2) if budget_gap else None,
            "size_sqft": round(size_val, 2),
            "lead_score": lead_score,
            "decision": decision
        }
    })

if __name__ == "__main__":
    app.run(debug=True)
