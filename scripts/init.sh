#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
exec "${PYTHON_BIN:-python3}" -m stageradar init
