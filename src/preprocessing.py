import cv2
import numpy as np

from src.config import Config


def to_grayscale(image: np.ndarray) -> np.ndarray:
    if len(image.shape) == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def deskew(image: np.ndarray, max_angle: int = 5) -> np.ndarray:
    """Deskew using edge detection so it works on both grayscale and binary images."""
    edges = cv2.Canny(image, 50, 150, apertureSize=3)
    coords = np.column_stack(np.where(edges > 0))
    if len(coords) < 50:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) > max_angle or abs(angle) < 0.5:
        return image
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def denoise(image: np.ndarray, h: int = 10) -> np.ndarray:
    return cv2.fastNlMeansDenoising(image, h=h)


def adaptive_threshold(image: np.ndarray, block_size: int = 15, c: int = 2) -> np.ndarray:
    if block_size % 2 == 0:
        block_size += 1
    return cv2.adaptiveThreshold(
        image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, block_size, c
    )


def preprocess(image: np.ndarray, config: Config) -> np.ndarray:
    gray = to_grayscale(image)
    gray = deskew(gray, config.deskew_max_angle)
    gray = denoise(gray, config.denoise_strength)
    return adaptive_threshold(gray, config.binarization_block_size, config.binarization_c)


def preprocess_region(image: np.ndarray, bbox: tuple, config: Config) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    crop = image[y1:y2, x1:x2]
    if crop.size == 0:
        return np.zeros((100, 100), dtype=np.uint8)
    return preprocess(crop, config)