def color(decision_label):
    return {
        "TAKE JOB": "green",
        "NEGOTIATE": "yellow",
        "REJECT": "red",
        "HIGH VALUE": "blue"
    }.get(decision_label, "gray")


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

    ratio = (budget / total) if total else 0

    if ratio < 0.6:
        return "REJECT", "Budget is far below estimated cost"
    elif ratio < 0.9:
        return "NEGOTIATE", "Budget is below estimated cost"
    elif ratio <= 1.3:
        return "TAKE JOB", "Budget is reasonably aligned with cost"
    else:
        return "HIGH VALUE", "Budget supports strong margins"


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

    if "luxury" in materials_text or "premium" in materials_text:
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
        flags.append("Budget is far above expected cost; verify scope, land cost, or owner expectations.")

    if budget and budget < cost:
        flags.append("Budget is below estimated cost; expect negotiation pressure or scope reduction.")

    if timeline_months and timeline_months > 48:
        flags.append("Timeline is unusually long; this may indicate phasing, financing risk, or uncertainty.")

    if timeline_months and timeline_months < 6:
        flags.append("Timeline is aggressive; labor premiums and coordination risk are likely.")

    if "luxury" in materials_text or "premium" in materials_text:
        flags.append("Luxury materials increase procurement volatility and finish-quality risk.")

    if any(x in description_text for x in ["slope", "steep", "hillside", "limited access", "remote"]):
        flags.append("Site conditions may increase excavation, access, and foundation complexity.")

    if size > 50000:
        flags.append("Large project scale increases staging, coordination, and subcontractor management risk.")

    if size < 100:
        flags.append("Parsed size is unusually small; check input formatting.")

    return flags
    
def get_decision_color(decision):
    if decision == "STRONG BID":
        return "green"
    if decision == "CONSIDER":
        return "yellow"
    return "red"
