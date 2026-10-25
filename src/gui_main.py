"""Desktop application entry point using the Python standard library GUI."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from gui.main_window import run_gui


if __name__ == "__main__":
    raise SystemExit(run_gui())
