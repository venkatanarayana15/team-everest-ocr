"""Unit tests for the extraction pipeline bbox logic and new input features."""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dataclasses import dataclass, field
from rapidfuzz import fuzz
from src.server import detect_input_type, detect_item_type, is_image, is_pdf, is_zip, extract_zip, scan_folder, IMAGE_EXTENSIONS
from src.page_classifier import PageClassifier, PageClassification
from src.datalab_schema import resolve_checkbox_marks, _validate_field_patterns, _resolve_single_checkbox_marks
from src.database import _extract_structured_fields
from src.extraction_pipeline import ExtractionPipeline, StructuredField


@dataclass
class WordBox:
    text: str
    page_num: int
    bbox: tuple[int, int, int, int]
    confidence: float


@dataclass
class TextLine:
    text: str
    bbox: tuple[int, int, int, int]
    page: int
    words: list[WordBox]


def group_words_into_lines(word_boxes: list[WordBox], page: int, y_tolerance: int = 20) -> list[TextLine]:
    page_words = sorted(
        [wb for wb in word_boxes if wb.page_num == page],
        key=lambda w: (w.bbox[1], w.bbox[0]),
    )
    if not page_words:
        return []

    lines: list[list[WordBox]] = [[page_words[0]]]
    for wb in page_words[1:]:
        prev_top = lines[-1][-1].bbox[1]
        if abs(wb.bbox[1] - prev_top) < y_tolerance:
            lines[-1].append(wb)
        else:
            lines.append([wb])

    result: list[TextLine] = []
    for group in lines:
        xs = [w.bbox[0] for w in group]
        ys = [w.bbox[1] for w in group]
        xe = [w.bbox[2] for w in group]
        ye = [w.bbox[3] for w in group]
        result.append(TextLine(
            text=" ".join(w.text for w in group),
            bbox=(min(xs), min(ys), max(xe), max(ye)),
            page=page,
            words=group,
        ))
    return result


def find_value_bbox(value_lower: str, best_line: TextLine, lines: list[TextLine], position_hint: str | None = None):
    if position_hint == "above_label":
        best_idx = lines.index(best_line)
        for candidate in reversed(lines[:best_idx]):
            if best_line.bbox[1] - candidate.bbox[3] > 40:
                break
            if value_lower and fuzz.partial_ratio(value_lower, candidate.text.lower()) > 50:
                return candidate.bbox
            return candidate.bbox
        return best_line.bbox

    if position_hint == "below_label":
        best_idx = lines.index(best_line)
        for candidate in lines[best_idx + 1:]:
            if candidate.bbox[1] - best_line.bbox[3] > 40:
                break
            if value_lower and fuzz.partial_ratio(value_lower, candidate.text.lower()) > 50:
                return candidate.bbox
            return candidate.bbox
        return best_line.bbox

    if position_hint in ("same_line_colon", "right_of_label"):
        colon_idx = best_line.text.find(":")
        if colon_idx >= 0:
            colon_word = None
            char_count = 0
            for wb in best_line.words:
                word_end = char_count + len(wb.text)
                if char_count <= colon_idx < word_end:
                    colon_word = wb
                    break
                char_count = word_end + 1
            if colon_word and len(best_line.words) > 1:
                right_words = [wb for wb in best_line.words if wb.bbox[0] > colon_word.bbox[0]]
                if right_words:
                    xs = [w.bbox[0] for w in right_words]
                    ys = [w.bbox[1] for w in right_words]
                    xe = [w.bbox[2] for w in right_words]
                    ye = [w.bbox[3] for w in right_words]
                    return (min(xs), min(ys), max(xe), max(ye))

        if value_lower:
            mid_x = (best_line.bbox[0] + best_line.bbox[2]) / 2
            right_words = [wb for wb in best_line.words if wb.bbox[0] > mid_x]
            if right_words:
                xs = [w.bbox[0] for w in right_words]
                ys = [w.bbox[1] for w in right_words]
                xe = [w.bbox[2] for w in right_words]
                ye = [w.bbox[3] for w in right_words]
                return (min(xs), min(ys), max(xe), max(ye))
        return best_line.bbox

    # No position_hint — try all strategies
    if value_lower:
        value_words: list[tuple[float, WordBox]] = []
        for wb in best_line.words:
            wl = wb.text.lower()
            if fuzz.partial_ratio(value_lower, wl) > 75 or fuzz.partial_ratio(wl, value_lower) > 75:
                weight = wb.confidence / 100.0 if wb.confidence > 60 else 0.5
                value_words.append((weight, wb))
        if value_words:
            value_words.sort(key=lambda x: x[0], reverse=True)
            chosen = [vw[1] for vw in value_words[:3]]
            xs = [w.bbox[0] for w in chosen]
            ys = [w.bbox[1] for w in chosen]
            xe = [w.bbox[2] for w in chosen]
            ye = [w.bbox[3] for w in chosen]
            return (min(xs), min(ys), max(xe), max(ye))

    colon_idx = best_line.text.find(":")
    if colon_idx >= 0:
        colon_word = None
        char_count = 0
        for wb in best_line.words:
            word_end = char_count + len(wb.text)
            if char_count <= colon_idx < word_end:
                colon_word = wb
                break
            char_count = word_end + 1
        if colon_word and len(best_line.words) > 1:
            right_words = [wb for wb in best_line.words if wb.bbox[0] > colon_word.bbox[0]]
            if right_words:
                xs = [w.bbox[0] for w in right_words]
                ys = [w.bbox[1] for w in right_words]
                xe = [w.bbox[2] for w in right_words]
                ye = [w.bbox[3] for w in right_words]
                return (min(xs), min(ys), max(xe), max(ye))

    best_idx = lines.index(best_line)
    for candidate in lines[best_idx + 1:]:
        if candidate.bbox[1] - best_line.bbox[3] > 40:
            break
        if value_lower and fuzz.partial_ratio(value_lower, candidate.text.lower()) > 50:
            return candidate.bbox
        return candidate.bbox

    return best_line.bbox


def find_field_bboxes(value: str, label: str, lines: list[TextLine], position_hint: str | None = None):
    if not lines:
        return None, None

    label_lower = label.lower().strip()
    best: tuple[float, TextLine] | None = None
    for line in lines:
        ratio = fuzz.token_set_ratio(label_lower, line.text.lower())
        if ratio > 65 and (best is None or ratio > best[0]):
            best = (ratio, line)

    if best is None:
        return None, None

    _, best_line = best
    label_bbox = best_line.bbox
    value_lower = value.lower().strip()

    value_bbox = find_value_bbox(value_lower, best_line, lines, position_hint)

    return label_bbox, value_bbox


# ═══════════════════ Tests ═══════════════════

def test_group_words_into_lines():
    wbs = [
        WordBox(text="Hello", page_num=1, bbox=(0, 0, 40, 20), confidence=95),
        WordBox(text="World", page_num=1, bbox=(45, 0, 90, 20), confidence=95),
        WordBox(text="Next", page_num=1, bbox=(0, 30, 35, 50), confidence=95),
    ]
    lines = group_words_into_lines(wbs, 1)
    assert len(lines) == 2, f"expected 2 lines got {len(lines)}"
    assert lines[0].text == "Hello World"
    assert lines[1].text == "Next"
    assert lines[0].bbox == (0, 0, 90, 20)
    assert lines[1].bbox == (0, 30, 35, 50)
    print("PASS: test_group_words_into_lines")


def test_find_field_bboxes_label_match():
    # Use labels that appear verbatim on page for reliable token_set_ratio match
    wb1 = WordBox(text="Date", page_num=1, bbox=(10, 10, 40, 30), confidence=90)
    wb2 = WordBox(text="2024-01-01", page_num=1, bbox=(50, 10, 110, 30), confidence=90)
    wb3 = WordBox(text="Name:", page_num=1, bbox=(10, 40, 50, 60), confidence=90)
    wb4 = WordBox(text="John", page_num=1, bbox=(55, 40, 85, 60), confidence=90)

    lines = group_words_into_lines([wb1, wb2, wb3, wb4], 1)

    label_bbox, value_bbox = find_field_bboxes("2024-01-01", "Date", lines)
    assert label_bbox == (10, 10, 110, 30), f"label_bbox got {label_bbox}"
    # Value should be right of colon for Name: John
    label_bbox2, value_bbox2 = find_field_bboxes("John", "Name:", lines)
    assert label_bbox2 == (10, 40, 85, 60), f"label_bbox2 got {label_bbox2}"
    assert value_bbox2 is not None
    assert value_bbox2[0] > 50, f"value_bbox2 left should be > 50, got {value_bbox2[0]}"
    print(f"PASS: test_find_field_bboxes_label_match  label={label_bbox}/{label_bbox2} value={value_bbox}/{value_bbox2}")


def test_find_field_bboxes_no_match():
    lines = [
        TextLine(text="Something", bbox=(0, 0, 50, 20), page=1, words=[
            WordBox(text="Something", page_num=1, bbox=(0, 0, 50, 20), confidence=90),
        ]),
    ]
    label_bbox, value_bbox = find_field_bboxes("nothing", "NonExistent", lines)
    assert label_bbox is None
    assert value_bbox is None
    print("PASS: test_find_field_bboxes_no_match")


def test_find_field_bboxes_empty_lines():
    label_bbox, value_bbox = find_field_bboxes("x", "y", [])
    assert label_bbox is None
    assert value_bbox is None
    print("PASS: test_find_field_bboxes_empty_lines")


def test_find_value_bbox_colon_split():
    wb_label = WordBox(text="Name:", page_num=1, bbox=(10, 10, 50, 30), confidence=90)
    wb_val = WordBox(text="John", page_num=1, bbox=(55, 10, 90, 30), confidence=90)
    line = TextLine(text="Name: John", bbox=(10, 10, 90, 30), page=1, words=[wb_label, wb_val])
    lines = [line]

    vb = find_value_bbox("john", line, lines)
    assert vb is not None
    # Should be the right-of-colon words
    lefts = [w.bbox[0] for w in line.words if w.bbox[0] > wb_label.bbox[0]]
    assert vb[0] == min(lefts), f"value_bbox left should be {min(lefts)} got {vb[0]}"
    print(f"PASS: test_find_value_bbox_colon_split  value_bbox={vb}")


def test_find_value_bbox_below_label():
    label_line = TextLine(text="Address:", bbox=(10, 10, 70, 30), page=1, words=[
        WordBox(text="Address:", page_num=1, bbox=(10, 10, 70, 30), confidence=90),
    ])
    val_line = TextLine(text="123 Main St", bbox=(10, 40, 100, 60), page=1, words=[
        WordBox(text="123", page_num=1, bbox=(10, 40, 35, 60), confidence=90),
        WordBox(text="Main", page_num=1, bbox=(40, 40, 70, 60), confidence=90),
        WordBox(text="St", page_num=1, bbox=(75, 40, 100, 60), confidence=90),
    ])
    lines = [label_line, val_line]

    vb = find_value_bbox("123 main st", label_line, lines, position_hint="below_label")
    assert vb == val_line.bbox, f"expected {val_line.bbox} got {vb}"
    print(f"PASS: test_find_value_bbox_below_label  value_bbox={vb}")


def test_find_value_bbox_fallback_to_label():
    line = TextLine(text="JustLabel", bbox=(10, 10, 80, 30), page=1, words=[
        WordBox(text="JustLabel", page_num=1, bbox=(10, 10, 80, 30), confidence=90),
    ])
    lines = [line]

    vb = find_value_bbox("", line, lines)
    assert vb == line.bbox, f"expected {line.bbox} got {vb}"
    print("PASS: test_find_value_bbox_fallback_to_label")


def test_structured_field_json_roundtrip():
    """Simulate the server JSON serialization/deserialization of a field with section_number and value_bbox."""
    field_dict = {
        "label": "Name",
        "value": "John",
        "confidence": 85,
        "page": 1,
        "section_number": 1,
        "bbox": [10, 10, 50, 30],
        "value_bbox": [60, 10, 120, 30],
        "needs_clarification": False,
        "reason": None,
        "is_verified": True,
        "verifier_confidence": 90,
        "verification_note": None,
        "extracted_by": "Gemini",
        "verified_by": "GPT",
        "original_value": None,
    }
    serialized = json.dumps(field_dict)
    deserialized = json.loads(serialized)
    assert deserialized["section_number"] == 1
    assert deserialized["bbox"] == [10, 10, 50, 30]
    assert deserialized["value_bbox"] == [60, 10, 120, 30]
    assert deserialized["label"] == "Name"
    print("PASS: test_structured_field_json_roundtrip")


def test_extract_structured_fields_llm_format():
    """Regression: LLM label format (hyphen separators, '(tick all that apply)',
    flat single-row tables, Yes/No checkbox pairs, single-select groups) must
    persist to DB columns instead of being silently dropped."""
    fields = [
        {"label": "Volunteer Name", "value": "M. Riaz"},
        {"label": "1.3 Gender", "value": "Male"},
        {"label": "3.1 House Ownership — Own", "value": "Yes"},
        {"label": "3.1 House Ownership — Rented", "value": "No"},
        {"label": "3.4.1 Type of Bedroom — Separate Bedroom", "value": "No"},
        {"label": "3.4.1 Type of Bedroom — No Separate Bedroom", "value": "Yes"},
        {"label": "3.5 Bathroom - Separate", "value": "Yes"},
        {"label": "3.5 Bathroom - Common for Apartment", "value": "No"},
        {"label": "3.6 Kitchen Type — Separate Kitchen", "value": "No"},
        {"label": "3.6 Kitchen Type — Hall with Kitchen", "value": "Yes"},
        {"label": "4.1 Assets at Home(tick all that apply) - Fridge", "value": "Yes"},
        {"label": "4.1 Assets at Home(tick all that apply) - Car", "value": "No"},
        {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes", "value": "No"},
        {"label": "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No", "value": "Yes"},
        {"label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Loan Purpose", "value": "Gold loan"},
        {"label": "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Loan Amount Taken", "value": "10 Lakh"},
    ]
    out = _extract_structured_fields(fields)
    assert out["volunteer_name"] == "M. Riaz"
    assert out["gender"] == "Male"
    assert out["house_ownership"] == "Own"
    assert out["type_of_bedroom"] == "No Separate Bedroom"
    assert out["bathroom"] == "Separate"
    assert out["kitchen_type"] == "Hall with Kitchen"
    assert json.loads(out["assets_at_home"]) == ["Fridge"]
    assert out["owns_other_assets"] == "No"
    loans = json.loads(out["loan_details"])
    assert loans[0]["Loan Purpose"] == "Gold loan"
    assert loans[0]["Loan Amount Taken"] == "10 Lakh"
    print("PASS: test_extract_structured_fields_llm_format")


def test_extract_structured_fields_datalab_format():
    """Datalab label format (em-dash separators, '— Row {n} —' tables, scalar
    group values) must continue to map correctly."""
    fields = [
        {"label": "3.5 Bathroom", "value": "Common for Apartment"},
        {"label": "3.1 House Ownership", "value": "Rented"},
        {"label": "4.1 Assets at Home", "value": "Fridge, LED TV"},
        {"label": "2.5 Family Members — Row 1 — Name", "value": "Ravi"},
        {"label": "2.5 Family Members — Row 1 — Age", "value": "45"},
        {"label": "4.3.1 — Row 1 — Property Description", "value": "Land"},
        {"label": "2.4 Government ID Verified — Aadhaar Card", "value": "Yes"},
    ]
    out = _extract_structured_fields(fields)
    assert out["bathroom"] == "Common for Apartment"
    assert out["house_ownership"] == "Rented"
    assert json.loads(out["assets_at_home"]) == ["Fridge", "LED TV"]
    assert json.loads(out["family_members"])[0] == {"Age": "45", "Name": "Ravi"}
    assert json.loads(out["other_assets_details"])[0]["Property Description"] == "Land"
    assert json.loads(out["government_id_verified"]) == ["Aadhaar Card"]
    print("PASS: test_extract_structured_fields_datalab_format")


def test_extract_structured_fields_dash_separators():
    """Label format (double-hyphen -- separators) and
    'Other (specify)' text field must both work correctly."""
    fields = [
        {"label": "2.4 Government ID Verified -- Aadhaar Card", "value": "Yes"},
        {"label": "2.4 Government ID Verified -- Ration Card", "value": "No"},
        {"label": "2.4 Government ID Verified -- Driving Licence", "value": "Yes"},
        {"label": "2.4 Government ID Verified -- Other", "value": ""},
        {"label": "2.4 Government ID Verified -- Other (specify)", "value": "Pan Card"},
        {"label": "3.2 Type of Home -- Individual", "value": "Yes"},
        {"label": "3.2 Type of Home -- Private Apartment", "value": "No"},
        {"label": "3.2 Type of Home -- Line House", "value": "Yes"},
        {"label": "3.3 Type of Ceiling -- Roof (Kurai)", "value": "No"},
        {"label": "3.3 Type of Ceiling -- Concrete", "value": "Yes"},
        {"label": "3.1 House Ownership -- Own", "value": "No"},
        {"label": "3.1 House Ownership -- Rented", "value": "Yes"},
        {"label": "4.1 Assets at Home(tick all that apply) - Washing Machine", "value": "Yes"},
        {"label": "4.1 Assets at Home(tick all that apply) - Car", "value": "No"},
    ]
    out = _extract_structured_fields(fields)
    # 2.4: Aadhaar+Driving checked, Other with text → "Other" included
    govt = json.loads(out["government_id_verified"])
    assert "Aadhaar Card" in govt
    assert "Driving Licence" in govt
    assert "Other: Pan Card" in govt
    assert "Other" not in govt
    assert "Ration Card" not in govt
    # 3.2: Individual + Line House checked
    home = json.loads(out["type_of_home"])
    assert "Individual" in home
    assert "Line House" in home
    assert "Private Apartment" not in home
    # 3.3: Concrete checked
    ceil = json.loads(out["type_of_ceiling"])
    assert "Concrete" in ceil
    assert "Roof (Kurai)" not in ceil
    # 3.1: Rented checked
    assert out["house_ownership"] == "Rented"
    # 4.1: Washing Machine checked
    assets = json.loads(out["assets_at_home"])
    assert "Washing Machine" in assets
    assert "Car" not in assets
    print("PASS: test_extract_structured_fields_dash_separators")


def test_extract_structured_fields_other_specify_no_text():
    """When 'Other (specify)' is empty, 'Other' must NOT be in the checked array."""
    fields = [
        {"label": "2.4 Government ID Verified -- Aadhaar Card", "value": "Yes"},
        {"label": "2.4 Government ID Verified -- Other", "value": ""},
        {"label": "2.4 Government ID Verified -- Other (specify)", "value": ""},
    ]
    out = _extract_structured_fields(fields)
    govt = json.loads(out["government_id_verified"])
    assert govt == ["Aadhaar Card"]
    print("PASS: test_extract_structured_fields_other_specify_no_text")


def test_extract_structured_fields_other_checked_no_text():
    """When 'Other' checkbox is ticked, it must be in array regardless of specify text."""
    fields = [
        {"label": "2.4 Government ID Verified -- Other", "value": "Yes"},
        {"label": "2.4 Government ID Verified -- Other (specify)", "value": ""},
    ]
    out = _extract_structured_fields(fields)
    govt = json.loads(out["government_id_verified"])
    assert govt == ["Other"]
    print("PASS: test_extract_structured_fields_other_checked_no_text")


# ═══════════════════ Input Handler Tests ═══════════════════

def test_is_image():
    assert is_image("photo.jpg")
    assert is_image("photo.jpeg")
    assert is_image("photo.png")
    assert is_image("photo.tiff")
    assert is_image("photo.tif")
    assert not is_image("doc.pdf")
    assert not is_image("archive.zip")
    print("PASS: test_is_image")


def test_is_pdf():
    assert is_pdf("doc.pdf")
    assert not is_pdf("photo.jpg")
    assert not is_pdf("archive.zip")
    print("PASS: test_is_pdf")


def test_is_zip():
    assert is_zip("archive.zip")
    assert not is_zip("doc.pdf")
    assert not is_zip("photo.jpg")
    print("PASS: test_is_zip")


def test_detect_input_type_pdf():
    assert detect_input_type(["doc.pdf"]) == "pdf"
    assert detect_input_type(["a.pdf", "b.pdf"]) == "pdf_set"
    print("PASS: test_detect_input_type_pdf")


def test_detect_input_type_image_set():
    assert detect_input_type(["page1.jpg", "page2.jpg", "page3.jpg"]) == "image_set"
    assert detect_input_type(["img1.png", "img2.jpeg", "img3.tiff"]) == "image_set"
    print("PASS: test_detect_input_type_image_set")


def test_detect_input_type_zip():
    assert detect_input_type(["images.zip"]) == "zip"
    print("PASS: test_detect_input_type_zip")


def test_detect_input_type_mixed():
    result = detect_input_type(["doc.pdf", "img1.jpg", "img2.jpg"])
    assert result == "mixed"
    print("PASS: test_detect_input_type_mixed")


def test_detect_input_type_unknown():
    assert detect_input_type(["notes.txt"]) == "unknown"
    print("PASS: test_detect_input_type_unknown")


def test_detect_item_type_pdf():
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(b"%PDF-1.4 mock")
        path = f.name
    try:
        assert detect_item_type(path) == "pdf"
    finally:
        os.unlink(path)
    print("PASS: test_detect_item_type_pdf")


def test_extract_zip():
    import zipfile
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as f:
        zip_path = f.name
    try:
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("page1.jpg", b"fake image data")
            zf.writestr("page2.png", b"fake png data")
            zf.writestr("notes.txt", b"not an image")
            zf.writestr("sub/page3.jpeg", b"nested image")
        out_dir = tempfile.mkdtemp()
        paths = extract_zip(zip_path, out_dir)
        assert len(paths) >= 3
        assert any("page1.jpg" in p for p in paths)
        assert any("page2.png" in p for p in paths)
        assert any("page3.jpeg" in p for p in paths)
        assert not any("notes.txt" in p for p in paths)
    finally:
        os.unlink(zip_path)
    print("PASS: test_extract_zip")


def test_scan_folder():
    with tempfile.TemporaryDirectory() as tmpdir:
        Path(tmpdir, "doc1.pdf").write_text("%PDF mock")
        Path(tmpdir, "doc2.pdf").write_text("%PDF mock")
        img_set = Path(tmpdir, "image_set_vol1")
        img_set.mkdir()
        for i in range(1, 7):
            Path(img_set, f"page{i}.jpg").write_text("fake")
        items = scan_folder(tmpdir)
        assert len(items) == 3
        pdfs = [i for i in items if i["type"] == "pdf"]
        img_sets = [i for i in items if i["type"] == "image_set"]
        assert len(pdfs) == 2
        assert len(img_sets) == 1
        assert len(img_sets[0]["images"]) == 6
    print("PASS: test_scan_folder")


# ═══════════════════ Page Classifier Tests ═══════════════════

def test_classify_from_text_page1():
    classifier = PageClassifier()
    text = "Volunteer Name: John\nCo-Volunteer Name: Jane\nDate of Visit: 2024-01-01\n1.1 Application ID: APP001\n1.2 Student Full Name: Bob\nGender: Male\nFamily Status: Having both parents"
    result = classifier.classify_from_text(text)
    assert result.page_number == 1
    assert result.confidence > 50
    assert not result.blank
    assert not result.unreadable
    print(f"PASS: test_classify_from_text_page1 → page={result.page_number}, conf={result.confidence}")


def test_classify_from_text_page2():
    classifier = PageClassifier()
    text = "2.3 Is Father/Mother photograph kept at home?\n2.4 Government ID Verified: Aadhaar Card\nHouse Ownership: Own\nType of Home: Individual"
    result = classifier.classify_from_text(text)
    assert result.page_number == 2
    assert result.confidence > 50
    print(f"PASS: test_classify_from_text_page2 → page={result.page_number}, conf={result.confidence}")


def test_classify_from_text_page3():
    classifier = PageClassifier()
    text = "3.3 Type of Ceiling: Roof\n3.4 Number of Bedrooms: 2\nBathroom: Separate\nKitchen Type: Separate Kitchen\n4.1 Assets at Home: Washing Machine\n4.2 Amount of Last Electricity Bill: 1500"
    result = classifier.classify_from_text(text)
    assert result.page_number == 3
    assert result.confidence > 50
    print(f"PASS: test_classify_from_text_page3 → page={result.page_number}, conf={result.confidence}")


def test_classify_from_text_page4():
    classifier = PageClassifier()
    text = "4.4 Apart from your job, is there any other source of income?\nIncome Type: Monthly\n4.6 Do you have any loans?\nLoan Purpose: Education\n4.7 If you choose any college, how much is the college fee?"
    result = classifier.classify_from_text(text)
    assert result.page_number == 4
    assert result.confidence > 50
    print(f"PASS: test_classify_from_text_page4 → page={result.page_number}, conf={result.confidence}")


def test_classify_from_text_page5():
    classifier = PageClassifier()
    text = "5.1 Does the student have any health issues?\n5.2 If yes, list the health issues: N/A\n6.1 Will you study college for three years without any obstacle?\n6.2 If we have a training program within 15 km from your home, can you come?\n6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays?"
    result = classifier.classify_from_text(text)
    assert result.page_number == 5
    assert result.confidence > 50
    print(f"PASS: test_classify_from_text_page5 → page={result.page_number}, conf={result.confidence}")


def test_classify_from_text_page6():
    classifier = PageClassifier()
    text = "7.1 Has the student received or applied for any other scholarships for their UG degree?\n8.1 What is your opinion about the student, their family members, and their living condition?\n8.2 Will you recommend this student for this scholarship?\nVolunteer Observation"
    result = classifier.classify_from_text(text)
    assert result.page_number == 6
    assert result.confidence > 50
    print(f"PASS: test_classify_from_text_page6 → page={result.page_number}, conf={result.confidence}")


def test_classify_blank_page():
    classifier = PageClassifier()
    result = classifier.classify_from_text("")
    assert result.blank
    assert result.page_number == 0
    print("PASS: test_classify_blank_page")


def test_classify_gibberish():
    classifier = PageClassifier()
    result = classifier.classify_from_text("asdfghjkl qwertyuiop zxcvbnm 1234567890 !@#$%^&*()")
    # Should be classified as unreadable (no template match)
    assert result.unreadable or result.page_number == 0
    print(f"PASS: test_classify_gibberish → unreadable={result.unreadable}")


def test_resolve_order_simple():
    classifier = PageClassifier()
    classifications = {
        0: PageClassification(page_number=1, confidence=90.0, matched_keywords=["Volunteer Name"], matched_sections=["Student Profile"]),
        1: PageClassification(page_number=2, confidence=85.0, matched_keywords=["Family Members"], matched_sections=["Family Background"]),
        2: PageClassification(page_number=3, confidence=88.0, matched_keywords=["Type of Ceiling"], matched_sections=["Housing Condition"]),
        3: PageClassification(page_number=4, confidence=82.0, matched_keywords=["Income Type"], matched_sections=["Financial Background"]),
        4: PageClassification(page_number=5, confidence=80.0, matched_keywords=["health issues"], matched_sections=["Health Information"]),
        5: PageClassification(page_number=6, confidence=86.0, matched_keywords=["other scholarships"], matched_sections=["Volunteer Observation"]),
    }
    page_map, validation = classifier.resolve_order(classifications)
    assert len(page_map) == 6
    assert page_map[1] == 0
    assert page_map[2] == 1
    assert page_map[3] == 2
    assert page_map[4] == 3
    assert page_map[5] == 4
    assert page_map[6] == 5
    assert not validation.get("has_missing")
    assert not validation.get("has_duplicates")
    print(f"PASS: test_resolve_order_simple → {page_map}")


def test_resolve_order_shuffled():
    """Test that shuffled images get correctly reordered."""
    classifier = PageClassifier()
    classifications = {
        0: PageClassification(page_number=5, confidence=80.0, matched_keywords=["health issues"], matched_sections=["Health Information"]),
        1: PageClassification(page_number=2, confidence=85.0, matched_keywords=["Family Members"], matched_sections=["Family Background"]),
        2: PageClassification(page_number=1, confidence=90.0, matched_keywords=["Volunteer Name"], matched_sections=["Student Profile"]),
        3: PageClassification(page_number=6, confidence=86.0, matched_keywords=["other scholarships"], matched_sections=["Volunteer Observation"]),
        4: PageClassification(page_number=3, confidence=88.0, matched_keywords=["Type of Ceiling"], matched_sections=["Housing Condition"]),
        5: PageClassification(page_number=4, confidence=82.0, matched_keywords=["Income Type"], matched_sections=["Financial Background"]),
    }
    page_map, validation = classifier.resolve_order(classifications)
    assert len(page_map) == 6
    assert page_map[1] == 2
    assert page_map[2] == 1
    assert page_map[3] == 4
    assert page_map[4] == 5
    assert page_map[5] == 0
    assert page_map[6] == 3
    assert not validation.get("has_missing")
    assert not validation.get("has_duplicates")
    print(f"PASS: test_resolve_order_shuffled → {page_map}")


def test_resolve_order_missing_page():
    """Test that missing pages are detected."""
    classifier = PageClassifier()
    classifications = {
        0: PageClassification(page_number=1, confidence=90.0, matched_keywords=[], matched_sections=[]),
        1: PageClassification(page_number=2, confidence=85.0, matched_keywords=[], matched_sections=[]),
        2: PageClassification(page_number=4, confidence=88.0, matched_keywords=[], matched_sections=[]),
        3: PageClassification(page_number=5, confidence=82.0, matched_keywords=[], matched_sections=[]),
    }
    page_map, validation = classifier.resolve_order(classifications)
    assert validation.get("has_missing")
    assert 3 in validation.get("missing_pages", [])
    assert 6 in validation.get("missing_pages", [])
    print(f"PASS: test_resolve_order_missing_page → missing={validation.get('missing_pages')}")


def test_docstring_inference():
    """Verify import works for User Story documentation references."""
    assert hasattr(PageClassifier, "classify_from_text")
    assert hasattr(PageClassifier, "resolve_order")
    print("PASS: test_docstring_inference")


def test_gemini_post_process_4_3_blank_merge():
    """Free-text below 4.3 (Zone A) and below the 4.3.1 table (Zone B) must be
    appended as extra 4.3.1 Property Description rows, and the helpers cleared."""
    fields = [
        StructuredField(label="4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes", value="Yes", page=3, section_number=4),
        StructuredField(label="4.3.1 If Yes, list their properties: — Row 1 — Property Description", value="Land", page=4, section_number=4),
        StructuredField(label="4.3.1 If Yes, list their properties: — Row 1 — Owner Name", value="Father", page=4, section_number=4),
        StructuredField(label="4.3.1 If Yes, list their properties: — Row 2 — Property Description", value="House", page=4, section_number=4),
        StructuredField(label="blank_text_below_4_3", value="grandparents asset", page=3, section_number=4),
        StructuredField(label="blank_text_below_4_3_1_table", value="no chance of getting share from brother", page=4, section_number=4),
    ]
    out = ExtractionPipeline._gemini_post_process(fields)

    prop_rows = [f for f in out if f.label.endswith("— Property Description")]
    # 2 printed + 2 free-text zones = 4 rows
    assert len(prop_rows) == 4, [f.label for f in prop_rows]
    texts = [f.value for f in prop_rows]
    assert "grandparents asset" in texts
    assert "no chance of getting share from brother" in texts

    # Helpers cleared
    helpers = [f for f in out if f.label in ("blank_text_below_4_3", "blank_text_below_4_3_1_table")]
    assert all(f.value == "" for f in helpers), [f.value for f in helpers]

    # New rows tagged page 4, section 4
    new_rows = [f for f in out if "Row 3" in f.label or "Row 4" in f.label]
    assert all(f.page == 4 and f.section_number == 4 for f in new_rows)
    print("PASS: test_gemini_post_process_4_3_blank_merge")


def test_resolve_checkbox_marks():
    extracted = {
        "kitchen_type_separate_mark": "✗",
        "kitchen_type_hall_mark": "✓",
        "house_ownership_rented_mark": "/",
        "house_ownership_own_mark": "✗",
    }
    resolved, ambiguous = resolve_checkbox_marks(extracted)
    assert resolved.get("kitchen_type") == "Hall with Kitchen"
    assert resolved.get("house_ownership") == "Rented"
    assert len(ambiguous) == 0

    # Ambiguous test
    ambiguous_extracted = {
        "kitchen_type_separate_mark": "✓",
        "kitchen_type_hall_mark": "/",
    }
    resolved_ambig, ambiguous_fields = resolve_checkbox_marks(ambiguous_extracted)
    assert "kitchen_type" in ambiguous_fields
    print("PASS: test_resolve_checkbox_marks")

def test_validate_field_patterns():
    extracted = {
        "volunteer_name": "APP-2024-1234",
        "application_id": "John Doe",
    }
    validated = _validate_field_patterns(extracted)
    assert validated.get("volunteer_name") == "John Doe"
    assert validated.get("application_id") == "APP-2024-1234"
    print("PASS: test_validate_field_patterns")


def test_resolve_single_checkbox_marks():
    # Tick → "✓"
    tick_input = {"asset_washing_machine": "tick"}
    _resolve_single_checkbox_marks(tick_input)
    assert tick_input["asset_washing_machine"] == "✓"

    # Slash → "✓"
    slash_input = {"govt_id_aadhaar": "slash"}
    _resolve_single_checkbox_marks(slash_input)
    assert slash_input["govt_id_aadhaar"] == "✓"

    # Cross → None
    cross_input = {"ceiling_roof": "cross"}
    _resolve_single_checkbox_marks(cross_input)
    assert cross_input["ceiling_roof"] is None

    # Empty → None
    empty_input = {"home_type_individual": "empty"}
    _resolve_single_checkbox_marks(empty_input)
    assert empty_input["home_type_individual"] is None

    # None → unchanged (not in extracted dict)
    none_input = {}
    _resolve_single_checkbox_marks(none_input)
    assert len(none_input) == 0

    # Unknown → unchanged
    unknown_input = {"asset_fridge": "unclear_mark"}
    _resolve_single_checkbox_marks(unknown_input)
    assert unknown_input["asset_fridge"] == "unclear_mark"

    # Not in _SINGLE_CHECKBOX_KEYS → unchanged
    other_input = {"volunteer_name": "tick"}
    _resolve_single_checkbox_marks(other_input)
    assert other_input["volunteer_name"] == "tick"

    print("PASS: test_resolve_single_checkbox_marks")


if __name__ == "__main__":
    # Schema tests
    test_resolve_checkbox_marks()
    test_validate_field_patterns()
    test_resolve_single_checkbox_marks()
    
    # Existing bbox tests
    test_group_words_into_lines()
    test_find_field_bboxes_label_match()
    test_find_field_bboxes_no_match()
    test_find_field_bboxes_empty_lines()
    test_find_value_bbox_colon_split()
    test_find_value_bbox_below_label()
    test_find_value_bbox_fallback_to_label()
    test_structured_field_json_roundtrip()
    test_extract_structured_fields_llm_format()
    test_extract_structured_fields_datalab_format()
    # New input handler tests
    test_is_image()
    test_is_pdf()
    test_is_zip()
    test_detect_input_type_pdf()
    test_detect_input_type_image_set()
    test_detect_input_type_zip()
    test_detect_input_type_mixed()
    test_detect_input_type_unknown()
    test_detect_item_type_pdf()
    test_extract_zip()
    test_scan_folder()
    # Label format regression tests (dash/em-dash separators)
    test_extract_structured_fields_dash_separators()
    test_extract_structured_fields_other_specify_no_text()
    test_extract_structured_fields_other_checked_no_text()
    # New page classifier tests
    test_classify_from_text_page1()
    test_classify_from_text_page2()
    test_classify_from_text_page3()
    test_classify_from_text_page4()
    test_classify_from_text_page5()
    test_classify_from_text_page6()
    test_classify_blank_page()
    test_classify_gibberish()
    test_resolve_order_simple()
    test_resolve_order_shuffled()
    test_resolve_order_missing_page()
    test_docstring_inference()
    test_gemini_post_process_4_3_blank_merge()
    print("\n=== All tests passed! ===")
