#!/bin/bash
# Complete workflow for DLPFC group analysis
# Run this after Job 2961 completes on HPC

set -e

echo "=========================================="
echo "DLPFC Group Analysis Workflow"
echo "=========================================="
echo "Start time: $(date)"
echo ""

# Step 1: Download DLPFC z-maps from HPC
echo "Step 1: Downloading DLPFC z-maps from HPC..."
mkdir -p derivatives/connectivity-difumo256/subject-level/seed_based
for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    echo "  Downloading $seed..."
    rsync -avz --progress \
        clivewong@hpclogin1.eduhk.hk:/home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based/$seed/ \
        derivatives/connectivity-difumo256/subject-level/seed_based/$seed/

    count=$(find derivatives/connectivity-difumo256/subject-level/seed_based/$seed -name '*_zmap.nii.gz' 2>/dev/null | wc -l)
    echo "    Downloaded $count z-maps"
done
echo ""

# Step 2: Update metadata with motion QC
echo "Step 2: Updating metadata with motion QC from seed output..."
python3 script/update_metadata_with_motion.py \
    --metadata derivatives/connectivity-difumo256/participants_all24.csv \
    --seed-csv derivatives/connectivity-difumo256/subject-level/seed_based/dlpfc_l/individual_maps.csv \
    --output derivatives/connectivity-difumo256/participants_all24_final.csv

# Check for task-restx issue in sub-037
echo ""
echo "Checking for task-restx in sub-037..."
if grep -q "task-restx" derivatives/connectivity-difumo256/subject-level/seed_based/dlpfc_l/individual_maps.csv; then
    echo "  WARNING: Found task-restx in individual_maps.csv"
    echo "  Removing sub-037 ses-01 from metadata (corrupted restx file)"
    # Create clean metadata without the problematic session
    python3 << 'EOFPYTHON'
import pandas as pd
meta = pd.read_csv('derivatives/connectivity-difumo256/participants_all24_final.csv')
# Remove any sub-037 ses-01 entries that came from restx
# We'll identify them by checking if they exist in individual_maps.csv with restx
seed_data = pd.read_csv('derivatives/connectivity-difumo256/subject-level/seed_based/dlpfc_l/individual_maps.csv')
restx_mask = seed_data['file'].str.contains('task-restx', na=False)
if restx_mask.any():
    print(f"  Found {restx_mask.sum()} restx entries")
    # If sub-037 ses-01 is in the restx list, exclude it
    restx_sessions = seed_data[restx_mask][['subject', 'session']]
    for _, row in restx_sessions.iterrows():
        print(f"    Excluding: {row['subject']} {row['session']}")
        meta = meta[~((meta['subject'] == row['subject']) & (meta['session'] == row['session']))]
meta.to_csv('derivatives/connectivity-difumo256/participants_all24_final.csv', index=False)
print(f"  Final metadata: {len(meta)} sessions")
EOFPYTHON
else
    echo "  No task-restx found (good)"
fi
echo ""

# Step 3: Run group-level analysis for each DLPFC seed
echo "Step 3: Running group-level analysis..."
for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    echo ""
    echo "  Analyzing $seed..."

    output_dir="derivatives/connectivity-difumo256/group-level/seed_based/$seed"
    mkdir -p "$output_dir"

    python3 script/group_level_analysis.py \
        --input-maps $(find derivatives/connectivity-difumo256/subject-level/seed_based/$seed -name '*_zmap.nii.gz' | tr '\n' ' ') \
        --metadata derivatives/connectivity-difumo256/participants_all24_final.csv \
        --output "$output_dir" \
        --cluster-threshold 0.05 \
        --n-permutations 5000

    echo "    ✓ $seed complete"
    echo "    Output: $output_dir"
done
echo ""

echo "=========================================="
echo "DLPFC Group Analysis Complete!"
echo "=========================================="
echo "End time: $(date)"
echo ""

# Summary
echo "Results locations:"
for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    dir="derivatives/connectivity-difumo256/group-level/seed_based/$seed"
    if [ -d "$dir" ]; then
        echo ""
        echo "  $seed:"

        # Count output files
        n_nii=$(find "$dir" -name "*.nii.gz" 2>/dev/null | wc -l)
        n_csv=$(find "$dir" -name "*.csv" 2>/dev/null | wc -l)
        n_png=$(find "$dir" -name "*.png" 2>/dev/null | wc -l)

        echo "    NIfTI maps: $n_nii"
        echo "    CSV tables: $n_csv"
        echo "    Visualizations: $n_png"

        # Show significant clusters if available
        if [ -f "$dir/clusters_interaction.csv" ]; then
            n_clusters=$(tail -n +2 "$dir/clusters_interaction.csv" | wc -l)
            echo "    Significant clusters (Group×Time): $n_clusters"
        fi
    fi
done

echo ""
echo "View results:"
echo "  HTML report: derivatives/connectivity-difumo256/group-level/seed_based/dlpfc_l/index.html (if generated)"
echo "  Cluster tables: derivatives/connectivity-difumo256/group-level/seed_based/*/clusters_*.csv"
echo "  Brain maps: derivatives/connectivity-difumo256/group-level/seed_based/*/*.png"
