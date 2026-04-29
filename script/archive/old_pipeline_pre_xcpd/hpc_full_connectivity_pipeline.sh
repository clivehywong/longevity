#!/bin/bash
# =============================================================================
# HPC Full Connectivity Analysis Pipeline - Master Orchestrator
# =============================================================================
# This script orchestrates the complete connectivity analysis pipeline on HPC
# using SLURM job dependencies to ensure proper execution order.
#
# Pipeline stages:
# 1. Local measures (fALFF, ReHo) for all 24 subjects
# 2. Seed-based connectivity (16 priority seeds)
# 3. Timeseries extraction for network connectivity
# 4. Within-network connectivity (10 networks)
# 5. Between-network connectivity (5 priority pairs)
# 6. Group-level analyses (local measures, seed-based)
# 7. HTML report generation (final)
#
# Usage:
#   bash hpc_full_connectivity_pipeline.sh [--dry-run] [--stage N]
#
# Options:
#   --dry-run    Show what would be submitted without actually submitting
#   --stage N    Start from stage N (1-7)
# =============================================================================

set -e

# Parse arguments
DRY_RUN=false
START_STAGE=1

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --stage)
            START_STAGE=$2
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

PROJECT_DIR="/home/clivewong/proj/long"
SCRIPT_DIR="$PROJECT_DIR/script"
LOG_FILE="$PROJECT_DIR/logs/pipeline_$(date +%Y%m%d_%H%M%S).log"

mkdir -p "$PROJECT_DIR/logs"

echo "================================================================"
echo "HPC Full Connectivity Analysis Pipeline"
echo "================================================================"
echo "Start time: $(date)"
echo "Start stage: $START_STAGE"
echo "Dry run: $DRY_RUN"
echo "Log file: $LOG_FILE"
echo ""

# Function to submit job
submit_job() {
    local script=$1
    local dependency=$2
    local job_name=$(basename $script .sh)

    if [ "$DRY_RUN" = true ]; then
        if [ -z "$dependency" ]; then
            echo "[DRY RUN] sbatch $script"
        else
            echo "[DRY RUN] sbatch --dependency=afterok:$dependency $script"
        fi
        echo "MOCK_JOB_ID"
    else
        if [ -z "$dependency" ]; then
            sbatch "$script" 2>&1 | tee -a "$LOG_FILE" | grep -o '[0-9]*$'
        else
            sbatch --dependency=afterok:$dependency "$script" 2>&1 | tee -a "$LOG_FILE" | grep -o '[0-9]*$'
        fi
    fi
}

# Function to submit array job
submit_array_job() {
    local script=$1
    local dependency=$2
    local job_name=$(basename $script .sh)

    if [ "$DRY_RUN" = true ]; then
        if [ -z "$dependency" ]; then
            echo "[DRY RUN] sbatch $script"
        else
            echo "[DRY RUN] sbatch --dependency=afterok:$dependency $script"
        fi
        echo "MOCK_ARRAY_ID"
    else
        if [ -z "$dependency" ]; then
            sbatch "$script" 2>&1 | tee -a "$LOG_FILE" | grep -o '[0-9]*$'
        else
            sbatch --dependency=afterok:$dependency "$script" 2>&1 | tee -a "$LOG_FILE" | grep -o '[0-9]*$'
        fi
    fi
}

# Track job IDs for dependencies
JOB_LOCAL_MEASURES=""
JOB_SEED_CONN=""
JOB_TIMESERIES=""
JOB_WITHIN_NET=""
JOB_BETWEEN_NET=""
JOB_GROUP_LOCAL=""
JOB_GROUP_SEED=""

echo "================================================================"
echo "Submitting Pipeline Jobs"
echo "================================================================"
echo ""

# STAGE 1: Local Measures (fALFF, ReHo)
if [ $START_STAGE -le 1 ]; then
    echo "Stage 1: Local Measures (fALFF, ReHo)"
    JOB_LOCAL_MEASURES=$(submit_job "$SCRIPT_DIR/hpc_local_measures_all24.sh" "")
    echo "  Submitted job: $JOB_LOCAL_MEASURES"
    echo ""
fi

# STAGE 2: Seed-Based Connectivity (Array)
if [ $START_STAGE -le 2 ]; then
    echo "Stage 2: Seed-Based Connectivity (16 seeds)"
    JOB_SEED_CONN=$(submit_array_job "$SCRIPT_DIR/hpc_seed_connectivity_array.sh" "")
    echo "  Submitted array job: $JOB_SEED_CONN"
    echo ""
fi

# STAGE 3: Timeseries Extraction (depends on nothing, can run in parallel)
if [ $START_STAGE -le 3 ]; then
    echo "Stage 3: Timeseries Extraction (DiFuMo 256)"
    JOB_TIMESERIES=$(submit_job "$SCRIPT_DIR/hpc_extract_timeseries_difumo256.sh" "")
    echo "  Submitted job: $JOB_TIMESERIES"
    echo ""
fi

# STAGE 4: Within-Network Connectivity (depends on timeseries)
if [ $START_STAGE -le 4 ]; then
    echo "Stage 4: Within-Network Connectivity (10 networks)"
    if [ -n "$JOB_TIMESERIES" ]; then
        JOB_WITHIN_NET=$(submit_array_job "$SCRIPT_DIR/hpc_within_network_array.sh" "$JOB_TIMESERIES")
    else
        JOB_WITHIN_NET=$(submit_array_job "$SCRIPT_DIR/hpc_within_network_array.sh" "")
    fi
    echo "  Submitted array job: $JOB_WITHIN_NET"
    echo ""
fi

# STAGE 5: Between-Network Connectivity (depends on timeseries)
if [ $START_STAGE -le 5 ]; then
    echo "Stage 5: Between-Network Connectivity (5 pairs)"
    if [ -n "$JOB_TIMESERIES" ]; then
        JOB_BETWEEN_NET=$(submit_array_job "$SCRIPT_DIR/hpc_between_network_array.sh" "$JOB_TIMESERIES")
    else
        JOB_BETWEEN_NET=$(submit_array_job "$SCRIPT_DIR/hpc_between_network_array.sh" "")
    fi
    echo "  Submitted array job: $JOB_BETWEEN_NET"
    echo ""
fi

# STAGE 6A: Group-Level Local Measures (depends on local measures)
if [ $START_STAGE -le 6 ]; then
    echo "Stage 6A: Group-Level Local Measures (fALFF, ReHo)"
    if [ -n "$JOB_LOCAL_MEASURES" ]; then
        JOB_GROUP_LOCAL=$(submit_job "$SCRIPT_DIR/hpc_group_analysis_local_measures.sh" "$JOB_LOCAL_MEASURES")
    else
        JOB_GROUP_LOCAL=$(submit_job "$SCRIPT_DIR/hpc_group_analysis_local_measures.sh" "")
    fi
    echo "  Submitted job: $JOB_GROUP_LOCAL"
    echo ""
fi

# STAGE 6B: Group-Level Seed Analysis (depends on seed connectivity)
if [ $START_STAGE -le 6 ]; then
    echo "Stage 6B: Group-Level Seed Analysis (13 seeds)"
    if [ -n "$JOB_SEED_CONN" ]; then
        JOB_GROUP_SEED=$(submit_array_job "$SCRIPT_DIR/hpc_seed_group_analysis_array.sh" "$JOB_SEED_CONN")
    else
        JOB_GROUP_SEED=$(submit_array_job "$SCRIPT_DIR/hpc_seed_group_analysis_array.sh" "")
    fi
    echo "  Submitted array job: $JOB_GROUP_SEED"
    echo ""
fi

echo "================================================================"
echo "Pipeline Submission Complete"
echo "================================================================"
echo ""
echo "Job Summary:"
echo "  Stage 1 (Local Measures):      $JOB_LOCAL_MEASURES"
echo "  Stage 2 (Seed Connectivity):   $JOB_SEED_CONN"
echo "  Stage 3 (Timeseries):          $JOB_TIMESERIES"
echo "  Stage 4 (Within-Network):      $JOB_WITHIN_NET"
echo "  Stage 5 (Between-Network):     $JOB_BETWEEN_NET"
echo "  Stage 6A (Group Local):        $JOB_GROUP_LOCAL"
echo "  Stage 6B (Group Seed):         $JOB_GROUP_SEED"
echo ""
echo "Monitor jobs with: squeue -u \$USER"
echo "Check status with: sacct -j JOB_ID"
echo ""
echo "After all jobs complete, run Stage 7 (HTML Report) locally:"
echo "  python script/generate_html_report.py \\"
echo "      --results-dir derivatives/connectivity-difumo256/group-level \\"
echo "      --output derivatives/connectivity-difumo256/group-level/comprehensive_connectivity_report.html"
echo ""
echo "Log file: $LOG_FILE"
