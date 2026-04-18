def build_fallback_analysis(
    project,
    city,
    project_type,
    size_sqft,
    total_cost,
    timeline_months,
    decision_label,
    decision_reason,
    expected_profit,
    margin_percent,
    risk,
    deal,
    flags,
    contingency_percent=0,
    budget=0,
    budget_gap=0,
    recommended_bid=0,
    aggressive_bid=0,
    min_bid=0
):
    flags_text = "\n".join([f"- {f}" for f in flags]) if flags else "- No major red flags detected."

    budget_text = "No valid budget provided."
    if budget and total_cost:
        ratio = budget / total_cost
        if ratio >= 1.3:
            budget_text = "Budget is comfortably above estimated cost and supports healthy margin."
        elif ratio >= 1.0:
            budget_text = "Budget is in range of estimated cost and appears workable."
        elif ratio >= 0.9:
            budget_text = "Budget is slightly below estimated cost and likely requires negotiation."
        elif ratio >= 0.75:
            budget_text = "Budget is materially below estimated cost and carries real bid risk."
        else:
            budget_text = "Budget is far below estimated cost and is not currently viable without major change."

    return f"""
PROJECT SUMMARY
---------------
Project: {project or "N/A"}
Project Type: {project_type}
Location: {city or "N/A"}
Size: {int(round(size_sqft, -2)):,} sqft
Estimated Cost: ${int(round(total_cost, -3)):,}
Estimated Contingency: {round(contingency_percent, 1)}%
Timeline: {round(timeline_months, 1) if timeline_months else "N/A"} months

BUDGET POSITION
---------------
Client Budget: ${int(round(budget, -3)):,}""" + (f"""
Budget Gap: ${int(round(budget_gap, -3)):,}""" if budget else """
Budget Gap: N/A""") + f"""
Assessment: {budget_text}

BID STRATEGY
------------
Recommended Bid: ${int(round(recommended_bid, -3)):,}
Aggressive Bid: ${int(round(aggressive_bid, -3)):,}
Minimum Bid: ${int(round(min_bid, -3)):,}

DECISION
--------
Decision: {decision_label}
Reason: {decision_reason}

PROFIT / RISK
-------------
Expected Profit: ${int(round(expected_profit, -3)):,}
Expected Margin: {round(margin_percent, 1)}%
Risk Score: {risk}/10
Deal Score: {deal}/10

RED FLAGS
---------
{flags_text}
""".strip()


def build_ai_analysis(
    client,
    project,
    project_type,
    size_sqft,
    city,
    materials,
    budget,
    timeline_months,
    description,
    total_cost,
    material_cost,
    labor_cost,
    recommended_bid,
    aggressive_bid,
    min_bid,
    budget_gap,
    budget_ratio,
    lead_score_value,
    decision_label,
    risk,
    deal,
    expected_profit,
    margin_percent,
    flags,
    summary
):
    try:
        prompt = f"""
You are a senior construction estimator and bid reviewer writing a contractor-facing report.

STRICT RULES:
- Use ONLY the values below
- DO NOT invent numbers
- DO NOT change units
- DO NOT act like a sales assistant or consultant
- Write like an estimator reviewing whether a job is worth pursuing
- Keep the tone practical, direct, and grounded in contractor decision-making
- If the budget is below cost, say so clearly
- If the job is risky, say why in plain language
- Do not use vague filler like "careful consideration should be given"
- Avoid repeating the same point in multiple sections

PROJECT DATA:
- Project Name: {project}
- Project Type: {project_type}
- Size: {int(round(size_sqft, -2)):,} sqft
- Location: {city}
- Materials: {materials}
- Budget: ${int(round(budget, -3)):,}
- Timeline: {round(timeline_months, 1) if timeline_months else "unknown"} months
- Description: {description}

COST MODEL:
- Base low cost per sqft: ${round(summary["base_range_low_per_sqft"], 2)}
- Base high cost per sqft: ${round(summary["base_range_high_per_sqft"], 2)}
- Base cost before adjustments: ${int(round(summary["base_cost"], -3)):,}
- Material factor: {round(summary["material_factor"], 2)}
- Labor factor: {round(summary["labor_factor"], 2)}
- Timeline factor: {round(summary["timeline_factor"], 2)}
- Site factor: {round(summary["site_factor"], 2)}

OUTPUT VALUES:
- Estimated Cost: ${int(round(total_cost, -3)):,}
- Material Cost: ${int(round(material_cost, -3)):,}
- Labor Cost: ${int(round(labor_cost, -3)):,}
- Recommended Bid: ${int(round(recommended_bid, -3)):,}
- Aggressive Bid: ${int(round(aggressive_bid, -3)):,}
- Minimum Bid: ${int(round(min_bid, -3)):,}
- Budget Gap: ${int(round(budget_gap, -3)):,}
- Budget Ratio: {round(budget_ratio, 2)}x
- Lead Score: {lead_score_value}/10
- Decision: {decision_label}
- Risk Score: {risk}/10
- Deal Score: {deal}/10
- Expected Profit at Recommended Bid: ${int(round(expected_profit, -3)):,}
- Margin at Recommended Bid: {round(margin_percent, 1)}%
- Red Flags: {"; ".join(flags) if flags else "None"}

Write under these exact headings:

## 1. Cost Realism
## 2. Key Cost Drivers
## 3. Contractor Decision
## 4. Profit Outlook
## 5. Risk Level
## 6. Bid Strategy
## 7. Red Flags

Writing instructions:
- Keep each section tight and useful
- Prefer short paragraphs over long ones
- In Contractor Decision, explicitly state whether the budget is workable
- In Bid Strategy, explain when the recommended bid is likely too high for the client budget
- In Profit Outlook, do not present profit as truly achievable if the bid is not realistic relative to budget
- In Red Flags, be concrete and blunt
- Sound like a contractor advisor, not a generic AI summary tool
"""

        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "You are a practical construction estimator and bid advisor. You write like a real estimator reviewing job viability, budget fit, risk, and bid strategy."
                },
                {"role": "user", "content": prompt}
            ],
            temperature=0.25
        )

        content = res.choices[0].message.content
        return content.strip() if content and content.strip() else None

    except Exception as e:
        print("AI analysis error:", e)
        return None
