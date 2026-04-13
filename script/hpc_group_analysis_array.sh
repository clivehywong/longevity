#!/bin/bash
#SBATCH --job-name=group_analysis
#SBATCH --array=0-11
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=08:00:00
#SBATCH --output=logs/group_analysis_%A_%a.out
#SBATCH --error=logs/group_analysis_%A_%a.err

#
# SLURM Array Job for Group-Level Voxelwise Analysis (HPC)
#
# Runs voxelwise analysis for all 12 seeds in parallel
#
# Usage:
#   sbatch script/hpc_group_analysis_array.sh
#
# Requirements:
#   - Subject-level z-maps uploaded to HPC
#   - Metadata and group files uploaded
#   - Python environment with nibabel, nilearn, statsmodels
#

set -e

# HPC paths (adjust as needed)
PROJECT_DIR="${HOME}/proj/long"
SUBJECT_LEVEL="${PROJECT_DIR}/derivatives/connectivity-difumo256/subject-level"
METADATA="${PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/participants_updated.tsv"
GROUP_FILE="${PROJECT_DIR}/group.csv"
OUTPUT_DIR="${PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/group-level"

# Create logs directory
mkdir -p logs

# Seed array (matches SLURM array indices)
SEEDS=(
    "motor_cortex"
    "cerebellar_motor"
    "cerebellar_cognitive"
    "hippocampus"
    "dlpfc_coarse"
    "dlpfc_dorsal"
    "dlpfc_ventral"
    "anterior_insula"
    "dacc"
    "insula_dacc_combined"
    "hippocampus_anterior"
    "hippocampus_posterior"
)

# Get seed for this array task
SEED="${SEEDS[$SLURM_ARRAY_TASK_ID]}"

echo "================================================================"
echo "GROUP-LEVEL ANALYSIS - SEED: ${SEED}"
echo "================================================================"
echo "SLURM Job ID: ${SLURM_JOB_ID}"
echo "Array Task ID: ${SLURM_ARRAY_TASK_ID}"
echo "Running on: $(hostname)"
echo "Started at: $(date)"
echo "================================================================"
echo ""

# Check input directory
SEED_DIR="${SUBJECT_LEVEL}/seed_based/${SEED}"
if [ ! -d "$SEED_DIR" ]; then
    echo "ERROR: Seed directory not found: $SEED_DIR"
    exit 1
fi

# Count z-maps
N_MAPS=$(ls "$SEED_DIR"/*_zmap.nii.gz 2>/dev/null | wc -l)
echo "Found $N_MAPS z-maps for ${SEED}"

if [ "$N_MAPS" -lt 10 ]; then
    echo "ERROR: Too few maps for analysis ($N_MAPS < 10)"
    exit 1
fi

# Output directory for this seed
OUTPUT_SEED_DIR="${OUTPUT_DIR}/seed_${SEED}"
mkdir -p "$OUTPUT_SEED_DIR"

echo ""
echo "Configuration:"
echo "  Subject-level: $SUBJECT_LEVEL"
echo "  Metadata: $METADATA"
echo "  Group file: $GROUP_FILE"
echo "  Output: $OUTPUT_SEED_DIR"
echo "  N permutations: 5000"
echo ""

# Activate conda environment
source ${HOME}/miniconda3/etc/profile.d/conda.sh
conda activate connectivity

# Run group-level analysis
python script/group_level_analysis.py \
    --input-maps "$SEED_DIR"/*_zmap.nii.gz \
    --metadata "$METADATA" \
    --group-file "$GROUP_FILE" \
    --output "$OUTPUT_SEED_DIR" \
    --cluster-threshold 0.05 \
    --n-permutations 5000 \
    --min-cluster-size 50

EXIT_CODE=$?

echo ""
echo "================================================================"
echo "ANALYSIS COMPLETE - SEED: ${SEED}"
echo "================================================================"
echo "Exit code: $EXIT_CODE"
echo "Finished at: $(date)"
echo ""

# Show results summary
if [ -f "$OUTPUT_SEED_DIR/correction_info.json" ]; then
    echo "Correction method:"
    cat "$OUTPUT_SEED_DIR/correction_info.json"
    echo ""
fi

if [ -f "$OUTPUT_SEED_DIR/clusters_interaction.csv" ]; then
    N_CLUSTERS=$(tail -n +2 "$OUTPUT_SEED_DIR/clusters_interaction.csv" | wc -l)
    echo "Significant clusters: $N_CLUSTERS"

    if [ "$N_CLUSTERS" -gt 0 ]; then
        echo ""
        echo "Top clusters:"
        head -6 "$OUTPUT_SEED_DIR/clusters_interaction.csv"
    fi
else
    echo "No significant clusters found"
fi

echo ""
echo "Output files:"
ls -lh "$OUTPUT_SEED_DIR" | grep -v "^d"
echo "================================================================"

exit $EXIT_CODE
