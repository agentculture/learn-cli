"""Entry point for ``python -m learn``."""

from __future__ import annotations

import sys

from learn.cli import main

if __name__ == "__main__":
    sys.exit(main())
