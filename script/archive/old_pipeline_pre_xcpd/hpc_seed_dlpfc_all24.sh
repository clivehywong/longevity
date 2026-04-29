#!/bin/bash
#SBATCH --job-name=dlpfc_all24
#SBATCH --cpus-per-task=15
#SBATCH --mem=64G
#SBATCH --time=4:00:00
#SBATCH --output=logs/dlpfc_all24_%j.out
#SBATCH --error=logs/dlpfc_all24_%j.err

# Process DLPFC seeds for ALL 24 subjects (48 sessions)
# Seeds: DLPFC_L, DLPFC_R, DLPFC_Bilateral (revised 2026-02-13)

set -e

echo "================================================================"
echo "DLPFC Seeds - ALL 24 Subjects (48 sessions)"
echo "================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: 8"
echo "Memory: 64GB"
echo "Start time: $(date)"
echo ""

# Paths on HPC
PROJECT_DIR="/home/clivewong/proj/long"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
SCRIPT_DIR="$PROJECT_DIR/script"
ATLASES_DIR="$PROJECT_DIR/atlases"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
METADATA_FILE="$DERIVATIVE_ROOT/participants.tsv"
SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"

mkdir -p "$SEED_DIR"

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# Count available subjects
n_bold=$(find "$FMRIPREP_DIR" -name '*task-rest_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz' | wc -l)
n_subjects=$(find "$FMRIPREP_DIR" -name '*task-rest_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz' | sed 's/.*sub-\([0-9]*\).*/\1/' | sort -u | wc -l)

echo "Found $n_bold BOLD files from $n_subjects subjects"
echo ""

echo "Processing 3 DLPFC seeds (revised lateralized definitions)..."
echo "Seeds: DLPFC_L, DLPFC_R, DLPFC_Bilateral"
echo "Workers: 3 (one per seed)"
echo "Expected output: 144 z-maps (3 seeds × 48 sessions)"
echo ""

python "$SCRIPT_DIR/seed_based_connectivity_parallel.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$ATLASES_DIR/motor_cerebellar_seeds.json" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --seed-names DLPFC_L DLPFC_R DLPFC_Bilateral \
    --fd-threshold 0.5 \
    --n-jobs 3 \
    --backend loky \
    --verbose 10

echo ""
echo "================================================================"
echo "DLPFC Processing Complete"
echo "================================================================"
echo "End time: $(date)"
echo "Output: $SEED_DIR"
echo ""

# Count results
echo "Results summary:"
for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    dir="$SEED_DIR/$seed"
    if [ -d "$dir" ]; then
        count=$(find "$dir" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
        echo "  $seed: $count z-maps"
    fi
done

echo ""
echo "Total DLPFC z-maps: $(find "$SEED_DIR"/dlpfc_* -name '*_zmap.nii.gz' 2>/dev/null | wc -l)"
echo "Expected: 144 (3 seeds × 48 sessions)"
echo ""
echo "Ready for group-level analysis with full 24-subject dataset!"
