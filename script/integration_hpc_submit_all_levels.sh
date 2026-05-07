#!/bin/bash
#
# Integration script: Submit subject-level and group-level jobs in sequence
#
# This script demonstrates the complete workflow:
# 1. Submit subject-level preprocessing/connectivity jobs
# 2. Wait for completion (optional)
# 3. Submit group-level analysis jobs with proper dependency
#
# Usage:
#   bash script/integration_hpc_submit_all_levels.sh [--wait] [--test-mode] [--dry-run]
#

set -e

# Configuration
PROJECT_DIR="${PROJECT_DIR:-/home/clivewong/proj/longevity}"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/home/clivewong/proj/long}"
SCRIPT_DIR="$PROJECT_DIR/script"
LOG_DIR="$PROJECT_DIR/logs"

# Flags
WAIT_MODE=false
TEST_MODE=false
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --wait)
            WAIT_MODE=true
            shift
            ;;
        --test-mode)
            TEST_MODE=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Logging
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/integration_$(date +%Y%m%d_%H%M%S).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "=========================================================================="
log "HPC INTEGRATION: SUBMIT SUBJECT-LEVEL + GROUP-LEVEL ANALYSIS"
log "=========================================================================="
log "Project: $PROJECT_DIR"
log "Test mode: $TEST_MODE"
log "Wait for completion: $WAIT_MODE"
log "Dry run: $DRY_RUN"
log ""

# Step 1: Submit subject-level jobs (example - substitute with real command)
log "[STEP 1] Submitting subject-level jobs..."

# This is a placeholder - use your actual subject-level submission command
# Example: Submit subject-level connectivity analysis
SUBJECT_LEVEL_SCRIPT="$SCRIPT_DIR/hpc_seed_connectivity_array_with_manifest.sh"

if [ ! -f "$SUBJECT_LEVEL_SCRIPT" ]; then
    log "ERROR: Subject-level script not found: $SUBJECT_LEVEL_SCRIPT"
    exit 1
fi

if [ "$DRY_RUN" = false ]; then
    SUBJECT_JOB_ID=$(sbatch "$SUBJECT_LEVEL_SCRIPT" | grep -o '[0-9]*' | head -1)
    log "Submitted subject-level job: $SUBJECT_JOB_ID"
else
    SUBJECT_JOB_ID="99999"
    log "[DRY RUN] Would submit subject-level job (using fake ID: $SUBJECT_JOB_ID)"
fi

log ""

# Step 2: Wait for subject-level completion (optional)
if [ "$WAIT_MODE" = true ]; then
    log "[STEP 2] Waiting for subject-level jobs to complete..."
    
    if [ "$DRY_RUN" = false ]; then
        python "$SCRIPT_DIR/hpc_submit_group_level.py" \
            --subject-job-id "$SUBJECT_JOB_ID" \
            --help > /dev/null 2>&1 || true
        
        # Wait using the monitoring function
        python3 << EOF
from script.hpc_submit_group_level import wait_for_subject_level_jobs
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger()

success = wait_for_subject_level_jobs(
    subject_job_id="$SUBJECT_JOB_ID",
    timeout_seconds=86400,
    check_interval=60,
    logger=logger
)

if not success:
    exit(1)
EOF
        log "Subject-level jobs completed!"
    else
        log "[DRY RUN] Would wait for subject-level job completion"
    fi
    log ""
fi

# Step 3: Submit group-level jobs with dependency
log "[STEP 3] Submitting group-level analysis jobs..."
log "Dependency: afterok:$SUBJECT_JOB_ID"
log ""

# Build command
CMD="python $SCRIPT_DIR/hpc_submit_group_level.py"
CMD="$CMD --subject-job-id $SUBJECT_JOB_ID"
CMD="$CMD --correction-method grf"
CMD="$CMD --n-permutations 1000"
CMD="$CMD --project-dir $PROJECT_DIR"
CMD="$CMD --remote-project-dir $REMOTE_PROJECT_DIR"

if [ "$TEST_MODE" = true ]; then
    CMD="$CMD --test-mode"
fi

if [ "$DRY_RUN" = true ]; then
    CMD="$CMD --dry-run"
fi

log "Command: $CMD"
log ""

# Execute
if eval "$CMD"; then
    GROUP_JOB_ID=$(eval "$CMD" 2>&1 | grep "Group job ID:" | awk '{print $NF}')
    log "Submitted group-level jobs: $GROUP_JOB_ID"
else
    log "ERROR: Failed to submit group-level jobs"
    exit 1
fi

log ""
log "=========================================================================="
log "SUBMISSION COMPLETE"
log "=========================================================================="
log "Subject-level job: $SUBJECT_JOB_ID"
log "Group-level job: $GROUP_JOB_ID (depends on subject-level)"
log "Log file: $LOG_FILE"
log ""
log "To check job status:"
log "  squeue -j $GROUP_JOB_ID"
log ""
log "To monitor job array:"
log "  squeue -A clivewong --array"
log ""
