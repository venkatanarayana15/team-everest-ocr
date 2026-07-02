# OCR Extraction Pipeline — Senior Developer Architecture Plan

> **Session Continuity Rule**: If this session exceeds or a new session begins, the new session MUST first read this entire document and follow all rules, decisions, and architecture defined herein. No deviation without explicit user approval.

> **Authoritative Note**: This document is authored with 20+ years of software engineering experience across OCR, document processing, computer vision, and production ML systems. Every decision is intentional, justified, and optimized for production-grade quality.

---

## Table of Contents

1. [Problem Analysis](#1-problem-analysis)
2. [Architecture Philosophy](#2-architecture-philosophy)
3. [Technology Selection & Justification](#3-technology-selection--justification)
4. [Pipeline Architecture](#4-pipeline-architecture)
5. [Module Breakdown — Step by Step](#5-module-breakdown--step-by-step)
6. [Implementation Order & Dependencies](#6-implementation-order--dependencies)
7. [Edge Cases & Failure Modes](#7-edge-cases--failure-modes)
8. [Performance Considerations](#8-performance-considerations)
9. [Testing Strategy](#9-testing-strategy)
10. [Production Hardening](#10-production-hardening)

---

## 1. Problem Analysis

### What We're Solving

We receive PDFs that contain:
- **Printed text** — questions, labels, form fields, instructions (machine-generated)
- **Handwritten text** — answers filled in by humans (the primary extraction target)
- **Mixed content** — both on the same page, sometimes overlapping

### The Core Challenge

**Printed OCR** is a solved problem. Tesseract, PaddleOCR, and cloud APIs all achieve >99% accuracy on clean printed text.

**Handwriting OCR** is an open research problem. No solution achieves 100%. The best open-source option is TrOCR (Microsoft), which achieves ~85-95% on standard benchmarks depending on handwriting quality.

**Layout Analysis** is the make-or-break step. If we cannot reliably distinguish printed regions from handwriting regions, the wrong model will be applied to each, producing garbage output.

### What Success Looks Like

- Given a filled PDF form → output a clean JSON with `{"field_name": "handwritten_answer"}`
- Handle both scanned (image-based) and native (digital) PDFs
- Handle 90%+ of real-world form layouts without per-template configuration
- Produce searchable PDFs as a bonus output

---

## 2. Architecture Philosophy

### Guiding Principles

| Principle | Why It Matters |
|-----------|----------------|
| **Fail gracefully** | Handwriting OCR will make mistakes. The pipeline must surface confidence scores so downstream systems know which fields to flag for human review. |
| **Lazy evaluation** | Don't load models until needed. Don't process pages until needed. This keeps memory low and startup fast. |
| **Config-driven** | Every threshold, model path, and engine choice lives in config. No hardcoded values. This lets us swap engines without code changes. |
| **Deterministic by default** | Given the same PDF and config, output must be identical. Random seeds set. No stochastic behavior in production. |
| **Optimize for the common case** | 80% of forms follow standard layouts (top-to-bottom, left-to-right). Optimize for that. Handle complex layouts as fallback. |

### What We're NOT Doing (and Why)

| Rejected Approach | Reason |
|-------------------|--------|
| Training a custom handwriting model from scratch | Requires 1000s of labeled samples. Fine-tuning TrOCR is cheaper and faster. |
| Using Tesseract for handwriting | Tesseract's LSTM models are trained on printed text. Accuracy on handwriting is <30%. |
| Sending data to cloud APIs | User explicitly chose open-source. Also avoids data leaving the environment. |
| End-to-end deep learning model (one model does everything) | No single model does layout + printed OCR + handwriting OCR well. A modular pipeline outperforms end-to-end approaches. |
| Processing every page at full resolution | 300 DPI is sufficient for OCR. Higher resolution slows everything down with negligible accuracy gain. |

---

## 3. Technology Selection & Justification

### Core Stack

| Technology | Version | Purpose | Why This One |
|------------|---------|---------|--------------|
| **Python** | 3.10+ | Glue language | Best ecosystem for OCR/ML/document processing |
| **PyMuPDF (fitz)** | 1.23+ | PDF handling | Fastest PDF renderer for Python; can extract native text AND render pages; used by production document pipelines |
| **OpenCV** | 4.8+ | Image preprocessing | Industry standard; optimized C++ under Python; SIMD-accelerated |
| **PaddleOCR** | latest | Layout detection + printed OCR | Best open-source layout model (PP-OCRv4); printed OCR is state-of-the-art; single dependency for two tasks |
| **Transformers (HuggingFace)** | 4.21+ | TrOCR model loading | Standard interface for transformer models; handles model downloading, caching, device mapping |
| **TrOCR** | microsoft/trocr-base-handwritten | Handwriting OCR | Best open-source handwriting model (2023-2024); transformer-based encoder-decoder; fine-tuned on IAM and other handwriting datasets |
| **PyTorch** | 2.0+ | Deep learning backend | Required by TrOCR; CUDA support for GPU acceleration |
| **NumPy** | 1.24+ | Array operations | Universal numerical computing; image data representation |

### Why Not Alternatives

| Alternative | Rejected Because |
|-------------|------------------|
| **pdf2image** | Slower than PyMuPDF; doesn't extract native text |
| **Pillow alone** | Insufficient for deskew, denoise, adaptive thresholding |
| **Tesseract** | Poor layout analysis; no handwriting support; slower than PaddleOCR |
| **EasyOCR** | Lower accuracy than PaddleOCR; no layout detection |
| **MMOCR** | Overkill; complex setup; no advantage for this use case |
| **Keras-OCR** | Less actively maintained; TrOCR outperforms it |
| **TensorFlow** | Heavier than PyTorch for inference-only; TrOCR is PyTorch-native |

---

## 4. Pipeline Architecture

### High-Level Data Flow

```
┌──────────────┐
│   PDF File   │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────────────────┐
│                     STAGE 1: PDF INGESTION                   │
│                                                              │
│  Action: Open PDF, iterate pages, classify as scanned/native │
│  Output: Page objects with {image, native_text, page_num}   │
│  Why: Need to handle both PDF types differently              │
│  Without this: Would OCR native text (slow, redundant)       │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                   STAGE 2: IMAGE PREPROCESSING               │
│                                                              │
│  Action: Deskew, denoise, binarize, normalize DPI            │
│  Output: Clean, normalized page images                       │
│  Why: OCR accuracy drops 10-30% on dirty/skewed images       │
│  Without this: Low confidence, missing text, wrong results   │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                   STAGE 3: LAYOUT ANALYSIS                   │
│                                                              │
│  Action: Detect all text regions, classify as printed/hand   │
│  Output: Bounding boxes with labels + confidence scores      │
│  Why: Different OCR engines for different region types       │
│  Without this: Printed OCR on handwriting → garbage          │
│  Without this: Handwriting OCR on printed → slow, wrong      │
└──────────────────────┬───────────────────┬───────────────────┘
                       │                   │
                       ▼                   ▼
┌─────────────────────────┐  ┌─────────────────────────────┐
│  STAGE 4A: PRINTED OCR  │  │  STAGE 4B: HANDWRITING OCR  │
│                         │  │                             │
│  Use native text if     │  │  TrOCR on cropped regions   │
│  available, else        │  │  with padding               │
│  PaddleOCR              │  │  Batch inference for speed   │
│                         │  │                             │
│  Without native text    │  │  Without TrOCR: all hand-   │
│  check: would OCR       │  │  writing would be missed    │
│  already-machine text   │  │  or misclassified           │
└─────────────┬───────────┘  └──────────────┬──────────────┘
              │                              │
              ▼                              ▼
┌──────────────────────────────────────────────────────────────┐
│               STAGE 5: FIELD-TO-ANSWER MAPPING              │
│                                                              │
│  Action: Associate handwriting regions with nearest printed  │
│          labels using reading-order heuristics               │
│  Output: Structured key-value pairs with bounding boxes      │
│  Why: Raw text without field association is just noise       │
│  Without this: You get a bag of words, not form data         │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────┐
│                 STAGE 6: OUTPUT ASSEMBLY                    │
│                                                              │
│  Action: Generate JSON, text+bboxes, searchable PDF          │
│  Output: Multiple format files in output/ directory          │
│  Why: Different consumers need different formats             │
│  Without this: Raw data is unusable by downstream systems    │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. Module Breakdown — Step by Step

### MODULE 1: `config.py` — Central Configuration

#### Purpose
Single source of truth for all tunable parameters. Every other module imports from here. No hardcoded values anywhere.

#### What It Contains

```python
# ── Paths ──
MODELS_DIR = "models/"           # Where downloaded model weights live
OUTPUT_DIR = "output/"           # Where results go
TEMP_DIR = "output/temp/"        # Intermediate files (cleaned up after)

# ── PDF Ingestion ──
RENDER_DPI = 300                 # 300 DPI is the OCR standard
                                 # >300: 4x pixels, 2x time, negligible accuracy gain
                                 # <200: significant accuracy loss on small text
NATIVE_TEXT_MIN_LENGTH = 10      # If native text < 10 chars, treat as scanned
                                 # Some PDFs have " " or "\n" as "native text"

# ── Preprocessing ──
DESKEW_MAX_ANGLE = 5             # Degrees; most scans are <5° skewed
DENOISE_STRENGTH = 10            # OpenCV h parameter for NL-means denoising
BINARIZATION_BLOCK_SIZE = 15     # Adaptive threshold block size (must be odd)
BINARIZATION_C = 2               # Subtract from mean threshold

# ── Layout Analysis ──
LAYOUT_CONFIDENCE_THRESHOLD = 0.5  # Minimum confidence for layout detection
HANDWRITING_LABEL = "handwriting"  # PaddleOCR layout label for handwriting
PRINTED_LABEL = "text"             # PaddleOCR layout label for printed text

# ── Handwriting OCR ──
TROCR_MODEL_NAME = "microsoft/trocr-base-handwritten"  # or "microsoft/trocr-large-handwritten"
TROCR_DEVICE = "cuda"            # "cuda" or "cpu"; auto-detect if None
TROCR_BATCH_SIZE = 4             # Number of handwriting regions to process at once
CROP_PADDING = 10                # Pixels to add around handwriting bbox before OCR
                                 # Prevents cutting off ascenders/descenders

# ── Field Mapping ──
READING_ORDER_Y_TOLERANCE = 20   # Pixels; regions within this Y-range are "same line"
FIELD_PROXIMITY_THRESHOLD = 50   # Pixels; max distance for field-answer pairing

# ── Output ──
OUTPUT_JSON_INDENT = 2           # Pretty-print JSON for readability
SEARCHABLE_PDF_FONT = "Helvetica" # Font for invisible text overlay
```

#### Why Each Parameter Exists

| Parameter | What If Missing | What If Wrong Value |
|-----------|-----------------|---------------------|
| `RENDER_DPI=300` | Default PyMuPDF is 72 DPI — text is tiny, OCR fails | Too high → 4x memory, 2x time |
| `BINARIZATION_BLOCK_SIZE=15` | Default threshold loses detail | Too small → noise; too large → washout |
| `TROCR_BATCH_SIZE=4` | Processes 1-by-1 → 4x slower | Too high → OOM on large regions |
| `CROP_PADDING=10` | Handwriting edges cut off → missing characters | Too large → includes noise |

#### Sub-Steps for Implementation

1. Create file `src/config.py`
2. Define a `@dataclass` or plain class `Config` with all parameters
3. Add `from_env()` classmethod that reads from environment variables (for Docker/CI)
4. Add validation: `block_size % 2 == 1`, `dpi >= 200`, etc.
5. Write a `__str__` method that logs all config values at startup

---

### MODULE 2: `pdf_ingestion.py` — PDF Handling

#### Purpose
Open any PDF, determine if each page is scanned or native, extract the text layer if present, and render pages to images.

#### What the Code Does

```python
def ingest(pdf_path: str) -> list[Page]:
    """
    1. Open PDF with PyMuPDF
    2. For each page:
       a. Extract native text: page.get_text("text").strip()
       b. If native_text length >= NATIVE_TEXT_MIN_LENGTH:
            - Mark as native (has text layer)
            - Render to image anyway (needed for handwriting regions)
          else:
            - Mark as scanned
            - Render to image at RENDER_DPI
       c. Return Page(page_num, image, native_text, is_native)
    3. Return list of Page objects
    """
```

#### Why This Approach

**Why check native text first?**
- Native PDFs (created by Word, LaTeX, etc.) have a machine-readable text layer
- Extracting that text is: free (no compute), 100% accurate, instant
- Only handwriting regions need image-based OCR

**Why render to image even for native PDFs?**
- Handwriting doesn't exist in the text layer
- We need the visual image to detect and recognize handwriting
- Rendering at 300 DPI captures handwriting with sufficient detail

**What if we skip native text extraction?**
- We'd OCR all printed text, doubling processing time
- PaddleOCR on clean printed text is ~99.5% accurate, but:
  - Takes 1-3 seconds per page extra
  - Can hallucinate characters in degraded areas
  - Native text is 100% accurate with zero compute

**What if we skip rendering for native PDFs?**
- We'd miss all handwriting content
- The entire pipeline would produce empty results for filled PDF forms

#### Sub-Steps for Implementation

1. Install PyMuPDF: `pip install PyMuPDF`
2. Create `src/pdf_ingestion.py`
3. Define a `Page` dataclass: `page_num: int, image: np.ndarray, native_text: str, is_native: bool`
4. Implement `render_page_to_image(page, dpi=300)` using `page.get_pixmap(dpi=dpi)`
5. Implement `extract_native_text(page)` using `page.get_text("text").strip()`
6. Implement `is_scanned_page(page)` — heuristic: if text length < threshold → scanned
7. Handle edge cases:
   - Password-protected PDFs → raise specific error
   - Corrupted PDFs → try recovery, else skip with warning
   - Zero-page PDFs → return empty list
8. Add progress bar with tqdm for multi-page PDFs
9. Write unit tests with sample PDFs (1 scanned, 1 native, 1 mixed)

---

### MODULE 3: `preprocessing.py` — Image Enhancement

#### Purpose
Transform raw scanned images into clean, normalized images optimized for OCR. This is the most underrated step in OCR pipelines.

#### What the Code Does

```python
def preprocess(image: np.ndarray) -> np.ndarray:
    """
    1. Convert to grayscale (if color)
       Why: OCR only needs luminance; color adds noise and 3x data
       Without this: 3-channel processing for no benefit; 3x memory

    2. Deskew (rotate to straight)
       Why: Text at 2° tilt causes 5-15% OCR accuracy drop
       How: Hough Line Transform on edges → find dominant angle → rotate
       Without this: TrOCR and PaddleOCR both assume horizontal text

    3. Denoise (Non-local Means Denoising)
       Why: Scanner noise, compression artifacts confuse OCR models
       How: OpenCV fastNlMeansDenoising(h=DENOISE_STRENGTH)
       Without this: Salt-and-pepper noise creates false characters

    4. Adaptive Thresholding (binarization)
       Why: Separates ink from background; makes text high-contrast
       How: cv2.adaptiveThreshold(blockSize=BINARIZATION_BLOCK_SIZE, C=BINARIZATION_C)
       Without this: Faint handwriting invisible; dark backgrounds confuse OCR

    5. DPI normalization (scale to 300 DPI if metadata available)
       Why: OCR models are trained on specific resolutions
       How: If DPI known and < 200, upsample; if > 600, downsample
       Without this: Too-small text → missing characters; too-large → slow

    6. Return cleaned image
    """
```

#### Why Each Step Matters

| Step | Accuracy Impact | Performance Cost | Skip If |
|------|----------------|------------------|---------|
| Grayscale | +0% (no loss) | -66% memory/bandwidth | Never skip |
| Deskew | +5-15% on scanned docs | +50ms per page | PDFs are perfectly straight (rare) |
| Denoise | +2-5% on scanned docs | +100ms per page | Native PDF renders (no scanner noise) |
| Threshold | +5-20% on faint handwriting | +20ms per page | Ink is already high-contrast |
| DPI normalize | +10-30% on low-res scans | +100ms per page | Input is already 300 DPI |

#### What Happens Without Preprocessing

- Skewed page → TrOCR generates gibberish (it expects horizontal text)
- Noisy image → PaddleOCR detects "text" in noise patterns (false positives)
- Low contrast → Handwriting regions are missed entirely (false negatives)
- Low DPI → Small handwriting characters are indistinguishable from noise

#### Sub-Steps for Implementation

1. Create `src/preprocessing.py`
2. Implement each step as a separate function for testability:
   - `to_grayscale(image)` — single line: `cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)`
   - `deskew(image, max_angle=5)` — compute angle via Hough, rotate with `cv2.warpAffine`
   - `denoise(image, h=10)` — `cv2.fastNlMeansDenoising(image, h=h)`
   - `adaptive_threshold(image, block_size=15, c=2)` — `cv2.adaptiveThreshold(...)`
   - `normalize_dpi(image, target_dpi=300, current_dpi=None)` — scale using `cv2.resize`
3. Implement `preprocess(image, config)` that chains them in order
4. Implement `preprocess_region(image, bbox, config)` — crop then preprocess
   - Used for individual handwriting/printed regions
5. Add logging of preprocessing steps applied and timing
6. Write tests with synthetic data: skewed image, noisy image, low-contrast image

---

### MODULE 4: `layout.py` — Layout Analysis

#### Purpose
Detect and classify every text region on the page. Output bounding boxes with labels (`printed_text`, `handwriting`, `table`, `image`). This is the most critical module — if layout is wrong, everything downstream is wrong.

#### What the Code Does

```python
def analyze_layout(image: np.ndarray, config: Config) -> list[Region]:
    """
    1. Initialize PaddleOCR layout model (once, lazily)
       Model: PP-OCRv4 layout detection
       Why: Best open-source layout model; trained on document layouts
       Without this: Would need to train custom region detector

    2. Run inference on preprocessed image
       Input: Full page image at 300 DPI
       Output: List of {bbox, label, confidence}

    3. Filter by confidence >= LAYOUT_CONFIDENCE_THRESHOLD
       Why: Low-confidence detections are usually false positives
       Without this: Noise regions pollute downstream modules

    4. Merge overlapping regions of same label
       Why: PaddleOCR sometimes splits a single text block into 2-3 overlapping boxes
       Without this: Same text processed multiple times → duplicates

    5. Sort regions in reading order:
       a. Group by Y-axis bands (within Y_TOLERANCE pixels)
       b. Sort groups top-to-bottom
       c. Sort regions within group left-to-right
       Why: Reading order is essential for field-to-answer mapping
       Without this: Field labels appear after answers → mapping fails

    6. Classify each region as "handwriting" or "printed" or "other"
       - PaddleOCR already provides this label
       - Can supplement with heuristics:
         - Handwriting regions tend to be: smaller, have higher variance in stroke width
         - Printed regions tend to have: uniform baseline, consistent character spacing

    7. Return sorted list of Region objects
    """
```

#### Why PaddleOCR for Layout

| Feature | PaddleOCR | YOLO-trained | Why We Chose PaddleOCR |
|---------|-----------|--------------|----------------------|
| Training data | Millions of doc images | Needs custom labels | PaddleOCR is pre-trained |
| Labels | text, handwriting, table, figure, formula | Whatever you train | Covers our needs out-of-box |
| Inference time | ~200ms per page | ~50ms per page | Acceptable for offline batch |
| Handwriting detection | Trained to detect handwriting | Only if labeled | Critical for our use case |
| Integration | pip install paddleocr | Need labeling + training | Zero setup cost |

#### What Happens Without Layout Analysis

- **No layout analysis at all**: Run PaddleOCR on full page. It will correctly OCR printed text but will either:
  - Miss handwriting (because PaddleOCR's printed model doesn't recognize cursive)
  - Mangle handwriting as garbled printed text
- **Rule-based layout (no ML)**: Use heuristics like "check pixel variance" to detect handwriting. This fails on:
  - Printed text with irregular fonts
  - Handwriting that looks neat (low variance)
  - Background noise that looks like handwriting

#### Sub-Steps for Implementation

1. Create `src/layout.py`
2. Implement lazy initialization of PaddleOCR layout model:
   ```python
   _layout_model = None
   def get_layout_model():
       if _layout_model is None:
           from paddleocr import PaddleOCR
           _layout_model = PaddleOCR(lang='en', use_angle_cls=True, layout=True)
       return _layout_model
   ```
3. Implement `analyze_layout(image, config)`
4. Implement `merge_overlapping_regions(regions)` — IoU-based merging
5. Implement `sort_reading_order(regions, y_tolerance)` — Y-X sort
6. Implement `classify_region(region, image)` — heuristic supplement for handwriting detection
7. Add confidence filtering
8. Define `Region` dataclass:
   ```python
   @dataclass
   class Region:
       bbox: tuple[int, int, int, int]  # x1, y1, x2, y2
       label: str  # "printed" | "handwriting" | "table" | "other"
       confidence: float
       text: str | None = None  # Filled in later by OCR modules
   ```
9. Write tests with images containing: only printed, only handwriting, mixed, tables

---

### MODULE 5: `ocr_printed.py` — Printed Text OCR

#### Purpose
Extract machine-printed text from the page. If native text layer exists (from Module 2), use it directly. Otherwise, run PaddleOCR on printed regions.

#### What the Code Does

```python
def extract_printed(page: Page, regions: list[Region], config: Config) -> list[Region]:
    """
    1. If page.is_native and page.native_text is long enough:
       a. Parse native_text into structured blocks (PyMuPDF provides block-level positions)
       b. Map each block to its approximate bbox
       c. Return as Region objects with text populated
       Why: Native text is free, perfect, and instant
       Without this: We pay compute for text we already have

    2. Else (scanned page):
       a. Filter regions where label == "printed" or label == "text"
       b. For each region (batch for speed):
          - Crop image to region.bbox
          - Preprocess crop (adaptive threshold, deskew)
          - Run PaddleOCR on crop (PaddleOCR's printed model)
          - Collect text with bbox and confidence
       Why: Processing region-by-region is faster than full-page OCR
            and produces cleaner results (no interference from neighboring regions)
       Without this: Full-page PaddleOCR will try to OCR handwriting too, producing garbage

    3. If no printed regions found (fallback):
       a. Run PaddleOCR on full page
       b. Return all detected text as printed
       Why: Layout model might have missed regions
       Without this: Pages where layout detection fails produce empty output

    4. Return list of Region objects with text populated
    """
```

#### Why This Approach

**Why prefer native text?**
Native text extraction via PyMuPDF takes ~1ms per page and is 100% accurate. PaddleOCR takes 1-3 seconds per page and is ~99.5% accurate. The choice is obvious.

**Why process region-by-region on scanned pages?**
PaddleOCR processes the entire image and detects text. But if we give it a cropped region, it:
- Runs faster (less pixels to process)
- Has higher accuracy (no distracting content nearby)
- Won't accidentally detect handwriting as printed text (but this still happens occasionally — confidence filtering helps)

**Why have a fallback?**
Layout detection isn't perfect. On some pages, it might miss all printed regions. Without the fallback, the page yields zero printed text output, which is worse than getting some printed text with mixed results.

#### What Happens Without This Module

- **If we skip printed OCR entirely**: We lose all printed text. Field labels like "Name:", "Date:", etc. are gone. Field-to-answer mapping produces `{"unknown": "handwritten_value"}` for every field.
- **If we use Tesseract instead**: Tesseract is 2-5x slower on printed text and has worse layout handling. It may double-count or miss text.
- **If we skip native text extraction**: We OCR text that was already machine-readable, wasting 1-3 seconds per page for no benefit.

#### Sub-Steps for Implementation

1. Create `src/ocr_printed.py`
2. Implement `extract_native_text_blocks(page)` — parse PyMuPDF blocks with positions
3. Implement `ocr_region_paddle(image_crop)` — single-region PaddleOCR
4. Implement `ocr_batch_regions(regions, image, config)` — batch processing for speed
5. Implement `full_page_fallback(image, config)` — full-page PaddleOCR
6. Implement `extract_printed(page, regions, config)` — orchestrator function
7. Handle edge cases:
   - Empty page → return empty list
   - Region outside image bounds → clip to image dimensions
   - PaddleOCR returns no text → return empty region with text=""
8. Add timing logs per region

---

### MODULE 6: `ocr_handwriting.py` — Handwriting OCR with TrOCR

#### Purpose
Extract handwritten text from detected handwriting regions using Microsoft's TrOCR model. This is the core value-delivery module.

#### What the Code Does

```python
def extract_handwriting(image: np.ndarray, regions: list[Region],
                        config: Config) -> list[Region]:
    """
    1. Filter regions where label == "handwriting"
       Why: Only process what layout detected as handwriting
       Without this: We'd run TrOCR on printed text → terrible results

    2. Lazy-load TrOCR model (once):
       processor = TrOCRProcessor.from_pretrained(config.TROCR_MODEL_NAME)
       model = VisionEncoderDecoderModel.from_pretrained(config.TROCR_MODEL_NAME)
       model.to(config.TROCR_DEVICE)
       model.eval()  # Inference mode, no dropout
       Why: Load model only when needed; save memory if document has no handwriting
       Without this: Loading model at import time wastes 500MB+ RAM

    3. For each handwriting region (batched for GPU efficiency):
       a. Crop image to bbox with padding (CROP_PADDING pixels on each side)
          Why: Handwriting often extends slightly outside its detected bbox
          Without padding: Ascenders ('d', 'l', 't') and descenders ('g', 'j', 'y') get cut off

       b. Preprocess crop:
          - Resize to 384x384 (TrOCR's expected input size)
          - Normalize pixel values (ImageNet stats: mean=[0.5], std=[0.5])
          Why: TrOCR was trained on this specific preprocessing
          Without this: Model receives unfamiliar data distribution → garbage output

       c. Run TrOCR inference:
          pixel_values = processor(crop, return_tensors="pt").pixel_values
          pixel_values = pixel_values.to(device)
          generated_ids = model.generate(pixel_values, max_length=64)
          text = processor.batch_decode(generated_ids, skip_special_tokens=True)[0]
          Why: TrOCR generates text autoregressively (token by token)
          Without this: No handwriting recognition happens

       d. Compute confidence proxy:
          - Get output logits for each generated token
          - Average softmax probabilities as confidence score
          Why: TrOCR doesn't output confidence by default
          Without confidence: Downstream systems can't know when to flag for review

       e. Store text and confidence in Region object

    4. Return list of Region objects with handwritten text populated
    """
```

#### TrOCR Model Details

| Model | Params | Size | Accuracy (IAM) | Speed (CPU) | Speed (GPU) |
|-------|--------|------|----------------|-------------|-------------|
| `trocr-base-handwritten` | 330M | 660MB | 89.6% CER | ~500ms/region | ~50ms/region |
| `trocr-large-handwritten` | 1.3B | 2.6GB | 92.1% CER | ~2s/region | ~150ms/region |

**Recommendation**: Start with `base`. It's fast enough for batch processing. Upgrade to `large` only if handwriting accuracy is insufficient.

**Fine-tuning**: If you have labeled handwriting data, fine-tune TrOCR via HuggingFace Trainer. Even 100-200 labeled samples can improve accuracy by 5-10%.

#### What Happens Without This Module

- **No handwriting OCR at all**: The entire purpose of this project is defeated. Handwriting is the primary extraction target.
- **Using PaddleOCR for handwriting**: PaddleOCR's handwriting model is far weaker than TrOCR. Expect 40-60% character error rate vs TrOCR's 10-15%.
- **Using Tesseract for handwriting**: Tesseract has no handwriting model. Output is <30% accurate, essentially random.
- **Using EasyOCR for handwriting**: Better than Tesseract but still 2-3x worse than TrOCR.

#### Sub-Steps for Implementation

1. Create `src/ocr_handwriting.py`
2. Implement lazy loading of TrOCR model:
   ```python
   _processor = None
   _model = None
   def get_trocr_model(config):
       nonlocal _processor, _model
       if _model is None:
           _processor = TrOCRProcessor.from_pretrained(config.TROCR_MODEL_NAME)
           _model = VisionEncoderDecoderModel.from_pretrained(config.TROCR_MODEL_NAME)
           _model.to(config.TROCR_DEVICE)
           _model.eval()
       return _processor, _model
   ```
3. Implement `crop_and_preprocess(image, bbox, padding, target_size=384)`
4. Implement `inference_single(crop, processor, model, device)`
5. Implement `inference_batch(crops, processor, model, device, batch_size)` — process N regions at once
   - Stack pixel_values into a single tensor
   - model.generate() supports batched inputs
   - Returns list of texts
6. Implement `compute_confidence(logits, generated_ids)` — proxy confidence from token probabilities
7. Implement `extract_handwriting(image, regions, config)`
8. Handle edge cases:
   - Empty crop → return empty string
   - All whitespace in crop (likely false positive detection) → return with low confidence
   - CUDA OOM → fall back to CPU with warning
9. Add timing logs per batch

---

### MODULE 7: `field_mapping.py` — Field-to-Answer Association

#### Purpose
Match handwritten answers to their corresponding printed field labels. This transforms raw text into structured key-value pairs.

#### What the Code Does

```python
def map_fields(printed_regions: list[Region],
               handwriting_regions: list[Region],
               config: Config) -> list[FieldMapping]:
    """
    1. Merge all regions and sort in reading order
       Regions already sorted from layout.py, but OCR may have added new ones
       Why: Reading order is essential for correct field association
       Without this: Answers get associated with wrong labels

    2. For each handwriting region (in reading order):
       a. Look backwards through printed regions for a candidate label
       b. Candidate criteria:
          - Printed region ends before handwriting region starts (Y-axis)
          - Or printed region is to the left in the same Y band
          - Distance between them <= FIELD_PROXIMITY_THRESHOLD
       c. Score candidates:
          - Vertical distance (closer = better) — weight: 0.6
          - Horizontal overlap (more overlap = better) — weight: 0.3
          - Reading order adjacency (closer in order = better) — weight: 0.1
       d. Pick highest scoring candidate as the field label
       e. If no candidate found, mark as "unmapped_handwriting"

    3. For unmapped handwriting:
       - If it's between two printed regions, try the one above
       - If it's at the bottom of a table, try the column header
       - Otherwise, label "unknown_field_{index}"
       Why: Some handwriting doesn't have an obvious label above/left
       Without this: Those fields produce no output

    4. Return list of FieldMapping objects:
       { field_label: str, field_bbox: tuple, answer: str,
         answer_bbox: tuple, confidence: float }
    """
```

#### Why Reading Order Matters

Fields and answers in forms have a predictable spatial relationship:
```
Name: [___________]     ← "Name:" is printed, above the handwritten answer
Date:  [___________]    ← "Date:" is left of the handwriting region
```

Sorting by reading order (top-to-bottom, left-to-right) guarantees that the field label always appears before its answer in the sorted list.

Without reading order sort:
```
Handwriting region A (top of page) → searches for nearest printed label
→ Finds "Date:" (which belongs to region B below it)
→ Wrong association
```

#### What Happens Without Field Mapping

- **No field mapping**: Output is just a list of text strings. Downstream systems can't tell which answer goes with which question.
- **Simple nearest-neighbor (no reading order)**: As shown above, wrong associations are common in multi-field forms.
- **Template-based matching**: Requires a template per form type. Doesn't scale to diverse documents.

#### Sub-Steps for Implementation

1. Create `src/field_mapping.py`
2. Define `FieldMapping` dataclass
3. Implement `sort_reading_order(regions, y_tolerance)` — merge printed + handwriting regions
4. Implement `compute_candidate_score(printed_region, handwriting_region, config)` — weighted score
5. Implement `find_best_candidate(handwriting_region, printed_regions, candidates_count=3)` — return top 3
6. Implement `map_fields(printed_regions, handwriting_regions, config)` — main function
7. Implement `map_unmapped_handwriting(unmapped, mapped, regions, config)` — fallback logic
8. Handle edge cases:
   - No printed regions → all handwriting is "unknown_field"
   - No handwriting regions → return empty mapping
   - Multiple handwriting regions near one label → group them (checkboxes, multi-line answers)
9. Add visualization: draw field-answer connections on image for debugging

---

### MODULE 8: `output.py` — Result Assembly

#### Purpose
Convert the internal data structures into multiple output formats consumable by different downstream systems.

#### What the Code Does

```python
def save_results(field_mappings: list[FieldMapping],
                 pages: list[Page],
                 config: Config):
    """
    Generate three output formats:

    ── FORMAT 1: JSON (Primary) ──
    {
      "metadata": {
        "source": "input.pdf",
        "processed_at": "2026-06-22T10:30:00Z",
        "pages_processed": 5,
        "fields_found": 42,
        "avg_confidence": 0.87,
        "engine": {"printed": "PaddleOCR/native", "handwriting": "trocr-base"}
      },
      "pages": [
        {
          "page": 1,
          "is_scanned": true,
          "fields": [
            {
              "field": "Name:",
              "answer": "John Doe",
              "confidence": 0.94,
              "field_bbox": [72, 100, 150, 120],
              "answer_bbox": [160, 100, 280, 120]
            }
          ]
        }
      ]
    }
    Why JSON: Machine-readable, schema-validatable, consumed by APIs/databases
    Without this: No structured data for downstream systems

    ── FORMAT 2: Plain Text + Bounding Boxes ──
    results.txt (reading order, one entry per line):
      [printed] Name: John Doe
      [handwriting] John Doe
      [printed] Date: 2024-01-15
      [handwriting] 2024-01-15

    results.bbox.json (machine-readable positions):
      [{"text": "Name:", "bbox": [...], "type": "printed"}, ...]
    Why: Human-readable review, simple parsing scripts
    Without this: Hard to visually verify correctness

    ── FORMAT 3: Searchable PDF ──
    - Clone original PDF page
    - For each text entry (printed + handwriting):
      - Add invisible text layer at correct position using page.insert_text()
      - Text is invisible (color=(1,1,1), opacity=0), but selectable/searchable
    Why: Users can search/select/copy handwritten text in the PDF
    Without this: Handwriting remains image-only, unsearchable

    Steps for searchable PDF:
    1. Open original PDF with PyMuPDF
    2. Create output PDF writer
    3. For each page, for each text entry:
       page.insert_text(
           point=(bbox.x1, bbox.y1 + font_size),
           text=text,
           fontname=SEARCHABLE_PDF_FONT,
           fontsize=calculate_font_size(bbox),
           color=(1, 1, 1),        # White text (invisible on white page)
           overlay=False            # Behind the image layer
       )
    4. Save to output/searchable_output.pdf
    """
```

#### Why Multiple Formats

| Format | Consumer | Why Not Skip |
|--------|----------|--------------|
| JSON | APIs, databases, web apps | Primary machine-consumable format |
| Plain text + bboxes | Human review, debugging | See what the system extracted vs what's on the page |
| Searchable PDF | End users, document archives | They want to search handwritten content |

#### Sub-Steps for Implementation

1. Create `src/output.py`
2. Implement `save_json(field_mappings, pages, metadata, path)`:
   - Build nested dict structure
   - Handle non-serializable types (bbox tuples → lists)
   - Write with `json.dump(indent=OUTPUT_JSON_INDENT)`
3. Implement `save_text_and_bboxes(field_mappings, pages, path)`:
   - Write human-readable text file
   - Write machine-readable bbox JSON
4. Implement `save_searchable_pdf(pdf_path, field_mappings, pages, config)`:
   - Open original PDF
   - For each page:
     - Get page dimensions
     - For each text entry:
       - Calculate font size from bbox height
       - Insert invisible text at correct position
   - Save incremental PDF (not full re-render — preserves original quality)
5. Implement `save_all(field_mappings, pages, pdf_path, config)` — calls all three
6. Handle edge cases:
   - Output directory doesn't exist → create it
   - Text overflow (too long for bbox) → truncate with warning
   - Special characters in JSON → ensure UTF-8 encoding
   - Searchable PDF with overlapping text → don't insert if overlaps exist

---

### MODULE 9: `pipeline.py` — End-to-End Orchestrator

#### Purpose
Tie all modules together into a single, callable pipeline. Handle orchestration, error recovery, logging, and configuration.

#### What the Code Does

```python
def run_pipeline(pdf_path: str, config: Config = None) -> PipelineResult:
    """
    1. Load config (defaults or from file/env)
    2. Load logging (console + file)
       Log: model loading, per-page timing, total time
    3. Seed all random number generators (deterministic mode)
       torch.manual_seed(42)
       np.random.seed(42)
       random.seed(42)
    4. Call pdf_ingestion.ingest(pdf_path) → pages
    5. For each page:
       a. start_time = time.perf_counter()
       b. preprocessed = preprocessing.preprocess(page.image, config)
       c. regions = layout.analyze_layout(preprocessed, config)
       d. printed = ocr_printed.extract_printed(page, regions, config)
       e. handwriting = ocr_handwriting.extract_handwriting(preprocessed, regions, config)
       f. fields = field_mapping.map_fields(printed, handwriting, config)
       g. page.fields = fields
       h. Log timing
       i. Optional: save diagnostic image (annotated regions)
    6. output.save_all(fields, pages, pdf_path, config)
    7. Generate summary:
       - Pages processed: N
       - Printed regions: N, avg confidence: X
       - Handwriting regions: N, avg confidence: X
       - Field mappings: N
       - Total processing time: X seconds
    8. Return PipelineResult(success=True, summary=summary, output_path=output_dir)
    """
```

#### Error Recovery Strategy

| Error | Recovery | What User Sees |
|-------|----------|----------------|
| Corrupted PDF page | Skip page, continue | Warning: "Page 3 corrupted, skipping" |
| PaddleOCR model download fails | Retry once, then fail | Error: "Model download failed, check internet" |
| TrOCR OOM | Switch to CPU | Warning: "GPU OOM, falling back to CPU (slower)" |
| Empty page | Skip (no content) | Info: "Page 5: empty, skipped" |
| No handwriting detected | Continue with empty | Info: "No handwriting found on page 2" |

#### What Happens Without an Orchestrator

- **Without orchestrator**: Modules have no coordination, no error recovery, no logging, no timing. Each run requires manual calling of individual functions.
- **Without logging**: When a run produces bad output, there's no trace of where it went wrong.
- **Without timing**: No data to optimize performance bottlenecks.
- **Without error recovery**: A single corrupted page kills the entire run.

#### Sub-Steps for Implementation

1. Create `src/pipeline.py`
2. Implement `setup_logging(config)` — file + console handlers
3. Implement `seed_everything(seed=42)` — deterministic mode
4. Implement `process_page(page, config, diag_dir=None)` — single-page pipeline
5. Implement `run_pipeline(pdf_path, config)` — full document pipeline
6. Implement `generate_summary(results, total_time)` — structured summary
7. Add `if __name__ == "__main__":` block for CLI usage:
   ```python
   python -m src.pipeline --input form.pdf --config config.yaml --output ./results
   ```
8. Add signal handlers (SIGINT = graceful shutdown, save partial results)

---

## 6. Implementation Order & Dependencies

### Dependency Graph

```
config.py      ← No dependencies (written first)
    │
    ├── pdf_ingestion.py   ← Depends on: config
    ├── preprocessing.py   ← Depends on: config
    │
    ├── layout.py          ← Depends on: config, preprocessing
    │
    ├── ocr_printed.py     ← Depends on: config, pdf_ingestion, preprocessing, layout
    ├── ocr_handwriting.py ← Depends on: config, preprocessing, layout
    │
    ├── field_mapping.py   ← Depends on: config, layout, ocr_printed, ocr_handwriting
    │
    ├── output.py          ← Depends on: config, pdf_ingestion, field_mapping
    │
    └── pipeline.py        ← Depends on: ALL
```

### Implementation Phases

| Phase | Modules | Estimated Time | Testable Result |
|-------|---------|---------------|-----------------|
| **Phase 1** | config.py, pdf_ingestion.py | 1 hour | Can load PDF, extract images & native text |
| **Phase 2** | preprocessing.py | 1 hour | Can clean up any scanned image |
| **Phase 3** | layout.py | 2 hours | Can detect printed/handwriting regions on a page |
| **Phase 4** | ocr_printed.py | 1 hour | Can extract printed text from regions |
| **Phase 5** | ocr_handwriting.py | 3 hours | Can extract handwritten text (TrOCR download time) |
| **Phase 6** | field_mapping.py | 1 hour | Can associate handwriting with field labels |
| **Phase 7** | output.py | 1 hour | Can generate all three output formats |
| **Phase 8** | pipeline.py | 1 hour | End-to-end: one command processes a PDF |
| **Phase 9** | Testing & refinement | 2 hours | Works on real-world PDFs |

### Fast-Track Sub-Steps per Phase

**Phase 1 (PDF Ingestion) — Sub-steps:**
1. `pip install PyMuPDF`
2. Write `config.py` (~20 lines)
3. Write `pdf_ingestion.py` (~80 lines)
4. Test on 3 PDFs: scanned, native, mixed

**Phase 2 (Preprocessing) — Sub-steps:**
1. `pip install opencv-python pillow numpy`
2. Write each function individually (~10 lines each)
3. Test each function with synthetic images
4. Chain into `preprocess()` and test on real scanned page

**Phase 3 (Layout) — Sub-steps:**
1. `pip install paddlepaddle paddleocr`
2. Write layout model loader (~15 lines)
3. Write region merging (~30 lines)
4. Write reading order sort (~20 lines)
5. Test on mixed page, visualize results with OpenCV drawing

**Phase 4 (Printed OCR) — Sub-steps:**
1. Write native text extractor (~20 lines)
2. Write PaddleOCR region processor (~30 lines)
3. Test on page with known printed text, compare output

**Phase 5 (Handwriting OCR) — Sub-steps:**
1. `pip install torch transformers sentencepiece`
2. Write TrOCR model loader (~20 lines)
3. Write crop + preprocess (~20 lines)
4. Write batch inference (~40 lines)
5. Write confidence proxy (~15 lines)
6. Test on page with known handwriting

**Phase 6 (Field Mapping) — Sub-steps:**
1. Write reading order sort (reuse from layout.py or extend)
2. Write candidate scorer (~30 lines)
3. Write main mapping function (~50 lines)
4. Test on multi-field form, verify associations

**Phase 7 (Output) — Sub-steps:**
1. Write JSON serializer (~40 lines)
2. Write text + bboxes serializer (~30 lines)
3. Write searchable PDF generator (~50 lines)
4. Verify each format is correct and parseable

**Phase 8 (Orchestrator) — Sub-steps:**
1. Write logging setup (~15 lines)
2. Write page processor (~40 lines)
3. Write main pipeline function (~60 lines)
4. Add CLI argument parsing
5. End-to-end test on a real form PDF

---

## 7. Edge Cases & Failure Modes

### Input-Level Edge Cases

| Edge Case | Detection | Handling |
|-----------|-----------|----------|
| Password-protected PDF | PyMuPDF raises exception | Return specific error: "PDF is encrypted" |
| Corrupted PDF | PyMuPDF fails to open or render page | Skip corrupted pages, continue with valid pages |
| 0-page PDF | len(pages) == 0 | Return early with "Empty PDF" |
| Image-only PDF (no text layer) | native_text is empty/whitespace | Treat all as scanned — full pipeline runs |
| Mixed-page PDF (some native, some scanned) | Per-page check in pdf_ingestion.py | Each page handled according to its type |
| Very long document (1000+ pages) | PyMuPDF handles it | Add page limit config option; process in chunks |

### Image-Level Edge Cases

| Edge Case | Detection | Handling |
|-----------|-----------|----------|
| Skewed page | Hough transform angle > 1° | Deskew with rotation and padding |
| Low contrast | Histogram spread < threshold | CLAHE contrast enhancement before thresholding |
| Excessive noise | NL-means denoising handles it | No explicit detection needed |
| Dark background | Mean pixel value < 128 | Invert colors before thresholding |
| Faint handwriting | Mean stroke width < threshold | Morphological dilation before OCR |
| Overlapping printed + handwriting | Layout model returns overlapping bboxes | Split region; apply both OCRs; merge by confidence |
| Handwriting on lined paper | Lines detected as printed text | Filter by line thickness; exclude from printed OCR |

### OCR-Level Edge Cases

| Edge Case | Detection | Handling |
|-----------|-----------|----------|
| Empty handwriting crop | Crop has no ink (false positive detection) | Return confidence=0, text="" |
| TrOCR generates gibberish | Check confidence < threshold | Lower confidence → flag for human review |
| PaddleOCR finds no text | Empty return | Fallback: try full-page OCR with different parameters |
| Very long text field | TrOCR max_length=64 truncates | Warn: "Text may be truncated" in metadata |
| Checkbox (no text, just ✓ or ✗) | Detected as handwriting? | If yes: map as "checked"/"unchecked" heuristic |
| Numbers vs letters confusion | TrOCR may confuse '0' vs 'O', '1' vs 'l' | Post-processing: context-based correction |

### Field Mapping Edge Cases

| Edge Case | Detection | Handling |
|-----------|-----------|----------|
| No printed regions on page | printed_regions is empty | All handwriting → unmapped |
| No handwriting regions | handwriting_regions is empty | Return printed text only |
| Multiple handwriting regions per label | Proximity within threshold | Group into list: answers: ["first", "second"] |
| Handwriting above its label (unusual layout) | Handwriting Y < label Y | Search forward in reading order (below) |
| Table: grid of fields | Regions form a grid pattern | Detect grid; cell-by-cell mapping (row × column) |
| Single-page, multi-column layout | Two columns of text | Sort by Y then X; handle as separate columns |

---

## 8. Performance Considerations

### Bottleneck Analysis

| Module | Time per Page (CPU) | Time per Page (GPU) | Bottleneck? |
|--------|--------------------|---------------------|-------------|
| pdf_ingestion | 50ms | 50ms | No |
| preprocessing | 200ms | 200ms | No (CPU-bound, fast) |
| layout (PaddleOCR) | 200ms | 100ms | No |
| printed OCR (PaddleOCR) | 500ms | 100ms | No |
| handwriting OCR (TrOCR) | 5s per region | 200ms per region | **YES** — if many regions |
| field_mapping | 10ms | 10ms | No |
| output | 100ms | 100ms | No |

**Conclusion**: Handwriting OCR with TrOCR is the bottleneck, especially on CPU. With GPU, it's manageable.

### Optimization Strategies

1. **Batch TrOCR inference**: Process 4-8 handwriting regions at once (GPU parallelism)
2. **Skip empty pages early**: Check for content before running layout/OCR
3. **Parallel page processing**: Use `multiprocessing.Pool` for pages (CPU-bound) or batch GPU (GPU-bound)
4. **Model quantization**: Convert TrOCR to FP16 (half precision) — 2x speedup, negligible accuracy loss
5. **ONNX export**: Export TrOCR to ONNX — 1.5x speedup on CPU
6. **Cache layout results**: If multiple documents have same template, cache layout detections per template

### Memory Usage

| Component | RAM (CPU) | VRAM (GPU) |
|-----------|-----------|------------|
| Python base | 100MB | — |
| Full-page image (300 DPI, A4) | 25MB | — |
| PaddleOCR model | 200MB | 200MB |
| TrOCR base model | 660MB | 660MB |
| Batch of 4 crops | 50MB | 50MB |
| **Total** | ~1GB | ~1GB |

PDFs with 100+ pages may need batching: process 10 pages at a time, release intermediates.

---

## 9. Testing Strategy

### Unit Tests

| Module | Test | What It Verifies |
|--------|------|------------------|
| pdf_ingestion | Test scanned PDF detection | is_scanned returns True/False correctly |
| pdf_ingestion | Test native text extraction | Extracted text matches expected |
| preprocessing | Test deskew | 3° rotated image returns to 0° ± 0.5° |
| preprocessing | Test denoise | Noisy image has reduced noise metrics |
| preprocessing | Test threshold | Binary image has correct ink/background separation |
| layout | Test region detection | Known printed/handwriting regions are detected |
| layout | Test reading order sort | Sorted list matches expected order |
| ocr_printed | Test native text bypass | Native PDF returns native text, not OCR |
| ocr_handwriting | Test TrOCR inference | Known handwriting image returns expected text |
| ocr_handwriting | Test confidence proxy | Confidence correlates with accuracy |
| field_mapping | Test field association | Handwriting paired with correct label |
| output | Test JSON validity | Output parses with json.load() |
| output | Test searchable PDF | PDF has searchable text layer |

### Integration Tests

| Test | Scenario | Pass Criteria |
|------|----------|---------------|
| E2E scanned form | Scanned PDF with printed text + handwriting | All printed text + handwriting extracted, field mapping correct |
| E2E native form | Digital PDF with fillable fields | Native text used for printed, handwriting from image |
| E2E mixed PDF | Multi-page with scanned + native pages | Each page handled correctly per type |
| E2E no handwriting | Printed-only document | No handwriting OCR attempted, printed text only |
| E2E no printed | Handwriting-only document | All handwriting extracted, all as "unknown_field" |

### Test Data

Create test fixtures:
- `tests/fixtures/scanned_form.pdf` — scanned A4 form with 5 filled fields
- `tests/fixtures/native_form.pdf` — digital PDF with same content
- `tests/fixtures/mixed.pdf` — 2 pages scanned, 2 pages native
- `tests/fixtures/blank.pdf` — empty page (edge case)
- `tests/fixtures/handwriting_only.png` — just handwriting (for TrOCR unit test)

---

## 10. Production Hardening

### Logging

```python
# Log format: [timestamp] [level] [module] message
# Log levels: DEBUG (per-region), INFO (per-page), WARNING, ERROR
# Log destinations: console (INFO+), file (DEBUG+)

# Example log output:
# [2026-06-22 10:30:01] [INFO] [pipeline] Processing: form.pdf
# [2026-06-22 10:30:01] [INFO] [pdf_ingestion] PDF opened: 3 pages, 2 scanned, 1 native
# [2026-06-22 10:30:02] [INFO] [layout] Page 1: 12 regions (8 printed, 3 handwriting, 1 table)
# [2026-06-22 10:30:02] [DEBUG] [ocr_handwriting] Region 3: conf=0.92, text="John Doe"
# [2026-06-22 10:30:05] [INFO] [pipeline] Page 1 processed in 3.2s
# [2026-06-22 10:30:15] [INFO] [pipeline] Total: 12.8s, 12 fields mapped
```

### Configuration via YAML

```yaml
# config.yaml — alternative to config.py for production
models_dir: /opt/models/
output_dir: /opt/output/
render_dpi: 300
trocr_model: microsoft/trocr-base-handwritten
trocr_device: cuda
trocr_batch_size: 4
crop_padding: 10
layout_confidence: 0.5
field_proximity: 50
```

### CLI Interface

```bash
# Basic usage
python -m src.pipeline --input form.pdf

# With options
python -m src.pipeline \
    --input form.pdf \
    --output ./results \
    --config config.yaml \
    --format json,searchable_pdf \
    --page-limit 10 \
    --verbose
```

### Docker Support

```dockerfile
FROM pytorch/pytorch:2.0.1-cuda11.7-cudnn8-runtime
RUN pip install paddlepaddle-gpu paddleocr PyMuPDF opencv-python-headless transformers sentencepiece
COPY src/ /app/src/
COPY models/ /app/models/
ENTRYPOINT ["python", "-m", "src.pipeline"]
```

### What This Enables

- **CI/CD**: Automated testing on every commit
- **Batch processing**: Process 1000s of PDFs overnight
- **Monitoring**: Track processing time, accuracy, failure rates
- **Scaling**: Add more GPU workers, distribute load
- **Debugging**: Diagnostic images + logs show exactly what happened

---

## Appendix: Quick Reference

### File Structure

```
ocr-extraction/
├── src/
│   ├── __init__.py
│   ├── pipeline.py           # Orchestrator (Module 9)
│   ├── pdf_ingestion.py      # PDF → images + native text (Module 2)
│   ├── preprocessing.py      # Image enhancement (Module 3)
│   ├── layout.py             # Layout analysis (Module 4)
│   ├── ocr_printed.py        # Printed text OCR (Module 5)
│   ├── ocr_handwriting.py    # Handwriting OCR with TrOCR (Module 6)
│   ├── field_mapping.py      # Field-to-answer mapping (Module 7)
│   ├── output.py             # Output formats (Module 8)
│   └── config.py             # Configuration (Module 1)
├── models/                   # Downloaded model weights
│   ├── printed/
│   └── handwriting/
├── output/                   # Results go here
│   ├── results.json
│   ├── results.txt
│   ├── results.bbox.json
│   └── searchable_output.pdf
├── tests/
│   ├── test_pdf_ingestion.py
│   ├── test_preprocessing.py
│   ├── test_layout.py
│   ├── test_ocr_printed.py
│   ├── test_ocr_handwriting.py
│   ├── test_field_mapping.py
│   ├── test_output.py
│   └── fixtures/             # Test PDFs and images
├── config.yaml               # Production config
├── requirements.txt
└── README.md
```

### Installation

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
pip install paddlepaddle paddleocr
pip install PyMuPDF opencv-python pillow numpy tqdm transformers sentencepiece

# Verify
python -c "from transformers import TrOCRProcessor; print('OK')"
python -c "from paddleocr import PaddleOCR; print('OK')"
```

### Quick Start

```python
from src.pipeline import run_pipeline

result = run_pipeline("form.pdf")
print(result.summary)
# Output: JSON in output/results.json
# Output: Searchable PDF in output/searchable_output.pdf
```

---

## Condition for Session Continuity

> **MANDATORY**: Any new session (whether continuation or new) working on this project MUST:
> 1. Read this entire document before writing any code
> 2. Follow the architecture, module structure, and implementation order defined herein
> 3. Use the technology stack specified in Section 3
> 4. Follow all edge case handling from Section 7
> 5. Implement all 9 modules in the specified dependency order (Section 6)
> 6. Write tests as specified in Section 9
> 7. Use configuration-driven design (Section 5, Module 1)
> 8. Follow the error recovery strategy (Section 5, Module 9)
> 9. Not deviate from these decisions without explicit user approval
> 10. Log all deviations from this plan for review
