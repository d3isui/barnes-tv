#!/usr/bin/env bash
# Barnes Television Broadcasting System - Linux/macOS launcher. First run creates a private Python environment.
set -e
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
if [ ! -x .venv/bin/python ]; then
  echo "Creating Python environment..."
  "$PY" -m venv .venv || { echo "Install python3-venv first (e.g. sudo apt install python3-venv)"; exit 1; }
fi
# packages are only (re)installed when requirements.txt changed since the last successful install
if ! cmp -s requirements.txt .venv/requirements.installed; then
  if .venv/bin/python -m pip install --disable-pip-version-check -q -r requirements.txt; then
    cp requirements.txt .venv/requirements.installed
  else
    echo "Some packages could not be installed; trying them one at a time (the app runs without the ones that fail)."
    grep -v '^[[:space:]]*#' requirements.txt | while read -r pkg; do
      [ -n "$pkg" ] && .venv/bin/python -m pip install --disable-pip-version-check -q "$pkg" || true
    done
  fi
fi
exec .venv/bin/python broadcast.py "$@"
