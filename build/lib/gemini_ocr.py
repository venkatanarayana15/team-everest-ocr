import argparse
import json
import logging
import os
from datetime import datetime, timezone

import google.generativeai as genai

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)
logger = logging.getLogger("gemini_ocr")


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def setup(api_key: str | None = None) -> str:
    _load_dotenv()
    key = api_key or os.environ.get("GEMINI_API_KEY")
    if not key:
        raise ValueError(
            "Gemini API key required. Set GEMINI_API_KEY env var or pass --api-key."
        )
    genai.configure(api_key=key)
    return key


def ocr_pdf(
    pdf_path: str,
    model_name: str = "gemini-2.5-flash",
    prompt: str | None = None,
) -> str:
    if prompt is None:
        prompt = (
            "Perform a clean OCR text extraction of this document. "
            "Return the output in structured Markdown, preserving tables and checkmarks."
        )

    logger.info("Uploading: %s", pdf_path)
    sample_file = genai.upload_file(path=pdf_path, mime_type="application/pdf")
    logger.info("Uploaded file: %s", sample_file.name)

    model = genai.GenerativeModel(model_name)
    logger.info("Calling %s...", model_name)
    response = model.generate_content([sample_file, prompt])

    logger.info("Tokens: %s", response.usage_metadata if hasattr(response, "usage_metadata") else "N/A")
    return response.text


def save_output(text: str, pdf_path: str, output_dir: str = "output") -> dict[str, str]:
    os.makedirs(output_dir, exist_ok=True)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    paths = {}

    md_path = os.path.join(output_dir, f"{base}_gemini.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info("Markdown: %s", md_path)
    paths["markdown"] = md_path

    txt_path = os.path.join(output_dir, f"{base}_gemini.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)
    logger.info("Text: %s", txt_path)
    paths["text"] = txt_path

    json_path = os.path.join(output_dir, f"{base}_gemini.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "source": os.path.basename(pdf_path),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "model": "gemini-2.5-flash",
            "text": text,
        }, f, indent=2, ensure_ascii=False)
    logger.info("JSON: %s", json_path)
    paths["json"] = json_path

    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Gemini OCR extraction")
    parser.add_argument("--input", "-i", required=True, help="Path to input PDF")
    parser.add_argument("--api-key", help="Gemini API key (default: GEMINI_API_KEY env var)")
    parser.add_argument("--model", default="gemini-2.5-flash", help="Gemini model name")
    parser.add_argument("--prompt", help="Custom OCR prompt")
    parser.add_argument("--output-dir", default="output", help="Output directory")
    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: file not found: {args.input}")
        return

    setup(args.api_key)
    text = ocr_pdf(args.input, args.model, args.prompt)
    print(text)
    print()
    paths = save_output(text, args.input, args.output_dir)
    for fmt, p in paths.items():
        print(f"  [{fmt}] {p}")


if __name__ == "__main__":
    main()
