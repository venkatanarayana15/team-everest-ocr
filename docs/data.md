Open‑source OCR libraries
1. Open source - Tesseract -  Printed documents, simple layouts - Very weak; not recommended for handwriting - Mature, widely used, easy to integrate, free - Poor on handwriting and complex forms; tuning is hard

2. Open source - PaddleOCR- Multi‑language docs, mobile/desktop apps- 	Some support with appropriate models- Fast, accurate on many printed docs, end‑to‑end pipeline- Handwriting still weaker than specialized cloud/document‑AI tools

3. Open source- EasyOCR- Quick prototypes in Python- Limited handwriting support- Simple API, many languages- Accuracy lower than more advanced frameworks for production use

4. Open source- MMOCR- Complex layouts, research/advanced projects- Depends on chosen models- Modular, supports detection + recognition, extensible- Higher complexity, more setup effort

5. Open source- Keras‑OCR / TrOCR and similar- Custom pipelines, ML teams- Can be trained/fine‑tuned for handwriting- Flexible, deep‑learning based- Requires ML expertise and compute to tune/train

6. Cloud OCR- Google Cloud Vision / Document AI- General OCR on images and PDFs- Has handwriting modes and document AI parsers- Good quality, strong layout analysis, managed service- Paid API, data leaves your environment

7. Cloud OCR- AWS Textract- Forms, tables, key‑value pairs- Some handwriting for specific fields- Strong for structured docs and extraction of fields- Pricing, region constraints, handwriting not perfect

8. Cloud OCR- Azure Vision Read / Document Intelligence- Printed and handwritten documents, forms- Explicitly supports handwritten notes and mixed content- Very good for handwritten business docs, strong SDKs- Paid, Azure lock‑in, needs configuration per use case

9. Commercial- ABBYY FineReader / FlexiCapture- Enterprise document capture- Some handwriting support depending on version- High accuracy for printed text, strong layout- Licensing cost, on‑prem/cloud setup effort

10. Specialized handwriting- Transkribus- Historical & modern handwriting archives- Yes, handwriting‑focused- Tailored models for handwriting, good accuracy on cursive- Service/platform‑style workflow, not just a small library

11. Specialized handwriting- Other handwriting OCR tools (2026 lists)- Business handwriting (forms, notes)- Yes, but quality varies- Tuned for handwriting, often with form templates- Average accuracy still lower than printed OCR; vendor choice matters

PDF has:
    Normal (printed) text (questions, labels, templates)
    Handwritten answers (fill‑in fields, notes, marks)
You want to extract:
    The printed text (optional, often already machine‑readable)
    The handwritten answers (the main value)

To extract both from a PDF (whether scanned or native) you need a pipeline that:
1. Detects regions of printed text vs handwritten text within the same page.
2. Applies the appropriate model for each region:
    a. printed text → standard OCR model
    b. handwritten answers → handwriting OCR model
3. Produces unified output: one clean, machine‑readable result (text, structured data, or searchable PDF).

