#!/bin/bash
# Extract ROI timeseries from fMRIPrep outputs for all atlases
#
# This script calls extract_timeseries.py for DiFuMo 256, Schaefer 400, and Schaefer 200 atlases.
# Outputs are saved as TSV files with QC metrics.
#
# Usage:
#   bash extract_timeseries_linux.sh [FMRIPREP_DIR] [OUTPUT_BASE]
#
# Example:
#   bash extract_timeseries_linux.sh fmriprep timeseries

set -e

# Configuration
FMRIPREP_DIR="${1:-/home/clivewong/proj/longevity/fmriprep}"
OUTPUT_BASE="${2:-/home/clivewong/proj/longevity/timeseries}"
SCRIPT_DIR="/home/clivewong/proj/longevity/script"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"; }

# Check if fMRIPrep directory exists
if [ ! -d "$FMRIPREP_DIR" ]; then
    echo "ERROR: fMRIPrep directory not found: $FMRIPREP_DIR"
    exit 1
fi

# Create output base directory
mkdir -p "${OUTPUT_BASE}/logs"

log "Extracting timeseries from fMRIPrep outputs"
log "fMRIPrep directory: $FMRIPREP_DIR"
log "Output base: $OUTPUT_BASE"

# Count BOLD files
n_bold=$(find "$FMRIPREP_DIR" -name "*_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz" | wc -l)
log "Found $n_bold preprocessed BOLD files"

if [ "$n_bold" -eq 0 ]; then
    warn "No BOLD files found. Has fMRIPrep completed?"
    exit 1
fi

# Atlas 1: DiFuMo 256 (PRIMARY - includes cerebellum)
log ""
log "=========================================="
log "Atlas 1/3: DiFuMo 256 (whole brain)"
log "=========================================="

python3 "${SCRIPT_DIR}/extract_timeseries.py" \
    "$FMRIPREP_DIR" \
    "${OUTPUT_BASE}/difumo256" \
    --atlas difumo_256 \
    --space MNI152NLin2009cAsym \
    --smoothing 6.0 \
    --high-pass 0.01 \
    --low-pass 0.1 \
    --confounds minimal \
    > "${OUTPUT_BASE}/logs/difumo256.log" 2>&1

if [ $? -eq 0 ]; then
    log "✓ DiFuMo 256 extraction complete"
else
    warn "DiFuMo 256 extraction failed (see ${OUTPUT_BASE}/logs/difumo256.log)"
fi

# Atlas 2: Schaefer 400 (7 Networks, cortical validation)
log ""
log "=========================================="
log "Atlas 2/3: Schaefer 400 (7 Networks)"
log "=========================================="

python3 "${SCRIPT_DIR}/extract_timeseries.py" \
    "$FMRIPREP_DIR" \
    "${OUTPUT_BASE}/schaefer400_7net" \
    --atlas schaefer_400_7 \
    --space MNI152NLin2009cAsym \
    --smoothing 6.0 \
    --high-pass 0.01 \
    --low-pass 0.1 \
    --confounds minimal \
    > "${OUTPUT_BASE}/logs/schaefer400_7net.log" 2>&1

if [ $? -eq 0 ]; then
    log "✓ Schaefer 400 extraction complete"
else
    warn "Schaefer 400 extraction failed (see ${OUTPUT_BASE}/logs/schaefer400_7net.log)"
fi

# Atlas 3: Schaefer 200 (7 Networks, lower dimension)
log ""
log "=========================================="
log "Atlas 3/3: Schaefer 200 (7 Networks)"
log "=========================================="

python3 "${SCRIPT_DIR}/extract_timeseries.py" \
    "$FMRIPREP_DIR" \
    "${OUTPUT_BASE}/schaefer200_7net" \
    --atlas schaefer_200_7 \
    --space MNI152NLin2009cAsym \
    --smoothing 6.0 \
    --high-pass 0.01 \
    --low-pass 0.1 \
    --confounds minimal \
    > "${OUTPUT_BASE}/logs/schaefer200_7net.log" 2>&1

if [ $? -eq 0 ]; then
    log "✓ Schaefer 200 extraction complete"
else
    warn "Schaefer 200 extraction failed (see ${OUTPUT_BASE}/logs/schaefer200_7net.log)"
fi

# Summary
log ""
log "=========================================="
log "EXTRACTION SUMMARY"
log "=========================================="

for atlas in difumo256 schaefer400_7net schaefer200_7net; do
    n_files=$(find "${OUTPUT_BASE}/${atlas}" -name "*_timeseries.tsv" 2>/dev/null | wc -l)
    log "${atlas}: ${n_files} timeseries files"

    # Show QC summary if available
    if [ -f "${OUTPUT_BASE}/${atlas}/qc_summary.tsv" ]; then
        log "  QC summary: ${OUTPUT_BASE}/${atlas}/qc_summary.tsv"
    fi
done

log ""
log "All timeseries extracted!"
log "Next step: Convert to HDF5 format for connectivity analysis"
log ""
log "Example:"
log "  python script/convert_tsv_to_hdf5.py \\"
log "    --timeseries-dir timeseries/difumo256 \\"
log "    --output results/timeseries_difumo256.h5 \\"
log "    --atlas difumo256 \\"
log "    --verify"
