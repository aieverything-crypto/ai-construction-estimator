import uuid
import threading
import traceback

try:
    import fitz
except ImportError:
    fitz = None

from plan_engine import (
    pre_extract_plan_data,
    sanitize_plan_data,
    analyze_pdf_text_with_ai,
    analyze_image_with_ai,
    merge_plan_data,
    render_pdf_page_to_png,
)

PLAN_JOBS = {}
MAX_MVP_PAGES = 5
BATCH_SIZE = 5


def create_plan_job(filename):
    job_id = str(uuid.uuid4())

    PLAN_JOBS[job_id] = {
        "job_id": job_id,
        "filename": filename,
        "status": "queued",
        "progress": 0,
        "pages_processed": 0,
        "total_pages": 0,
        "result": None,
        "error": None,
        "current_page": None,
        "current_step": "queued",
        "pages_target": 0,
        
    }

    return job_id


def get_plan_job(job_id):
    return PLAN_JOBS.get(job_id)


def get_pdf_page_count(file_bytes):
    if not fitz:
        return 0

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        return len(doc)
    except Exception:
        return 0


def extract_page_text(file_bytes, page_index):
    if not fitz:
        return ""

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")

        if page_index >= len(doc):
            return ""

        page = doc[page_index]
        return page.get_text() or ""

    except Exception:
        return ""

def build_contractor_plan_summary(parsed):
    summary = []

    project_type = parsed.get("project_type")
    size = parsed.get("estimated_size_sqft")
    stories = parsed.get("stories")
    materials = parsed.get("materials_hint")
    foundation = parsed.get("foundation_type")
    roof = parsed.get("roof_type")

    if project_type:
        summary.append(f"Detected project type appears to be {project_type}.")

    if size:
        summary.append(f"Detected approximate project size is {int(round(size)):,} sqft.")

    if stories:
        summary.append(f"The plan appears to show a {stories}-story structure.")

    if materials:
        summary.append(f"Material clues include: {materials}.")

    if foundation:
        summary.append(f"Foundation condition appears to involve {foundation}.")

    if roof:
        summary.append(f"Roof type appears to be {roof}.")

    scope = parsed.get("scope_of_work") or []
    if scope:
        summary.append("Detected scope items include " + ", ".join(scope[:8]) + ".")

    risks = parsed.get("risk_flags") or []
    site = parsed.get("site_constraints") or []
    structural = parsed.get("structural_flags") or []

    all_risks = risks + site + structural

    if all_risks:
        summary.append(
            "Contractor should review these risk items closely: "
            + ", ".join(all_risks[:8])
            + "."
        )

    systems = parsed.get("mechanical_systems") or []
    if systems:
        summary.append(
            "MEP/system coordination may be needed for: "
            + ", ".join(systems[:8])
            + "."
        )

    if not summary:
        return "The uploaded plan was analyzed, but not enough reliable construction detail was detected to generate a strong contractor summary."

    return " ".join(summary)
    
def build_page_insight(page_type, parsed):
    clues = []

    if parsed.get("project_type"):
        clues.append(f"project type: {parsed.get('project_type')}")

    if parsed.get("estimated_size_sqft"):
        clues.append(f"size: {int(round(parsed.get('estimated_size_sqft'))):,} sqft")

    if parsed.get("stories"):
        clues.append(f"stories: {parsed.get('stories')}")

    if parsed.get("bedrooms"):
        clues.append(f"bedrooms: {parsed.get('bedrooms')}")

    if parsed.get("bathrooms"):
        clues.append(f"bathrooms: {parsed.get('bathrooms')}")

    if parsed.get("foundation_type"):
        clues.append(f"foundation: {parsed.get('foundation_type')}")

    if parsed.get("roof_type"):
        clues.append(f"roof: {parsed.get('roof_type')}")

    if parsed.get("materials_hint"):
        clues.append(f"materials: {parsed.get('materials_hint')}")

    scope = parsed.get("scope_of_work") or []
    if scope:
        clues.append("scope: " + ", ".join(scope[:5]))

    risks = parsed.get("risk_flags") or []
    if risks:
        clues.append("risks: " + ", ".join(risks[:5]))

    systems = parsed.get("mechanical_systems") or []
    if systems:
        clues.append("systems: " + ", ".join(systems[:5]))

    if not clues:
        return f"{page_type} page analyzed, but no strong structured clues were detected."

    return f"{page_type} page contributed " + "; ".join(clues) + "."

def build_plan_scores(parsed):
    complexity = 3
    site_risk = 2
    mep_coordination = 2
    confidence = 3

    structural_flags = parsed.get("structural_flags") or []
    site_constraints = parsed.get("site_constraints") or []
    mechanical_systems = parsed.get("mechanical_systems") or []
    risk_flags = parsed.get("risk_flags") or []
    scope = parsed.get("scope_of_work") or []

    if parsed.get("estimated_size_sqft"):
        confidence += 2

        if parsed["estimated_size_sqft"] > 3000:
            complexity += 1
        if parsed["estimated_size_sqft"] > 6000:
            complexity += 2

    if parsed.get("stories") and parsed["stories"] >= 2:
        complexity += 1

    if structural_flags:
        complexity += min(len(structural_flags), 3)

    if site_constraints:
        site_risk += min(len(site_constraints), 4)

    if risk_flags:
        site_risk += min(len(risk_flags), 3)

    if mechanical_systems:
        mep_coordination += min(len(mechanical_systems), 4)

    if len(scope) >= 5:
        complexity += 1
        confidence += 1

    if parsed.get("materials_hint"):
        confidence += 1

    if parsed.get("foundation_type"):
        confidence += 1

    if parsed.get("roof_type"):
        confidence += 1

    complexity = max(1, min(10, complexity))
    site_risk = max(1, min(10, site_risk))
    mep_coordination = max(1, min(10, mep_coordination))
    confidence_num = max(1, min(10, confidence))

    if confidence_num >= 8:
        confidence_label = "High"
    elif confidence_num >= 5:
        confidence_label = "Medium"
    else:
        confidence_label = "Low"

    return {
        "complexity_score": complexity,
        "site_risk_score": site_risk,
        "mep_coordination_score": mep_coordination,
        "estimate_confidence_score": confidence_num,
        "estimate_confidence": confidence_label
    }

def merge_page_results(page_results):
    merged = {}

    for page_result in page_results:
        parsed = page_result.get("parsed") or {}
        merged = merge_plan_data(merged, parsed)

    merged = sanitize_plan_data(merged)

    merged["pages_analyzed"] = len(page_results)

    merged["contractor_summary"] = build_contractor_plan_summary(merged)
    merged["plan_scores"] = build_plan_scores(merged)

    sheet_types = {}
    page_insights = []

    for page in page_results:
        page_type = page.get("page_type", "unknown")
        sheet_types[page_type] = sheet_types.get(page_type, 0) + 1

        page_insights.append({
            "page": page.get("page"),
            "page_type": page_type,
            "mode": page.get("mode"),
            "insight": build_page_insight(page_type, page.get("parsed") or {})
        })

    merged["sheet_type_summary"] = sheet_types
    merged["page_insights"] = page_insights

    merged["notes"] = (
        f"Background processing analyzed the first {len(page_results)} pages in batches. "
        "Full-plan processing can be enabled after testing stability."
    )

    return merged

def classify_plan_page(text):
    t = (text or "").lower()

    if any(x in t for x in ["cover sheet", "project data", "sheet index", "general notes"]):
        return "cover_sheet"

    if any(x in t for x in ["site plan", "grading", "drainage", "erosion", "setback", "lot area"]):
        return "site_civil"

    if any(x in t for x in ["floor plan", "bedroom", "bathroom", "kitchen", "living room"]):
        return "floor_plan"

    if any(x in t for x in ["foundation plan", "footing", "slab", "crawlspace", "basement"]):
        return "foundation"

    if any(x in t for x in ["structural", "shear wall", "beam", "joist", "rafter", "holdown"]):
        return "structural"

    if any(x in t for x in ["roof plan", "roofing", "ridge", "gable", "standing seam"]):
        return "roof_plan"

    if any(x in t for x in ["mechanical", "hvac", "heat pump", "air handler", "duct"]):
        return "mechanical"

    if any(x in t for x in ["electrical", "panel", "lighting", "receptacle", "service"]):
        return "electrical"

    if any(x in t for x in ["plumbing", "water heater", "fixture", "sewer", "drain"]):
        return "plumbing"

    if any(x in t for x in ["detail", "section", "schedule"]):
        return "details"

    return "unknown"

def process_plan_job(job_id, client, file_bytes, filename):
    job = PLAN_JOBS[job_id]

    try:
        job["status"] = "processing"
        job["progress"] = 5

        if not filename.lower().endswith(".pdf"):
            job["status"] = "failed"
            job["progress"] = 100
            job["error"] = "Background plan jobs currently support PDF files only."
            return

        total_pages = get_pdf_page_count(file_bytes)
        job["total_pages"] = total_pages

        if total_pages <= 0:
            job["status"] = "failed"
            job["progress"] = 100
            job["error"] = "Could not read PDF page count."
            return

        pages_to_process = min(total_pages, MAX_MVP_PAGES)
        job["pages_target"] = pages_to_process
        page_results = []

        for page_index in range(pages_to_process):
            page_number = page_index + 1

            job["current_page"] = page_number
            job["current_step"] = "extracting page text"

            page_text = extract_page_text(file_bytes, page_index)
            page_type = classify_plan_page(page_text)
            job["current_step"] = f"classified page as {page_type}"

            if page_text and len(page_text.strip()) > 50:
                job["current_step"] = "pre-extracting page data"

                pre_data = pre_extract_plan_data(page_text)
                pre_data = sanitize_plan_data(pre_data)

                try:
                    job["current_step"] = "running AI text analysis"
                    
                    raw, ai_parsed = analyze_pdf_text_with_ai(
                        client=client,
                        extracted_text=page_text[:12000],
                        pre_data=pre_data
                    )

                    merged = merge_plan_data(pre_data, ai_parsed)
                    merged = sanitize_plan_data(merged)

                    page_results.append({
                        "page": page_number,
                        "page_type": page_type,
                        "mode": "page_text_hybrid",
                        "raw": raw,
                        "parsed": merged,
                        "pre_extracted": pre_data
                    })

                except Exception as e:
                    page_results.append({
                        "page": page_number,
                        "page_type": page_type,
                        "mode": "page_text_preextract_only",
                        "raw": str(e),
                        "parsed": pre_data,
                        "pre_extracted": pre_data
                    })

            else:
                try:
                    job["current_step"] = "rendering scanned PDF page"

                    png_bytes = render_pdf_page_to_png(
                        file_bytes=file_bytes,
                        page_number=page_index,
                        zoom=2
                    )

                    if not png_bytes:
                        page_results.append({
                            "page": page_number,
                            "page_type": page_type,
                            "mode": "page_no_text",
                            "raw": "No readable text and page image render failed.",
                            "parsed": {
                                "notes": "Page could not be analyzed."
                            },
                            "pre_extracted": {}
                        })

                    else:
                        job["current_step"] = "running AI image analysis"
                        
                        raw, parsed = analyze_image_with_ai(client, png_bytes)
                        parsed = sanitize_plan_data(parsed or {})

                        page_results.append({
                            "page": page_number,
                            "page_type": page_type,
                            "mode": "page_image",
                            "raw": raw,
                            "parsed": parsed,
                            "pre_extracted": {}
                        })

                except Exception as e:
                    page_results.append({
                        "page": page_number,
                        "page_type": page_type,
                        "mode": "page_image_error",
                        "raw": str(e),
                        "parsed": {
                            "notes": "Image analysis failed for this page."
                        },
                        "pre_extracted": {}
                    })

            job["pages_processed"] = page_number
            job["progress"] = int((page_number / pages_to_process) * 90)

        final_result = merge_page_results(page_results)

        job["status"] = "complete"
        job["progress"] = 100
        job["current_step"] = "complete"
        job["current_page"] = None
        job["result"] = {
            "mode": "background_pdf_mvp",
            "pages_requested": total_pages,
            "pages_analyzed": pages_to_process,
            "parsed": final_result,
            "page_results": page_results
        }

    except Exception as e:
        print("Background plan job error:", e)
        traceback.print_exc()

        job["status"] = "failed"
        job["progress"] = 100
        job["error"] = str(e)


def start_plan_job(job_id, client, file_bytes, filename):
    thread = threading.Thread(
        target=process_plan_job,
        args=(job_id, client, file_bytes, filename),
        daemon=True
    )
    thread.start()
