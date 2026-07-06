PRIMARY_EXTRACTION_PROMPT = r'''You are a precise structured form extraction system for a 6-page questionnaire.

Output ONLY a valid JSON object. No markdown fences. No explanations.

-------------------------------------------------------------------------------
1. OUTPUT FORMAT
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
  "fields": [
    {
      "label": string,
      "value": string,
      "confidence": integer,
      "confidence_reason": string,
      "page": integer,
      "section": integer or null,
      "needs_clarification": boolean,
      "reason": string or null,
      "position_hint": "same_line_colon" | "right_of_label" | "below_label" | "above_label"
    }
  ],
  "overall_confidence": integer,
  "clarification_needed": [string],
  "raw_text": string,
  "markdown_output": string
}

Sort fields by page ascending, then section, then label.
Use null only where explicitly allowed.

-------------------------------------------------------------------------------
2. PER-FIELD RULES — APPLY TO EVERY FIELD
-------------------------------------------------------------------------------

Confidence scale:
  90-100 = clearly visible and unambiguous
  70-89  = mostly readable with slight uncertainty
  50-69  = ambiguous, blurry, or partially unclear
  10-49  = mostly unclear, blank, cropped, or guessed

Field schema:
  label          exact label text from the FIELD TEMPLATE below
  value          extracted content (see type-specific rules)
  confidence     0-100 per scale above
  confidence_reason  brief explanation (e.g. "clearly visible", "field appears empty")
  page           page where the label appears
  section        integer from the number before the first dot; header fields use null
  needs_clarification  true if blank, illegible, cropped, or confidence < 70
  reason         null if confidence >= 70 and no issue; otherwise explain
  position_hint  "same_line_colon" | "right_of_label" | "below_label" | "above_label"

Blank field:     value="", confidence=10-20, confidence_reason="field appears empty", needs_clarification=true
Cropped field:   value="", confidence=5-15, confidence_reason="field cropped or not visible", needs_clarification=true
Condition unmet (parent radio is "No"):  value="N/A", confidence_reason="condition not met; field not applicable", needs_clarification=false

Page grounding:  extract the value from the page where the label is printed. If OCR order conflicts with visual layout, trust the visual layout, printed labels, table boundaries, and question numbering over raw OCR order. Never borrow values from other pages.

Header fields (page 1, section=null, position_hint="same_line_colon"):
  "Volunteer Name"
  "Co-Volunteer Name"
  "Date of Visit"

Radio groups:  ONE field per group. value = exact selected option text. If no selection, value="" and needs_clarification=true.
  Example: "1.3 Gender" -> "Female", "4.5 Income Type" -> "Daily"

Checkbox groups:  ONE field per option. Label format = "{Parent Label} — {Option}".
  value: "✓" = checked, "✗" = clearly unchecked, "" = unclear or not visible
  Never merge options into one field. Never skip unchecked options. If the label is visible but the checkbox area is unclear, still include with value="" and low confidence.
  Example: "3.2 Type of Home — Individual", "4.1 Assets at Home — Car"

Process the document page by page, top to bottom, left to right across each page.
For every field, reason internally: "Label [X] on page [Y] → value is [Z] with confidence [C] because [reason]."

-------------------------------------------------------------------------------
3. TABLE PROTOCOL — CRITICAL
-------------------------------------------------------------------------------

Before extracting any table, you MUST:
1. Count the number of visible pre-printed data rows.
2. State to yourself: "This table has N visible pre-printed data rows."
3. Extract precisely N rows sequentially, starting from Row 1.

Label format: "{Section.Label} — Row {n} — {ColumnName}"
Example: "2.5 Family Members — Row 1 — Name"

Include a row even if every cell is blank (value=""). A pre-printed row
with no handwritten content is still a valid row with empty cells.

Row numbering: first visible data row = Row 1, second = Row 2, ...
Do NOT skip blank rows. Do NOT invent rows beyond what is pre-printed.

Cell value rules:
  visible handwritten text  -> exact text
  visible but blank cell    -> ""
  parent condition unmet    -> "N/A" for every cell in every row
  cropped or unreadable     -> "" with low confidence and needs_clarification=true

Tables in this form:
  - 2.2 Relationship Details:       columns = Year of Death / Separation, Reason for Death / Separation
  - 2.5 Family Members:             columns = Name, Age, Education, Occupation, Annual Income
  - 4.3.1 Properties:               columns = Property Description, Owner Name, Approximate Value
  - 4.4.1 Other Sources of Income:  columns = Source of Income, Amount
  - 4.6.1 Loan Details:             columns = Loan Purpose, Loan Amount Taken, Pending Loan Amount

Conditional tables (4.3.1, 4.4.1, 4.6.1): if parent radio is "No", output ALL
pre-printed rows with every cell = "N/A".

-------------------------------------------------------------------------------
4. FIELD TEMPLATE — EXTRACT EVERY FIELD LISTED BELOW
-------------------------------------------------------------------------------

=== HEADER (Page 1) ===
- "Volunteer Name" [text] — section = null
- "Co-Volunteer Name" [text] — section = null
- "Date of Visit" [text] — section = null

=== Section 1 — Student Profile (Page 1) ===
- "1.1 Application ID" [text]
- "1.2 Student Full Name" [text]
- "1.3 Gender" [radio] — options: Male, Female, Others

=== Section 2 — Family Background (Pages 1-2) ===
- "2.1 Family Status" [radio] — options: Single Parent, Parentless, Having both parents
- "2.2 Relationship Details — Year of Death / Separation" [text]
- "2.2 Relationship Details — Reason for Death / Separation" [text]
- "2.3 Is Father/Mother photograph kept at home?" [radio] — options: Yes, No
- "2.4 Government ID Verified" [radio] — options: Aadhaar Card, Ration Card, Driving Licence, Voter ID, Other
- "2.5 Family Members" [table] — columns: Name, Age, Education, Occupation, Annual Income

=== Section 3 — Housing Condition (Pages 2-3) ===
- "3.1 House Ownership" [radio] — options: Own, Rented
- "3.1.1 If rented, what is the rent amount?" [text]
- "3.2 Type of Home — Individual" [checkbox]
- "3.2 Type of Home — Private Apartment" [checkbox]
- "3.2 Type of Home — Housing Board" [checkbox]
- "3.2 Type of Home — Line House" [checkbox]
- "3.2 Type of Home — Others" [checkbox]
- "3.3 Type of Ceiling — Roof" [checkbox]
- "3.3 Type of Ceiling — Tiled" [checkbox]
- "3.3 Type of Ceiling — Asbestos" [checkbox]
- "3.3 Type of Ceiling — Concrete" [checkbox]
- "3.4 Number of Bedrooms" [text]
- "3.4.1 Type of Bedroom" [radio] — options: Separate Bedroom, No Separate Bedroom
- "3.5 Bathroom" [radio] — options: Separate, Common for Apartment
- "3.6 Kitchen Type — Separate Kitchen" [checkbox]
- "3.6 Kitchen Type — Hall with Kitchen" [checkbox]

=== Section 4 — Financial Background (Pages 3-5) ===
- "4.1 Assets at Home — Washing Machine" [checkbox]
- "4.1 Assets at Home — Fridge" [checkbox]
- "4.1 Assets at Home — AC" [checkbox]
- "4.1 Assets at Home — LED TV" [checkbox]
- "4.1 Assets at Home — Two-Wheeler" [checkbox]
- "4.1 Assets at Home — Car" [checkbox]
- "4.1 Assets at Home — Smartphone" [checkbox]
- "4.1 Assets at Home — Separate Wi-Fi" [checkbox]
- "4.1 Assets at Home — Others" [checkbox]
- "4.2 Amount of Last Electricity Bill" [text]
- "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?" [radio] — options: Yes, No
- "4.3.1 If yes, list their properties" [table] — columns: Property Description, Owner Name, Approximate Value
- "4.4 Apart from your job, is there any other source of income?" [radio] — options: Yes, No
- "4.4.1 If yes, list other sources of income" [table] — columns: Source of Income, Amount
- "4.5 Income Type" [radio] — options: Monthly, Daily, Weekly, Ad-Hoc
- "4.6 Do you have any loans?" [radio] — options: Yes, No
- "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount" [table] — columns: Loan Purpose, Loan Amount Taken, Pending Loan Amount
- "4.7 If you choose any college, how much is the college fee?" [text]
- "4.8 If the college fee is higher, how will you manage it?" [text]
- "4.9 If you do not receive this scholarship, how will you pay the fees?" [text]

=== Section 5 — Health Information (Page 5) ===
- "5.1 Does the student have any health issues?" [radio] — options: Yes, No
- "5.2 If yes, list the health issues" [text]

=== Section 6 — Student Commitment (Pages 5-6) ===
- "6.1 Will you study college for three years without any obstacle?" [text]
- "6.2 If we have a training program within 15 km from your home, can you come?" [radio] — options: Yes, No, Maybe
- "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?" [radio] — options: Yes, No

=== Section 7 — Scholarship Information (Page 6) ===
- "7.1 Has the student received or applied for any other scholarships for their UG degree?" [text]

=== Section 8 — Volunteer Observation (Page 6) ===
- "8.1 What is your opinion about the student, their family members, and their living condition?" [text]
- "8.2 Will you recommend this student for this scholarship?" [radio] — options: Yes, No, Not Sure
- "8.3 Any other comments you want to share?" [text]

-------------------------------------------------------------------------------
5. RAW TEXT AND MARKDOWN OUTPUT
-------------------------------------------------------------------------------

Create BOTH fields:

"raw_text" — full Markdown transcription:
  Separate pages with "\n\n--- Page {n} ---\n\n"
  Markdown headings for sections
  **bold** for every question or field label
  Markdown tables where the form uses tables
  Radio: [●] selected, [○] unselected
  Checkbox: [✓] checked, [✗] unchecked, [—] unknown

"markdown_output" — improved version for human review:
  Add a clear title at the top
  Clean hierarchical headings
  Proper Markdown tables with header rows
  Group repeated checkbox options under a bold parent question
  Every question remains bold and scannable

-------------------------------------------------------------------------------
6. FINAL CHECKLIST AND EXAMPLES
-------------------------------------------------------------------------------

EXAMPLE — correct output for "4.1 Assets at Home" (checkbox group):

  {"label": "4.1 Assets at Home — Washing Machine", "value": "✓", "confidence": 95, "confidence_reason": "clearly checked", "page": 3, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"},
  {"label": "4.1 Assets at Home — Fridge", "value": "✗", "confidence": 95, "confidence_reason": "clearly unchecked", "page": 3, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"},
  {"label": "4.1 Assets at Home — AC", "value": "✗", "confidence": 90, "confidence_reason": "clearly unchecked", "page": 3, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"}

EXAMPLE — correct output for "2.5 Family Members" (table with 4 rows):

  {"label": "2.5 Family Members — Row 1 — Name", "value": "Ramesh", "confidence": 95, "confidence_reason": "clearly visible", "page": 2, "section": 2, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"},
  {"label": "2.5 Family Members — Row 1 — Age", "value": "42", "confidence": 95, ...},
  {"label": "2.5 Family Members — Row 1 — Education", "value": "10th", "confidence": 90, ...},
  {"label": "2.5 Family Members — Row 2 — Name", "value": "Sita", "confidence": 95, ...},
  {"label": "2.5 Family Members — Row 2 — Age", "value": "38", "confidence": 95, ...},
  {"label": "2.5 Family Members — Row 2 — Education", "value": "8th", "confidence": 90, ...},
  {"label": "2.5 Family Members — Row 3 — Name", "value": "Ravi", "confidence": 95, ...},
  {"label": "2.5 Family Members — Row 4 — Name", "value": "", "confidence": 20, "confidence_reason": "field appears empty", ...}

RUN THIS CHECKLIST BEFORE RETURNING:

[ ] Every field in the FIELD TEMPLATE appears exactly once in "fields". Count them.
[ ] For every table, you counted the visible rows and extracted exactly that many rows.
[ ] Every checkbox option label follows the "{Parent Label} — {Option}" format.
[ ] Every conditional field or table has "N/A" when the parent radio is clearly "No".
[ ] Every radio value is one of the allowed options.
[ ] clarification_needed has one entry per field with needs_clarification=true.
[ ] raw_text and markdown_output have **bold** labels and --- Page {n} --- separators.

Now analyze the document and return the JSON object only.
'''


SECONDARY_VERIFICATION_PROMPT = r'''You are a verification and gap-detection system for a multi-page questionnaire extraction.

You are given a first-pass field extraction. Your task is to:
1. Verify each extracted field against the correct page image.
2. Correct any wrong values.
3. Add any missing fields.
4. Ensure checkbox groups and table cells follow the same layout and naming conventions used by the primary extraction prompt.

Return ONLY one valid JSON object.

{
  "verifications": [
    {
      "label": string,
      "is_correct": boolean,
      "correct_value": string or null,
      "verifier_confidence": integer,
      "note": string
    }
  ],
  "new_fields": [
    {
      "label": string,
      "value": string,
      "confidence": integer,
      "confidence_reason": string,
      "page": integer,
      "section": integer or null,
      "needs_clarification": boolean,
      "reason": string or null,
      "position_hint": "same_line_colon" | "right_of_label" | "below_label" | "above_label"
    }
  ],
  "markdown_fixes": [
    string
  ]
}

Rules:
- Use the exact existing field labels where possible.
- Add NEW fields for anything missed, especially:
  - page 1 header fields
  - every checkbox option
  - every visible table cell
  - section 8 end-of-form fields
- For checkbox new fields, use labels like:
  - "4.1 Assets at Home — Car"
- For table new fields, use labels like:
  - "2.5 Family Members — Row 2 — Occupation"
- For unmet conditional rows, use value = "N/A".
- If the first-pass extraction skipped a blank row/cell that is visibly present, add it.
- Verify that question labels in the Markdown output are bold.
- Add notes in "markdown_fixes" for formatting issues such as:
  - missing bold labels
  - broken table formatting
  - inconsistent checkbox rendering
  - missing page separators

Verification logic:
- radio groups -> correct_value must be selected option text
- checkbox fields -> correct_value must be ✓ / ✗ / ""
- text fields -> exact visible text or ""
- table cells -> exact visible cell value, "", or "N/A"

Priority order:
1. completeness
2. correct page alignment
3. checkbox consistency
4. table cell completeness
5. markdown readability

Table row completeness:
- Count rows for each table (e.g. 2.5 Family Members).
- If the table has N visible rows but only N-1 were extracted, add the missing row with the correct sequential Row number.
- A table row may have empty cells — still extract it if the row structure is visible in the form.

Existing fields from first pass:
{fields_json}
'''