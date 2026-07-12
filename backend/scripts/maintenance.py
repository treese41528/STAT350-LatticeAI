#!/usr/bin/env python3
"""Nightly rollup / retention purge, runnable from anywhere with any python:

    python backend/scripts/maintenance.py rollup
    python backend/scripts/maintenance.py purge
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap  # noqa: E402

bootstrap()

from app.jobs import main  # noqa: E402

sys.exit(main())
