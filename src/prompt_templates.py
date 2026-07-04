PRIMARY_EXTRACTION_PROMPT = r'''You are a precise structured form extraction system.

Your task is to analyze a multi-page scanned questionnaire and extract ALL fields exhaustively from the document.

Return ONLY one valid JSON object.
Do not return markdown fences.
Do not add explanations.
Do not omit any listed field.

-------------------------------------------------------------------------------
1. OUTPUT FORMAT (STRICT)
-------------------------------------------------------------------------------

Return exactly this top-level structure:

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

Rules:
- Sort all fields by page ascending.
- Use exact labels from the template below.
- Include every listed field, even if blank, unclear, not applicable, cropped, or conditionally hidden.
- Use null only where explicitly allowed.

-------------------------------------------------------------------------------
2. UNIVERSAL FIELD RULES
-------------------------------------------------------------------------------

For every field:
- "label": exact printed label text from the template.
- "value": extracted content using the field-specific rules below.
- "confidence": 0-100.
- "confidence_reason": brief reason for confidence score.
- "page": page number where the field appears.
- "section": integer section number from the leading number before the first dot; header fields use null.
- "needs_clarification": true if blank, illegible, ambiguous, cropped, or confidence < 70.
- "reason": null if confidence >= 70 and no clarification needed; otherwise explain what is uncertain.
- "position_hint": one of:
  - "same_line_colon"
  - "right_of_label"
  - "below_label"
  - "above_label"

Confidence guidance:
- 90-100 = clearly visible and unambiguous.
- 70-89 = mostly readable with slight uncertainty.
- 50-69 = ambiguous, blurry, or partially unclear.
- 10-49 = mostly unclear, blank, cropped, or guessed.

If field is blank:
- value = ""
- confidence = 10-20
- confidence_reason = "field appears empty"
- needs_clarification = true

If field is cropped/not visible:
- value = ""
- confidence = 5-15
- confidence_reason = "field cropped or not visible"
- needs_clarification = true

If condition is not met for an "If yes" field:
- value = "N/A"
- confidence_reason = "condition not met; field not applicable"
- needs_clarification = false unless visibility is unclear

-------------------------------------------------------------------------------
3. PAGE GROUNDING RULE
-------------------------------------------------------------------------------

For each field:
1. First identify the page where the field label appears.
2. Extract the value from that page's layout.
3. If OCR order conflicts with visual structure, trust the visual layout, printed label, and table boundaries over OCR order.
4. Do not borrow values from neighboring sections.

-------------------------------------------------------------------------------
4. HEADER FIELDS
-------------------------------------------------------------------------------

Extract these 3 header fields from page 1:
- "Volunteer Name"
- "Co-Volunteer Name"
- "Date of Visit"

Rules:
- section = null
- position_hint = "same_line_colon"
- Always include all three.

-------------------------------------------------------------------------------
5. RADIO BUTTON RULE
-------------------------------------------------------------------------------

For radio groups:
- Each group is ONE field.
- value = selected option text only.
- If no option selected, value = "".
- Use the exact option text.

Example:
"1.3 Gender" -> "Female"
"4.5 Income Type" -> "Daily"
"8.2 Will you recommend this student for this scholarship?" -> "Yes"

-------------------------------------------------------------------------------
6. CHECKBOX GROUP RULE (UNIVERSAL)
-------------------------------------------------------------------------------

Every checkbox option must be extracted as a separate field using this exact label format:

"{Parent Label} — {Option}"

Value rules:
- "✓" = checked
- "✗" = visible and unchecked
- "" = option not visible/cropped/unclear

Apply this same layout consistently to ALL checkbox groups in the form, including:
- 3.2 Type of Home
- 3.3 Type of Ceiling
- 3.6 Kitchen Type
- 4.1 Assets at Home

Examples:
- "3.2 Type of Home — Individual"
- "3.3 Type of Ceiling — Concrete"
- "4.1 Assets at Home — Car"

IMPORTANT:
- Never merge checkbox options into one field.
- Never skip unchecked options.
- If an option label exists but the check area is unclear, still output the field with low confidence.

-------------------------------------------------------------------------------
7. TABLE RULE (UNIVERSAL)
-------------------------------------------------------------------------------

For every table:
- Extract every visible row in top-to-bottom order.
- Extract every column in each row as a separate field.
- Keep row numbering consistent from the first visible data row.
- Do NOT skip blank rows if the form visibly provides them.
- Do NOT invent rows that are not present.

Label format:
"{Section.Label} — Row {n} — {ColumnName}"

Cell value rules:
- visible text -> exact text
- visible blank cell -> ""
- condition unmet -> "N/A"
- unreadable/cropped -> best guess or "" with low confidence

CRITICAL:
- BLANK means the printed cell exists and is empty.
- N/A means the field is not applicable because the parent condition is not met.

-------------------------------------------------------------------------------
8. RAW MARKDOWN TRANSCRIPTION RULES
-------------------------------------------------------------------------------

Create BOTH:
- "raw_text": a full Markdown transcription
- "markdown_output": a cleaner human-friendly Markdown version

For BOTH fields:
- Separate pages using: "\n\n--- Page {n} ---\n\n"
- Use Markdown headings for sections.
- Every question label MUST be in bold.
- Preserve layout as much as possible.
- Use Markdown tables where the original uses tables.
- Show radio options with:
  - [●] selected
  - [○] unselected
- Show checkboxes with:
  - [✓] checked
  - [✗] unchecked
  - [—] unknown/not visible

Question formatting rule:
- Every question or field label must be bold, for example:
  - **1.1 Application ID:** TEMP - 2026 - 9597
  - **4.8 If the college fee is higher, how will you manage it?:** lending money (Extra work)

markdown_output formatting improvements:
- Add a title at the top.
- Keep section headings clean.
- Use proper tables with headers.
- Group repeated checkbox fields under a bold parent question.
- Preserve answers clearly for human review.
- Every question remains bold.

-------------------------------------------------------------------------------
9. FIELD TEMPLATE (EXTRACT ALL OF THESE)
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
10. TABLE ROW EXPECTATIONS FOR THIS FORM
-------------------------------------------------------------------------------

Use the visible pre-printed rows in the form layout.
For this questionnaire structure, extract all visible rows in these tables:
- 2.2 Relationship Details table
- 2.5 Family Members table
- 4.3.1 Properties table
- 4.4.1 Other Sources of Income table
- 4.6.1 Loan Details table

If a row is visibly present but empty, output all cells for that row with value = "".
If the table is conditional and the answer is "No", output all visible rows and cells with value = "N/A".

-------------------------------------------------------------------------------
11. FINAL QUALITY RULES
-------------------------------------------------------------------------------

Before returning JSON, ensure:
- All listed fields are present.
- All checkbox options are represented individually.
- All radio groups contain only the selected option text.
- All visible table cells are extracted.
- All question labels in raw_text and markdown_output are bold.
- markdown_output is clean, readable, and useful for a human reviewer.
- sections array includes all sections 1 through 8.

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

Existing fields from first pass:
{fields_json}
'''