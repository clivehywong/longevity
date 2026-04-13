#!/bin/bash
#SBATCH --job-name=extract_ts
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=4:00:00
#SBATCH --output=logs/extract_ts_%j.out
#SBATCH --error=logs/extract_ts_%j.err

# =============================================================================
# HPC SLURM Script: Extract DiFuMo 256 ROI Timeseries
# =============================================================================
# Extracts ROI timeseries from fMRIPrep preprocessed BOLD data for all
# 24 longitudinal subjects (48 sessions) using the DiFuMo 256 atlas.
#
# Output: TSV files per subject/session, then converted to HDF5 format
# for network connectivity analysis.
#
# Processing time: ~1-2 minutes per subject × 24 = ~45-90 minutes
# =============================================================================

set -e

echo "================================================================"
echo "ROI Timeseries Extraction (DiFuMo 256) - HPC"
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
TIMESERIES_DIR="$DERIVATIVE_ROOT/subject-level/timeseries_tsv"
OUTPUT_HDF5="$DERIVATIVE_ROOT/subject-level/timeseries_difumo256.h5"

mkdir -p "$TIMESERIES_DIR"
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

echo "Step 1: Extracting timeseries to TSV format"
echo "Processing ${#ALL_SUBJECTS[@]} subjects..."
echo ""

# Extract timeseries for all subjects
python "$SCRIPT_DIR/extract_timeseries.py" \
    "$FMRIPREP_DIR" \
    "$TIMESERIES_DIR" \
    --atlas difumo_256 \
    --space MNI152NLin2009cAsym \
    --smoothing 6.0 \
    --high-pass 0.01 \
    --low-pass 0.1 \
    --confounds minimal \
    --subjects $(echo ${ALL_SUBJECTS[@]} | sed 's/sub-//g')

echo ""
echo "Step 2: Converting TSV to HDF5 format"
echo ""

# Convert TSV to HDF5 for efficient network connectivity analysis
python "$SCRIPT_DIR/convert_tsv_to_hdf5.py" \
    "$TIMESERIES_DIR" \
    "$OUTPUT_HDF5" \
    --atlas-name difumo256 \
    --verbose

echo ""
echo "================================================================"
echo "Timeseries Extraction Complete"
echo "================================================================"
echo "End time: $(date)"
echo ""

# Report results
tsv_count=$(find "$TIMESERIES_DIR" -name "*_timeseries.tsv" 2>/dev/null | wc -l)
echo "Results summary:"
echo "  TSV files: $tsv_count"
echo "  HDF5 file: $OUTPUT_HDF5"

if [ -f "$OUTPUT_HDF5" ]; then
    hdf5_size=$(du -h "$OUTPUT_HDF5" | cut -f1)
    echo "  HDF5 size: $hdf5_size"
    echo ""
    echo "SUCCESS: Timeseries extraction complete."
    echo "Use $OUTPUT_HDF5 for network connectivity analyses."
else
    echo ""
    echo "ERROR: HDF5 file not created successfully."
    exit 1
fi
