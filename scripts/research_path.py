"""Add the repository root for standalone script execution."""
from pathlib import Path
import sys


def install_research_path() -> None:
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
