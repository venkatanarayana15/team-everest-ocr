import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/home/venkatanarayana/team-everest/new-ocr")
from src.pipeline_runner import run_pipeline

async def main():
    job_dir = Path("/home/venkatanarayana/team-everest/new-ocr/output/test_guna")
    job_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = "/home/venkatanarayana/team-everest/new-ocr/Test_Batch/1test/DocScanner_19-Jun-2026_22-03.pdf"
    
    print(f"Running pipeline on {pdf_path}...")
    await run_pipeline(job_dir, pdf_path)
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
