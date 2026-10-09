"""Small, bounded operating-system integrations."""
from __future__ import annotations

import os
import subprocess
import sys

from .urls import InputError

def open_url(url: str) -> None:
    """Dispatch once. Success means OS acceptance, not FileMaker completion."""
    try:
        if sys.platform == "darwin":
            subprocess.run(["/usr/bin/open", url], check=True, capture_output=True, timeout=15)
        elif sys.platform == "win32":
            os.startfile(url)  # type: ignore[attr-defined]
        else:
            raise InputError("opening FileMaker requires macOS or Windows; use --dry-run to print the URL")
    except (OSError, subprocess.SubprocessError) as exc:
        raise InputError("could not open the FMP URL; check that the selected FileMaker version is installed") from exc
