#!/bin/bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
fi

echo "============================================================"
echo "🚀 Starting AsobiAgent Hackathon Demo Server..."
echo "📍 Access UI at: http://localhost:8000"
echo "⚡ Models: GMI Cloud (Qwen3.8-Flash) & Ekispert MCP"
echo "============================================================"

.venv/bin/python server.py
