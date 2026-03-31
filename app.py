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
    estimate_rooms,
    calculate_component_cost,
    estimate_duration
)

from decision_engine import (
    color,
    lead_score,
    decision,
    risk_score,
    deal_score,
    build_flags,
    get_decision_color,
    classify_lead
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
        print("🔥 ANALYZE HIT")

        data = request.get_json(force=True) or {}
        print("🔥 INPUT DATA:", data)

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

        print("🔥 PARSED:", size_sqft, budget, timeline_months)

        # -----------------------------
        # SCOPE
        # -----------------------------
        scope = normalize_scope(scope_input)
        scope = str(scope).lower().strip()

        print("🔥 SCOPE:", scope)

        # -----------------------------
        # COMPONENT COST TEST ONLY
        # -----------------------------
        result = calculate_component_cost(scope, size_sqft, city, rooms={})
        print("🔥 COMPONENT RESULT:", result)

        return jsonify({
            "status": "debug success",
            "scope": scope,
            "size": size_sqft,
            "component": result
        })

    except Exception as e:
        import traceback
        traceback.print_exc()

        return jsonify({
            "error": str(e),
            "trace": traceback.format_exc()
        }), 500

    except Exception as e:
        print("ERROR:", e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True)
