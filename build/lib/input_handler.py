"""Input handler — detects and processes different input types.

Supports:
  - Mode A: Single PDF (already handled in server.py)
  - Mode B: Multiple images (6 individual image files)
  - Mode C: ZIP file containing images
  - Mixed batch: Folder with PDFs and image sets
"""

import io
import logging
import os
import tempfile
import zipfile
from pathlib import Path

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif"}


def is_pdf(file_path: str | Path) -> bool:
    return Path(file_path).suffix.lower() == ".pdf"


def is_image(file_path: str | Path) -> bool:
    return Path(file_path).suffix.lower() in IMAGE_EXTENSIONS


def is_zip(file_path: str | Path) -> bool:
    return Path(file_path).suffix.lower() == ".zip"


def detect_input_type(paths: list[str | Path]) -> str:
    """Detect whether a list of files is a single PDF, image set, or mixed.

    Returns: "pdf", "image_set", "zip", or "mixed"
    """
    if len(paths) == 1 and is_pdf(paths[0]):
        return "pdf"

    if len(paths) == 1 and is_zip(paths[0]):
        return "zip"

    image_count = sum(1 for p in paths if is_image(p))
    pdf_count = sum(1 for p in paths if is_pdf(p))

    if image_count > 0 and pdf_count == 0:
        return "image_set"

    if pdf_count > 0 and image_count == 0:
        if pdf_count == 1:
            return "pdf"
        return "pdf_set"

    if pdf_count > 0 and image_count > 0:
        return "mixed"

    return "unknown"


def detect_item_type(item_path: str | Path) -> str:
    """Detect whether a single filesystem item is a PDF or image set.

    Returns: "pdf", "image_set", or "unknown"
    """
    p = Path(item_path)
    if p.is_file() and is_pdf(p):
        return "pdf"
    if p.is_dir():
        images = [f for f in p.iterdir() if f.is_file() and is_image(f)]
        if len(images) >= 4:
            return "image_set"
    return "unknown"


def extract_zip(zip_path: str | Path, extract_dir: str | Path) -> list[str]:
    """Extract a ZIP file and return paths to extracted images."""
    extract_dir = Path(extract_dir)
    extract_dir.mkdir(parents=True, exist_ok=True)

    image_paths: list[str] = []
    with zipfile.ZipFile(str(zip_path), "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower()
            if ext in IMAGE_EXTENSIONS:
                zf.extract(info, extract_dir)
                extracted_path = extract_dir / info.filename
                if extracted_path.exists():
                    image_paths.append(str(extracted_path.resolve()))

    image_paths.sort()
    logger.info("Extracted %d images from %s", len(image_paths), zip_path)
    return image_paths


def scan_folder(folder_path: str | Path) -> list[dict]:
    """Scan a folder and classify each item as PDF or image set.

    Returns list of dicts: {path, type, name, images: [paths]}
    """
    folder = Path(folder_path)
    items: list[dict] = []

    for entry in sorted(folder.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_file() and is_pdf(entry):
            items.append({
                "path": str(entry.resolve()),
                "type": "pdf",
                "name": entry.name,
                "images": [],
            })
        elif entry.is_dir():
            images = sorted([
                str(f.resolve()) for f in entry.iterdir()
                if f.is_file() and is_image(f)
            ])
            if len(images) >= 4:
                items.append({
                    "path": str(entry.resolve()),
                    "type": "image_set",
                    "name": entry.name,
                    "images": images,
                })

    logger.info("Scanned %s: found %d items (%d PDFs, %d image sets)",
                folder_path, len(items),
                sum(1 for i in items if i["type"] == "pdf"),
                sum(1 for i in items if i["type"] == "image_set"))
    return items
