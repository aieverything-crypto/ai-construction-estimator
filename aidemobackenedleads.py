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
# COST DATABASE ($/sqft BASE)
# -----------------------------
cost_per_sqft = {
    "residential": (180, 350),
    "commercial": (220, 500),
    "industrial": (250, 650),
    "remodel": (120, 300)
}

# -----------------------------
# LOCATION COST FACTORS 🌎
# -----------------------------
def get_location_multiplier(city):
    if not city:
        return 1.0

    text = city.lower()

    # HIGH COST AREAS
    if any(x in text for x in ["hawaii", "honolulu"]):
        return 1.4
    if any(x in text for x in ["california", "los angeles", "san francisco", "san diego"]):
        return 1.3
    if any(x in text for x in ["new york", "nyc"]):
        return 1.35
    if any(x in text for x in ["london", "uk"]):
        return 1.3
    if any(x in text for x in ["tokyo", "japan"]):
        return 1.25

    # LOW COST AREAS
    if any(x in text for x in ["texas", "arizona", "nevada"]):
        return 0.9
    if any(x in text for x in ["mexico", "india", "vietnam"]):
        return 0.7

    return 1.0

# -----------------------------
# AI NORMALIZATION
# -----------------------------
def normalize_inputs_with_ai(user_input):
    if not client:
        return None

    try:
        prompt = f"""
Convert construction input into JSON.

- Size → sqft
- Budget → USD
- Timeline → months
- If invalid → null

Input:
{user_input}

Return ONLY JSON:
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
# PARSE BUDGET (FIXED 🔥)
# -----------------------------
def parse_budget(budget_input):
    if not budget_input:
        return 0

    text = str(budget_input).lower().replace(",", "").strip()

    # scientific notation (10^6)
    power_match = re.search(r"(\d+)\s*\^\s*(\d+)", text)
    if power_match:
        return float(power_match.group(1)) ** float(power_match.group(2))

    # e notation (1e6)
    e_match = re.search(r"(\d+\.?\d*)e(\d+)", text)
    if e_match:
        return float(e_match.group(1)) * (10 ** float(e_match.group(2)))

    # invalid units
    if any(x in text for x in ["lb", "lbs", "pound", "kg"]):
        return None

    nums = re.findall(r"\d+\.?\d*", text)
    if not nums:
        return 0

    value = float(nums[0])

    if "million" in text or "m" in text:
        value *= 1_000_000
    elif "k" in text or "thousand" in text:
        value *= 1_000

    return value

# -----------------------------
# PARSE SIZE
# -----------------------------
def parse_size(size_input):
    if not size_input:
        return 2000

    text = str(size_input).lower().replace(",", "").strip()

    text = text.replace("meter to the power of 2", "sqm")
    text = text.replace("square meters", "sqm")

    if "sqm" in text or "m2" in text:
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

    if "warehouse" in text:
        return "industrial"
    if "office" in text:
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
# LEAD SCORE
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

    combined_input = f"""
Project: {project}
Size: {size}
Budget: {budget}
Timeline: {timeline}
Location: {city}
Description: {description}
"""

    normalized = normalize_inputs_with_ai(combined_input)

    size_val = parse_size(size)
    budget_val = parse_budget(budget)

    # AI override if needed
    if normalized:
        if not size_val or size_val < 500:
            size_val = normalized.get("size_sqft", size_val)
        if not budget_val or budget_val < 1000:
            budget_val = normalized.get("budget_usd", budget_val)

    if not size_val:
        size_val = 2000
    if not budget_val:
        budget_val = 0

    # -----------------------------
    # ESTIMATION
    # -----------------------------
    project_type = detect_project_type(project, description)
    complexity = get_project_complexity(project, description)

    location_factor = get_location_multiplier(city)

    low, high = cost_per_sqft[project_type]
    base_mid = (size_val * low + size_val * high) / 2

    total_cost = base_mid * complexity * location_factor

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
You are a construction estimator.

Project: {project}
Size: {size_val:.0f} sqft
Location: {city}
Budget: {budget_val}
Estimated Cost: {total_cost}

Explain realism, risks, and bid strategy.
"""

            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}]
            )

            analysis_text = response.choices[0].message.content

        except Exception as e:
            analysis_text = str(e)

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
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
