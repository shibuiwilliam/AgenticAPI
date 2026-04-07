"""Python and dependency version compatibility utilities."""

from __future__ import annotations

import sys

PYTHON_VERSION = sys.version_info
MIN_PYTHON_VERSION = (3, 13)

if PYTHON_VERSION < MIN_PYTHON_VERSION:
    msg = f"AgenticAPI requires Python {'.'.join(map(str, MIN_PYTHON_VERSION))}+, got {sys.version}"
    raise RuntimeError(msg)
