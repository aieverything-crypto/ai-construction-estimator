import uuid
import threading
import traceback
from collections import Counter

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
MAX_MVP_PAGES = 100
BATCH_SIZE = 5

GLOBAL_FACT_VOTE_FIELDS = [
    "project_type",
    "estimated_size_sqft",
    "stories",
    "bedrooms",
    "bathrooms",
    "foundation_type",
    "roof_type",
    "materials_hint"
]


def normalize_vote_value(value):
    if value in (None, "", [], {}):
        return None

    if isinstance(value, float):
        return round(value)

    if isinstance(value, int):
        return value

    return str(value).strip()


def vote_global_facts(page_results):
    votes = {field: Counter() for field in GLOBAL_FACT_VOTE_FIELDS}
    source_pages = {field: {} for field in GLOBAL_FACT_VOTE_FIELDS}

    for page in page_results:
        parsed = page.get("parsed") or {}
        page_type = page.get("page_type", "unknown")
        page_tags = page.get("page_tags", [])
        page_number = page.get("page")

        trusted = is_trusted_for_global_facts(page_type, page_tags)

        if not trusted:
            continue

        for field in GLOBAL_FACT_VOTE_FIELDS:
            value = normalize_vote_value(parsed.get(field))

            if value is None:
                continue

            weight = 1

            if page_type == "cover_sheet":
                weight = 5

            elif page_type == "floor_plan":
                weight = 3

            elif page_type == "site_civil":
                weight = 3

            elif page_type == "foundation":
                weight = 2

            elif page_type == "roof_plan":
                weight = 2

            votes[field][value] += weight

            if value not in source_pages[field]:
                source_pages[field][value] = []

            source_pages[field][value].append(page_number)

    final_facts = {}
    confidence = {}

    for field, counter in votes.items():
        if not counter:
            continue

        winner, winner_votes = counter.most_common(1)[0]
        total_votes = sum(counter.values())

        final_facts[field] = winner

        confidence[field] = {
            "value": winner,
            "confidence_percent": round((winner_votes / total_votes) * 100),
            "votes": winner_votes,
            "total_votes": total_votes,
            "source_pages": source_pages[field].get(winner, [])
        }

    return final_facts, confidence

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

def is_valid_project_type(value):
    if not value:
        return False

    value = str(value).lower().strip()

    invalid = [
        "structural",
        "mechanical",
        "electrical",
        "plumbing",
        "foundation",
        "roofing",
        "roof",
        "civil",
        "details",
        "modular construction"
    ]

    return value not in invalid

def build_page_insight(page_type, parsed):
    clues = []

    if (
        parsed.get("project_type")
        and page_type == "cover_sheet"
        and is_valid_project_type(parsed.get("project_type"))
    ):
        clues.append(f"project type: {parsed.get('project_type')}")

    if parsed.get("estimated_size_sqft") and page_type in ["cover_sheet", "floor_plan", "site_civil"]:
        clues.append(f"size: {int(round(parsed.get('estimated_size_sqft'))):,} sqft")

    if parsed.get("stories") and page_type in ["cover_sheet", "floor_plan", "site_civil"]:
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

import re

def extract_drawing_index_from_text(text):
    """
    Attempts to extract drawing/sheet index rows from plan text.
    Returns a list of sheets like:
    [{"sheet": "A1.0", "title": "Floor Plan", "discipline": "architectural"}]
    """
    if not text:
        return []

    lines = text.splitlines()
    sheets = []

    sheet_pattern = re.compile(
        r"\b([A-Z]{1,3}\d+(?:\.\d+)?(?:[A-Z])?)\b[\s\-:]+(.{3,80})",
        re.IGNORECASE
    )

    for line in lines:
        clean = " ".join(line.strip().split())

        if not clean:
            continue

        match = sheet_pattern.search(clean)

        if not match:
            continue

        sheet = match.group(1).upper()
        title = match.group(2).strip()

        # avoid junk matches
        if len(title) < 3:
            continue

        discipline = classify_sheet_discipline(sheet, title)

        sheets.append({
            "sheet": sheet,
            "title": title,
            "discipline": discipline
        })

    # de-dupe
    deduped = []
    seen = set()

    for item in sheets:
        key = item["sheet"]
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    return deduped


def classify_sheet_discipline(sheet, title):
    text = f"{sheet} {title}".lower()

    if sheet.startswith("A") or any(x in text for x in ["floor plan", "elevation", "section", "architectural"]):
        return "architectural"

    if sheet.startswith("S") or any(x in text for x in ["structural", "foundation", "framing", "shear", "beam"]):
        return "structural"

    if sheet.startswith("M") or any(x in text for x in ["mechanical", "hvac", "duct", "heat pump"]):
        return "mechanical"

    if sheet.startswith("E") or any(x in text for x in ["electrical", "lighting", "power", "panel"]):
        return "electrical"

    if sheet.startswith("P") or any(x in text for x in ["plumbing", "water", "sewer", "gas"]):
        return "plumbing"

    if sheet.startswith("C") or any(x in text for x in ["civil", "grading", "drainage", "erosion", "site"]):
        return "civil"

    if sheet.startswith("T") or any(x in text for x in ["title", "cover", "index", "general notes"]):
        return "title"

    return "unknown"

def rank_contractor_relevant_sheets(sheet_index):
    """
    Ranks sheets by usefulness for early contractor estimating/review.
    """
    ranked = []

    priority_keywords = {
        "floor plan": 10,
        "site plan": 9,
        "foundation": 9,
        "structural": 8,
        "framing": 8,
        "roof": 7,
        "mechanical": 7,
        "electrical": 7,
        "plumbing": 7,
        "elevation": 5,
        "section": 5,
        "schedule": 4,
        "detail": 3,
        "notes": 2,
        "cover": 2,
        "index": 2
    }

    discipline_bonus = {
        "architectural": 8,
        "structural": 8,
        "civil": 7,
        "mechanical": 6,
        "electrical": 6,
        "plumbing": 6,
        "title": 2,
        "unknown": 1
    }

    for sheet in sheet_index:
        title = (sheet.get("title") or "").lower()
        discipline = sheet.get("discipline", "unknown")

        score = discipline_bonus.get(discipline, 1)

        for keyword, value in priority_keywords.items():
            if keyword in title:
                score += value

        ranked.append({
            **sheet,
            "contractor_priority_score": min(score, 20)
        })

    ranked.sort(key=lambda x: x["contractor_priority_score"], reverse=True)
    return ranked
    
GLOBAL_FACT_FIELDS = [
    "project_type",
    "estimated_size_sqft",
    "stories",
    "bedrooms",
    "bathrooms",
    "location_data",
    "construction_type",
    "occupancy_class"
]

GLOBAL_TRUSTED_PAGE_TYPES = [
    "cover_sheet",
    "floor_plan",
    "site_civil"
]

LOCAL_DETAIL_PAGE_TYPES = [
    "structural",
    "mechanical",
    "electrical",
    "plumbing",
    "details",
    "foundation",
    "roof_plan",
    "unknown"
]


def is_trusted_for_global_facts(page_type, page_tags):
    if page_type in GLOBAL_TRUSTED_PAGE_TYPES:
        return True

    tags = page_tags or []

    if "cover_sheet" in tags or "floor_plan" in tags or "site_civil" in tags:
        return True

    return False


def strip_global_facts_from_local_page(parsed, page_type, page_tags):
    """
    Prevents detail sheets from overriding whole-project facts.
    Example: module connection page should not change project_type to modular construction.
    """
    if not isinstance(parsed, dict):
        return {}

    if is_trusted_for_global_facts(page_type, page_tags):
        return parsed

    cleaned = dict(parsed)

    for field in GLOBAL_FACT_FIELDS:
        if field in cleaned:
            cleaned.pop(field, None)

    return cleaned

def merge_page_results(page_results):
    merged = {}
    drawing_index = []

    for page_result in page_results:
        parsed = page_result.get("parsed") or {}
        page_type = page_result.get("page_type", "unknown")
        page_tags = page_result.get("page_tags", [])

        cleaned_parsed = strip_global_facts_from_local_page(
            parsed=parsed,
            page_type=page_type,
            page_tags=page_tags
        )

        merged = merge_plan_data(merged, cleaned_parsed)

        raw_text = page_result.get("raw") or ""
        possible_index = extract_drawing_index_from_text(raw_text)

        if possible_index:
            drawing_index.extend(possible_index)

    voted_facts, global_fact_confidence = vote_global_facts(page_results)

    for key, value in voted_facts.items():
        merged[key] = value

    merged["global_fact_confidence"] = global_fact_confidence
    
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
            "page_tags": page.get("page_tags", []),
            "page_importance": page.get("page_importance", 1),
            "mode": page.get("mode"),
            "insight": build_page_insight(page_type, page.get("parsed") or {})
        })

    merged["sheet_type_summary"] = sheet_types
    merged["page_insights"] = page_insights

    if drawing_index:
        # de-dupe again across pages
        seen = set()
        clean_index = []

        for item in drawing_index:
            key = item.get("sheet")
            if key and key not in seen:
                seen.add(key)
                clean_index.append(item)

        merged["drawing_index"] = clean_index
        merged["contractor_priority_sheets"] = rank_contractor_relevant_sheets(clean_index)[:12]

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

def classify_plan_page_tags(text):
    t = (text or "").lower()
    tags = []

    tag_rules = {
        "cover_sheet": ["cover sheet", "project data", "sheet index", "general notes"],
        "site_civil": ["site plan", "grading", "drainage", "erosion", "setback", "lot area"],
        "floor_plan": ["floor plan", "bedroom", "bathroom", "kitchen", "living room"],
        "foundation": ["foundation plan", "footing", "slab", "crawlspace", "basement"],
        "structural": ["structural", "shear wall", "beam", "joist", "rafter", "holdown"],
        "roof_plan": ["roof plan", "roofing", "ridge", "gable", "standing seam"],
        "mechanical": ["mechanical", "hvac", "heat pump", "air handler", "duct"],
        "electrical": ["electrical", "panel", "lighting", "receptacle", "service"],
        "plumbing": ["plumbing", "water heater", "fixture", "sewer", "drain"],
        "details": ["detail", "section", "schedule"]
    }

    for tag, keywords in tag_rules.items():
        if any(keyword in t for keyword in keywords):
            tags.append(tag)

    if not tags:
        tags.append("unknown")

    return tags

def score_page_importance(page_type, page_tags):
    score = 3

    high_value = ["cover_sheet", "site_civil", "floor_plan", "foundation"]
    medium_value = ["structural", "roof_plan", "mechanical", "electrical", "plumbing"]
    low_value = ["details", "unknown"]

    if page_type in high_value:
        score += 3
    elif page_type in medium_value:
        score += 2
    elif page_type in low_value:
        score -= 1

    for tag in page_tags or []:
        if tag in high_value:
            score += 1
        elif tag in medium_value:
            score += 1

    return max(1, min(10, score))

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
            page_tags = classify_plan_page_tags(page_text)
            page_importance = score_page_importance(page_type, page_tags)

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
                        "page_tags": page_tags,
                        "page_importance": page_importance,
                        "mode": "page_text_hybrid",
                        "raw": raw,
                        "parsed": merged,
                        "pre_extracted": pre_data
                    })

                except Exception as e:
                    page_results.append({
                        "page": page_number,
                        "page_type": page_type,
                        "page_tags": page_tags,
                        "page_importance": page_importance,
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
                            "page_tags": page_tags,
                            "page_importance": page_importance,
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
                            "page_tags": page_tags,
                            "page_importance": page_importance,
                            "mode": "page_image",
                            "raw": raw,
                            "parsed": parsed,
                            "pre_extracted": {}
                        })

                except Exception as e:
                    page_results.append({
                        "page": page_number,
                        "page_type": page_type,
                        "page_tags": page_tags,
                        "page_importance": page_importance,
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
