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
# HELPERS
# -----------------------------
def color(decision):
    return {
        "TAKE JOB": "green",
        "NEGOTIATE": "yellow",
        "REJECT": "red",
        "HIGH VALUE": "blue"
    }.get(decision, "gray")

# -----------------------------
# PARSERS
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

    if "sqm" in text or "m²" in text or "m2" in text:
        nums = re.findall(r"\d+\.?\d*", text)
        if nums:
            return float(nums[0]) * multiplier * 10.7639

    text = text.replace("square feet", "").replace("sqft", "").replace("sq ft", "").replace("ft", "")
    text = re.sub(r"\s*by\s*", "x", text)
    text = re.sub(r"\s*x\s*", "x", text)

    if "x" in text:
        parts = text.split("x")
        try:
            return float(parts[0]) * float(parts[1])
        except Exception:
            pass

    nums = re.findall(r"\d+\.?\d*", text)
    if nums:
        return float(nums[0]) * multiplier

    return 2000


def extract_timeline_months(text):
    if not text:
        return None

    text = str(text).lower()

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
    text = f"{project or ''} {description or ''}".lower()

    if any(x in text for x in ["warehouse", "factory", "industrial", "plant"]):
        return "industrial"
    if any(x in text for x in ["office", "retail", "apartment", "complex", "commercial", "mixed use"]):
        return "commercial"
    if "remodel" in text:
        return "remodel"
    return "residential"


def adjustments(materials, city, timeline, description):
    m = 1.0
    l = 1.0
    t = 1.0
    s = 1.0

    materials_text = (materials or "").lower()
    city_text = (city or "").lower()
    description_text = (description or "").lower()

    if "steel" in materials_text:
        m += 0.15
    if "luxury" in materials_text:
        m += 0.20
    if "concrete" in materials_text:
        m += 0.10

    if any(x in city_text for x in ["san francisco", "new york", "dubai", "seattle", "boston"]):
        l += 0.30
    elif "las vegas" in city_text:
        l += 0.10

    months = extract_timeline_months(timeline)
    if months:
        if months < 6:
            t += 0.15
        elif months > 36:
            t -= 0.05

    if any(x in description_text for x in ["slope", "steep", "hillside"]):
        s += 0.20

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

    r = budget / total if total else 0

    if r < 0.6:
        return "REJECT", "Budget too low"
    elif r < 0.9:
        return "NEGOTIATE", "Below expected cost"
    elif r <= 1.3:
        return "TAKE JOB", "Good alignment"
    else:
        return "HIGH VALUE", "High profit potential"


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
        flags.append("Budget far exceeds cost — verify scope.")
    if budget < cost:
        flags.append("Budget below estimated cost.")
    if months and months > 60:
        flags.append("Timeline unusually long.")
    if "luxury" in (materials or "").lower():
        flags.append("Luxury materials increase volatility.")
    if "slope" in (description or "").lower():
        flags.append("Slope increases construction complexity.")

    return flags

# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return {"status": "AI estimator running"}

@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(force=True) or {}

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

        profit_min = minb - total
        profit_mid = rec - total
        profit_max = agg - total
        margin_mid = (profit_mid / rec) * 100 if rec else 0

        score = lead_score(size, budget, total)
        dec, reason = decision(total, budget)
        risk = risk_score(budget, total, months)
        deal = deal_score(budget, total, risk, margin_mid)
        flags = build_flags(budget, total, months, data.get("materials", ""), data.get("description", ""))

        analysis = f"""Project Type: {project_type}
Estimated Cost: ${round(total):,}
Budget: ${round(budget):,}
Decision: {dec}
Reason: {reason}
Expected Profit: ${round(profit_mid):,}
Risk: {risk}/10
Deal Score: {deal}/10"""

        if client:
            try:
                prompt = f"""
You are a senior construction estimator.

Use ONLY these values:
Project Type: {project_type}
Size: {round(size):,} sqft
Budget: ${round(budget):,}
Estimated Cost: ${round(total):,}
Material Cost: ${round(material):,}
Labor Cost: ${round(labor):,}
Timeline: {round(months,1) if months else "unknown"} months
Recommended Bid: ${round(rec):,}
Aggressive Bid: ${round(agg):,}
Minimum Bid: ${round(minb):,}
Budget Gap: ${round(budget_gap):,}
Budget Ratio: {round(budget_ratio,2)}x
Lead Score: {score}/10
Decision: {dec}
Risk Score: {risk}/10
Deal Score: {deal}/10
Expected Profit: ${round(profit_mid):,}
Margin: {round(margin_mid,1)}%
Red Flags: {"; ".join(flags) if flags else "None"}

Write under these headings:
## 1. Cost Realism
## 2. Key Cost Drivers
## 3. Contractor Decision
## 4. Profit Outlook
## 5. Risk Level
## 6. Bid Strategy
## 7. Red Flags
"""
                res = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are a practical construction estimator and bid advisor."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.4
                )
                ai_text = res.choices[0].message.content
                if ai_text and ai_text.strip():
                    analysis = ai_text.strip()
            except Exception as openai_error:
                print("OpenAI error:", openai_error)

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
                    "min_profit": profit_min,
                    "expected_profit": profit_mid,
                    "max_profit": profit_max,
                    "margin_percent": margin_mid
                },
                "flags": flags
            }
        })

    except Exception as e:
        print("Analyze error:", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
