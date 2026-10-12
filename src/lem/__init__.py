"""LEM — Local Energy Measurement."""

import os
import sys

__version__ = "0.2.0"


def version_string() -> str:
    """'0.2.0', plus the commit a packaged app was built from ('0.2.0 (223fa14)').

    The rolling 'latest' release reuses one version number across pushes, so
    the commit is what tells two downloads apart. PyInstaller builds stamp it
    into the bundle (see packaging/lem.spec); dev runs show the bare version."""
    if hasattr(sys, "_MEIPASS"):
        try:
            with open(os.path.join(sys._MEIPASS, "lem_assets", "build.txt")) as f:
                commit = f.read().strip()
            if commit:
                return f"{__version__} ({commit})"
        except OSError:
            pass
    return __version__
