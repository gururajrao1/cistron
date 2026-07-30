#!/usr/bin/env bash
# Native Render Free build: Python API first, then optional Vite Studio.
# Soft-fails the UI build so a Node/OOM hiccup still leaves the API deployable.
set -euo pipefail

echo "==> Installing Python package"
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .

NODE_VERSION="${NODE_VERSION:-22.16.0}"
NODE_DIR="/tmp/node-v${NODE_VERSION}-linux-x64"

echo "==> Building Studio (same-origin VITE_API_BASE)"
set +e
if [[ ! -x "${NODE_DIR}/bin/node" ]]; then
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    | tar -xJ -C /tmp
fi
export PATH="${NODE_DIR}/bin:${PATH}"
(
  cd frontend
  # Prefer npm ci; fall back to npm install when lockfile drifts (Render Node != local).
  npm ci || npm install
  VITE_API_BASE= npm run build
)
ui_status=$?
set -e
if [[ $ui_status -ne 0 ]]; then
  echo "WARNING: Studio build failed (exit ${ui_status}); API-only deploy continues."
else
  echo "==> Studio build OK"
fi
