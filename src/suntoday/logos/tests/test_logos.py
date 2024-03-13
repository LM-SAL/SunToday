from pathlib import Path

from suntoday.logos import JPG_IMAGE, PNG_IMAGE


def test_logo_paths() -> None:
    base_dir = Path(__file__).parent.parent
    png_image = base_dir / "large_aia_watermark_50pct_rgba.png"
    jpg_image = base_dir / "large_aia_watermark_50pct.jpg"
    assert jpg_image == JPG_IMAGE
    assert png_image == PNG_IMAGE
