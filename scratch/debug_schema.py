import sys
sys.path.insert(0, "/home/venkatanarayana/team-everest/new-ocr")
from src.datalab_schema import resolve_checkbox_marks

extracted = {
    "kitchen_type_separate": "✗",
    "kitchen_type_hall_with_kitchen": "✓",
    "house_ownership_rented": "/",
    "house_ownership_own": "✗",
}

print(resolve_checkbox_marks(extracted))
