#!/bin/bash
#
# Complete HPC Setup and Run Workflow for Seed-Based Connectivity
# This script:
#   1. Uploads scripts and data to HPC
#   2. Installs Python dependencies (first time only)
#   3. Submits SLURM job
#   4. Monitors progress
#   5. Downloads results
#

set -e

HPC_HOST="clivewong@hpclogin1.eduhk.hk"
HPC_PROJECT="/home/clivewong/proj/long"
LOCAL_PROJECT="/home/clivewong/proj/longevity"

echo "================================================================"
echo "HPC Seed-Based Connectivity - Complete Workflow"
echo "================================================================"
echo ""

# Step 0: Check if dependencies are installed
echo "Step 0: Checking Python environment on HPC..."
echo "----------------------------------------------------------------"

DEP_CHECK=$(ssh "$HPC_HOST" "
    if [ -f \$HOME/venv/connectivity/bin/activate ]; then
        source \$HOME/venv/connectivity/bin/activate
        python -c 'import nilearn, nibabel, pandas, joblib' 2>/dev/null && echo 'OK' || echo 'MISSING'
    else
        echo 'NO_VENV'
    fi
")

if [ "$DEP_CHECK" == "NO_VENV" ] || [ "$DEP_CHECK" == "MISSING" ]; then
    echo "  Dependencies not installed. Installing..."

    # Upload install script
    rsync -avz "$LOCAL_PROJECT/script/hpc_install_deps.sh" "$HPC_HOST:$HPC_PROJECT/script/"

    # Run installation
    ssh "$HPC_HOST" "cd $HPC_PROJECT && bash script/hpc_install_deps.sh"

    echo "  Installation complete!"
else
    echo "  Dependencies already installed."
fi

echo ""

# Step 1: Upload necessary files to HPC
echo "Step 1: Uploading files to HPC..."
echo "----------------------------------------------------------------"

# Create directories on HPC
ssh "$HPC_HOST" "mkdir -p $HPC_PROJECT/script $HPC_PROJECT/atlases $HPC_PROJECT/derivatives/connectivity-difumo256 $HPC_PROJECT/logs"

# Upload Python script
echo "  Uploading seed_based_connectivity_parallel.py..."
rsync -avz --progress \
    "$LOCAL_PROJECT/script/seed_based_connectivity_parallel.py" \
    "$HPC_HOST:$HPC_PROJECT/script/"

# Upload SLURM script
echo "  Uploading SLURM job script..."
rsync -avz --progress \
    "$LOCAL_PROJECT/script/hpc_seed_connectivity.sh" \
    "$HPC_HOST:$HPC_PROJECT/script/"

# Upload atlases
echo "  Uploading atlases..."
rsync -avz --progress \
    "$LOCAL_PROJECT/atlases/motor_cerebellar_seeds.json" \
    "$HPC_HOST:$HPC_PROJECT/atlases/"

# Upload metadata
echo "  Uploading metadata..."
rsync -avz --progress \
    "$LOCAL_PROJECT/derivatives/connectivity-difumo256/participants.tsv" \
    "$HPC_HOST:$HPC_PROJECT/derivatives/connectivity-difumo256/"

echo "  Upload complete!"
echo ""

# Step 2: Submit SLURM job
echo "Step 2: Submitting SLURM job..."
echo "----------------------------------------------------------------"

JOB_ID=$(ssh "$HPC_HOST" "cd $HPC_PROJECT && sbatch script/hpc_seed_connectivity.sh" | grep -oP '\d+')

echo "  Job submitted: $JOB_ID"
echo "  Node allocation: 16 CPUs, 64GB RAM"
echo "  Estimated runtime: 2-4 hours (vs 40+ hours locally)"
echo ""
echo "  Monitor commands:"
echo "    Status: ssh $HPC_HOST squeue -u clivewong"
echo "    Output: ssh $HPC_HOST tail -f $HPC_PROJECT/logs/seed_connectivity_${JOB_ID}.out"
echo "    Error:  ssh $HPC_HOST tail -f $HPC_PROJECT/logs/seed_connectivity_${JOB_ID}.err"
echo ""

# Step 3: Monitor job status
echo "Step 3: Monitoring job status..."
echo "----------------------------------------------------------------"
echo "  Checking every 60 seconds..."
echo ""

while true; do
    # Check job status
    STATUS=$(ssh "$HPC_HOST" "squeue -j $JOB_ID -h -o '%T' 2>/dev/null" || echo "")

    if [ -z "$STATUS" ]; then
        echo "  Job completed or not found. Checking logs..."

        # Check exit code from log
        EXIT_CODE=$(ssh "$HPC_HOST" "tail -20 $HPC_PROJECT/logs/seed_connectivity_${JOB_ID}.err 2>/dev/null | grep -oP 'Exit code: \K\d+' || echo '0'")

        if [ "$EXIT_CODE" == "0" ]; then
            echo "  Job completed successfully!"
        else
            echo "  Job failed with exit code: $EXIT_CODE"
            echo "  Check error log: ssh $HPC_HOST cat $HPC_PROJECT/logs/seed_connectivity_${JOB_ID}.err"
        fi
        break
    else
        TIMESTAMP=$(date +%H:%M:%S)
        echo "  [$TIMESTAMP] Job status: $STATUS"

        # Show brief progress if available
        PROGRESS=$(ssh "$HPC_HOST" "tail -5 $HPC_PROJECT/logs/seed_connectivity_${JOB_ID}.out 2>/dev/null | grep -E 'Processed|maps for|Done' | tail -1" || echo "")
        if [ -n "$PROGRESS" ]; then
            echo "    Latest: $PROGRESS"
        fi

        sleep 60
    fi
done

echo ""

# Step 4: Download results
echo "Step 4: Downloading results..."
echo "----------------------------------------------------------------"

# Download z-maps
echo "  Downloading z-maps..."
rsync -avz --progress \
    "$HPC_HOST:$HPC_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based/" \
    "$LOCAL_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based/"

# Download log files
echo "  Downloading log files..."
mkdir -p "$LOCAL_PROJECT/logs"
rsync -avz --progress \
    "$HPC_HOST:$HPC_PROJECT/logs/seed_connectivity_${JOB_ID}.*" \
    "$LOCAL_PROJECT/logs/"

echo "  Download complete!"
echo ""

# Step 5: Summary
echo "================================================================"
echo "HPC Workflow Complete!"
echo "================================================================"
echo ""
echo "Job ID: $JOB_ID"
echo "Log files:"
echo "  Output: $LOCAL_PROJECT/logs/seed_connectivity_${JOB_ID}.out"
echo "  Error:  $LOCAL_PROJECT/logs/seed_connectivity_${JOB_ID}.err"
echo ""
echo "Results: $LOCAL_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based/"
echo ""

# Count results
echo "Results summary:"
for dir in "$LOCAL_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based"/*/; do
    if [ -d "$dir" ]; then
        name=$(basename "$dir")
        count=$(find "$dir" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
        printf "  %-25s %s z-maps\n" "$name:" "$count"
    fi
done

echo ""
TOTAL=$(find "$LOCAL_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based" -name '*_zmap.nii.gz' 2>/dev/null | wc -l)
echo "Total z-maps: $TOTAL"
echo "Expected: ~540 (12 seeds × 45 sessions)"
echo ""

if [ "$TOTAL" -ge 500 ]; then
    echo "✓ Analysis appears complete!"
    echo ""
    echo "Next steps:"
    echo "  1. Review log: cat logs/seed_connectivity_${JOB_ID}.out"
    echo "  2. Run group-level analysis"
    echo "  3. Generate HTML report"
else
    echo "⚠ Some z-maps may be missing. Check logs for errors."
fi
