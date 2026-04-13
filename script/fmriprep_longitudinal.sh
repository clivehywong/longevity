#!/bin/bash
#SBATCH --job-name=fmriprep_long          # Job name
#SBATCH --array=1-8%4                     # Will be updated per batch
#SBATCH --partition=shared_cpu
#SBATCH --cpus-per-task=8
#SBATCH --mem=32GB
#SBATCH --time=24:00:00                   # Longer for longitudinal
#SBATCH --output=logs/sub-%a_%j.out
#SBATCH --error=logs/sub-%a_%j.err

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
SUBID=$(sed -n "${SLURM_ARRAY_TASK_ID}p" /home/clivewong/proj/long/sublist.txt)

mkdir -p ${OUT_DIR} ${WORK_DIR} logs

singularity run --cleanenv \
  --bind ${BIDS_DIR}:/data:ro \
  --bind ${OUT_DIR}:/out \
  --bind ${WORK_DIR}:/work \
  --bind ${LICENSE}:/opt/freesurfer/license.txt \
  ${IMG} \
  /data /out participant \
  --participant-label ${SUBID} \
  --fs-license-file /opt/freesurfer/license.txt \
  --nthreads ${SLURM_CPUS_PER_TASK} \
  --mem_mb $(( ${SLURM_MEM_PER_NODE%%GB} * 1024 )) \
  --skip-bids-validation \
  --ignore slicetiming \
  --longitudinal \
  --output-spaces MNI152NLin2009cAsym:res-2 MNI152NLin6Asym:res-2 T1w fsnative \
  --resource-monitor
