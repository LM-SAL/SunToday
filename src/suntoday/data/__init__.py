from pathlib import Path

import suntoday

__all__ = [
    "DATA_ROOTDIR",
    "RESPONSE_TABLE_V10",
]

DATA_ROOTDIR = Path(Path(suntoday.__file__).parent) / "data"
RESPONSE_TABLE_V10 = DATA_ROOTDIR / "aia_V10_20201119_190000_response_table.txt"
