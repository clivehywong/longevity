#!/bin/bash
#SBATCH --job-name=fp_seeds
#SBATCH --cpus-per-task=15
#SBATCH --mem=64G
#SBATCH --time=16:00:00
#SBATCH --output=logs/fp_seeds_%j.out
#SBATCH --error=logs/fp_seeds_%j.err

# HPC SLURM script for parallel seed-based connectivity analysis
# This runs on EdUHK HPC with 16 CPUs and 64GB RAM for ~4x speedup

set -e

echo "================================================================"
echo "Seed-Based Connectivity Analysis - HPC"
echo "================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: 15 (QOS limit)"
echo "Memory: 64GB"
echo "Start time: $(date)"
echo ""

# Paths on HPC
PROJECT_DIR="/home/clivewong/proj/long"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
SCRIPT_DIR="$PROJECT_DIR/script"
ATLASES_DIR="$PROJECT_DIR/atlases"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
METADATA_FILE="$DERIVATIVE_ROOT/participants.tsv"
SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"

mkdir -p "$SEED_DIR"

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# Run parallel seed-based connectivity with 8 workers
# 64GB RAM / 8 workers = 8GB per worker (safe)
echo "Running parallel seed-based connectivity..."
echo "Workers: 8"
echo ""
echo "Phase 1: Updated DLPFC seeds with probability_threshold >= 0.5 (validation)"
echo ""

python "$SCRIPT_DIR/seed_based_connectivity_parallel.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$ATLASES_DIR/motor_cerebellar_seeds.json" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --seed-names DLPFC_L DLPFC_R DLPFC_Bilateral \
    --fd-threshold 0.5 \
    --n-jobs 8 \
    --backend loky \
    --verbose 10

echo ""
echo "Phase 2: Individual FrontoParietal component seeds (24 seeds)"
echo ""

python "$SCRIPT_DIR/seed_based_connectivity_parallel.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$ATLASES_DIR/motor_cerebellar_seeds.json" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --seed-names \
        FP_001_MFG_Ant_RH FP_003_IFS_Post_RH FP_023_POS_Mid \
        FP_028_Angular_Sup_RH FP_056_IFG_LH FP_066_MFG_Mid_RH \
        FP_074_IFS_Post_LH FP_078_FP_Lat_RH FP_093_IFS_Ant_LH \
        FP_115_SFG_Med FP_117_IPS_Inf_RH FP_120_dmPFC \
        FP_128_PrCS_RH FP_140_IFG_Ant_LH FP_143_IFS_Ant_RH \
        FP_144_Angular_Sup_LH FP_145_IPJ_RH FP_182_IPS_LH \
        FP_184_FP_Lat_LH FP_191_MFG_Post_RH FP_204_PCS_Mid \
        FP_213_MFG_Ant FP_240_Precuneus_Post FP_247_SFS_RH \
    --fd-threshold 0.5 \
    --n-jobs 8 \
    --backend loky \
    --verbose 10

echo ""
echo "================================================================"
echo "Seed-Based Connectivity Analysis Complete"
echo "================================================================"
echo "End time: $(date)"
echo "Output: $SEED_DIR"
echo ""

# Count results
echo "Results summary:"
for dir in "$SEED_DIR"/*/; do
    if [ -d "$dir" ]; then
        name=$(basename "$dir")
        count=$(find "$dir" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
        echo "  $name: $count z-maps"
    fi
done

echo ""
echo "Total z-maps: $(find "$SEED_DIR" -name '*_zmap.nii.gz' 2>/dev/null | wc -l)"
