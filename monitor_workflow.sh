#!/bin/bash
#
# Monitor the running workflow progress
#

OUTPUT_FILE="/tmp/claude-1002/-home-clivewong-proj-longevity/tasks/bfcfbd1.output"

if [[ ! -f "$OUTPUT_FILE" ]]; then
    echo "Workflow output file not found. Workflow may have completed or not started."
    exit 1
fi

echo "================================================================================"
echo "WORKFLOW PROGRESS MONITOR"
echo "================================================================================"
echo ""
echo "Last 30 lines of output:"
echo "--------------------------------------------------------------------------------"
tail -30 "$OUTPUT_FILE"
echo ""
echo "================================================================================"
echo "To view full output: less $OUTPUT_FILE"
echo "To follow live: tail -f $OUTPUT_FILE"
echo "================================================================================"
