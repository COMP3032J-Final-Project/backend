#!/usr/bin/env bash

set -euo pipefail

project_dir="/var/www/hivey/backend/"
cd "$project_dir"

. .venv/bin/activate

exec "$@"


