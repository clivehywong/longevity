#!/bin/bash
# Simple monitoring script for fMRIPrep job 2816

REMOTE_HOST="clivewong@hpclogin1.eduhk.hk"
JOB_ID="2816"

echo "Monitoring fMRIPrep job ${JOB_ID}"
echo "Press Ctrl+C to stop monitoring (job will continue running)"
echo ""

while true; do
    clear
    echo "=========================================="
    echo "fMRIPrep Job Status - $(date '+%Y-%m-%d %H:%M:%S')"
    echo "=========================================="
    echo ""

    # Check job status
    STATUS=$(ssh ${REMOTE_HOST} "squeue -j ${JOB_ID} -h 2>/dev/null")

    if [ -z "$STATUS" ]; then
        echo "✅ Job ${JOB_ID} has completed!"
        echo ""
        echo "Next steps:"
        echo "  1. Download results: bash script/batch_fmriprep.sh download 1"
        echo "  2. Start batch 2: bash script/batch_fmriprep.sh 2"
        break
    else
        echo "$STATUS" | awk '{printf "%-15s %-15s %-10s %s\n", $1, $3, $5, $6}'
        echo ""

        # Count running vs pending
        RUNNING=$(echo "$STATUS" | grep " R " | wc -l)
        PENDING=$(echo "$STATUS" | grep " PD " | wc -l)
        echo "Running: ${RUNNING} | Pending: ${PENDING}"
        echo ""
        echo "Checking again in 5 minutes..."
    fi

    sleep 300  # Check every 5 minutes
done
