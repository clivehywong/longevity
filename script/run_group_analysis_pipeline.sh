#!/usr/bin/env bash
#
# Master Pipeline for Group-Level Connectivity Analysis
#
# Orchestrates:
# 1. Voxelwise analysis for all 12 seeds (with fallback to uncorrected)
# 2. Cluster barplots for significant clusters
# 3. Network connectivity analyses (within/between networks)
# 4. Connectivity matrices with significance
# 5. Network connection barplots
# 6. Comprehensive HTML report
#
# Usage:
#   bash script/run_group_analysis_pipeline.sh \
#       --subject-level derivatives/connectivity-difumo256-hpc/subject-level \
#       --metadata derivatives/connectivity-difumo256/participants.tsv \
#       --group-file group.csv \
#       --output derivatives/connectivity-difumo256-hpc/group-level \
#       --report derivatives/connectivity-difumo256-hpc/group_analysis_report.html
#
# Options:
#   --skip-voxelwise    Skip voxelwise analyses (if already run)
#   --skip-network      Skip network analyses
#   --skip-barplots     Skip barplot generation
#   --skip-report       Skip HTML report generation
#   --seeds             Space-separated list of seeds to analyze (default: all 12)

set -e  # Exit on error

# Default values
SUBJECT_LEVEL=""
METADATA=""
GROUP_FILE=""
OUTPUT_DIR=""
REPORT_FILE=""
SKIP_VOXELWISE=false
SKIP_NETWORK=false
SKIP_BARPLOTS=false
SKIP_REPORT=false
N_PERMUTATIONS=5000
CLUSTER_THRESHOLD=0.05

# All 12 seeds
ALL_SEEDS=(
    "motor_cortex"
    "cerebellar_motor"
    "cerebellar_cognitive"
    "hippocampus"
    "dlpfc_coarse"
    "dlpfc_dorsal"
    "dlpfc_ventral"
    "anterior_insula"
    "dacc"
    "insula_dacc_combined"
    "hippocampus_anterior"
    "hippocampus_posterior"
)

SEEDS=("${ALL_SEEDS[@]}")  # Default: all seeds

# Networks to analyze
WITHIN_NETWORKS=(
    "SalienceVentralAttention"
    "FrontoParietal"
    "DefaultMode"
    "Somatomotor"
)

BETWEEN_NETWORK_PAIRS=(
    "FrontoParietal:Somatomotor"
    "FrontoParietal:Cerebellar_Cognitive"
    "DefaultMode:Cerebellar_Cognitive"
)

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --subject-level)
            SUBJECT_LEVEL="$2"
            shift 2
            ;;
        --metadata)
            METADATA="$2"
            shift 2
            ;;
        --group-file)
            GROUP_FILE="$2"
            shift 2
            ;;
        --output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --report)
            REPORT_FILE="$2"
            shift 2
            ;;
        --skip-voxelwise)
            SKIP_VOXELWISE=true
            shift
            ;;
        --skip-network)
            SKIP_NETWORK=true
            shift
            ;;
        --skip-barplots)
            SKIP_BARPLOTS=true
            shift
            ;;
        --skip-report)
            SKIP_REPORT=true
            shift
            ;;
        --seeds)
            shift
            SEEDS=()
            while [[ $# -gt 0 ]] && [[ ! $1 =~ ^-- ]]; do
                SEEDS+=("$1")
                shift
            done
            ;;
        --n-permutations)
            N_PERMUTATIONS="$2"
            shift 2
            ;;
        *)
            echo "Unknown argument: $1"
            exit 1
            ;;
    esac
done

# Validate required arguments
if [[ -z "$SUBJECT_LEVEL" ]] || [[ -z "$METADATA" ]] || [[ -z "$OUTPUT_DIR" ]]; then
    echo "Usage: $0 --subject-level DIR --metadata FILE --output DIR [OPTIONS]"
    echo ""
    echo "Required:"
    echo "  --subject-level DIR    Subject-level results directory"
    echo "  --metadata FILE        Metadata TSV/CSV file"
    echo "  --output DIR           Output directory for group-level results"
    echo ""
    echo "Optional:"
    echo "  --group-file FILE      Group assignments CSV (subject_id, group)"
    echo "  --report FILE          HTML report output path"
    echo "  --skip-voxelwise       Skip voxelwise analyses"
    echo "  --skip-network         Skip network connectivity analyses"
    echo "  --skip-barplots        Skip barplot generation"
    echo "  --skip-report          Skip HTML report generation"
    echo "  --seeds LIST           Space-separated list of seeds to analyze"
    echo "  --n-permutations N     Number of permutations (default: 5000)"
    exit 1
fi

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Determine report file
if [[ -z "$REPORT_FILE" ]]; then
    REPORT_FILE="$OUTPUT_DIR/group_analysis_report.html"
fi

echo "================================================================"
echo "GROUP-LEVEL CONNECTIVITY ANALYSIS PIPELINE"
echo "================================================================"
echo "Subject-level results: $SUBJECT_LEVEL"
echo "Metadata: $METADATA"
echo "Group file: ${GROUP_FILE:-None}"
echo "Output directory: $OUTPUT_DIR"
echo "Report file: $REPORT_FILE"
echo "Seeds to analyze: ${SEEDS[@]}"
echo "================================================================"
echo ""

# ===============================================================
# PHASE 1: VOXELWISE ANALYSIS FOR ALL SEEDS
# ===============================================================

if [ "$SKIP_VOXELWISE" = false ]; then
    echo ""
    echo "================================================================"
    echo "PHASE 1: VOXELWISE WHOLE-BRAIN ANALYSIS"
    echo "================================================================"
    echo ""

    for seed in "${SEEDS[@]}"; do
        echo "--------------------------------------------------------------"
        echo "Analyzing seed: $seed"
        echo "--------------------------------------------------------------"

        seed_dir="$SUBJECT_LEVEL/seed_based/$seed"
        output_seed_dir="$OUTPUT_DIR/seed_${seed}"

        if [ ! -d "$seed_dir" ]; then
            echo "Warning: Seed directory not found: $seed_dir"
            echo "Skipping $seed"
            continue
        fi

        # Count z-maps
        n_maps=$(ls "$seed_dir"/*_zmap.nii.gz 2>/dev/null | wc -l)
        echo "Found $n_maps z-maps in $seed_dir"

        if [ "$n_maps" -lt 10 ]; then
            echo "Warning: Too few maps for group analysis ($n_maps < 10)"
            echo "Skipping $seed"
            continue
        fi

        # Run group-level analysis
        group_file_arg=""
        if [ -n "$GROUP_FILE" ]; then
            group_file_arg="--group-file $GROUP_FILE"
        fi

        python script/group_level_analysis.py \
            --input-maps "$seed_dir"/*_zmap.nii.gz \
            --metadata "$METADATA" \
            $group_file_arg \
            --output "$output_seed_dir" \
            --cluster-threshold "$CLUSTER_THRESHOLD" \
            --n-permutations "$N_PERMUTATIONS" \
            --min-cluster-size 50

        echo ""
    done

    echo "================================================================"
    echo "PHASE 1 COMPLETE: Voxelwise analyses done"
    echo "================================================================"
    echo ""
else
    echo "Skipping voxelwise analyses (--skip-voxelwise)"
fi

# ===============================================================
# PHASE 2: CREATE CLUSTER BARPLOTS
# ===============================================================

if [ "$SKIP_BARPLOTS" = false ]; then
    echo ""
    echo "================================================================"
    echo "PHASE 2: GENERATING CLUSTER BARPLOTS"
    echo "================================================================"
    echo ""

    for seed in "${SEEDS[@]}"; do
        seed_dir="$SUBJECT_LEVEL/seed_based/$seed"
        output_seed_dir="$OUTPUT_DIR/seed_${seed}"
        cluster_table="$output_seed_dir/clusters_interaction.csv"

        if [ ! -f "$cluster_table" ]; then
            echo "No cluster table for $seed, skipping barplots"
            continue
        fi

        # Count clusters
        n_clusters=$(tail -n +2 "$cluster_table" | wc -l)
        if [ "$n_clusters" -eq 0 ]; then
            echo "No significant clusters for $seed, skipping barplots"
            continue
        fi

        echo "Creating barplots for $seed ($n_clusters clusters)"

        # Find thresholded map (FWE or uncorrected)
        thresholded_map=""
        if [ -f "$output_seed_dir/interaction_fwe_p05.nii.gz" ]; then
            thresholded_map="$output_seed_dir/interaction_fwe_p05.nii.gz"
        elif [ -f "$output_seed_dir/interaction_uncorr_p0001_k50.nii.gz" ]; then
            thresholded_map="$output_seed_dir/interaction_uncorr_p0001_k50.nii.gz"
        else
            echo "Warning: No thresholded map found for $seed"
            continue
        fi

        # Prepare seed name for title
        seed_name=$(echo "$seed" | sed 's/_/ /g' | awk '{for(i=1;i<=NF;i++) $i=toupper(substr($i,1,1)) tolower(substr($i,2))}1')

        group_file_arg=""
        if [ -n "$GROUP_FILE" ]; then
            group_file_arg="--group-file $GROUP_FILE"
        fi

        python script/create_cluster_barplots.py \
            --cluster-table "$cluster_table" \
            --thresholded-map "$thresholded_map" \
            --subject-maps "$seed_dir"/*_zmap.nii.gz \
            --metadata "$METADATA" \
            $group_file_arg \
            --output "$output_seed_dir/cluster_barplots" \
            --seed-name "$seed_name"

        echo ""
    done

    echo "================================================================"
    echo "PHASE 2 COMPLETE: Cluster barplots created"
    echo "================================================================"
    echo ""
else
    echo "Skipping barplot generation (--skip-barplots)"
fi

# ===============================================================
# PHASE 3: NETWORK CONNECTIVITY ANALYSES
# ===============================================================

if [ "$SKIP_NETWORK" = false ]; then
    echo ""
    echo "================================================================"
    echo "PHASE 3: NETWORK CONNECTIVITY ANALYSES"
    echo "================================================================"
    echo ""

    # Check if timeseries file exists
    timeseries_file="$OUTPUT_DIR/../timeseries_difumo256.h5"
    if [ ! -f "$timeseries_file" ]; then
        echo "Timeseries file not found: $timeseries_file"
        echo "Skipping network connectivity analyses"
        echo "Please run timeseries extraction first"
    else
        network_defs="atlases/difumo256_network_definitions.json"

        # Within-network connectivity
        echo "--------------------------------------------------------------"
        echo "Within-Network Connectivity"
        echo "--------------------------------------------------------------"

        for network in "${WITHIN_NETWORKS[@]}"; do
            echo "Analyzing within-network: $network"

            output_network_dir="$OUTPUT_DIR/network_within_${network,,}"

            group_file_arg=""
            if [ -n "$GROUP_FILE" ]; then
                group_file_arg="--group-file $GROUP_FILE"
            fi

            python script/python_connectivity_analysis.py \
                --timeseries "$timeseries_file" \
                --metadata "$METADATA" \
                $group_file_arg \
                --networks "$network_defs" \
                --output "$output_network_dir" \
                --within-network "$network"

            echo ""
        done

        # Between-network connectivity
        echo "--------------------------------------------------------------"
        echo "Between-Network Connectivity"
        echo "--------------------------------------------------------------"

        for pair in "${BETWEEN_NETWORK_PAIRS[@]}"; do
            IFS=':' read -r net1 net2 <<< "$pair"
            echo "Analyzing between-networks: $net1 <-> $net2"

            output_network_dir="$OUTPUT_DIR/network_between_${net1,,}_${net2,,}"

            group_file_arg=""
            if [ -n "$GROUP_FILE" ]; then
                group_file_arg="--group-file $GROUP_FILE"
            fi

            python script/python_connectivity_analysis.py \
                --timeseries "$timeseries_file" \
                --metadata "$METADATA" \
                $group_file_arg \
                --networks "$network_defs" \
                --output "$output_network_dir" \
                --between-networks "$net1" "$net2"

            echo ""
        done

        echo "================================================================"
        echo "PHASE 3 COMPLETE: Network connectivity analyses done"
        echo "================================================================"
        echo ""
    fi
else
    echo "Skipping network connectivity analyses (--skip-network)"
fi

# ===============================================================
# PHASE 4: GENERATE HTML REPORT
# ===============================================================

if [ "$SKIP_REPORT" = false ]; then
    echo ""
    echo "================================================================"
    echo "PHASE 4: GENERATING HTML REPORT"
    echo "================================================================"
    echo ""

    python script/generate_html_report.py \
        --results-dir "$OUTPUT_DIR" \
        --output "$REPORT_FILE"

    echo ""
    echo "================================================================"
    echo "PIPELINE COMPLETE"
    echo "================================================================"
    echo ""
    echo "Results saved to: $OUTPUT_DIR"
    echo "HTML report: $REPORT_FILE"
    echo ""
    echo "To view report:"
    echo "  xdg-open $REPORT_FILE"
    echo ""
else
    echo "Skipping HTML report generation (--skip-report)"
fi
