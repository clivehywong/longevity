#!/bin/bash
#SBATCH --job-name=fp_phase2
#SBATCH --cpus-per-task=15
#SBATCH --mem=64G
#SBATCH --time=24:00:00
#SBATCH --output=logs/fp_phase2_%j.out
#SBATCH --error=logs/fp_phase2_%j.err

# HPC SLURM script for FrontoParietal component seeds (Phase 2 resubmission)
# SESSION-BY-SESSION mode: Processes all 24 seeds in parallel for each session
# This provides earlier preliminary results (all seeds have some data after ~2 hours)

set -e

echo "================================================================"
echo "FrontoParietal Component Seeds - Phase 2 (SESSION-BY-SESSION)"
echo "================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: 15 (QOS limit)"
echo "Memory: 64GB"
echo "Workers: 15 (processing all 24 seeds in parallel per session)"
echo "Mode: SESSION-BY-SESSION (provides earlier preliminary results)"
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

# Run Phase 2 with SESSION-BY-SESSION mode
# This processes all 24 seeds in parallel for each session
# Provides preliminary results after ~2 hours (all seeds have 5+ z-maps)
echo "Processing 24 FrontoParietal component seeds..."
echo "Mode: SESSION-BY-SESSION (all seeds in parallel per session)"
echo "Workers: 15 (matching CPU limit)"
echo "Estimated time: ~10 hours total, preliminary results in ~2 hours"
echo ""

python "$SCRIPT_DIR/seed_based_connectivity_parallel.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$ATLASES_DIR/motor_cerebellar_seeds.json" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --session-by-session \
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
    --n-jobs 15 \
    --backend loky \
    --verbose 10

echo ""
echo "================================================================"
echo "FrontoParietal Component Analysis Complete"
echo "================================================================"
echo "End time: $(date)"
echo "Output: $SEED_DIR"
echo ""

# Count results
echo "Results summary:"
for dir in "$SEED_DIR"/fp_*/; do
    if [ -d "$dir" ]; then
        name=$(basename "$dir")
        count=$(find "$dir" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
        echo "  $name: $count z-maps"
    fi
done

echo ""
echo "Total FP component z-maps: $(find "$SEED_DIR"/fp_*/ -name '*_zmap.nii.gz' 2>/dev/null | wc -l)"
echo "Expected: 768 (24 seeds × 32 sessions)"
