from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
import os

from cost_engine import (
    cost_per_sqft,
    detect_project_type,
    adjustments,
    build_cost_summary,
    normalize_scope,
    apply_scope_cost,
    estimate_rooms
)

from decision_engine import (
    color,
    lead_score,
    decision,
    risk_score,
    deal_score,
    build_flags,
    get_decision_color
)

from parsers import parse_budget, parse_size, extract_timeline_months
from ai_engine import build_fallback_analysis, build_ai_analysis
from plan_engine import analyze_uploaded_plan

app = Flask(__name__)
CORS(app)

client = None
api_key = os.getenv("OPENAI_API_KEY")
if api_key:
    client = OpenAI(api_key=api_key)


@app.route("/")
def home():
    return {"status": "construction intelligence system running"}


@app.route("/analyze-plan", methods=["POST"])
def analyze_plan():
    try:
        if not client:
            return jsonify({"error": "OpenAI not configured"}), 500

        file = request.files.get("file")
        if not file:
            return jsonify({"error": "No file uploaded"}), 400

        result = analyze_uploaded_plan(client, file)
        return jsonify(result)

    except Exception as e:
        print("Plan analysis error:", e)
        return jsonify({"error": str(e)}), 500


@app.route("/analyze", methods=["POST"])
def analyze():
    try:
        data = request.get_json(force=True) or {}

        project = data.get("project", "")
        scope_input = data.get("scope", "")
        size_raw = data.get("size", "")
        materials = data.get("materials", "")
        budget_raw = data.get("budget", "")
        timeline_raw = data.get("timeline", "")
        city = data.get("city", "")
        description = data.get("description", "")

        # -----------------------------
        # PARSING
        # -----------------------------
        size_sqft = parse_size(size_raw)
        budget = parse_budget(budget_raw)
        timeline_months = extract_timeline_months(timeline_raw)

        # -----------------------------
        # SCOPE (CLEAN + SAFE)
        # -----------------------------
        print("RAW SCOPE INPUT:", scope_input)

        scope = normalize_scope(scope_input)
        scope = str(scope).lower().strip()

        if not scope or scope == "ground_up":
            if scope_input and scope_input.strip():
                text = scope_input.lower()

                if "fram" in text:
                    scope = "framing"
                elif "elect" in text:
                    scope = "electrical"
                elif "plumb" in text:
                    scope = "plumbing"
                elif "hvac" in text:
                    scope = "hvac"
                elif "roof" in text:
                    scope = "roofing"
                elif "found" in text:
                    scope = "foundation"
                elif "interior" in text:
                    scope = "interior"
                elif "remodel" in text:
                    scope = "remodel"

        print("FINAL SCOPE:", scope)

        # -----------------------------
        # PROJECT TYPE
        # -----------------------------
        project_type = detect_project_type(project, description)

        if scope != "ground_up":
            project_type = f"{scope}_project"

                # -----------------------------
        # BASE COST
        # -----------------------------
        if scope == "ground_up":
            low, high = cost_per_sqft.get(project_type, (200, 400))
            base_cost_per_sqft = (low + high) / 2
        else:
            base_cost_per_sqft = apply_scope_cost(None, scope, city, size_sqft)
            low = base_cost_per_sqft * 0.8
            high = base_cost_per_sqft * 1.2

        print("COST/SQFT:", base_cost_per_sqft)

        base_cost = base_cost_per_sqft * size_sqft

        # -----------------------------
        # ADJUSTMENTS
        # -----------------------------
        material_factor, labor_factor, timeline_factor, site_factor = adjustments(
            materials=materials,
            city=city,
            timeline=timeline_raw,
            description=description
        )

        total_cost = base_cost * material_factor * labor_factor * timeline_factor * site_factor

        # -----------------------------
        # COST STABILITY LIMITS
        # -----------------------------
        min_cost = size_sqft * 8
        total_cost = max(total_cost, min_cost)

        max_cost = size_sqft * 600
        total_cost = min(total_cost, max_cost)

        # -----------------------------
        # ROOM BREAKDOWN
        # -----------------------------
        rooms = []
        if isinstance(data.get("rooms"), list):
            rooms = data.get("rooms")

        room_breakdown, room_total = estimate_rooms(rooms, 1.0)

        if room_total > 0:
            total_cost = (total_cost * 0.7) + (room_total * 0.3)

        # -----------------------------
        # COST SPLITS
        # -----------------------------
        material_cost = total_cost * 0.45
        labor_cost = total_cost * 0.55

        # -----------------------------
        # BIDS
        # -----------------------------
        recommended_bid = total_cost * 1.25
        aggressive_bid = total_cost * 1.18
        min_bid = total_cost * 1.10

        # -----------------------------
        # FINANCIALS
        # -----------------------------
        budget_gap = budget - total_cost if budget else 0
        budget_ratio = (budget / total_cost) if (budget and total_cost) else 0

        min_profit = min_bid - total_cost
        expected_profit = recommended_bid - total_cost
        max_profit = aggressive_bid - total_cost
        margin_percent = (expected_profit / recommended_bid * 100) if recommended_bid else 0

        # -----------------------------
        # DECISION ENGINE
        # -----------------------------
        lead = lead_score(size_sqft, budget, total_cost)
        decision_label, decision_reason = decision(total_cost, budget)
        decision_color = get_decision_color(decision_label)

        risk = risk_score(
            budget=budget,
            cost=total_cost,
            timeline_months=timeline_months,
            materials=materials,
            description=description
        )

        deal = deal_score(
            budget=budget,
            cost=total_cost,
            risk=risk,
            margin=margin_percent
        )

        flags = build_flags(
            budget=budget,
            cost=total_cost,
            timeline_months=timeline_months,
            materials=materials,
            description=description,
            size=size_sqft
        )

        # -----------------------------
        # SUMMARY
        # -----------------------------
        summary = build_cost_summary(
            project_type=project_type,
            size_sqft=size_sqft,
            city=city,
            low=low,
            high=high,
            base_cost=base_cost,
            total_cost=total_cost,
            material_factor=material_factor,
            labor_factor=labor_factor,
            timeline_factor=timeline_factor,
            site_factor=site_factor
        )

        # -----------------------------
        # ANALYSIS
        # -----------------------------
        analysis = build_fallback_analysis(
            project=project,
            city=city,
            project_type=project_type,
            size_sqft=size_sqft,
            total_cost=total_cost,
            timeline_months=timeline_months,
            decision_label=decision_label,
            decision_reason=decision_reason,
            expected_profit=expected_profit,
            margin_percent=margin_percent,
            risk=risk,
            deal=deal,
            flags=flags
        )

        if client:
            ai_text = build_ai_analysis(
                client=client,
                project=project,
                project_type=project_type,
                size_sqft=size_sqft,
                city=city,
                materials=materials,
                budget=budget,
                timeline_months=timeline_months,
                description=description,
                total_cost=total_cost,
                material_cost=material_cost,
                labor_cost=labor_cost,
                recommended_bid=recommended_bid,
                aggressive_bid=aggressive_bid,
                min_bid=min_bid,
                budget_gap=budget_gap,
                budget_ratio=budget_ratio,
                lead_score_value=lead,
                decision_label=decision_label,
                risk=risk,
                deal=deal,
                expected_profit=expected_profit,
                margin_percent=margin_percent,
                flags=flags,
                summary=summary
            )
            if ai_text:
                analysis = ai_text

        return jsonify({
            "analysis": analysis,
            "data": {
                "project_type": project_type,
                "scope": scope,
                "size_sqft": size_sqft,
                "budget": budget,
                "timeline_months": timeline_months,
                "total_cost": total_cost,
                "material_cost": material_cost,
                "labor_cost": labor_cost,
                "recommended_bid": recommended_bid,
                "aggressive_bid": aggressive_bid,
                "min_bid": min_bid,
                "budget_gap": budget_gap,
                "budget_ratio": budget_ratio,
                "lead_score": lead,
                "decision": decision_label,
                "decision_reason": decision_reason,
                "decision_color": decision_color,
                "risk_score": risk,
                "deal_score": deal,
                "rooms": room_breakdown,
                "profit": {
                    "min_profit": min_profit,
                    "expected_profit": expected_profit,
                    "max_profit": max_profit,
                    "margin_percent": margin_percent
                },
                "flags": flags
            }
        })

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
