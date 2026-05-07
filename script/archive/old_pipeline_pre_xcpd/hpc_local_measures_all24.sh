#!/bin/bash
#SBATCH --job-name=local_meas
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=logs/local_measures_%j.out
#SBATCH --error=logs/local_measures_%j.err

# =============================================================================
# HPC SLURM Script: Local Measures (fALFF, ReHo) for All 24 Subjects
# =============================================================================
# Computes voxelwise local measures from fMRIPrep preprocessed BOLD data
# for all 24 longitudinal subjects (48 sessions total)
#
# Processing time: ~9 min per subject for ReHo, ~30 sec for fALFF
# Total estimate: ~4-5 hours for all 24 subjects
# =============================================================================

set -e

echo "================================================================"
echo "Local Measures Analysis (fALFF, ReHo) - HPC"
echo "================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: 32GB"
echo "Start time: $(date)"
echo ""

# Paths on HPC
PROJECT_DIR="/home/clivewong/proj/long"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
SCRIPT_DIR="$PROJECT_DIR/script"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
OUTPUT_DIR="$DERIVATIVE_ROOT/subject-level/local_measures"

mkdir -p "$OUTPUT_DIR"
mkdir -p logs

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# All 24 longitudinal subjects
ALL_SUBJECTS=(
    sub-033 sub-034 sub-035 sub-036 sub-037 sub-038 sub-039 sub-040
    sub-043 sub-045 sub-046 sub-047 sub-048 sub-052 sub-055 sub-056
    sub-057 sub-058 sub-059 sub-060 sub-061 sub-062 sub-063 sub-064
)

echo "Processing ${#ALL_SUBJECTS[@]} subjects..."
echo "Subjects: ${ALL_SUBJECTS[*]}"
echo ""

# Run local measures computation
python "$SCRIPT_DIR/compute_local_measures.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --output "$OUTPUT_DIR" \
    --measures fALFF ReHo \
    --tr 0.8 \
    --low-freq 0.01 \
    --high-freq 0.1

echo ""
echo "================================================================"
echo "Local Measures Analysis Complete"
echo "================================================================"
echo "End time: $(date)"
echo "Output: $OUTPUT_DIR"
echo ""

# Count results
echo "Results summary:"
fALFF_count=$(find "$OUTPUT_DIR" -name "*_fALFF.nii.gz" 2>/dev/null | wc -l)
ReHo_count=$(find "$OUTPUT_DIR" -name "*_ReHo.nii.gz" 2>/dev/null | wc -l)
echo "  fALFF maps: $fALFF_count"
echo "  ReHo maps: $ReHo_count"

# Verify expected counts
expected=48  # 24 subjects × 2 sessions
if [ "$fALFF_count" -eq "$expected" ] && [ "$ReHo_count" -eq "$expected" ]; then
    echo ""
    echo "SUCCESS: All $expected expected maps generated for each measure."
else
    echo ""
    echo "WARNING: Expected $expected maps per measure, but found fALFF=$fALFF_count, ReHo=$ReHo_count"
    echo "Some subjects may be missing."
fi
