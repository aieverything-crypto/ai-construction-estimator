from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os
import re

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# -----------------------------
# SAFE OPENAI INIT
# -----------------------------
client = None
try:
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        client = OpenAI(api_key=api_key)
except Exception as e:
    print("OpenAI init error:", e)

# -----------------------------
# BASE COST DATABASE ($ / sq ft)
# -----------------------------
cost_per_sqft = {
    "residential": (180, 350),
    "commercial": (220, 500),
    "industrial": (250, 650),
    "remodel": (120, 300)
}

# -----------------------------
# INPUT PARSERS (UPGRADED)
# -----------------------------

def parse_budget(budget_input):
    if not budget_input:
        return 0

    text = str(budget_input).lower().replace(",", "").strip()

    # 🚨 detect INVALID units like lb
    if "lb" in text or "kg" in text:
        return 0  # invalid budget input

    multiplier = 1

    # currency detection
    if "€" in text or "eur" in text:
        multiplier = 1.1
    elif "£" in text or "gbp" in text:
        multiplier = 1.25
    elif "cad" in text:
        multiplier = 0.75

    nums = re.findall(r"\d+\.?\d*", text)
    if not nums:
        return 0

    value = float(nums[0])

    if any(x in text for x in ["million", "m"]):
        value *= 1_000_000
    elif any(x in text for x in ["thousand", "k"]):
        value *= 1_000

    return value * multiplier


def parse_size(size_input):
    if not size_input:
        return 2000

    text = str(size_input).lower().replace(",", "").strip()

    # meters (500m x 100m)
    if "m" in text and "x" in text:
        nums = re.findall(r"\d+\.?\d*", text)
        if len(nums) >= 2:
            sqm = float(nums[0]) * float(nums[1])
            return sqm * 10.764

    text = text.replace("sqft", "").replace("sq ft", "").replace("ft", "").strip()
    text = re.sub(r"\s*by\s*", "x", text)
    text = re.sub(r"\s*x\s*", "x", text)

    if "x" in text:
        parts = text.split("x")
        if len(parts) == 2:
            try:
                a = float(re.findall(r"\d+\.?\d*", parts[0])[0])
                b = float(re.findall(r"\d+\.?\d*", parts[1])[0])
                return a * b
            except:
                pass

    nums = re.findall(r"\d+\.?\d*", text)
    return float(nums[0]) if nums else 2000


# -----------------------------
# PROJECT TYPE + COMPLEXITY (UPGRADED)
# -----------------------------
def detect_project_type(project, description):
    text = f"{project or ''} {description or ''}".lower()

    if any(x in text for x in ["warehouse", "factory", "industrial"]):
        return "industrial"
    if any(x in text for x in ["office", "retail", "restaurant"]):
        return "commercial"
    if any(x in text for x in ["remodel", "renovation"]):
        return "remodel"
    return "residential"


def get_project_complexity(project, description):
    factor = 1.0
    special = None
    flags = []

    text = f"{project or ''} {description or ''}".lower()

    if "castle" in text:
        factor += 1.5
        special = (600, 1200)
        flags.append("custom architecture")

    if "luxury" in text or "estate" in text:
        factor += 0.8
        flags.append("luxury build")

    if "underground" in text or "bunker" in text:
        factor += 2.0
        special = (500, 1500)
        flags.append("underground complexity")

    if "hospital" in text:
        factor += 1.5
        special = (450, 1300)

    if "skyscraper" in text:
        factor += 2.0
        special = (500, 1400)

    if "slope" in text or "hillside" in text:
        factor += 0.35
        flags.append("difficult site")

    return factor, special, flags


# -----------------------------
# ADJUSTMENTS
# -----------------------------
def get_adjustments(materials, city, timeline, description):
    material_factor = 1.0
    labor_factor = 1.0
    timeline_factor = 1.0
    site_factor = 1.0

    text_materials = (materials or "").lower()
    text_city = (city or "").lower()
    text_description = (description or "").lower()
    text_timeline = (timeline or "").lower()

    if "steel" in text_materials:
        material_factor += 0.15
    if "concrete" in text_materials:
        material_factor += 0.10
    if "luxury" in text_materials:
        material_factor += 0.25

    if "california" in text_city or "san francisco" in text_city:
        labor_factor += 0.30

    if "rush" in text_timeline:
        timeline_factor += 0.20

    if "slope" in text_description:
        site_factor += 0.20

    return material_factor, labor_factor, timeline_factor, site_factor


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

    size_val = parse_size(size)
    budget_val = parse_budget(budget)

    project_type = detect_project_type(project, description)
    complexity, special, flags = get_project_complexity(project, description)

    # SCALE ADJUSTMENT (IMPORTANT)
    if size_val > 20000:
        complexity += 0.3
    if size_val > 50000:
        complexity += 0.5

    low, high = special if special else cost_per_sqft[project_type]

    base_mid = (size_val * low + size_val * high) / 2

    m, l, t, s = get_adjustments(materials, city, timeline, description)

    total_cost = base_mid * complexity * m * l * t * s

    material_cost = total_cost * 0.45
    labor_cost = total_cost * 0.55

    recommended_bid = total_cost * 1.25

    # -----------------------------
    # AI REPORT (UPGRADED)
    # -----------------------------
    analysis_text = "AI unavailable."

    if client:
        try:
            prompt = f"""
You are a senior construction estimator.

Project:
{project}

Size: {size_val:.0f} sqft
City: {city}
Materials: {materials}
Budget: {budget_val}

Estimated Cost: {total_cost}

Explain:
1. Is cost realistic?
2. Key drivers
3. Risks
4. Bid strategy

Be realistic and practical.
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
        "total_cost": round(total_cost, 2),
        "recommended_bid": round(recommended_bid, 2),
        "size_sqft": round(size_val, 2),
        "flags": flags
    })


if __name__ == "__main__":
    app.run(debug=True)
