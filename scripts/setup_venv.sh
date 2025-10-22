#!/usr/bin/env bash
set -euo pipefail

PY=${PYTHON:-python3}
VENV_DIR=${VENV_DIR:-.venv}

if [[ ! -d "$VENV_DIR" ]]; then
  echo "Creating venv at $VENV_DIR" >&2
  $PY -m venv "$VENV_DIR"
fi

source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
pip install -r requirements.txt
echo "Virtualenv ready. Activate with: source $VENV_DIR/bin/activate" >&2

