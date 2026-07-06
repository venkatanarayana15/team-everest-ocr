import logging
import os
import time
import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
import numpy as np

logger = logging.getLogger(__name__)

# ─── Locate bundled tesseract binary ────────────────────────────
_tesseract_bin = Path(__file__).resolve().parent.parent / "bin" / "tesseract"
if _tesseract_bin.exists():
    import pytesseract as _pt
    _pt.pytesseract.tesseract_cmd = str(_tesseract_bin)
    os.environ.setdefault("TESSDATA_PREFIX", str(_tesseract_bin.parent))

# ─── Shared data types ────────────────────────────────────────────

@dataclass
class WordBox:
    text: str
    page_num: int
    bbox: tuple[int, int, int, int]  # (left, top, right, bottom)
    confidence: float


@dataclass
class OCRResult:
    raw_text: str | None = None
    pages_data: dict[int, dict] = field(default_factory=dict)
    word_boxes: list[WordBox] = field(default_factory=list)


class OCRBackend(ABC):
    @abstractmethod
    def process(self, pdf_path: str, config) -> OCRResult:
        ...


# ─── Tesseract BBox Backend ───────────────────────────────────────

class TesseractBackend(OCRBackend):
    """Lightweight bounding-box detection using Tesseract OCR.
    Returns word-level text + coordinates. No GPU needed, no C++ crashes."""

    @staticmethod
    def _page_result(
        arr: np.ndarray, page_num: int
    ) -> tuple[int, list[WordBox], dict]:
        import pytesseract

        t0 = time.perf_counter()
        data = pytesseract.image_to_data(arr, output_type=pytesseract.Output.DICT)

        word_texts: list[str] = []
        word_confidences: list[float] = []
        word_bboxes: list[tuple[int, int, int, int]] = []
        word_boxes: list[WordBox] = []

        for j in range(len(data["text"])):
            text = data["text"][j].strip()
            conf = int(data["conf"][j])
            if not text or conf < 0:
                continue
            left = data["left"][j]
            top = data["top"][j]
            w = data["width"][j]
            h = data["height"][j]
            bbox = (left, top, left + w, top + h)
            word_texts.append(text)
            word_confidences.append(conf)
            word_bboxes.append(bbox)
            word_boxes.append(WordBox(
                text=text, page_num=page_num, bbox=bbox, confidence=conf,
            ))

        elapsed = time.perf_counter() - t0
        logger.info("Page %d: %d words in %.2fs", page_num, len(word_texts), elapsed)

        return page_num, word_boxes, {
            "word_texts": word_texts,
            "word_confidences": word_confidences,
            "word_bboxes": word_bboxes,
        }

    def process(self, pdf_path: str, config) -> OCRResult:
        import fitz
        from PIL import Image
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_EXCEPTION

        doc = fitz.open(pdf_path)
        pages_arr: list[tuple[np.ndarray, int]] = []

        for i in range(len(doc)):
            page = doc[i]
            mat = fitz.Matrix(config.bbox_render_dpi / 72, config.bbox_render_dpi / 72)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            pages_arr.append((np.array(img), i + 1))

        doc.close()

        all_boxes: list[WordBox] = []
        pages_data: dict[int, dict] = {}
        num_workers = min(len(pages_arr), config.tesseract_workers)

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = [pool.submit(self._page_result, arr, pn) for arr, pn in pages_arr]
            done, not_done = wait(futures, timeout=config.tesseract_timeout, return_when=FIRST_EXCEPTION)
            for f in not_done:
                logger.warning("Tesseract page task timed out — skipping")
            for f in done:
                if f.exception() is not None:
                    logger.error("Tesseract page task failed: %s", f.exception())
                    continue
                page_num, word_boxes, page_dict = f.result()
                all_boxes.extend(word_boxes)
                pages_data[page_num] = page_dict

        logger.info("Tesseract done: %d total words across %d pages", len(all_boxes), len(pages_data))
        return OCRResult(pages_data=pages_data, word_boxes=all_boxes)

    def process_images(
        self, image_paths: dict[int, str], config
    ) -> OCRResult:
        """Run Tesseract on a dict of page_num -> image_path."""
        from PIL import Image
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_EXCEPTION

        pages_arr: list[tuple[np.ndarray, int]] = []
        for page_num in sorted(image_paths):
            img = Image.open(image_paths[page_num])
            pages_arr.append((np.array(img), page_num))

        all_boxes: list[WordBox] = []
        pages_data: dict[int, dict] = {}
        num_workers = min(len(pages_arr), config.tesseract_workers)

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = [pool.submit(self._page_result, arr, pn) for arr, pn in pages_arr]
            done, not_done = wait(futures, timeout=config.tesseract_timeout, return_when=FIRST_EXCEPTION)
            for f in not_done:
                logger.warning("Tesseract image page task timed out — skipping")
            for f in done:
                if f.exception() is not None:
                    logger.error("Tesseract image page task failed: %s", f.exception())
                    continue
                page_num, word_boxes, page_dict = f.result()
                all_boxes.extend(word_boxes)
                pages_data[page_num] = page_dict

        logger.info("Tesseract done: %d total words across %d image pages", len(all_boxes), len(image_paths))
        return OCRResult(pages_data=pages_data, word_boxes=all_boxes)


_backends: dict[str, type[OCRBackend]] = {
    "tesseract": TesseractBackend,
}


def get_backend(name: str, **kwargs) -> OCRBackend:
    if name not in _backends:
        raise ValueError(f"Unknown backend: {name}. Available: {list(_backends.keys())}")
    cls = _backends[name]
    return cls(**kwargs)


# ─── BBox Cache & Processor Logic ─────────────────────────────────

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


def _save_tesseract_data(job_dir: Path, word_boxes: list[WordBox]) -> None:
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


import asyncio

_TESSERACT_SEMAPHORE = None

def _get_tesseract_semaphore():
    global _TESSERACT_SEMAPHORE
    if _TESSERACT_SEMAPHORE is None:
        _TESSERACT_SEMAPHORE = asyncio.Semaphore(2)
    return _TESSERACT_SEMAPHORE

async def run_tesseract_async(
    loop,
    pipeline,
    processed_images: dict[int, str],
    job_dir: Path,
    use_cache: bool = False,
) -> list[WordBox]:
    bbox_cache = job_dir / "bbox_cache.json"
    cache_key = _get_bbox_cache_key()
    if use_cache and bbox_cache.exists() and cache_key:
        cached = _load_bbox_cache(bbox_cache, cache_key)
        if cached is not None:
            return cached
            
    async with _get_tesseract_semaphore():
        wb = await loop.run_in_executor(None, pipeline.run_bbox_images, processed_images)
        
    if use_cache and cache_key:
        _save_bbox_cache(bbox_cache, cache_key, wb)
    return wb
