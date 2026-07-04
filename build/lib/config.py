from dataclasses import dataclass, field


def _default_trocr_device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        return "cpu"


@dataclass
class Config:
    models_dir: str = "models/"
    output_dir: str = "output/"
    temp_dir: str = "output/temp/"

    render_dpi: int = 300
    native_text_min_length: int = 10

    deskew_max_angle: int = 5
    denoise_strength: int = 10
    binarization_block_size: int = 15
    binarization_c: int = 2

    layout_confidence_threshold: float = 0.3
    handwriting_label: str = "handwriting"
    printed_label: str = "text"

    hw_height_cv_threshold: float = 0.15
    hw_baseline_cv_threshold: float = 0.1

    trocr_model_name: str = "microsoft/trocr-base-handwritten"
    trocr_device: str = field(default_factory=_default_trocr_device)
    trocr_batch_size: int = 4
    crop_padding: int = 10

    reading_order_y_tolerance: int = 20
    field_proximity_threshold: int = 50

    output_json_indent: int = 2
    searchable_pdf_font: str = "Helvetica"
    ocr_backend: str = "tesseract"
    max_image_width: int = 1200