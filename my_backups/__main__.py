"""Entry point: python3 -m my_backups"""
import sys

from . import __version__
from .app import main

if __name__ == "__main__":
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"VaultLeaf Backup {__version__}")
        sys.exit(0)
    sys.exit(main())
