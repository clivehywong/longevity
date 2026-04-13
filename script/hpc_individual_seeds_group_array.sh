#!/bin/bash
#SBATCH --job-name=indiv_group
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=10:00:00
#SBATCH --array=1-43
#SBATCH --output=logs/indiv_group_%A_%a.out
#SBATCH --error=logs/indiv_group_%A_%a.err

# =============================================================================
# HPC SLURM Array Script: Group Analysis for Individual Component Seeds
# =============================================================================
# Runs voxelwise linear mixed-effects analysis on individual DiFuMo component
# seed-based connectivity z-maps for Group × Time interaction.
#
# 43 individual seeds:
# - 10 FrontoParietal frontal
# - 23 Somatomotor (focus on motor network hypothesis)
# - 10 Cerebellar Cognitive
#
# Statistical model:
#   connectivity_z ~ Group × Time + Age + Sex + MeanFD + (1|Subject)
# =============================================================================

set -e

echo "================================================================"
echo "Individual Seed Group Analysis - Array Job"
echo "================================================================"
echo "Job Array ID: $SLURM_ARRAY_JOB_ID"
echo "Array Task ID: $SLURM_ARRAY_TASK_ID"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: 32GB"
echo "Start time: $(date)"
echo ""

# Paths on HPC
PROJECT_DIR="/home/clivewong/proj/long"
SCRIPT_DIR="$PROJECT_DIR/script"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
SEED_INPUT_ROOT="$DERIVATIVE_ROOT/subject-level/seed_based"
METADATA_FILE="$DERIVATIVE_ROOT/participants_all24_final.csv"
OUTPUT_ROOT="$DERIVATIVE_ROOT/group-level/seed_based"

mkdir -p "$OUTPUT_ROOT"
mkdir -p logs

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# Define individual seed list (43 seeds - lowercase directory names)
SEEDS=(
    # FrontoParietal frontal (10)
    "fp_001" "fp_056" "fp_066" "fp_093" "fp_115"
    "fp_120" "fp_140" "fp_143" "fp_191" "fp_213"

    # Somatomotor (23)
    "sm_022" "sm_025" "sm_043" "sm_047" "sm_050"
    "sm_082" "sm_085" "sm_086" "sm_099" "sm_114"
    "sm_122" "sm_136" "sm_141" "sm_151" "sm_162"
    "sm_166" "sm_185" "sm_190" "sm_200" "sm_203"
    "sm_218" "sm_238" "sm_254"

    # Cerebellar Cognitive (10)
    "cb_035" "cb_080" "cb_090" "cb_142" "cb_146"
    "cb_155" "cb_171" "cb_178" "cb_186" "cb_208"
)

# Get seed for this array task
SEED=${SEEDS[$SLURM_ARRAY_TASK_ID-1]}
INPUT_DIR="$SEED_INPUT_ROOT/$SEED"
OUTPUT_DIR="$OUTPUT_ROOT/$SEED"

echo "Processing individual seed: $SEED"
echo "Array task: $SLURM_ARRAY_TASK_ID / ${#SEEDS[@]}"
echo "Input: $INPUT_DIR"
echo "Output: $OUTPUT_DIR"
echo ""

# Check that input directory exists
if [ ! -d "$INPUT_DIR" ]; then
    echo "ERROR: Input directory not found: $INPUT_DIR"
    echo "Please run hpc_individual_seeds_array.sh first."
    exit 1
fi

# Count available z-maps
zmap_count=$(find "$INPUT_DIR" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
echo "Found $zmap_count z-maps for $SEED"

if [ "$zmap_count" -lt 40 ]; then
    echo "WARNING: Only $zmap_count z-maps found. Expected 48."
    echo "Proceeding with available data..."
fi

mkdir -p "$OUTPUT_DIR"

# Run group-level analysis
python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$INPUT_DIR/*_zmap.nii.gz" \
    --metadata "$METADATA_FILE" \
    --output "$OUTPUT_DIR" \
    --cluster-threshold 0.05 \
    --n-permutations 5000 \
    --min-cluster-size 50

echo ""
echo "================================================================"
echo "Group Analysis Complete for $SEED"
echo "================================================================"
echo "End time: $(date)"
echo ""

# Report results
if [ -f "$OUTPUT_DIR/interaction_tstat_map.nii.gz" ]; then
    echo "Results generated successfully:"
    ls -la "$OUTPUT_DIR/"
    echo ""

    if [ -f "$OUTPUT_DIR/clusters_interaction.csv" ]; then
        n_clusters=$(wc -l < "$OUTPUT_DIR/clusters_interaction.csv")
        n_clusters=$((n_clusters - 1))
        echo "Significant clusters: $n_clusters"
    fi
else
    echo "WARNING: Output files not generated. Check error logs."
fi
