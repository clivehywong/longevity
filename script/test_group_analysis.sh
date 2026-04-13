#!/usr/bin/env bash
#
# Quick Test Script for Group-Level Analysis Pipeline
#
# Tests with motor_cortex seed only (fastest validation)
#
# Usage:
#   bash script/test_group_analysis.sh

set -e

echo "================================================================"
echo "GROUP ANALYSIS PIPELINE - QUICK TEST"
echo "================================================================"
echo ""

# Configuration
SUBJECT_LEVEL="derivatives/connectivity-difumo256-hpc/subject-level"
METADATA="derivatives/connectivity-difumo256/participants.tsv"
GROUP_FILE="group.csv"
OUTPUT_DIR="test_group_analysis"
N_PERMUTATIONS=1000  # Reduced for speed

# Clean previous test
if [ -d "$OUTPUT_DIR" ]; then
    echo "Removing previous test results..."
    rm -rf "$OUTPUT_DIR"
fi

echo "Test configuration:"
echo "  Subject-level: $SUBJECT_LEVEL"
echo "  Metadata: $METADATA"
echo "  Group file: $GROUP_FILE"
echo "  Output: $OUTPUT_DIR"
echo "  Permutations: $N_PERMUTATIONS (reduced for testing)"
echo ""

# Check prerequisites
echo "Checking prerequisites..."

if [ ! -d "$SUBJECT_LEVEL/seed_based/motor_cortex" ]; then
    echo "ERROR: Motor cortex seed directory not found"
    echo "Expected: $SUBJECT_LEVEL/seed_based/motor_cortex"
    exit 1
fi

if [ ! -f "$METADATA" ]; then
    echo "ERROR: Metadata file not found: $METADATA"
    exit 1
fi

if [ ! -f "$GROUP_FILE" ]; then
    echo "ERROR: Group file not found: $GROUP_FILE"
    exit 1
fi

n_maps=$(ls "$SUBJECT_LEVEL/seed_based/motor_cortex"/*_zmap.nii.gz 2>/dev/null | wc -l)
echo "  Found $n_maps z-maps for motor_cortex"

if [ "$n_maps" -lt 10 ]; then
    echo "ERROR: Too few z-maps ($n_maps < 10)"
    exit 1
fi

echo "  Prerequisites OK"
echo ""

# Run voxelwise analysis
echo "================================================================"
echo "STEP 1: Voxelwise Whole-Brain Analysis (Motor Cortex)"
echo "================================================================"
echo ""

python script/group_level_analysis.py \
    --input-maps "$SUBJECT_LEVEL/seed_based/motor_cortex"/*_zmap.nii.gz \
    --metadata "$METADATA" \
    --group-file "$GROUP_FILE" \
    --output "$OUTPUT_DIR/seed_motor_cortex" \
    --cluster-threshold 0.05 \
    --n-permutations "$N_PERMUTATIONS" \
    --min-cluster-size 50

echo ""
echo "Step 1 complete."
echo ""

# Check results
echo "Checking voxelwise results..."

if [ ! -f "$OUTPUT_DIR/seed_motor_cortex/interaction_tstat_map.nii.gz" ]; then
    echo "ERROR: T-statistic map not created"
    exit 1
fi

if [ ! -f "$OUTPUT_DIR/seed_motor_cortex/correction_info.json" ]; then
    echo "ERROR: correction_info.json not created"
    exit 1
fi

echo "  T-statistic map: ✓"
echo "  Correction info: ✓"

# Show correction method
echo ""
echo "Correction method used:"
cat "$OUTPUT_DIR/seed_motor_cortex/correction_info.json"
echo ""

# Check for clusters
if [ -f "$OUTPUT_DIR/seed_motor_cortex/clusters_interaction.csv" ]; then
    n_clusters=$(tail -n +2 "$OUTPUT_DIR/seed_motor_cortex/clusters_interaction.csv" | wc -l)
    echo "Significant clusters found: $n_clusters"

    if [ "$n_clusters" -gt 0 ]; then
        echo ""
        echo "Cluster table:"
        head -6 "$OUTPUT_DIR/seed_motor_cortex/clusters_interaction.csv"
    fi
else
    echo "No significant clusters found (clusters_interaction.csv not created)"
    n_clusters=0
fi

echo ""

# Run barplots if clusters exist
if [ "$n_clusters" -gt 0 ]; then
    echo "================================================================"
    echo "STEP 2: Creating Cluster Barplots"
    echo "================================================================"
    echo ""

    # Find thresholded map
    thresholded_map=""
    if [ -f "$OUTPUT_DIR/seed_motor_cortex/interaction_fwe_p05.nii.gz" ]; then
        thresholded_map="$OUTPUT_DIR/seed_motor_cortex/interaction_fwe_p05.nii.gz"
    elif [ -f "$OUTPUT_DIR/seed_motor_cortex/interaction_uncorr_p0001_k50.nii.gz" ]; then
        thresholded_map="$OUTPUT_DIR/seed_motor_cortex/interaction_uncorr_p0001_k50.nii.gz"
    fi

    if [ -n "$thresholded_map" ]; then
        python script/create_cluster_barplots.py \
            --cluster-table "$OUTPUT_DIR/seed_motor_cortex/clusters_interaction.csv" \
            --thresholded-map "$thresholded_map" \
            --subject-maps "$SUBJECT_LEVEL/seed_based/motor_cortex"/*_zmap.nii.gz \
            --metadata "$METADATA" \
            --group-file "$GROUP_FILE" \
            --output "$OUTPUT_DIR/seed_motor_cortex/cluster_barplots" \
            --seed-name "Motor Cortex"

        echo ""
        echo "Cluster barplots created:"
        ls -1 "$OUTPUT_DIR/seed_motor_cortex/cluster_barplots"/*.png 2>/dev/null | wc -l
    else
        echo "ERROR: No thresholded map found for barplot creation"
    fi
else
    echo "Skipping barplots (no significant clusters)"
fi

echo ""

# Generate mini HTML report
echo "================================================================"
echo "STEP 3: Generating HTML Report"
echo "================================================================"
echo ""

python script/generate_html_report.py \
    --results-dir "$OUTPUT_DIR" \
    --output "$OUTPUT_DIR/test_report.html"

echo ""

# Summary
echo "================================================================"
echo "TEST COMPLETE"
echo "================================================================"
echo ""
echo "Results saved to: $OUTPUT_DIR/"
echo ""
echo "Files created:"
ls -lh "$OUTPUT_DIR/seed_motor_cortex"/ | grep -v "^d" | tail -n +2 || echo "  (none)"
echo ""

if [ -f "$OUTPUT_DIR/test_report.html" ]; then
    echo "HTML report: $OUTPUT_DIR/test_report.html"
    echo ""
    echo "To view:"
    echo "  xdg-open $OUTPUT_DIR/test_report.html"
else
    echo "WARNING: HTML report not created"
fi

echo ""
echo "To view brain images:"
if [ -f "$OUTPUT_DIR/seed_motor_cortex/thresholded_map_ortho.png" ]; then
    echo "  xdg-open $OUTPUT_DIR/seed_motor_cortex/thresholded_map_ortho.png"
fi
if [ -f "$OUTPUT_DIR/seed_motor_cortex/thresholded_map_mosaic.png" ]; then
    echo "  xdg-open $OUTPUT_DIR/seed_motor_cortex/thresholded_map_mosaic.png"
fi

echo ""
echo "To view cluster barplots:"
if [ -d "$OUTPUT_DIR/seed_motor_cortex/cluster_barplots" ]; then
    echo "  ls $OUTPUT_DIR/seed_motor_cortex/cluster_barplots/*.png"
fi

echo ""
echo "================================================================"
