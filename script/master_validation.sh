#!/bin/bash
#
# Master BIDS Validation Workflow
#
# Runs all validation checks in sequence and generates comprehensive reports.
# Use this before running fMRIPrep to catch data quality issues early.
#
# Usage:
#     bash script/master_validation.sh [bids_dir] [output_dir]
#
# Example:
#     bash script/master_validation.sh bids/ validation_reports/
#

# Note: We don't use 'set -e' because validation scripts return non-zero when issues are found
# This is expected behavior, not an error

# Default paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIDS_DIR="${1:-/home/clivewong/proj/longevity/bids}"
OUTPUT_DIR="${2:-/home/clivewong/proj/longevity/validation_reports}"

# Colors for output (if terminal supports it)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    BLUE='\033[0;34m'
    NC='\033[0m' # No Color
else
    RED=''
    GREEN=''
    YELLOW=''
    BLUE=''
    NC=''
fi

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}    BIDS VALIDATION WORKFLOW${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo "BIDS directory: $BIDS_DIR"
echo "Output directory: $OUTPUT_DIR"
echo ""

# Check if BIDS directory exists
if [ ! -d "$BIDS_DIR" ]; then
    echo -e "${RED}Error: BIDS directory not found: $BIDS_DIR${NC}"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"
mkdir -p "$OUTPUT_DIR/quality_metrics"

# Track errors
ERRORS=0

# Function to run a step
run_step() {
    local step_num=$1
    local step_name=$2
    local cmd=$3
    local output_file=$4

    echo ""
    echo -e "${BLUE}===== STEP $step_num: $step_name =====${NC}"

    if eval "$cmd" > "$output_file" 2>&1; then
        echo -e "${GREEN}  Completed successfully${NC}"
    else
        echo -e "${YELLOW}  Completed with warnings/errors${NC}"
        ERRORS=$((ERRORS + 1))
    fi

    echo "  Output: $output_file"
}

# Step 1: BIDS Naming Validation
echo ""
echo -e "${BLUE}===== STEP 1: BIDS Naming Validation =====${NC}"
python "$SCRIPT_DIR/validate_bids_names.py" "$BIDS_DIR" --json \
    > "$OUTPUT_DIR/naming_validation.json" 2>&1 || ERRORS=$((ERRORS + 1))

# Check for errors in JSON output
if grep -q '"error_count": 0' "$OUTPUT_DIR/naming_validation.json" 2>/dev/null; then
    echo -e "${GREEN}  No naming errors found${NC}"
else
    echo -e "${YELLOW}  Naming issues detected - see naming_validation.json${NC}"
fi
echo "  Output: $OUTPUT_DIR/naming_validation.json"

# Also run human-readable output
python "$SCRIPT_DIR/validate_bids_names.py" "$BIDS_DIR" \
    > "$OUTPUT_DIR/naming_validation.txt" 2>&1

# Step 2: NIfTI Integrity Check
echo ""
echo -e "${BLUE}===== STEP 2: NIfTI Integrity Check =====${NC}"

# Change to output directory so log files are created there
pushd "$OUTPUT_DIR" > /dev/null
python "$SCRIPT_DIR/check_nifty.py" "$BIDS_DIR" --no-data-check \
    > nifti_integrity.log 2>&1 || ERRORS=$((ERRORS + 1))
popd > /dev/null

if grep -q "All NIfTI files are readable" "$OUTPUT_DIR/nifti_integrity.log" 2>/dev/null; then
    echo -e "${GREEN}  All files readable${NC}"
else
    echo -e "${YELLOW}  Issues detected - see nifti_integrity.log${NC}"
fi
echo "  Output: $OUTPUT_DIR/nifti_integrity.log"

# Step 3: Dimensional Consistency
echo ""
echo -e "${BLUE}===== STEP 3: Dimensional Consistency =====${NC}"
python "$SCRIPT_DIR/dimensional_consistency.py" \
    --bids "$BIDS_DIR" \
    --output "$OUTPUT_DIR/dimensional_consistency.csv" 2>&1 | tee "$OUTPUT_DIR/dimensional_consistency.log" || ERRORS=$((ERRORS + 1))

if [ ! -s "$OUTPUT_DIR/dimensional_consistency.csv" ] || [ "$(wc -l < "$OUTPUT_DIR/dimensional_consistency.csv")" -eq 1 ]; then
    echo -e "${GREEN}  No dimensional inconsistencies${NC}"
else
    echo -e "${YELLOW}  Inconsistencies detected - see dimensional_consistency.csv${NC}"
fi

# Step 4: Image Quality Metrics
echo ""
echo -e "${BLUE}===== STEP 4: Image Quality Metrics =====${NC}"
python "$SCRIPT_DIR/image_quality_metrics.py" \
    --bids "$BIDS_DIR" \
    --output "$OUTPUT_DIR/quality_metrics" 2>&1 | tee "$OUTPUT_DIR/quality_metrics.log" || ERRORS=$((ERRORS + 1))

if [ -f "$OUTPUT_DIR/quality_metrics/noise_flagged.json" ]; then
    echo -e "${YELLOW}  Noise-flagged images detected - see quality_metrics/noise_flagged.json${NC}"
else
    echo -e "${GREEN}  No noise-only images detected${NC}"
fi

# Step 5: Noise Detection
echo ""
echo -e "${BLUE}===== STEP 5: Noise Detection =====${NC}"
python "$SCRIPT_DIR/noise_detection.py" \
    --bids "$BIDS_DIR" \
    --output "$OUTPUT_DIR/noise_detection.csv" 2>&1 | tee "$OUTPUT_DIR/noise_detection.log" || ERRORS=$((ERRORS + 1))

# Count noise-flagged in CSV (skip header)
if [ -f "$OUTPUT_DIR/noise_detection.csv" ]; then
    NOISE_COUNT=$(grep -c "True" "$OUTPUT_DIR/noise_detection.csv" 2>/dev/null || echo "0")
    if [ "$NOISE_COUNT" -gt 0 ]; then
        echo -e "${YELLOW}  $NOISE_COUNT noise-flagged images detected${NC}"
    else
        echo -e "${GREEN}  No noise-only images detected${NC}"
    fi
fi

# Step 6: Visual QA (Optional - check if script exists)
echo ""
echo -e "${BLUE}===== STEP 6: Visual QA (Optional) =====${NC}"
if [ -f "$SCRIPT_DIR/qa_check_images.py" ]; then
    mkdir -p "$OUTPUT_DIR/visual_qa"
    python "$SCRIPT_DIR/qa_check_images.py" \
        --bids-dir "$BIDS_DIR" \
        --output "$OUTPUT_DIR/visual_qa" 2>&1 | tee "$OUTPUT_DIR/visual_qa.log" || true
    echo "  Output: $OUTPUT_DIR/visual_qa/"
else
    echo -e "${YELLOW}  Skipped - qa_check_images.py not found${NC}"
fi

# Final Summary
echo ""
echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}    VALIDATION COMPLETE${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo "Reports directory: $OUTPUT_DIR"
echo ""
echo "Generated reports:"
ls -la "$OUTPUT_DIR"/*.{json,csv,log,txt} 2>/dev/null | awk '{print "  " $NF}'
echo ""

# Quick summary of issues
echo -e "${BLUE}Quick Issue Summary:${NC}"

# Naming errors
if [ -f "$OUTPUT_DIR/naming_validation.json" ]; then
    ERROR_COUNT=$(grep -o '"error_count": [0-9]*' "$OUTPUT_DIR/naming_validation.json" | grep -o '[0-9]*' || echo "?")
    echo "  Naming errors: $ERROR_COUNT"
fi

# Dimensional issues
if [ -f "$OUTPUT_DIR/dimensional_consistency.csv" ]; then
    DIM_COUNT=$(($(wc -l < "$OUTPUT_DIR/dimensional_consistency.csv") - 1))
    [ "$DIM_COUNT" -lt 0 ] && DIM_COUNT=0
    echo "  Dimensional inconsistencies: $DIM_COUNT"
fi

# Noise-flagged
if [ -f "$OUTPUT_DIR/noise_detection.csv" ]; then
    NOISE_COUNT=$(grep -c "True" "$OUTPUT_DIR/noise_detection.csv" 2>/dev/null || echo "0")
    echo "  Noise-flagged images: $NOISE_COUNT"
fi

echo ""

if [ $ERRORS -gt 0 ]; then
    echo -e "${YELLOW}Warning: Some validation steps reported issues.${NC}"
    echo "Review the reports before proceeding with fMRIPrep."
    exit 1
else
    echo -e "${GREEN}All validation steps completed successfully.${NC}"
    exit 0
fi
