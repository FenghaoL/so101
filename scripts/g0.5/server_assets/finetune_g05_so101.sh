#!/usr/bin/env bash
# Install the three sibling files from this folder into the GalaxeaVLA checkout
# first; see server_assets/README.md.  Then execute this script on the GPU host.
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
: "${G05_SO101_DATASET_DIR:?Set this to the prepared LeRobot v3 dataset directory}"
: "${G05_SO101_PRETRAINED_CKPT:?Set this to the G0.5 model_state_dict.pt to fine-tune}"
: "${G05_OUTPUT_DIR:?Set this to a writable output root on the GPU server}"

export PYTHONPATH="$ROOT/src:${PYTHONPATH:-}"
export TOKENIZERS_PARALLELISM=false
MODE=${1:-run}
if [[ "$MODE" == "--dry-run" ]]; then
  export DRY_RUN=1
  shift
elif [[ "$MODE" == "run" ]]; then
  shift || true
else
  echo "Usage: $0 [run|--dry-run] [Hydra overrides...]" >&2
  exit 2
fi

cd "$ROOT"
exec "$ROOT/.venv/bin/python" scripts/finetune.py \
  task=so101_fenghao \
  model.pretrained_ckpt="$G05_SO101_PRETRAINED_CKPT" \
  model.use_pretrained_norm_stats=false \
  logger.type=null \
  "$@"
