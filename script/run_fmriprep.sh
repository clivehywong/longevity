#!/bin/bash
# fMRIPrep preprocessing script for longevity dataset
# Uses Singularity container

set -e

# Configuration
BIDS_DIR="/home/clivewong/proj/longevity/bids"
OUTPUT_DIR="/home/clivewong/proj/longevity/derivatives/fmriprep"
WORK_DIR="/home/clivewong/proj/longevity/work/fmriprep"
FS_LICENSE="/home/clivewong/license.txt"  # FreeSurfer license - UPDATE THIS PATH

# fMRIPrep version and container
FMRIPREP_VERSION="24.0.1"
CONTAINER_DIR="/home/clivewong/containers"
CONTAINER="${CONTAINER_DIR}/fmriprep-${FMRIPREP_VERSION}.sif"

# Processing settings
NTHREADS=8
OMP_NTHREADS=4
MEM_MB=32000

# Output spaces
OUTPUT_SPACES="MNI152NLin2009cAsym:res-2 anat"

# All subjects with complete data (both sessions)
COMPLETE_SUBJECTS="033 034 035 036 037 038 039 040 043 045 046 047 048 052 055 056 057 058 059 060 061 062 063 064"

# All subjects with session 1 only
SES1_ONLY_SUBJECTS="049 051 053 054 065 066 067 068 069 070 071 072 073 074 076 077 079 080 081 082"

# Default: process all subjects
SUBJECTS="${COMPLETE_SUBJECTS} ${SES1_ONLY_SUBJECTS}"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --participant-label)
            SUBJECTS="$2"
            shift 2
            ;;
        --complete-only)
            SUBJECTS="${COMPLETE_SUBJECTS}"
            shift
            ;;
        --ses1-only)
            SUBJECTS="${SES1_ONLY_SUBJECTS}"
            shift
            ;;
        --test)
            # Test with single subject
            SUBJECTS="033"
            shift
            ;;
        --download-container)
            DOWNLOAD_CONTAINER=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --participant-label SUBS  Process specific subjects (space-separated)"
            echo "  --complete-only           Process only subjects with both sessions (n=24)"
            echo "  --ses1-only               Process only subjects with session 1 (n=20)"
            echo "  --test                    Test run with single subject (sub-033)"
            echo "  --download-container      Download fMRIPrep container first"
            echo "  --help                    Show this help"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Create directories
mkdir -p "${OUTPUT_DIR}"
mkdir -p "${WORK_DIR}"
mkdir -p "${CONTAINER_DIR}"

# Check FreeSurfer license
if [[ ! -f "${FS_LICENSE}" ]]; then
    echo "ERROR: FreeSurfer license not found at ${FS_LICENSE}"
    echo ""
    echo "To obtain a FreeSurfer license (free):"
    echo "1. Go to https://surfer.nmr.mgh.harvard.edu/registration.html"
    echo "2. Fill out the registration form"
    echo "3. Download the license.txt file"
    echo "4. Save it to: ${FS_LICENSE}"
    exit 1
fi

# Download container if requested or not present
if [[ "${DOWNLOAD_CONTAINER}" == "true" ]] || [[ ! -f "${CONTAINER}" ]]; then
    echo "Downloading fMRIPrep ${FMRIPREP_VERSION} container..."
    singularity pull "${CONTAINER}" docker://nipreps/fmriprep:${FMRIPREP_VERSION}
fi

# Check container exists
if [[ ! -f "${CONTAINER}" ]]; then
    echo "ERROR: fMRIPrep container not found at ${CONTAINER}"
    echo "Run with --download-container to download it"
    exit 1
fi

echo "=============================================="
echo "fMRIPrep Preprocessing"
echo "=============================================="
echo "BIDS directory: ${BIDS_DIR}"
echo "Output directory: ${OUTPUT_DIR}"
echo "Work directory: ${WORK_DIR}"
echo "Container: ${CONTAINER}"
echo "Subjects: ${SUBJECTS}"
echo "Threads: ${NTHREADS} (OMP: ${OMP_NTHREADS})"
echo "Memory: ${MEM_MB} MB"
echo "Output spaces: ${OUTPUT_SPACES}"
echo "=============================================="

# Run fMRIPrep
singularity run --cleanenv \
    -B "${BIDS_DIR}":/data:ro \
    -B "${OUTPUT_DIR}":/out \
    -B "${WORK_DIR}":/work \
    -B "${FS_LICENSE}":/opt/freesurfer/license.txt:ro \
    "${CONTAINER}" \
    /data /out participant \
    --participant-label ${SUBJECTS} \
    --output-spaces ${OUTPUT_SPACES} \
    --work-dir /work \
    --nthreads ${NTHREADS} \
    --omp-nthreads ${OMP_NTHREADS} \
    --mem-mb ${MEM_MB} \
    --skip-bids-validation \
    --write-graph \
    --stop-on-first-crash

echo ""
echo "fMRIPrep completed!"
echo "Results: ${OUTPUT_DIR}"
echo "Reports: ${OUTPUT_DIR}/sub-*/figures/"
