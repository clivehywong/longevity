#!/bin/bash
#SBATCH --job-name=xcpd_fc_v2
#SBATCH --partition=shared_cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=24:00:00
#SBATCH --output=/home/clivewong/proj/long/logs/xcpd_fc_v2_%j.out
#SBATCH --error=/home/clivewong/proj/long/logs/xcpd_fc_v2_%j.err

set -euo pipefail

# Initialize module system if available
if [ -f /etc/profile.d/modules.sh ]; then
    source /etc/profile.d/modules.sh
elif [ -f /usr/share/Modules/init/bash ]; then
    source /usr/share/Modules/init/bash
fi

# Load singularity module if needed
if ! command -v singularity &> /dev/null && command -v module &> /dev/null; then
    module purge
    module load singularity 2>/dev/null || true
fi

if ! command -v singularity &> /dev/null; then
    echo "ERROR: singularity is not available on the compute node." >&2
    exit 1
fi
mkdir -p /home/clivewong/proj/long/logs /home/clivewong/proj/long/work/xcpd/fc
echo "====== XCP-D FC | Job: ${SLURM_JOB_ID} | Node: $(hostname) | Start: $(date) ======"

singularity run \
  -B /home/clivewong/proj/long:/home/clivewong/proj/long \
  -B /home/clivewong/proj/long/bids:/home/clivewong/proj/long/bids \
  -B /home/clivewong/proj/long/derivatives:/home/clivewong/proj/long/derivatives \
  -B /home/clivewong/proj/long/atlases:/home/clivewong/proj/long/atlases \
  -B /home/clivewong/proj/long/work:/home/clivewong/proj/long/work \
  -B /home/clivewong/software:/home/clivewong/software \
  -B /home/clivewong/freesurfer/license.txt:/home/clivewong/freesurfer/license.txt \
  /home/clivewong/software/xcp-d-26.0.2.sif \
  /home/clivewong/proj/long/derivatives/preprocessing/fmriprep \
  /home/clivewong/proj/long/derivatives/preprocessing/xcpd/fc \
  participant --mode linc -p acompcor --dummy-scans auto -f 0.3 --min-time 240 \
  --motion-filter-type notch --band-stop-min 12 --band-stop-max 18 \
  --smoothing 6.0 --head-radius auto --min-coverage 0.5 \
  --output-type censored --output-layout bids --input-type fmriprep \
  --file-format nifti --report-output-level session --output-run-wise-correlations y \
  -w /home/clivewong/proj/long/work/xcpd/fc \
  --despike --lower-bpf 0.01 --upper-bpf 0.08 \
  --fs-license-file /home/clivewong/freesurfer/license.txt \
  --datasets longevity=/home/clivewong/proj/long/atlases/xcpd_project_atlases \
  --atlases LongevitySchaefer200 Tian \
  --nprocs 8 --omp-nthreads 1 \
  --participant-label 043 045 046 047 048 051 052 055 056 057 058 059 060 061 062 063 064 065 069 071 074 076 079 080 081 \
  --session-id 01 02

EXIT_CODE=$?
echo "====== XCP-D FC done | Exit: ${EXIT_CODE} | End: $(date) ======"

# Clean work dir to free disk space for next pipeline
echo "Cleaning work directory..."
rm -rf /home/clivewong/proj/long/work/xcpd/fc/
echo "Work dir cleaned"

exit ${EXIT_CODE}
