#!/bin/bash
# Reprocess 4 problematic fMRIPrep subjects
# Usage: bash reprocess_problematic_subjects.sh [upload|submit|status|verify|download|all]

set -e

HPC_HOST="clivewong@hpclogin1.eduhk.hk"
REMOTE_DIR="/home/clivewong/proj/long"
LOCAL_DIR="/home/clivewong/proj/longevity"
SCRIPT_DIR="$(dirname "$0")"

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Upload scripts to HPC
upload_scripts() {
    log_info "Uploading reprocessing scripts to HPC..."

    # Create logs directory on HPC
    ssh ${HPC_HOST} "mkdir -p ${REMOTE_DIR}/logs"

    # Upload all scripts
    for script in run_sub055_forcesyn.sh run_sub061_ignoreT2w.sh run_sub057.sh run_sub058.sh; do
        scp "${SCRIPT_DIR}/${script}" "${HPC_HOST}:${REMOTE_DIR}/${script}"
        log_info "Uploaded ${script}"
    done

    log_info "All scripts uploaded successfully"
}

# Submit jobs to SLURM
submit_jobs() {
    local subject=$1

    if [[ -z "$subject" ]]; then
        # Submit all jobs
        log_info "Submitting all reprocessing jobs..."

        # Priority 1: Quick fixes (055, 061)
        log_info "Priority 1: sub-055 (force-syn) and sub-061 (ignore T2w)"
        ssh ${HPC_HOST} "cd ${REMOTE_DIR} && sbatch run_sub055_forcesyn.sh"
        ssh ${HPC_HOST} "cd ${REMOTE_DIR} && sbatch run_sub061_ignoreT2w.sh"

        # Priority 2: Full reprocessing (057, 058)
        log_info "Priority 2: sub-057 and sub-058 (full reprocess)"
        ssh ${HPC_HOST} "cd ${REMOTE_DIR} && sbatch run_sub057.sh"
        ssh ${HPC_HOST} "cd ${REMOTE_DIR} && sbatch run_sub058.sh"

        log_info "All jobs submitted"
    else
        # Submit single subject
        case $subject in
            055) ssh ${HPC_HOST} "cd ${REMOTE_DIR} && sbatch run_sub055_forcesyn.sh" ;;
            061) ssh ${HPC_HOST} "cd ${REMOTE_DIR} && sbatch run_sub061_ignoreT2w.sh" ;;
            057) ssh ${HPC_HOST} "cd ${REMOTE_DIR} && sbatch run_sub057.sh" ;;
            058) ssh ${HPC_HOST} "cd ${REMOTE_DIR} && sbatch run_sub058.sh" ;;
            *) log_error "Unknown subject: $subject"; exit 1 ;;
        esac
        log_info "Job for sub-${subject} submitted"
    fi
}

# Check job status
check_status() {
    log_info "Checking SLURM job status..."
    ssh ${HPC_HOST} "squeue -u clivewong --format='%.18i %.9P %.20j %.8u %.8T %.10M %.9l %.6D %R'"

    echo ""
    log_info "Recent fMRIPrep jobs:"
    ssh ${HPC_HOST} "sacct -u clivewong --starttime=now-7days --format='JobID,JobName%25,State,Elapsed,ExitCode' | grep -E 'fmriprep|JobID' | head -20" || true
}

# Verify outputs for a subject
verify_subject() {
    local sub=$1
    log_info "Verifying outputs for sub-${sub}..."

    # Check MNI outputs
    local mni_count=$(ssh ${HPC_HOST} "ls ${REMOTE_DIR}/fmriprep/sub-${sub}/ses-*/func/*MNI152NLin2009cAsym*res-2*preproc_bold.nii.gz 2>/dev/null | wc -l" || echo "0")

    # Check confounds
    local conf_count=$(ssh ${HPC_HOST} "ls ${REMOTE_DIR}/fmriprep/sub-${sub}/ses-*/func/*confounds_timeseries.tsv 2>/dev/null | wc -l" || echo "0")

    # Check HTML report
    local html_exists=$(ssh ${HPC_HOST} "test -f ${REMOTE_DIR}/fmriprep/sub-${sub}.html && echo 'yes' || echo 'no'")

    echo "  MNI BOLD outputs: ${mni_count} (expected: 2)"
    echo "  Confounds files:  ${conf_count} (expected: 2)"
    echo "  HTML report:      ${html_exists}"

    if [[ "$mni_count" -ge 2 ]] && [[ "$conf_count" -ge 2 ]] && [[ "$html_exists" == "yes" ]]; then
        log_info "sub-${sub}: ✅ COMPLETE"
        return 0
    else
        log_warn "sub-${sub}: ⚠️ INCOMPLETE"
        return 1
    fi
}

# Verify all subjects
verify_all() {
    log_info "Verifying all problematic subjects..."
    echo ""

    local complete=0
    local incomplete=0

    for sub in 055 057 058 061; do
        if verify_subject $sub; then
            ((complete++))
        else
            ((incomplete++))
        fi
        echo ""
    done

    echo "================================"
    log_info "Summary: ${complete}/4 complete, ${incomplete}/4 incomplete"
}

# Download completed subjects
download_results() {
    local subject=$1

    if [[ -z "$subject" ]]; then
        subjects="055 057 058 061"
    else
        subjects="$subject"
    fi

    for sub in $subjects; do
        log_info "Downloading sub-${sub}..."

        # Download subject directory (excluding fsnative to save space)
        rsync -avz --progress --exclude='*_space-fsnative_*' \
            "${HPC_HOST}:${REMOTE_DIR}/fmriprep/sub-${sub}/" \
            "${LOCAL_DIR}/fmriprep/sub-${sub}/"

        # Download HTML report
        rsync -avz \
            "${HPC_HOST}:${REMOTE_DIR}/fmriprep/sub-${sub}.html" \
            "${LOCAL_DIR}/fmriprep/"

        log_info "sub-${sub} download complete"
    done
}

# Check T2w file integrity for sub-061
check_t2w_integrity() {
    log_info "Checking T2w file integrity for sub-061..."

    for ses in 01 02; do
        echo ""
        log_info "Session ${ses}:"
        ssh ${HPC_HOST} "fslhd ${REMOTE_DIR}/bids/sub-061/ses-${ses}/anat/sub-061_ses-${ses}_T2w.nii.gz 2>/dev/null | head -20" || log_error "Cannot read T2w for ses-${ses}"
    done
}

# Main
case "${1:-}" in
    upload)
        upload_scripts
        ;;
    submit)
        submit_jobs "$2"
        ;;
    status)
        check_status
        ;;
    verify)
        if [[ -n "$2" ]]; then
            verify_subject "$2"
        else
            verify_all
        fi
        ;;
    download)
        download_results "$2"
        ;;
    check-t2w)
        check_t2w_integrity
        ;;
    all)
        upload_scripts
        submit_jobs
        log_info "Jobs submitted. Use 'bash $0 status' to monitor progress."
        ;;
    *)
        echo "Usage: $0 [command] [subject]"
        echo ""
        echo "Commands:"
        echo "  upload          Upload reprocessing scripts to HPC"
        echo "  submit [sub]    Submit SLURM jobs (all or specific subject: 055|057|058|061)"
        echo "  status          Check SLURM job status"
        echo "  verify [sub]    Verify outputs (all or specific subject)"
        echo "  download [sub]  Download results (all or specific subject)"
        echo "  check-t2w       Check T2w file integrity for sub-061"
        echo "  all             Upload scripts and submit all jobs"
        echo ""
        echo "Problematic Subjects:"
        echo "  055 - Registration failure (fix: --force-syn)"
        echo "  057 - Incomplete processing (fix: full rerun)"
        echo "  058 - Early termination (fix: full rerun)"
        echo "  061 - T2w corruption (fix: --ignore t2w)"
        echo ""
        echo "Note: sub-037 is USABLE - just filter task-restx in analysis"
        ;;
esac
