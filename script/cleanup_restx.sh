#!/bin/bash
# Remove corrupted task-restx z-maps for sub-037 ses-01
# This subject has both task-rest (good) and task-restx (corrupted)
# We need to keep only task-rest

echo "=========================================="
echo "Cleaning up corrupted task-restx z-maps"
echo "=========================================="
echo ""

SEED_DIR="derivatives/connectivity-difumo256/subject-level/seed_based"

for seed in dlpfc_l dlpfc_r dlpfc_bilateral; do
    # Look for restx files (filename will have task-restx in the parent BOLD filename)
    # The z-map filename is sub-037_ses-01_zmap.nii.gz
    # We need to check the individual_maps.csv to see which one came from restx

    csv_file="$SEED_DIR/$seed/individual_maps.csv"
    if [ -f "$csv_file" ]; then
        echo "Checking $seed..."

        # Find sub-037 ses-01 entries with restx in the source file path
        restx_entries=$(grep "sub-037.*ses-01.*task-restx" "$csv_file" || true)

        if [ -n "$restx_entries" ]; then
            echo "  Found task-restx entry in $seed:"
            echo "$restx_entries" | head -3
            echo ""
            echo "  WARNING: Cannot automatically identify which z-map file is from restx"
            echo "  Both task-rest and task-restx create: sub-037_ses-01_zmap.nii.gz"
            echo "  Manual intervention required!"
        else
            echo "  No task-restx entries found (good)"
        fi
    fi
done

echo ""
echo "=========================================="
echo "RECOMMENDED ACTION:"
echo "=========================================="
echo ""
echo "Since sub-037 has both task-rest and task-restx for ses-01,"
echo "and both would create 'sub-037_ses-01_zmap.nii.gz', we need to:"
echo ""
echo "Option 1: Exclude sub-037 ses-01 from group analysis"
echo "  - Edit metadata to remove this session"
echo "  - Keep ses-02 for sub-037"
echo ""
echo "Option 2: Reprocess with explicit task-rest glob pattern"
echo "  - Modify script to use: *task-rest_space-* (not *task-rest*)"
echo "  - This excludes task-restx"
echo ""
echo "For now, check individual_maps.csv to see if both were processed."
