#!/bin/bash
# QueryBook launcher for macOS. Double-click in Finder (it opens Terminal) or run ./run_mac.command
cd "$(dirname "$0")"
exec python3 -m querybook serve --open "$@"
