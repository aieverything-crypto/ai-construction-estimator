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
        # SCOPE DEBUG + FORCE FIX
        # -----------------------------
        print("RAW SCOPE INPUT FROM FRONTEND:", scope_input)

        scope = normalize_scope(scope_input)
        scope = str(scope).lower().strip()

        print("FINAL NORMALIZED SCOPE:", scope)

        # 🔥 FORCE FIX (GUARANTEED WORK)
        if scope_input and "fram" in scope_input.lower():
            print("FORCING SCOPE TO FRAMING")
            scope = "framing"

        print("FINAL SCOPE USED FOR COST:", scope)

        # -----------------------------
        # PROJECT TYPE
        # -----------------------------
        project_type = detect_project_type(project, description)

        if scope != "ground_up":
            project_type = f"{scope}_project"

        # -----------------------------
        # BASE COST (FIXED)
        # -----------------------------
        if scope == "ground_up":
            print("USING PROJECT TYPE PRICING")

            low, high = cost_per_sqft.get(project_type, (200, 400))
            base_cost_per_sqft = (low + high) / 2

        else:
            print("USING SCOPE PRICING")

            base_cost_per_sqft = apply_scope_cost(None, scope, city)

            low = base_cost_per_sqft * 0.8
            high = base_cost_per_sqft * 1.2

        print("COST PER SQFT:", base_cost_per_sqft)

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

        if scope == "ground_up":
            total_cost = base_cost * material_factor * labor_factor * timeline_factor * site_factor
        else:
            total_cost = base_cost * (1 + (labor_factor - 1) * 0.5)

        # -----------------------------
        # ROOM BREAKDOWN
        # -----------------------------
        rooms = []
        if isinstance(data.get("rooms"), list):
            rooms = data.get("rooms")

        room_breakdown, room_total = estimate_rooms(rooms, 1.0)

        total_cost = max(total_cost, room_total)

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

        # -----------------------------
        # DECISION
        # -----------------------------
        lead = lead_score(size_sqft, budget, total_cost)
        decision_label, decision_reason = decision(total_cost, budget)
        decision_color = get_decision_color(decision_label)

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
            expected_profit=recommended_bid - total_cost,
            margin_percent=20,
            risk=5,
            deal=5,
            flags=[]
        )

        return jsonify({
            "analysis": analysis,
            "data": {
                "project_type": project_type,
                "scope": scope,
                "total_cost": total_cost,
                "recommended_bid": recommended_bid,
                "lead_score": lead,
                "decision": decision_label,
                "decision_color": decision_color
            }
        })

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
