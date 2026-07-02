"""Stress-test the /upload-batch endpoint with multiple PDFs.

Usage:
    uv run python tests/test_batch.py [--count 5] [--port 8000]

If the server is not running, this script will start it automatically.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


SAMPLE_PAGE_1 = """Home Visit Questionnaire
Volunteer Name: Test User
Co-Volunteer Name: Test Co
Date of Visit: 2025-01-15
Section 1: Student Profile
1.1 Application ID: APP-001
1.2 Student Full Name: Test Student
1.3 Gender: Male"""

SAMPLE_PAGE_2 = """2.3 Is Father/Mother photograph kept at home? Yes
2.4 Government ID Verified: Aadhaar Card
3.1 House Ownership: Own
3.2 Type of Home: Individual"""

SAMPLE_PAGE_3 = """3.3 Type of Ceiling: Roof
3.4 Number of Bedrooms: 2
3.5 Bathroom: Separate
3.6 Kitchen Type: Separate Kitchen
4.1 Assets at Home: Washing Machine
4.2 Amount of Last Electricity Bill: 1500"""


def generate_sample_pdf() -> bytes:
    import fitz
    doc = fitz.open()
    for text in [SAMPLE_PAGE_1, SAMPLE_PAGE_2, SAMPLE_PAGE_3]:
        page = doc.new_page(width=595, height=842)
        y = 72
        for line in text.strip().split("\n"):
            page.insert_text((72, y), line, fontsize=11)
            y += 20
    data = doc.tobytes()
    doc.close()
    return data


def main():
    parser = argparse.ArgumentParser(description="Batch upload stress test")
    parser.add_argument("--count", type=int, default=5,
                        help="Number of PDFs to upload (default: 5)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Server port (default: 8000)")
    parser.add_argument("--start-server", action="store_true",
                        help="Auto-start the server if not running")
    parser.add_argument("--poll", type=float, default=5.0,
                        help="Poll interval in seconds (default: 5)")
    parser.add_argument("--timeout", type=float, default=600,
                        help="Per-job timeout in seconds (default: 600)")
    args = parser.parse_args()

    BASE = f"http://127.0.0.1:{args.port}"

    # ── Health check ──────────────────────────────────────────────
    print(f"Checking server at {BASE} ...")
    try:
        r = requests.get(f"{BASE}/docs", timeout=5)
        r.raise_for_status()
    except Exception as e:
        print(f"Server not reachable: {e}")
        if args.start_server:
            print("Starting server...")
            proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "src.server:app",
                 "--port", str(args.port), "--host", "127.0.0.1"],
                cwd=str(Path(__file__).resolve().parent.parent),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            time.sleep(4)
            try:
                r = requests.get(f"{BASE}/docs", timeout=5)
                r.raise_for_status()
                print("Server started.")
            except Exception as e2:
                print(f"Server failed to start: {e2}")
                sys.exit(1)
        else:
            print("Use --start-server to auto-start, or start manually:")
            print(f"  uv run uvicorn src.server:app --port {args.port}")
            sys.exit(1)

    print(f"Server OK. Generating {args.count} sample PDFs...")

    # ── Generate PDFs ─────────────────────────────────────────────
    t0 = time.time()
    files = []
    for i in range(args.count):
        pdf_data = generate_sample_pdf()
        files.append(("files", (f"sample_{i:03d}.pdf", pdf_data, "application/pdf")))
    gen_time = time.time() - t0
    total_kb = sum(len(data) for _, (_, data, _) in files) / 1024
    print(f"Generated {len(files)} PDFs ({total_kb:.1f} KB total) in {gen_time:.2f}s")

    # ── Upload batch ──────────────────────────────────────────────
    print(f"Uploading to {BASE}/upload-batch ...")
    t0 = time.time()
    try:
        r = requests.post(f"{BASE}/upload-batch", files=files, timeout=120)
        r.raise_for_status()
        result = r.json()
    except Exception as e:
        print(f"Upload failed: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text[:500]}")
        sys.exit(1)

    elapsed = time.time() - t0
    print(f"Upload took {elapsed:.2f}s")
    print(f"Response: {json.dumps(result, indent=2)[:600]}")

    jobs = result.get("results", [])
    if not jobs:
        print("No jobs returned!")
        sys.exit(1)

    print(f"\nSubmitted {len(jobs)} jobs. Monitoring (poll every {args.poll}s)...")

    # ── Monitor jobs ──────────────────────────────────────────────
    ok = failed = 0
    for j in jobs:
        jid = j.get("job_id", "?")
        fname = j.get("filename", "?")
        short = jid[:12] if len(jid) > 12 else jid
        print(f"  [{short}] {fname} → ", end="", flush=True)

        deadline = time.time() + args.timeout
        last_status = ""
        while time.time() < deadline:
            try:
                r = requests.get(f"{BASE}/status/{jid}", timeout=10)
                st = r.json()
            except Exception as e:
                print(f"status_error({e})", end="", flush=True)
                time.sleep(args.poll)
                continue
            s = st.get("status", "unknown")
            msg = st.get("message", "")
            if s != last_status:
                print(f"\n    [{s}] {msg[:100]}", end="", flush=True)
                last_status = s
            if s in ("done", "error", "unknown"):
                break
            time.sleep(args.poll)
        else:
            print(" [TIMEOUT]", flush=True)
            failed += 1
            continue

        print(flush=True)
        if s == "done":
            ok += 1
        else:
            failed += 1
            log = st.get("log", [])
            if log:
                print(f"    Last log entries: {json.dumps(log[-3:])}")

    # ── Summary ───────────────────────────────────────────────────
    total = time.time() - t0
    print(f"\n{'='*50}")
    print(f"Results: {ok}/{len(jobs)} succeeded, {failed} failed")
    print(f"Total wall time: {total:.1f}s ({total / max(len(jobs), 1):.1f}s avg)")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
