#!/bin/bash
#SBATCH --job-name=grp_dlpfc_parallel
#SBATCH --array=1-2
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=2:00:00
#SBATCH --output=logs/grp_dlpfc_%A_%a.out
#SBATCH --error=logs/grp_dlpfc_%A_%a.err

# =============================================================================
# SLURM Array Job for Parallel DLPFC Group-Level Analysis
# =============================================================================
# Array task 1: DLPFC_R
# Array task 2: DLPFC_Bilateral
#
# Usage: sbatch script/hpc_group_analysis_dlpfc_parallel.sh
# =============================================================================

set -e

# Map array index to seed name
case $SLURM_ARRAY_TASK_ID in
    1)
        SEED="dlpfc_r"
        SEED_DISPLAY="DLPFC_R"
        ;;
    2)
        SEED="dlpfc_bilateral"
        SEED_DISPLAY="DLPFC_Bilateral"
        ;;
    *)
        echo "ERROR: Unknown array task ID: $SLURM_ARRAY_TASK_ID"
        exit 1
        ;;
esac

echo "================================================================"
echo "Group-Level Analysis: $SEED_DISPLAY"
echo "================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Array Task ID: $SLURM_ARRAY_TASK_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: $SLURM_MEM_PER_NODE"
echo "Start time: $(date)"
echo ""

# Paths
PROJECT_DIR="/home/clivewong/proj/long"
SCRIPT_DIR="$PROJECT_DIR/script"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"
OUTPUT_DIR="$DERIVATIVE_ROOT/group-level/seed_based/$SEED"

# Create output directory
mkdir -p "$OUTPUT_DIR"
mkdir -p "$PROJECT_DIR/logs"

# Activate conda environment
echo "Activating conda environment..."
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# Verify Python and nilearn
echo "Python: $(which python)"
python -c "import nilearn; print(f'nilearn: {nilearn.__version__}')"
echo ""

# Metadata file
METADATA_FILE="$DERIVATIVE_ROOT/participants_all24_final.csv"
if [ ! -f "$METADATA_FILE" ]; then
    echo "ERROR: Metadata file not found: $METADATA_FILE"
    exit 1
fi
echo "Metadata file: $METADATA_FILE"
echo "Metadata preview:"
head -3 "$METADATA_FILE"
echo ""

# Count z-maps
INPUT_DIR="$SEED_DIR/$SEED"
N_MAPS=$(find "$INPUT_DIR" -name '*_zmap.nii.gz' 2>/dev/null | wc -l)
echo "Input directory: $INPUT_DIR"
echo "Found $N_MAPS z-maps for $SEED_DISPLAY"

if [ "$N_MAPS" -eq 0 ]; then
    echo "ERROR: No z-maps found in $INPUT_DIR"
    exit 1
fi

# List a few input files
echo "Sample input files:"
ls "$INPUT_DIR"/*_zmap.nii.gz 2>/dev/null | head -3
echo ""

# Run group analysis (0 permutations for parametric stats only)
echo "================================================================"
echo "Running group-level analysis (parametric stats only)..."
echo "================================================================"
echo ""

python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps $INPUT_DIR/*_zmap.nii.gz \
    --metadata "$METADATA_FILE" \
    --output "$OUTPUT_DIR" \
    --cluster-threshold 0.05 \
    --n-permutations 0

echo ""
echo "================================================================"
echo "$SEED_DISPLAY Analysis Complete"
echo "================================================================"
echo "End time: $(date)"
echo "Output directory: $OUTPUT_DIR"
echo ""

# Summary of outputs
echo "Output files:"
ls -lh "$OUTPUT_DIR"/ 2>/dev/null || echo "(No files found)"
echo ""

# Check for key outputs
if [ -f "$OUTPUT_DIR/interaction_tstat_map.nii.gz" ]; then
    echo "✓ Interaction t-stat map created"
else
    echo "✗ Missing: interaction_tstat_map.nii.gz"
fi

if [ -f "$OUTPUT_DIR/interaction_pval_map.nii.gz" ]; then
    echo "✓ Interaction p-value map created"
else
    echo "✗ Missing: interaction_pval_map.nii.gz"
fi

if [ -f "$OUTPUT_DIR/clusters_interaction.csv" ]; then
    n_clusters=$(tail -n +2 "$OUTPUT_DIR/clusters_interaction.csv" 2>/dev/null | wc -l)
    echo "✓ Cluster table created ($n_clusters clusters)"
else
    echo "✗ Missing: clusters_interaction.csv"
fi

n_png=$(ls "$OUTPUT_DIR"/*.png 2>/dev/null | wc -l)
echo "✓ Visualizations: $n_png PNG files"

echo ""
echo "Done!"
