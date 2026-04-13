#!/bin/bash
#
# Download Group-Level Results from HPC
#
# Downloads voxelwise analysis results from HPC after completion
#
# Usage:
#   bash script/hpc_download_group_results.sh
#

set -e

# Configuration
HPC_USER="clivewong"
HPC_HOST="hpclogin1.eduhk.hk"
HPC_PROJECT_DIR="/home/clivewong/proj/long"

LOCAL_PROJECT_DIR="/home/clivewong/proj/longevity"
LOCAL_OUTPUT_DIR="${LOCAL_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/group-level"

echo "================================================================"
echo "DOWNLOAD GROUP-LEVEL RESULTS FROM HPC"
echo "================================================================"
echo "HPC: ${HPC_USER}@${HPC_HOST}:${HPC_PROJECT_DIR}"
echo "Local: ${LOCAL_OUTPUT_DIR}"
echo "================================================================"
echo ""

# Create local output directory
mkdir -p "$LOCAL_OUTPUT_DIR"

# Check if HPC results exist
echo "Checking HPC for completed analyses..."
ssh ${HPC_USER}@${HPC_HOST} "ls -d ${HPC_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/group-level/seed_*/ 2>/dev/null | wc -l" || N_SEEDS=0
N_SEEDS=$(ssh ${HPC_USER}@${HPC_HOST} "ls -d ${HPC_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/group-level/seed_*/ 2>/dev/null | wc -l")

if [ "$N_SEEDS" -eq 0 ]; then
    echo "ERROR: No seed results found on HPC"
    echo "Expected: ${HPC_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/group-level/seed_*/"
    exit 1
fi

echo "Found $N_SEEDS seed analyses on HPC"
echo ""

# Download all seed results
echo "Downloading group-level results..."
rsync -avz --progress \
    ${HPC_USER}@${HPC_HOST}:${HPC_PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/group-level/ \
    "$LOCAL_OUTPUT_DIR/"

# Download logs
echo ""
echo "Downloading SLURM logs..."
mkdir -p "${LOCAL_PROJECT_DIR}/hpc_logs"
rsync -avz --progress \
    ${HPC_USER}@${HPC_HOST}:${HPC_PROJECT_DIR}/logs/ \
    "${LOCAL_PROJECT_DIR}/hpc_logs/"

echo ""
echo "================================================================"
echo "DOWNLOAD COMPLETE"
echo "================================================================"
echo ""

# Summary of downloaded results
echo "Downloaded seed analyses:"
ls -d "${LOCAL_OUTPUT_DIR}"/seed_*/ | while read seed_dir; do
    seed_name=$(basename "$seed_dir")

    # Check for results
    if [ -f "$seed_dir/correction_info.json" ]; then
        correction=$(cat "$seed_dir/correction_info.json" | grep -o '"method"[^,]*' | cut -d'"' -f4)

        if [ -f "$seed_dir/clusters_interaction.csv" ]; then
            n_clusters=$(tail -n +2 "$seed_dir/clusters_interaction.csv" | wc -l)
            echo "  ✓ $seed_name - $correction correction - $n_clusters clusters"
        else
            echo "  ✓ $seed_name - $correction correction - 0 clusters"
        fi
    else
        echo "  ✗ $seed_name - INCOMPLETE"
    fi
done

echo ""
echo "SLURM logs saved to: ${LOCAL_PROJECT_DIR}/hpc_logs/"
echo ""
echo "Next steps:"
echo ""
echo "1. Generate cluster barplots (local):"
echo "   bash script/local_generate_barplots.sh"
echo ""
echo "2. Generate HTML report (local):"
echo "   bash script/local_generate_report.sh"
echo ""
echo "3. Or run both automatically:"
echo "   bash script/local_postprocessing.sh"
echo ""
echo "================================================================"
