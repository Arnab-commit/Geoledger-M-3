"""Image preprocessing service for OCR enhancement."""

import logging
from pathlib import Path
from PIL import Image
import cv2
import numpy as np

logger = logging.getLogger("geoldger.preprocessing")


def read_image_safe(image_path: Path) -> np.ndarray:
    """Read image safely on Windows even with Unicode characters in the path."""
    try:
        # Use numpy fromfile to prevent Windows path encoding issues
        data = np.fromfile(str(image_path), dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            # Fallback to standard imread
            img = cv2.imread(str(image_path))
        return img
    except Exception as e:
        logger.warning(f"Safe image read failed for {image_path}: {e}")
        return cv2.imread(str(image_path))


def write_image_safe(image_path: Path, img: np.ndarray) -> bool:
    """Write image safely on Windows."""
    try:
        image_path.parent.mkdir(parents=True, exist_ok=True)
        ext = image_path.suffix.lower()
        if not ext:
            ext = ".png"
        success, encoded = cv2.imencode(ext, img)
        if success:
            encoded.tofile(str(image_path))
            return True
        return cv2.imwrite(str(image_path), img)
    except Exception as e:
        logger.warning(f"Safe image write failed for {image_path}: {e}")
        return cv2.imwrite(str(image_path), img)


def detect_and_correct_skew(gray_img: np.ndarray) -> np.ndarray:
    """
    Detect text orientation skew and correct only if a small, genuine skew is found (-15 to +15 deg).
    Never rotates upside down or 90 degrees.
    """
    try:
        # Invert colors: text white, background black
        inv = cv2.bitwise_not(gray_img)
        # Apply Otsu threshold
        _, thresh = cv2.threshold(inv, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # Morphological dilation along horizontal axis to merge letters into text lines
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (30, 3))
        dilated = cv2.dilate(thresh, kernel, iterations=2)

        # Find contours of text lines
        contours, _ = cv2.findContours(dilated, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        angles = []
        for c in contours:
            area = cv2.contourArea(c)
            if area > 1000:  # Significant text block
                rect = cv2.minAreaRect(c)
                angle = rect[-1]
                if angle < -45:
                    angle = 90 + angle
                if -15 < angle < 15 and abs(angle) > 0.4:
                    angles.append(angle)

        if angles:
            median_angle = float(np.median(angles))
            if abs(median_angle) > 0.5:
                (h, w) = gray_img.shape[:2]
                center = (w // 2, h // 2)
                M = cv2.getRotationMatrix2D(center, median_angle, 1.0)
                rotated = cv2.warpAffine(
                    gray_img,
                    M,
                    (w, h),
                    flags=cv2.INTER_CUBIC,
                    borderMode=cv2.BORDER_REPLICATE
                )
                logger.info(f"Deskewed image by {median_angle:.2f} degrees")
                return rotated

        return gray_img
    except Exception as e:
        logger.warning(f"Deskew detection skipped: {e}")
        return gray_img


def sauvola_threshold(gray: np.ndarray, window_size: int = 25, k: float = 0.2, r: float = 128.0) -> np.ndarray:
    """
    Sauvola local adaptive thresholding for degraded historical and handwritten document images.
    Formula: T = m * (1 + k * (s / r - 1))
    where m is local mean, s is local standard deviation.
    Effectively extracts faint ink strokes, pencil handwriting, and aged stamps from discolored paper.
    """
    try:
        gray_f = gray.astype(np.float32)
        mean = cv2.boxFilter(gray_f, ddepth=-1, ksize=(window_size, window_size))
        mean_sq = cv2.boxFilter(gray_f ** 2, ddepth=-1, ksize=(window_size, window_size))
        variance = np.maximum(mean_sq - (mean ** 2), 0)
        std = np.sqrt(variance)

        threshold = mean * (1.0 + k * ((std / r) - 1.0))
        binary = np.where(gray_f > threshold, 255, 0).astype(np.uint8)
        return binary
    except Exception as e:
        logger.warning(f"Sauvola thresholding fallback to Otsu: {e}")
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
        return binary


def preprocess_image(image_path: Path, output_path: Path) -> dict:
    """
    Non-destructive high-performance image enhancement for OCR.
    Optimized for multi-lingual scanned records, handwritten text, faint ink, stamps, and camera photos.
    Generates enhanced grayscale image and Sauvola-binarized version for multi-pass OCR.
    Returns dict with original and processed dimensions.
    """
    try:
        img = read_image_safe(image_path)
        if img is None:
            raise ValueError(f"Could not read image: {image_path}")

        original_height, original_width = img.shape[:2]

        # 1. Resolution upscale for small/low-res images to achieve ~300 DPI clarity
        min_dim = min(original_height, original_width)
        max_dim = max(original_height, original_width)
        if max_dim < 1800:
            scale_factor = min(3.0, 2000.0 / max_dim)
            new_w = int(original_width * scale_factor)
            new_h = int(original_height * scale_factor)
            img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

        # 2. Grayscale conversion
        if len(img.shape) == 3 and img.shape[2] == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img.copy()

        # 3. Safe deskewing (bounded to -15 to +15 deg)
        deskewed = detect_and_correct_skew(gray)

        # 4. Bilateral filtering: removes sensor noise and paper grain while preserving sharp character edges
        denoised = cv2.bilateralFilter(deskewed, d=9, sigmaColor=75, sigmaSpace=75)

        # 5. Background shadow removal / illumination normalization
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25))
        morph_bg = cv2.morphologyEx(denoised, cv2.MORPH_CLOSE, kernel)
        norm_img = cv2.divide(denoised, morph_bg, scale=255)

        # 6. Contrast Enhancement via CLAHE
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = clahe.apply(norm_img)

        # 7. Unsharp Masking to sharpen faint handwriting and aged print strokes
        gaussian = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=2.0)
        sharpened = cv2.addWeighted(enhanced, 1.4, gaussian, -0.4, 0)

        # Write primary enhanced grayscale image
        write_image_safe(output_path, sharpened)

        # 8. Generate Sauvola-binarized threshold image for handwriting & degraded text
        binary_img = sauvola_threshold(sharpened, window_size=25, k=0.2, r=128.0)
        # Apply mild closing to reconnect broken handwriting strokes
        close_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary_cleaned = cv2.morphologyEx(binary_img, cv2.MORPH_CLOSE, close_kernel)
        bin_output_path = output_path.parent / f"bin_{output_path.name}"
        write_image_safe(bin_output_path, binary_cleaned)

        processed_height, processed_width = sharpened.shape[:2]
        logger.info(f"Image preprocessed successfully: {image_path.name} -> {output_path.name} ({processed_width}x{processed_height})")

        return {
            "original_width": original_width,
            "original_height": original_height,
            "processed_width": processed_width,
            "processed_height": processed_height,
            "binary_path": str(bin_output_path),
        }

    except Exception as e:
        logger.error(f"Preprocessing failed for {image_path}: {e}", exc_info=True)
        raise


def pdf_to_images(pdf_path: Path, output_dir: Path) -> list[Path]:
    """
    Convert PDF pages to 300 DPI high-resolution PNG images.
    Returns list of image paths.
    """
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError:
            logger.error("PyMuPDF (pymupdf/fitz) not available. Cannot process PDF.")
            raise

    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        image_paths = []

        doc = fitz.open(str(pdf_path))

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Render at 300 DPI (300/72 = 4.1667 zoom)
            zoom = 300.0 / 72.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            output_path = output_dir / f"page_{page_num + 1:03d}.png"
            pix.save(str(output_path))

            image_paths.append(output_path)
            logger.info(f"Extracted page {page_num + 1} from {pdf_path.name} at 300 DPI")

        doc.close()
        logger.info(f"PDF converted: {len(image_paths)} pages from {pdf_path.name}")
        return image_paths

    except Exception as e:
        logger.error(f"PDF conversion failed for {pdf_path}: {e}", exc_info=True)
        raise


def get_image_dimensions(image_path: Path) -> tuple[int, int]:
    """Get image width and height."""
    try:
        with Image.open(image_path) as img:
            return img.size  # (width, height)
    except Exception as e:
        logger.error(f"Could not read image dimensions: {image_path}: {e}")
        return (0, 0)
