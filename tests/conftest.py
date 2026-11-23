import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for extra in (ROOT, ROOT / "ta_core"):
    if str(extra) not in sys.path:
        sys.path.insert(0, str(extra))
