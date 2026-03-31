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
    flags
):
    flags_text = "\n".join([f"- {f}" for f in flags]) if flags else "- No major red flags."

    return f"""
Project: {project or "N/A"}
Type: {project_type}
Location: {city or "N/A"}
Size: {round(size_sqft):,} sqft

Estimated Cost: ${round(total_cost):,}
Timeline: {round(timeline_months,1) if timeline_months else "N/A"} months

Decision: {decision_label}
Reason: {decision_reason}

Expected Profit: ${round(expected_profit):,}
Margin: {round(margin_percent,1)}%

Risk: {risk}/10
Deal: {deal}/10

Flags:
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
You are a senior construction estimator evaluating a real job.

Be:
- practical
- skeptical
- financially focused
- like a contractor deciding whether to bid

PROJECT:
{project_type}, {round(size_sqft):,} sqft in {city}

KEY NUMBERS:
- Estimated Cost: ${round(total_cost):,}
- Budget: ${round(budget):,}
- Budget Ratio: {round(budget_ratio,2)}x
- Timeline: {round(timeline_months,1) if timeline_months else "unknown"} months

COST BREAKDOWN:
- Materials: ${round(material_cost):,}
- Labor: ${round(labor_cost):,}

BIDDING:
- Recommended: ${round(recommended_bid):,}
- Aggressive: ${round(aggressive_bid):,}
- Minimum: ${round(min_bid):,}

METRICS:
- Margin: {round(margin_percent,1)}%
- Expected Profit: ${round(expected_profit):,}
- Risk: {risk}/10
- Deal Score: {deal}/10

FLAGS:
{"; ".join(flags) if flags else "None"}

Write like a contractor deciding if this job is worth it.

STRUCTURE:

## 1. Cost Reality
## 2. Cost Drivers
## 3. Take or Pass
## 4. Profit Reality
## 5. Risk
## 6. Recommendation

Be direct. No fluff. No generic AI language.
"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a blunt, experienced construction estimator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        content = response.choices[0].message.content

        if content and content.strip():
            return content.strip()

        return None

    except Exception as e:
        print("AI error:", e)
        return None
