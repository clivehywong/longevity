#!/bin/bash
#SBATCH --job-name=seed_connectivity
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=6:00:00
#SBATCH --array=1-17%16
#SBATCH --output=logs/seed_connectivity_%A_%a.out
#SBATCH --error=logs/seed_connectivity_%A_%a.err

# =============================================================================
# HPC SLURM Array Script: Seed-Based Connectivity with Manifest Tracking
# =============================================================================
# Runs seed-based connectivity analysis in parallel for multiple seeds
# with automatic manifest completion recording.
#
# Features:
# - Proper job array logging with task IDs
# - Manifest completion tracking for group analysis validation
# - Automatic cleanup markers on success/failure
# - Comprehensive error reporting
#
# Processing time: ~3-5 min per subject per seed
# Parallelized via SLURM array
# =============================================================================

set -e

echo "================================================================"
echo "Seed-Based Connectivity Analysis - Array Job with Manifest"
echo "================================================================"
echo "Job Array ID: $SLURM_ARRAY_JOB_ID"
echo "Array Task ID: $SLURM_ARRAY_TASK_ID"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: 16GB"
echo "Start time: $(date)"
echo ""

# =============================================================================
# CONFIGURATION
# =============================================================================

# Paths on HPC
PROJECT_DIR="${PROJECT_DIR:-/home/clivewong/proj/long}"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
SCRIPT_DIR="$PROJECT_DIR/script"
ATLASES_DIR="$PROJECT_DIR/atlases"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
METADATA_FILE="$DERIVATIVE_ROOT/participants_all24_final.csv"
SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"
MANIFEST_FILE="$DERIVATIVE_ROOT/.manifest.json"

# Export manifest path for Python scripts
export MANIFEST_FILE

# Create output directories
mkdir -p "$SEED_DIR"
mkdir -p logs
mkdir -p "$(dirname "$MANIFEST_FILE")"

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# =============================================================================
# Get subject, seed, and atlas for this task
# =============================================================================

# Parse task index to get subject, seed, atlas combination
# Task array can iterate through: subjects × seeds × atlases

# Subject list from metadata or environment
SUBJECTS_STR="${SUBJECTS:-sub-033,sub-034,sub-035,sub-036,sub-037,sub-038,sub-039,sub-040}"
IFS=',' read -ra SUBJECT_ARRAY <<< "$SUBJECTS_STR"
NUM_SUBJECTS=${#SUBJECT_ARRAY[@]}

# Seed list
SEED_LIST=(
    "Anterior_Insula"
    "dACC"
    "Insula_dACC_Combined"
    "Hippocampus"
    "Hippocampus_Anterior"
    "Hippocampus_Posterior"
    "Cerebellar_Cognitive_L"
    "Cerebellar_Cognitive_R"
    "Cerebellar_Cognitive_Bilateral"
    "Cerebellar_Motor"
    "Cerebellar_Vestibular"
    "Motor_Cortex"
    "Default_Mode"
    "Frontoparietal_Control"
    "DLPFC_Coarse"
    "DLPFC_Dorsal"
    "DLPFC_Ventral"
)
NUM_SEEDS=${#SEED_LIST[@]}

# Atlas list
ATLASES_STR="${ATLASES:-difumo256,schaefer400}"
IFS=',' read -ra ATLAS_ARRAY <<< "$ATLASES_STR"
NUM_ATLASES=${#ATLAS_ARRAY[@]}

# Calculate which subject/seed/atlas combination for this array task
# Simple linear indexing through subjects × seeds × atlases
TASK_INDEX=$((SLURM_ARRAY_TASK_ID - 1))  # Convert to 0-based

# For simpler implementation, iterate through subjects with all seeds/atlases fixed
SUBJECT_INDEX=$((TASK_INDEX % NUM_SUBJECTS))
SEED_INDEX=$((TASK_INDEX / NUM_SUBJECTS))

SUBJECT="${SUBJECT_ARRAY[$SUBJECT_INDEX]}"
SEED="${SEED_LIST[$SEED_INDEX]}"
ATLAS="${ATLAS_ARRAY[0]}"  # Default to first atlas
SESSION="ses-01"  # Default session

echo "Task Index: $TASK_INDEX"
echo "Subject: $SUBJECT ($((SUBJECT_INDEX + 1))/$NUM_SUBJECTS)"
echo "Seed: $SEED ($((SEED_INDEX + 1))/$NUM_SEEDS)"
echo "Atlas: $ATLAS"
echo "Session: $SESSION"
echo ""

# Convert to lowercase for output dir naming
SEED_LOWER=$(echo "$SEED" | tr '[:upper:]' '[:lower:]' | tr '_' '_')

# =============================================================================
# RUN ANALYSIS
# =============================================================================

echo "Running seed-based connectivity analysis..."
echo ""

ANALYSIS_EXIT_CODE=0

if python "$SCRIPT_DIR/seed_based_connectivity.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$ATLASES_DIR/motor_cerebellar_seeds.json" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --subject "$SUBJECT" \
    --seed-names "$SEED" \
    --atlas "$ATLAS" \
    --smoothing 6.0 \
    --high-pass 0.01 \
    --low-pass 0.1; then
    ANALYSIS_EXIT_CODE=0
    echo "[SUCCESS] Analysis completed for $SUBJECT $SESSION $SEED $ATLAS"
else
    ANALYSIS_EXIT_CODE=$?
    echo "[ERROR] Analysis failed with exit code $ANALYSIS_EXIT_CODE"
fi

echo ""

# =============================================================================
# RECORD COMPLETION IN MANIFEST
# =============================================================================

echo "Recording completion in manifest..."
echo ""

if [ $ANALYSIS_EXIT_CODE -eq 0 ]; then
    # Get output path for metadata
    OUTPUT_PATH="$SEED_DIR/${SEED_LOWER}"
    
    # Record successful completion
    python3 "$SCRIPT_DIR/hpc_manifest.py" \
        --manifest "$MANIFEST_FILE" \
        record \
        --subject "$SUBJECT" \
        --session "$SESSION" \
        --seed "$SEED_LOWER" \
        --atlas "$ATLAS" \
        --status "complete" \
        --output "$OUTPUT_PATH" \
        --job-id "$SLURM_JOB_ID"
    
    COMPLETION_STATUS="complete"
    
    # Create completion marker
    DONE_FILE="$SEED_DIR/${SEED_LOWER}/.${SUBJECT}_${SESSION}.done"
    mkdir -p "$(dirname "$DONE_FILE")"
    touch "$DONE_FILE"
    
else
    # Record failure
    python3 "$SCRIPT_DIR/hpc_manifest.py" \
        --manifest "$MANIFEST_FILE" \
        record \
        --subject "$SUBJECT" \
        --session "$SESSION" \
        --seed "$SEED_LOWER" \
        --atlas "$ATLAS" \
        --status "failed" \
        --job-id "$SLURM_JOB_ID"
    
    COMPLETION_STATUS="failed"
fi

# =============================================================================
# SUMMARY
# =============================================================================

echo ""
echo "================================================================"
echo "Seed-Based Connectivity Analysis Summary"
echo "================================================================"
echo "Status: $COMPLETION_STATUS"
echo "Subject: $SUBJECT"
echo "Session: $SESSION"
echo "Seed: $SEED"
echo "Atlas: $ATLAS"
echo "Job ID: $SLURM_JOB_ID"
echo "Array Task: $SLURM_ARRAY_TASK_ID"
echo "End time: $(date)"
echo "================================================================"
echo ""

# Exit with the analysis exit code so SLURM records success/failure
exit $ANALYSIS_EXIT_CODE
