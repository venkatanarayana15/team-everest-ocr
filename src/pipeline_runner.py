import asyncio
import hashlib
import json
import logging
import re
import time
from pathlib import Path

import cv2
import numpy as np

from src.backends import WordBox
from src.config import Config
from src.extraction_pipeline import ExtractionPipeline, KNOWN_TEMPLATE_FIELDS, StructuredField
from src.chandra_client import call_chandra_ocr
from src.model_client import get_model_client
from src.page_classifier import PageClassifier
from src.renderers import _render_markdown, _format_job_datetime
from src.status import (
    _set_status, _save_checkpoint, _load_checkpoint, _cleanup_intermediate,
    _get_status, _progress_store,
)

logger = logging.getLogger(__name__)

_BBOX_CACHE_KEY: str | None = None


def _get_bbox_cache_key() -> str:
    global _BBOX_CACHE_KEY
    if _BBOX_CACHE_KEY is not None:
        return _BBOX_CACHE_KEY
    data_path = Path("bin/eng.traineddata")
    if data_path.exists():
        _BBOX_CACHE_KEY = hashlib.md5(data_path.read_bytes()).hexdigest()
    else:
        _BBOX_CACHE_KEY = ""
    return _BBOX_CACHE_KEY


def _load_bbox_cache(cache_path: Path, key: str) -> list[WordBox] | None:
    try:
        with open(cache_path) as f:
            cache = json.load(f)
        if cache.get("key") == key:
            return [WordBox(**wb) for wb in cache["data"]]
    except Exception:
        pass
    return None


def _save_bbox_cache(cache_path: Path, key: str, data: list[WordBox]) -> None:
    try:
        with open(cache_path, "w") as f:
            json.dump({"key": key, "data": [wb.__dict__ for wb in data]}, f)
    except Exception as e:
        logger.warning("Failed to save bbox cache: %s", e)


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


async def _set_batch_pdf_status(job_dir: Path, pdf_name: str, status: str, pct: int, message: str = "") -> None:
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


async def _wait_for_memory(job_dir: Path, min_free_mem_mb: int = 512, timeout: int = 3600) -> bool:
    import psutil
    start = time.time()
    wait = 1.0
    while time.time() - start < timeout:
        free = psutil.virtual_memory().available / (1024 * 1024)
        if free >= min_free_mem_mb:
            return True
        logger.warning("Low memory: %.0f MB free (need %d MB). Delaying job...", free, min_free_mem_mb)
        await asyncio.sleep(wait)
        wait = min(wait * 2, 60.0)
    await _set_status(job_dir, "error",
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


async def _run_core_extraction(
    job_dir: Path,
    pdf_path: str,
    processed_images: dict[int, str],
    pipeline: ExtractionPipeline,
    primary_name: str,
    status_func,
    use_cache: bool = False,
    checkpoint=None,
) -> dict:
    _t = {k: 0.0 for k in ("preprocess", "tesseract", "chandra", "llm", "merge", "save")}
    _t["wall_start"] = time.time()

    if checkpoint:
        step, fields, overall_confidence, raw_text, sections_data = checkpoint
        word_boxes = []
        primary_token_usage = {}
    else:
        await status_func("primary_extraction", f"Running OCR + LLM extraction ({primary_name})...")
        _t["preprocess"] = time.time() - _t["wall_start"]

        loop = asyncio.get_running_loop()

        async def _run_tesseract():
            bbox_cache = job_dir / "bbox_cache.json"
            cache_key = _get_bbox_cache_key()
            if use_cache and bbox_cache.exists() and cache_key:
                cached = _load_bbox_cache(bbox_cache, cache_key)
                if cached is not None:
                    return cached
            t0 = time.time()
            wb = await loop.run_in_executor(None, pipeline.run_bbox_images, processed_images)
            _t["tesseract"] = time.time() - t0
            if use_cache and cache_key:
                _save_bbox_cache(bbox_cache, cache_key, wb)
            return wb

        tesseract_task = asyncio.create_task(_run_tesseract())
        chandra_task = asyncio.create_task(
            call_chandra_ocr(page_images=processed_images)
        ) if processed_images else None

        word_boxes = await tesseract_task
        if not word_boxes:
            logger.warning("Tesseract returned no word boxes — LLM extraction may produce degraded results")

        chandra_markdown = None
        if chandra_task:
            try:
                t0 = time.time()
                chandra_markdown = await asyncio.wait_for(chandra_task, timeout=120.0)
                _t["chandra"] = time.time() - t0
                logger.info("Chandra-2 markdown received: %d chars (%.1fs)", len(chandra_markdown), _t["chandra"])
            except Exception as e:
                _t["chandra"] = time.time() - t0
                logger.warning("Chandra-2 failed (%s, %.1fs) — falling back to vision LLM", e, _t["chandra"])

        t0 = time.time()
        if chandra_markdown:
            from src.markdown_parser import parse_markdown
            model_data = parse_markdown(chandra_markdown)
            primary_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "calls": 0}
            logger.info("Markdown parser extracted %d fields", len(model_data.get("fields", [])))
        else:
            llm_task = asyncio.create_task(
                pipeline.run_primary_extraction(pdf_path, processed_images)
            )
            model_data, primary_token_usage = await llm_task
        _t["llm"] = time.time() - t0

        _save_tesseract_data(job_dir, word_boxes)

        if model_data:
            overall_confidence = model_data.get("overall_confidence", 0)
            raw_text = model_data.get("raw_text", "")
            raw_text = _insert_page_markers(raw_text, model_data.get("fields", []))
            t_m = time.time()
            fields = pipeline.merge_fields(model_data, word_boxes, prefix=primary_name)
            _t["merge"] = time.time() - t_m
            await status_func("field_mapping", f"Merged {len(fields)} fields.")
        else:
            await status_func("field_mapping", "Primary extraction failed — using Tesseract words.")
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
        _t["save"] = time.time() - t_m

    _t["total"] = time.time() - _t["wall_start"]
    logger.info(
        "STAGE TIMING | preprocess=%.1fs tesseract=%.1fs chandra=%.1fs llm=%.1fs merge=%.1fs save=%.1fs total=%.1fs",
        _t["preprocess"], _t["tesseract"], _t["chandra"], _t["llm"], _t["merge"], _t["save"], _t["total"],
    )

    token_usage = {
        "primary": primary_token_usage,
        "total": {
            "prompt_tokens": primary_token_usage.get("prompt_tokens", 0) or 0,
            "completion_tokens": primary_token_usage.get("completion_tokens", 0) or 0,
            "total_tokens": primary_token_usage.get("total_tokens", 0) or 0,
        },
    }

    await status_func("template_fill", "Filling missing template fields...")
    fields = ExtractionPipeline.fill_missing_template_fields(fields)
    sections_data = _derive_sections(fields, raw_text or "")

    return {
        "overall_confidence": overall_confidence,
        "num_pages": len(processed_images),
        "raw_text": raw_text or "",
        "primary_model": primary_name,
        "token_usage": token_usage,
        "llm_calls": primary_token_usage.get("calls", 0),
        "sections": sections_data or [],
        "fields": _fields_to_dict(fields),
    }


async def _save_to_db(job_dir: Path) -> bool:
    results_path = job_dir / "results" / "result.json"
    if not results_path.exists():
        return True
    try:
        from src.database import upsert_ocr_document
    except ImportError:
        logger.info("DB module not available, skipping auto-save")
        return True

    try:
        with open(results_path) as f:
            result_data = json.load(f)
        name_path = job_dir / "original_name.txt"
        orig_name = name_path.read_text().strip() if name_path.exists() else job_dir.name
        fields_data = result_data.get("fields", [])
        low_conf = sum(1 for f in fields_data if f.get("confidence", 0) < 70)
        needs_review = sum(1 for f in fields_data if f.get("needs_clarification", False))
        logger.info(
            "Uploading extracted data to Supabase... (file=%r, fields=%d, confidence=%s, "
            "low_conf=%d, needs_review=%d, time=%.2fs)",
            orig_name,
            len(fields_data),
            result_data.get("overall_confidence", "N/A"),
            low_conf, needs_review,
            result_data.get("processing_time", 0),
        )
        await upsert_ocr_document(
            job_id=job_dir.name,
            file_name=orig_name,
            status="done",
            processing_time=result_data.get("processing_time"),
            confidence_score=result_data.get("overall_confidence"),
            num_pdfs=result_data.get("num_pdfs"),
            result_json=result_data,
        )
        logger.info("Auto-save to DB succeeded for job %s", job_dir.name)
        return True
    except Exception as e:
        logger.warning("Auto-save to DB failed for job %s: %s", job_dir.name, e)
        return False


async def run_pipeline(job_dir: Path, pdf_path: str) -> None:
    if not await _wait_for_memory(job_dir):
        return
    try:
        t0 = time.time()
        name_path = job_dir / "original_name.txt"
        pdf_name = name_path.read_text().strip() if name_path.exists() else Path(pdf_path).name

        valid, err_msg = _validate_pdf(pdf_path)
        if not valid:
            await _set_status(job_dir, "error", err_msg)
            return

        config = Config()
        primary = get_model_client("primary")
        pipeline = ExtractionPipeline(config, primary_client=primary)

        checkpoint = _load_checkpoint(job_dir)
        if not checkpoint:
            await _set_status(job_dir, "preprocessing", f"Preprocessing PDF ({pdf_name})...")
            pipeline.preprocess(pdf_path, str(job_dir))
            await _set_status(job_dir, "preprocessing", "Preprocessing done.", pages=6)

        processed_images = _ensure_page_images(job_dir / "pages")

        async def status_func(stage, msg):
            await _set_status(job_dir, stage, msg)

        res = await _run_core_extraction(
            job_dir=job_dir,
            pdf_path=pdf_path,
            processed_images=processed_images,
            pipeline=pipeline,
            primary_name=type(primary).__name__.replace("Client", ""),
            status_func=status_func,
            use_cache=True,
            checkpoint=checkpoint,
        )
        res["processing_time"] = round(time.time() - t0, 2)
        res["input_type"] = "pdf"
        res["pdf_names"] = [pdf_name]

        await _set_status(job_dir, "saving_results", "Saving results...")
        _save_results(job_dir, res, job_dir.name)
        _print_field_report(job_dir, res)
        await _set_status(job_dir, "done", "Extraction complete. Results ready for download.")
        _db_ok = await _save_to_db(job_dir)
        if not _db_ok:
            await _set_status(job_dir, "done", "Extraction complete but DB save failed")
            logger.error("Pipeline extraction OK but DB save failed | job=%s", job_dir.name)
        print(f"{'='*80}")
        _ok_label = "1 succeeded" if _db_ok else "1 extracted (DB save failed)"
        print(f"  SUMMARY: 1 file processed — {_ok_label}, 0 failed")
        print(f"{'='*80}\n")
    except Exception as e:
        logger.exception("Pipeline failed")
        await _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
        print(f"{'='*80}")
        print(f"  SUMMARY: 1 file processed — 0 succeeded, 1 failed")
        print(f"{'='*80}\n")
    finally:
        _cleanup_intermediate(job_dir)


async def run_batch_pdfs_pipeline(job_dir: Path, pdfs_info: list[dict]) -> None:
    t0 = time.time()
    try:
        config = Config()
        primary = get_model_client("primary")
        pipeline = ExtractionPipeline(config, primary_client=primary)
        primary_name = type(primary).__name__.replace("Client", "")

        await _set_status(job_dir, "preprocessing", f"Batch: processing {len(pdfs_info)} PDFs...")

        all_results: list[dict] = []
        for idx, pdf_info in enumerate(pdfs_info):
            pdf_name = Path(pdf_info["path"]).name
            await _set_batch_pdf_status(job_dir, pdf_name, "processing", 0, f"Starting ({idx+1}/{len(pdfs_info)})")

            try:
                valid, err = _validate_pdf(pdf_info["path"])
                if not valid:
                    await _set_batch_pdf_status(job_dir, pdf_name, "error", 100, err)
                    all_results.append({"name": pdf_name, "error": err})
                    continue

                pipeline.preprocess(pdf_info["path"], str(job_dir))
                await _set_batch_pdf_status(job_dir, pdf_name, "preprocessing", 20, f"Preprocessed ({idx+1}/{len(pdfs_info)})")

                processed_images = _ensure_page_images(job_dir / "pages")

                async def batch_status_func(stage, msg):
                    pct = 40 if stage == "primary_extraction" else (70 if stage == "secondary_verification" else 85)
                    await _set_batch_pdf_status(job_dir, pdf_name, stage, pct, f"{msg} ({idx+1}/{len(pdfs_info)})")

                res = await _run_core_extraction(
                    job_dir=job_dir,
                    pdf_path=pdf_info["path"],
                    processed_images=processed_images,
                    pipeline=pipeline,
                    primary_name=primary_name,
                    status_func=batch_status_func,
                    use_cache=False,
                )
                res["pdf_name"] = pdf_name
                res["input_type"] = "batch_pdf"
                res["processing_time"] = round(time.time() - t0, 2)

                _print_field_report(job_dir, res, pdf_name)

                all_results.append(res)
                await _set_batch_pdf_status(job_dir, pdf_name, "done", 100, f"Done ({idx+1}/{len(pdfs_info)})")
            except Exception as e:
                logger.exception("Batch item failed: %s", pdf_name)
                await _set_batch_pdf_status(job_dir, pdf_name, "error", 100, str(e))
                all_results.append({"name": pdf_name, "error": str(e)})

        await _set_status(job_dir, "saving_results", "Saving batch results...")
        combined = {
            "batch": True,
            "num_pdfs": len(pdfs_info),
            "pdfs": all_results,
            "pdf_names": [r.get("pdf_name") or r.get("name", f"file_{i}") for i, r in enumerate(all_results)],
            "processing_time": round(time.time() - t0, 2),
        }
        results_dir = job_dir / "results"
        results_dir.mkdir(exist_ok=True)
        with open(results_dir / "result.json", "w") as f:
            json.dump(combined, f, indent=2)

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
        print(f"  FILES: {len(pdfs_info)} total  |  SUCCESS: {success}  |  FAILED: {failed}  |  Time: {combined.get('processing_time', '?')}s")
        print(f"{'='*80}\n")
        await _set_status(job_dir, "done", f"Batch complete: {success}/{len(pdfs_info)} succeeded.")
    except Exception as e:
        logger.exception("Batch pipeline failed")
        await _set_status(job_dir, "error", f"Batch pipeline failed: {e}")
    finally:
        _cleanup_intermediate(job_dir)


async def run_image_pipeline(job_dir: Path, image_paths: dict[int, str]) -> None:
    try:
        t0 = time.time()
        config = Config()
        primary = get_model_client("primary")
        pipeline = ExtractionPipeline(config, primary_client=primary)

        await _set_status(job_dir, "preprocessing", "Preprocessing page images...")
        pages = pipeline.preprocess_images(image_paths, str(job_dir))
        await _set_status(job_dir, "preprocessing", f"Preprocessing done. {len(pages)} pages ready.", pages=len(pages))

        processed_images = _ensure_page_images(job_dir / "pages")

        async def status_func(stage, msg):
            await _set_status(job_dir, stage, msg)

        res = await _run_core_extraction(
            job_dir=job_dir,
            pdf_path="",
            processed_images=processed_images,
            pipeline=pipeline,
            primary_name=type(primary).__name__.replace("Client", ""),
            status_func=status_func,
            use_cache=False,
        )
        res["processing_time"] = round(time.time() - t0, 2)
        res["input_type"] = "image_set"
        name_path = job_dir / "original_name.txt"
        image_name = name_path.read_text().strip() if name_path.exists() else job_dir.name
        res["pdf_names"] = [image_name]

        await _set_status(job_dir, "saving_results", "Saving results...")
        _save_results(job_dir, res, job_dir.name)
        _print_field_report(job_dir, res)
        await _set_status(job_dir, "done", "Extraction complete.")
    except Exception as e:
        logger.exception("Image pipeline failed")
        await _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
    finally:
        _cleanup_intermediate(job_dir)


async def run_image_pipeline_from_zip(job_dir: Path, image_paths: list[str]) -> None:
    if not await _wait_for_memory(job_dir):
        return
    try:
        valid, err = _validate_images(image_paths)
        if not valid:
            await _set_status(job_dir, "error", err)
            return

        await _set_status(job_dir, "preprocessing", f"Classifying {len(image_paths)} pages...")
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
            await _set_status(job_dir, "incomplete", msg)
            print(f"\n{'='*80}")
            print(f"  FILE: {job_dir.name}")
            print(f"  STATUS: INCOMPLETE — {msg}")
            print(f"{'='*80}\n")
            return

        reordered: dict[int, str] = {}
        for page_num, img_idx in page_map.items():
            reordered[page_num] = image_paths[img_idx]

        await _set_status(job_dir, "preprocessing", f"Pages classified. Running pipeline...", pages=len(reordered))
        await run_image_pipeline(job_dir, reordered)
    except Exception as e:
        logger.exception("Image pipeline from zip failed")
        await _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
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


def _checkbox_bracket(value: str) -> str:
    if "\u2713" in value:
        return "[✓]"
    if value in ("\u2717", "No", "✗"):
        return "[✗]"
    if value in ("—", "", "\u2014"):
        return "[ ]"
    if len(value) <= 3:
        return f"[{value}]"
    return f"[{value[:3]}…]"


def _print_field_report(job_dir: Path, res: dict, pdf_name: str | None = None) -> None:
    name_path = job_dir / "original_name.txt"
    display_name = pdf_name or (name_path.read_text().strip() if name_path.exists() else job_dir.name)
    fields = res.get("fields", [])
    status_str = "\033[92m\033[1mDONE\033[0m" if "error" not in res else "\033[91m\033[1mFAILED\033[0m"
    
    # Format confidence score color
    raw_conf = res.get("overall_confidence", "?")
    try:
        conf_val = float(raw_conf)
        if conf_val >= 85:
            conf_str = f"\033[92m{raw_conf}%\033[0m"
        elif conf_val >= 70:
            conf_str = f"\033[93m{raw_conf}%\033[0m"
        else:
            conf_str = f"\033[91m{raw_conf}%\033[0m"
    except (ValueError, TypeError):
        conf_str = f"\033[93m{raw_conf}%\033[0m"

    elapsed = res.get("processing_time", "?")
    sections = res.get("sections", [])

    sec_names: dict[int, str] = {}
    for s in sections:
        sec_names[s["number"]] = s["name"]

    known_labels: set[str] = {t["label"] for t in KNOWN_TEMPLATE_FIELDS}

    pages: dict[int, list[dict]] = {}
    for f in fields:
        pages.setdefault(f["page"], []).append(f)

    total_review = sum(1 for f in fields if f.get("needs_clarification"))
    review_summary = f"\033[91m\033[1m{total_review} need review\033[0m" if total_review > 0 else "\033[92m0 need review\033[0m"

    print(f"\n\033[1m{'='*80}\033[0m")
    print(f"  \033[1mFILE:\033[0m {display_name}")
    print(f"  \033[1mSTATUS:\033[0m {status_str}  |  \033[1mConfidence:\033[0m {conf_str}  |  \033[1mTime:\033[0m {elapsed}s")
    print(f"  \033[1mFIELDS:\033[0m {len(fields)} total  |  {review_summary}  |  \033[1mPages:\033[0m {len(pages)}")
    print(f"\033[90m{'─'*80}\033[0m")

    re_row = __import__('re').compile(r'^(.+?) — Row (\d+) — (.+)$')
    re_check = __import__('re').compile(r'^(.+?) — (.+)$')

    for page_num in sorted(pages):
        page_fields = pages[page_num]
        needs_review = sum(1 for f in page_fields if f.get("needs_clarification"))

        # Group fields by section
        by_sec: dict[int | None | str, list[dict]] = {}
        for f in page_fields:
            sec = f.get("section_number")
            by_sec.setdefault("header" if sec is None else sec, []).append(f)

        sec_keys = sorted(
            (k for k in by_sec if k != "header"),
            key=lambda k: int(k) if isinstance(k, int) else 0,
        )
        ordered = (["header"] if "header" in by_sec else []) + sec_keys

        review_suffix = f"  \033[91m\033[1m⚠ {needs_review} flag(s)\033[0m" if needs_review else "  \033[92m✓ Clear\033[0m"
        print(f"\n  ── \033[1mPage {page_num}\033[0m {review_suffix} ──────────────────────────────────────────────────────────")

        for sec_key in ordered:
            sec_fields = by_sec[sec_key]

            if sec_key == "header":
                sec_title = "Header"
            else:
                sec_name = sec_names.get(sec_key, "")
                sec_title = f"Section {sec_key}" + (f" — {sec_name}" if sec_name else "")
            
            print(f"\n    \033[1m\033[36m{sec_title}\033[0m")
            print(f"    \033[90m{'─' * 50}\033[0m")

            tables: dict[str, dict[int, dict[str, str]]] = {}
            checklists: dict[str, list[tuple[str, str]]] = {}
            simple: list[dict] = []

            for f in sec_fields:
                label = f.get("label", "?")
                value = f.get("value") or "—"

                m = re_row.match(label)
                if m:
                    table_name = m.group(1)
                    row_num = int(m.group(2))
                    col_name = m.group(3)
                    tables.setdefault(table_name, {}).setdefault(row_num, {})[col_name] = value
                    continue

                m = re_check.match(label)
                if m and label not in known_labels:
                    group_name = m.group(1)
                    option = m.group(2)
                    checklists.setdefault(group_name, []).append((option, value))
                    continue

                simple.append(f)

            for f in simple:
                label = f.get("label", "?")
                raw_val = f.get("value")
                if raw_val is None or raw_val == "":
                    val_display = r"<empty>"
                else:
                    val_display = str(raw_val)
                
                # Highlight fields needing review
                if f.get("needs_clarification"):
                    val_display = f"\033[93m{val_display} (needs review)\033[0m"
                
                print(f"      {label:<54} {val_display}")

            for group_name, options in checklists.items():
                if options:
                    max_opt = max(len(opt) for opt, _ in options)
                    print(f"      {group_name}")
                    for option, value in options:
                        bracket = _checkbox_bracket(value)
                        # Highlight active checkbox options
                        if "[✓]" in bracket:
                            bracket_display = f"\033[92m{bracket}\033[0m"
                        else:
                            bracket_display = bracket
                        print(f"        {option:{max_opt}}  {bracket_display}")

            for table_name, rows in tables.items():
                col_order: list[str] = []
                for rn in sorted(rows):
                    for c in rows[rn]:
                        if c not in col_order:
                            col_order.append(c)
                col_widths = []
                for c in col_order:
                    max_val = max(len(rows[rn].get(c, "")) for rn in rows)
                    col_widths.append(max(len(c), max_val, 8))
                
                header = "  |  ".join(f"\033[1m{c.ljust(col_widths[i])}\033[0m" for i, c in enumerate(col_order))
                sep = "—+—".join("—" * w for w in col_widths)
                print(f"\n      \033[4m{table_name}\033[0m")
                print(f"        {header}")
                print(f"        \033[90m{sep}\033[0m")
                for rn in sorted(rows):
                    vals = [rows[rn].get(c, "—").ljust(col_widths[i]) for i, c in enumerate(col_order)]
                    print(f"        {'  |  '.join(vals)}")

        print()
        high_conf = sum(1 for f in page_fields if f.get("confidence", 0) >= 90)
        low_conf = sum(1 for f in page_fields if f.get("confidence", 0) < 70)
        
        # Color coding stats footer
        high_str = f"\033[92m{high_conf}\033[0m"
        low_str = f"\033[91m{low_conf}\033[0m" if low_conf > 0 else "0"
        
        print(f"  Page {page_num}: {len(page_fields)} fields  |  High Confidence: {high_str}  |  Low Confidence: {low_str}")
        print(f"  \033[90m{'─' * 76}\033[0m")

    print(f"\033[1m{'='*80}\033[0m\n")
