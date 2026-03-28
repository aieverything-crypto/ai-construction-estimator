>>> def build_fallback_analysis(
...     project,
...     city,
...     project_type,
...     size_sqft,
...     total_cost,
...     timeline_months,
...     decision_label,
...     decision_reason,
...     expected_profit,
...     margin_percent,
...     risk,
...     deal,
...     flags
... ):
...     flags_text = "\n".join([f"- {f}" for f in flags]) if flags else "- No major red flags detected."
... 
...     return f"""
... Project: {project or "N/A"}
... Project Type: {project_type}
... Location: {city or "N/A"}
... Size: {round(size_sqft):,} sqft
... Estimated Cost: ${round(total_cost):,}
... Timeline: {round(timeline_months, 1) if timeline_months else "N/A"} months
... 
... Decision: {decision_label}
... Reason: {decision_reason}
... 
... Expected Profit: ${round(expected_profit):,}
... Expected Margin: {round(margin_percent, 1)}%
... Risk Score: {risk}/10
... Deal Score: {deal}/10
... 
... Red Flags:
... {flags_text}
... """.strip()


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
You are a senior construction estimator writing a contractor-facing report.

STRICT RULES:
- Use ONLY the values below
- DO NOT invent numbers
- DO NOT change units
- Ground the report in practical construction reasoning

PROJECT DATA:
- Project Name: {project}
- Project Type: {project_type}
- Size: {round(size_sqft):,} sqft
- Location: {city}
- Materials: {materials}
- Budget: ${round(budget):,}
- Timeline: {round(timeline_months, 1) if timeline_months else "unknown"} months
- Description: {description}

COST MODEL:
- Base low/high cost per sqft: ${summary["base_range_low_per_sqft"]} / ${summary["base_range_high_per_sqft"]}
- Base cost before adjustments: ${round(summary["base_cost"]):,}
- Material factor: {round(summary["material_factor"], 2)}
- Labor factor: {round(summary["labor_factor"], 2)}
- Timeline factor: {round(summary["timeline_factor"], 2)}
- Site factor: {round(summary["site_factor"], 2)}

OUTPUT VALUES:
- Estimated Cost: ${round(total_cost):,}
- Material Cost: ${round(material_cost):,}
- Labor Cost: ${round(labor_cost):,}
- Recommended Bid: ${round(recommended_bid):,}
- Aggressive Bid: ${round(aggressive_bid):,}
- Minimum Bid: ${round(min_bid):,}
- Budget Gap: ${round(budget_gap):,}
- Budget Ratio: {round(budget_ratio, 2)}x
- Lead Score: {lead_score_value}/10
- Decision: {decision_label}
- Risk Score: {risk}/10
- Deal Score: {deal}/10
- Expected Profit at Recommended Bid: ${round(expected_profit):,}
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

Be specific, realistic, and useful to a contractor deciding whether to pursue the job.
"""
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a practical construction estimator and bid advisor."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.4
        )
        content = res.choices[0].message.content
        return content.strip() if content and content.strip() else None
    except Exception as e:
        print("AI analysis error:", e)
