#!/bin/bash
#SBATCH --job-name=fmriprep_055_syn
#SBATCH --partition=shared_cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=32GB
#SBATCH --time=24:00:00
#SBATCH --output=logs/sub-055_forcesyn_%j.out
#SBATCH --error=logs/sub-055_forcesyn_%j.err

# Sub-055: Registration failure - reprocess with --force-syn flag
# Root cause: Template registration failed during anatomical normalization
# Expected outcome: Full MNI-space outputs

# Initialize module system if available
if [ -f /etc/profile.d/modules.sh ]; then
    source /etc/profile.d/modules.sh
elif [ -f /usr/share/Modules/init/bash ]; then
    source /usr/share/Modules/init/bash
fi

# Load singularity module if available
if command -v module &> /dev/null; then
    module purge
    module load singularity
fi

BIDS_DIR="/home/clivewong/proj/long/bids"
OUT_DIR="/home/clivewong/proj/long/fmriprep"
WORK_DIR="/home/clivewong/proj/long/fmriprep_work"
IMG="/home/clivewong/software/fmriprep-25.1.4.simg"
LICENSE="/home/clivewong/freesurfer/license.txt"

# Clear previous work directory for this subject
rm -rf ${WORK_DIR}/fmriprep_25_1_wf/single_subject_055_wf

singularity run --cleanenv \
  --bind ${BIDS_DIR}:/data:ro \
  --bind ${OUT_DIR}:/out \
  --bind ${WORK_DIR}:/work \
  --bind ${LICENSE}:/opt/freesurfer/license.txt \
  ${IMG} \
  /data /out participant \
  --participant-label 055 \
  --fs-license-file /opt/freesurfer/license.txt \
  --work-dir /work \
  --nthreads 8 \
  --mem_mb 32768 \
  --skip-bids-validation \
  --ignore slicetiming \
  --longitudinal \
  --use-syn-sdc \
  --output-spaces MNI152NLin2009cAsym:res-2 MNI152NLin6Asym:res-2 T1w fsnative \
  --resource-monitor

echo "Sub-055 processing complete at $(date)"
