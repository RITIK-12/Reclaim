#!/usr/bin/env bash
# Serve Liquid LFM2.5-VL-3B from ./models with llama.cpp (OpenAI-compatible API at http://localhost:8080/v1).
# Weights: LiquidAI/LFM2.5-VL-3B-GGUF -> models/LFM2.5-VL-3B-F16.gguf + models/mmproj-LFM2.5-VL-3B-F16.gguf
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MODEL="${MODEL:-$ROOT/models/LFM2.5-VL-3B-F16.gguf}"
MMPROJ="${MMPROJ:-$ROOT/models/mmproj-LFM2.5-VL-3B-F16.gguf}"
exec llama-server -m "$MODEL" --mmproj "$MMPROJ" --alias lfm2.5-vl-3b \
  --host 127.0.0.1 --port "${PORT:-8080}" -c "${CTX:-32768}" -np "${PARALLEL:-4}" -ngl 99 --jinja
