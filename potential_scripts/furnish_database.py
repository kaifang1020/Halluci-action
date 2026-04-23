#!/usr/bin/env python3
"""Compatibility wrapper for the formal database furnishing script.

The maintained entry point lives at scripts/furnish_database.py.  This wrapper
keeps older README commands and notebooks working while avoiding two copies of
the seeding logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from scripts.furnish_database import main


if __name__ == "__main__":
    main()
