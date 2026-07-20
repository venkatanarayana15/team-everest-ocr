PRIMARY_EXTRACTION_PROMPT = r'''
-------------------------------------------------------------------------------
SINGLE-RECTANGLE MARK DETECTION — The ONLY rule for EVERY checkbox / radio
-------------------------------------------------------------------------------
For EACH option row, the [ ] box AND its label text form ONE combined
rectangle. Treat them as a single container — do NOT separate them.

  VISUAL SCAN:
    Start at the LEFT edge of [ ]. Scan RIGHTWARD across the box AND
    continue through the ENTIRE label text to the end of the option row.
    Do NOT stop at the right edge of [ ]. The mark may be anywhere.

  SINGLE RECTANGLE RULE:
    Each option = ONE rectangle from [left of box] to [end of label text].
    Search the FULL rectangle. The box and text are inseparable.

  RESOLUTION:
    • Tick (✓) or slash (/) ANYWHERE in the rectangle → "Yes" (selected)
    • Cross (X / ✗ / ×) ANYWHERE in the rectangle → "No" (rejected)
    • No mark at all in the rectangle → "No" (empty)
    • Dot, scribble, circle-around-text = noise — ignore, look for real mark
    • If BOTH tick AND cross in same rectangle → tick wins → "Yes"
      (A single X has intersecting lines — that is a cross, not tick+cross)

  THIS APPLIES TO EVERY FIELD. NO EXCEPTIONS.
  The mark location (inside box vs on text) is IRRELEVANT.

  Examples:
    [✓] Separate Kitchen               → "Yes"
    [ ] Separate Kitchen with ✓ on text → "Yes"
    [ ] fridge with / on "fridge"       → "Yes"
    [ ] Aadhaar Card with ✓ on text     → "Yes"
    [✗] Individual                      → "No"
    [ ] Individual with X on text       → "No"
    [ ] Private Apartment blank         → "No"

You are a trusted form extraction engine for a fixed 6-page "I Am The Change — Home Visit Questionnaire". Your output is the single source of truth for downstream Zoho Creator and Supabase persistence. Every field matters.

Output ONLY valid JSON. No markdown fences. No explanations. No commentary. ONLY the JSON object.

GROUND RULES
1. Extract EVERY field listed below. Never skip a single field.
2. value="" for unreadable/blanks. value="N/A" for conditionals when parent="No". Never "null".
3. Radio → exact allowed option (e.g. "Male", "Yes", "Separate"). Checkbox → each option is ONE rectangle (box + label text). Tick/slash ANYWHERE in rectangle → "Yes". Cross ANYWHERE → "No". No mark → "No".
4. Table → count pre-printed rows first. Every cell: "{Table} — Row {n} — {Column}".
5. Never invent values. If unreadable: "" and low confidence.
6. OUTPUT ALL FIELDS ON THIS PAGE. If you cannot read the value, output value="" with low confidence. If the label area is cropped/blurry, output value="" anyway — do not omit the field.

-------------------------------------------------------------------------------
REASONING INSTRUCTIONS — Apply these steps for each field type
-------------------------------------------------------------------------------

For EVERY field, before writing the output, mentally:

### Mutually exclusive checkbox pairs (exactly ONE must be "Yes"):
  These fields have TWO options, and EXACTLY ONE must be selected:
  3.1 House Ownership (Own vs Rented)
  3.4.1 Type of Bedroom (Separate vs No Separate)
  4.3 Own other assets/properties (Yes vs No)
  3.5 Bathroom (Separate vs Common for Apartment)

  STEP 1: Identify the mark in BOTH option rectangles
          (see SINGLE-RECTANGLE MARK DETECTION above).
  STEP 2: The rectangle with a tick/slash → "Yes"; the other → "No".
          A cross in the rectangle = "No" (rejected).
  STEP 3: If BOTH rectangles hold a tick/slash → pick the darker/denser one.
  STEP 4: If NEITHER has a tick/slash → use context:
    - 3.1: if rent amount (3.1.1) filled → Rented = "Yes"
    - 3.4.1: if "Number of Bedrooms" > 0 → Separate = "Yes"
    - 4.3: if 4.3.1 table is filled → Yes = "Yes"
    - 3.5: look at nearby sentence text
  STEP 5: NEVER output "No" for BOTH. NEVER "Yes" for BOTH. Exactly one "Yes".

### Multi-select checkboxes (any subset can be "Yes", independent):
   2.4 Government ID Verified (Aadhaar, Ration, Driving Licence, Voter ID, Other)
   3.2 Type of Home (Individual, Private Apartment, Housing Board, Line House, Others)
   3.3 Type of Ceiling (Roof (Kurai), Tiled, Asbestos/Sheet, Concrete)
   4.1 Assets at Home (Washing Machine, Fridge, AC, LED TV, Two-Wheeler, Car, Smartphone, Separate Wi-Fi, Others)  ← for 4.1 only: any mark = checked, only X = unchecked
   4.5 Income Type (Monthly, Daily, Weekly, Ad-Hoc)
   3.6 Kitchen Type (Separate Kitchen, Hall with Kitchen)

  STEP 1: Examine EACH option independently in its SINGLE RECTANGLE
          (box + label text as one — see SINGLE-RECTANGLE MARK DETECTION above).
  STEP 2: Tick (✓) or slash (/) ANYWHERE in the rectangle → "Yes".
          Cross (X/✗) ANYWHERE → "No". No mark → "No".
  STEP 3: If a section shows all empty, re-examine for faint marks.
  STEP 4: Multiple "Yes" allowed. Each option is independent.
  STEP 5: For "Others:" fields, also capture handwritten text.
  STEP 6: For Income Type checkboxes, also capture any handwritten text/name written near each checked option (e.g. "mother" near Monthly → specify field "Monthly: mother").
  STEP 6: If BOTH tick and cross in same rectangle → tick wins → "Yes".

### Radio buttons (exactly ONE selected — output the option TEXT, not "Yes"/"No"):
   1.3 Gender (Male | Female | Others)
   2.3 Is Father/Mother photograph kept at home? (Yes | No — also capture free text after checkbox as Notes)
   4.4 Apart from your job, is there any other source of income? (Yes | No)
   4.6 Do you have any loans? (Yes | No)
   5.1 Does the student have any health issues? (Yes | No)
   6.2 If we have a training program... (Yes | No | Maybe)
   6.3 Are you ready to send... (Yes | No)
   8.2 Will you recommend... (Yes | No | Not Sure)

  STEP 1: For each option, search its SINGLE RECTANGLE (box + label text).
          Tick (✓) or slash (/) ANYWHERE in the rectangle → selected.
          Cross (X) ANYWHERE → not selected.
  STEP 2: Output the EXACT text of the selected option.
  STEP 3: If nothing is clearly selected, look for any tick/slash/handwriting near an
          option. If one option is crossed out (X), the OTHER option is selected. If
          still ambiguous, use OCR proximity — the option closest to the tick/slash wins.
  STEP 4: NEVER output an option that does not appear in the allowed list.

### Numeric text fields:
  4.6.1 Loan Amount Taken/Pending:

  STEP 1: Extract only digits, decimal point, and optional negative sign.
  STEP 2: Remove all currency symbols (₹, $, etc.), commas, and unit words (Rs, rupees).
  STEP 3: If the value ends with ".00", keep the decimal. If it's a clean integer, output without decimal.
  STEP 4: If the value looks like "1200/" → extract "1200".
  STEP 5: OCR may confuse l/1, O/0, and B/8 — reason about context.
  EXCEPTION — 3.1.1 rent amount: preserve the ORIGINAL text exactly as written including "Rs", "/-", "/month", and commas. Do NOT strip these.

### Table fields (count pre-printed rows, fill every cell):
NEVER combine column names with | in a single label. Each column is its own separate " — ColumnName" field.
  4.3.1 Properties (Property Description, Owner Name, Approximate Value) — 3 cols
  4.4.1 Income Sources (Source of Income, Amount) — 2 cols
  4.6.1 Loans (Loan Purpose, Loan Amount Taken, Pending Loan Amount) — 3 cols

  STEP 1: Count the NUMBER OF PRE-PRINTED ROWS in the table. These are rows printed on the form, NOT rows with data filled in. (2.5 Family Members: usually 4 pre-printed rows).
  STEP 2: For each row n (1, 2, 3, ...), output every column: "{Table label} — Row {n} — {Column name}".
  STEP 3: If a cell is blank (no data filled), output value="" — do NOT skip the row.
  STEP 4: If parent conditional field is "No", output "N/A" for ALL cells in ALL rows. Exception: 4.4.1 — if the table has visible handwritten text (not struck through), extract it even when 4.4 = No.
  STEP 5: For 4.6.1 Loans: Sr.No. is typically pre-printed (1, 2, 3). Check if there's handwriting in the Loan Purpose column to confirm data presence.
  STEP 6: For 2.5 Family Members: after counting the pre-printed rows, scan for any handwritten text AFTER the last pre-printed row and include it as an extra row with the text in the Name column.
  STEP 7: For 4.6.1 Loans: scan for any handwritten text BEFORE Sr.No. 1 or AFTER Sr.No. 3 and include each as an extra row (Row 0 or Row 4) with text in the appropriate column.

### STRIKETHROUGH / CROSSED-OUT TEXT — treat as VOID (CRITICAL — applies to ALL table fields):

Some filled-in table cells have been DELETED by the respondent:
  - A horizontal strikethrough line (───) drawn through the handwriting
  - A diagonal slash (/ or \) through the entire cell
  - A cross (X) covering the cell
  - Any mark that clearly crosses out the text

RULE: If ANY cell in a table row has a strikethrough/slash/cross → the
respondent voided that entire row. Output value="" for ALL columns in
that row. Treat the row as if it were blank.

EXAMPLE 1 — 4.4.1 Income Sources table:
  Source="Mother/Father"  Amount="Daily/weekly wages (3000 per week)"
  But a horizontal LINE is drawn through both cells → VOID
  → Source of Income=""  AND  Amount=""

EXAMPLE 2 — 4.6.1 Loans table:
  Loan Purpose="Education loan"  Amount Taken="50000"  Pending="30000"
  But a CROSS (X) covers the row → VOID
  → Loan Purpose=""  AND  Loan Amount Taken=""  AND  Pending Loan Amount=""

Apply this rule to 2.5 Family Members, 4.3.1 Properties, 4.4.1 Income
Sources, and 4.6.1 Loans. If in doubt about a mark, check if it
overlaps the handwritten text — overlapping = deletion.

### BLANK AREA HANDWRITING — 4.3.1 Properties table (CRITICAL):

The 4.3.1 Properties table has 2 pre-printed rows (printed on the form) PLUS 2
extra rows whose content lives in UNPRINTED blank spaces on pages 3 and 4.
You MUST locate and transcribe these handwritten blank-area entries.

  Row 3 — from page 3 blank area:
    LOCATION: The empty space at the BOTTOM of page 3, directly below the
    "4.3 Do you own any other assets/properties in the name of
    grandparents, parents, or student?" checkbox section.
    TASK: Scan this blank area. Handwriting here looks like e.g.
    "brothers land", "no share in the property", "brothers property".
    Extract the text into "4.3.1 — Row 3 — Property Description".
    Owner Name and Approximate Value are typically empty for Row 3.

  Row 4 — from page 4 blank area:
    LOCATION: The empty gap on page 4 BETWEEN the last pre-printed
    4.3.1 table row and the next question "4.4 Apart from your job,
    is there any other source of income?".
    TASK: Scan this gap. Handwriting here looks like e.g.
    "no chance of getting share", "brothers land".
    Extract into "4.3.1 — Row 4 — Property Description".
    Owner Name and Approximate Value are typically empty for Row 4.

  EXPECTED OUTPUT (example of a fully filled form):
    Row 1: Property Description="Home",  Owner Name="Grandparent's Name",  Approximate Value="-"
    Row 2: Property Description="",        Owner Name="",                     Approximate Value=""
    Row 3: Property Description="brothers land",  Owner Name="",  Approximate Value=""
    Row 4: Property Description="no chance of getting share",  Owner Name="",  Approximate Value=""

  If a blank area is TRULY EMPTY (no handwriting) → value="" for all 3 columns.

### Conditional dependency reasoning:
  For ANY field that depends on a parent Yes/No field:

  STEP 1: Find the parent field value first.
  STEP 2: Parent = "No" → ALL children = "N/A"
  STEP 3: Parent = "Yes" → the child fields ARE filled in — actively read the handwriting in that row/table. Do NOT output "" or "No loans recorded" when the parent is "Yes"; transcribe the actual written values (e.g. for 4.6.1 read Loan Purpose, Loan Amount Taken, Pending Loan Amount from the handwritten row).
  STEP 4: Parent is unclear → extract children anyway, note dependency in reason field.

  Key dependencies:
  3.1.1 rent amount → depends on 3.1 House Ownership = Rented
  4.3.1 properties table → depends on 4.3 = Yes
  4.6.1 loans table → depends on 4.6 = Yes
  5.2 health issues → depends on 5.1 = Yes

-------------------------------------------------------------------------------
CORE OUTPUT SCHEMA
-------------------------------------------------------------------------------
{
  "sections": [
    {"number": 1, "name": "Student Profile", "page": 1},
    {"number": 2, "name": "Family Background", "page": 1},
    {"number": 3, "name": "Housing Condition", "page": 2},
    {"number": 4, "name": "Financial Background", "page": 3},
    {"number": 5, "name": "Health Information", "page": 5},
    {"number": 6, "name": "Student Commitment", "page": 5},
    {"number": 7, "name": "Scholarship Information", "page": 6},
    {"number": 8, "name": "Volunteer Observation", "page": 6}
  ],
  "fields": [ { Field objects — see below } ],
  "overall_confidence": 0-100,
  "clarification_needed": ["label1", "label2", ...],
  "raw_text": "...",
  "markdown_output": "..."
}
Sort: page ascending, then section, then label.

-------------------------------------------------------------------------------
FIELD OBJECT
-------------------------------------------------------------------------------
{
  "label":  string  — exact label from FIELD LIST below,
  "value":  string  — "" | "N/A" | extracted text,
  "confidence": 0-100,
  "confidence_reason": string,
  "page":  int,  "section":  int|null,  "needs_clarification": bool,
  "reason":  string|null,  "position_hint": "same_line_colon"|"right_of_label"|...,
  "bbox":          [x1, y1, x2, y2] | null,
  "value_bbox":    [x1, y1, x2, y2] | null,
  "parent_label":  string|null,        // parent question label (e.g. "2.4 Government ID Verified")
  "field_type":    "text"|"radio"|"checkbox"|"table_row"|"table_header"|"specify",
  "group_id":      string|null,        // group identifier for radio/checkbox groups
  "row_index":     int|null,           // row number for table rows (1-based)
  "column_name":   string|null         // column name for table cells
}

-------------------------------------------------------------------------------
SPATIAL GROUNDING — bbox / value_bbox (REQUIRED for every field when visible)
-------------------------------------------------------------------------------
For EACH field, provide TWO bounding boxes in NORMALIZED 0–1000 coordinates
(where 0 = top/left edge of the page image, 1000 = bottom/right edge).
  • "bbox":       rectangle around the FIELD LABEL (the printed/asked question text).
  • "value_bbox": rectangle around the FIELD VALUE (the answer — ticked box, filled
                  text, selected option, or handwritten entry).
Format: [x1, y1, x2, y2]  with x1<x2 and y1<y2, all integers in 0..1000.
Rules:
  • Coordinates are relative to the SAME page image you are viewing for that field.
  • If the label or value is not visible / cannot be located, use null (never omit
    the key — include "bbox": null explicitly).
  • For checkbox groups, value_bbox should cover the specific checked box + its option text.
  • For table cells, bbox covers the cell label/header area, value_bbox covers the cell content.
  • Be precise: tightly bound the text region, do not pad excessively.
  • This grounding is used to draw a highlight on the PDF, so accuracy matters.

-------------------------------------------------------------------------------
VALUE RULES — APPLY TO EVERY FIELD
-------------------------------------------------------------------------------
Text/Radio:    exact text. Radio must be one allowed option. Unreadable → "".
Checkbox:      "Yes" (checked) | "No" (unchecked) | "" (unclear). EVERY option → separate field.
Table cell:    "{Table} — Row {n} — {Column}". Every row → every column.
Header fields: section=null, position_hint=same_line_colon.
Conditional:   parent="No" → ALL children "N/A". parent="Yes" but blank → "".
Long text:     preserve complete text, join multi-line with \n.
Blank/cropped: value="", confidence=10-20, needs_clarification=true.
NEVER omit.   If you cannot see the label area, still output with value="" confidence=10.

-------------------------------------------------------------------------------
ZOHO CREATOR COMPATIBILITY — Follow these value formatting rules
-------------------------------------------------------------------------------
Numeric fields (output as plain numbers, no ₹, no commas, no spaces):
  "2.5 Family Members — Row n — Age"        → e.g. "42"      not "42 years"
  "4.6.1 — Row n — Loan Amount Taken"       → e.g. "200000"  not "2,00,000"

Boolean fields (only "Yes" or "No" — never "yes", "no", "true", "false", "Y", "N"):
  All conditional radio fields with [radio → Yes | No]
  Also: 6.3

Enum fields (exact value from allowed set):
  "Gender":        exactly "Male" | "Female" | "Others"
   "Income Type":   "Monthly | Daily | Weekly | Ad-Hoc (checkbox, multiple OK, include specify text)"

Normalize consistently:
  "yes" → "Yes", "no" → "No", "y" → "Yes", "n" → "No"
  Strip leading/trailing whitespace from all values
  Replace multiple spaces with single space

-------------------------------------------------------------------------------
CONDITIONAL DEPENDENCY TABLE
-------------------------------------------------------------------------------
Parent field                               | Parent=Yes →     | Parent=No →
3.1 House Ownership = Rented               | 3.1.1 = rent      | 3.1.1 = "N/A"
5.1 health issues = Yes                    | 5.2 = list        | 5.2 = "N/A"
4.3 own assets = Yes                       | 4.3.1 table=value | 4.3.1 = all "N/A"
4.6 loans = Yes                            | 4.6.1 table=value | 4.6.1 = all "N/A"
All others                                 | value from field  | n/a

-------------------------------------------------------------------------------
FIELD LIST — EXTRACT EVERY SINGLE FIELD  (expected counts in parentheses)
-------------------------------------------------------------------------------

--- Header (Page 1, section=null) — 3 fields ---
  Volunteer Name        [text]
  Co-Volunteer Name     [text]
  Date of Visit         [text]

--- Section 1 — Student Profile (Page 1) — 3 fields ---
  1.1 Application ID                      [text — alphanumeric CODE. Last 4 chars are DIGITS only, not letters. '8'↔'B', '0'↔'O', '1'↔'l', '5'↔'S'. E.g. B974→8974.]
  1.2 Student Full Name                   [text]
  1.3 Gender                              [radio → Male | Female | Others]

--- Section 2 — Family Background (Pages 1-2) — 5 fields + (5 × N) table ---
  2.1 Family Status                                    [radio → Single Parent | Parentless | Having both parents]
  2.2 Relationship Details — Year of Death / Separation [text]      ← pg 2
  2.2 Relationship Details — Reason for Death / Separation [text]   ← pg 2 — ALSO look carefully at the blank area BELOW 2.1 Family Status options on page 1 for any handwritten notes/annotations and include them here
  blank_text_below_2_1 [text — hidden helper, capture handwriting in the blank area between 2.1 and 2.2 on page 1, then output empty string]
   2.3 Is Father/Mother photograph kept at home?         [radio → Yes | No — also capture free text written after checkbox as "2.3 Is Father/Mother photograph kept at home? — Notes"]
  2.4 Government ID Verified — Ration Card       [checkbox]
  2.4 Government ID Verified — Driving Licence   [checkbox]
  2.4 Government ID Verified — Voter ID          [checkbox]
  2.4 Government ID Verified — Other              [checkbox]
  2.5 Family Members                                    [table — columns: Name, Age, Education, Occupation, Annual Income]  ← pg 2

--- Section 3 — Housing Condition (Pages 2-3) — 12 fields ---
  3.1 House Ownership — Own               [checkbox]                     ← pg 2
  3.1 House Ownership — Rented            [checkbox]
  3.1.1 If rented, what is the rent amount? [text]                        ← pg 2
  3.2 Type of Home — Individual           [checkbox]                      ← pg 2
  3.2 Type of Home — Private Apartment    [checkbox]
  3.2 Type of Home — Housing Board        [checkbox]
  3.2 Type of Home — Line House           [checkbox]
  3.2 Type of Home — Others               [text — capture free-text from "Others:" line]
  3.3 Type of Ceiling — Roof (Kurai)     [checkbox]                      ← pg 3
  3.3 Type of Ceiling — Tiled             [checkbox]
  3.3 Type of Ceiling — Asbestos / Sheet   [checkbox]
  3.3 Type of Ceiling — Concrete          [checkbox]
  3.4 Number of Bedrooms                  [text]                          ← pg 3
  3.4.1 Type of Bedroom — Separate Bedroom   [checkbox]
  3.4.1 Type of Bedroom — No Separate Bedroom [checkbox]
  3.5 Bathroom                            [radio → Separate | Common for Apartment]
  3.6 Kitchen Type — Separate Kitchen     [checkbox]                      ← pg 3
  3.6 Kitchen Type — Hall with Kitchen    [checkbox]

--- Section 4 — Financial Background (Pages 3-5) — 12 fields + (4 × 3 + 2 × 2 + 3 × 3) table ---
  4.1 Assets at Home(tick all that apply) - Washing Machine    [checkbox]                      ← pg 3
  4.1 Assets at Home(tick all that apply) - Fridge             [checkbox]
  4.1 Assets at Home(tick all that apply) - AC                 [checkbox]
  4.1 Assets at Home(tick all that apply) - LED TV             [checkbox]
  4.1 Assets at Home(tick all that apply) - Two-Wheeler        [checkbox]
  4.1 Assets at Home(tick all that apply) - Car                [checkbox]
  4.1 Assets at Home(tick all that apply) - Smartphone         [checkbox]
  4.1 Assets at Home(tick all that apply) - Separate Wi-Fi     [checkbox]
   4.1 Assets at Home(tick all that apply) - Others             [checkbox]
      ↑ For 4.1 only: any mark near checkbox or text = checked; only X = unchecked.
   4.2 Amount of Last Electricity Bill     [text — preserve original text including ₹, Rs, /month]   ← pg 3
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes  [checkbox]                 ← pg 3
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No   [checkbox]
    4.3.1 — Row 1 — Property Description [text]                           ← pg 4
    4.3.1 — Row 1 — Owner Name           [text]
    4.3.1 — Row 1 — Approximate Value    [text]
    4.3.1 — Row 2 — Property Description [text]                           ← pg 4
    4.3.1 — Row 2 — Owner Name           [text]
    4.3.1 — Row 2 — Approximate Value    [text]
    4.3.1 — Row 3 — Property Description [text — BLANK AREA page 3: check empty space below 4.3 checkbox]  ← pg 3
    4.3.1 — Row 3 — Owner Name           [text — leave empty for page-3 handwritten notes]
    4.3.1 — Row 3 — Approximate Value    [text — leave empty for page-3 handwritten notes]
    4.3.1 — Row 4 — Property Description [text — BLANK AREA page 4: check gap between 4.3.1 table and 4.4]  ← pg 4
    4.3.1 — Row 4 — Owner Name           [text — leave empty for page-4 handwritten notes]
    4.3.1 — Row 4 — Approximate Value    [text — leave empty for page-4 handwritten notes]
  4.4 Apart from your job, is there any other source of income? [radio → Yes | No]  ← pg 4
   4.5 Income Type                         [checkbox — Monthly | Daily | Weekly | Ad-Hoc, +specify text for each]  ← pg 4
   4.6 Do you have any loans?              [radio → Yes | No]                           ← pg 4
      4.6.1                             [table — 3 pre-printed rows; columns: Sr.No., Loan Purpose, Loan Amount Taken, Pending Loan Amount]    ← pg 4
   4.7 If you choose any college, how much is the college fee? [text — scan ENTIRE blank space below (multiple lines ok). Combine with ", " if continuation found.]                   ← pg 5
  4.8 If the college fee is higher, how will you manage it? [text]
  4.9 If you do not receive this scholarship, how will you pay the fees? [text]

--- Section 5 — Health Information (Page 5) — 2 fields ---
  5.1 Does the student have any health issues? [radio → Yes | No]
  5.2 If yes, list the health issues        [text]

--- Section 6 — Student Commitment (Pages 5-6) — 3 fields ---
  6.1 Will you study college for three years without any obstacle? [text]               ← pg 5
   6.2 If we have a training program within 15 km from your home, can you come?          ← pg 5
       [radio → Yes | No | Maybe]
  6.3 Are you ready to send your son/daughter to weekly skill development classes
      on Sundays (16 classes a year)? [radio → Yes | No]          ← pg 6

--- Section 7 — Scholarship Information (Page 6) — 1 field ---
  7.1 Has the student received or applied for any other scholarships for their UG degree? [text]

--- Section 8 — Volunteer Observation (Page 6) — 3 fields ---
  8.1 What is your opinion about the student, their family members, and their living condition?
      [text — preserve complete answer, preserve newlines within answer]
  8.2 Will you recommend this student for this scholarship? [radio → Yes | No | Not Sure]
  8.3 Any other comments you want to share? [text]

-------------------------------------------------------------------------------
TABLE RULES (CRITICAL)
-------------------------------------------------------------------------------
Before extracting ANY table:
  1. Count pre-printed data rows in the form. NOT filled rows — ALL pre-printed rows.
  2. State to yourself: "Table has N rows".
  3. Output exactly N rows: Row 1, Row 2, ..., Row N. Every row → every column.

Label format: "{Table label} — Row {n} — {Column name}"
Example: "2.5 Family Members — Row 1 — Name", "2.5 Family Members — Row 1 — Age"

  Blank cell     → value=""
  Conditional No → every cell = "N/A" for every row
  Never skip a row just because it is blank. Pre-printed empty rows are still valid rows.

Tables:
  2.5 Family Members:      Name, Age, Education, Occupation, Annual Income             (5 cols)
  4.3.1:                   Property Description, Owner Name, Approximate Value          (3 cols)
  4.6.1:                   Loan Purpose, Loan Amount Taken, Pending Loan Amount         (3 cols)

-------------------------------------------------------------------------------
SELF-VERIFICATION — CRITICAL: review all fields before finalizing
-------------------------------------------------------------------------------
1. Scan for any fields with confidence < 70 or needs_clarification=true.
2. Re-examine the document image for EACH such field:
   - Can I now read the value? → update value, raise confidence to 80-99, clear needs_clarification.
   - Is it truly blank? → set confidence=95-99, confidence_reason="confirmed blank", clear needs_clarification.
   - Still uncertain? → keep original state.
3. Check ALL conditionals: parent="No" → children must be "N/A". Fix any missed.
4. Verify field count per section matches expected counts above. If short, add missing fields with value="".
5. Verify no null values in any value field — only "" or "N/A" or text.

-------------------------------------------------------------------------------
RAW TEXT & MARKDOWN OUTPUT
-------------------------------------------------------------------------------
"raw_text":
  - Pages separated by "\n\n--- Page {n} ---\n\n"
  - **bold** for every question/field label
  - Markdown tables for form tables
  - Radio: [●] selected, [○] unselected
  - Checkbox: [✓] checked, [✗] unchecked, [—] unknown

"markdown_output":
  - Same content, cleaned for human review
  - Title at top, clean hierarchical headings, every question bold

-------------------------------------------------------------------------------
FINAL VERIFICATION CHECKLIST — RUN EVERY ITEM BEFORE RETURNING
-------------------------------------------------------------------------------
[ ] SECTION COUNTS: Header(3) + S1(3) + S2(5 + 5×N rows) + S3(12) + S4(12 + 4R×3 + 2S×2 + 3T×3) + S5(2) + S6(3) + S7(1) + S8(3) — do the math.
[ ] Every label from FIELD LIST appears exactly once.
[ ] Every checkbox option present: ✓ or ✗ or "". None merged, none missing.
[ ] Table rows: counted pre-printed rows, output exactly that many.
[ ] Radio values: each is ONE of the allowed options per the list above.
[ ] Conditionals: all children "N/A" when parent clearly "No". Not flagged as low-confidence.
[ ] Header fields all have section=null.
[ ] needs_clarification=true entries all match a label in clarification_needed list.
[ ] value is never null — only "" or "N/A" or extracted text.
[ ] Table label format: "{prefix} — Row {n} — {Column}" e.g. "4.3.1 — Row 1 — Property Description".
[ ] Numeric values: no ₹, no commas, no "years"/"Rs" suffixes.
[ ] Boolean values: only "Yes" or "No" — never "yes", "true", "Y".
[ ] No markdown fences around JSON. No text before or after JSON.

Now process the document page by page and return the JSON.
'''


SECONDARY_VERIFICATION_PROMPT = r'''You are a targeted gap-filler for a 6-page questionnaire extraction.

The primary extraction already produced the fields below. Your job is ONLY to fix errors and fill gaps in low-confidence fields. Do NOT re-extract fields that are already correct.

Return ONLY valid JSON.

{
  "verifications": [
    {
      "label": string,
      "is_correct": boolean,
      "correct_value": string or null,
      "verifier_confidence": 0-100,
      "note": string or null
    }
  ],
  "new_fields": [
    {
      "label": string,
      "value": string,
      "confidence": 0-100,
      "confidence_reason": string,
      "page": integer,
      "section": integer or null,
      "needs_clarification": boolean,
      "reason": string or null,
      "position_hint": "same_line_colon" | "right_of_label" | "below_label" | "above_label"
    }
  ]
}

RULES
-----
1. For each field in the input, decide: is the value correct?
   - is_correct=true  → leave as-is (even if value="")
   - is_correct=false → provide correct_value and a note explaining the fix

2. Only set is_correct=false when you are CERTAIN the value is wrong.
   - Radio: wrong option selected (not the option marked with a tick/slash).
    - Checkbox: each option = ONE rectangle (box + label text as a single container). Search the FULL rectangle:
        • Tick (✓) or slash (/) ANYWHERE → "Yes"
        • Cross (X/✗) ANYWHERE → "No" (rejected)
        • Both tick and cross visible → tick wins → "Yes"
        • No mark, or only dot/scribble → "No"
      A mark on text counts the same as a mark in the box. The box does NOT need to contain the mark.
    - Text: clearly misread.
   - Do NOT flag fields just because value="" — the primary prompt may have correctly found a blank.

3. Add new_fields ONLY for fields that are MISSING entirely (not in the input).
   - Do NOT add fields that are already present with any value (including "").
   - Check the label list carefully before adding anything.

4. Value rules (match the primary extraction conventions):
   - Radio: exact option text (Male|Female|Others|Yes|No|...)
    - Checkbox: each option = ONE rectangle (box + label text). Tick/slash ANYWHERE in rectangle → "Yes". Cross ANYWHERE → "No". No mark → "No".
   - Table cell: "{Table} — Row {n} — {Column}" format
   - Conditional unmet: "N/A"
   - Unreadable: "" not null

Existing fields (low-confidence only — high-confidence fields were already auto-accepted):
{fields_json}
'''


PAGE_FIELD_MAPPINGS: dict[int, str] = {
    1: """
--- Header (Page 1, section=null) — 3 fields ---
  Volunteer Name        [text — full name, exactly as written]
  Co-Volunteer Name     [text — full name, exactly as written]
  Date of Visit         [text — exactly as written on the form, do NOT convert or reformat. E.g. if written "6th June 2026" return "6th June 2026"]

--- Section 1 — Student Profile (Page 1) — 3 fields ---
  1.1 Application ID                      [text — alphanumeric CODE like 'TE2024001' or 'temp-2026-9934'. Last 4 chars are DIGITS only, not letters. '8'↔'B', '0'↔'O', '1'↔'l', '5'↔'S'. E.g. B974→8974, O→0.]
  1.2 Student Full Name                   [text — full name, exactly as written]
  1.3 Gender                              [radio → Male | Female | Others — pick the single EXACT option text]

--- Section 2 — Family Background (Page 1) — 4 fields ---
  2.1 Family Status                                    [radio → Single Parent | Parentless | Having both parents — pick the single EXACT option text]
   blank_text_below_2_1 [text — REQUIRED: examine the blank area BETWEEN the 2.1 options and the 2.2 header on page 1. If there is ANY handwriting (notes, annotations), transcribe it verbatim. If blank, output "".]
  2.2 Relationship Details — Year of Death / Separation [text]
  2.2 Relationship Details — Reason for Death / Separation [text — ALSO scan blank_text_below_2_1 region above and include any text found there]
""",
    2: """
--- Section 2 — Family Background (Page 2) — 2 fields + (5 × N) table ---
  2.3 Is Father/Mother photograph kept at home?         [radio → Yes | No — also scan the area BEYOND the No checkbox for free text (e.g. "we shifted to new house 2 months back") and output it as "2.3 Is Father/Mother photograph kept at home? — Notes"]
  2.3 Is Father/Mother photograph kept at home? — Notes [text — free text written after the 2.3 checkbox area, e.g. "we shifted to new house 2 months back". If nothing written, output ""]
  2.4 Government ID Verified — Aadhaar Card      [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Ration Card       [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Driving Licence   [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Voter ID          [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Other              [checkbox — ✓ if checked, ✗ if empty]
2.4 Government ID Verified — Other (specify)   [text — free-text written next to "Other", EXACTLY as written. If the "Other" box is unchecked OR nothing is written, output empty string ""]
    2.5 Family Members [table_header]
      2.5 Family Members — Row 1 — Name [text]
      2.5 Family Members — Row 1 — Age [text]
      2.5 Family Members — Row 1 — Education [text]
      2.5 Family Members — Row 1 — Occupation [text]
      2.5 Family Members — Row 1 — Annual Income [text]
      2.5 Family Members — Row 2 — Name [text]
      2.5 Family Members — Row 2 — Age [text]
      2.5 Family Members — Row 2 — Education [text]
      2.5 Family Members — Row 2 — Occupation [text]
      2.5 Family Members — Row 2 — Annual Income [text]
      2.5 Family Members — Row 3 — Name [text]
      2.5 Family Members — Row 3 — Age [text]
      2.5 Family Members — Row 3 — Education [text]
      2.5 Family Members — Row 3 — Occupation [text]
      2.5 Family Members — Row 3 — Annual Income [text]
      2.5 Family Members — Row 4 — Name [text]
      2.5 Family Members — Row 4 — Age [text]
      2.5 Family Members — Row 4 — Education [text]
      2.5 Family Members — Row 4 — Occupation [text]
      2.5 Family Members — Row 4 — Annual Income [text]
      Also scan for any handwritten text AFTER the last pre-printed row and include it as an extra row ("2.5 Family Members — Row 5 — Name") with the text in the Name column.

--- Section 3 — Housing Condition (Page 2) — 7 fields ---
  3.1 House Ownership — Own               [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.1 House Ownership — Rented            [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
   3.1.1 If rented, what is the rent amount? [text — preserve original text including comma, ₹, Rs, /month]
  3.2 Type of Home — Individual           [checkbox — ✓ or ✗ — independent, can be ✓ with others]
  3.2 Type of Home — Private Apartment    [checkbox — ✓ or ✗ — independent, can be ✓ with others]
  3.2 Type of Home — Housing Board        [checkbox — ✓ or ✗ — independent, can be ✓ with others]
  3.2 Type of Home — Line House           [checkbox — ✓ or ✗ — independent, can be ✓ with others]
  3.2 Type of Home — Others               [text — ALWAYS capture free-text from "Others:______" line even if checkbox is empty. Prefix with "Others: " if the text is present.]
""",
    3: """
--- Section 3 — Housing Condition (Page 3) — 9 fields ---
  3.3 Type of Ceiling — Roof (Kurai)     [checkbox — ✓ or ✗ — independent]
  3.3 Type of Ceiling — Tiled             [checkbox — ✓ or ✗ — independent]
  3.3 Type of Ceiling — Asbestos / Sheet   [checkbox — ✓ or ✗ — independent]
  3.3 Type of Ceiling — Concrete          [checkbox — ✓ or ✗ — independent]
  3.4 Number of Bedrooms                  [text — whatever is written, verbatim. e.g. "2", "two", "2 rooms". Do NOT strip or convert.]
  3.4.1 Type of Bedroom — Separate Bedroom   [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.4.1 Type of Bedroom — No Separate Bedroom [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.5 Bathroom - Separate                 [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.5 Bathroom - Common for Apartment     [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.6 Kitchen Type — Separate Kitchen     [checkbox — ✓ or ✗ — independent]
  3.6 Kitchen Type — Hall with Kitchen    [checkbox — ✓ or ✗ — independent]

--- Section 4 — Financial Background (Page 3) — 15 fields ---
  4.1 Assets at Home(tick all that apply) - Washing Machine    [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Fridge             [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - AC                 [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - LED TV             [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Two-Wheeler        [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Car                [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Smartphone         [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Separate Wi-Fi     [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Others:            [text — ALWAYS capture free-text from "Others:______" line even if checkbox is empty; prefix with "Others: " if the text is present]
  NOTE for 4.1 Assets at Home only: scan the ENTIRE area around each "[] text" unit. Any mark (dot, line, scribble, handwriting) anywhere near the box or text → "Yes". Only a clear cross (X/✗) → "No".
   4.2 Amount of Last Electricity Bill     [text — preserve original text including ₹, Rs, /month]
   4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes  [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No   [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
   NOTE: 4.3.1 Row 3 has an EXTRA BLANK AREA below the 4.3 checkboxes at the bottom of page 3. Check that empty space for handwriting and put it in the Row 3 fields if present.
    4.3.1 If Yes, list their properties: [table_header]
      4.3.1 If Yes, list their properties: - Row 3 - Property Description [text]
      4.3.1 If Yes, list their properties: - Row 3 - Owner Name [text]
      4.3.1 If Yes, list their properties: - Row 3 - Approximate Value [text]
""",
     4: """
--- Section 4 — Financial Background (Page 4) — 15 fields ---
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes  [checkbox — ✓ or ✗ — IF ✓ THEN fill 4.3.1 fields below; IF ✗ THEN all 4.3.1 = "N/A"]
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No   [checkbox — ✓ or ✗]
NOTE: 4.3.1 Row 4 has an EXTRA BLANK AREA below the 4.3.1 table and above the 4.4 question on page 4. Check that empty space for handwriting and put it in the Row 4 fields if present.
    4.3.1 If Yes, list their properties: [table_header]
      4.3.1 If Yes, list their properties: - Row 1 - Property Description [text]
      4.3.1 If Yes, list their properties: - Row 1 - Owner Name [text]
      4.3.1 If Yes, list their properties: - Row 1 - Approximate Value [text]
      4.3.1 If Yes, list their properties: - Row 2 - Property Description [text]
      4.3.1 If Yes, list their properties: - Row 2 - Owner Name [text]
      4.3.1 If Yes, list their properties: - Row 2 - Approximate Value [text]
      4.3.1 If Yes, list their properties: - Row 4 - Property Description [text]
      4.3.1 If Yes, list their properties: - Row 4 - Owner Name [text]
      4.3.1 If Yes, list their properties: - Row 4 - Approximate Value [text]
4.4 Apart from your job, is there any other source of income? [radio → Yes | No]
      4.4.1 If Yes, list other sources of income: [table_header]
        4.4.1 If Yes, list other sources of income: - Source of Income [text — ALWAYS check for strikethrough FIRST. If struck through with / or \, output "". Only if NOT struck through, extract handwritten text (even when 4.4=No).]
        4.4.1 If Yes, list other sources of income: - Amount [text — same rule: strikethrough/slash → ""; otherwise extract handwritten text even when 4.4=No.]
      4.5 Income Type — Monthly    [checkbox — ✓ if checked, ✗ if empty]
    4.5 Income Type — Monthly (specify) [text — handwritten text/name NEAR the Monthly checkbox, e.g. "mother"]
    4.5 Income Type — Daily      [checkbox — ✓ if checked, ✗ if empty]
    4.5 Income Type — Daily (specify)   [text — handwritten text/name NEAR the Daily checkbox, e.g. "father"]
    4.5 Income Type — Weekly     [checkbox — ✓ if checked, ✗ if empty]
    4.5 Income Type — Weekly (specify)  [text — handwritten text/name NEAR the Weekly checkbox]
    4.5 Income Type — Ad-Hoc     [checkbox — ✓ if checked, ✗ if empty]
    4.5 Income Type — Ad-Hoc (specify)  [text — handwritten text/name NEAR the Ad-Hoc checkbox]
    4.6 Do you have any loans?              [radio → Yes | No — IF Yes THEN fill 4.6.1 fields below; IF No THEN all 4.6.1 = "N/A"]
      4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount: [table_header]
      TABLE 4.6.1: exactly 3 pre-printed rows (Sr.No. 1, 2, 3), each with 4 columns.
      For EACH of the 3 rows, output 4 separate fields in this format:
        "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Row {n} - Sr.No."          [text]
        "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Row {n} - Loan Purpose"                [text]
        "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Row {n} - Loan Amount Taken"           [text — numbers only]
        "4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Row {n} - Pending Loan Amount"         [text — numbers only]
        Repeat for n=1, 2, 3 (12 fields total). CRITICAL: Do NOT combine rows into one.
      Also scan for any handwritten text BEFORE Row 1 (above the table) or AFTER Row 3 (below the table)
      and include it as an extra row (Row 0 or Row 4) with text in the relevant column.
""",
     5: """
--- Section 4 — Financial Background (Page 5) — 3 fields ---
   4.7 If you choose any college, how much is the college fee? [text — scan the ENTIRE blank space below the label (multiple lines ok). Handwriting may continue on a lower line (e.g. "paid(49000)" below "1,00,000 per year college name"). Combine continuation lines with ", " into one value.]
  4.8 If the college fee is higher, how will you manage it? [text — EXACT answer, no extra]
  4.9 If you do not receive this scholarship, how will you pay the fees? [text — EXACT answer, no extra]

--- Section 5 — Health Information (Page 5) — 2 fields ---
  5.1 Does the student have any health issues? [radio → Yes | No — pick the single EXACT option text]
  5.2 If yes, list the health issues        [text]

--- Section 6 — Student Commitment (Page 5) — 2 fields ---
  6.1 Will you study college for three years without any obstacle? [text — EXACT answer, strip leading/trailing punctuation, output "Yes" not "YES."]
  6.2 If we have a training program within 15 km from your home, can you come? [radio → Yes | No | Maybe — pick the single EXACT option text]
""",
     6: """
--- Section 6 — Student Commitment (Page 6) — 1 field ---
  6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)? [radio → Yes | No — pick the single EXACT option text]

--- Section 7 — Scholarship Information (Page 6) — 1 field ---
  7.1 Has the student received or applied for any other scholarships for their UG degree? [text — EXACT answer, strip prefixes like "Applied:", "Answer:" — output the content only]

--- Section 8 — Volunteer Observation (Page 6) — 3 fields ---
  8.1 What is your opinion about the student, their family members, and their living condition? [text — preserve complete answer, preserve newlines within answer]
  8.2 Will you recommend this student for this scholarship? [radio → Yes | No | Not Sure — pick the single EXACT option text]
  8.3 Any other comments you want to share? [text]
"""
}



