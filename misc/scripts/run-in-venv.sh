#!/usr/bin/env bash

set -euo pipefail

project_dir="/var/www/hivey/backend/"

cd "$project_dir"

if [[ ! -d ./.venv ]]; then
    echo "Virtual environment doesn't exist. Creating one..."
    python3 -m venv .venv
fi

. .venv/bin/activate

echo "Updating/Install dependencies..."
pip3 install -r ./requirements_full.txt

echo "Starting Service..."
CPU_CORES=$(nproc)
WORKERS=$((2 * CPU_CORES + 1))
fastapi run --workers $WORKERS ./main.py


