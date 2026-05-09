from pathlib import Path

from .read_csv import make_read_csv

THIS_DIR = Path(__file__).parent
TYPE_STUBS = (THIS_DIR / "type_stubs.pyi").read_text()

__all__ = [
    "make_read_csv",
    "TYPE_STUBS",
]
