import asyncio
import logging
import os
import time
from pathlib import Path
import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

def _load_env_keys():
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / ".env"
    if path.exists():
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                os.environ[k.strip()] = v.strip()

_load_env_keys()
CHANDRA_OCR_URL = os.getenv("CHANDRA_OCR_URL", "https://ocr.teameverest.ngo/v1/ocr")

class ChandraOcrError(Exception):
    """Custom exception for Chandra-2 OCR API failures."""
    pass

async def _process_single_page_ocr(
    page_num: int,
    image_path: str,
    max_retries: int = 3,
    initial_delay: float = 2.0,
) -> str:
    """Helper function to upload and process a single page image."""
    target_path = Path(image_path)
    if not target_path.exists():
        raise FileNotFoundError(f"Page image does not exist: {target_path}")

    file_name = target_path.name
    file_size = target_path.stat().st_size
    logger.info("Chandra-2 upload started for Page %d: %s (%d bytes)", page_num, file_name, file_size)

    t0 = time.time()
    delay = initial_delay
    for attempt in range(1, max_retries + 1):
        try:
            api_key = os.getenv("DATALAB_API_KEY") or os.getenv("CHANDRA_API_KEY") or os.getenv("PRIMARY_API_KEY") or os.getenv("SECONDARY_API_KEY")
            with open(target_path, "rb") as f:
                files = {
                    "file": (file_name, f, "image/png")
                }
                data = {
                    "output_format": "markdown",
                    "mode": "balanced"
                }

                # 60s timeout is more than enough for a single page
                timeout = httpx.Timeout(60.0, connect=10.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(
                        "https://www.datalab.to/api/v1/convert",
                        files=files,
                        data=data,
                        headers={"X-API-Key": api_key}
                    )

            if response.status_code != 200:
                raise ChandraOcrError(
                    f"API responded with status code {response.status_code}: {response.text}"
                )

            response_data = response.json()
            check_url = response_data.get("request_check_url")
            if not check_url:
                raise ChandraOcrError(f"No request_check_url in response: {response_data}")

            # Poll the check_url
            markdown_text = None
            for _ in range(150): # up to 5 minutes
                await asyncio.sleep(2)
                async with httpx.AsyncClient(timeout=30.0) as client:
                    poll_resp = await client.get(check_url, headers={"X-API-Key": api_key})
                    poll_resp.raise_for_status()
                    poll_data = poll_resp.json()
                    status = poll_data.get("status", "")
                    if status == "complete":
                        markdown_text = poll_data.get("markdown")
                        break
                    elif status == "failed":
                        raise ChandraOcrError(f"Datalab conversion failed: {poll_data.get('error', 'unknown error')}")

            if markdown_text is None:
                raise ChandraOcrError("Datalab conversion timed out or did not return markdown key")

            elapsed = time.time() - t0
            logger.info(
                "Chandra-2 OCR completed successfully for Page %d in %.2fs",
                page_num,
                elapsed
            )
            return markdown_text

        except (httpx.HTTPError, ChandraOcrError, ValueError, KeyError) as e:
            logger.error(
                "Chandra-2 OCR API failure (attempt %d/%d) for Page %d: %s",
                attempt,
                max_retries,
                page_num,
                e
            )
            if attempt == max_retries:
                raise ChandraOcrError(
                    f"Chandra-2 OCR failed for Page {page_num} after {max_retries} attempts. Last error: {e}"
                )

            logger.info("Retrying Page %d in %.2fs...", page_num, delay)
            await asyncio.sleep(delay)
            delay *= 2.0

async def call_chandra_ocr(
    file_path: str = "",
    page_images: dict[int, str] = None,
    job_dir: Path = None,
    max_retries: int = 3,
    initial_delay: float = 2.0,
) -> str:
    """
    Call Chandra-2 OCR service with a PDF or preprocessed page images.
    Returns the extracted Markdown string exactly as provided by Chandra-2.
    """
    _load_env_keys()
    api_key = os.getenv("DATALAB_API_KEY") or os.getenv("CHANDRA_API_KEY") or os.getenv("PRIMARY_API_KEY") or os.getenv("SECONDARY_API_KEY")
    if not api_key:
        raise ValueError("DATALAB_API_KEY (or CHANDRA_API_KEY) is not configured in .env")

    # If page_images is provided, process in parallel page-by-page
    if page_images:
        logger.info("Chandra-2: Processing %d pages in parallel...", len(page_images))
        tasks = []
        for page_num in sorted(page_images.keys()):
            tasks.append(_process_single_page_ocr(page_num, page_images[page_num], max_retries, initial_delay))

        markdown_pages = await asyncio.gather(*tasks)

        # Merge the pages together
        full_markdown = []
        for page_num, md in zip(sorted(page_images.keys()), markdown_pages):
            full_markdown.append(md)

        return "\n\n".join(full_markdown)

    # Fallback to single file upload (e.g. if page_images is not provided)
    if file_path and Path(file_path).exists():
        target_path = Path(file_path)
        logger.info("Chandra-2: Using provided file path directly: %s", target_path)
        t0 = time.time()
        file_name = target_path.name
        file_size = target_path.stat().st_size
        logger.info("Chandra-2 upload started: %s (%d bytes)", file_name, file_size)

        delay = initial_delay
        for attempt in range(1, max_retries + 1):
            try:
                with open(target_path, "rb") as f:
                    files = {
                        "file": (file_name, f, "application/pdf" if target_path.suffix.lower() == ".pdf" else "image/png")
                    }
                    data = {
                        "output_format": "markdown",
                        "mode": "balanced"
                    }

                    # 120s timeout for full PDF upload
                    timeout = httpx.Timeout(120.0, connect=10.0)
                    async with httpx.AsyncClient(timeout=timeout) as client:
                        response = await client.post(
                            "https://www.datalab.to/api/v1/convert",
                            files=files,
                            data=data,
                            headers={"X-API-Key": api_key}
                        )

                if response.status_code != 200:
                    raise ChandraOcrError(
                        f"API responded with status code {response.status_code}: {response.text}"
                    )

                response_data = response.json()
                check_url = response_data.get("request_check_url")
                if not check_url:
                    raise ChandraOcrError(f"No request_check_url in response: {response_data}")

                # Poll the check_url
                markdown_text = None
                for _ in range(150): # up to 5 minutes
                    await asyncio.sleep(2)
                    async with httpx.AsyncClient(timeout=30.0) as client:
                        poll_resp = await client.get(check_url, headers={"X-API-Key": api_key})
                        poll_resp.raise_for_status()
                        poll_data = poll_resp.json()
                        status = poll_data.get("status", "")
                        if status == "complete":
                            markdown_text = poll_data.get("markdown")
                            break
                        elif status == "failed":
                            raise ChandraOcrError(f"Datalab conversion failed: {poll_data.get('error', 'unknown error')}")

                if markdown_text is None:
                    raise ChandraOcrError("Datalab conversion timed out or did not return markdown key")

                elapsed = time.time() - t0
                logger.info(
                    "Chandra-2 OCR completed successfully in %.2fs. Pages: %s",
                    elapsed,
                    file_name
                )
                return markdown_text

            except (httpx.HTTPError, ChandraOcrError, ValueError, KeyError) as e:
                logger.error(
                    "Chandra-2 OCR API failure (attempt %d/%d) for %s: %s",
                    attempt,
                    max_retries,
                    file_name,
                    e
                )
                if attempt == max_retries:
                    raise ChandraOcrError(
                        f"Chandra-2 OCR failed after {max_retries} attempts. Last error: {e}"
                    )

                logger.info("Retrying in %.2fs...", delay)
                await asyncio.sleep(delay)
                delay *= 2.0
    else:
        raise ValueError("Either file_path or page_images must be provided")
