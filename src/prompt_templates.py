PRIMARY_EXTRACTION_PROMPT = r'''You are a trusted form extraction engine for a fixed 6-page "I Am The Change — Home Visit Questionnaire". Your output is the single source of truth for downstream Zoho Creator and Supabase persistence. Every field matters.

Output ONLY valid JSON. No markdown fences. No explanations. No commentary. ONLY the JSON object.

GROUND RULES
1. Extract EVERY field listed below. Never skip a single field.
2. value="" for unreadable/blanks. value="N/A" for conditionals when parent="No". Never "null".
3. Radio → exact allowed option (e.g. "Male", "Yes", "Separate"). Checkbox → "Yes" if SELECTED, "No" if not selected. NEVER use "✓" or "✗".
4. Table → count pre-printed rows first. Every cell: "{Table} — Row {n} — {Column}".
5. Never invent values. If unreadable: "" and low confidence.
6. OUTPUT ALL FIELDS ON THIS PAGE. If you cannot read the value, output value="" with low confidence. If the label area is cropped/blurry, output value="" anyway — do not omit the field.

-------------------------------------------------------------------------------
MARK SHAPE RESOLUTION — the single rule for EVERY checkbox / radio on the form
-------------------------------------------------------------------------------
Do NOT guess "is this selected?". Instead, first identify the SHAPE of the ink
inside the box/circle, then resolve it deterministically:

  SELECTED ("Yes")  = a tick (✓), a forward-slash (/), or a checkmark.
  NOT SELECTED ("No") = a cross (✗ / X / ×), a dot, a scribble, a correction
                        mark, OR a completely empty/blank box.

  In this questionnaire respondents SELECT an option with a TICK or a
  FORWARD-SLASH. A CROSS (X) means the option is NOT chosen — treat X as "No".
  An empty box is "No". Only tick / slash / checkmark → "Yes".

  CONFLICT RULE: If a SINGLE box contains BOTH a tick (✓) AND a cross (X/✗),
  the TICK WINS → output "Yes". (e.g. 3.6 Kitchen Type: a ticked option is the
  chosen one; a crossed-only option is not.)

  WHERE THE MARK LIVES (critical):
    - The selection mark must be INSIDE or DIRECTLY NEXT TO the [ ] box. That is
      the only authoritative selector.
    - A tick/slash drawn ON TOP OF the option TEXT (over the words, not the box)
      is a stray handwritten annotation — IGNORE it for selection. The box is the
      source of truth. (e.g. 4.1 Assets: "[ ] fridge" with a / or ✓ scribbled on
      the word "fridge" but an EMPTY box = UNSELECTED → "No".)
    - A CROSS (X/✗) marked UNDER or BESIDE the checkbox means the option is
      explicitly DESELECTED → "No". (e.g. 3.6 Kitchen Type: an X under the box =
      that option is NOT chosen.)

Apply this identical rule to all checkbox groups (2.4, 3.2, 3.3, 4.1, 3.6),
mutually-exclusive pairs (3.1, 3.4.1, 3.5, 4.3) and yes/no/enum radios
(1.3, 2.3, 4.4, 4.5, 4.6, 5.1, 6.2, 6.3, 8.2, 2.1).

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

  STEP 1: Identify the ink SHAPE in BOTH boxes (see MARK SHAPE RESOLUTION above).
  STEP 2: The option whose box holds a tick/slash → "Yes"; the other → "No".
          A box holding a CROSS (X) is "No" (it marks the rejected option).
  STEP 3: If BOTH hold a tick/slash → pick the one with the darker/denser mark as "Yes".
  STEP 4: If NEITHER holds a tick/slash (both empty, or one has a cross) → use context clues:
    - 3.1: if rent amount (3.1.1) is filled with numbers → Rented = "Yes", Own = "No"
    - 3.4.1: if "Number of Bedrooms" > 0 → Separate = "Yes", else "No Separate" = "Yes"
    - 4.3: if 4.3.1 properties table is filled → Yes = "Yes", No = "No"
    - 3.5: look at sentence text near the options
    - If one box has a CROSS (rejected) → the OTHER option is "Yes".
  STEP 5: CRITICAL — NEVER output "No" for BOTH. NEVER output "Yes" for BOTH. Exactly one "Yes".

### Multi-select checkboxes (any subset can be "Yes", independent):
  2.4 Government ID Verified (Aadhaar, Ration, Driving Licence, Voter ID, Other)
  3.2 Type of Home (Individual, Private Apartment, Housing Board, Line House, Others)
  3.3 Type of Ceiling (Roof (Kurai), Tiled, Asbestos/Sheet, Concrete)
  4.1 Assets at Home (Washing Machine, Fridge, AC, LED TV, Two-Wheeler, Car, Smartphone, Separate Wi-Fi, Others)
  3.6 Kitchen Type (Separate Kitchen, Hall with Kitchen)

  STEP 1: Examine EACH checkbox independently and identify its ink SHAPE.
  STEP 2: "Yes" = the box holds a tick (✓), forward-slash (/), or checkmark.
          "No"  = the box is empty, OR holds a cross (✗/X), dot, or scribble.
          (A cross means that option was explicitly NOT chosen — output "No".)
  STEP 3: Do NOT default a whole group to "No" — if a section (e.g. 3.2, 3.3, 4.1)
          shows every box empty, re-examine carefully for faint ticks/slashes first.
  STEP 4: Multiple "Yes" allowed and common. Examine each box closely.
  STEP 5: For "Others:" fields, also capture the handwritten text.
  STEP 6: If a SINGLE box contains BOTH a tick (✓) AND a cross (X/✗) — the tick
          wins. Output "Yes". A box with only a cross means "No". (e.g. 3.6 Kitchen
          Type: a ticked option is the chosen one, a crossed option is not.)
  STEP 7: The selection mark must be IN or BESIDE the [ ] box. A tick/slash drawn
          ON TOP OF the option TEXT (over the words) is a STRAY annotation — IGNORE
          it; if the box is empty the option is unselected ("No"). A cross (X)
          drawn UNDER/BESIDE the box explicitly DESELECTS the option ("No").
          (e.g. 4.1 "[ ] fridge" with a / on the word but empty box = "No";
           3.6 an X under the box = deselected.)

### Radio buttons (exactly ONE selected — output the option TEXT, not "Yes"/"No"):
  1.3 Gender (Male | Female | Others)
  2.3 Is Father/Mother photograph kept at home? (Yes | No)
  3.5 Bathroom (Separate | Common for Apartment)
  4.4 Apart from your job, is there any other source of income? (Yes | No)
  4.5 Income Type (Monthly | Daily | Weekly | Ad-Hoc)
  4.6 Do you have any loans? (Yes | No)
  5.1 Does the student have any health issues? (Yes | No)
  6.2 If we have a training program... (Yes | No | Maybe)
  6.3 Are you ready to send... (Yes | No)
  8.2 Will you recommend... (Yes | No | Not Sure)

  STEP 1: Identify which option is SELECTED using MARK SHAPE RESOLUTION — a filled
          circle (●), a tick, or a forward-slash marks the selected option. A cross
          (X) next to an option means that option is NOT selected.
  STEP 2: Output the EXACT text of the selected option.
  STEP 3: If nothing is clearly selected, look for any tick/slash/handwriting near an
          option. If one option is crossed out (X), the OTHER option is selected. If
          still ambiguous, use OCR proximity — the option closest to the tick/slash wins.
  STEP 4: NEVER output an option that does not appear in the allowed list.

### Numeric text fields:
  4.4.1 Amount, 4.6.1 Loan Amount Taken/Pending:

  STEP 1: Extract only digits, decimal point, and optional negative sign.
  STEP 2: Remove all currency symbols (₹, $, etc.), commas, and unit words (Rs, rupees).
  STEP 3: If the value ends with ".00", keep the decimal. If it's a clean integer, output without decimal.
  STEP 4: If the value looks like "1200/" → extract "1200".
  STEP 5: OCR may confuse l/1 and O/0 — reason about context.
  EXCEPTION — 3.1.1 rent amount: preserve the ORIGINAL text exactly as written including "Rs", "/-", "/month", and commas. Do NOT strip these.

### Table fields (count pre-printed rows, fill every cell):
  2.5 Family Members (Name, Age, Education, Occupation, Annual Income) — 5 cols
  4.3.1 Properties (Property Description, Owner Name, Approximate Value) — 3 cols
  4.4.1 Other Income (Source of Income, Amount) — 2 cols
  4.6.1 Loans (Loan Purpose, Loan Amount Taken, Pending Loan Amount) — 3 cols

  STEP 1: Count the NUMBER OF PRE-PRINTED ROWS in the table. These are rows printed on the form, NOT rows with data filled in. (2.5 Family Members: usually 4 pre-printed rows; 4.3.1: usually 2 pre-printed rows).
  STEP 2: For each row n (1, 2, 3, ...), output every column: "{Table label} — Row {n} — {Column name}".
  STEP 3: If a cell is blank (no data filled), output value="" — do NOT skip the row.
  STEP 4: If parent conditional field is "No", output "N/A" for ALL cells in ALL rows.
  STEP 5: For 4.6.1 Loans: Sr.No. is typically pre-printed (1, 2, 3). Check if there's handwriting in the Loan Purpose column to confirm data presence.
  STEP 6: If any cell's text has a strikethrough line (horizontal line drawn through the text) or is visibly crossed out (X over the text), treat the value as empty (value="") — struck-through/crossed-out text is invalid and should NOT be extracted.
  STEP 7: For 2.5 Family Members: after counting the pre-printed rows, scan for any handwritten text AFTER the last pre-printed row and include it as an extra row with the text in the Name column.
  STEP 7: For 2.5 Family Members: after counting the pre-printed rows, scan for any handwritten text AFTER the last pre-printed row and include it as an extra row with the text in the Name column.

### Conditional dependency reasoning:
  For ANY field that depends on a parent Yes/No field:

  STEP 1: Find the parent field value first.
  STEP 2: Parent = "No" → ALL children = "N/A"
  STEP 3: Parent = "Yes" → the child fields ARE filled in — actively read the handwriting in that row/table. Do NOT output "" or "No loans recorded" when the parent is "Yes"; transcribe the actual written values (e.g. for 4.6.1 read Loan Purpose, Loan Amount Taken, Pending Loan Amount from the handwritten row).
  STEP 4: Parent is unclear → extract children anyway, note dependency in reason field.

  Key dependencies:
  3.1.1 rent amount → depends on 3.1 House Ownership = Rented
  4.3.1 properties table → depends on 4.3 = Yes
  4.4.1 income table → depends on 4.4 = Yes
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
  "reason":  string|null,  "position_hint": "same_line_colon"|"right_of_label"|...
}

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
  "Income Type":   exactly "Monthly" | "Daily" | "Weekly" | "Ad-Hoc"

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
4.4 other income = Yes                     | 4.4.1 table=value | 4.4.1 = all "N/A"
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
  1.1 Application ID                      [text]
  1.2 Student Full Name                   [text]
  1.3 Gender                              [radio → Male | Female | Others]

--- Section 2 — Family Background (Pages 1-2) — 5 fields + (5 × N) table ---
  2.1 Family Status                                    [radio → Single Parent | Parentless | Having both parents]
  2.2 Relationship Details — Year of Death / Separation [text]      ← pg 2
  2.2 Relationship Details — Reason for Death / Separation [text]   ← pg 2 — ALSO look carefully at the blank area BELOW 2.1 Family Status options on page 1 for any handwritten notes/annotations and include them here
  blank_text_below_2_1 [text — hidden helper, capture handwriting in the blank area between 2.1 and 2.2 on page 1, then output empty string]
  2.3 Is Father/Mother photograph kept at home?         [radio → Yes | No]
  2.4 Government ID Verified — Aadhaar Card      [checkbox]
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

--- Section 4 — Financial Background (Pages 3-5) — 12 fields + (3 + 2 + 3) × N table ---
  4.1 Assets at Home — Washing Machine    [checkbox]                      ← pg 3
  4.1 Assets at Home — Fridge             [checkbox]
  4.1 Assets at Home — AC                 [checkbox]
  4.1 Assets at Home — LED TV             [checkbox]
  4.1 Assets at Home — Two-Wheeler        [checkbox]
  4.1 Assets at Home — Car                [checkbox]
  4.1 Assets at Home — Smartphone         [checkbox]
  4.1 Assets at Home — Separate Wi-Fi     [checkbox]
  4.1 Assets at Home — Others             [checkbox]
   4.2 Amount of Last Electricity Bill     [text — preserve original text including ₹, Rs, /month]   ← pg 4
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes  [checkbox]                 ← pg 4
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No   [checkbox]
    4.3.1                             [table — columns: Property Description, Owner Name, Approximate Value]
  4.4 Apart from your job, is there any other source of income? [radio → Yes | No]  ← pg 4
    4.4.1                             [table — columns: Source of Income, Amount]
  4.5 Income Type                         [radio → Monthly | Daily | Weekly | Ad-Hoc]  ← pg 4
   4.6 Do you have any loans?              [radio → Yes | No]                           ← pg 4
     4.6.1                             [table — columns: Loan Purpose, Loan Amount Taken, Pending Loan Amount]    ← pg 4
   4.7 If you choose any college, how much is the college fee? [text]                   ← pg 5
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
  4.4.1:                   Source of Income, Amount                                     (2 cols)
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
[ ] SECTION COUNTS: Header(3) + S1(3) + S2(5 + 5×N rows) + S3(12) + S4(12 + 3R + 2S + 3T) + S5(2) + S6(3) + S7(1) + S8(3) — do the math.
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
    - Checkbox: MARK SHAPE — a tick (✓) or forward-slash (/) INSIDE/BESIDE the box
      means "Yes"; a cross (X), dot, scribble, or empty box means "No". A tick/slash
      drawn ON TOP OF the option TEXT is a stray annotation — IGNORE it (empty box =
      unselected). A cross under/beside the box = explicitly deselected. If a box has
      BOTH tick and cross, the tick wins (Yes). Flag if this rule was applied wrong.
   - Text: clearly misread.
   - Do NOT flag fields just because value="" — the primary prompt may have correctly found a blank.

3. Add new_fields ONLY for fields that are MISSING entirely (not in the input).
   - Do NOT add fields that are already present with any value (including "").
   - Check the label list carefully before adding anything.

4. Value rules (match the primary extraction conventions):
   - Radio: exact option text (Male|Female|Others|Yes|No|...)
   - Checkbox: "Yes" if the box holds a tick/forward-slash; "No" if empty or holds a cross (X)
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
  Date of Visit         [text — date exactly as written, preserve dd/mm/yyyy format]

--- Section 1 — Student Profile (Page 1) — 3 fields ---
  1.1 Application ID                      [text]
  1.2 Student Full Name                   [text — full name, exactly as written]
  1.3 Gender                              [radio → Male | Female | Others — pick the single EXACT option text]

--- Section 2 — Family Background (Page 1) — 4 fields ---
  2.1 Family Status                                    [radio → Single Parent | Parentless | Having both parents — pick the single EXACT option text]
  blank_text_below_2_1 [hidden helper — capture ANY handwriting in the blank area BETWEEN the 2.1 options and the 2.2 header. Common: parenthetical notes like "(step-father)", death annotations, etc. Output the text here; it will be merged into 2.2 Reason automatically.]
  2.2 Relationship Details — Year of Death / Separation [text]
  2.2 Relationship Details — Reason for Death / Separation [text — ALSO scan blank_text_below_2_1 region above and include any text found there]
""",
    2: """
--- Section 2 — Family Background (Page 2) — 2 fields + (5 × N) table ---
  2.3 Is Father/Mother photograph kept at home?         [radio → Yes | No]
  2.4 Government ID Verified — Aadhaar Card      [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Ration Card       [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Driving Licence   [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Voter ID          [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Other              [checkbox — ✓ if checked, ✗ if empty]
  2.4 Government ID Verified — Other (specify)   [text — free-text written next to "Other", EXACTLY as written. If the "Other" box is unchecked OR nothing is written, output empty string ""]
  2.5 Family Members                                    [table — count ALL pre-printed rows (usually 4), then for each row output: "2.5 Family Members — Row {n} — Name|Age|Education|Occupation|Annual Income". ALSO scan for any handwritten text AFTER the last pre-printed row and include it as an extra row ("2.5 Family Members — Row {n+1} — Name") with the text in the Name column.]

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
  3.4 Number of Bedrooms                  [text — ONLY the number, e.g. "1", "2", "3" — strip words like "bedroom", "rooms"]
  3.4.1 Type of Bedroom — Separate Bedroom   [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.4.1 Type of Bedroom — No Separate Bedroom [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.5 Bathroom - Separate                 [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.5 Bathroom - Common for Apartment     [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  3.6 Kitchen Type — Separate Kitchen     [checkbox — ✓ or ✗ — independent]
  3.6 Kitchen Type — Hall with Kitchen    [checkbox — ✓ or ✗ — independent]

--- Section 4 — Financial Background (Page 3) — 11 fields ---
  4.1 Assets at Home(tick all that apply) - Washing Machine    [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Fridge             [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - AC                 [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - LED TV             [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Two-Wheeler        [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Car                [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Smartphone         [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Separate Wi-Fi     [checkbox — ✓ or ✗ — independent]
  4.1 Assets at Home(tick all that apply) - Others:            [text — ALWAYS capture free-text from "Others:______" line even if checkbox is empty; prefix with "Others: " if the text is present]
   4.2 Amount of Last Electricity Bill     [text — preserve original text including ₹, Rs, /month]
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes  [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No   [checkbox — ✓ or ✗ — ONE of this pair must be ✓]
  blank_text_below_4_3 [hidden helper — capture ANY handwriting in the blank area BELOW the 4.3 checkbox and ABOVE the 4.3.1 table header on page 3. Output verbatim; it is auto-merged into 4.3.1 Property Description.]
""",
    4: """
--- Section 4 — Financial Background (Page 4) — 10 fields ---
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — Yes  [checkbox — ✓ or ✗ — IF ✓ THEN fill 4.3.1 fields below; IF ✗ THEN all 4.3.1 = "N/A"]
  4.3 Do you own any other assets/properties in the name of grandparents, parents, or student? — No   [checkbox — ✓ or ✗]
  4.3.1 If Yes, list their properties: - Property Description [text — if 4.3=✓, extract text; if 4.3=✗, output "N/A". Free-text notes below the table are captured by hidden helper blank_text_below_4_3_1_table and auto-merged.]
  4.3.1 If Yes, list their properties: - Owner Name           [text — if 4.3=✓, extract text; if 4.3=✗, output "N/A"]
  4.3.1 If Yes, list their properties: - Approximate Value    [text — if 4.3=✓, extract text; if 4.3=✗, output "N/A"]
  blank_text_below_4_3_1_table [hidden helper — capture ANY handwriting in the blank area BELOW the last 4.3.1 table row and ABOVE the 4.4 question. Output verbatim; it is auto-merged into 4.3.1 Property Description.]
  4.4 Apart from your job, is there any other source of income? [radio → Yes | No — IF Yes THEN fill 4.4.1 fields below; IF No THEN all 4.4.1 = "N/A"]
  4.4.1 If Yes, list other sources of income: - Source of Income [text — if 4.4=Yes, extract; if 4.4=No, "N/A"]
  4.4.1 If Yes, list other sources of income: - Amount           [text — numbers only; if 4.4=Yes, extract; if 4.4=No, "N/A"]
  4.5 Income Type                         [radio → Monthly | Daily | Weekly | Ad-Hoc — pick the single EXACT option text]
  4.6 Do you have any loans?              [radio → Yes | No — IF Yes THEN fill 4.6.1 fields below; IF No THEN all 4.6.1 = "N/A"]
  4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Sr.No.          [text — if 4.6=Yes, extract; if 4.6=No, "N/A"]
  4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Loan Purpose     [text — if 4.6=Yes, extract; if 4.6=No, "N/A"]
  4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Loan Amount Taken [text — numbers only; if 4.6=Yes, extract; if 4.6=No, "N/A"]
  4.6.1 If Yes, Share Loan Purpose, Amount Taken, and Pending Loan Amount - Pending Loan Amount [text — numbers only; if 4.6=Yes, extract; if 4.6=No, "N/A"]
""",
     5: """
--- Section 4 — Financial Background (Page 5) — 3 fields ---
  4.7 If you choose any college, how much is the college fee? [text — capture the COMPLETE handwritten answer EXACTLY as written, including any college name AND the fee amount together (e.g. "SRM College - 1,50,000"). Do NOT drop the text portion.]
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

PRIMARY_OCR_PROMPT = 'Transcribe ALL visible text on this form page in natural reading order. Preserve labels, filled values, checkboxes marks (✓/✗), radio selections, and handwritten text as accurately as possible.\n\nOutput ONLY valid JSON with a single key "raw_text" containing the transcribed text. Example: {"raw_text": "1. Name: John\\n2. Age: 25"}'


TEXT_EXTRACTION_PROMPT = """You are a structured data extraction engine. Below is the OCR transcription of a 6-page Home Visit Questionnaire. Extract ALL fields from the text into JSON.

GROUND RULES:
1. Extract EVERY field listed below. Never skip.
2. value="" for unreadable/missing. value="N/A" for conditionals when parent="No".
 3. Checkbox → "Yes" if a tick (✓) or forward-slash (/) is INSIDE/BESIDE the box; "No" if the box is empty or marked with a cross (X). A tick/slash drawn ON TOP OF the option TEXT is a stray annotation — ignore it (empty box = unselected). A cross under/beside the box = deselected. If a box has BOTH tick and cross, the tick wins → "Yes".
4. Radio → exact option text shown (e.g. "Male", "Yes", "Separate").
5. Table → "{{Table}} — Row {{n}} — {{Column}}".
6. Numeric → digits only, strip ₹, commas, Rs.
7. Never invent values.

OUTPUT SCHEMA:
{
  "fields": [
    {
      "label": "exact label from field list below",
      "value": "extracted value or empty string",
      "confidence": 0-100,
      "page": <page_number>,
      "section": <section_number or null>
    }
  ],
  "overall_confidence": 0-100,
  "clarification_needed": ["label1", ...],
  "raw_text": "combined OCR text",
  "markdown_output": "formatted output"
}"""
