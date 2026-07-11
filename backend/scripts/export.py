#!/usr/bin/env python3
"""Anonymized data export, runnable from anywhere with any python:

    python backend/scripts/export.py --from 2026-08-01 --to 2026-12-20 --out exports/fall26
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap  # noqa: E402

bootstrap()

from app.export.dump import main  # noqa: E402

sys.exit(main())
