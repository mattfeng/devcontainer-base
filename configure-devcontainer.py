#!/usr/bin/env python3
"""Compatibility wrapper for the packaged CLI."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from devcontainer_configurator.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
