#!/bin/bash
# Batch workflow for longitudinal fMRIPrep processing
# Handles upload, processing, and download in batches due to storage limits

set -e

# Configuration
LOCAL_BIDS="/home/clivewong/proj/longevity/bids"
LOCAL_OUTPUT="/home/clivewong/proj/longevity/fmriprep"
REMOTE_HOST="clivewong@hpclogin1.eduhk.hk"
REMOTE_BASE="/home/clivewong/proj/long"
BATCH_SIZE=8  # Number of subjects per batch

# Subjects with both sessions (longitudinal)
# Already processed: 043 045 046 047 048 052 055 057 058 059 060 061
# Remaining subjects to process:
SUBJECTS=(
    033 034 035 036 037 038 039 040
    056 062 063 064
)

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"; }
error() { echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"; exit 1; }

# Create local output directory
mkdir -p "${LOCAL_OUTPUT}"

# Calculate number of batches
TOTAL=${#SUBJECTS[@]}
NUM_BATCHES=$(( (TOTAL + BATCH_SIZE - 1) / BATCH_SIZE ))

log "Total subjects: ${TOTAL}"
log "Batch size: ${BATCH_SIZE}"
log "Number of batches: ${NUM_BATCHES}"

# Function to upload a batch
upload_batch() {
    local batch_num=$1
    local start_idx=$(( (batch_num - 1) * BATCH_SIZE ))
    local batch_subjects=("${SUBJECTS[@]:$start_idx:$BATCH_SIZE}")

    log "Uploading batch ${batch_num}/${NUM_BATCHES}: ${batch_subjects[*]}"

    # Create subject list for this batch
    printf '%s\n' "${batch_subjects[@]}" | ssh ${REMOTE_HOST} "cat > ${REMOTE_BASE}/sublist.txt"

    # Upload BIDS data for each subject
    for sub in "${batch_subjects[@]}"; do
        log "  Uploading sub-${sub}..."
        rsync -avz --progress \
            "${LOCAL_BIDS}/sub-${sub}/" \
            "${REMOTE_HOST}:${REMOTE_BASE}/bids/sub-${sub}/"
    done

    # Upload dataset_description.json if not exists
    ssh ${REMOTE_HOST} "test -f ${REMOTE_BASE}/bids/dataset_description.json" || \
        echo '{"Name": "long", "BIDSVersion": "1.6.0", "DatasetType": "raw"}' | \
        ssh ${REMOTE_HOST} "cat > ${REMOTE_BASE}/bids/dataset_description.json"

    # Update SLURM array size
    local n_subs=${#batch_subjects[@]}
    ssh ${REMOTE_HOST} "sed -i 's/^#SBATCH --array=.*/#SBATCH --array=1-${n_subs}%4/' ${REMOTE_BASE}/fmriprep_longitudinal.sh"
}

# Function to submit and wait for job
submit_and_wait() {
    local batch_num=$1

    log "Submitting fmriprep job for batch ${batch_num}..."

    # Submit job and capture job ID
    local job_id=$(ssh ${REMOTE_HOST} "cd ${REMOTE_BASE} && sbatch fmriprep_longitudinal.sh" | grep -o '[0-9]*' | head -1)

    if [ -z "$job_id" ]; then
        error "Failed to submit job"
    fi

    log "Job submitted: ${job_id}"
    log "Waiting for job completion..."

    # Poll job status
    while true; do
        local status=$(ssh ${REMOTE_HOST} "squeue -j ${job_id} -h 2>/dev/null | wc -l")
        if [ "$status" -eq 0 ]; then
            log "Job ${job_id} completed"
            break
        fi
        sleep 300  # Check every 5 minutes
    done
}

# Function to download results (selective - exclude large work dirs)
download_batch() {
    local batch_num=$1
    local start_idx=$(( (batch_num - 1) * BATCH_SIZE ))
    local batch_subjects=("${SUBJECTS[@]:$start_idx:$BATCH_SIZE}")

    log "Downloading results for batch ${batch_num}..."

    for sub in "${batch_subjects[@]}"; do
        log "  Downloading sub-${sub}..."

        # Download subject derivatives including figures (excludes fsnative space to save space)
        rsync -avz --progress \
            --exclude='*_space-fsnative_*' \
            "${REMOTE_HOST}:${REMOTE_BASE}/fmriprep/sub-${sub}/" \
            "${LOCAL_OUTPUT}/sub-${sub}/"

        # Download subject HTML report
        rsync -avz "${REMOTE_HOST}:${REMOTE_BASE}/fmriprep/sub-${sub}.html" "${LOCAL_OUTPUT}/" 2>/dev/null || true
    done

    # Download dataset-level files
    rsync -avz "${REMOTE_HOST}:${REMOTE_BASE}/fmriprep/dataset_description.json" "${LOCAL_OUTPUT}/" 2>/dev/null || true
    rsync -avz "${REMOTE_HOST}:${REMOTE_BASE}/fmriprep/logs/" "${LOCAL_OUTPUT}/logs/" 2>/dev/null || true

    log "Download complete. Work directories excluded to save space."
}

# Function to cleanup remote
cleanup_remote() {
    local batch_num=$1
    local start_idx=$(( (batch_num - 1) * BATCH_SIZE ))
    local batch_subjects=("${SUBJECTS[@]:$start_idx:$BATCH_SIZE}")

    log "Cleaning up remote for batch ${batch_num}..."

    for sub in "${batch_subjects[@]}"; do
        ssh ${REMOTE_HOST} "rm -rf ${REMOTE_BASE}/bids/sub-${sub} ${REMOTE_BASE}/fmriprep/sub-${sub}* ${REMOTE_BASE}/fmriprep_work/fmriprep*sub-${sub}*"
    done
}

# Main workflow
main() {
    local start_batch=${1:-1}

    log "Starting from batch ${start_batch}"

    for (( batch=start_batch; batch<=NUM_BATCHES; batch++ )); do
        log "=========================================="
        log "Processing batch ${batch}/${NUM_BATCHES}"
        log "=========================================="

        upload_batch $batch
        submit_and_wait $batch
        download_batch $batch
        cleanup_remote $batch

        log "Batch ${batch} complete!"
    done

    log "All batches complete!"
}

# Command line interface
case "${1:-}" in
    upload)
        upload_batch ${2:-1}
        ;;
    submit)
        submit_and_wait ${2:-1}
        ;;
    download)
        download_batch ${2:-1}
        ;;
    cleanup)
        cleanup_remote ${2:-1}
        ;;
    status)
        ssh ${REMOTE_HOST} "squeue -u clivewong"
        ;;
    *)
        if [ -n "$1" ] && [ "$1" -eq "$1" ] 2>/dev/null; then
            main $1
        else
            main 1
        fi
        ;;
esac
