from dataclasses import dataclass


@dataclass
class Config:
    render_dpi: int = 300
    deskew_max_angle: int = 5
    denoise_strength: int = 10
    binarization_block_size: int = 15
    binarization_c: int = 2
    ocr_backend: str = "tesseract"
    max_image_width: int = 1200
    bbox_render_dpi: int = 150