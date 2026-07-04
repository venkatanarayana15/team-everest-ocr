import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


def run_batch(
    items: list[dict],
    process_fn,
    progress_cb,
    max_workers: int = 8,
):
    """Process multiple items in parallel with per-item progress tracking.

    Args:
        items: List of dicts, each must have at least ``"name"``.
        process_fn: Callable(item_dict, progress_cb_for_item) -> result.
            The per-item progress callback takes (pct: float, stage: str).
        progress_cb: Called with ``{"overall": int, "pdfs": {name: {...}}}``
            on every progress change.
        max_workers: ThreadPoolExecutor max workers (default 8).

    Returns:
        Dict of ``{item_name: result_or_error_dict}``.
    """
    total = len(items)
    if total == 0:
        return {}

    item_progress: dict[str, float] = {item["name"]: 0.0 for item in items}
    item_results: dict[str, dict] = {}

    def _make_report():
        overall = sum(item_progress.values()) / total
        return {
            "overall": round(overall),
            "pdfs": {
                name: {
                    "progress": round(pct),
                    "stage": "",
                }
                for name, pct in item_progress.items()
            },
        }

    def _on_item_progress(name: str, pct: float, stage: str = ""):
        item_progress[name] = pct
        report = _make_report()
        report["pdfs"][name]["stage"] = stage
        progress_cb(report)

    with ThreadPoolExecutor(max_workers=min(total, max_workers)) as pool:
        futures = {
            pool.submit(process_fn, item, _on_item_progress): item
            for item in items
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                result = future.result()
                item_results[item["name"]] = result
                _on_item_progress(item["name"], 100.0, "done")
            except Exception as e:
                logger.error("Pipeline failed for %s: %s", item["name"], e)
                item_results[item["name"]] = {"error": str(e)}
                _on_item_progress(item["name"], 100.0, "error")

    return item_results
