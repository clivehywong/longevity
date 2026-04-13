#!/bin/bash
# Monitor batch 2 job 2837 and auto-download when complete

REMOTE_HOST="clivewong@hpclogin1.eduhk.hk"
JOB_ID="2837"

echo "Monitoring batch 2 job ${JOB_ID}..."
echo "Will auto-download when complete."

while true; do
    STATUS=$(ssh ${REMOTE_HOST} "squeue -j ${JOB_ID} -h 2>/dev/null | wc -l")

    if [ "$STATUS" -eq 0 ]; then
        echo "Job ${JOB_ID} completed at $(date)"
        echo "Downloading results..."
        bash script/batch_fmriprep.sh download 2
        echo "Download complete!"
        break
    fi

    sleep 300  # Check every 5 minutes
done
