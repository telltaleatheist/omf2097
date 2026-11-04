#!/bin/sh
# Runs a differential script with the project's Python, or skips (77) if there isn't one.
# usage: run.sh <python> <script> [args]
python=$1
shift
if [ ! -x "$python" ]; then
  echo "SKIP: no Python at $python. Set one up with: python3 -m venv .venv && .venv/bin/pip install -r tests/requirements.txt"
  exit 77
fi
exec "$python" -B "$@"
