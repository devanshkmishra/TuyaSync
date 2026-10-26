"""TuyaSync entry point (kept at this path for PyInstaller and the console script)."""

from __future__ import annotations

import sys

from screensync.gui.app import main


if __name__ == "__main__":
    sys.exit(main())
