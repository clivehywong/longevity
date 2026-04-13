#!/bin/bash
#
# Run Seed-Based Connectivity Analysis on HPC
# This script uploads necessary files, submits the job, monitors progress, and downloads results
#

set -e

HPC_HOST="clivewong@hpclogin1.eduhk.hk"
HPC_PROJECT="/home/clivewong/proj/long"
LOCAL_PROJECT="/home/clivewong/proj/longevity"

echo "================================================================"
echo "HPC Seed-Based Connectivity Workflow"
echo "================================================================"
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

rsync -avz --progress \
    "$LOCAL_PROJECT/atlases/difumo256_4D.nii" \
    "$HPC_HOST:$HPC_PROJECT/atlases/" || echo "  (skipping difumo256_4D.nii if already on HPC)"

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
echo "  Monitor with: ssh $HPC_HOST squeue -u clivewong"
echo "  View output: ssh $HPC_HOST tail -f $HPC_PROJECT/logs/seed_connectivity_${JOB_ID}.out"
echo ""

# Step 3: Monitor job status
echo "Step 3: Monitoring job status..."
echo "----------------------------------------------------------------"
echo "  Job ID: $JOB_ID"
echo ""

while true; do
    # Check job status
    STATUS=$(ssh "$HPC_HOST" "squeue -j $JOB_ID -h -o %T 2>/dev/null" || echo "COMPLETED")

    if [ -z "$STATUS" ] || [ "$STATUS" == "COMPLETED" ]; then
        echo "  Job completed!"
        break
    else
        echo "  Job status: $STATUS ($(date +%H:%M:%S))"
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
echo "Log files: $LOCAL_PROJECT/logs/seed_connectivity_${JOB_ID}.*"
echo "Results: $LOCAL_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based/"
echo ""

# Count results
echo "Results summary:"
for dir in "$LOCAL_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based"/*/; do
    if [ -d "$dir" ]; then
        name=$(basename "$dir")
        count=$(find "$dir" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
        echo "  $name: $count z-maps"
    fi
done

echo ""
echo "Total z-maps: $(find "$LOCAL_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based" -name '*_zmap.nii.gz' 2>/dev/null | wc -l)"
echo ""
echo "Next steps:"
echo "  1. View log: cat logs/seed_connectivity_${JOB_ID}.out"
echo "  2. Run group-level analysis: bash script/continue_from_step3_parallel.sh (skip to step 6)"
echo "  3. Generate HTML report"
