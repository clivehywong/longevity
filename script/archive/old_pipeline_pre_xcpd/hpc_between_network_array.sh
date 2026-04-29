#!/bin/bash
#SBATCH --job-name=between_net
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=8:00:00
#SBATCH --array=1-5
#SBATCH --output=logs/between_net_%A_%a.out
#SBATCH --error=logs/between_net_%A_%a.err

# =============================================================================
# HPC SLURM Array Script: Between-Network Connectivity for 5 Priority Pairs
# =============================================================================
# Computes between-network ROI-to-ROI connectivity for hypothesis-driven
# network pairs using mixed-effects ANOVA (Group × Time interaction).
#
# Priority Network Pairs (5 total):
# 1. FrontoParietal ↔ Cerebellar_Cognitive (executive-cerebellar)
# 2. SalienceVentralAttention ↔ DefaultMode (canonical anticorrelation)
# 3. Somatomotor ↔ Cerebellar_Motor (motor-cerebellar)
# 4. FrontoParietal ↔ DefaultMode (task-positive vs task-negative)
# 5. Limbic ↔ Cerebellar_Cognitive (emotion-cognition)
#
# Processing time: ~1-2 hours per pair (cross-network has many connections)
# =============================================================================

set -e

echo "================================================================"
echo "Between-Network Connectivity Analysis - Array Job"
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

# Define network pairs (5 priority pairs)
# Format: "NetworkA:NetworkB"
NETWORK_PAIRS=(
    "FrontoParietal:Cerebellar_Cognitive"
    "SalienceVentralAttention:DefaultMode"
    "Somatomotor:Cerebellar_Motor"
    "FrontoParietal:DefaultMode"
    "Limbic:Cerebellar_Cognitive"
)

# Get network pair for this array task
PAIR=${NETWORK_PAIRS[$SLURM_ARRAY_TASK_ID-1]}
NET1=$(echo $PAIR | cut -d: -f1)
NET2=$(echo $PAIR | cut -d: -f2)

# Create output directory name (use underscores, lowercase)
PAIR_NAME="${NET1}_${NET2}"
OUTPUT_DIR="$OUTPUT_ROOT/between_$PAIR_NAME"

echo "Processing network pair: $NET1 ↔ $NET2"
echo "Array task: $SLURM_ARRAY_TASK_ID / ${#NETWORK_PAIRS[@]}"
echo "Output: $OUTPUT_DIR"
echo ""

mkdir -p "$OUTPUT_DIR"

# Run between-network connectivity analysis
python "$SCRIPT_DIR/python_connectivity_analysis.py" \
    --timeseries "$TIMESERIES_FILE" \
    --metadata "$METADATA_FILE" \
    --networks "$NETWORK_DEFS" \
    --output "$OUTPUT_DIR" \
    --between-networks "$NET1" "$NET2" \
    --alpha 0.05

echo ""
echo "================================================================"
echo "Between-Network Analysis Complete for $NET1 ↔ $NET2"
echo "================================================================"
echo "End time: $(date)"
echo ""

# Report results
if [ -f "$OUTPUT_DIR/connectivity_anova_results.csv" ]; then
    n_tests=$(wc -l < "$OUTPUT_DIR/connectivity_anova_results.csv")
    n_tests=$((n_tests - 1))  # Subtract header
    echo "Results: $n_tests cross-network connections tested"

    if [ -f "$OUTPUT_DIR/significant_interactions_fdr.csv" ]; then
        n_sig=$(wc -l < "$OUTPUT_DIR/significant_interactions_fdr.csv")
        n_sig=$((n_sig - 1))  # Subtract header
        echo "Significant interactions (FDR q<0.05): $n_sig"
    fi
    echo "Output files: $OUTPUT_DIR/"
else
    echo "WARNING: No results file found. Check error logs."
fi
