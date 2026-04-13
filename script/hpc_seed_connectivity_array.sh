#!/bin/bash
#SBATCH --job-name=seed_array
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=6:00:00
#SBATCH --array=1-17
#SBATCH --output=logs/seed_%A_%a.out
#SBATCH --error=logs/seed_%A_%a.err

# =============================================================================
# HPC SLURM Array Script: Seed-Based Connectivity for 17 Priority Seeds
# =============================================================================
# Runs seed-based connectivity analysis in parallel for 17 priority seeds
# using SLURM job arrays. Each array task processes one seed.
#
# Seeds include:
# - DLPFC (anatomically corrected L/R/Bilateral)
# - Salience network (Anterior_Insula, dACC, Combined)
# - Hippocampus (Anterior, Posterior, Bilateral)
# - Motor-cerebellar (Motor_Cortex, Cerebellar_Motor, lateralized cerebellar)
# - Network seeds (Default_Mode, Frontoparietal_Control)
#
# Processing time: ~3-5 min per subject per seed
# Parallelized via SLURM array (16 jobs)
# =============================================================================

set -e

echo "================================================================"
echo "Seed-Based Connectivity Analysis - Array Job"
echo "================================================================"
echo "Job Array ID: $SLURM_ARRAY_JOB_ID"
echo "Array Task ID: $SLURM_ARRAY_TASK_ID"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: 16GB"
echo "Start time: $(date)"
echo ""

# Paths on HPC
PROJECT_DIR="/home/clivewong/proj/long"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
SCRIPT_DIR="$PROJECT_DIR/script"
ATLASES_DIR="$PROJECT_DIR/atlases"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
METADATA_FILE="$DERIVATIVE_ROOT/participants_all24_final.csv"
SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"

mkdir -p "$SEED_DIR"
mkdir -p logs

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# Define seed list (17 priority seeds - added Cerebellar_Vestibular)
SEED_LIST=(
    "Anterior_Insula"
    "dACC"
    "Insula_dACC_Combined"
    "Hippocampus"
    "Hippocampus_Anterior"
    "Hippocampus_Posterior"
    "Cerebellar_Cognitive_L"
    "Cerebellar_Cognitive_R"
    "Cerebellar_Cognitive_Bilateral"
    "Cerebellar_Motor"
    "Cerebellar_Vestibular"
    "Motor_Cortex"
    "Default_Mode"
    "Frontoparietal_Control"
    "DLPFC_Coarse"
    "DLPFC_Dorsal"
    "DLPFC_Ventral"
)

# Get seed for this array task
SEED=${SEED_LIST[$SLURM_ARRAY_TASK_ID-1]}

echo "Processing seed: $SEED"
echo "Array task: $SLURM_ARRAY_TASK_ID / ${#SEED_LIST[@]}"
echo ""

# Run seed-based connectivity
python "$SCRIPT_DIR/seed_based_connectivity.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$ATLASES_DIR/motor_cerebellar_seeds.json" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --seed-names "$SEED" \
    --smoothing 6.0 \
    --high-pass 0.01 \
    --low-pass 0.1

echo ""
echo "================================================================"
echo "Seed-Based Connectivity Complete for $SEED"
echo "================================================================"
echo "End time: $(date)"
echo ""

# Count results for this seed
SEED_OUTPUT_DIR="$SEED_DIR/$(echo $SEED | tr '[:upper:]' '[:lower:]' | tr '_' '_')"
if [ -d "$SEED_OUTPUT_DIR" ]; then
    zmap_count=$(find "$SEED_OUTPUT_DIR" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
    echo "Results: $zmap_count z-maps generated for $SEED"
    echo "Output: $SEED_OUTPUT_DIR"
else
    echo "WARNING: Output directory not found: $SEED_OUTPUT_DIR"
fi
