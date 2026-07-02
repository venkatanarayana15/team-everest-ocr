PRIMARY_EXTRACTION_PROMPT = """You are a precise form extraction system. Analyze the document and extract ALL form fields exhaustively.

For each field, output a JSON object with:
  - "label": the printed field label text (e.g. "3.1 Name of Applicant", "1.3 Gender")
  - "value": the filled-in value — see rules below for checkboxes, radio buttons, and tables
  - "confidence_tier": "high" (clearly legible), "medium" (some uncertainty), "low" (illegible/ambiguous)
  - "page": the page number where the field appears (1-indexed)
  - "section": the section number this field belongs to (e.g., 1 for "1.1 Name", 4 for "4.1 Assets at Home"). If the field is not under a numbered section, use null
  - CRITICAL: EVERY field MUST include "section". For checkbox options like "4.1 Assets at Home — Washing Machine" → section = 4 (parent section). For table rows like "2.5 Family Members — Row 1 — Name" → section = 2. For sub-questions like "3.4.1 Type of Bedroom" → section = 3 (leading number before first dot).
  - "needs_clarification": true if the value is illegible, ambiguous, or missing
  - "reason": if confidence is medium or low, explain WHY you are uncertain
  - "position_hint": "same_line_colon" (label: value on same line), "right_of_label" (value to right), "below_label" (value on next line), "above_label" (value above)

EXTRACT EVERY FIELD — do not skip any:
  - Section headers are NOT fields — skip them
  - Numbered fields (1.1, 2.3, 4.6.1, etc.) ARE fields — extract every one
  - Sub-questions (4.3.1, 4.4.1, 5.2, etc.) ARE fields — extract them
  - Text input fields — extract the handwritten/typed value
  - Radio button groups — extract the SELECTED option as the value
  - Checkbox groups — extract each option individually as a separate field
  - Table rows — extract each row as a separate field with row number
  - CRITICAL: Extract ALL cells in a table row, even if the cell is blank/empty
  - CRITICAL: If a Yes/No question has extra sub-fields (4.3.1, 4.4.1, 5.2), always include them even if condition is "No" (value = "N/A")

HEADER FIELDS (page 1, before Section 1 — these are NOT numbered):
  - "Volunteer Name": the name of the visiting volunteer (label has colon)
  - "Co-Volunteer Name": co-volunteer name (label has colon)
  - "Date of Visit": date of the home visit (label has colon)
  - These appear at the very top of page 1 in a single line with colons. Extract all three.
  - Use section = null for these header fields since they are not under a numbered section

RADIO BUTTON rules (single select — only one option chosen):
  - Each group is ONE field. The value is the selected option text.
  - Example: 1.3 Gender → "Male" (not a list, not ✓/✗)
  - Example: 3.1 House Ownership → "Rented"
  - If no option is selected → value = "", needs_clarification = true

CHECKBOX rules (multi-select — several may be checked):
  - Each option is a SEPARATE field with label = "Section.Label — Option"
  - Example: "4.1 Assets at Home — Washing Machine" value = "✓" if checked, "✗" if unchecked
  - Do NOT merge them into one field

YES/NO fields:
  - If the question has "Yes" and "No" options below it, extract as ONE field
  - Value = "Yes" or "No" (the selected one, not ✓/✗)

CONDITIONAL fields (e.g. "4.3.1 If yes, list..."):
  - Always include the conditional sub-fields, even if the condition answer is "No"
  - If condition is unmet → value = "N/A"

TABLE fields (e.g. "2.5 Family Members"):
  - Extract each row as a SEPARATE field
  - Label = "{Section.Label} — Row {n} — {ColumnName}"
  - Value = the cell content (empty string if blank)
  - Example: "2.5 Family Members — Row 1 — Name" value = "Ravi"
  - Example: "2.5 Family Members — Row 1 — Age" value = "45"

HERE IS THE COMPLETE FORM TEMPLATE — extract every field listed below.
For each field, determine the actual filled-in value from the document.
Fields marked [text] are text inputs. Fields marked [radio] are single-select radio buttons.
Fields marked [checkbox] are multi-select checkboxes. Fields marked [table] are table rows.

=== HEADER (Page 1) ===
- "Volunteer Name" [text] — section = null
- "Co-Volunteer Name" [text] — section = null
- "Date of Visit" [text] — section = null

=== Section 1 — Student Profile (Page 1) ===
- "1.1 Application ID" [text]
- "1.2 Student Full Name" [text]
- "1.3 Gender" [radio] — options: Male, Female, Others

=== Section 2 — Family Background (Pages 1-2) ===
- "2.1 Family Status" [radio] (Page 1) — options: Single Parent, Parentless, Having both parents
- "2.2 Relationship Details (if applicable)" (Page 1) — sub-fields:
  - "2.2 Relationship Details — Year of Death / Separation" [text]
  - "2.2 Relationship Details — Reason for Death / Separation" [text]
- "2.3 Is Father/Mother photograph kept at home?" [radio] (Page 2) — options: Yes, No
- "2.4 Government ID Verified" [radio] (Page 2) — options: Aadhaar Card, Ration Card, Driving Licence, Voter ID, Other
- "2.5 Family Members" [table] (Page 2) — columns: Name, Age, Education, Occupation, Annual Income. Extract each row.

=== Section 3 — Housing Condition (Pages 2-3) ===
- "3.1 House Ownership" [radio] (Page 2) — options: Own, Rented
- "3.1.1 If rented, what is the rent amount?" [text] (Page 2)
- "3.2 Type of Home" [checkbox] (Page 2) — options: Individual, Private Apartment, Housing Board, Line House, Others
- "3.3 Type of Ceiling" [checkbox] (Page 3) — options: Roof, Tiled, Asbestos, Concrete
- "3.4 Number of Bedrooms" [text] (Page 3)
- "3.4.1 Type of Bedroom" [radio] (Page 3) — options: Separate Bedroom, No Separate Bedroom
- "3.5 Bathroom" [radio] (Page 3) — options: Separate, Common for Apartment
- "3.6 Kitchen Type" [checkbox] (Page 3) — options: Separate Kitchen, Hall with Kitchen

=== Section 4 — Financial Background (Pages 3-5) ===
- "4.1 Assets at Home" [checkbox] (Page 3) — options: Washing Machine, Fridge, AC, LED TV, Two-Wheeler, Car, Smartphone, Separate Wi-Fi, Others
- "4.2 Amount of Last Electricity Bill" [text] (Page 3)
- "4.3 Do you own any other assets/properties in the name of grandparents, parents, or student?" [radio] (Page 3) — options: Yes, No
- "4.3.1 If yes, list their properties" [table] (Page 3) — columns: Property Description, Owner Name, Approximate Value. Extract each row. Value = "N/A" for all if 4.3 is No.
- "4.4 Apart from your job, is there any other source of income?" [radio] (Page 4) — options: Yes, No
- "4.4.1 If yes, list other sources of income" [table] (Page 4) — columns: Source of Income, Amount. Extract each row. Value = "N/A" if 4.4 is No.
- "4.5 Income Type" [radio] (Page 4) — options: Monthly, Daily, Weekly, Ad-Hoc
- "4.6 Do you have any loans?" [radio] (Page 4) — options: Yes, No
- "4.6.1 If yes, share Loan Purpose, Amount Taken, and Pending Loan Amount" [table] (Page 4) — columns: Loan Purpose, Loan Amount Taken, Pending Loan Amount. Extract each row. Value = "N/A" for all if 4.6 is No.
- "4.7 If you choose any college, how much is the college fee?" [text] (Page 4)
- "4.8 If the college fee is higher, how will you manage it?" [text] (Page 5)
- "4.9 If you do not receive this scholarship, how will you pay the fees?" [text] (Page 5)

=== Section 5 — Health Information (Page 5) ===
- "5.1 Does the student have any health issues?" [radio] (Page 5) — options: Yes, No
- "5.2 If yes, list the health issues" [text] (Page 5) — value = health issue description, or "N/A" if 5.1 is No

=== Section 6 — Student Commitment (Page 5) ===
- "6.1 Will you study college for three years without any obstacle?" [text] (Page 5) — free text answer
- "6.2 If we have a training program within 15 km from your home, can you come?" [radio] (Page 5) — options: Yes, No, Maybe
- "6.3 Are you ready to send your son/daughter to weekly skill development classes on Sundays (16 classes a year)?" [radio] (Page 5) — options: Yes, No

=== Section 7 — Scholarship Information (Page 6) ===
- "7.1 Has the student received or applied for any other scholarships for their UG degree?" [text] (Page 6) — free text answer

=== Section 8 — Volunteer Observation (Page 6) ===
- "8.1 What is your opinion about the student, their family members, and their living condition?" [text] (Page 6)
- "8.2 Will you recommend this student for this scholarship?" [radio] (Page 6) — options: Yes, No, Not Sure
- "8.3 Any other comments you want to share?" [text] (Page 6)

IMPORTANT — Be honest about where you get stuck:
  - If handwriting is illegible → confidence_tier "low", reason "unclear handwriting"
  - If the field is blank → value = "" (empty string), confidence_tier "low", needs_clarification = true, reason "field appears empty"
  - If you can't decide between two possible values → pick the most likely, set confidence_tier appropriately, add reason explaining the ambiguity
  - If the field is completely cut off in the image → value = "", needs_clarification = true, reason "field cropped in image"
  - For checkbox options that are NOT visible on the page at all (cropped/off-screen), still include them with value = "" and needs_clarification = true

After all fields, provide:
  - "overall_confidence": document-level extraction confidence 0-100
  - "clarification_needed": list of specific issues requiring human review (max 5 items)

Also provide a complete, clean Markdown transcription of the entire document:
  - "raw_text": the full document text with all labels and filled values, preserving section headings, tables, and checkmarks
  - Use Markdown formatting: headings with ##, bold for labels (**Label:**), tables where appropriate
  - MOST IMPORTANTLY: mirror the original document layout. If fields are arranged in a table/row-column format, use Markdown tables.
  - For field-label pairs (e.g. "Name: John Smith"), use **Label:** value on the same line.
  - For checkboxes: [✓] for checked, [✗] for unchecked, [—] for empty  
  - For radio buttons: [●] for selected, [○] for unselected
  - NO confidence scores, NO notes, NO technical metadata
  - Separate each page with: "\n\n--- Page {n} ---\n\n"

Also provide a "sections" array listing EVERY section in the document, including sections that have NO filled-in fields at all:
  - "number": the section number (integer)
  - "name": the section title text (e.g. "Student Profile", "Financial Background")
  - "page": the page where the section starts
  - Fields within that section will reference this number in their "section" field
  - CRITICAL: Include ALL sections you see in the document, even if every field in that section is blank or missing entirely.

Return ONLY valid JSON. No markdown fences, no extra text.
Use this exact structure:
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
    {"label": "Volunteer Name", "value": "Aadithya R", "confidence_tier": "high", "page": 1, "section": null, "needs_clarification": false, "reason": null, "position_hint": "same_line_colon"},
    {"label": "Co-Volunteer Name", "value": "Thameem", "confidence_tier": "high", "page": 1, "section": null, "needs_clarification": false, "reason": null, "position_hint": "same_line_colon"},
    {"label": "Date of Visit", "value": "10/15/2026", "confidence_tier": "high", "page": 1, "section": null, "needs_clarification": false, "reason": null, "position_hint": "same_line_colon"},
    {"label": "1.1 Application ID", "value": "2020-0346", "confidence_tier": "high", "page": 1, "section": 1, "needs_clarification": false, "reason": null, "position_hint": "below_label"},
    {"label": "1.2 Student Full Name", "value": "Joseph V.", "confidence_tier": "high", "page": 1, "section": 1, "needs_clarification": false, "reason": null, "position_hint": "below_label"},
    {"label": "1.3 Gender", "value": "Male", "confidence_tier": "high", "page": 1, "section": 1, "needs_clarification": false, "reason": null, "position_hint": "below_label"},
    {"label": "2.1 Family Status", "value": "Having both parents", "confidence_tier": "high", "page": 1, "section": 2, "needs_clarification": false, "reason": null, "position_hint": "below_label"},
    {"label": "4.1 Assets at Home — Washing Machine", "value": "✓", "confidence_tier": "high", "page": 3, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"},
    {"label": "4.1 Assets at Home — Fridge", "value": "✗", "confidence_tier": "high", "page": 3, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"},
    {"label": "4.1 Assets at Home — Car", "value": "✗", "confidence_tier": "high", "page": 3, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"},
    {"label": "2.5 Family Members — Row 1 — Name", "value": "Ravi", "confidence_tier": "high", "page": 2, "section": 2, "needs_clarification": false, "reason": null, "position_hint": "below_label"},
    {"label": "2.5 Family Members — Row 1 — Age", "value": "45", "confidence_tier": "high", "page": 2, "section": 2, "needs_clarification": false, "reason": null, "position_hint": "below_label"},
    {"label": "4.6.1 Loan Details — Row 1 — Loan Purpose", "value": "Housing Loan", "confidence_tier": "high", "page": 4, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "below_label"},
    {"label": "5.2 If yes, list the health issues", "value": "N/A", "confidence_tier": "high", "page": 5, "section": 5, "needs_clarification": false, "reason": null, "position_hint": "below_label"}
  ],
  "overall_confidence": 90,
  "clarification_needed": [],
  "raw_text": "# I AM THE CHANGE\\n\\n--- Page 1 ---\\n\\n**Volunteer Name:** Aadithya R\\n**Co-Volunteer Name:** Thameem\\n**Date of Visit:** 10/15/2026\\n\\n## Section 1 — Student Profile\\n**1.1 Application ID:** 2020-0346\\n**1.2 Student Full Name:** Joseph V.\\n**1.3 Gender:** Male\\n  [●] Male\\n  [○] Female\\n  [○] Others\\n\\n--- Page 2 ---\\n\\n## Section 2 — Family Background\\n**2.1 Family Status:** Having both parents\\n  [○] Single Parent\\n  [○] Parentless\\n  [●] Having both parents\\n\\n## Section 3 — Housing Condition\\n**3.1 House Ownership:** Rented\\n  [○] Own\\n  [●] Rented\\n\\n...truncated..."
}
"""


SECONDARY_VERIFICATION_PROMPT = """You are a verification system. The following fields were extracted from a multi-page document by a first-pass model. For each field, examine the corresponding page image and either confirm or correct the extracted value.

Additionally, look for any form fields the first model might have MISSED entirely — especially:
  - Header fields on page 1: "Volunteer Name", "Co-Volunteer Name", "Date of Visit"
  - Checkbox options (e.g. "4.1 Assets at Home — Car", "3.2 Type of Home — Others") that were omitted
  - Radio button groups where no value was captured
  - Table rows that were skipped, including empty cells
  - Conditional sub-fields (e.g. "4.3.1 If yes, list their properties", "5.2 If yes, list the health issues")
  - Fields at the end of the form: "8.3 Any other comments you want to share?"

For each existing field, respond with:
  - "label": the field label (exactly as given)
  - "is_correct": true/false (whether the extracted value matches the document)
  - "correct_value": the correct value if different (null if correct)
  - "verifier_confidence": your confidence 0-100
  - "note": brief explanation — mention what was wrong or what you confirmed

For any NEW fields you discover, respond in the "new_fields" array with:
  - "label": the field label as it appears on the form
  - "value": the filled-in value — use same conventions as primary (✓/✗ for checkboxes, selected option text for radio buttons, row-based labels for tables)
  - "confidence_tier": "high", "medium", or "low"
  - "page": which page number
  - "section": the section number this field belongs to (null if not under a numbered section)
  - CRITICAL: Every new field MUST include "section". Derive it from the leading number: "4.1 Assets at Home — Car" → section 4, "2.5 Family Members — Row 2 — Name" → section 2, "3.4.1 Type of Bedroom" → section 3.
  - "needs_clarification": true/false
  - "reason": explanation if uncertain
  - "position_hint": "same_line_colon", "right_of_label", "below_label", "above_label"

Radio button / checkbox conventions:
  - Radio group (single select) → value = the selected option's label text (e.g. "Male")
  - Checkbox option (multi-select) → value = "✓" if checked, "✗" if unchecked
  - Yes/No field → value = "Yes" or "No"
  - Table row → label = "{Section.Label} — Row {n} — {Column}"
  - Conditional sub-field when condition is "No" → value = "N/A"

Existing fields from first pass:
{fields_json}

IMPORTANT: Each field has a "page" field. Look at the correct page image.

Return ONLY a valid JSON object. No markdown fences, no extra text.
Use this exact structure:
{
  "verifications": [
    {"label": "3.1 House Ownership", "is_correct": true, "correct_value": null, "verifier_confidence": 95, "note": "Confirmed correct"},
    {"label": "1.3 Gender", "is_correct": false, "correct_value": "Female", "verifier_confidence": 98, "note": "Radio option Female was selected, not Male"}
  ],
  "new_fields": [
    {"label": "4.1 Assets at Home — Car", "value": "✗", "confidence_tier": "high", "page": 3, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"},
    {"label": "4.1 Assets at Home — Smartphone", "value": "✓", "confidence_tier": "high", "page": 3, "section": 4, "needs_clarification": false, "reason": null, "position_hint": "right_of_label"}
  ]
}
"""