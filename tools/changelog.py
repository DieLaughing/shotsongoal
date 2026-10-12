"""Rewrite CHANGELOG.md from sog/data/changes.yaml. Run after adding an entry: .venv/bin/python tools/changelog.py"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from sog import changes  # noqa: E402

APP, SITE = "Shots on Goal", "https://github.com/DieLaughing/shotsongoal"

if __name__ == "__main__":
    (ROOT / "CHANGELOG.md").write_text(changes.markdown(changes.load(), APP, SITE))
    print("CHANGELOG.md updated")
