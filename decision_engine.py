def color(decision_label):
    return {
        "TAKE JOB": "green",
        "NEGOTIATE": "yellow",
        "REJECT": "red",
        "HIGH VALUE": "blue",
        "HIGH RISK": "red"
    }.get(decision_label, "gray")


def lead_score(size, budget, cost):
    if cost <= 0:
        return 1

    score = 5
    ratio = (budget / cost) if budget else 0

    if not budget or budget <= 0:
        score -= 3
    elif ratio < 0.5:
        score -= 4
    elif ratio < 0.75:
        score -= 2
    elif ratio < 0.9:
        score -= 1
    elif ratio <= 1.1:
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


def classify_lead(budget_ratio, risk, margin):
    if budget_ratio >= 1.3 and risk <= 3 and margin >= 20:
        return "A"
    elif budget_ratio >= 1.0 and risk <= 6:
        return "B"
    else:
        return "C"


def decision(total, budget):
    if not budget or budget <= 0:
        return "REJECT", "No valid budget"

    if not total or total <= 0:
        return "REJECT", "Invalid estimated cost"

    ratio = budget / total

    if ratio >= 1.3:
        return "HIGH VALUE", "Budget supports strong margins"
    elif ratio >= 1.0:
        return "TAKE JOB", "Budget meets or exceeds estimated cost"
    elif ratio >= 0.9:
        return "NEGOTIATE", "Slight budget gap"
    elif ratio >= 0.75:
        return "HIGH RISK", "Significant budget gap"
    else:
        return "REJECT", "Budget is far below estimated cost"


def risk_score(budget, cost, timeline_months, materials, description):
    risk = 4
    ratio = (budget / cost) if (budget and cost) else 0

    materials_text = (materials or "").lower()
    description_text = (description or "").lower()

    if budget and budget < cost:
        risk += 3
    elif ratio > 5:
        risk += 1

    if timeline_months:
        if timeline_months < 6:
            risk += 2
        elif timeline_months > 48:
            risk += 1

    if "luxury" in materials_text:
        risk += 1

    if any(x in description_text for x in ["slope", "steep", "hillside", "limited access", "remote"]):
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
        flags.append("Budget far above expected cost")

    if budget and budget < cost:
        flags.append("Budget below estimated cost")

    if timeline_months and timeline_months < 6:
        flags.append("Aggressive timeline")

    if "luxury" in materials_text:
        flags.append("High-end materials risk")

    if any(x in description_text for x in ["slope", "steep", "hillside"]):
        flags.append("Site complexity risk")

    if size > 50000:
        flags.append("Large project coordination risk")

    return flags


def get_decision_color(decision):
    if decision in ["TAKE JOB", "HIGH VALUE"]:
        return "green"
    if decision in ["NEGOTIATE"]:
        return "yellow"
    return "red"
