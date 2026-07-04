import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from src.config import Config

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
    def process(self, pdf_path: str, config: Config) -> OCRResult:
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

    def process(self, pdf_path: str, config: Config) -> OCRResult:
        import fitz
        from PIL import Image
        from concurrent.futures import ThreadPoolExecutor

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
        num_workers = min(len(pages_arr), 6)

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = [pool.submit(self._page_result, arr, pn) for arr, pn in pages_arr]
            for f in futures:
                page_num, word_boxes, page_dict = f.result()
                all_boxes.extend(word_boxes)
                pages_data[page_num] = page_dict

        logger.info("Tesseract done: %d total words across %d pages", len(all_boxes), len(pages_data))
        return OCRResult(pages_data=pages_data, word_boxes=all_boxes)

    def process_images(
        self, image_paths: dict[int, str], config: Config
    ) -> OCRResult:
        """Run Tesseract on a dict of page_num -> image_path.

        Unlike process(), this takes already-rendered images and assigns
        page numbers directly from the dict keys.
        """
        from PIL import Image
        from concurrent.futures import ThreadPoolExecutor

        pages_arr: list[tuple[np.ndarray, int]] = []
        for page_num in sorted(image_paths):
            img = Image.open(image_paths[page_num])
            pages_arr.append((np.array(img), page_num))

        all_boxes: list[WordBox] = []
        pages_data: dict[int, dict] = {}
        num_workers = min(len(pages_arr), 6)

        with ThreadPoolExecutor(max_workers=num_workers) as pool:
            futures = [pool.submit(self._page_result, arr, pn) for arr, pn in pages_arr]
            for f in futures:
                page_num, word_boxes, page_dict = f.result()
                all_boxes.extend(word_boxes)
                pages_data[page_num] = page_dict

        logger.info("Tesseract done: %d total words across %d image pages", len(all_boxes), len(image_paths))
        return OCRResult(pages_data=pages_data, word_boxes=all_boxes)


# ─── Gemini API Backend ───────────────────────────────────────────


class GeminiBackend(OCRBackend):
    def __init__(self, api_key: str | None = None, model_name: str = "gemini-2.5-flash"):
        self.api_key = api_key
        self.model_name = model_name

    def process(self, pdf_path: str, config: Config) -> OCRResult:
        import google.generativeai as genai

        def _load_dotenv(path: str = ".env") -> None:
            if not os.path.exists(path):
                return
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    os.environ.setdefault(k.strip(), v.strip())

        _load_dotenv()
        key = self.api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ValueError("Gemini API key required. Set GEMINI_API_KEY env var or pass --gemini-key.")
        genai.configure(api_key=key)

        prompt = (
            "Perform a clean OCR text extraction of this document. "
            "Return the output in structured Markdown, preserving tables and checkmarks."
        )

        logger.info("Uploading: %s", pdf_path)
        sample_file = genai.upload_file(path=pdf_path, mime_type="application/pdf")
        logger.info("Uploaded: %s", sample_file.name)

        model = genai.GenerativeModel(self.model_name)
        logger.info("Calling %s...", self.model_name)
        response = model.generate_content([sample_file, prompt])
        text = response.text

        if hasattr(response, "usage_metadata"):
            logger.info("Tokens: %s", response.usage_metadata)

        return OCRResult(raw_text=text)


# ─── Factory ───────────────────────────────────────────────────────


_backends: dict[str, type[OCRBackend]] = {
    "tesseract": TesseractBackend,
    "gemini": GeminiBackend,
}


def get_backend(name: str, **kwargs) -> OCRBackend:
    if name not in _backends:
        raise ValueError(f"Unknown backend: {name}. Available: {list(_backends.keys())}")
    cls = _backends[name]
    return cls(**kwargs)
