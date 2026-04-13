#!/bin/bash
#SBATCH --job-name=grp_dlpfc_bi
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=2:00:00
#SBATCH --output=logs/grp_dlpfc_bilateral_%j.out
#SBATCH --error=logs/grp_dlpfc_bilateral_%j.err

# =============================================================================
# SLURM Job for DLPFC_Bilateral Group-Level Analysis
# =============================================================================
# Usage: sbatch script/hpc_group_analysis_dlpfc_bilateral.sh
# =============================================================================

set -e

SEED="dlpfc_bilateral"
SEED_DISPLAY="DLPFC_Bilateral"

echo "================================================================"
echo "Group-Level Analysis: $SEED_DISPLAY"
echo "================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Start time: $(date)"
echo ""

# Paths
PROJECT_DIR="/home/clivewong/proj/long"
SCRIPT_DIR="$PROJECT_DIR/script"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"
OUTPUT_DIR="$DERIVATIVE_ROOT/group-level/seed_based/$SEED"

mkdir -p "$OUTPUT_DIR"
mkdir -p "$PROJECT_DIR/logs"

# Activate conda
echo "Activating conda environment..."
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

echo "Python: $(which python)"
python -c "import nilearn; print(f'nilearn: {nilearn.__version__}')"
echo ""

# Metadata
METADATA_FILE="$DERIVATIVE_ROOT/participants_all24_final.csv"
if [ ! -f "$METADATA_FILE" ]; then
    echo "ERROR: Metadata file not found: $METADATA_FILE"
    exit 1
fi

# Count z-maps
INPUT_DIR="$SEED_DIR/$SEED"
N_MAPS=$(find "$INPUT_DIR" -name '*_zmap.nii.gz' 2>/dev/null | wc -l)
echo "Found $N_MAPS z-maps for $SEED_DISPLAY"

if [ "$N_MAPS" -eq 0 ]; then
    echo "ERROR: No z-maps found in $INPUT_DIR"
    exit 1
fi

# Run group analysis
echo ""
echo "Running group-level analysis (parametric stats only)..."
echo ""

python "$SCRIPT_DIR/group_level_analysis_fast.py" \
    --input-maps $INPUT_DIR/*_zmap.nii.gz \
    --metadata "$METADATA_FILE" \
    --output "$OUTPUT_DIR" \
    --cluster-threshold 0.05 \
    --min-cluster-size 50 \
    --n-jobs 4

echo ""
echo "================================================================"
echo "$SEED_DISPLAY Analysis Complete"
echo "================================================================"
echo "End time: $(date)"
echo ""

# Summary
ls -lh "$OUTPUT_DIR"/ 2>/dev/null

if [ -f "$OUTPUT_DIR/clusters_interaction.csv" ]; then
    n_clusters=$(tail -n +2 "$OUTPUT_DIR/clusters_interaction.csv" 2>/dev/null | wc -l)
    echo "✓ Found $n_clusters significant clusters"
fi

echo "Done!"
