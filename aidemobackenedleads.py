from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os
import re

app = Flask(__name__)
CORS(app)

client = None
api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    client = OpenAI(api_key=api_key)

cost_per_sqft = {
    "residential": (180, 350),
    "commercial": (220, 500),
    "industrial": (250, 650),
    "remodel": (120, 300)
}

# -----------------------------
# PARSERS
# -----------------------------
def parse_budget(text):
    if not text:
        return 0
    text = str(text).lower().replace(",", "").replace("$", "")
    nums = re.findall(r"\d+\.?\d*", text)
    if not nums:
        return 0
    val = float(nums[0])
    if "m" in text or "million" in text:
        val *= 1_000_000
    elif "k" in text or "thousand" in text:
        val *= 1000
    return val


def parse_size(text):
    if not text:
        return 2000

    text = str(text).lower().replace(",", "")
    text = text.replace("sqft", "").replace("sq ft", "").replace("ft", "")
    text = re.sub(r"\s*by\s*", "x", text)
    text = re.sub(r"\s*x\s*", "x", text)

    if "x" in text:
        parts = text.split("x")
        try:
            return float(parts[0]) * float(parts[1])
        except:
            pass

    nums = re.findall(r"\d+\.?\d*", text)
    if nums:
        return float(nums[0])

    return 2000


def extract_timeline_months(text):
    if not text:
        return None

    text = text.lower()

    m = re.search(r"(\d+\.?\d*)\s*month", text)
    if m:
        return float(m.group(1))

    y = re.search(r"(\d+\.?\d*)\s*year", text)
    if y:
        return float(y.group(1)) * 12

    d = re.search(r"(\d+\.?\d*)\s*day", text)
    if d:
        return float(d.group(1)) / 30

    return None


# -----------------------------
# LOGIC
# -----------------------------
def detect_project_type(project, description):
    text = f"{project} {description}".lower()

    if "warehouse" in text:
        return "industrial"
    if "office" in text or "retail" in text:
        return "commercial"
    if "remodel" in text:
        return "remodel"
    return "residential"


def adjustments(materials, city, timeline, description):
    m = 1.0
    l = 1.0
    t = 1.0
    s = 1.0

    if "steel" in materials.lower():
        m += 0.15

    if "san francisco" in city.lower() or "los angeles" in city.lower():
        l += 0.3

    months = extract_timeline_months(timeline)

    # ✅ USE timeline properly
    if months:
        if months < 6:
            t += 0.15
        elif months > 24:
            t -= 0.05  # long timeline = slightly cheaper

    if "slope" in description.lower():
        s += 0.2

    return m, l, t, s


def lead_score(size, budget, cost):
    if cost <= 0:
        return 1

    score = 5
    ratio = budget / cost if budget else 0

    # Budget realism
    if budget == 0:
        score -= 3
    elif ratio < 0.5:
        score -= 4
    elif ratio < 0.8:
        score -= 2
    elif ratio <= 1.2:
        score += 1
    elif ratio <= 2:
        score += 2
    elif ratio <= 5:
        score += 3
    else:
        score += 4  # huge budget = very strong lead

    # Project size quality
    if size > 10000:
        score += 1
    elif size < 1000:
        score -= 1

    return max(1, min(10, score))


def decision(total, budget):
    if budget == 0:
        return "NEGOTIATE", "No budget provided"

    r = budget / total

    if r < 0.6:
        return "REJECT", "Budget too low"
    elif r < 0.9:
        return "NEGOTIATE", "Below expected cost"
    elif r <= 1.3:
        return "TAKE JOB", "Good alignment"
    else:
        return "HIGH VALUE", "High profit margin"


def color(d):
    return {
        "TAKE JOB": "green",
        "NEGOTIATE": "yellow",
        "REJECT": "red",
        "HIGH VALUE": "blue"
    }.get(d, "gray")


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return {"status": "API running"}


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.json

        size = parse_size(data.get("size"))
        budget = parse_budget(data.get("budget"))
        timeline_raw = data.get("timeline", "")
        months = extract_timeline_months(timeline_raw)

        project_type = detect_project_type(data.get("project"), data.get("description"))

        low, high = cost_per_sqft[project_type]
        base = ((low + high) / 2) * size

        m, l, t, s = adjustments(
            data.get("materials", ""),
            data.get("city", ""),
            timeline_raw,
            data.get("description", "")
        )

        total = base * m * l * t * s

        material = total * 0.45
        labor = total * 0.55

        rec = total * 1.25
        agg = total * 1.18
        minb = total * 1.10

        score = lead_score(size, budget, total)
        dec, reason = decision(total, budget)

        # ✅ Better fallback analysis
        analysis = f"""
Project Type: {project_type}
Size: {round(size)} sqft
Estimated Cost: ${round(total):,}
Timeline: {round(months,1) if months else "N/A"} months

Decision: {dec}
Reason: {reason}
"""

        # ✅ STRONGER AI PROMPT
        if client:
            try:
                prompt = f"""
You are a construction estimator.

STRICT RULES:
- Use ONLY provided numbers
- DO NOT change units
- DO NOT reinterpret timeline

DATA:
Cost = {round(total)}
Timeline (months) = {round(months,1) if months else "unknown"}
Decision = {dec}

Write a short contractor report.
"""
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":prompt}],
                    temperature=0.2
                )
                analysis = res.choices[0].message.content
            except:
                pass

        return jsonify({
            "analysis": analysis,
            "data": {
                "total_cost": total,
                "material_cost": material,
                "labor_cost": labor,
                "recommended_bid": rec,
                "aggressive_bid": agg,
                "min_bid": minb,
                "lead_score": score,
                "decision": dec,
                "decision_color": color(dec),
                "budget": budget,
                "size_sqft": size,
                "timeline_months": months  # ✅ NEW
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
