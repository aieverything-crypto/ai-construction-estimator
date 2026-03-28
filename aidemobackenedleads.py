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

    text = str(text).lower().replace(",", "").replace("$", "").strip()

    multiplier = 1

    if "billion" in text or "b" in text:
        multiplier = 1_000_000_000
    elif "million" in text or "m" in text:
        multiplier = 1_000_000
    elif "thousand" in text or "k" in text:
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

    nums = re.findall(r"\d+\.?\d*", text)
    if nums:
        return float(nums[0]) * multiplier

    return 2000

def extract_timeline_months(text):
    if not text:
        return None

    text = str(text).lower().strip()

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

    if any(word in text for word in ["warehouse", "factory", "industrial", "plant"]):
        return "industrial"

    if any(word in text for word in [
        "office", "retail", "store", "restaurant", "apartment",
        "complex", "multifamily", "mixed use", "commercial"
    ]):
        return "commercial"

    if any(word in text for word in ["remodel", "renovation", "tenant improvement", "addition"]):
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
    if "concrete" in materials_text:
        m += 0.10
    if "luxury" in materials_text or "premium" in materials_text or "high end" in materials_text:
        m += 0.20
    if "typical" in materials_text:
        m += 0.02

    if any(x in city_text for x in ["san francisco", "los angeles", "new york", "seattle", "boston"]):
        l += 0.30
    elif any(x in city_text for x in ["las vegas", "san diego", "san jose", "sacramento"]):
        l += 0.10

    months = extract_timeline_months(timeline)
    if months:
        if months < 6:
            t += 0.15
        elif months < 12:
            t += 0.08
        elif months > 36:
            t -= 0.03

    if any(x in description_text for x in ["slope", "steep", "hillside"]):
        s += 0.20
    if any(x in description_text for x in ["tight lot", "urban infill", "limited access"]):
        s += 0.10
    if any(x in description_text for x in ["outside of", "outskirts"]):
        s += 0.02

    return m, l, t, s


def lead_score(size, budget, cost):
    if cost <= 0:
        return 1

    score = 5
    ratio = (budget / cost) if budget else 0

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

    ratio = budget / total if total else 0

    if ratio < 0.6:
        return "REJECT", "Budget too low versus expected cost"
    elif ratio < 0.9:
        return "NEGOTIATE", "Budget below expected cost"
    elif ratio <= 1.3:
        return "TAKE JOB", "Budget aligns with expected cost"
    else:
        return "HIGH VALUE", "Strong margin potential"


def color(d):
    return {
        "TAKE JOB": "green",
        "NEGOTIATE": "yellow",
        "REJECT": "red",
        "HIGH VALUE": "blue"
    }.get(d, "gray")


def risk_score(budget, cost, timeline_months, materials, description):
    risk = 4

    ratio = (budget / cost) if (budget and cost) else 0

    if budget and budget < cost:
        risk += 3
    elif ratio > 5:
        risk += 1

    if timeline_months:
        if timeline_months < 6:
            risk += 2
        elif timeline_months > 48:
            risk += 1

    materials_text = (materials or "").lower()
    description_text = (description or "").lower()

    if "luxury" in materials_text or "premium" in materials_text:
        risk += 1

    if any(x in description_text for x in ["slope", "steep", "hillside", "limited access"]):
        risk += 2

    return max(1, min(10, risk))


def deal_score(budget, cost, risk, margin):
    score = 5
    ratio = (budget / cost) if cost else 0

    if ratio > 2:
        score += 2
    elif ratio >= 1:
        score += 1
    else:
        score -= 2

    if margin > 20:
        score += 2
    elif margin > 12:
        score += 1
    elif margin < 8:
        score -= 1

    if risk > 7:
        score -= 2
    elif risk <= 4:
        score += 1

    return max(1, min(10, score))


def build_flags(budget, cost, timeline_months, materials, description, size):
    flags = []

    ratio = (budget / cost) if (budget and cost) else 0
    materials_text = (materials or "").lower()
    description_text = (description or "").lower()

    if ratio > 5:
        flags.append("Budget is far above expected cost; verify scope, land cost, or hidden owner expectations.")

    if budget and budget < cost:
        flags.append("Budget is below estimated cost; expect scope reduction or negotiation pressure.")

    if timeline_months and timeline_months > 48:
        flags.append("Timeline is unusually long; this may indicate phased construction, financing risk, or scheduling uncertainty.")

    if timeline_months and timeline_months < 6:
        flags.append("Timeline is very aggressive; labor premiums and coordination risk are likely.")

    if "luxury" in materials_text or "premium" in materials_text:
        flags.append("Luxury materials increase procurement volatility and finish-quality risk.")

    if any(x in description_text for x in ["slope", "steep", "hillside", "limited access"]):
        flags.append("Site conditions may increase excavation, access, and foundation complexity.")

    if size > 50000:
        flags.append("Large project scale increases coordination, staging, and subcontractor management risk.")

    return flags


# -----------------------------
# ROUTES
# -----------------------------
@app.route("/")
def home():
    return {"status": "API running - intelligence system live"}


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.json or {}

        project = data.get("project", "")
        size_raw = data.get("size", "")
        materials = data.get("materials", "")
        budget_raw = data.get("budget", "")
        timeline_raw = data.get("timeline", "")
        city = data.get("city", "")
        description = data.get("description", "")

        size = parse_size(size_raw)
        budget = parse_budget(budget_raw)
        months = extract_timeline_months(timeline_raw)

        project_type = detect_project_type(project, description)

        low, high = cost_per_sqft[project_type]
        base = ((low + high) / 2) * size

        m, l, t, s = adjustments(materials, city, timeline_raw, description)
        total = base * m * l * t * s

        material = total * 0.45
        labor = total * 0.55

        rec = total * 1.25
        agg = total * 1.18
        minb = total * 1.10

        budget_gap = (budget - total) if budget else 0
        budget_ratio = (budget / total) if total and budget else 0

        profit_low = minb - total
        profit_mid = rec - total
        profit_high = agg - total
        margin_mid = ((profit_mid / rec) * 100) if rec else 0

        score = lead_score(size, budget, total)
        dec, reason = decision(total, budget)
        risk = risk_score(budget, total, months, materials, description)
        deal = deal_score(budget, total, risk, margin_mid)
        flags = build_flags(budget, total, months, materials, description, size)

        analysis = f"""
Project Type: {project_type}
Size: {round(size):,} sqft
Estimated Cost: ${round(total):,}
Timeline: {round(months, 1) if months else "N/A"} months

Decision: {dec}
Reason: {reason}

Expected Profit: ${round(profit_mid):,}
Expected Margin: {round(margin_mid, 1)}%
Risk Score: {risk}/10
Deal Score: {deal}/10
""".strip()

        if client:
            try:
                prompt = f"""
You are a senior construction estimator writing a contractor-facing report.

STRICT RULES:
- Use ONLY the values below
- DO NOT invent any numbers
- DO NOT change units
- Keep the report practical and contractor-focused

PROJECT DATA:
- Project Name: {project}
- Project Type: {project_type}
- Size: {round(size):,} sqft
- Location: {city}
- Materials: {materials}
- Budget: ${round(budget):,}
- Estimated Cost: ${round(total):,}
- Material Cost: ${round(material):,}
- Labor Cost: ${round(labor):,}
- Timeline: {round(months, 1) if months else "unknown"} months
- Recommended Bid: ${round(rec):,}
- Aggressive Bid: ${round(agg):,}
- Minimum Bid: ${round(minb):,}
- Budget Gap: ${round(budget_gap):,}
- Budget Ratio: {round(budget_ratio, 2)}x
- Lead Score: {score}/10
- Decision: {dec}
- Risk Score: {risk}/10
- Deal Score: {deal}/10
- Expected Profit at Recommended Bid: ${round(profit_mid):,}
- Expected Margin at Recommended Bid: {round(margin_mid, 1)}%
- Red Flags: {"; ".join(flags) if flags else "None"}

Write under these exact headings:

## 1. Cost Realism
## 2. Key Cost Drivers
## 3. Contractor Decision
## 4. Profit Outlook
## 5. Risk Level
## 6. Bid Strategy
## 7. Red Flags

Be specific, practical, and grounded in these numbers.
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
            except Exception:
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
                    "min_profit": profit_low,
                    "expected_profit": profit_mid,
                    "max_profit": profit_high,
                    "margin_percent": margin_mid
                },
                "flags": flags
            }
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
