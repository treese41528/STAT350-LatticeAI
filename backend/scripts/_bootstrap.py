"""Shared launcher shim: re-exec under the project venv (so `python
backend/scripts/xxx.py` works with any interpreter) and put backend/ on the
path (so `app` imports regardless of CWD)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def bootstrap() -> None:
    if str(BACKEND) not in sys.path:
        sys.path.insert(0, str(BACKEND))
    try:
        import genai_studio  # noqa: F401
        return
    except ImportError:
        pass
    for venv in (os.environ.get("STAT350_VENV"),
                 str(Path.home() / "venvs" / "stat350-tutor"),
                 "/opt/stat350-tutor/venv"):
        if venv and (py := Path(venv) / "bin" / "python").exists() \
                and str(py) != sys.executable:
            os.execv(str(py), [str(py), *sys.argv])
    sys.exit(
        "genai-studio-sdk not importable and no project venv found.\n"
        "Run with the venv python, e.g.\n"
        "    ~/venvs/stat350-tutor/bin/python " + " ".join(sys.argv) + "\n"
        "or set STAT350_VENV to a venv with the backend deps installed."
    )
