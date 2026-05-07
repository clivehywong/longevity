#!/bin/bash
#
# Master HPC Orchestration: Submit jobs with proper dependencies and manifest tracking
# 
# This script:
# 1. Submits subject-level jobs (seed connectivity, local measures, etc.)
# 2. Chains sync jobs to wait for subject-level completion
# 3. Submits group-level analysis after sync validates readiness
# 4. Uses SLURM job dependencies to prevent race conditions
#
# Usage:
#   bash script/hpc_orchestrate_full_pipeline.sh [--test] [--no-group]
#

set -e

PROJECT_DIR="${PROJECT_DIR:-/home/clivewong/proj/longevity}"
SCRIPT_DIR="$PROJECT_DIR/script"
RESULTS_DIR="$PROJECT_DIR/results"
LOG_DIR="$PROJECT_DIR/logs"

# Test mode: use fewer subjects, shorter timeouts
TEST_MODE=false
SUBMIT_GROUP=true

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            TEST_MODE=true
            echo "[TEST MODE] Running with reduced scope"
            shift
            ;;
        --no-group)
            SUBMIT_GROUP=false
            echo "[INFO] Skipping group-level jobs"
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Create output directories
mkdir -p "$LOG_DIR" "$RESULTS_DIR"

# Log file for this orchestration run
ORCHESTRATION_LOG="$LOG_DIR/orchestration_$(date +%Y%m%d_%H%M%S).log"

{

echo "========================================================================="
echo "HPC ORCHESTRATION: Master Full Pipeline"
echo "========================================================================="
echo "Start time: $(date)"
echo "Project: $PROJECT_DIR"
echo "Test mode: $TEST_MODE"
echo "Submit group-level: $SUBMIT_GROUP"
echo ""

# =============================================================================
# Configuration
# =============================================================================

# Subjects to process
ALL_SUBJECTS=(
    sub-033 sub-034 sub-035 sub-036 sub-037 sub-038 sub-039 sub-040
    sub-043 sub-045 sub-046 sub-047 sub-048 sub-052 sub-055 sub-057
    sub-058 sub-059 sub-060 sub-061 sub-062 sub-063 sub-064 sub-056
)

# Seeds for analysis
SEEDS=(
    dlpfc_l dlpfc_r dlpfc_bilateral
    anterior_insula dacc_combined
    hippocampus_anterior hippocampus_posterior hippocampus_bilateral
    motor_cortex cerebellar_motor
    default_mode frontoparietal_control
)

# Atlases
ATLASES=(difumo256 schaefer400)

# In test mode, use smaller set
if [[ "$TEST_MODE" == "true" ]]; then
    SUBJECTS=(${ALL_SUBJECTS[@]:0:2})
    SEEDS=(dlpfc_l dlpfc_r)
    ATLASES=(difumo256)
else
    SUBJECTS=("${ALL_SUBJECTS[@]}")
fi

echo "Configuration:"
echo "  Subjects: ${#SUBJECTS[@]} (${SUBJECTS[0]}...${SUBJECTS[-1]})"
echo "  Seeds: ${#SEEDS[@]} (${SEEDS[0]}...${SEEDS[-1]})"
echo "  Atlases: ${#ATLASES[@]} (${ATLASES[0]}...${ATLASES[-1]})"
echo ""

# =============================================================================
# STEP 1: Submit subject-level jobs
# =============================================================================

echo "STEP 1: Submitting Subject-Level Jobs"
echo "======================================"
echo ""

# Submit local measures
echo "Submitting local measures jobs..."
SUBJECTS_STR=$(IFS=, ; echo "${SUBJECTS[*]}")
SEEDS_STR=$(IFS=, ; echo "${SEEDS[*]}")
ATLASES_STR=$(IFS=, ; echo "${ATLASES[*]}")

# Use the job manager to submit
LOCAL_JOB=$(python3 "$SCRIPT_DIR/hpc_job_manager.py" \
    --project-dir "$PROJECT_DIR" \
    submit-subject \
    --script "$SCRIPT_DIR/hpc_local_measures_all24.sh" \
    --job-name "local_measures" \
    --subjects "$SUBJECTS_STR" \
    --seeds "$SEEDS_STR" \
    --atlases "$ATLASES_STR" \
    $(if [[ "$TEST_MODE" == "true" ]]; then echo "--test"; fi) \
    2>&1 | grep -oE "Job ID: [0-9]+" | awk '{print $3}')

if [[ -z "$LOCAL_JOB" ]]; then
    echo "[WARN] Local measures job submission may have failed, attempting direct submission..."
    LOCAL_JOB=$(sbatch \
        --job-name="local_measures_$(date +%H%M%S)" \
        --array=1-${#SUBJECTS[@]}%10 \
        "$SCRIPT_DIR/hpc_local_measures_all24.sh" \
        2>&1 | grep -oE "[0-9]+$")
fi

echo "[SUCCESS] Submitted local measures: $LOCAL_JOB"
echo ""

# Submit seed connectivity
echo "Submitting seed connectivity jobs..."
SEED_JOB=$(sbatch \
    --job-name="seed_connectivity_$(date +%H%M%S)" \
    --array=1-${#SUBJECTS[@]}%10 \
    --depend=afterok:$LOCAL_JOB \
    "$SCRIPT_DIR/hpc_seed_connectivity_array.sh" \
    2>&1 | grep -oE "[0-9]+$")

echo "[SUCCESS] Submitted seed connectivity: $SEED_JOB (depends on $LOCAL_JOB)"
echo ""

# Submit between-network connectivity
echo "Submitting between-network connectivity jobs..."
BETWEEN_JOB=$(sbatch \
    --job-name="between_network_$(date +%H%M%S)" \
    --array=1-${#SUBJECTS[@]}%10 \
    --depend=afterok:$SEED_JOB \
    "$SCRIPT_DIR/hpc_between_network_array.sh" \
    2>&1 | grep -oE "[0-9]+$")

echo "[SUCCESS] Submitted between-network connectivity: $BETWEEN_JOB (depends on $SEED_JOB)"
echo ""

# Collect all subject-level job IDs for final dependency
echo "Subject-level jobs:"
echo "  Local measures: $LOCAL_JOB"
echo "  Seed connectivity: $SEED_JOB"
echo "  Between-network: $BETWEEN_JOB"
echo ""

# =============================================================================
# STEP 2: Submit synchronization job
# =============================================================================

echo "STEP 2: Submitting Synchronization Job"
echo "======================================"
echo ""

# Sync job depends on all subject-level jobs completing
SYNC_JOB=$(sbatch \
    --job-name="sync_results_$(date +%H%M%S)" \
    --depend=afterok:$BETWEEN_JOB \
    "$SCRIPT_DIR/hpc_sync.sh" \
    2>&1 | grep -oE "[0-9]+$")

echo "[SUCCESS] Submitted sync job: $SYNC_JOB (depends on $BETWEEN_JOB)"
echo ""

# =============================================================================
# STEP 3: Submit group-level jobs (if enabled)
# =============================================================================

if [[ "$SUBMIT_GROUP" == "true" ]]; then
    echo "STEP 3: Submitting Group-Level Analysis Jobs"
    echo "============================================="
    echo ""
    
    # Group analysis depends on sync completing
    GROUP_JOB=$(sbatch \
        --job-name="group_analysis_$(date +%H%M%S)" \
        --array=1-$((${#SEEDS[@]} * ${#ATLASES[@]}))%10 \
        --depend=afterok:$SYNC_JOB \
        "$SCRIPT_DIR/hpc_group_analysis_array.sh" \
        2>&1 | grep -oE "[0-9]+$")
    
    echo "[SUCCESS] Submitted group-level analysis: $GROUP_JOB (depends on $SYNC_JOB)"
    echo ""
fi

# =============================================================================
# STEP 4: Print Job Dependency Chain
# =============================================================================

echo "STEP 4: Job Dependency Chain"
echo "============================"
echo ""

echo "Dependency chain (use 'squeue --dependency' to monitor):"
if [[ "$SUBMIT_GROUP" == "true" ]]; then
    cat << EOF

    Local Measures ($LOCAL_JOB)
           ↓
    Seed Connectivity ($SEED_JOB)
           ↓
    Between-Network ($BETWEEN_JOB)
           ↓
    Sync Results ($SYNC_JOB)
           ↓
    Group Analysis ($GROUP_JOB)

EOF
else
    cat << EOF

    Local Measures ($LOCAL_JOB)
           ↓
    Seed Connectivity ($SEED_JOB)
           ↓
    Between-Network ($BETWEEN_JOB)
           ↓
    Sync Results ($SYNC_JOB)

EOF
fi

echo "Monitor with: squeue -u $USER"
echo "Monitor dependencies with: squeue -u $USER --priority"
echo ""

# =============================================================================
# STEP 5: Summary
# =============================================================================

echo "STEP 5: Orchestration Complete"
echo "==============================="
echo ""
echo "Start time:  $(date)"
echo "Orchestration log: $ORCHESTRATION_LOG"
echo "Results directory: $RESULTS_DIR"
echo ""
echo "Key commands:"
echo "  - Check job status: squeue -u $USER"
echo "  - View job logs: ls -la $LOG_DIR"
echo "  - Check manifest: python3 $SCRIPT_DIR/hpc_manifest.py --manifest $RESULTS_DIR/.manifest.json status"
echo "  - Cancel all jobs: scancel $LOCAL_JOB $SEED_JOB $BETWEEN_JOB $SYNC_JOB $(if [[ "$SUBMIT_GROUP" == "true" ]]; then echo "$GROUP_JOB"; fi)"
echo ""
echo "========================================================================="

} | tee "$ORCHESTRATION_LOG"

exit 0
