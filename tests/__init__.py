import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_root = str(ROOT)
sys.path[:] = [p for p in sys.path if p != _root]
sys.path.insert(0, _root)
