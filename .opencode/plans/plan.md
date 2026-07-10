# Fix 4.1 assets checkbox extraction

**Problem**: 4.1 asset fields are `"type": "string"` in EXTRACT_SCHEMA. Datalab normalizes ALL filled checkbox marks to `"✓"` in string fields — cannot distinguish `/` (tick/has) from `x` (cross/doesn't have).

**Root cause**: All other checkbox fields (2.4, 3.1, 3.2, 3.3, 3.4.1, 3.6, 4.3) use `"type": "boolean"` and correctly distinguish `/` from `x`. Only 4.1 assets use `"type": "string"`.

**Fix**: Change 8 asset fields from `"type": "string"` to `"type": "boolean"`, same as every other checkbox on the form.

## Changes

### 1. `src/datalab_schema.py` — EXTRACT_SCHEMA (lines 78-86)

Change these 8 fields:
```python
# Before (all type: string with verbose descriptions):
"asset_washing_machine": {"type": "string", "description": "4.1 Assets at Home — Washing Machine. Return '✓' if the checkbox is ticked/checked. Return 'x' or '✗' if crossed or an. Leave empty if blank."},
"asset_fridge": {"type": "string", "description": "4.1 Assets at Home — Fridge. Return '✓' if the checkbox is ticked/checked. Return 'x' or '✗' if crossed. Leave empty if blank."},
... (same pattern for ac, led_tv, two_wheeler, car, smartphone, separate_wifi)

# After (all type: boolean with short descriptions):
"asset_washing_machine": {"type": "boolean", "description": "4.1 Assets at Home — Washing Machine (checkbox)"},
"asset_fridge": {"type": "boolean", "description": "4.1 Assets at Home — Fridge (checkbox)"},
"asset_ac": {"type": "boolean", "description": "4.1 Assets at Home — AC (checkbox)"},
"asset_led_tv": {"type": "boolean", "description": "4.1 Assets at Home — LED TV (checkbox)"},
"asset_two_wheeler": {"type": "boolean", "description": "4.1 Assets at Home — Two-Wheeler (checkbox)"},
"asset_car": {"type": "boolean", "description": "4.1 Assets at Home — Car (checkbox)"},
"asset_smartphone": {"type": "boolean", "description": "4.1 Assets at Home — Smartphone (checkbox)"},
"asset_separate_wifi": {"type": "boolean", "description": "4.1 Assets at Home — Separate Wi-Fi (checkbox)"},
```

Keep `asset_others` as `"type": "string"` (needs to capture free text).

### 2. `src/datalab_schema.py` — Remove dead code

Delete these blocks (unused after removing markdown parsing approach):

- **`ASSET_MARKDOWN_PATTERNS`** dict (lines 243-253)
- **`_interpret_bracket()`** function (lines 256-266)
- **`_CHECKBOX_UNICODE`** regex (line 269)
- **`_find_checkbox_near_label()`** function (lines 274-299)
- **`_detect_asset_checkboxes()`** function (lines 302-330)

### 3. `src/datalab_schema.py` — Simplify `convert_extract_response()`

**Remove line 345**:
```python
# Delete this line:
markdown_overrides = _detect_asset_checkboxes(response.get("markdown", ""))
```

**Remove lines 348-358** (HTML debug logging):
```python
# Delete this entire block:
# TEMP DEBUG: log HTML around asset section
import logging
logger = logging.getLogger(__name__)
if html:
    html_text = html if isinstance(html, str) else str(html)
    for pat in ASSET_MARKDOWN_PATTERNS:
        m = re.search(pat, html_text, re.IGNORECASE)
        if m:
            start = max(0, m.start() - 80)
            end = min(len(html_text), m.end() + 80)
            logger.info("Asset HTML [%s]: |%s|", pat, html_text[start:end].replace("\n", " "))
```

Also remove the unused `html = response.get("html", "")` variable.

**Remove `import re`** if it's no longer needed (check if `re` is still used elsewhere in the file).

**Simplify lines 379-392** (asset handling block):

Before:
```python
        if key.startswith("asset_") and key != "asset_others":
            norm = value.strip().lower()
            if norm in ("\u2713", "/", "1", "yes", "y", "true"):
                if markdown_overrides.get(key) is False:
                    continue
                value = "\u2713"
            else:
                continue
        elif key == "asset_others":
            if markdown_overrides.get(key) is False:
                continue
            if value and value not in ("\u2713", "\u2717", ""):
                if not value.lower().startswith("others"):
                    value = f"Others: {value}"
```

After:
```python
        if key.startswith("asset_") and key != "asset_others":
            norm = value.strip().lower()
            if norm in ("\u2713", "/", "1", "yes", "y", "true"):
                value = "\u2713"
            else:
                continue
        elif key == "asset_others":
            if value and value not in ("\u2713", "\u2717", ""):
                if not value.lower().startswith("others"):
                    value = f"Others: {value}"
```

### 4. `src/database.py` — No changes needed

The DB layer uses `_is_checked("✓")` and `JSONB_ARRAY_COLUMNS` aggregation for `assets_at_home`. The boolean-derived `"✓"` values flow through correctly.

### 5. Run tests

```bash
uv run python tests/test_backend.py
```

## Data flow after fix

```
Datalab response: asset_washing_machine=true, asset_fridge=false, ...
convert_extract_response():
  - True → value = "✓" → appended: {"label": "4.1 Assets at Home — Washing Machine", "value": "✓", ...}
  - False → line 367: if not raw_value: continue → SKIPPED
  - null/None → line 364: if raw_value is None: continue → SKIPPED

database.py _extract_structured_fields():
  - JSONB_ARRAY_COLUMNS aggregates labels prefixed "4.1 Assets at Home — "
  - "Washing Machine" → fval.strip() = "✓" → _is_checked → True → added to checked[]
  - "Fridge" → not present in label_map (was skipped) → not added
  - Result: sorted(["Car", "LED TV", "Smartphone", ...]) — only truly ticked items
```
