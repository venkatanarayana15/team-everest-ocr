"""Verify Zoho OAuth scopes and discover the correct form name."""
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")
from src.zoho_integration import _get_zoho_access_token

token = _get_zoho_access_token()
print("✓ OAuth token acquired\n")

OWNER = "teameverest"
APP = "iatc-selection-one-app"

def _try(label, url):
    req = urllib.request.Request(url, headers={"Authorization": f"Zoho-oauthtoken {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            body = resp.read().decode()
            print(f"✅ {label}: HTTP {resp.status}")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"❌ {label}: HTTP {e.code} — {body[:300]}")
        return None

# 1) GET report — tests report.READ scope
print("── Test 1: GET report (report.READ scope) ──")
_try("GET Home_Visit_Questionnaire_Report",
     f"https://www.zohoapis.com/creator/v2.1/data/{OWNER}/{APP}/report/Home_Visit_Questionnaire_Report?limit=1")

# 2) GET app metadata — lists all forms
print("\n── Test 2: GET app metadata (lists forms) ──")
meta = _try("GET app metadata",
            f"https://www.zohoapis.com/creator/v2.1/meta/{OWNER}/{APP}")
if meta:
    sections = meta.get("sections", [])
    forms = [s["link_name"] for s in sections if s.get("type") == "form"]
    reports = [s["link_name"] for s in sections if s.get("type") == "report"]
    print(f"\n  Forms found:   {forms}")
    print(f"  Reports found: {reports}")
    # Find the form linked to our report
    for s in sections:
        if s.get("link_name") == "Home_Visit_Questionnaire_Report":
            print(f"\n  Report 'Home_Visit_Questionnaire_Report' details:")
            print(f"    type: {s.get('type')}")
            print(f"    form_link_name: {s.get('form_link_name', 'N/A')}")

# 3) Dummy POST to form — tests form.CREATE scope
print("\n── Test 3: POST to form (form.CREATE scope) ──")
form_name = "Home_Visit_Questionnaire"
url = f"https://www.zohoapis.com/creator/v2.1/data/{OWNER}/{APP}/form/{form_name}"
dummy = json.dumps({"data": {"Application_ID": "TEST-SCOPE-CHECK"}}).encode()
req = urllib.request.Request(url, data=dummy, headers={
    "Authorization": f"Zoho-oauthtoken {token}",
    "Content-Type": "application/json",
}, method="POST")
try:
    with urllib.request.urlopen(req) as resp:
        print(f"✅ POST to form/{form_name}: HTTP {resp.status}")
        print(f"   Response: {resp.read().decode()[:300]}")
except urllib.error.HTTPError as e:
    body = e.read().decode() if e.fp else ""
    parsed = json.loads(body) if body else {}
    code = parsed.get("code", e.code)
    desc = parsed.get("description", "")
    print(f"❌ POST to form/{form_name}: HTTP {e.code}")
    print(f"   Zoho code: {code}")
    print(f"   Message: {desc}")
    if code == 2945:
        print(f"\n   ⚠ SCOPE MISSING: Your refresh token does NOT have ZohoCreator.form.CREATE.")
        print(f"     You need to regenerate the refresh token with this scope included.")
    elif code == 2894 or "No form" in desc or "invalid" in desc.lower():
        print(f"\n   ⚠ FORM NAME WRONG: '{form_name}' is not valid. Check the forms list above.")
