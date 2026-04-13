#!/bin/bash
#
# Master Workflow: Subject-Level Connectivity Analysis
# Longitudinal Walking Intervention Study
#
# This script orchestrates all connectivity analysis modules:
# 1. Local measures (fALFF, ReHo)
# 2. Seed-based connectivity (extended seeds)
# 3. Network-based connectivity (within/between)
# 4. Group-level statistical analysis
# 5. Interactive HTML report generation
#
# Usage:
#   bash master_full_connectivity_workflow.sh [--test]
#   --test: Run on subset of data for testing
#

set -e  # Exit on error

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_DIR="/home/clivewong/proj/longevity"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
ATLASES_DIR="$PROJECT_DIR/atlases"
SCRIPT_DIR="$PROJECT_DIR/script"
RESULTS_DIR="$PROJECT_DIR/results"

# Input files
GROUP_FILE="$PROJECT_DIR/group.csv"
SEEDS_JSON="$ATLASES_DIR/motor_cerebellar_seeds.json"
NETWORKS_JSON="$ATLASES_DIR/difumo256_network_definitions.json"

# Output directories
LOCAL_MEASURES_DIR="$RESULTS_DIR/local_measures"
SEED_BASED_DIR="$RESULTS_DIR/seed_based"
NETWORK_CONN_DIR="$RESULTS_DIR/network_connectivity"
GROUP_ANALYSIS_DIR="$RESULTS_DIR/group_analysis"
REPORT_FILE="$RESULTS_DIR/connectivity_report.html"

# Subjects to process (all subjects if not in test mode)
ALL_SUBJECTS=(sub-033 sub-034 sub-035 sub-036 sub-037 sub-038 sub-039 sub-040)
TEST_SUBJECTS=(sub-033 sub-034)

# Check for test mode
TEST_MODE=false
if [[ "$1" == "--test" ]]; then
    TEST_MODE=true
    SUBJECTS=("${TEST_SUBJECTS[@]}")
    echo "TEST MODE: Processing subset of data"
else
    SUBJECTS=("${ALL_SUBJECTS[@]}")
    echo "FULL MODE: Processing all available data"
fi

# =============================================================================
# STEP 0: PREPARE METADATA
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 0: PREPARE METADATA"
echo "================================================================================"
echo ""

METADATA_FILE="$RESULTS_DIR/metadata.csv"

if [[ ! -f "$METADATA_FILE" ]]; then
    echo "Generating metadata.csv..."
    python "$SCRIPT_DIR/prepare_metadata.py" \
        --fmriprep "$FMRIPREP_DIR" \
        --group "$GROUP_FILE" \
        --output "$METADATA_FILE"
else
    echo "Metadata file already exists: $METADATA_FILE"
fi

# =============================================================================
# STEP 1: LOCAL MEASURES (fALFF, ReHo)
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 1: LOCAL MEASURES (fALFF, ReHo)"
echo "================================================================================"
echo ""

if $TEST_MODE; then
    echo "Computing fALFF and ReHo for test subjects..."
    python "$SCRIPT_DIR/compute_local_measures.py" \
        --fmriprep "$FMRIPREP_DIR" \
        --output "$LOCAL_MEASURES_DIR" \
        --measures fALFF ReHo \
        --subjects "${SUBJECTS[@]}" \
        --tr 0.8 \
        --low-freq 0.01 \
        --high-freq 0.1
else
    echo "Computing fALFF and ReHo for all subjects..."
    python "$SCRIPT_DIR/compute_local_measures.py" \
        --fmriprep "$FMRIPREP_DIR" \
        --output "$LOCAL_MEASURES_DIR" \
        --measures fALFF ReHo \
        --tr 0.8 \
        --low-freq 0.01 \
        --high-freq 0.1
fi

# =============================================================================
# STEP 2: SEED-BASED CONNECTIVITY (Extended Seeds)
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 2: SEED-BASED CONNECTIVITY"
echo "================================================================================"
echo ""

# List of seeds to analyze
SEED_NAMES=(
    "Motor_Cortex"
    "Cerebellar_Motor"
    "Cerebellar_Cognitive"
    "Hippocampus"
    "DLPFC_Coarse"
    "DLPFC_Dorsal"
    "DLPFC_Ventral"
    "Anterior_Insula"
    "dACC"
    "Insula_dACC_Combined"
    "Hippocampus_Anterior"
    "Hippocampus_Posterior"
)

echo "Computing seed-based connectivity for ${#SEED_NAMES[@]} seeds..."

if $TEST_MODE; then
    python "$SCRIPT_DIR/seed_based_connectivity.py" \
        --fmriprep "$FMRIPREP_DIR" \
        --seeds "$SEEDS_JSON" \
        --metadata "$METADATA_FILE" \
        --output "$SEED_BASED_DIR" \
        --seed-names "${SEED_NAMES[@]}" \
        --smoothing 6.0 \
        --high-pass 0.01 \
        --low-pass 0.1
else
    # Process all subjects
    python "$SCRIPT_DIR/seed_based_connectivity.py" \
        --fmriprep "$FMRIPREP_DIR" \
        --seeds "$SEEDS_JSON" \
        --metadata "$METADATA_FILE" \
        --output "$SEED_BASED_DIR" \
        --seed-names "${SEED_NAMES[@]}" \
        --smoothing 6.0 \
        --high-pass 0.01 \
        --low-pass 0.1
fi

# =============================================================================
# STEP 3: NETWORK-BASED CONNECTIVITY
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 3: NETWORK-BASED CONNECTIVITY"
echo "================================================================================"
echo ""

# First, extract timeseries if not already done
TIMESERIES_FILE="$RESULTS_DIR/timeseries_difumo256.h5"

if [[ ! -f "$TIMESERIES_FILE" ]]; then
    echo "Extracting DiFuMo 256 timeseries..."
    python "$SCRIPT_DIR/extract_timeseries.py" \
        --fmriprep "$FMRIPREP_DIR" \
        --atlas difumo256 \
        --output "$TIMESERIES_FILE"
else
    echo "Timeseries file already exists: $TIMESERIES_FILE"
fi

# Within-network connectivity
WITHIN_NETWORKS=(
    "SalienceVentralAttention"
    "DefaultMode"
    "FrontoParietal"
)

echo ""
echo "Computing within-network connectivity..."
for NETWORK in "${WITHIN_NETWORKS[@]}"; do
    echo "  Processing: $NETWORK"
    OUTPUT_DIR="$NETWORK_CONN_DIR/within_${NETWORK,,}"  # lowercase

    python "$SCRIPT_DIR/python_connectivity_analysis.py" \
        --timeseries "$TIMESERIES_FILE" \
        --metadata "$METADATA_FILE" \
        --networks "$NETWORKS_JSON" \
        --output "$OUTPUT_DIR" \
        --within-network "$NETWORK" \
        --alpha 0.05
done

# Between-network connectivity (key hypothesis-driven pairs)
BETWEEN_PAIRS=(
    "SalienceVentralAttention DefaultMode"
    "FrontoParietal Cerebellar_Cognitive"
    "Somatomotor Cerebellar_Motor"
)

echo ""
echo "Computing between-network connectivity..."
for PAIR in "${BETWEEN_PAIRS[@]}"; do
    read -ra NETS <<< "$PAIR"
    NET1="${NETS[0]}"
    NET2="${NETS[1]}"
    echo "  Processing: $NET1 ↔ $NET2"
    OUTPUT_DIR="$NETWORK_CONN_DIR/between_${NET1,,}_${NET2,,}"

    python "$SCRIPT_DIR/python_connectivity_analysis.py" \
        --timeseries "$TIMESERIES_FILE" \
        --metadata "$METADATA_FILE" \
        --networks "$NETWORKS_JSON" \
        --output "$OUTPUT_DIR" \
        --between-networks "$NET1" "$NET2" \
        --alpha 0.05
done

# =============================================================================
# STEP 4: GROUP-LEVEL STATISTICAL ANALYSIS
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 4: GROUP-LEVEL STATISTICAL ANALYSIS"
echo "================================================================================"
echo ""

# fALFF group analysis
echo "Analyzing fALFF..."
python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$LOCAL_MEASURES_DIR"/*_fALFF.nii.gz \
    --metadata "$METADATA_FILE" \
    --output "$GROUP_ANALYSIS_DIR/fALFF" \
    --cluster-threshold 0.05 \
    --n-permutations 1000 \
    --min-cluster-size 10

# ReHo group analysis
echo ""
echo "Analyzing ReHo..."
python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$LOCAL_MEASURES_DIR"/*_ReHo.nii.gz \
    --metadata "$METADATA_FILE" \
    --output "$GROUP_ANALYSIS_DIR/ReHo" \
    --cluster-threshold 0.05 \
    --n-permutations 1000 \
    --min-cluster-size 10

# Seed-based group analyses
echo ""
echo "Analyzing seed-based connectivity..."
for SEED_NAME in "${SEED_NAMES[@]}"; do
    SEED_DIR="$SEED_BASED_DIR/${SEED_NAME,,}"  # lowercase

    if [[ -d "$SEED_DIR" ]]; then
        echo "  Processing: $SEED_NAME"
        python "$SCRIPT_DIR/group_level_analysis.py" \
            --input-maps "$SEED_DIR"/*_zmap.nii.gz \
            --metadata "$METADATA_FILE" \
            --output "$GROUP_ANALYSIS_DIR/seed_${SEED_NAME,,}" \
            --cluster-threshold 0.05 \
            --n-permutations 1000 \
            --min-cluster-size 10
    else
        echo "  Skipping $SEED_NAME (directory not found)"
    fi
done

# =============================================================================
# STEP 5: GENERATE INTERACTIVE HTML REPORT
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 5: GENERATE INTERACTIVE HTML REPORT"
echo "================================================================================"
echo ""

python "$SCRIPT_DIR/generate_html_report.py" \
    --results-dir "$RESULTS_DIR" \
    --output "$REPORT_FILE"

# =============================================================================
# WORKFLOW COMPLETE
# =============================================================================

echo ""
echo "================================================================================"
echo "WORKFLOW COMPLETE"
echo "================================================================================"
echo ""
echo "Results directory: $RESULTS_DIR"
echo "Interactive report: $REPORT_FILE"
echo ""
echo "Summary:"
echo "  - Local measures: $LOCAL_MEASURES_DIR"
echo "  - Seed-based connectivity: $SEED_BASED_DIR"
echo "  - Network connectivity: $NETWORK_CONN_DIR"
echo "  - Group-level analyses: $GROUP_ANALYSIS_DIR"
echo ""
echo "To view the report, open in a browser:"
echo "  firefox $REPORT_FILE"
echo ""
