"""Load secrets/settings from a `.env` file into the process environment.

Values already set in the environment win. Set QUANT_NO_DOTENV=1 to disable (the test
suite does, so a developer's real keys can never leak into tests).
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

DISABLE_ENV = "QUANT_NO_DOTENV"


def load_env_file(path: Path | str = ".env") -> bool:
    """Returns True if a file was loaded."""
    if os.environ.get(DISABLE_ENV) == "1":
        return False
    path = Path(path)
    if not path.is_file():
        return False
    return bool(load_dotenv(path, override=False))
