import fitz
import numpy as np
from PIL import Image
from dataclasses import dataclass

from src.config import Config


@dataclass
class Page:
    page_num: int
    image: np.ndarray
    native_text: str
    is_native: bool


def _render_page_to_image(page, dpi: int = 300) -> np.ndarray:
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=mat)
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    return np.array(img)


def _extract_native_text(page) -> str:
    return page.get_text("text").strip()


def ingest(pdf_path: str, config: Config) -> list[Page]:
    doc = fitz.open(pdf_path)
    pages: list[Page] = []
    for i, page in enumerate(doc):
        native_text = _extract_native_text(page)
        image = _render_page_to_image(page, config.render_dpi)
        is_native = len(native_text) >= config.native_text_min_length
        pages.append(
            Page(
                page_num=i + 1,
                image=image,
                native_text=native_text,
                is_native=is_native,
            )
        )
    doc.close()
    return pages