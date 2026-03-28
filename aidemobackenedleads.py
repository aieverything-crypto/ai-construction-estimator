from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os
import re

app = Flask(__name__)
CORS(app)

# -----------------------------
# OPENAI INIT (SAFE)
# -----------------------------
client = None
api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    client = OpenAI(api_key=api_key)

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
# PARSERS (FIXED)
# -----------------------------
def parse_budget(text):
    if not text:
        return 0

    text = str(text).lower().replace(",", "").replace("$", "").strip()

    multiplier = 1

    if "billion" in text or re.search(r"\bb\b", text):
        multiplier = 1_000_000_000
    elif "million" in text or re.search(r"\bm\b", text):
        multiplier = 1_000_000
    elif "thousand" in text or re.search(r"\bk\b", text):
        multiplier = 1_000

    nums = re.findall(r"\d+\.?\d*", text)
    if nums:
        return float(nums[0]) * multiplier

    return 0


def parse_size(text):
    if not text:
        return 2000

    text = str(text).lower().replace(",", "").strip()

    multiplier = 1

    if "billion" in text:
        multiplier = 1_000_000_000
    elif "million" in text:
        multiplier = 1_000_000
    elif "thousand" in text:
        multiplier = 1_000

    # sqm → sqft conversion
    if "sqm" in text or "m²" in text or "m2" in text:
        nums = re.findall(r"\d+\.?\d*", text)
        if nums:
            return float(nums[0]) * multiplier * 10.7639

    # 30x50 format
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
        return float(nums[0]) * multiplier

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

    if any(x in text for x in ["warehouse", "factory"]):
        return "industrial"
    if any(x in text for x in ["office", "retail", "apartment", "complex"]):
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
    if "luxury" in materials.lower():
        m += 0.2

    if any(x in city.lower() for x in ["san francisco", "new york"]):
        l += 0.3
    elif any(x in city.lower() for x in ["las vegas"]):
        l += 0.1

    months = extract_timeline_months(timeline)
    if months:
        if months < 6:
            t += 0.15
        elif months > 36:
            t -= 0.05

    if any(x in description.lower() for x in ["slope", "steep"]):
        s += 0.2

    return m, l, t, s


def lead_score(size, budget, cost):
    if cost <= 0:
        return 1

    score = 5
    ratio = budget / cost if budget else 0

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
        score += 4

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
        return "HIGH VALUE", "High profit"


def risk_score(budget, cost, months):
    risk = 5

    if budget < cost:
        risk += 3
    if months and months < 6:
        risk += 2
    if months and months > 60:
        risk += 1

    return min(10, risk)


def deal_score(budget, cost, risk, margin):
    score = 5
    ratio = budget / cost if cost else 0

    if ratio > 2:
        score += 2
    if margin > 20:
        score += 2
    if risk > 7:
        score -= 2

    return max(1, min(10, score))


def build_flags(budget, cost, months, materials, description):
    flags = []

    if budget > cost * 5:
        flags.append("Budget far exceeds cost — verify scope")

    if budget < cost:
        flags.append("Budget below estimated cost")

    if months and months > 60:
        flags.append("Timeline unusually long")

    if "luxury" in materials.lower():
        flags.append("Luxury materials increase volatility")

    if "slope" in description.lower():
        flags.append("Slope increases construction complexity")

    return flags


# -----------------------------
# ROUTE
# -----------------------------
@app.route("/")
def home():
    return {"status": "AI estimator running"}

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.json

        size = parse_size(data.get("size"))
        budget = parse_budget(data.get("budget"))
        months = extract_timeline_months(data.get("timeline"))

        project_type = detect_project_type(
            data.get("project"),
            data.get("description")
        )

        low, high = cost_per_sqft[project_type]
        base = ((low + high) / 2) * size

        m, l, t, s = adjustments(
            data.get("materials", ""),
            data.get("city", ""),
            data.get("timeline", ""),
            data.get("description", "")
        )

        total = base * m * l * t * s

        material = total * 0.45
        labor = total * 0.55

        rec = total * 1.25
        agg = total * 1.18
        minb = total * 1.10

        budget_gap = budget - total if budget else 0
        budget_ratio = budget / total if total else 0

        profit_mid = rec - total
        margin_mid = (profit_mid / rec) * 100 if rec else 0

        score = lead_score(size, budget, total)
        dec, reason = decision(total, budget)

        risk = risk_score(budget, total, months)
        deal = deal_score(budget, total, risk, margin_mid)
        flags = build_flags(budget, total, months, data.get("materials",""), data.get("description",""))

        analysis = f"""
Project Type: {project_type}
Estimated Cost: ${round(total):,}
Decision: {dec}
"""

        # AI REPORT
        if client:
            try:
                prompt = f"""
Write a professional contractor report.

Use these exact values:
Cost: {round(total)}
Budget: {round(budget)}
Decision: {dec}
Risk: {risk}/10
Profit: {round(profit_mid)}

Include:
- Cost realism
- Risks
- Bid strategy
"""
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role":"user","content":prompt}],
                    temperature=0.4
                )
                analysis = res.choices[0].message.content
            except:
                pass

        return jsonify({
            "analysis": analysis,
            "data": {
                "project_type": project_type,
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
                "timeline_months": months,
                "budget_gap": budget_gap,
                "budget_ratio": budget_ratio,
                "risk_score": risk,
                "deal_score": deal,
                "profit": {
                    "expected_profit": profit_mid,
                    "margin_percent": margin_mid
                },
                "flags": flags
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
