"""
OCR provider for JARVIS using Tesseract.

Provides text extraction from images for the perception pipeline.
Uses tesseract-ocr binary (v5.5.0) via pytesseract Python bindings.

Design:
  - Singleton-style provider (one instance per process)
  - Configurable language (default: English)
  - Handles image preprocessing (grayscale conversion) for better accuracy
  - health() returns tesseract version and language status (read-only)
"""
import os
import sys
import shutil
from typing import Optional, List, Dict, Any

try:
    import pytesseract
    from PIL import Image
    _PYTESSERACT_AVAILABLE = True
except ImportError:
    _PYTESSERACT_AVAILABLE = False


class TesseractOCRProvider:
    """
    OCR text extraction using Tesseract.

    Requirements:
      - tesseract binary in PATH (v5.5.0 confirmed)
      - pytesseract Python package (v0.3.13 confirmed)
      - Pillow for image loading (v10.4.0 confirmed)

    Usage:
        ocr = TesseractOCRProvider()
        text = ocr.extract("/path/to/image.png")
        # → "Hello, this is OCR text"
    """

    def __init__(self, language: str = "eng", tesseract_path: str = None):
        self._tesseract_path = tesseract_path or shutil.which("tesseract")
        self._language = language
        self._available = self._check_available()

    def _check_available(self) -> bool:
        """Check if tesseract is available and callable."""
        if not self._tesseract_path:
            return False
        if not _PYTESSERACT_AVAILABLE:
            return False
        return os.path.isfile(self._tesseract_path) and os.access(self._tesseract_path, os.X_OK)

    @property
    def is_available(self) -> bool:
        return self._available

    def extract(self, image_path: str) -> Optional[str]:
        """
        Extract text from an image file.
        Returns None if OCR is unavailable.
        """
        if not self._available:
            return None

        try:
            # Load and preprocess image
            img = Image.open(image_path)
            # Convert to grayscale for better recognition
            if img.mode not in ("L", "1"):
                img = img.convert("L")

            # Run Tesseract OCR
            text = pytesseract.image_to_string(
                img,
                lang=self._language,
                config="--psm 6",  # Assume a single uniform block of text
            )
            return text.strip() if text else None

        except Exception as e:
            print(f"[OCR] Extraction failed: {e}", file=sys.stderr)
            return None

    def extract_file(self, image_path: str) -> Optional[str]:
        """Alias for extract()."""
        return self.extract(image_path)

    def health(self) -> Dict[str, Any]:
        """Read-only health check — never exposes secrets or file contents."""
        version = "unknown"
        if self._tesseract_path:
            import subprocess
            try:
                result = subprocess.run(
                    [self._tesseract_path, "--version"],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    version = result.stdout.strip().split('\n')[0]
            except Exception:
                pass

        return {
            "available": self._available,
            "tesseract_path": self._tesseract_path,
            "tesseract_version": version,
            "pytesseract_available": _PYTESSERACT_AVAILABLE,
            "language": self._language,
        }
