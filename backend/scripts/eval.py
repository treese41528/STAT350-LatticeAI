#!/usr/bin/env python3
"""Retrieval-quality eval, runnable from anywhere with any python:

    python backend/scripts/eval.py run [--k 8]
    python backend/scripts/eval.py replay --since 2026-08-01
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _bootstrap import bootstrap  # noqa: E402

bootstrap()

from app.eval.harness import main  # noqa: E402

sys.exit(main())
