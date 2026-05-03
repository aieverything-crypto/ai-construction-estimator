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
MAX_MVP_PAGES = 15
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


def merge_page_results(page_results):
    merged = {}

    for page_result in page_results:
        parsed = page_result.get("parsed") or {}
        merged = merge_plan_data(merged, parsed)

    merged = sanitize_plan_data(merged)

    merged["pages_analyzed"] = len(page_results)
    merged["notes"] = (
        f"MVP background processing analyzed the first {len(page_results)} pages only."
    )

    return merged


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
        page_results = []

        for page_index in range(pages_to_process):
            page_number = page_index + 1
            page_text = extract_page_text(file_bytes, page_index)

            if page_text and len(page_text.strip()) > 50:
                pre_data = pre_extract_plan_data(page_text)
                pre_data = sanitize_plan_data(pre_data)

                try:
                    raw, ai_parsed = analyze_pdf_text_with_ai(
                        client=client,
                        extracted_text=page_text[:12000],
                        pre_data=pre_data
                    )

                    merged = merge_plan_data(pre_data, ai_parsed)
                    merged = sanitize_plan_data(merged)

                    page_results.append({
                        "page": page_number,
                        "mode": "page_text_hybrid",
                        "raw": raw,
                        "parsed": merged,
                        "pre_extracted": pre_data
                    })

                except Exception as e:
                    page_results.append({
                        "page": page_number,
                        "mode": "page_text_preextract_only",
                        "raw": str(e),
                        "parsed": pre_data,
                        "pre_extracted": pre_data
                    })

            else:
                try:
                    png_bytes = render_pdf_page_to_png(
                        file_bytes=file_bytes,
                        page_number=page_index,
                        zoom=2
                    )

                    if not png_bytes:
                        page_results.append({
                            "page": page_number,
                            "mode": "page_no_text",
                            "raw": "No readable text and page image render failed.",
                            "parsed": {
                                "notes": "Page could not be analyzed."
                            },
                            "pre_extracted": {}
                        })

                    else:
                        raw, parsed = analyze_image_with_ai(client, png_bytes)
                        parsed = sanitize_plan_data(parsed or {})

                        page_results.append({
                            "page": page_number,
                            "mode": "page_image",
                            "raw": raw,
                            "parsed": parsed,
                            "pre_extracted": {}
                        })

                except Exception as e:
                    page_results.append({
                        "page": page_number,
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
