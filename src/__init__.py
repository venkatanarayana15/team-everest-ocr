# Lazy import to avoid cv2 dependency at module level
def get_config():
    from src.extraction_pipeline import Config
    return Config

__all__ = ["Config", "get_config"]