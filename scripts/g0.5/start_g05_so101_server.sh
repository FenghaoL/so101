#!/usr/bin/env bash
# Copy this file to the GalaxeaVLA checkout on the GPU server, then run it
# there.  It deliberately exposes the WebSocket service only through SSH.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
CKPT=${1:?Usage: bash scripts/g0.5/start_g05_so101_server.sh /path/to/model_state_dict.pt}
PORT=${POLICY_PORT:-8765}
CUDA_DEVICE=${CUDA_VISIBLE_DEVICES:-0}
TORCH_COMPILE=${G05_TORCH_COMPILE:-false}
ACTION_STEPS=${G05_ACTION_STEPS:-1}

test -x "$ROOT/.venv/bin/python"
test -f "$CKPT"

export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"
export CUDA_VISIBLE_DEVICES="$CUDA_DEVICE"

echo "[server] checkpoint: $CKPT"
echo "[server] endpoint:   ws://127.0.0.1:$PORT"
echo "[server] action_steps=$ACTION_STEPS compile=$TORCH_COMPILE gpu=$CUDA_DEVICE"

cd "$ROOT"
exec "$ROOT/.venv/bin/python" scripts/serve_policy.py \
  --ckpt_path "$CKPT" \
  --host 127.0.0.1 \
  --port "$PORT" \
  --device cuda \
  --action_steps "$ACTION_STEPS" \
  eval_embodiment=so100 \
  model.model_weights_to_bf16=true \
  model.use_torch_compile="$TORCH_COMPILE" \
  model.model_arch.attn_implementation=sdpa
