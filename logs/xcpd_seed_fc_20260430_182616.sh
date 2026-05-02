#!/bin/bash
# SLURM XCP-D Subject-Level Seed Connectivity Array
# Generated: 2026-04-30T18:26:16.072301
# Pipeline: fc  Measures: plv

#SBATCH --job-name=seed_connectivity
#SBATCH --array=1-2%2
#SBATCH --time=06:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --partition=cpu-long
#SBATCH --output=logs/seed_%A_%a.out
#SBATCH --error=logs/seed_%A_%a.err

set -euo pipefail

# ---------- subject/session lookup (1-based SLURM index) ----------
SUBJECTS_ARRAY=("sub-033" "sub-033")
SESSIONS_ARRAY=("ses-01" "ses-02")
IDX=$(( SLURM_ARRAY_TASK_ID - 1 ))
SUBJECT="${SUBJECTS_ARRAY[$IDX]}"
SESSION="${SESSIONS_ARRAY[$IDX]}"

LOG_FILE="logs/seed_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}_${SUBJECT}_${SESSION}.log"

log_info() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE"; }

log_info "Starting seed for $SUBJECT $SESSION (array task ${SLURM_ARRAY_TASK_ID}/${SLURM_ARRAY_TASK_COUNT:-2})"

# ---------- manifest: expected marker ----------
mkdir -p outputs/expected outputs/done
touch "outputs/expected/${SUBJECT}_${SESSION}_seed.expected"

# ---------- backend ----------
if python3 script/compute_seed_connectivity_xcpd.py \
    --bids-root "/home/clivewong/proj/longevity" \
    --subject "$SUBJECT" \
    --session "$SESSION" \
    --pipeline fc \
    --seed atlas-4S256Parcels:LH_Cont_OFC_1 \
    --measures plv \
    --out-root "derivatives/connectivity" \
    --tr 0.8 \
    >> "$LOG_FILE" 2>&1; then
    log_info "SUCCESS: seed for $SUBJECT $SESSION"
    touch "outputs/done/${SUBJECT}_${SESSION}_seed.done"
else
    log_error "FAILED: seed for $SUBJECT $SESSION"
    exit 1
fi
