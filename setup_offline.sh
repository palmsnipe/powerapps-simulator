#!/bin/sh
set -eu
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/python -m pip install --force-reinstall --no-index --find-links wheelhouse powerapps-sim==0.1.0
echo "Installed. Run: ./start.sh"
