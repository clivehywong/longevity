#!/bin/bash
#
# Monitor Full Analysis Progress
#

PROJECT_DIR="/home/clivewong/proj/longevity"
OUTPUT_FILE="$PROJECT_DIR/workflow_output.log"

if [[ ! -f "$OUTPUT_FILE" ]]; then
    echo "Analysis output file not found: $OUTPUT_FILE"
    echo "Workflow may have completed or not started."
    exit 1
fi

echo "================================================================================"
echo "FULL ANALYSIS PROGRESS MONITOR (DiFuMo256)"
echo "================================================================================"
echo ""
echo "Output directory: derivatives/connectivity-difumo256/"
echo "Log file: workflow_output.log"
echo ""

# Check if process is running
if pgrep -f "run_full_analysis_difumo256" > /dev/null; then
    echo "Status: ✅ RUNNING"
else
    echo "Status: ⚠️ NOT RUNNING (completed or stopped)"
fi
echo ""

# Show progress based on completed files
echo "Progress:"
echo "--------------------------------------------------------------------------------"
LOCAL_COUNT=$(ls "$PROJECT_DIR/derivatives/connectivity-difumo256/subject-level/local_measures/"*_fALFF.nii.gz 2>/dev/null | wc -l)
REHO_COUNT=$(ls "$PROJECT_DIR/derivatives/connectivity-difumo256/subject-level/local_measures/"*_ReHo.nii.gz 2>/dev/null | wc -l)
echo "  Local measures: $LOCAL_COUNT/17 fALFF, $REHO_COUNT/17 ReHo"

SEED_DIRS=$(ls -d "$PROJECT_DIR/derivatives/connectivity-difumo256/subject-level/seed_based/"*/ 2>/dev/null | wc -l)
echo "  Seed-based: $SEED_DIRS seed directories created"

if [[ -f "$PROJECT_DIR/derivatives/connectivity-difumo256/subject-level/timeseries_difumo256.h5" ]]; then
    echo "  Timeseries: ✅ Created"
else
    echo "  Timeseries: ⏳ Pending"
fi

GROUP_DIRS=$(ls -d "$PROJECT_DIR/derivatives/connectivity-difumo256/group-level/"*/ 2>/dev/null | wc -l)
echo "  Group analysis: $GROUP_DIRS result directories"

if [[ -f "$PROJECT_DIR/derivatives/reports/connectivity-difumo256_report.html" ]]; then
    echo "  HTML Report: ✅ Created"
else
    echo "  HTML Report: ⏳ Pending"
fi

echo ""
echo "Last 30 lines of output:"
echo "--------------------------------------------------------------------------------"
tail -30 "$OUTPUT_FILE"
echo ""
echo "================================================================================"
echo "Commands:"
echo "  View full output: less $OUTPUT_FILE"
echo "  Follow live: tail -f $OUTPUT_FILE"
echo "  Check process: ps aux | grep run_full_analysis"
echo "================================================================================"
