#!/bin/bash
#
# Test Script: Local Measures (fALFF, ReHo)
# Test with a single subject to verify implementation
#

set -e

PROJECT_DIR="/home/clivewong/proj/longevity"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
TEST_OUTPUT="$PROJECT_DIR/test_output/local_measures"

echo "================================================================================"
echo "TEST: Local Measures (fALFF, ReHo)"
echo "================================================================================"
echo ""
echo "Testing with sub-033..."
echo ""

mkdir -p "$TEST_OUTPUT"

python "$PROJECT_DIR/script/compute_local_measures.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --output "$TEST_OUTPUT" \
    --measures fALFF ReHo \
    --subjects sub-033 \
    --sessions ses-01 \
    --tr 0.8 \
    --low-freq 0.01 \
    --high-freq 0.1 \
    --neighborhood faces_edges_corners

echo ""
echo "Test complete! Check output at: $TEST_OUTPUT"
echo ""
echo "Expected files:"
echo "  - sub-033_ses-01_fALFF.nii.gz"
echo "  - sub-033_ses-01_ReHo.nii.gz"
echo "  - local_measures_summary.csv"
echo ""

# List generated files
ls -lh "$TEST_OUTPUT"/

echo ""
echo "To view fALFF map:"
echo "  fsleyes $TEST_OUTPUT/sub-033_ses-01_fALFF.nii.gz"
echo ""
echo "To view ReHo map:"
echo "  fsleyes $TEST_OUTPUT/sub-033_ses-01_ReHo.nii.gz"
