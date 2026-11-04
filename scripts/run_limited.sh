#!/usr/bin/env bash
# Run one CPU-heavy command under hard limits, one at a time (S38, after a node hang).
# Usage: scripts/run_limited.sh <command...>
# Limits: 16 cores (PERCH_LIMIT_CORES), 24 GB memory, 512 tasks, lowest priority, no GPU,
# math threads equal to the core limit. The node has 255 cores and is shared.
# Refuses to start while another limited job runs or the 1-minute load is above 96.
# GPU mode: PERCH_LIMIT_GPU=<index> exposes that one GPU, uses 4 cores by default and takes
# a separate lock, so one GPU job may run beside one CPU job.
set -euo pipefail
GPU="${PERCH_LIMIT_GPU:-}"
if [ -n "$GPU" ]; then
  CORES="${PERCH_LIMIT_CORES:-4}"; DEFAULT_LOCK=perch-gpu.lock
else
  CORES="${PERCH_LIMIT_CORES:-16}"; DEFAULT_LOCK=perch-heavy.lock
fi
LOCK="${PERCH_LIMIT_LOCK:-${XDG_RUNTIME_DIR:-/tmp}/$DEFAULT_LOCK}"
exec 9>"$LOCK"
if ! flock -n 9; then echo "run_limited: another heavy job is running; not starting" >&2; exit 75; fi
load=$(cut -d' ' -f1 /proc/loadavg)
if awk -v l="$load" 'BEGIN{exit !(l>96)}'; then echo "run_limited: load $load is above 96; not starting" >&2; exit 75; fi
export CUDA_VISIBLE_DEVICES="$GPU" OMP_NUM_THREADS="$CORES" MKL_NUM_THREADS="$CORES" \
  OPENBLAS_NUM_THREADS="$CORES" TOKENIZERS_PARALLELISM=false PERCH_TORCH_THREADS="$CORES" \
  PERCH_MODEL_SLOTS=1
exec systemd-run --user --scope -q -p CPUQuota="$((CORES * 100))%" -p MemoryMax=24G \
  -p TasksMax=512 nice -n 19 "$@"
