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
    _get_status, _progress_store, _progress_lock, _render_markdown, _format_job_datetime,
)

logger = logging.getLogger(__name__)

# Global semaphore limiting concurrent PDF page rendering (CPU-bound, prevents thrash)
_RENDER_SEMAPHORE = asyncio.Semaphore(
    int(os.environ.get("RENDER_MAX_CONCURRENCY", "6"))
)

_COMBINE_PAGES = os.environ.get("COMBINE_PAGES", "false").lower() in ("1", "true", "yes")
_BATCH_PRINT_REPORT = os.environ.get("BATCH_PRINT_REPORT", "false").lower() in ("1", "true", "yes")


def _cleanup_pdf_job_dir(pdf_job_dir: Path) -> None:
    pages_dir = pdf_job_dir / "pages"
    if pages_dir.exists():
        for p in pages_dir.glob("*.png"):
            try:
                p.unlink()
            except OSError:
                pass
        try:
            pages_dir.rmdir()
        except OSError:
            pass


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

    async with _progress_lock:
        existing_progress = _progress_store.get(job_dir.name, {})
        start_time = existing_progress.get("start_time")
        if not start_time:
            start_time = time.time()
        elapsed = round(time.time() - start_time, 1)

        pdfs_map = dict(existing_progress.get("pdfs", {}))
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
    coverage = None
    confidence = None
    primary_extraction_failed = False

    if checkpoint:
        step, fields, overall_confidence, raw_text, sections_data = checkpoint
        primary_token_usage = {}
    else:
        await status_func("primary_extraction", f"Running primary extraction ({primary_name})...")

        if _COMBINE_PAGES:
            llm_task = asyncio.create_task(pipeline.run_combined_extraction(pdf_path, processed_images))
        else:
            llm_task = asyncio.create_task(pipeline.run_primary_extraction(pdf_path, processed_images))

        model_data, primary_token_usage = await llm_task

        # Fallback: if combined extraction returned empty, retry per-page
        if _COMBINE_PAGES and (not model_data or not model_data.get("fields")):
            logger.warning("Combined extraction returned no data — falling back to per-page extraction")
            llm_task = asyncio.create_task(pipeline.run_primary_extraction(pdf_path, processed_images))
            model_data, primary_token_usage = await llm_task

        if model_data:
            overall_confidence = model_data.get("overall_confidence", 0)
            coverage = model_data.get("coverage")
            confidence = model_data.get("confidence")
            raw_text = model_data.get("raw_text", "")
            raw_fields = model_data.get("fields", [])
            bad_fields = [f for f in raw_fields if not isinstance(f, dict)]
            if bad_fields:
                logger.warning("Ignoring %d non-dict fields from LLM response", len(bad_fields))
            raw_text = _insert_page_markers(raw_text, raw_fields)
            fields = pipeline.merge_fields(model_data, prefix=primary_name)
            await status_func("field_mapping", f"Merged {len(fields)} fields.")
        else:
            primary_extraction_failed = True
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

        _save_checkpoint(job_dir, "mapped", fields, overall_confidence, raw_text, sections=sections_data, coverage=coverage, confidence=confidence)

    token_usage = {
        "primary": primary_token_usage,
        "total": {
            "prompt_tokens": primary_token_usage.get("prompt_tokens", 0) or 0,
            "completion_tokens": primary_token_usage.get("completion_tokens", 0) or 0,
            "total_tokens": primary_token_usage.get("total_tokens", 0) or 0,
        },
    }

    await status_func("template_fill", "Filling missing template fields...")
    _provider = getattr(pipeline.primary_client, 'provider', '') if pipeline else ''
    fields = ExtractionPipeline.fill_missing_template_fields(fields, pdf_path=pdf_path, provider=_provider)

    all_no_groups = ExtractionPipeline._find_all_no_groups(fields)
    text_refinable = [f for f in fields if ExtractionPipeline._needs_refinement(f) and ExtractionPipeline._is_text_field_candidate(f)]
    do_recheck = all_no_groups and pipeline and pipeline.primary_client and pipeline.primary_client.needs_images
    do_refine = text_refinable and pipeline and pipeline.primary_client and pipeline.primary_client.needs_images

    if do_recheck or do_refine:
        tasks = []
        if do_recheck:
            await status_func("recheck_checkboxes", f"Re-checking {len(all_no_groups)} all-No checkbox groups...")
            tasks.append(ExtractionPipeline._recheck_checkbox_groups(
                fields, pdf_path, processed_images, pipeline.primary_client
            ))
        if do_refine:
            await status_func("text_refinement", f"Re-reading {len(text_refinable)} text fields with focused prompts...")
            tasks.append(ExtractionPipeline._refine_text_fields(
                fields, pdf_path, processed_images, pipeline.primary_client
            ))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("Post-primary task failed: %s", r)
            elif r is not None:
                fields = r

    if _provider == "gemini":
        await status_func("gemini_post_process", "Applying Gemini-specific post-processing...")
        fields = ExtractionPipeline._gemini_post_process(fields)

    fields = ExtractionPipeline._normalize_boolean_fields(fields)

    sections_data = _derive_sections(fields, raw_text or "")

    num_pages = len(processed_images)
    if not num_pages and pdf_path:
        try:
            import fitz
            doc = fitz.open(pdf_path)
            num_pages = len(doc)
            doc.close()
        except Exception:
            num_pages = 0

    return {
        "overall_confidence": overall_confidence,
        "coverage": coverage,
        "confidence": confidence,
        "num_pages": num_pages,
        "raw_text": raw_text or "",
        "primary_model": primary_name,
        "token_usage": token_usage,
        "llm_calls": primary_token_usage.get("calls", 0),
        "sections": sections_data or [],
        "fields": _fields_to_dict(fields),
        "primary_extraction_failed": primary_extraction_failed,
    }


async def _save_to_db(job_dir: Path) -> bool:
    results_path = job_dir / "results" / "result.json"
    if not results_path.exists():
        return True
    logger.info("  [DB] _save_to_db: job_dir=%s result.json=%s", job_dir, "exists" if results_path.exists() else "MISSING")
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
        hash_path = job_dir / "file_hash.txt"
        file_hash = hash_path.read_text().strip() if hash_path.exists() else None
        fields_data = result_data.get("fields", [])
        low_conf = sum(1 for f in fields_data if f.get("confidence", 0) < 70)
        needs_review = sum(1 for f in fields_data if f.get("needs_clarification", False))
        logger.info(
            "Uploading extracted data to Supabase... (file=%r, fields=%d, coverage=%s, confidence=%s, "
            "low_conf=%d, needs_review=%d, time=%.2fs)",
            orig_name,
            len(fields_data),
            result_data.get("coverage", "N/A"),
            result_data.get("confidence", "N/A"),
            low_conf, needs_review,
            result_data.get("processing_time", 0),
        )
        doc_id = await upsert_ocr_document(
            job_id=job_dir.name,
            file_name=orig_name,
            status="done",
            file_hash=file_hash,
            processing_time=result_data.get("processing_time"),
            confidence_score=result_data.get("overall_confidence"),
            num_pdfs=result_data.get("num_pdfs"),
            result_json=result_data,
        )
        if not doc_id:
            logger.warning("  ❌ DB save: upsert returned empty id (job=%s)", job_dir.name)
            return False
        logger.info("  ✅ DB save: %d fields, %d low-conf, row=%s", len(fields_data), low_conf, doc_id)
        return True
    except Exception as e:
        _hint = "check DATABASE_URL in .env and verify Supabase DB is accessible"
        if "connection" in str(e).lower() or "timeout" in str(e).lower():
            _hint = "database connection timeout — check DATABASE_URL / Supabase pooler status"
        elif "42P01" in str(e).split() or "relation" in str(e).lower():
            _hint = "table 'ocr_documents' missing — run schema migration"
        elif "23505" in str(e).split():
            _hint = "duplicate key violation — check upsert logic"
        logger.error("  ❌ DB save FAILED: %s | hint=%s", e, _hint)


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
                processed_images = _ensure_page_images(job_dir / "pages")
                if not processed_images:
                    logger.warning("Preprocessing produced 0 page images — Gemini will receive the raw PDF")
                await _set_status(job_dir, "preprocessing", "Preprocessing done.", pages=len(processed_images))
            else:
                await _set_status(job_dir, "preprocessing", "Skipping page rendering (provider handles PDF directly).")
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
        )
        res["processing_time"] = round(time.time() - t0, 2)
        res["input_type"] = "pdf"
        res["pdf_names"] = [pdf_name]

        await _set_status(job_dir, "saving_results", "Saving results...")
        await asyncio.to_thread(_save_results, job_dir, res, job_dir.name)
        await asyncio.to_thread(_print_field_report, job_dir, res)
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
                pdf_job_dir = job_dir / str(idx)
                pdf_job_dir.mkdir(parents=True, exist_ok=True)

                # Save original PDF for lazy page rendering in UI
                try:
                    shutil.copy2(pdf_info["path"], pdf_job_dir / "original.pdf")
                except Exception:
                    logger.warning("Failed to save original PDF for lazy rendering: %s", pdf_name)

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
                        async with _RENDER_SEMAPHORE:
                            processed = await asyncio.to_thread(pipeline.preprocess_images, image_paths, str(pdf_job_dir))
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
                            async with _RENDER_SEMAPHORE:
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
                    )
                    res["pdf_name"] = pdf_name
                    res["input_type"] = "batch_" + input_type
                    res["processing_time"] = round(time.time() - t0, 2)

                

                    if "zoho_req" in pdf_info:
                        from src.zoho_integration import run_zoho_writeback_for_batch_item
                        await run_zoho_writeback_for_batch_item(job_dir, Path(pdf_info["path"]), pdf_info["zoho_req"], res, input_info)

                    if _BATCH_PRINT_REPORT:
                        await asyncio.to_thread(_print_field_report, pdf_job_dir, res, pdf_name)

                    all_results.append(res)
                    await _set_batch_pdf_status(job_dir, pdf_name, "done", 100, f"Done ({idx+1}/{len(pdfs_info)})")
                except Exception as e:
                    _stage = _progress_store.get(job_dir.name, {}).get("status", "unknown")
                    logger.exception("Batch item failed at stage=%s | pdf=%s", _stage, pdf_name)
                    await _set_batch_pdf_status(job_dir, pdf_name, "error", 100, str(e))
                    all_results.append({"name": pdf_name, "error": f"[stage={_stage}] {e}"})

                queue.task_done()

                _cleanup_pdf_job_dir(pdf_job_dir)

        # Run up to N PDFs concurrently (configurable, default 5)
        max_batch_conc = int(os.environ.get("BATCH_MAX_CONCURRENCY", "2"))
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

        # Save each individual PDF's full result to DB using the batch job_id prefix
        # so the row is discoverable under the batch job rather than subdirectory "0"/"1".
        from src.database import upsert_ocr_document as _batch_upsert
        for r in all_results:
            if "error" in r or not r.get("fields"):
                continue
            pdf_result = r.copy()
            pdf_result["processing_time"] = combined.get("processing_time", 0)
            doc_id = await _batch_upsert(
                job_id=f"{job_dir.name}_{all_results.index(r)}",
                file_name=r.get("pdf_name", f"file_{all_results.index(r)}"),
                status="done",
                processing_time=pdf_result.get("processing_time"),
                confidence_score=pdf_result.get("overall_confidence"),
                result_json=pdf_result,
            )
            if doc_id:
                logger.info("  ✅ Batch-level DB save: job=%s_%s row=%s fields=%d", job_dir.name, all_results.index(r), doc_id, len(pdf_result.get('fields',[])))
            else:
                logger.warning("  ❌ Batch-level DB save failed for %s", r.get('pdf_name','?'))

        _progress_store.pop(job_dir.name, None)
        success = sum(1 for r in all_results if 'error' not in r)
        failed = len(pdfs_info) - success
        logger.info("BATCH REPORT: %d files processed", len(pdfs_info))
        for r in all_results:
            name = r.get("pdf_name", r.get("name", "?"))
            if "error" in r:
                logger.warning("  ✗ %s — FAILED: %s", name, r['error'])
            else:
                fields = r.get("fields", [])
                pages = len({f["page"] for f in fields})
                cov = r.get("coverage", "?")
                conf = r.get("confidence", "?")
                logger.info("  ✓ %s — %d fields, %d pages, coverage=%s%% confidence=%s%%", name, len(fields), pages, cov, conf)
        logger.info("FILES: %d total  |  SUCCESS: %d  |  FAILED: %d  |  Time: %ss", len(pdfs_info), success, failed, combined.get('processing_time', '?'))
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
        await asyncio.to_thread(_save_results, job_dir, res, job_dir.name)
        await asyncio.to_thread(_print_field_report, job_dir, res)
        _db_ok = await _save_to_db(job_dir)
        if not _db_ok:
            logger.error("Image pipeline DB save failed | job=%s", job_dir.name)
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
    all_keys = set()
    for k in (set(name_map.keys()) | set(page_map.keys())):
        if k is None:
            continue
        try:
            all_keys.add(int(k))
        except (ValueError, TypeError):
            logger.warning("Skipping non-integer section key: %r", k)
    all_nums = sorted(all_keys)
    return [
        {"number": num, "name": name_map.get(num, f"Section {num}"), "page": page_map.get(num, 1)}
        for num in all_nums
    ]


def _insert_page_markers(raw_text: str, fields: list) -> str:
    if not raw_text:
        return raw_text
    fields = [f for f in fields if isinstance(f, dict)]
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
    if vis_w > width:
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


def _normalize_label(label: str) -> str:
    return label.lower().rstrip(".").strip()


def _print_field_report(job_dir: Path, res: dict, pdf_name: str | None = None) -> None:
    name_path = job_dir / "original_name.txt"
    display_name = pdf_name or (name_path.read_text().strip() if name_path.exists() else job_dir.name)
    fields = res.get("fields", [])

    fv = {}
    fv_norm: dict[str, str] = {}
    for f in fields:
        label = f.get("label", "")
        value = str(f.get("value", "")).strip()
        if label and value:
            fv[label] = value
            fv_norm[_normalize_label(label)] = value

    def _lookup(label: str) -> str:
        if label in fv:
            return fv[label]
        return fv_norm.get(_normalize_label(label), "")

    def get_val(label: str) -> str:
        return _lookup(label)

    def get_check(label: str) -> str:
        val = _lookup(label)
        if val.lower() in ("yes", "true", "✓", "x"):
            return "☑"
        return "☐"

    def get_radio(label: str, option: str) -> str:
        val = _lookup(label)
        if val.lower() == option.lower():
            return "☑"
        return "☐"

    def get_table_val(table: str, row: int, col: str) -> str:
        raw = f"{table} — Row {row} — {col}"
        return _lookup(raw)

    W = 100
    C_WIDTH = W - 4

    def format_table(headers: list[str], ratios: list[float], rows: list[list[str]]) -> list[str]:
        avail = C_WIDTH - len(headers) - 1
        widths = [int(avail * r) for r in ratios[:-1]]
        widths.append(avail - sum(widths))
        
        tbl = []
        tbl.append("┌" + "┬".join("─" * w for w in widths) + "┐")
        tbl.append("│" + "│".join(f" {h.ljust(widths[i]-2)[:widths[i]-2]} " for i, h in enumerate(headers)) + "│")
        tbl.append("├" + "┼".join("─" * w for w in widths) + "┤")
        for r in rows:
            tbl.append("│" + "│".join(f" {str(val).ljust(widths[i]-2)[:widths[i]-2]} " for i, val in enumerate(r)) + "│")
        tbl.append("└" + "┴".join("─" * w for w in widths) + "┘")
        return tbl

    pages = {1: [], 2: [], 3: [], 4: [], 5: [], 6: []}

    # Page 1
    p1 = pages[1]
    p1.append("I AM THE CHANGE")
    p1.append("Scholarship Program — Home Visit Questionnaire")
    p1.append("Team Everest | Confidential")
    p1.append("─" * C_WIDTH)
    p1.append(f"Volunteer Name: {get_val('Volunteer Name'):<25} Co-Volunteer Name: {get_val('Co-Volunteer Name'):<25} Date: {get_val('Date of Visit')}")
    p1.append("─" * C_WIDTH)
    p1.append("Section 1 — Student Profile")
    p1.append("")
    p1.append("1.1. Application ID")
    p1.append(get_val('1.1 Application ID'))
    p1.append("")
    p1.append("1.2. Student Full Name")
    p1.append(get_val('1.2 Student Full Name'))
    p1.append("")
    p1.append(f"1.3. Gender:   {get_radio('1.3 Gender', 'Male')} Male     {get_radio('1.3 Gender', 'Female')} Female     {get_radio('1.3 Gender', 'Others')} Others")
    p1.append("─" * C_WIDTH)
    p1.append("Section 2 — Family Background")
    p1.append("")
    p1.append(f"2.1. Family Status:   {get_radio('2.1 Family Status', 'Single Parent')} Single Parent     {get_radio('2.1 Family Status', 'Parentless')} Parentless     {get_radio('2.1 Family Status', 'Having both parents')} Having both parents")
    p1.append("")
    p1.append("2.2. Relationship Details (if applicable)")
    r_rows = []
    for i in range(1, 4):
        r1 = get_table_val('2.2 Relationship Details', i, 'Year of Death / Separation')
        r2 = get_table_val('2.2 Relationship Details', i, 'Reason for Death / Separation')
        if r1 or r2:
            r_rows.append([r1, r2])
    if r_rows:
        p1.extend(format_table(["Year of Death / Separation", "Reason for Death / Separation"], [0.35, 0.65], r_rows))
    else:
        p1.append("No relationship details recorded.")

    # Page 2
    p2 = pages[2]
    p2.append("2.3. Is Father/ Mother photograph kept at home?")
    p2.append(f"  {get_radio('2.3 Is Father/Mother photograph kept at home?', 'Yes')} Yes     {get_radio('2.3 Is Father/Mother photograph kept at home?', 'No')} No")
    notes = get_val('2.3 Is Father/Mother photograph kept at home? — Notes')
    if notes:
        p2.append(f"  Notes: {notes}")
    p2.append("")
    p2.append("2.4. Government ID Verified")
    p2.append(f"  {get_check('2.4 Government ID Verified — Aadhaar Card')} Aadhaar Card    {get_check('2.4 Government ID Verified — Ration Card')} Ration Card    {get_check('2.4 Government ID Verified — Driving Licence')} Driving Licence    {get_check('2.4 Government ID Verified — Voter ID')} Voter ID    {get_check('2.4 Government ID Verified — Other')} Other")
    p2.append("")
    p2.append("2.5. Family Members")
    f_rows = []
    for i in range(1, 7):
        c1 = get_table_val('2.5 Family Members', i, 'Name')
        c2 = get_table_val('2.5 Family Members', i, 'Age')
        c3 = get_table_val('2.5 Family Members', i, 'Education')
        c4 = get_table_val('2.5 Family Members', i, 'Occupation')
        c5 = get_table_val('2.5 Family Members', i, 'Annual Income')
        if any([c1, c2, c3, c4, c5]):
            f_rows.append([c1, c2, c3, c4, c5])
    if f_rows:
        p2.extend(format_table(["Name", "Age", "Education", "Occupation", "Annual Income"], [0.3, 0.1, 0.2, 0.2, 0.2], f_rows))
    else:
        p2.append("No family members recorded.")
    p2.append("─" * C_WIDTH)
    p2.append("Section 3 — Housing Condition")
    p2.append("")
    p2.append(f"3.1. House Ownership:   {get_check('3.1 House Ownership — Own')} Own     {get_check('3.1 House Ownership — Rented')} Rented")
    p2.append(f"3.1.1 If rented, what is the rent amount?  {get_val('3.1.1 If rented, what is the rent amount?')}")
    p2.append("")
    p2.append(f"3.2. Type of Home:   {get_check('3.2 Type of Home — Individual')} Individual   {get_check('3.2 Type of Home — Private Apartment')} Private Apartment   {get_check('3.2 Type of Home — Housing Board')} Housing Board   {get_check('3.2 Type of Home — Line House')} Line House   {get_check('3.2 Type of Home — Others')} Others")

    # Page 3
    p3 = pages[3]
    p3.append("3.3. Type of Ceiling")
    p3.append(f"  {get_check('3.3 Type of Ceiling — Roof (Kurai)')} Roof (Kurai)    {get_check('3.3 Type of Ceiling — Tiled')} Tiled    {get_check('3.3 Type of Ceiling — Asbestos / Sheet')} Asbestos / Sheet    {get_check('3.3 Type of Ceiling — Concrete')} Concrete")
    p3.append("")
    p3.append(f"3.4. Number of Bedrooms:  {get_val('3.4 Number of Bedrooms')}")
    p3.append(f"3.4.1 Type of Bedroom:   {get_check('3.4.1 Type of Bedroom — Separate Bedroom')} Separate Bedroom     {get_check('3.4.1 Type of Bedroom — No Separate Bedroom')} No Separate Bedroom")
    p3.append("")
    p3.append(f"3.5. Bathroom:   {get_check('3.5 Bathroom - Separate')} Separate     {get_check('3.5 Bathroom - Common for Apartment')} Common for Apartment")
    p3.append("")
    p3.append(f"3.6. Kitchen Type:   {get_check('3.6 Kitchen Type — Separate Kitchen')} Separate Kitchen     {get_check('3.6 Kitchen Type — Hall with Kitchen')} Hall with Kitchen")
    p3.append("─" * C_WIDTH)
    p3.append("Section 4 — Financial Background")
    p3.append("")
    p3.append("4.1. Assets at Home (tick all that apply)")
    PREFIX = '4.1 Assets at Home(tick all that apply) - '
    p3.append(f"  {get_check(PREFIX + 'Washing Machine')} Washing Machine   {get_check(PREFIX + 'Fridge')} Fridge   {get_check(PREFIX + 'AC')} AC   {get_check(PREFIX + 'LED TV')} LED TV   {get_check(PREFIX + 'Two-Wheeler')} Two-Wheeler   {get_check(PREFIX + 'Car')} Car")
    p3.append(f"  {get_check(PREFIX + 'Smartphone')} Smartphone   {get_check(PREFIX + 'Separate Wi-Fi')} Separate Wi-Fi   {get_check(PREFIX + 'Others:')} Others")
    p3.append("")
    p3.append(f"4.2. Amount of Last Electricity Bill:  {get_val('4.2 Amount of Last Electricity Bill')}")
    p3.append("")
    _4_3 = '4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?'
    p3.append(_4_3[4:])
    p3.append(f"  {get_check(_4_3 + ' — Yes')} Yes     {get_check(_4_3 + ' — No')} No")

    # Page 4
    p4 = pages[4]
    p4.append("4.3.1 If yes, list their properties:")
    prop_rows = []
    for i in range(1, 4):
        c1 = get_table_val('4.3.1', i, 'Property Description')
        c2 = get_table_val('4.3.1', i, 'Owner Name')
        c3 = get_table_val('4.3.1', i, 'Approximate Value')
        if any([c1, c2, c3]):
            prop_rows.append([c1, c2, c3])
    if prop_rows:
        p4.extend(format_table(["Property Description", "Owner Name", "Approximate Value"], [0.4, 0.3, 0.3], prop_rows))
    else:
        p4.append("No properties recorded.")
    p4.append("")
    p4.append("4.4. Apart from your job, is there any other source of income?")
    p4.append(f"  {get_radio('4.4 Apart from your job, is there any other source of income?', 'Yes')} Yes     {get_radio('4.4 Apart from your job, is there any other source of income?', 'No')} No")
    p4.append("")
    p4.append("4.4.1 If yes, list other sources of income:")
    inc_rows = []
    for i in range(1, 4):
        c1 = get_table_val('4.4.1', i, 'Source of Income')
        c2 = get_table_val('4.4.1', i, 'Amount')
        if any([c1, c2]):
            inc_rows.append([c1, c2])
    if inc_rows:
        p4.extend(format_table(["Source of Income", "Amount"], [0.65, 0.35], inc_rows))
    else:
        p4.append("No other sources of income recorded.")
    p4.append("")
    p4.append(f"4.5. Income Type:   {get_check('4.5 Income Type — Monthly')} Monthly ({get_val('4.5 Income Type — Monthly (specify)')})     {get_check('4.5 Income Type — Daily')} Daily ({get_val('4.5 Income Type — Daily (specify)')})     {get_check('4.5 Income Type — Weekly')} Weekly ({get_val('4.5 Income Type — Weekly (specify)')})     {get_check('4.5 Income Type — Ad-Hoc')} Ad-Hoc ({get_val('4.5 Income Type — Ad-Hoc (specify)')})")
    p4.append("")
    p4.append("4.6. Do you have any loans?")
    p4.append(f"  {get_radio('4.6 Do you have any loans?', 'Yes')} Yes     {get_radio('4.6 Do you have any loans?', 'No')} No")
    p4.append("")
    p4.append("4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount:")
    loan_rows = []
    for i in range(1, 5):
        c1 = get_table_val('4.6.1', i, 'Loan Purpose')
        c2 = get_table_val('4.6.1', i, 'Loan Amount Taken')
        c3 = get_table_val('4.6.1', i, 'Pending Loan Amount')
        if any([c1, c2, c3]):
            loan_rows.append([str(i), c1, c2, c3])
    if loan_rows:
        p4.extend(format_table(["Sr. No.", "Loan Purpose", "Loan Amount Taken", "Pending Loan Amount"], [0.1, 0.4, 0.25, 0.25], loan_rows))
    else:
        p4.append("No loans recorded.")

    # Page 5
    p5 = pages[5]
    p5.append(f"4.7. If you choose any college, how much is the college fee?  {get_val('4.7 If you choose any college, how much is the college fee?')}")
    p5.append("")
    p5.append(f"4.8. If the college fee is higher, how will you manage it?  {get_val('4.8 If the college fee is higher, how will you manage it?')}")
    p5.append("")
    p5.append(f"4.9. If you do not receive this scholarship, how will you pay the fees?  {get_val('4.9 If you do not receive this scholarship, how will you pay the fees?')}")
    p5.append("─" * C_WIDTH)
    p5.append("Section 5 — Health Information")
    p5.append("")
    p5.append("5.1. Does the student have any health issues?")
    p5.append(f"  {get_radio('5.1 Does the student have any health issues?', 'Yes')} Yes     {get_radio('5.1 Does the student have any health issues?', 'No')} No")
    p5.append("")
    p5.append(f"5.2. If yes, list the health issues:  {get_val('5.2 If yes, list the health issues:')}")
    p5.append("─" * C_WIDTH)
    p5.append("Section 6 — Student Commitment")
    p5.append("")
    p5.append(f"6.1. Will you study college for three years without any obstacle?  {get_val('6.1 Will you study college for three years without any obstacle?')}")
    p5.append("")
    p5.append(f"6.2. If we have a training program within 15 km from your home, can you come?   {get_radio('6.2 If we have a training program within 15 km from your home, can you come?', 'Yes')} Yes     {get_radio('6.2 If we have a training program within 15 km from your home, can you come?', 'No')} No     {get_radio('6.2 If we have a training program within 15 km from your home, can you come?', 'Maybe')} Maybe")

    # Page 6
    p6 = pages[6]
    p6.append("6.3. Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?")
    p6.append(f"  {get_radio('6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?', 'Yes')} Yes     {get_radio('6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?', 'No')} No")
    p6.append("─" * C_WIDTH)
    p6.append("Section 7 — Scholarship Information")
    p6.append("")
    p6.append(f"7.1. Has the student received or applied for any other scholarships for their UG degree?  {get_val('7.1 Has the student received or applied for any other scholarships for their UG degree?')}")
    p6.append("─" * C_WIDTH)
    p6.append("Section 8 — Volunteer Observation")
    p6.append("")
    p6.append(f"8.1. What is your opinion about the student, their family members, and their living condition?  {get_val('8.1 What is your opinion about the student, their family members, and their living condition?')}")
    p6.append("")
    p6.append(f"8.2. Will you recommend this student for this scholarship?   {get_radio('8.2 Will you recommend this student for this scholarship?', 'Yes')} Yes     {get_radio('8.2 Will you recommend this student for this scholarship?', 'No')} No     {get_radio('8.2 Will you recommend this student for this scholarship?', 'Not Sure')} Not Sure")
    p6.append("")
    p6.append(f"8.3. Any other comments you want to share?  {get_val('8.3 Any other comments you want to share?')}")

    # Center-alignment configurations
    import os
    try:
        term_width = os.get_terminal_size().columns
    except Exception:
        term_width = 120
    indent = max((term_width - W) // 2, 0)
    ind_str = " " * indent

    print(f"\n{ind_str}\033[1m📄 {display_name}\033[0m\n")
    for page_num in sorted(pages.keys()):
        page_title = f"Page {page_num} of 6"
        top_border = f"\033[90m┌── {page_title} " + "─" * (W - 8 - len(page_title)) + "┐\033[0m"
        bottom_border = "\033[90m└" + "─" * (W - 2) + "┘\033[0m"
        
        print(f"{ind_str}{top_border}")
        for line in pages[page_num]:
            print(f"{ind_str}\033[90m│\033[0m {pad_line(line, C_WIDTH)} \033[90m│\033[0m")
        print(f"{ind_str}{bottom_border}")
        print()

    raw_entries = []
    for f in fields:
        label = f.get("label", "")
        value = str(f.get("value", "")).strip()
        if label and value:
            raw_entries.append(f"  {label}: {value}")
    if raw_entries:
        top_border = f"\033[90m┌── Extracted Fields " + "─" * (W - 23) + "┐\033[0m"
        bottom_border = "\033[90m└" + "─" * (W - 2) + "┘\033[0m"
        print(f"{ind_str}{top_border}")
        for entry in raw_entries:
            print(f"{ind_str}\033[90m│\033[0m {pad_line(entry, C_WIDTH)} \033[90m│\033[0m")
        print(f"{ind_str}{bottom_border}")
        print()
