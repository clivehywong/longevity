#!/bin/bash
#
# Local Post-Processing After HPC Analysis
#
# Generates cluster barplots and HTML report from HPC results
# Runs locally - does not require HPC resources
#
# Usage:
#   bash script/local_postprocessing.sh
#

set -e

PROJECT_DIR="/home/clivewong/proj/longevity"
SUBJECT_LEVEL="${PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/subject-level"
GROUP_LEVEL="${PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/group-level"
METADATA="${PROJECT_DIR}/derivatives/connectivity-difumo256-hpc/participants_updated.tsv"
GROUP_FILE="${PROJECT_DIR}/group.csv"
REPORT_FILE="${GROUP_LEVEL}/group_analysis_report.html"

echo "================================================================"
echo "LOCAL POST-PROCESSING (AFTER HPC ANALYSIS)"
echo "================================================================"
echo "Group-level results: $GROUP_LEVEL"
echo "================================================================"
echo ""

# Check if HPC results exist
if [ ! -d "$GROUP_LEVEL" ]; then
    echo "ERROR: Group-level results not found"
    echo "Expected: $GROUP_LEVEL"
    echo ""
    echo "Did you download results from HPC?"
    echo "  bash script/hpc_download_group_results.sh"
    exit 1
fi

N_SEEDS=$(ls -d "$GROUP_LEVEL"/seed_*/ 2>/dev/null | wc -l)
if [ "$N_SEEDS" -eq 0 ]; then
    echo "ERROR: No seed results found in $GROUP_LEVEL"
    exit 1
fi

echo "Found $N_SEEDS seed analyses"
echo ""

# ================================================================
# PHASE 1: GENERATE CLUSTER BARPLOTS
# ================================================================

echo "================================================================"
echo "PHASE 1: GENERATING CLUSTER BARPLOTS"
echo "================================================================"
echo ""

TOTAL_CLUSTERS=0
SEEDS_WITH_CLUSTERS=0

for seed_dir in "$GROUP_LEVEL"/seed_*/; do
    seed_name=$(basename "$seed_dir" | sed 's/seed_//')
    cluster_table="$seed_dir/clusters_interaction.csv"

    if [ ! -f "$cluster_table" ]; then
        echo "Skipping $seed_name: No cluster table found"
        continue
    fi

    n_clusters=$(tail -n +2 "$cluster_table" | wc -l)
    if [ "$n_clusters" -eq 0 ]; then
        echo "Skipping $seed_name: No significant clusters"
        continue
    fi

    TOTAL_CLUSTERS=$((TOTAL_CLUSTERS + n_clusters))
    SEEDS_WITH_CLUSTERS=$((SEEDS_WITH_CLUSTERS + 1))

    echo "--------------------------------------------------------------"
    echo "Creating barplots: $seed_name ($n_clusters clusters)"
    echo "--------------------------------------------------------------"

    # Find thresholded map
    thresholded_map=""
    if [ -f "$seed_dir/interaction_fwe_p05.nii.gz" ]; then
        thresholded_map="$seed_dir/interaction_fwe_p05.nii.gz"
    elif [ -f "$seed_dir/interaction_uncorr_p0001_k50.nii.gz" ]; then
        thresholded_map="$seed_dir/interaction_uncorr_p0001_k50.nii.gz"
    else
        echo "WARNING: No thresholded map found for $seed_name, skipping"
        continue
    fi

    # Get seed-specific z-maps
    subject_maps_dir="${SUBJECT_LEVEL}/seed_based/${seed_name}"
    if [ ! -d "$subject_maps_dir" ]; then
        echo "WARNING: Subject maps not found: $subject_maps_dir"
        continue
    fi

    # Format seed name for display
    seed_display=$(echo "$seed_name" | sed 's/_/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2))}1')

    # Generate barplots
    python script/create_cluster_barplots.py \
        --cluster-table "$cluster_table" \
        --thresholded-map "$thresholded_map" \
        --subject-maps "$subject_maps_dir"/*_zmap.nii.gz \
        --metadata "$METADATA" \
        --group-file "$GROUP_FILE" \
        --output "$seed_dir/cluster_barplots" \
        --seed-name "$seed_display"

    n_barplots=$(ls "$seed_dir/cluster_barplots"/*.png 2>/dev/null | wc -l)
    echo "  Created $n_barplots barplots"
    echo ""
done

echo "================================================================"
echo "BARPLOT GENERATION COMPLETE"
echo "================================================================"
echo "Seeds with clusters: $SEEDS_WITH_CLUSTERS"
echo "Total clusters: $TOTAL_CLUSTERS"
echo "================================================================"
echo ""

# ================================================================
# PHASE 2: GENERATE HTML REPORT
# ================================================================

echo "================================================================"
echo "PHASE 2: GENERATING HTML REPORT"
echo "================================================================"
echo ""

python script/generate_html_report.py \
    --results-dir "$GROUP_LEVEL" \
    --output "$REPORT_FILE"

echo ""
echo "================================================================"
echo "POST-PROCESSING COMPLETE"
echo "================================================================"
echo ""
echo "Results summary:"
echo "  Seeds analyzed: $N_SEEDS"
echo "  Seeds with significant clusters: $SEEDS_WITH_CLUSTERS"
echo "  Total significant clusters: $TOTAL_CLUSTERS"
echo ""
echo "Output files:"
echo "  HTML report: $REPORT_FILE"
echo "  Group-level results: $GROUP_LEVEL"
echo ""
echo "To view report:"
echo "  xdg-open $REPORT_FILE"
echo ""

# Show seeds with results
echo "Seeds with significant results:"
for seed_dir in "$GROUP_LEVEL"/seed_*/; do
    seed_name=$(basename "$seed_dir" | sed 's/seed_//')

    if [ -f "$seed_dir/clusters_interaction.csv" ]; then
        n_clusters=$(tail -n +2 "$seed_dir/clusters_interaction.csv" | wc -l)
        if [ "$n_clusters" -gt 0 ]; then
            correction=$(cat "$seed_dir/correction_info.json" 2>/dev/null | grep -o '"method"[^,]*' | cut -d'"' -f4 || echo "unknown")
            echo "  ✓ $seed_name: $n_clusters clusters ($correction)"
        fi
    fi
done

echo ""
echo "================================================================"
