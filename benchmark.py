"""Quick benchmark: run combined extraction on a small batch, measure time & tokens."""
import asyncio, time, json, os, sys, shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["COMBINE_PAGES"] = "true"
os.environ["OPENAI_IMAGE_DETAIL"] = "low"
os.environ["TESSERACT_ENABLED"] = "false"
os.environ["BATCH_MAX_CONCURRENCY"] = "50"

from src.pipeline_runner import run_pipeline, _run_core_extraction
from src.extraction_pipeline import Config as PipeConfig
from src.model_client import get_model_client
from src.extraction_pipeline import ExtractionPipeline

PDF_DIR = Path("tests/fixtures/allpdf")
pdfs = sorted(PDF_DIR.glob("*.pdf"))

BATCH_SIZE = min(3, len(pdfs))
test_pdfs = pdfs[:BATCH_SIZE]

async def benchmark():
    print(f"\n--- Benchmark: {BATCH_SIZE} PDFs, combined extraction, detail=low ---\n")
    total_start = time.time()
    results = []

    for pdf_path in test_pdfs:
        pdf_path = str(pdf_path)
        name = Path(pdf_path).name
        job_dir = Path("/tmp/ocr_bench") / name.replace(".pdf", "")

        t0 = time.time()
        config = PipeConfig()
        primary = get_model_client("primary")
        pipeline = ExtractionPipeline(config, primary_client=primary)
        token_usage = {}

        try:
            if job_dir.exists():
                shutil.rmtree(str(job_dir))
            job_dir.mkdir(parents=True, exist_ok=True)

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, pipeline.preprocess, pdf_path, str(job_dir))
            processed_images = {}
            from src.pipeline_runner import _ensure_page_images
            processed_images = _ensure_page_images(job_dir / "pages")

            model_data, token_usage = await pipeline.run_combined_extraction(pdf_path, processed_images)

            elapsed = time.time() - t0
            pt = token_usage.get("prompt_tokens", 0)
            ct = token_usage.get("completion_tokens", 0)
            calls = token_usage.get("calls", 1)
            fields = len(model_data.get("fields", [])) if model_data else 0
            results.append({"name": name, "elapsed": elapsed, "prompt": pt, "completion": ct, "calls": calls, "fields": fields})
            print(f"  {name:40s} {elapsed:5.1f}s  prompt={pt:>6}  comp={ct:>5}  calls={calls}  fields={fields}")
        except Exception as e:
            elapsed = time.time() - t0
            print(f"  {name:40s} {elapsed:5.1f}s  ERROR: {e}")
            results.append({"name": name, "elapsed": elapsed, "error": str(e)})
        finally:
            if job_dir.exists():
                shutil.rmtree(str(job_dir))

    total_elapsed = time.time() - total_start
    successes = [r for r in results if "error" not in r]
    if successes:
        avg = sum(r["elapsed"] for r in successes) / len(successes)
        total_tokens = sum(r.get("prompt", 0) + r.get("completion", 0) for r in successes)
        total_api = sum(r["elapsed"] for r in successes)
        print(f"\n--- Results ---")
        print(f"  {len(successes)}/{BATCH_SIZE} succeeded in {total_elapsed:.1f}s total")
        print(f"  Avg per PDF: {avg:.1f}s  |  Total tokens: {total_tokens}")
        print(f"  Estimated for 50: {avg * 50:.0f}s ({avg * 50 / 60:.1f} min)")
    else:
        print("\n  No successful runs.")

if __name__ == "__main__":
    asyncio.run(benchmark())
