from pathlib import Path

BASE_DIR = Path(__file__).parent
PNG_IMAGE = BASE_DIR / "large_aia_watermark_50pct_rgba.png"
JPG_IMAGE = BASE_DIR / "large_aia_watermark_50pct.jpg"

__all__ = ["JPG_IMAGE", "PNG_IMAGE"]
