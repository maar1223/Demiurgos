"""Allow running the manual CLI as `python -m engram_sync`."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
