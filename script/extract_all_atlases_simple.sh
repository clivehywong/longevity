#!/bin/bash
# Extract time series using multiple atlases (sequential version - no GNU parallel required)

set -e

FMRIPREP_DIR="${1:-/Volumes/Work/Work/long/fmriprep}"
OUTPUT_BASE="${2:-/Volumes/Work/Work/long/timeseries}"

# Check if fMRIPrep directory exists
if [ ! -d "$FMRIPREP_DIR" ]; then
    echo "Error: fMRIPrep directory not found: $FMRIPREP_DIR"
    exit 1
fi

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN}Multi-Atlas Time Series Extraction${NC}"
echo -e "${GREEN}====================================${NC}"
echo ""
echo "Input:  $FMRIPREP_DIR"
echo "Output: $OUTPUT_BASE"
echo ""

# Create log directory
mkdir -p "${OUTPUT_BASE}/logs"

# Atlas configurations: name|output_suffix|description
ATLASES=(
    "schaefer_400_7|schaefer400_7net|Schaefer 400 ROIs, Yeo 7-networks (PRIMARY)"
    "difumo_256|difumo256|DiFuMo 256 components (data-driven)"
    "schaefer_200_7|schaefer200_7net|Schaefer 200 ROIs, Yeo 7-networks"
)

# Function to run extraction for one atlas
extract_atlas() {
    local atlas_name=$1
    local output_suffix=$2
    local description=$3
    local output_dir="${OUTPUT_BASE}/${output_suffix}"
    local log_file="${OUTPUT_BASE}/logs/${output_suffix}.log"

    echo -e "${BLUE}Processing:${NC} $description"

    python3 /Volumes/Work/Work/long/script/extract_timeseries.py \
        "$FMRIPREP_DIR" \
        "$output_dir" \
        --atlas "$atlas_name" \
        --smoothing 6 \
        --confounds minimal \
        > "$log_file" 2>&1

    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Complete:${NC} $description → $output_dir"
    else
        echo -e "\033[0;31m✗ Failed:${NC} $description (see $log_file)"
        return 1
    fi
}

# Run extractions sequentially
for atlas_line in "${ATLASES[@]}"; do
    IFS='|' read -r name suffix desc <<< "$atlas_line"
    extract_atlas "$name" "$suffix" "$desc"
    echo ""
done

echo -e "${GREEN}====================================${NC}"
echo -e "${GREEN}All extractions complete!${NC}"
echo -e "${GREEN}====================================${NC}"
echo ""
echo "Output directories:"
for atlas_line in "${ATLASES[@]}"; do
    IFS='|' read -r name suffix desc <<< "$atlas_line"
    echo "  - ${OUTPUT_BASE}/${suffix}/"
done

echo ""
echo "QC summaries:"
for atlas_line in "${ATLASES[@]}"; do
    IFS='|' read -r name suffix desc <<< "$atlas_line"
    qc_file="${OUTPUT_BASE}/${suffix}/qc_summary.tsv"
    if [ -f "$qc_file" ]; then
        n_subjects=$(tail -n +2 "$qc_file" | wc -l | tr -d ' ')
        echo "  - $suffix: $n_subjects subjects"
    fi
done
