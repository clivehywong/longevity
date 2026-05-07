#!/bin/bash
# SLURM XCP-D Subject-Level Seed Connectivity Array
# Generated: 2026-04-30T14:25:56.465490
# Pipeline: fc  Measures: pearson

#SBATCH --job-name=seed_connectivity
#SBATCH --array=1-72%20
#SBATCH --time=12:00:00
#SBATCH --mem=16G
#SBATCH --cpus-per-task=4
#SBATCH --partition=cpu-long
#SBATCH --output=logs/seed_%A_%a.out
#SBATCH --error=logs/seed_%A_%a.err

set -euo pipefail

# ---------- subject/session lookup (1-based SLURM index) ----------
SUBJECTS_ARRAY=("sub-033" "sub-033" "sub-034" "sub-034" "sub-035" "sub-035" "sub-036" "sub-036" "sub-037" "sub-037" "sub-038" "sub-038" "sub-039" "sub-039" "sub-040" "sub-040" "sub-043" "sub-043" "sub-045" "sub-045" "sub-046" "sub-046" "sub-047" "sub-047" "sub-048" "sub-048" "sub-051" "sub-051" "sub-052" "sub-052" "sub-055" "sub-055" "sub-056" "sub-056" "sub-057" "sub-057" "sub-058" "sub-058" "sub-059" "sub-059" "sub-060" "sub-060" "sub-061" "sub-061" "sub-062" "sub-062" "sub-063" "sub-063" "sub-064" "sub-064" "sub-065" "sub-065" "sub-066" "sub-066" "sub-068" "sub-068" "sub-069" "sub-069" "sub-071" "sub-071" "sub-072" "sub-072" "sub-074" "sub-074" "sub-076" "sub-076" "sub-079" "sub-079" "sub-080" "sub-080" "sub-081" "sub-081")
SESSIONS_ARRAY=("ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02" "ses-01" "ses-02")
IDX=$(( SLURM_ARRAY_TASK_ID - 1 ))
SUBJECT="${SUBJECTS_ARRAY[$IDX]}"
SESSION="${SESSIONS_ARRAY[$IDX]}"

LOG_FILE="logs/seed_${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}_${SUBJECT}_${SESSION}.log"

log_info() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] [INFO] $*" | tee -a "$LOG_FILE"; }
log_error() { echo "[$(date +'%Y-%m-%d %H:%M:%S')] [ERROR] $*" | tee -a "$LOG_FILE"; }

log_info "Starting seed for $SUBJECT $SESSION (array task ${SLURM_ARRAY_TASK_ID}/${SLURM_ARRAY_TASK_COUNT:-72})"

# ---------- manifest: expected marker ----------
mkdir -p outputs/expected outputs/done
touch "outputs/expected/${SUBJECT}_${SESSION}_seed.expected"

# ---------- backend ----------
if python3 script/compute_seed_connectivity_xcpd.py \
    --bids-root "/home/clivewong/proj/longevity" \
    --subject "$SUBJECT" \
    --session "$SESSION" \
    --pipeline fc \
    --seed atlas-4S256Parcels:RH_Cont_Par_1 \
    --measures pearson \
    --out-root "/home/clivewong/proj/long" \
    --tr 0.8 \
    >> "$LOG_FILE" 2>&1; then
    log_info "SUCCESS: seed for $SUBJECT $SESSION"
    touch "outputs/done/${SUBJECT}_${SESSION}_seed.done"
else
    log_error "FAILED: seed for $SUBJECT $SESSION"
    exit 1
fi
