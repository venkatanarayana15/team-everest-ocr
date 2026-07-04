import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from src.status import _set_status, _get_status
from src.pipeline_runner import run_pipeline, _print_field_report

logger = logging.getLogger(__name__)

env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value

ZOHO_CLIENT_ID = get_required_env("ZOHO_CLIENT_ID")
ZOHO_CLIENT_SECRET = get_required_env("ZOHO_CLIENT_SECRET")
ZOHO_REFRESH_TOKEN = get_required_env("ZOHO_REFRESH_TOKEN")
SUPABASE_URL = get_required_env("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = get_required_env("SUPABASE_SERVICE_ROLE_KEY")

_TOKEN_CACHE: dict = {"token": None, "expires_at": 0.0}

class OcrExtractRequest(BaseModel):
    record_id: str
    zoho_app_owner: str
    zoho_app_link_name: str
    zoho_report_link_name: str
    zoho_record_id: str
    file_field_link_name: str
    file_names: list[str]
    bucket: str = "files"


def _get_zoho_access_token() -> str:
    now = time.time()
    if _TOKEN_CACHE["token"] and now < _TOKEN_CACHE["expires_at"] - 60:
        return _TOKEN_CACHE["token"]

    data = urllib.parse.urlencode({
        "refresh_token": ZOHO_REFRESH_TOKEN,
        "client_id": ZOHO_CLIENT_ID,
        "client_secret": ZOHO_CLIENT_SECRET,
        "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(
        "https://accounts.zoho.com/oauth/v2/token", data=data,
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    if "access_token" not in result:
        raise RuntimeError(f"Zoho OAuth failed: {result}")

    expires_in = result.get("expires_in", 3600)
    _TOKEN_CACHE["token"] = result["access_token"]
    _TOKEN_CACHE["expires_at"] = now + expires_in
    return result["access_token"]


def _download_zoho_file(access_token: str, req: OcrExtractRequest, file_name: str) -> bytes:
    encoded_path = urllib.parse.quote(file_name, safe='')
    url = (f"https://www.zohoapis.com/creator/v2.1/data/{req.zoho_app_owner}/"
           f"{req.zoho_app_link_name}/report/{req.zoho_report_link_name}/"
           f"{req.zoho_record_id}/{req.file_field_link_name}/download?filepath={encoded_path}")
    request = urllib.request.Request(
        url, headers={"Authorization": f"Zoho-oauthtoken {access_token}"},
    )
    with urllib.request.urlopen(request) as resp:
        return resp.read()


def _upload_to_supabase(bucket: str, path: str, data: bytes, content_type: str) -> None:
    url = f"{SUPABASE_URL}/storage/v1/object/{bucket}/{path}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
        "apikey": SUPABASE_SERVICE_ROLE_KEY,
        "x-upsert": "true",
        "Content-Type": content_type,
    }
    request = urllib.request.Request(url, data=data, headers=headers, method='PUT')
    with urllib.request.urlopen(request) as resp:
        resp.read()


def _update_zoho_creator(access_token: str, req: OcrExtractRequest, status: str = "updated") -> None:
    url = (f"https://www.zohoapis.com/creator/v2.1/data/{req.zoho_app_owner}/"
           f"{req.zoho_app_link_name}/report/{req.zoho_report_link_name}/"
           f"{req.zoho_record_id}")
    data = json.dumps({"data": {"OCR_Status": status}}).encode()
    headers = {
        "Authorization": f"Zoho-oauthtoken {access_token}",
        "Content-Type": "application/json",
    }
    request = urllib.request.Request(url, data=data, headers=headers, method='PATCH')
    with urllib.request.urlopen(request) as resp:
        resp.read()


def _merge_to_pdf(file_paths: list[Path], output_path: Path) -> None:
    import fitz
    merged = fitz.open()
    for fp in file_paths:
        ext = fp.suffix.lower()
        try:
            if ext in ('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif', '.tiff', '.tif'):
                img_doc = fitz.open(fp)
                pdfbytes = img_doc.convert_to_pdf()
                img_doc.close()
                src = fitz.open("pdf", pdfbytes)
            elif ext == '.pdf':
                src = fitz.open(fp)
            else:
                logger.warning("Skipping unsupported file: %s", fp.name)
                continue
            merged.insert_pdf(src)
            src.close()
        except Exception as e:
            logger.warning("Failed to merge %s: %s", fp.name, e)
    merged.save(str(output_path))
    merged.close()


def _run_ocr_extract_pipeline(job_dir: Path, req: OcrExtractRequest) -> None:
    t0 = time.time()
    logger.info("OCR extract started | record=%s | files=%d", req.record_id, len(req.file_names))
    _set_status(job_dir, "oauth", f"Starting OCR extract for {req.record_id}")

    try:
        _set_status(job_dir, "oauth", "Zoho OAuth...")
        access_token = _get_zoho_access_token()
        logger.info("Zoho OAuth token acquired")
        _set_status(job_dir, "oauth", "Zoho authentication successful")

        download_dir = job_dir / "downloads"
        download_dir.mkdir(exist_ok=True)
        downloaded: list[Path] = []

        for i, file_name in enumerate(req.file_names):
            _set_status(job_dir, "downloading",
                f"Downloading {i+1}/{len(req.file_names)}: {file_name}")
            logger.info("Downloading file %d/%d: %s", i+1, len(req.file_names), file_name)
            try:
                file_bytes = _download_zoho_file(access_token, req, file_name)
            except Exception as e:
                msg = f"Download failed for {file_name}: {e}"
                logger.error(msg)
                _set_status(job_dir, "error", msg)
                return
            ext = Path(file_name).suffix.lower()
            local_path = download_dir / f"{i}_{file_name}"
            local_path.write_bytes(file_bytes)
            downloaded.append(local_path)
            logger.info("Downloaded %s (%d bytes)", file_name, len(file_bytes))

        logger.info("All %d files downloaded", len(downloaded))
        _set_status(job_dir, "downloading", f"Downloaded {len(downloaded)} files")

        combined_pdf = job_dir / "combined.pdf"
        _set_status(job_dir, "converting", "Converting to single PDF...")
        _merge_to_pdf(downloaded, combined_pdf)
        pdf_size = combined_pdf.stat().st_size
        logger.info("Merged PDF created (%.0f KB from %d files)", pdf_size / 1024, len(downloaded))
        _set_status(job_dir, "converting", f"PDF created ({pdf_size/1024:.0f} KB)")

        supabase_path = f"{req.record_id}/{req.record_id}.pdf"
        _set_status(job_dir, "supabase_upload", "Uploading to Supabase Storage...")
        logger.info("Uploading to Supabase: %s/%s (%.0f KB)", req.bucket, supabase_path, pdf_size / 1024)
        _upload_to_supabase(req.bucket, supabase_path, combined_pdf.read_bytes(), "application/pdf")
        logger.info("Supabase upload complete")
        _set_status(job_dir, "supabase_upload", "PDF uploaded to Supabase")

        input_pdf = job_dir / "input.pdf"
        combined_pdf.rename(input_pdf)
        _set_status(job_dir, "pipeline_start", "Starting extraction pipeline...")
        logger.info("Starting extraction pipeline...")

        run_pipeline(job_dir, str(input_pdf))

        result_path = job_dir / "results" / "result.json"
        if result_path.exists():
            with open(result_path) as _f:
                _print_field_report(job_dir, json.load(_f))

        _set_status(job_dir, "zoho_update", "Updating Zoho Creator record...")
        try:
            _update_zoho_creator(access_token, req, "updated")
            logger.info("Zoho Creator OCR_Status=updated | record=%s", req.record_id)
            _set_status(job_dir, "done", "OCR complete — Zoho record updated")
        except Exception as zoho_err:
            logger.error("Zoho Creator update failed | record=%s | error=%s",
                req.record_id, zoho_err)
            _set_status(job_dir, "done", f"Pipeline done but Zoho update failed: {zoho_err}")

    except Exception as e:
        logger.exception("OCR extract failed | record=%s", req.record_id)
        _set_status(job_dir, "error", f"OCR extract failed: {e}")
    finally:
        elapsed = round(time.time() - t0, 1)
        logger.info("OCR extract finished | record=%s | elapsed=%ds", req.record_id, elapsed)
        cur = _get_status(job_dir).get("status", "unknown")
        if cur not in ("done", "error"):
            _set_status(job_dir, "done", f"OCR extract complete ({elapsed}s)")
