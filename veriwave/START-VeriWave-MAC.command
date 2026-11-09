#!/bin/sh
# VeriWave: the QueryBook AI model. Starts QueryBook's applications too (or uses a QueryBook window already open).
cd "$(dirname "$0")" && exec python3 veriwave.py "$@"
