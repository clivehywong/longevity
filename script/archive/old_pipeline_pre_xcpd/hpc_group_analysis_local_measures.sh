#!/bin/bash
#SBATCH --job-name=local_group
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=6:00:00
#SBATCH --output=logs/local_group_%j.out
#SBATCH --error=logs/local_group_%j.err

# =============================================================================
# HPC SLURM Script: Group-Level Analysis for Local Measures (fALFF, ReHo)
# =============================================================================
# Runs voxelwise linear mixed-effects analysis on fALFF and ReHo maps
# for Group × Time interaction with permutation testing.
#
# Statistical model:
#   value ~ Group × Time + Age + Sex + MeanFD + (1|Subject)
#
# Multiple comparisons: Permutation testing with TFCE, FWE p < 0.05
# =============================================================================

set -e

echo "================================================================"
echo "Group-Level Local Measures Analysis (fALFF, ReHo) - HPC"
echo "================================================================"
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
LOCAL_MEASURES_DIR="$DERIVATIVE_ROOT/subject-level/local_measures"
METADATA_FILE="$DERIVATIVE_ROOT/participants_all24_final.csv"
OUTPUT_ROOT="$DERIVATIVE_ROOT/group-level/local_measures"

mkdir -p "$OUTPUT_ROOT"
mkdir -p logs

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# Check that input files exist
fALFF_count=$(find "$LOCAL_MEASURES_DIR" -name "*_fALFF.nii.gz" 2>/dev/null | wc -l)
ReHo_count=$(find "$LOCAL_MEASURES_DIR" -name "*_ReHo.nii.gz" 2>/dev/null | wc -l)

echo "Found $fALFF_count fALFF maps and $ReHo_count ReHo maps"

if [ "$fALFF_count" -lt 16 ] || [ "$ReHo_count" -lt 16 ]; then
    echo "ERROR: Insufficient local measure maps found."
    echo "Please run hpc_local_measures_all24.sh first."
    exit 1
fi

echo ""
echo "================================================================"
echo "Step 1: fALFF Group Analysis"
echo "================================================================"
echo ""

OUTPUT_DIR_FALFF="$OUTPUT_ROOT/fALFF"
mkdir -p "$OUTPUT_DIR_FALFF"

python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$LOCAL_MEASURES_DIR/*_fALFF.nii.gz" \
    --metadata "$METADATA_FILE" \
    --output "$OUTPUT_DIR_FALFF" \
    --cluster-threshold 0.05 \
    --n-permutations 5000 \
    --min-cluster-size 50

echo ""
echo "fALFF analysis complete. Output: $OUTPUT_DIR_FALFF"
echo ""

echo "================================================================"
echo "Step 2: ReHo Group Analysis"
echo "================================================================"
echo ""

OUTPUT_DIR_REHO="$OUTPUT_ROOT/ReHo"
mkdir -p "$OUTPUT_DIR_REHO"

python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$LOCAL_MEASURES_DIR/*_ReHo.nii.gz" \
    --metadata "$METADATA_FILE" \
    --output "$OUTPUT_DIR_REHO" \
    --cluster-threshold 0.05 \
    --n-permutations 5000 \
    --min-cluster-size 50

echo ""
echo "ReHo analysis complete. Output: $OUTPUT_DIR_REHO"
echo ""

echo "================================================================"
echo "Group-Level Local Measures Analysis Complete"
echo "================================================================"
echo "End time: $(date)"
echo ""

# Report results
echo "Results summary:"
echo ""
echo "fALFF ($OUTPUT_DIR_FALFF):"
if [ -f "$OUTPUT_DIR_FALFF/interaction_tstat_map.nii.gz" ]; then
    echo "  - T-statistic map generated"
    if [ -f "$OUTPUT_DIR_FALFF/clusters_interaction.csv" ]; then
        n_clusters=$(wc -l < "$OUTPUT_DIR_FALFF/clusters_interaction.csv")
        n_clusters=$((n_clusters - 1))
        echo "  - Significant clusters: $n_clusters"
    fi
else
    echo "  - WARNING: Analysis may have failed, check logs"
fi

echo ""
echo "ReHo ($OUTPUT_DIR_REHO):"
if [ -f "$OUTPUT_DIR_REHO/interaction_tstat_map.nii.gz" ]; then
    echo "  - T-statistic map generated"
    if [ -f "$OUTPUT_DIR_REHO/clusters_interaction.csv" ]; then
        n_clusters=$(wc -l < "$OUTPUT_DIR_REHO/clusters_interaction.csv")
        n_clusters=$((n_clusters - 1))
        echo "  - Significant clusters: $n_clusters"
    fi
else
    echo "  - WARNING: Analysis may have failed, check logs"
fi
