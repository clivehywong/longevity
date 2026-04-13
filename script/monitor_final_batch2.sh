#!/bin/bash
# Monitor final batch 2 jobs: 2841_2, 2841_4, 2846

REMOTE_HOST="clivewong@hpclogin1.eduhk.hk"

echo "Monitoring Final Batch 2 Jobs"
echo "=============================="
echo "Job 2841_2: sub-062 (running ~5 hours)"
echo "Job 2841_4: sub-064 (running ~5 hours)"
echo "Job 2846: sub-056 (just resubmitted)"
echo "Started: $(date)"
echo ""

while true; do
    # Check all three jobs
    RUNNING=$(ssh ${REMOTE_HOST} "squeue -u clivewong -j 2841_2,2841_4,2846 -h 2>/dev/null | wc -l")

    if [ "$RUNNING" -eq 0 ]; then
        echo "All jobs completed at $(date)"
        echo "Downloading all batch 2 subjects..."
        cd /home/clivewong/proj/longevity

        for sub in 056 062 063 064; do
            echo "Downloading sub-${sub}..."
            rsync -avz --progress --exclude='*_space-fsnative_*' \
                "${REMOTE_HOST}:/home/clivewong/proj/long/fmriprep/sub-${sub}/" \
                "fmriprep/sub-${sub}/" 2>/dev/null || echo "  (sub-${sub} may not exist yet)"

            rsync -avz "${REMOTE_HOST}:/home/clivewong/proj/long/fmriprep/sub-${sub}.html" \
                "fmriprep/" 2>/dev/null || true
        done

        echo ""
        echo "✅ All 24 subjects complete!"
        echo "Ready for connectivity analysis."
        break
    fi

    # Show current status
    ssh ${REMOTE_HOST} "squeue -u clivewong -o '%.10i %.15j %.2t %.10M' -h 2>/dev/null" | grep -E '2841_2|2841_4|2846' || true

    sleep 300  # Check every 5 minutes
done
