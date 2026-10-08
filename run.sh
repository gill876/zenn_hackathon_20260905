#!/bin/bash
# Local development server: memory store, LINE replies logged instead of sent unless a token is set.
set -e
cd "$(dirname "${BASH_SOURCE[0]}")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements-dev.txt
fi
echo "AsobiAgent → http://localhost:8000"
exec .venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port 8000 --reload
