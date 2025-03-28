#!/usr/bin/env bash

set -euo pipefail

project_dir="/var/www/hivey/backend/"

cd "$project_dir"

if [[ -d ./.venv ]]; then
    # since `rsync --delete` will empty most of the stuffs inside .venv (not not all)
    rm -rf ./.venv
fi

python3 -m venv .venv

. .venv/bin/activate

echo "Updating/Install dependencies..."
pip3 install -r ./requirements_full.txt

echo "Starting Service..."
CPU_CORES=$(nproc)
WORKERS=$((2 * CPU_CORES + 1))
# FIXME temporarily we cannot run with workers > 1
fastapi run --workers 1 ./app


