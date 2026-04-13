#!/bin/bash
#
# Upload Files to HPC for Group-Level Analysis
#
# Uploads subject-level z-maps, metadata, and scripts to HPC
#
# Usage:
#   bash script/hpc_upload_for_group_analysis.sh
#

set -e

# Configuration
HPC_USER="clivewong"
HPC_HOST="hpclogin1.eduhk.hk"
HPC_PROJECT_DIR="/home/clivewong/proj/long"

LOCAL_PROJECT_DIR="/home/clivewong/proj/longevity"

echo "================================================================"
echo "UPLOAD TO HPC FOR GROUP-LEVEL ANALYSIS"
echo "================================================================"
echo "HPC: ${HPC_USER}@${HPC_HOST}:${HPC_PROJECT_DIR}"
echo "================================================================"
echo ""

# Create remote directories
echo "Creating remote directories..."
ssh ${HPC_USER}@${HPC_HOST} "mkdir -p ${HPC_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/group-level"
ssh ${HPC_USER}@${HPC_HOST} "mkdir -p ${HPC_PROJECT_DIR}/script"
ssh ${HPC_USER}@${HPC_HOST} "mkdir -p ${HPC_PROJECT_DIR}/logs"

# Upload metadata files
echo ""
echo "Uploading metadata files..."
rsync -avz --progress \
    "${LOCAL_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/participants_updated.tsv" \
    ${HPC_USER}@${HPC_HOST}:${HPC_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/

rsync -avz --progress \
    "${LOCAL_PROJECT_DIR}/group.csv" \
    ${HPC_USER}@${HPC_HOST}:${HPC_PROJECT_DIR}/

# Upload subject-level z-maps (if not already on HPC)
echo ""
echo "Checking if subject-level z-maps need upload..."
if ssh ${HPC_USER}@${HPC_HOST} "[ ! -d ${HPC_PROJECT_DIR}/derivatives/connectivity-difumo256/subject-level/seed_based ]"; then
    echo "Subject-level z-maps not found on HPC. Uploading..."

    # Upload all seed directories
    rsync -avz --progress \
        "${LOCAL_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/subject-level/seed_based/" \
        ${HPC_USER}@${HPC_HOST}:${HPC_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/subject-level/seed_based/
else
    echo "Subject-level z-maps already on HPC. Skipping upload."
    echo "To force re-upload, delete remote directory first."
fi

# Upload scripts
echo ""
echo "Uploading analysis scripts..."
rsync -avz --progress \
    "${LOCAL_PROJECT_DIR}/script/group_level_analysis.py" \
    "${LOCAL_PROJECT_DIR}/script/hpc_group_analysis_array.sh" \
    ${HPC_USER}@${HPC_HOST}:${HPC_PROJECT_DIR}/script/

# Make scripts executable
ssh ${HPC_USER}@${HPC_HOST} "chmod +x ${HPC_PROJECT_DIR}/script/*.sh"

echo ""
echo "================================================================"
echo "UPLOAD COMPLETE"
echo "================================================================"
echo ""
echo "Next steps on HPC:"
echo ""
echo "1. SSH to HPC:"
echo "   ssh ${HPC_USER}@${HPC_HOST}"
echo ""
echo "2. Navigate to project:"
echo "   cd ${HPC_PROJECT_DIR}"
echo ""
echo "3. Submit array job (12 seeds in parallel):"
echo "   sbatch script/hpc_group_analysis_array.sh"
echo ""
echo "4. Monitor jobs:"
echo "   squeue -u ${HPC_USER}"
echo "   watch -n 10 squeue -u ${HPC_USER}"
echo ""
echo "5. Check logs (while running):"
echo "   tail -f logs/group_analysis_*.out"
echo ""
echo "6. After completion, download results:"
echo "   bash script/hpc_download_group_results.sh"
echo ""
echo "================================================================"
