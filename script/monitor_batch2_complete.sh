#!/bin/bash
# Monitor all batch 2 jobs (2841 tasks 2-4 + job 2845)

REMOTE_HOST="clivewong@hpclogin1.eduhk.hk"

echo "Monitoring Batch 2 fMRIPrep jobs"
echo "================================"
echo "Job 2841: sub-062, 063, 064 (tasks 2-4)"
echo "Job 2845: sub-056"
echo "Started: $(date)"
echo ""

while true; do
    # Check both jobs
    STATUS_2841=$(ssh ${REMOTE_HOST} "squeue -j 2841 -h 2>/dev/null | wc -l")
    STATUS_2845=$(ssh ${REMOTE_HOST} "squeue -j 2845 -h 2>/dev/null | wc -l")

    TOTAL_RUNNING=$((STATUS_2841 + STATUS_2845))

    if [ "$TOTAL_RUNNING" -eq 0 ]; then
        echo "All batch 2 jobs completed at $(date)"
        echo "Downloading results..."
        cd /home/clivewong/proj/longevity

        # Download all batch 2 subjects
        for sub in 056 062 063 064; do
            echo "Downloading sub-${sub}..."
            rsync -avz --progress --exclude='*_space-fsnative_*' \
                "${REMOTE_HOST}:/home/clivewong/proj/long/fmriprep/sub-${sub}/" \
                "fmriprep/sub-${sub}/"

            rsync -avz "${REMOTE_HOST}:/home/clivewong/proj/long/fmriprep/sub-${sub}.html" \
                "fmriprep/" 2>/dev/null || true
        done

        echo ""
        echo "✅ All 24 subjects complete!"
        echo "Total: 24 subjects × 2 sessions = 48 scanning sessions"
        break
    fi

    sleep 300  # Check every 5 minutes
done
