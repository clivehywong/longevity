#!/bin/bash
#SBATCH --job-name=seed_group
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=8:00:00
#SBATCH --array=1-14
#SBATCH --output=logs/seed_group_%A_%a.out
#SBATCH --error=logs/seed_group_%A_%a.err

# =============================================================================
# HPC SLURM Array Script: Group-Level Seed-Based Connectivity Analysis
# =============================================================================
# Runs voxelwise linear mixed-effects analysis on seed-based connectivity
# z-maps for Group × Time interaction with permutation testing.
#
# Seeds (13 total, excluding already-completed DLPFC_L/R/Bilateral):
# - Salience: Anterior_Insula, dACC, Insula_dACC_Combined
# - Hippocampus: unified, Anterior, Posterior
# - Cerebellar: Cognitive_L, Cognitive_R, Cognitive_Bilateral, Motor
# - Motor_Cortex
# - Networks: Default_Mode, Frontoparietal_Control
#
# Statistical model:
#   connectivity_z ~ Group × Time + Age + Sex + MeanFD + (1|Subject)
#
# Multiple comparisons: Permutation testing with TFCE, FWE p < 0.05
# =============================================================================

set -e

echo "================================================================"
echo "Seed-Based Group Analysis - Array Job"
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

# Define seed list (14 seeds excluding already-completed DLPFC L/R/Bilateral)
# These should match the lowercase directory names in subject-level/seed_based/
SEEDS=(
    "anterior_insula"
    "dacc"
    "insula_dacc_combined"
    "hippocampus"
    "hippocampus_anterior"
    "hippocampus_posterior"
    "cerebellar_cognitive_l"
    "cerebellar_cognitive_r"
    "cerebellar_cognitive_bilateral"
    "cerebellar_motor"
    "cerebellar_vestibular"
    "motor_cortex"
    "default_mode"
    "frontoparietal_control"
)

# Get seed for this array task
SEED=${SEEDS[$SLURM_ARRAY_TASK_ID-1]}
INPUT_DIR="$SEED_INPUT_ROOT/$SEED"
OUTPUT_DIR="$OUTPUT_ROOT/$SEED"

echo "Processing seed: $SEED"
echo "Array task: $SLURM_ARRAY_TASK_ID / ${#SEEDS[@]}"
echo "Input: $INPUT_DIR"
echo "Output: $OUTPUT_DIR"
echo ""

# Check that input directory exists
if [ ! -d "$INPUT_DIR" ]; then
    echo "ERROR: Input directory not found: $INPUT_DIR"
    echo "Please run hpc_seed_connectivity_array.sh first to generate subject-level z-maps."
    exit 1
fi

# Count available z-maps
zmap_count=$(find "$INPUT_DIR" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
echo "Found $zmap_count z-maps for $SEED"

if [ "$zmap_count" -lt 40 ]; then
    echo "WARNING: Only $zmap_count z-maps found. Expected 48 (24 subjects × 2 sessions)."
    echo "Proceeding with available data..."
fi

mkdir -p "$OUTPUT_DIR"

# Run group-level analysis with permutation testing
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

    # Check for significant clusters
    if [ -f "$OUTPUT_DIR/clusters_interaction.csv" ]; then
        n_clusters=$(wc -l < "$OUTPUT_DIR/clusters_interaction.csv")
        n_clusters=$((n_clusters - 1))  # Subtract header
        echo "Significant clusters: $n_clusters"
    fi
else
    echo "WARNING: Output files not generated. Check error logs."
fi
