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
# INPUT PARSERS
# -----------------------------
def parse_budget(budget_input):
    if not budget_input:
        return 0

    text = str(budget_input).lower().replace(",", "").replace("$", "").strip()
    nums = re.findall(r"\d+\.?\d*", text)

    if not nums:
        return 0

    value = float(nums[0])

    # Support words and suffixes
    if "million" in text or re.search(r"\bm\b", text):
        value *= 1_000_000
    elif "thousand" in text or re.search(r"\bk\b", text):
        value *= 1_000

    return value


def parse_size(size_input):
    """
    Supports:
    - 2000
    - 2000 sqft
    - 30x50
    - 30 x 50
    - 30by50
    - 30 by 50 ft
    """
    if not size_input:
        return 2000

    text = str(size_input).lower().replace(",", "").strip()
    text = text.replace("square feet", "").replace("sqft", "").replace("sq ft", "").replace("ft", "").strip()

    # normalize "by" to x
    text = re.sub(r"\s*by\s*", "x", text)
    text = re.sub(r"\s*x\s*", "x", text)

    if "x" in text:
        parts = text.split("x")
        if len(parts) == 2:
            try:
                a = float(re.findall(r"\d+\.?\d*", parts[0])[0])
                b = float(re.findall(r"\d+\.?\d*", parts[1])[0])
                return a * b
            except Exception:
                pass

    nums = re.findall(r"\d+\.?\d*", text)

    # If multiple numbers remain and no x/by pattern was caught,
    # assume first number is intended sqft if user typed something like "2000 sqft"
    if len(nums) >= 1:
        return float(nums[0])

    return 2000


# -----------------------------
# PROJECT TYPE + COMPLEXITY
# -----------------------------
def detect_project_type(project, description):
    text = f"{project or ''} {description or ''}".lower()

    if any(x in text for x in ["warehouse", "factory", "plant", "industrial"]):
        return "industrial"
    if any(x in text for x in ["office", "retail", "restaurant", "commercial", "store"]):
        return "commercial"
    if any(x in text for x in ["remodel", "renovation", "addition", "tenant improvement"]):
        return "remodel"
    return "residential"


def get_project_complexity(project, description):
    """
    Returns:
    factor,
    special_cost_range,
    flags[]
    """
    factor = 1.0
    special = None
    flags = []

    text = f"{project or ''} {description or ''}".lower()

    if "underground" in text or "bunker" in text:
        factor += 2.0
        special = (500, 1500)
        flags.append("underground")

    if "antarctica" in text or "arctic" in text or "remote" in text:
        factor += 1.5
        special = special or (700, 2200)
        flags.append("remote logistics")

    if "hospital" in text or "lab" in text or "medical" in text:
        factor += 1.4
        special = special or (450, 1300)
        flags.append("specialized MEP / compliance")

    if "luxury" in text or "high-end" in text:
        factor += 0.4
        flags.append("luxury finishes")

    if "steep slope" in text or "hillside" in text or "slope" in text:
        factor += 0.35
        flags.append("difficult site / slope work")

    if "simple" in text or "shed" in text:
        factor -= 0.2
        flags.append("simple structure")

    return max(0.7, factor), special, flags


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

    # Materials
    if "steel" in text_materials:
        material_factor += 0.15
    if "concrete" in text_materials:
        material_factor += 0.10
    if "luxury" in text_materials or "premium" in text_materials:
        material_factor += 0.25
    if "wood" in text_materials:
        material_factor += 0.03

    # City / labor market
    high_cost_cities = [
        "san francisco", "los angeles", "san jose", "new york",
        "seattle", "boston", "san diego"
    ]
    if any(c in text_city for c in high_cost_cities):
        labor_factor += 0.30
    elif "california" in text_city or "new york" in text_city:
        labor_factor += 0.20

    # Timeline
    months = extract_timeline_months(text_timeline)
    if "rush" in text_timeline or "fast" in text_timeline or "asap" in text_timeline:
        timeline_factor += 0.20
    elif months and months < 6:
        timeline_factor += 0.15
    elif months and months < 10:
        timeline_factor += 0.08

    # Site
    if "steep slope" in text_description or "hillside" in text_description or "slope" in text_description:
        site_factor += 0.20
    if "tight lot" in text_description or "urban infill" in text_description:
        site_factor += 0.10

    return material_factor, labor_factor, timeline_factor, site_factor


def extract_timeline_months(timeline_text):
    if not timeline_text:
        return None

    m = re.search(r"(\d+\.?\d*)\s*month", timeline_text)
    if m:
        return float(m.group(1))

    y = re.search(r"(\d+\.?\d*)\s*year", timeline_text)
    if y:
        return float(y.group(1)) * 12

    return None


# -----------------------------
# LEAD SCORING
# -----------------------------
def calculate_lead_score(size, budget, cost):
    score = 5

    if size > 5000:
        score += 2
    elif size < 1000:
        score -= 1

    if budget == 0:
        score -= 2
    elif budget < cost * 0.30:
        score -= 5
    elif budget < cost * 0.60:
        score -= 3
    elif budget < cost * 0.90:
        score -= 1
    elif budget <= cost * 1.30:
        score += 1
    else:
        score += 2

    return max(1, min(10, score))


# -----------------------------
# CONTRACTOR DECISION
# -----------------------------
def contractor_decision(total, budget):
    if budget == 0:
        return "NEGOTIATE", "No stated budget"

    ratio = budget / total

    if ratio < 0.60:
        return "REJECT", "Budget far below expected cost"
    elif ratio < 0.90:
        return "NEGOTIATE", "Budget below expected cost"
    elif ratio <= 1.30:
        return "TAKE JOB", "Budget is reasonably aligned"
    else:
        return "HIGH VALUE", "Strong margin potential"


def decision_color(decision):
    return {
        "TAKE JOB": "green",
        "NEGOTIATE": "yellow",
        "REJECT": "red",
        "HIGH VALUE": "blue"
    }.get(decision, "gray")


def fmt_money(n):
    return round(float(n), 2)


# -----------------------------
# AI REPORT
# -----------------------------
def build_fallback_analysis(project, city, size_val, total_cost, decision, reason, flags):
    flags_text = ", ".join(flags) if flags else "standard conditions"

    return f"""
Project Summary:
- Project: {project or 'N/A'}
- City: {city or 'N/A'}
- Estimated size: {size_val:.0f} sqft
- Estimated cost: ${total_cost:,.0f}

Estimator Notes:
This estimate was generated using rule-based construction pricing logic and adjusted for site, materials, labor market, and schedule conditions. Key complexity drivers detected: {flags_text}.

Contractor Recommendation:
Decision: {decision}
Reason: {reason}

Bid Advice:
Use the recommended bid as the primary proposal, use aggressive bid only in competitive situations, and avoid going below minimum bid unless scope is reduced.
""".strip()


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return {"status": "running"}


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(force=True) or {}

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

        low, high = special if special else cost_per_sqft[project_type]

        base_low = size_val * low
        base_high = size_val * high
        base_mid = (base_low + base_high) / 2

        material_factor, labor_factor, timeline_factor, site_factor = get_adjustments(
            materials, city, timeline, description
        )

        total_multiplier = complexity * material_factor * labor_factor * timeline_factor * site_factor
        total_cost = base_mid * total_multiplier

        material_cost = total_cost * 0.45
        labor_cost = total_cost * 0.55

        recommended_bid = total_cost * 1.25
        aggressive_bid = total_cost * 1.18
        min_bid = total_cost * 1.10

        lead_score = calculate_lead_score(size_val, budget_val, total_cost)
        decision, reason = contractor_decision(total_cost, budget_val)
        budget_gap = budget_val - total_cost if budget_val else 0

        analysis_text = build_fallback_analysis(
            project, city, size_val, total_cost, decision, reason, flags
        )

        if client:
            try:
                prompt = f"""
You are a senior construction estimator writing a concise contractor-facing report.

Use the numeric estimate below as the source of truth. Do not invent new totals.

Project Inputs:
- Project: {project}
- Size: {size_val:.0f} sqft
- City: {city}
- Materials: {materials}
- Timeline: {timeline}
- Budget: ${budget_val:,.0f}
- Description: {description}

Computed Estimate:
- Project type: {project_type}
- Base cost range: ${low}/sqft to ${high}/sqft
- Complexity factor: {complexity:.2f}
- Estimated total cost: ${total_cost:,.0f}
- Material cost: ${material_cost:,.0f}
- Labor cost: ${labor_cost:,.0f}
- Recommended bid: ${recommended_bid:,.0f}
- Aggressive bid: ${aggressive_bid:,.0f}
- Minimum bid: ${min_bid:,.0f}
- Lead score: {lead_score}/10
- Decision: {decision}
- Reason: {reason}

Write under these headings:
1. Cost Realism
2. Key Cost Drivers
3. Contractor Decision
4. Risk Level
5. Bid Strategy

Keep it practical and grounded in the numbers above.
                """.strip()

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a practical construction estimating assistant. Be concise, numeric, and realistic."
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.3
                )

                ai_content = response.choices[0].message.content
                if ai_content and ai_content.strip():
                    analysis_text = ai_content.strip()

            except Exception as e:
                print("AI generation error:", e)

        return jsonify({
            "analysis": analysis_text,
            "data": {
                "project_type": project_type,
                "size_sqft": fmt_money(size_val),
                "budget": fmt_money(budget_val),
                "total_cost": fmt_money(total_cost),
                "material_cost": fmt_money(material_cost),
                "labor_cost": fmt_money(labor_cost),
                "recommended_bid": fmt_money(recommended_bid),
                "aggressive_bid": fmt_money(aggressive_bid),
                "min_bid": fmt_money(min_bid),
                "lead_score": lead_score,
                "decision": decision,
                "decision_reason": reason,
                "decision_color": decision_color(decision),
                "budget_gap": fmt_money(budget_gap),
                "cost_range_low": fmt_money(base_low * total_multiplier / ((base_low + base_high) / 2)),
                "cost_range_high": fmt_money(base_high * total_multiplier / ((base_low + base_high) / 2)),
                "factors": {
                    "complexity": round(complexity, 2),
                    "material_factor": round(material_factor, 2),
                    "labor_factor": round(labor_factor, 2),
                    "timeline_factor": round(timeline_factor, 2),
                    "site_factor": round(site_factor, 2)
                },
                "flags": flags
            }
        })

    except Exception as e:
        return jsonify({
            "error": "Analysis failed",
            "details": str(e)
        }), 500


if __name__ == "__main__":
    app.run(debug=True)
