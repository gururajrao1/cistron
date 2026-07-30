#!/usr/bin/env bash
# Native Render Free build: Node (Vite) + Python (FastAPI) in one web service.
# Docker is not available on Render Free; this replaces the Dockerfile path.
set -euo pipefail

NODE_VERSION="${NODE_VERSION:-22.16.0}"
NODE_DIR="${HOME}/.local/node-v${NODE_VERSION}-linux-x64"

if [[ ! -x "${NODE_DIR}/bin/node" ]]; then
  mkdir -p "${HOME}/.local"
  echo "==> Installing Node ${NODE_VERSION}"
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz" \
    | tar -xJ -C "${HOME}/.local"
fi
export PATH="${NODE_DIR}/bin:${PATH}"
node -v
npm -v

echo "==> Building Studio (same-origin VITE_API_BASE)"
cd frontend
npm ci
VITE_API_BASE= npm run build
cd ..

echo "==> Installing Python package"
python -m pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
pip install -e .
