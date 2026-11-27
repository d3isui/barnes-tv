#!/usr/bin/env bash
# Barnes Television Broadcasting System - Linux/macOS launcher. First run creates a private Python environment.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ ! -x .venv/bin/python ]; then
  echo "Creating Python environment..."
  "$PY" -m venv .venv || { echo "Install python3-venv first (e.g. sudo apt install python3-venv)"; exit 1; }
fi
if ! .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
  echo "Some optional packages could not be installed; installing the essentials only (casting may be unavailable)."
  .venv/bin/python -m pip install --disable-pip-version-check -q "Pillow>=10.1"
fi
exec .venv/bin/python broadcast.py "$@"
