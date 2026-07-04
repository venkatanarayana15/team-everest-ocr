import json
import logging
import pickle
import re
import time
from pathlib import Path

import cv2
import numpy as np

from src.config import Config
from src.extraction_pipeline import ExtractionPipeline, StructuredField
from src.model_client import get_model_client
from src.page_classifier import PageClassifier
from src.renderers import _render_markdown, _format_job_datetime
from src.status import (
    _set_status, _save_checkpoint, _load_checkpoint, _cleanup_intermediate,
    _get_status, _progress_store, _progress_lock,
)

logger = logging.getLogger(__name__)


def _validate_pdf(path: str) -> tuple[bool, str]:
    p = Path(path)
    if not p.exists():
        return False, f"File not found: {path}"
    if p.stat().st_size == 0:
        return False, f"Empty file: {path}"
    try:
        import fitz
        doc = fitz.open(path)
        num_pages = len(doc)
        doc.close()
        if num_pages == 0:
            return False, f"PDF has no pages: {path}"
    except Exception as e:
        return False, f"Invalid/corrupted PDF: {e}"
    return True, ""


def _save_tesseract_data(job_dir: Path, word_boxes: list) -> None:
    pages_data: dict[int, list[dict]] = {}
    for wb in word_boxes:
        p = wb.page_num
        if p not in pages_data:
            pages_data[p] = []
        pages_data[p].append({
            "text": wb.text, "page": p,
            "bbox": list(wb.bbox), "confidence": wb.confidence,
        })
    data = {"pages": {str(k): v for k, v in pages_data.items()}}
    path = job_dir / "tesseract_data.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    logger.info("Saved tesseract data for %d pages (%d total words)", len(pages_data), len(word_boxes))


def _validate_images(image_paths: list[str]) -> tuple[bool, str]:
    for p in image_paths:
        path = Path(p)
        if not path.exists():
            return False, f"Image not found: {p}"
        if path.stat().st_size == 0:
            return False, f"Empty image: {p}"
    return True, ""


def _set_batch_pdf_status(job_dir: Path, pdf_name: str, status: str, pct: int, message: str = "") -> None:
    path = job_dir / "status.json"
    existing = {}
    if path.exists():
        try:
            with open(path) as f:
                existing = json.load(f)
        except Exception:
            pass

    log = existing.get("log", [])
    if message:
        from datetime import datetime
        log.append({"t": datetime.now().strftime("%H:%M:%S"), "msg": f"[{pdf_name}] {message}"})

    data = {
        "status": "processing",
        "message": f"Processing {pdf_name}: {message}" if message else existing.get("message", ""),
        "log": log,
        "pages": existing.get("pages", 0),
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    with _progress_lock:
        existing_progress = _progress_store.get(job_dir.name, {})
        start_time = existing_progress.get("start_time")
        if not start_time:
            start_time = time.time()
        elapsed = round(time.time() - start_time, 1)

        pdfs_map = existing_progress.get("pdfs", {})
        pdfs_map[pdf_name] = {"progress": pct, "stage": status, "elapsed": elapsed}

        total_pct = sum(item["progress"] for item in pdfs_map.values())
        overall_pct = round(total_pct / len(pdfs_map)) if pdfs_map else 0

        _progress_store[job_dir.name] = {
            "overall": overall_pct,
            "pdfs": pdfs_map,
            "start_time": start_time,
            "elapsed": elapsed,
        }


def _wait_for_memory(job_dir: Path, min_free_mem_mb: int = 512, timeout: int = 3600) -> bool:
    import psutil
    start = time.time()
    while time.time() - start < timeout:
        free = psutil.virtual_memory().available / (1024 * 1024)
        if free >= min_free_mem_mb:
            return True
        logger.warning("Low memory: %.0f MB free (need %d MB). Delaying job...", free, min_free_mem_mb)
        time.sleep(5)
    _set_status(job_dir, "error",
        f"Timed out waiting for memory (>{timeout}s, "
        f"free={free:.0f} MB < {min_free_mem_mb} MB). Try again later.")
    return False


def _ensure_page_images(pages_dir: Path) -> dict[int, str]:
    if not pages_dir.exists():
        return {}
    return {
        int(p.stem.split("_")[1]): str(p)
        for p in sorted(pages_dir.glob("page_*.png")) if "_original" not in p.stem
    }


def _fields_to_dict(fields: list[StructuredField]) -> list[dict]:
    return [
        {
            "label": f.label, "value": f.value, "confidence": f.confidence,
            "page": f.page, "section_number": f.section_number,
            "bbox": list(f.bbox) if f.bbox else None,
            "value_bbox": list(f.value_bbox) if f.value_bbox else None,
            "needs_clarification": f.needs_clarification, "reason": f.reason,
            "is_verified": f.is_verified, "verifier_confidence": f.verifier_confidence,
            "verification_note": f.verification_note,
            "extracted_by": f.extracted_by, "verified_by": f.verified_by,
            "original_value": f.original_value,
        }
        for f in fields
    ]


def _save_results(job_dir: Path, result_dict: dict, job_id: str) -> None:
    results_dir = job_dir / "results"
    results_dir.mkdir(exist_ok=True)

    with open(results_dir / "result.json", "w") as f:
        json.dump(result_dict, f, indent=2)

    md_content = _render_markdown(result_dict, job_id)
    with open(results_dir / "result.md", "w") as f:
        f.write(md_content)

    txt = re.sub(r'#{1,6}\s+', '', md_content)
    txt = re.sub(r'\*\*(.+?)\*\*', r'\1', txt)
    txt = re.sub(r'\*(.+?)\*', r'\1', txt)
    txt = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', txt)
    txt = re.sub(r'\|.*?\|', '', txt)
    txt = re.sub(r'[-]{2,}', '', txt)
    txt = re.sub(r'\n{3,}', '\n\n', txt)
    with open(results_dir / "result.txt", "w") as f:
        f.write(txt.strip())

    try:
        import markdown
        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])
    except ImportError:
        html_body = f"<pre>{md_content}</pre>"
    html_page = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>OCR Extraction — {job_id}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 800px; margin: 2em auto; padding: 0 1em; line-height: 1.6; color: #1e293b; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #cbd5e1; padding: 6px 10px; text-align: left; }}
  th {{ background: #f8fafc; font-weight: 600; }}
  pre {{ background: #f1f5f9; padding: 1em; border-radius: 6px; overflow-x: auto; }}
  code {{ background: #f1f5f9; padding: 1px 4px; border-radius: 3px; font-size: 0.9em; }}
</style>
</head>
<body>
{html_body}
</body>
</html>"""
    with open(results_dir / "result.html", "w") as f:
        f.write(html_page)

    cp = job_dir / "checkpoint.json"
    if cp.exists():
        cp.unlink()


def _run_core_extraction(
    job_dir: Path,
    pdf_path: str,
    processed_images: dict[int, str],
    pipeline: ExtractionPipeline,
    primary_name: str,
    secondary_name: str,
    status_func,
    use_cache: bool = False,
    checkpoint = None,
) -> dict:
    # 1. Primary Extraction & OCR (Tesseract)
    if checkpoint:
        step, fields, overall_confidence, raw_text, sections_data = checkpoint
        word_boxes = []
        primary_token_usage = {}
    else:
        status_func("primary_extraction", f"Running Tesseract + primary extraction ({primary_name})...")
        results: dict = {}
        
        def _run_tesseract():
            bbox_cache = job_dir / "bbox_cache.pkl"
            if use_cache and bbox_cache.exists():
                with open(bbox_cache, "rb") as f:
                    results["word_boxes"] = pickle.load(f)
            else:
                results["word_boxes"] = pipeline.run_bbox_images(processed_images)
                if use_cache:
                    with open(bbox_cache, "wb") as f:
                        pickle.dump(results["word_boxes"], f)

        def _run_llm():
            results["model_data"], results["primary_token_usage"] = pipeline.run_primary_extraction(pdf_path, processed_images)

        from concurrent.futures import ThreadPoolExecutor as _TempPool
        with _TempPool(max_workers=2) as pool:
            pool.submit(_run_tesseract).result()
            pool.submit(_run_llm).result()

        word_boxes = results.get("word_boxes", [])
        model_data = results.get("model_data")
        primary_token_usage = results.get("primary_token_usage", {})
        _save_tesseract_data(job_dir, word_boxes)

        if model_data:
            overall_confidence = model_data.get("overall_confidence", 0)
            raw_text = model_data.get("raw_text", "")
            raw_text = _insert_page_markers(raw_text, model_data.get("fields", []))
            fields = pipeline.merge_fields(model_data, word_boxes, prefix=primary_name)
            status_func("field_mapping", f"Merged {len(fields)} fields.")
        else:
            status_func("field_mapping", "Primary extraction failed — using Tesseract words.")
            fields = [
                StructuredField(label=wb.text, value=wb.text, confidence=int(wb.confidence),
                                page=wb.page_num, bbox=wb.bbox, extracted_by=primary_name)
                for wb in word_boxes
            ]

        sections_data = (model_data or {}).get("sections") or []
        derived = _derive_sections(fields, raw_text)
        existing_nums = {s["number"] for s in sections_data}
        for ds in derived:
            if ds["number"] not in existing_nums:
                sections_data.append(ds)
        sections_data.sort(key=lambda s: s["number"])

        _save_checkpoint(job_dir, "mapped", fields, overall_confidence, raw_text, sections=sections_data)

    # 2. Secondary Verification
    skip_secondary = False
    if overall_confidence is not None and overall_confidence >= 95:
        if not any(getattr(f, 'needs_clarification', False) for f in fields):
            skip_secondary = True

    if not skip_secondary:
        status_func("secondary_verification", f"Running secondary verification ({secondary_name})...")
        fields, secondary_token_usage = pipeline.verify_secondary(fields, word_boxes, str(job_dir), prefix=secondary_name)
    else:
        secondary_token_usage = {}

    token_usage = {
        "primary": primary_token_usage,
        "secondary": secondary_token_usage,
        "total": {
            "prompt_tokens": (primary_token_usage.get("prompt_tokens", 0) or 0) + (secondary_token_usage.get("prompt_tokens", 0) or 0),
            "completion_tokens": (primary_token_usage.get("completion_tokens", 0) or 0) + (secondary_token_usage.get("completion_tokens", 0) or 0),
            "total_tokens": (primary_token_usage.get("total_tokens", 0) or 0) + (secondary_token_usage.get("total_tokens", 0) or 0),
        },
    }

    status_func("template_fill", "Filling missing template fields...")
    fields = ExtractionPipeline.fill_missing_template_fields(fields)
    sections_data = _derive_sections(fields, raw_text or "")

    return {
        "overall_confidence": overall_confidence,
        "num_pages": len(processed_images),
        "raw_text": raw_text or "",
        "primary_model": primary_name,
        "secondary_model": secondary_name,
        "token_usage": token_usage,
        "sections": sections_data or [],
        "fields": _fields_to_dict(fields),
    }


def _save_to_db(job_dir: Path) -> None:
    results_path = job_dir / "results" / "result.json"
    if not results_path.exists():
        return
    try:
        from src.database import upsert_ocr_document
    except ImportError:
        logger = logging.getLogger(__name__)
        logger.info("DB module not available, skipping auto-save")
        return

    import asyncio
    logger = logging.getLogger(__name__)
    try:
        with open(results_path) as f:
            result_data = json.load(f)
        name_path = job_dir / "original_name.txt"
        orig_name = name_path.read_text().strip() if name_path.exists() else job_dir.name
        logger.info(
            "Uploading extracted data to Supabase... (file=%r, fields=%d, confidence=%s, time=%.2fs)",
            orig_name,
            len(result_data.get("fields", [])),
            result_data.get("overall_confidence", "N/A"),
            result_data.get("processing_time", 0),
        )
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(upsert_ocr_document(
                job_id=job_dir.name,
                file_name=orig_name,
                status="done",
                processing_time=result_data.get("processing_time"),
                confidence_score=result_data.get("overall_confidence"),
                num_pdfs=result_data.get("num_pdfs"),
                result_json=result_data,
            ))
        finally:
            loop.close()
        logger.info("Auto-save to DB succeeded for job %s", job_dir.name)
    except Exception as e:
        logger.warning("Auto-save to DB failed for job %s: %s", job_dir.name, e)


def run_pipeline(job_dir: Path, pdf_path: str) -> None:
    if not _wait_for_memory(job_dir):
        return
    try:
        t0 = time.time()
        name_path = job_dir / "original_name.txt"
        pdf_name = name_path.read_text().strip() if name_path.exists() else Path(pdf_path).name

        valid, err_msg = _validate_pdf(pdf_path)
        if not valid:
            _set_status(job_dir, "error", err_msg)
            return

        config = Config()
        primary = get_model_client("primary")
        secondary = get_model_client("secondary")
        pipeline = ExtractionPipeline(config, primary_client=primary, secondary_client=secondary)

        checkpoint = _load_checkpoint(job_dir)
        if not checkpoint:
            _set_status(job_dir, "preprocessing", f"Preprocessing PDF ({pdf_name})...")
            pipeline.preprocess(pdf_path, str(job_dir))
            _set_status(job_dir, "preprocessing", "Preprocessing done.", pages=6)

        processed_images = _ensure_page_images(job_dir / "pages")
        
        def status_func(stage, msg):
            _set_status(job_dir, stage, msg)

        res = _run_core_extraction(
            job_dir=job_dir,
            pdf_path=pdf_path,
            processed_images=processed_images,
            pipeline=pipeline,
            primary_name=type(primary).__name__.replace("Client", ""),
            secondary_name=type(secondary).__name__.replace("Client", ""),
            status_func=status_func,
            use_cache=True,
            checkpoint=checkpoint,
        )
        res["processing_time"] = round(time.time() - t0, 2)
        res["input_type"] = "pdf"

        _set_status(job_dir, "saving_results", "Saving results...")
        _save_results(job_dir, res, job_dir.name)
        _print_field_report(job_dir, res)
        _set_status(job_dir, "done", "Extraction complete. Results ready for download.")
        _save_to_db(job_dir)
    except Exception as e:
        logger.exception("Pipeline failed")
        _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
    finally:
        _cleanup_intermediate(job_dir)


def run_batch_pdfs_pipeline(job_dir: Path, pdfs_info: list[dict]) -> None:
    t0 = time.time()
    try:
        config = Config()
        primary = get_model_client("primary")
        secondary = get_model_client("secondary")
        pipeline = ExtractionPipeline(config, primary_client=primary, secondary_client=secondary)
        primary_name = type(primary).__name__.replace("Client", "")
        secondary_name = type(secondary).__name__.replace("Client", "")

        _set_status(job_dir, "preprocessing", f"Batch: processing {len(pdfs_info)} PDFs...")

        all_results: list[dict] = []
        for idx, pdf_info in enumerate(pdfs_info):
            pdf_name = Path(pdf_info["path"]).name
            _set_batch_pdf_status(job_dir, pdf_name, "processing", 0, f"Starting ({idx+1}/{len(pdfs_info)})")

            try:
                valid, err = _validate_pdf(pdf_info["path"])
                if not valid:
                    _set_batch_pdf_status(job_dir, pdf_name, "error", 100, err)
                    all_results.append({"name": pdf_name, "error": err})
                    continue

                pipeline.preprocess(pdf_info["path"], str(job_dir))
                _set_batch_pdf_status(job_dir, pdf_name, "preprocessing", 20, f"Preprocessed ({idx+1}/{len(pdfs_info)})")

                processed_images = _ensure_page_images(job_dir / "pages")

                def batch_status_func(stage, msg):
                    pct = 40 if stage == "primary_extraction" else (70 if stage == "secondary_verification" else 85)
                    _set_batch_pdf_status(job_dir, pdf_name, stage, pct, f"{msg} ({idx+1}/{len(pdfs_info)})")

                res = _run_core_extraction(
                    job_dir=job_dir,
                    pdf_path=pdf_info["path"],
                    processed_images=processed_images,
                    pipeline=pipeline,
                    primary_name=primary_name,
                    secondary_name=secondary_name,
                    status_func=batch_status_func,
                    use_cache=False,
                )
                res["pdf_name"] = pdf_name
                res["input_type"] = "batch_pdf"
                res["processing_time"] = round(time.time() - t0, 2)
                
                all_results.append(res)
                _set_batch_pdf_status(job_dir, pdf_name, "done", 100, f"Done ({idx+1}/{len(pdfs_info)})")
            except Exception as e:
                logger.exception("Batch item failed: %s", pdf_name)
                _set_batch_pdf_status(job_dir, pdf_name, "error", 100, str(e))
                all_results.append({"name": pdf_name, "error": str(e)})

        _set_status(job_dir, "saving_results", "Saving batch results...")
        combined = {
            "batch": True,
            "num_pdfs": len(pdfs_info),
            "pdfs": all_results,
            "processing_time": round(time.time() - t0, 2),
        }
        results_dir = job_dir / "results"
        results_dir.mkdir(exist_ok=True)
        with open(results_dir / "result.json", "w") as f:
            json.dump(combined, f, indent=2)

        with _progress_lock:
            _progress_store.pop(job_dir.name, None)
        success = sum(1 for r in all_results if 'error' not in r)
        failed = len(pdfs_info) - success
        print(f"\n{'='*80}")
        print(f"  BATCH REPORT: {len(pdfs_info)} files processed")
        print(f"{'='*80}")
        for r in all_results:
            name = r.get("pdf_name", r.get("name", "?"))
            if "error" in r:
                print(f"  ✗ {name}  —  FAILED: {r['error']}")
            else:
                fields = r.get("fields", [])
                pages = len({f["page"] for f in fields})
                conf = r.get("overall_confidence", "?")
                print(f"  ✓ {name}  —  {len(fields)} fields, {pages} pages, {conf}%")
        print(f"{'─'*80}")
        print(f"  SUCCESS: {success}/{len(pdfs_info)}  |  FAILED: {failed}  |  Time: {combined.get('processing_time', '?')}s")
        print(f"{'='*80}\n")
        _set_status(job_dir, "done", f"Batch complete: {success}/{len(pdfs_info)} succeeded.")
    except Exception as e:
        logger.exception("Batch pipeline failed")
        _set_status(job_dir, "error", f"Batch pipeline failed: {e}")
    finally:
        _cleanup_intermediate(job_dir)


def run_image_pipeline(job_dir: Path, image_paths: dict[int, str]) -> None:
    try:
        t0 = time.time()
        config = Config()
        primary = get_model_client("primary")
        secondary = get_model_client("secondary")
        pipeline = ExtractionPipeline(config, primary_client=primary, secondary_client=secondary)

        _set_status(job_dir, "preprocessing", "Preprocessing page images...")
        pages = pipeline.preprocess_images(image_paths, str(job_dir))
        _set_status(job_dir, "preprocessing", f"Preprocessing done. {len(pages)} pages ready.", pages=len(pages))

        processed_images = _ensure_page_images(job_dir / "pages")

        def status_func(stage, msg):
            _set_status(job_dir, stage, msg)

        res = _run_core_extraction(
            job_dir=job_dir,
            pdf_path="",
            processed_images=processed_images,
            pipeline=pipeline,
            primary_name=type(primary).__name__.replace("Client", ""),
            secondary_name=type(secondary).__name__.replace("Client", ""),
            status_func=status_func,
            use_cache=False,
        )
        res["processing_time"] = round(time.time() - t0, 2)
        res["input_type"] = "image_set"

        _set_status(job_dir, "saving_results", "Saving results...")
        _save_results(job_dir, res, job_dir.name)
        _print_field_report(job_dir, res)
        _set_status(job_dir, "done", "Extraction complete.")
    except Exception as e:
        logger.exception("Image pipeline failed")
        _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
    finally:
        _cleanup_intermediate(job_dir)


def run_image_pipeline_from_zip(job_dir: Path, image_paths: list[str]) -> None:
    if not _wait_for_memory(job_dir):
        return
    try:
        valid, err = _validate_images(image_paths)
        if not valid:
            _set_status(job_dir, "error", err)
            return

        _set_status(job_dir, "preprocessing", f"Classifying {len(image_paths)} pages...")
        classifier = PageClassifier()
        classifications = classifier.classify_all(image_paths)
        page_map, validation = classifier.resolve_order(classifications)

        with open(job_dir / "page_validation.json", "w") as f:
            json.dump(validation, f, indent=2)

        is_valid = (
            not validation.get("has_missing", False)
            and not validation.get("has_duplicates", False)
            and not validation.get("has_blank_pages", False)
            and not validation.get("has_unreadable_pages", False)
            and len(page_map) == 6
        )
        if not is_valid:
            msg = (
                f"Page validation failed. {validation.get('total_images_received', 0)} images, "
                f"missing: {validation.get('missing_pages', [])}, "
                f"duplicates: {validation.get('duplicate_pages', [])}."
            )
            _set_status(job_dir, "incomplete", msg)
            print(f"\n{'='*80}")
            print(f"  FILE: {job_dir.name}")
            print(f"  STATUS: INCOMPLETE — {msg}")
            print(f"{'='*80}\n")
            return

        reordered: dict[int, str] = {}
        for page_num, img_idx in page_map.items():
            reordered[page_num] = image_paths[img_idx]

        _set_status(job_dir, "preprocessing", f"Pages classified. Running pipeline...", pages=len(reordered))
        run_image_pipeline(job_dir, reordered)
    except Exception as e:
        logger.exception("Image pipeline from zip failed")
        _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
    finally:
        _cleanup_intermediate(job_dir)


KNOWN_SECTIONS: list[dict] = [
    {"number": 1, "name": "Student Profile", "page": 1},
    {"number": 2, "name": "Family Background", "page": 1},
    {"number": 3, "name": "Housing Condition", "page": 2},
    {"number": 4, "name": "Financial Background", "page": 3},
    {"number": 5, "name": "Health Information", "page": 5},
    {"number": 6, "name": "Student Commitment", "page": 5},
    {"number": 7, "name": "Scholarship Information", "page": 6},
    {"number": 8, "name": "Volunteer Observation", "page": 6},
]


def _derive_sections(fields: list[StructuredField], raw_text: str) -> list[dict]:
    name_map: dict[int, str] = {}
    page_map: dict[int, int] = {}
    for ks in KNOWN_SECTIONS:
        name_map.setdefault(ks["number"], ks["name"])
        page_map.setdefault(ks["number"], ks["page"])
    for match in re.finditer(
        r"(?:##\s*)?Section\s+(\d+)\s*[—–\-:.]\s*(.+?)(?:\n|$)", raw_text,
    ):
        num = int(match.group(1))
        name = match.group(2).strip()
        name_map[num] = name
    for f in fields:
        if f.section_number is not None and f.section_number not in page_map:
            page_map[f.section_number] = f.page
    all_nums = sorted(set(name_map.keys()) | set(page_map.keys()))
    return [
        {"number": num, "name": name_map.get(num, f"Section {num}"), "page": page_map.get(num, 1)}
        for num in all_nums
    ]


def _insert_page_markers(raw_text: str, fields: list[dict]) -> str:
    if not raw_text:
        return raw_text
    sorted_fields = sorted(fields, key=lambda f: f.get("page", 1))
    current_page = sorted_fields[0].get("page", 1) if sorted_fields else 1
    result = raw_text
    insertions = 0
    offset = 0
    for f in sorted_fields:
        page = f.get("page", 1)
        if page != current_page:
            label = f.get("label", "")
            if label:
                idx = result.find(label, offset)
                if idx >= 0:
                    marker = f"\n\n--- Page {page} ---\n\n"
                    result = result[:idx] + marker + result[idx:]
                    offset = idx + len(marker)
                    current_page = page
                    insertions += 1
    if insertions == 0 and len(sorted_fields) > 1:
        first_page = sorted_fields[0].get("page", 1)
        if first_page > 1:
            result = f"--- Page {first_page} ---\n\n{raw_text}"
    return result


def _print_field_report(job_dir: Path, res: dict, pdf_name: str | None = None) -> None:
    name_path = job_dir / "original_name.txt"
    display_name = pdf_name or (name_path.read_text().strip() if name_path.exists() else job_dir.name)
    fields = res.get("fields", [])
    status_str = "DONE" if "error" not in res else "FAILED"
    conf = res.get("overall_confidence", "?")
    elapsed = res.get("processing_time", "?")
    sections = res.get("sections", [])

    sec_by_page: dict[int, list[str]] = {}
    for s in sections:
        sec_by_page.setdefault(s["page"], []).append(s["name"])

    pages: dict[int, list[dict]] = {}
    for f in fields:
        pages.setdefault(f["page"], []).append(f)

    print(f"\n{'='*80}")
    print(f"  FILE: {display_name}")
    print(f"  STATUS: {status_str}  |  Confidence: {conf}%  |  Time: {elapsed}s")
    print(f"{'='*80}")

    for page_num in sorted(pages):
        page_fields = pages[page_num]
        sec_names = sec_by_page.get(page_num, [])
        sec_label = f" ({', '.join(sec_names)})" if sec_names else ""
        needs_review = sum(1 for f in page_fields if f.get("needs_clarification"))
        review_suffix = f"  ⚠ {needs_review} need review" if needs_review else ""
        print(f"\n  Page {page_num}{sec_label} — {len(page_fields)} fields{review_suffix}")
        print(f"  {'─'*76}")
        for f in page_fields:
            label = f.get("label", "?")
            value = (f.get("value") or "—")[:42]
            pct = f.get("confidence", 0)
            badges = []
            if f.get("needs_clarification"):
                badges.append("⚠")
            if f.get("is_verified"):
                badges.append("✓")
            badge_str = f"  {' '.join(badges)}" if badges else ""
            print(f"    {label:<48} {value:<22} {pct}%{badge_str}")

    total_review = sum(1 for f in fields if f.get("needs_clarification"))
    print(f"\n{'─'*80}")
    print(f"  TOTAL: {len(fields)} fields across {len(pages)} pages  |  {total_review} need review  |  {elapsed}s")
    print(f"{'='*80}\n")



