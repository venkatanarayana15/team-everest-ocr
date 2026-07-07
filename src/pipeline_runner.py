import asyncio
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path

import cv2
import numpy as np

from src.extraction_pipeline import ExtractionPipeline, KNOWN_TEMPLATE_FIELDS, StructuredField, Config
from src.model_client import get_model_client
from src.page_classifier import PageClassifier
from src.status import (
    _set_status, _save_checkpoint, _load_checkpoint, _cleanup_intermediate,
    _get_status, _progress_store, _render_markdown, _format_job_datetime,
)

from src.tesseract import _save_tesseract_data, run_tesseract_async

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
            raw = path.read_text()
            if raw.strip():
                existing = json.loads(raw)
        except (json.JSONDecodeError, OSError):
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
    tmp = path.with_name(f".{path.name}.tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    tmp.replace(path)

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
    tesseract_enabled: bool = True,
) -> dict:
    if checkpoint:
        step, fields, overall_confidence, raw_text, sections_data = checkpoint
        word_boxes = []
        primary_token_usage = {}
    else:
        await status_func("primary_extraction", f"Running primary extraction ({primary_name})...")

        loop = asyncio.get_running_loop()

        if tesseract_enabled:
            tesseract_task = asyncio.create_task(
                run_tesseract_async(loop, pipeline, processed_images, job_dir, use_cache)
            )

        llm_task = asyncio.create_task(pipeline.run_primary_extraction(pdf_path, processed_images))

        if tesseract_enabled:
            word_boxes = await tesseract_task
            if not word_boxes:
                logger.warning("Tesseract returned no word boxes — LLM extraction may produce degraded results")
        else:
            word_boxes = []

        model_data, primary_token_usage = await llm_task

        if tesseract_enabled:
            _save_tesseract_data(job_dir, word_boxes)

        if model_data:
            overall_confidence = model_data.get("overall_confidence", 0)
            raw_text = model_data.get("raw_text", "")
            raw_text = _insert_page_markers(raw_text, model_data.get("fields", []))
            fields = pipeline.merge_fields(model_data, word_boxes, prefix=primary_name)
            await status_func("field_mapping", f"Merged {len(fields)} fields.")
        else:
            if word_boxes:
                await status_func("field_mapping", "Primary extraction failed — using Tesseract words.")
                fields = [
                    StructuredField(label=wb.text, value=wb.text, confidence=int(wb.confidence),
                                    page=wb.page_num, bbox=wb.bbox, extracted_by=primary_name)
                    for wb in word_boxes
                ]
            else:
                await status_func("field_mapping", "Primary extraction failed — no fallback data available.")
                fields = []
                overall_confidence = 0
                raw_text = ""

        sections_data = (model_data or {}).get("sections") or []
        derived = _derive_sections(fields, raw_text)
        existing_nums = {s["number"] for s in sections_data}
        for ds in derived:
            if ds["number"] not in existing_nums:
                sections_data.append(ds)
        sections_data.sort(key=lambda s: s["number"])

        _save_checkpoint(job_dir, "mapped", fields, overall_confidence, raw_text, sections=sections_data)

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
        doc_id = await upsert_ocr_document(
            job_id=job_dir.name,
            file_name=orig_name,
            status="done",
            processing_time=result_data.get("processing_time"),
            confidence_score=result_data.get("overall_confidence"),
            num_pdfs=result_data.get("num_pdfs"),
            result_json=result_data,
        )
        if not doc_id:
            logger.warning("Auto-save to DB failed (upsert returned empty id) for job %s", job_dir.name)
            return False
        logger.info("Auto-save to DB succeeded for job %s → row id=%s", job_dir.name, doc_id)
        return True
    except Exception as e:
        _hint = "check DATABASE_URL in .env and verify Supabase DB is accessible"
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            _hint = "database connection timeout — check DATABASE_URL / Supabase pooler status"
        elif "42P01" in str(e).split() or "relation" in str(e).lower():
            _hint = "table 'ocr_documents' missing — run schema migration"
        elif "23505" in str(e).split():
            _hint = "duplicate key violation — check upsert logic"
        logger.warning("Auto-save to DB failed for job %s: %s | hint=%s", job_dir.name, e, _hint)
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
            if pipeline.primary_client.needs_images:
                await _set_status(job_dir, "preprocessing", f"Preprocessing PDF ({pdf_name})...")
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, pipeline.preprocess, pdf_path, str(job_dir))
                await _set_status(job_dir, "preprocessing", "Preprocessing done.", pages=6)
                processed_images = _ensure_page_images(job_dir / "pages")
            else:
                await _set_status(job_dir, "preprocessing", "Skipping page rendering (Chandra OCR).")
                processed_images = {}
        else:
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
            tesseract_enabled=config.tesseract_enabled,
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
        print(f"\033[92m\033[1m┌{'─'*78}┐\033[0m")
        _ok_label = "\033[92m1 succeeded\033[0m" if _db_ok else "\033[93m1 extracted (DB save failed)\033[0m"
        print(f"\033[92m\033[1m│\033[0m  \033[1mSUMMARY:\033[0m 1 file processed  •  {_ok_label}  •  \033[92m0 failed\033[0m")
        print(f"\033[92m\033[1m└{'─'*78}┘\033[0m\n")
    except Exception as e:
        # Include last known stage from status store for root-cause clarity
        _stage_info = _progress_store.get(job_dir.name, {}).get("status", "unknown")
        logger.exception("Pipeline failed at stage=%s | job=%s", _stage_info, job_dir.name)
        await _set_status(job_dir, "error", f"{type(e).__name__}: {e}")
        print(f"\033[91m\033[1m┌{'─'*78}┐\033[0m")
        print(f"\033[91m\033[1m│\033[0m  \033[1mSUMMARY:\033[0m 1 file processed  •  \033[91m0 succeeded, 1 failed\033[0m")
        print(f"\033[91m\033[1m│\033[0m  \033[1mFAILED AT:\033[0m stage={_stage_info}  exception={type(e).__name__}: {e}")
        print(f"\033[91m\033[1m└{'─'*78}┘\033[0m\n")
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
        
        queue = asyncio.Queue()
        for idx, pdf_info in enumerate(pdfs_info):
            queue.put_nowait((idx, pdf_info))

        async def batch_worker():
            while True:
                try:
                    idx, pdf_info = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                pdf_name = Path(pdf_info["path"]).name
                # Use a unique sub-directory for each PDF so they don't overwrite each other's images/tesseract data
                pdf_job_dir = job_dir / str(idx)
                pdf_job_dir.mkdir(parents=True, exist_ok=True)

                await _set_batch_pdf_status(job_dir, pdf_name, "processing", 0, f"Starting ({idx+1}/{len(pdfs_info)})")

                try:
                    input_type = pdf_info.get("input_type", "pdf")
                    input_info = pdf_info.get("input_info", {})

                    if input_type == "images":
                        # Image input: copy images to subdir, use preprocess_images
                        image_paths = input_info.get("image_paths", {})
                        if not image_paths:
                            raise RuntimeError("Images input type but no image_paths in input_info")
                        pages_dir = pdf_job_dir / "pages"
                        pages_dir.mkdir(parents=True, exist_ok=True)
                        # Copy images to pages dir with expected naming
                        for p_num, src_path in image_paths.items():
                            dest = pages_dir / f"page_{p_num}.png"
                            shutil.copy2(src_path, str(dest))
                        await _set_batch_pdf_status(job_dir, pdf_name, "preprocessing", 20, f"Images ready ({idx+1}/{len(pdfs_info)})")
                        processed_images = {p_num: str(pages_dir / f"page_{p_num}.png") for p_num in image_paths}
                        # Need to run preprocess_images for deskew/denoise
                        processed = pipeline.preprocess_images(image_paths, str(pdf_job_dir))
                        processed_images = _ensure_page_images(pdf_job_dir / "pages")
                        pdf_path_for_extraction = ""
                    else:
                        valid, err = _validate_pdf(pdf_info["path"])
                        if not valid:
                            await _set_batch_pdf_status(job_dir, pdf_name, "error", 100, err)
                            all_results.append({"name": pdf_name, "error": err})
                            queue.task_done()
                            continue

                        if pipeline.primary_client.needs_images:
                            await asyncio.to_thread(pipeline.preprocess, pdf_info["path"], str(pdf_job_dir))
                            await _set_batch_pdf_status(job_dir, pdf_name, "preprocessing", 20, f"Preprocessed ({idx+1}/{len(pdfs_info)})")
                            processed_images = _ensure_page_images(pdf_job_dir / "pages")
                        else:
                            await _set_batch_pdf_status(job_dir, pdf_name, "preprocessing", 20, f"Ready ({idx+1}/{len(pdfs_info)})")
                            processed_images = {}
                        pdf_path_for_extraction = pdf_info["path"]

                    async def batch_status_func(stage, msg, _pdf_name=pdf_name, _idx=idx):
                        pct = 40 if stage == "primary_extraction" else (70 if stage == "secondary_verification" else 85)
                        await _set_batch_pdf_status(job_dir, _pdf_name, stage, pct, f"{msg} ({_idx+1}/{len(pdfs_info)})")

                    res = await _run_core_extraction(
                        job_dir=pdf_job_dir,
                        pdf_path=pdf_path_for_extraction,
                        processed_images=processed_images,
                        pipeline=pipeline,
                        primary_name=primary_name,
                        status_func=batch_status_func,
                        use_cache=False,
                        tesseract_enabled=config.tesseract_enabled,
                    )
                    res["pdf_name"] = pdf_name
                    res["input_type"] = "batch_" + input_type
                    res["processing_time"] = round(time.time() - t0, 2)

                    if "zoho_req" in pdf_info:
                        from src.zoho_integration import run_zoho_writeback_for_batch_item
                        await run_zoho_writeback_for_batch_item(job_dir, Path(pdf_info["path"]), pdf_info["zoho_req"], res, input_info)

                    _print_field_report(pdf_job_dir, res, pdf_name)

                    all_results.append(res)
                    await _set_batch_pdf_status(job_dir, pdf_name, "done", 100, f"Done ({idx+1}/{len(pdfs_info)})")
                except Exception as e:
                    _stage = _progress_store.get(job_dir.name, {}).get("status", "unknown")
                    logger.exception("Batch item failed at stage=%s | pdf=%s", _stage, pdf_name)
                    await _set_batch_pdf_status(job_dir, pdf_name, "error", 100, str(e))
                    all_results.append({"name": pdf_name, "error": f"[stage={_stage}] {e}"})

                queue.task_done()

        # Run up to N PDFs concurrently (configurable, default 5)
        max_batch_conc = int(os.environ.get("BATCH_MAX_CONCURRENCY", "5"))
        num_workers = min(max_batch_conc, len(pdfs_info))
        workers = [asyncio.create_task(batch_worker()) for _ in range(num_workers)]
        await asyncio.gather(*workers)

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

        _db_ok = await _save_to_db(job_dir)
        if not _db_ok:
            logger.error("Batch DB save failed | job=%s", job_dir.name)

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
            tesseract_enabled=config.tesseract_enabled,
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


import re
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[mK]')

def visible_len(s: str) -> int:
    clean = ANSI_ESCAPE.sub('', s.replace('\033', '\x1b'))
    return len(clean)

def pad_line(content: str, width: int) -> str:
    vis_w = visible_len(content)
    if vis_w >= width:
        res = []
        cur_len = 0
        in_esc = False
        for char in content:
            if char == '\033' or char == '\x1b':
                in_esc = True
                res.append(char)
                continue
            if in_esc:
                res.append(char)
                if char == 'm':
                    in_esc = False
                continue
            if cur_len < width - 1:
                res.append(char)
                cur_len += 1
            elif cur_len == width - 1:
                res.append('…')
                cur_len += 1
        res.append('\033[0m')
        return "".join(res)
    return content + " " * (width - vis_w)


def _print_field_report(job_dir: Path, res: dict, pdf_name: str | None = None) -> None:
    name_path = job_dir / "original_name.txt"
    display_name = pdf_name or (name_path.read_text().strip() if name_path.exists() else job_dir.name)
    fields = res.get("fields", [])
    status_bad = "error" in res
    status_str = "\033[91m\033[1mFAILED\033[0m" if status_bad else "\033[92m\033[1mDONE\033[0m"

    raw_conf = res.get("overall_confidence", "?")
    try:
        conf_val = float(raw_conf)
        conf_str = (
            f"\033[92m{raw_conf}%\033[0m" if conf_val >= 85 else
            f"\033[93m{raw_conf}%\033[0m" if conf_val >= 70 else
            f"\033[91m{raw_conf}%\033[0m"
        )
    except (ValueError, TypeError):
        conf_str = f"\033[93m{raw_conf}%\033[0m"

    elapsed = res.get("processing_time", "?")
    sec_names: dict[int, str] = {}
    for s in res.get("sections", []):
        sec_names[s["number"]] = s["name"]

    known_labels: set[str] = {t["label"] for t in KNOWN_TEMPLATE_FIELDS}

    pages: dict[int, list[dict]] = {}
    for f in fields:
        pages.setdefault(f["page"], []).append(f)

    total_review = sum(1 for f in fields if f.get("needs_clarification"))
    review_str = f"\033[91m\033[1m{total_review} need review\033[0m" if total_review > 0 else "\033[92m0 need review\033[0m"

    W = 86
    C_WIDTH = W - 4

    report_lines = []
    report_lines.append("")
    report_lines.append(f"  \033[1m📄 {display_name}\033[0m")
    report_lines.append(f"  {status_str}  ·  Confidence: {conf_str}  ·  {elapsed}s  ·  {len(fields)} fields  ·  {review_str}")
    report_lines.append(f"\033[90m{'─'*C_WIDTH}\033[0m")

    re_row = __import__('re').compile(r'^(.+?) — Row (\d+) — (.+)$')
    re_check = __import__('re').compile(r'^(.+?) — (.+)$')

    for page_num in sorted(pages):
        page_fields = pages[page_num]
        needs_review = sum(1 for f in page_fields if f.get("needs_clarification"))

        by_sec: dict[int | None | str, list[dict]] = {}
        for f in page_fields:
            sec = f.get("section_number")
            by_sec.setdefault("header" if sec is None else sec, []).append(f)

        sec_keys = sorted(
            (k for k in by_sec if k != "header"),
            key=lambda k: int(k) if isinstance(k, int) else 0,
        )
        ordered = (["header"] if "header" in by_sec else []) + sec_keys

        # Clean, aligned page header
        if needs_review:
            suffix_colored = f" \033[91m\033[1m[⚠ {needs_review}]\033[0m"
            suffix_clean = f" [⚠ {needs_review}]"
        else:
            suffix_colored = " \033[92m[✓]\033[0m"
            suffix_clean = " [✓]"
        prefix = f" \033[1mPage {page_num}\033[0m"
        prefix_clean = f" Page {page_num}"
        pad = C_WIDTH - 6 - len(prefix_clean) - len(suffix_clean)
        report_lines.append(f" \033[90m──\033[0m{prefix}{suffix_colored} \033[90m{'─' * pad}\033[0m")

        for sec_key in ordered:
            sec_fields = by_sec[sec_key]
            sec_title = "Header" if sec_key == "header" else f"Section {sec_key}" + (f" — {sec_names.get(sec_key, '').rstrip('*').strip()}" if sec_names.get(sec_key) else "")
            
            # Clean section header line
            pad_sec = C_WIDTH - 6 - len(sec_title)
            report_lines.append(f"    \033[1m\033[36m{sec_title}\033[0m \033[90m{'─' * max(pad_sec, 4)}\033[0m")

            tables: dict[str, dict[int, dict[str, str]]] = {}
            checklists: dict[str, list[tuple[str, str]]] = {}
            simple: list[dict] = []

            for f in sec_fields:
                label = f.get("label", "?")
                value_raw = f.get("value") or ""
                value = value_raw or "—"

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

            # Suppress all checklist parents from simple list
            agg_labels = set(checklists.keys())

            for f in simple:
                label = f.get("label", "?")
                val = f.get("value") or "—"

                if label in agg_labels:
                    continue

                if val == "—":
                    val_display = f"\033[90m—\033[0m"
                elif f.get("needs_clarification"):
                    val_display = f"\033[93m{val} (needs review)\033[0m"
                else:
                    val_display = val

                # Handle multi-line layouts nicely
                if len(label) > 40 and len(str(val)) > 15:
                    report_lines.append(f"      {label}")
                    lines = str(val_display).split('\n')
                    for line in lines:
                        report_lines.append(f"        {line}")
                else:
                    lines = str(val_display).split('\n')
                    report_lines.append(f"      {label:<40} {lines[0]}")
                    for extra_line in lines[1:]:
                        report_lines.append(f"{' ' * 47}{extra_line}")

            for group_name, options in checklists.items():
                if not options:
                    continue
                max_opt = max(len(opt) for opt, _ in options)
                
                # Check status counting
                checked_count = sum(1 for _, v in options if "[✓]" in _checkbox_bracket(v))

                if sum(len(opt) for opt, _ in options) < 30:
                    parts = []
                    for option, value in options:
                        bracket = _checkbox_bracket(value)
                        if "[✓]" in bracket:
                            sym = f"\033[92m✓\033[0m"
                        elif "[✗]" in bracket:
                            sym = f"\033[91m✗\033[0m"
                        else:
                            sym = f"\033[90m·\033[0m"
                        parts.append(f"{option} {sym}")
                    report_lines.append(f"      {group_name}  \033[90m({checked_count} checked)\033[0m  {'  '.join(parts)}")
                else:
                    report_lines.append(f"      {group_name}  \033[90m({checked_count} checked)\033[0m")
                    for option, value in options:
                        bracket = _checkbox_bracket(value)
                        if "[✓]" in bracket:
                            bracket_display = f"\033[92m[✓]\033[0m"
                        elif "[✗]" in bracket:
                            bracket_display = f"\033[91m[✗]\033[0m"
                        else:
                            bracket_display = f"\033[90m{bracket}\033[0m"
                        report_lines.append(f"        {option:{max_opt}}  {bracket_display}")

            for table_name, rows in tables.items():
                col_order: list[str] = []
                for rn in sorted(rows):
                    for c in rows[rn]:
                        if c not in col_order:
                            col_order.append(c)
                
                sr_col = "Sr. No."
                col_order = [sr_col] + col_order
                col_widths = []
                for c in col_order:
                    if c == sr_col:
                        max_val = max(len(str(rn)) for rn in rows) if rows else 3
                        col_widths.append(max(len(c), max_val))
                    else:
                        max_val = max(len(str(rows[rn].get(c, "")).replace("\r", "").replace("\n", " ")) for rn in rows) if rows else 0
                        col_widths.append(max(len(c), max_val))

                report_lines.append("")
                report_lines.append(f"      \033[4m{table_name}\033[0m  \033[90m({len(rows)} rows)\033[0m")
                
                # Unicode box-drawing aligned table layout
                top_border = "\033[90m┌" + "┬".join("─" * (w + 2) for w in col_widths) + "┐\033[0m"
                header_row = "\033[90m│\033[0m" + "│".join(f" \033[1m{c.ljust(col_widths[i])}\033[0m " for i, c in enumerate(col_order)) + "\033[90m│\033[0m"
                mid_border = "\033[90m├" + "┼".join("─" * (w + 2) for w in col_widths) + "┤\033[0m"
                bottom_border = "\033[90m└" + "┴".join("─" * (w + 2) for w in col_widths) + "┘\033[0m"

                report_lines.append(f"        {top_border}")
                report_lines.append(f"        {header_row}")
                report_lines.append(f"        {mid_border}")
                for rn in sorted(rows):
                    row_cells = []
                    for i, c in enumerate(col_order):
                        val = str(rn) if c == sr_col else str(rows[rn].get(c, "—"))
                        val_clean = val.replace("\r", "").replace("\n", " ")
                        row_cells.append(f" {val_clean.ljust(col_widths[i])} ")
                    row_str = "\033[90m│\033[0m" + "\033[90m│\033[0m".join(row_cells) + "\033[90m│\033[0m"
                    report_lines.append(f"        {row_str}")
                report_lines.append(f"        {bottom_border}")

        report_lines.append("")
        high_conf = sum(1 for f in page_fields if f.get("confidence", 0) >= 90)
        low_conf = sum(1 for f in page_fields if f.get("confidence", 0) < 70)

        page_details = f"Page {page_num} · {len(page_fields)} fields"
        if high_conf:
            page_details += f" · \033[92m{high_conf} high\033[0m"
        if low_conf:
            page_details += f" · \033[91m{low_conf} low\033[0m"
        else:
            page_details += f" · 0 low"

        remaining = max(C_WIDTH - 4 - visible_len(page_details), 4)
        report_lines.append(f"  {page_details} \033[90m{'─' * remaining}\033[0m")

    # Print the border container layout
    top_box = "\033[90m┌" + "─" * (W - 2) + "┐\033[0m"
    bottom_box = "\033[90m└" + "─" * (W - 2) + "┘\033[0m"
    
    print(f"\n{top_box}")
    for line in report_lines:
        print(f"\033[90m│\033[0m {pad_line(line, C_WIDTH)} \033[90m│\033[0m")
    print(f"{bottom_box}\n")
