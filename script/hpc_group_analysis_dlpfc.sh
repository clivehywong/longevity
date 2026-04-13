#!/bin/bash
#SBATCH --job-name=grp_dlpfc
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=4:00:00
#SBATCH --output=logs/grp_dlpfc_%j.out
#SBATCH --error=logs/grp_dlpfc_%j.err

# HPC SLURM script for Group-Level Analysis of DLPFC Seeds
# Runs voxelwise linear mixed-effects model: value ~ Group * Time + Age + Sex + MeanFD + (1|Subject)
# Applies permutation testing with TFCE for cluster correction (FWE p < 0.05)

set -e

echo "================================================================"
echo "Group-Level Analysis: DLPFC Seeds"
echo "================================================================"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: 4"
echo "Memory: 32GB"
echo "Start time: $(date)"
echo ""

# Paths on HPC
PROJECT_DIR="/home/clivewong/proj/long"
SCRIPT_DIR="$PROJECT_DIR/script"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"
METADATA_FILE="$DERIVATIVE_ROOT/participants.tsv"
GROUP_OUTPUT="$DERIVATIVE_ROOT/group-level/seed_based"

mkdir -p "$GROUP_OUTPUT"

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

echo "Analyzing 3 DLPFC seeds (32 z-maps each)..."
echo "Seeds: DLPFC_L, DLPFC_R, DLPFC_Bilateral"
echo "Model: value ~ Group * Time + Age + Sex + MeanFD + (1|Subject)"
echo "Correction: Permutation testing with TFCE, FWE p < 0.05"
echo ""

# Run group analysis for each DLPFC seed
for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    echo "================================================================"
    echo "SEED: ${seed^^}"
    echo "================================================================"

    INPUT_MAPS="$SEED_DIR/$seed/*_zmap.nii.gz"
    OUTPUT_DIR="$GROUP_OUTPUT/$seed"

    echo "Input: $SEED_DIR/$seed/"
    echo "Output: $OUTPUT_DIR"
    echo "Z-maps: $(ls $INPUT_MAPS 2>/dev/null | wc -l)"
    echo ""

    python "$SCRIPT_DIR/group_level_analysis.py" \
        --input-maps $INPUT_MAPS \
        --metadata "$METADATA_FILE" \
        --output "$OUTPUT_DIR" \
        --cluster-threshold 0.05 \
        --n-permutations 5000

    echo ""
    echo "✓ $seed complete"
    echo ""
done

echo "================================================================"
echo "Group-Level Analysis Complete"
echo "================================================================"
echo "End time: $(date)"
echo "Output: $GROUP_OUTPUT"
echo ""

# Summary
echo "Results summary:"
for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    output_dir="$GROUP_OUTPUT/$seed"
    if [ -d "$output_dir" ]; then
        echo ""
        echo "  $seed:"

        # Check for interaction maps
        if [ -f "$output_dir/interaction_tstat_map.nii.gz" ]; then
            echo "    ✓ Interaction t-stat map"
        fi

        # Check for FWE-corrected maps
        fwe_maps=$(find "$output_dir" -name "*_fwe_p05.nii.gz" 2>/dev/null | wc -l)
        echo "    ✓ $fwe_maps FWE-corrected maps (p<0.05)"

        # Check for cluster tables
        cluster_tables=$(find "$output_dir" -name "clusters_*.csv" 2>/dev/null | wc -l)
        echo "    ✓ $cluster_tables cluster tables"

        # Check for visualizations
        pngs=$(find "$output_dir" -name "*.png" 2>/dev/null | wc -l)
        echo "    ✓ $pngs visualizations"
    fi
done

echo ""
echo "Ready for interpretation!"
