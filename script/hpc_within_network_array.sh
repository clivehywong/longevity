#!/bin/bash
#SBATCH --job-name=within_net
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=4:00:00
#SBATCH --array=1-10
#SBATCH --output=logs/within_net_%A_%a.out
#SBATCH --error=logs/within_net_%A_%a.err

# =============================================================================
# HPC SLURM Array Script: Within-Network Connectivity for 10 Networks
# =============================================================================
# Computes within-network ROI-to-ROI connectivity for each major functional
# network using mixed-effects ANOVA (Group × Time interaction).
#
# Networks (10 total):
# 1. SalienceVentralAttention
# 2. FrontoParietal
# 3. DefaultMode
# 4. DorsalAttention
# 5. Somatomotor
# 6. Visual
# 7. Limbic
# 8. Cerebellar_Motor
# 9. Cerebellar_Cognitive
# 10. Subcortical
#
# Processing time: ~30-60 min per network (depending on ROI count)
# =============================================================================

set -e

echo "================================================================"
echo "Within-Network Connectivity Analysis - Array Job"
echo "================================================================"
echo "Job Array ID: $SLURM_ARRAY_JOB_ID"
echo "Array Task ID: $SLURM_ARRAY_TASK_ID"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: 16GB"
echo "Start time: $(date)"
echo ""

# Paths on HPC
PROJECT_DIR="/home/clivewong/proj/long"
SCRIPT_DIR="$PROJECT_DIR/script"
ATLASES_DIR="$PROJECT_DIR/atlases"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
TIMESERIES_FILE="$DERIVATIVE_ROOT/subject-level/timeseries_difumo256.h5"
METADATA_FILE="$DERIVATIVE_ROOT/participants_all24_final.csv"
NETWORK_DEFS="$ATLASES_DIR/difumo256_network_definitions.json"
OUTPUT_ROOT="$DERIVATIVE_ROOT/group-level/network"

mkdir -p "$OUTPUT_ROOT"
mkdir -p logs

# Check that timeseries file exists
if [ ! -f "$TIMESERIES_FILE" ]; then
    echo "ERROR: Timeseries file not found: $TIMESERIES_FILE"
    echo "Please run hpc_extract_timeseries_difumo256.sh first."
    exit 1
fi

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# Define network list (10 networks)
NETWORKS=(
    "SalienceVentralAttention"
    "FrontoParietal"
    "DefaultMode"
    "DorsalAttention"
    "Somatomotor"
    "Visual"
    "Limbic"
    "Cerebellar_Motor"
    "Cerebellar_Cognitive"
    "Subcortical"
)

# Get network for this array task
NET=${NETWORKS[$SLURM_ARRAY_TASK_ID-1]}
OUTPUT_DIR="$OUTPUT_ROOT/within_$NET"

echo "Processing network: $NET"
echo "Array task: $SLURM_ARRAY_TASK_ID / ${#NETWORKS[@]}"
echo "Output: $OUTPUT_DIR"
echo ""

mkdir -p "$OUTPUT_DIR"

# Run within-network connectivity analysis
python "$SCRIPT_DIR/python_connectivity_analysis.py" \
    --timeseries "$TIMESERIES_FILE" \
    --metadata "$METADATA_FILE" \
    --networks "$NETWORK_DEFS" \
    --output "$OUTPUT_DIR" \
    --within-network "$NET" \
    --alpha 0.05

echo ""
echo "================================================================"
echo "Within-Network Analysis Complete for $NET"
echo "================================================================"
echo "End time: $(date)"
echo ""

# Report results
if [ -f "$OUTPUT_DIR/connectivity_anova_results.csv" ]; then
    n_tests=$(wc -l < "$OUTPUT_DIR/connectivity_anova_results.csv")
    n_tests=$((n_tests - 1))  # Subtract header
    echo "Results: $n_tests ROI pairs tested"

    if [ -f "$OUTPUT_DIR/significant_interactions_fdr.csv" ]; then
        n_sig=$(wc -l < "$OUTPUT_DIR/significant_interactions_fdr.csv")
        n_sig=$((n_sig - 1))  # Subtract header
        echo "Significant interactions (FDR q<0.05): $n_sig"
    fi
    echo "Output files: $OUTPUT_DIR/"
else
    echo "WARNING: No results file found. Check error logs."
fi
