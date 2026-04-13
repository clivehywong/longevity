#!/bin/bash
# Monitor job 2841 and auto-download batch 2 when complete

REMOTE_HOST="clivewong@hpclogin1.eduhk.hk"
JOB_ID="2841"

echo "Monitoring fMRIPrep job ${JOB_ID} (batch 2: sub-056, 062, 063, 064)"
echo "Will auto-download when complete."
echo "Started: $(date)"
echo ""

while true; do
    STATUS=$(ssh ${REMOTE_HOST} "squeue -j ${JOB_ID} -h 2>/dev/null | wc -l")

    if [ "$STATUS" -eq 0 ]; then
        echo "Job ${JOB_ID} completed at $(date)"
        echo "Downloading results..."
        cd /home/clivewong/proj/longevity
        bash script/batch_fmriprep.sh download 2
        echo "All done! All 24 subjects now complete."
        break
    fi

    sleep 300  # Check every 5 minutes
done
