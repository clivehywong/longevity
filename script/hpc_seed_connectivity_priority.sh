#!/bin/bash
#SBATCH --job-name=fp_priority
#SBATCH --cpus-per-task=15
#SBATCH --mem=64G
#SBATCH --time=6:00:00
#SBATCH --output=logs/fp_priority_%j.out
#SBATCH --error=logs/fp_priority_%j.err

# HPC SLURM script for PRIORITY FrontoParietal seeds (subset for quick group analysis)
# Processes 6 key seeds SEED-BY-SEED to get complete results quickly
# Expected: ~1-1.5 hours for complete data on 6 seeds

set -e

echo "================================================================"
echo "PRIORITY FrontoParietal Seeds (6 seeds for quick group analysis)"
echo "================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: 15 (QOS limit)"
echo "Memory: 64GB"
echo "Workers: 4 (reduced to avoid OOM, seed-by-seed mode)"
echo "Mode: SEED-BY-SEED (complete seeds faster)"
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

# Priority seeds for quick analysis:
# - FP_056_IFG_LH: Left IFG (key DLPFC component)
# - FP_066_MFG_Mid_RH: Right MFG (key DLPFC component)
# - FP_115_SFG_Med: Medial SFG (dmPFC adjacent)
# - FP_120_dmPFC: Dorsomedial PFC (key control region)
# - FP_182_IPS_LH: Left IPS (attention/parietal)
# - FP_240_Precuneus_Post: Posterior precuneus (default mode interface)

echo "Processing 6 PRIORITY FrontoParietal seeds (SEED-BY-SEED)..."
echo "Seeds: IFG_LH, MFG_Mid_RH, SFG_Med, dmPFC, IPS_LH, Precuneus_Post"
echo "Workers: 4 (reduced to avoid OOM)"
echo "Estimated time: ~1.5-2 hours for ALL 6 seeds complete"
echo ""

python "$SCRIPT_DIR/seed_based_connectivity_parallel.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$ATLASES_DIR/motor_cerebellar_seeds.json" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --seed-names \
        FP_056_IFG_LH \
        FP_066_MFG_Mid_RH \
        FP_115_SFG_Med \
        FP_120_dmPFC \
        FP_182_IPS_LH \
        FP_240_Precuneus_Post \
    --fd-threshold 0.5 \
    --n-jobs 4 \
    --backend loky \
    --verbose 10

echo ""
echo "================================================================"
echo "PRIORITY Seeds Complete"
echo "================================================================"
echo "End time: $(date)"
echo "Output: $SEED_DIR"
echo ""

# Count results
echo "Results summary (priority seeds):"
for seed in fp_056_ifg_lh fp_066_mfg_mid_rh fp_115_sfg_med fp_120_dmpfc fp_182_ips_lh fp_240_precuneus_post; do
    dir="$SEED_DIR/$seed"
    if [ -d "$dir" ]; then
        count=$(find "$dir" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
        echo "  $seed: $count z-maps"
    fi
done

echo ""
echo "Total priority z-maps: $(find $SEED_DIR/fp_056* $SEED_DIR/fp_066* $SEED_DIR/fp_115* $SEED_DIR/fp_120* $SEED_DIR/fp_182* $SEED_DIR/fp_240* -name '*_zmap.nii.gz' 2>/dev/null | wc -l)"
echo "Expected: 192 (6 seeds × 32 sessions)"
echo ""
echo "Ready for group-level analysis!"
