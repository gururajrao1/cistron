"""``python -m voidsignal.ui`` launches the Streamlit Virtual Cellular Laboratory."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> int:
    app = Path(__file__).resolve().parent / "app.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
