"""
Test script: Only test the Zoho Creator questionnaire POST.
Reuses the last OCR result and sends it to Zoho Creator form endpoint.

Usage:
    cd ~/team-everest/new-ocr
    uv run python test_zoho_post.py
"""

import json
import sys
import os
from pathlib import Path

# Make sure we can import from src/
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

from src.zoho_integration import (
    _get_zoho_access_token,
    _build_creator_payload,
    OcrExtractRequest,
)
import urllib.request

# ── Config ──────────────────────────────────────────────────────────────────
RESULT_JSON_PATH = Path("output/ext_563cf557/results/result.json")
RECORD_ID = "TEMP-2026-10128"

# ── Load last OCR result ────────────────────────────────────────────────────
if not RESULT_JSON_PATH.exists():
    print(f"❌ Result file not found: {RESULT_JSON_PATH}")
    sys.exit(1)

with open(RESULT_JSON_PATH) as f:
    ocr_result = json.load(f)

print(f"✓ Loaded result: {len(ocr_result.get('fields', []))} fields, "
      f"confidence={ocr_result.get('confidence')}%")

# ── Build the Zoho Creator payload ──────────────────────────────────────────
payload = _build_creator_payload(ocr_result)
if not payload:
    print("❌ No fields to write — payload is empty")
    sys.exit(1)

simple_count = sum(1 for v in payload.values() if not isinstance(v, list))
subform_count = sum(1 for v in payload.values() if isinstance(v, list))

print(f"\n{'='*80}")
print(f"  PAYLOAD PREVIEW | record={RECORD_ID}")
print(f"  Fields: {len(payload)} total  |  Simple: {simple_count}  |  Subforms: {subform_count}")
print(f"{'─'*80}")
for key, val in payload.items():
    if isinstance(val, list):
        if val and isinstance(val[0], dict):
            print(f"  ✓ {key}  ({len(val)} rows)")
            for row in val:
                for k, v in row.items():
                    print(f"      {k}: {v}")
        else:
            display = ", ".join(str(x) for x in val) if val else "(empty)"
            print(f"  ✓ {key}: [{display}]")
    else:
        display = str(val)[:60] + "..." if len(str(val)) > 60 else str(val)
        print(f"  ✓ {key}: {display}")
print(f"{'─'*80}")

# ── Get OAuth token ─────────────────────────────────────────────────────────
print("\n⏳ Getting Zoho OAuth token...")
access_token = _get_zoho_access_token()
print(f"✓ OAuth token acquired")

# ── Build request (same as the fixed code) ──────────────────────────────────
app_owner = os.getenv("ZOHO_APP_OWNER", "teameverest")
app_link_name = os.getenv("ZOHO_APP_LINK_NAME", "iatc-selection-one-app")
form_link_name = "Home_Visit_Questionnaire"

url = (f"https://www.zohoapis.com/creator/v2.1/data/{app_owner}/"
       f"{app_link_name}/form/{form_link_name}")

data = json.dumps({"data": payload}).encode()
headers = {
    "Authorization": f"Zoho-oauthtoken {access_token}",
    "Content-Type": "application/json",
}

print(f"\n⏳ POSTing to Zoho Creator...")
print(f"  URL: {url}")
print(f"  Method: POST")
print(f"  Payload size: {len(data)} bytes")

try:
    request = urllib.request.Request(url, data=data, headers=headers, method='POST')
    with urllib.request.urlopen(request) as resp:
        status = resp.status
        response_body = resp.read().decode()
    print(f"\n✅ SUCCESS — HTTP {status}")
    print(f"  Response: {response_body[:500]}")
except urllib.error.HTTPError as e:
    print(f"\n❌ FAILED — HTTP {e.code} {e.reason}")
    error_body = e.read().decode() if e.fp else ""
    print(f"  Response: {error_body[:500]}")
    print(f"\n  Hint: If 405, the form link name '{form_link_name}' may be wrong.")
    print(f"  Try checking available forms in Zoho Creator.")
except Exception as e:
    print(f"\n❌ FAILED — {type(e).__name__}: {e}")
