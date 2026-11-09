"""Start VeriWave: python veriwave.py  (options: --no-querybook --attach --start --no-books --no-browser --port N)"""
from __future__ import annotations

import sys

from vw.server import main

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
