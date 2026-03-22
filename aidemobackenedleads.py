from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os
import re

print("APP STARTED SUCCESSFULLY")

# -----------------------------
# INIT
# -----------------------------
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
    else:
        print("No API key found.")
except Exception as e:
    print("OpenAI init error:", e)
    client = None

# -----------------------------
# BASE COST DATABASE
# -----------------------------
cost_per_sqft = {
    "residential": (150, 300),
    "commercial": (200, 450),
    "industrial": (250, 600),
    "remodel": (100, 250)
}

materials_db = {
    "concrete": {"price": 150},
    "rebar": {"price": 0.85},
    "lumber": {"price": 4.25},
    "drywall": {"price": 15}
}

# -----------------------------
# HELPERS
# -----------------------------
def parse_budget(budget_input):
    if not budget_input:
        return 0

    text = str(budget_input).lower().replace(",", "").replace("$", "").strip()

    if "m" in text:
        nums = re.findall(r"\d+\.?\d*", text)
        if nums:
            return float(nums[0]) * 1_000_000

    if "k" in text:
        nums = re.findall(r"\d+\.?\d*", text)
        if nums:
            return float(nums[0]) * 1_000

    nums = re.findall(r"\d+\.?\d*", text)
    return float(nums[0]) if nums else 0


def parse_size(size_input):
    if not size_input:
        return 2000

    text = str(size_input).lower().replace(",", "").replace("ft", "").replace("sq", "").strip()

    if "x" in text:
        try:
            a, b = text.split("x")
            return float(a) * float(b)
        except:
            return 2000

    nums = re.findall(r"\d+\.?\d*", text)
    return float(nums[0]) if nums else 2000


def get_project_complexity(project, description):
    complexity = 1.0
    override = None
    special = None

    text = f"{project or ''} {description or ''}".lower()

    if "underground" in text or "bunker" in text:
        complexity += 2.0
        override = "industrial"
        special = (500, 1500)

    if "antarctica" in text:
        complexity += 2.0
        special = (800, 2500)

    if "hospital" in text:
        complexity += 1.5
        special = (400, 1200)

    return complexity, override, special


def get_adjustments(materials, city, timeline):
    m, l, t = 1.0, 1.0, 1.0

    if materials and "steel" in materials.lower():
        m += 0.15

    if city and "california" in city.lower():
        l += 0.25

    if timeline and "rush" in timeline.lower():
        t += 0.20

    return m, l, t


def calculate_lead_score(size, budget, min_cost):
    score = 5

    if size > 5000:
        score += 2

    if budget < min_cost * 0.3:
        score -= 4

    return max(1, min(10, score))


def contractor_decision(total, budget):
    if budget == 0:
        return "NEGOTIATE ⚠️", "No budget"

    ratio = budget / total

    if ratio < 0.6:
        return "REJECT ❌", "Too low"
    elif ratio < 0.9:
        return "NEGOTIATE ⚠️", "Below cost"
    elif ratio <= 1.3:
        return "TAKE JOB ✅", "Fair"
    else:
        return "HIGH VALUE 💰", "Great deal"


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return {"status": "running"}


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.json

        project = data.get("project")
        size = data.get("size")
        materials = data.get("materials")
        budget = data.get("budget")
        timeline = data.get("timeline")
        city = data.get("city")
        description = data.get("description")

        size_val = parse_size(size)
        budget_val = parse_budget(budget)

        complexity, override, special = get_project_complexity(project, description)
        project_type = override or "residential"

        low, high = special if special else cost_per_sqft[project_type]

        base_low = size_val * low
        base_high = size_val * high

        m, l, t = get_adjustments(materials, city, timeline)

        total_cost = ((base_low + base_high) / 2) * complexity * m * l * t

        material_cost = total_cost * 0.45
        labor_cost = total_cost * 0.55

        recommended_bid = total_cost * 1.25

        lead_score = calculate_lead_score(size_val, budget_val, base_low)
        decision, reason = contractor_decision(total_cost, budget_val)

        budget_gap = budget_val - total_cost if budget_val else 0

        # AI CALL
        analysis_text = "AI analysis unavailable."

        if client:
            try:
                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": f"Explain this project cost simply: {total_cost}"}]
                )
                analysis_text = response.choices[0].message.content
            except Exception as e:
                analysis_text = f"AI error: {str(e)}"

        return jsonify({
            "analysis": analysis_text,
            "data": {
                "total_cost": total_cost,
                "material_cost": material_cost,
                "labor_cost": labor_cost,
                "recommended_bid": recommended_bid,
                "lead_score": lead_score,
                "decision": decision,
                "budget_gap": budget_gap
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
