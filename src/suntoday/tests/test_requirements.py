import re
from pathlib import Path

ROOT = Path(__file__).parents[3]


def _pins(name: str) -> set[str]:
    lines = (ROOT / name).read_text(encoding="utf-8").splitlines()
    # The lock drops extras: sunpy[map]==1 is locked as sunpy==1.
    return {re.sub(r"\[.*?\]", "", line) for line in lines if line and not line.startswith(("#", " "))}


def test_lock_file_matches_requirements() -> None:
    # Docker installs requirements-full.txt while CI tests requirements.txt,
    # so a bump to one alone never reaches production.
    stale = _pins("requirements.txt") - _pins("requirements-full.txt")
    assert not stale, f"Regenerate requirements-full.txt (command in its header) for: {sorted(stale)}"
