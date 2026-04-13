#!/bin/bash
#
# Master Workflow: Subject-Level Connectivity Analysis (v2 - BIDS-Derivatives)
# Longitudinal Walking Intervention Study
#
# NEW: Atlas-specific organization with subject-level and group-level separation
#
# Usage:
#   bash master_full_connectivity_workflow_v2.sh [--test] [--atlas ATLAS_NAME]
#   --test: Run on subset of data for testing
#   --atlas: Specify atlas (default: difumo256)
#

set -e  # Exit on error

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_DIR="/home/clivewong/proj/longevity"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
ATLASES_DIR="$PROJECT_DIR/atlases"
SCRIPT_DIR="$PROJECT_DIR/script"

# Parse arguments
TEST_MODE=false
ATLAS="difumo256"

while [[ $# -gt 0 ]]; do
    case $1 in
        --test)
            TEST_MODE=true
            shift
            ;;
        --atlas)
            ATLAS="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--test] [--atlas ATLAS_NAME]"
            exit 1
            ;;
    esac
done

# Atlas-specific derivative directory (BIDS-Derivatives structure)
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-${ATLAS}"
GROUP_DIR="$DERIVATIVE_ROOT/group"
REPORTS_DIR="$PROJECT_DIR/derivatives/reports"

# Input files
GROUP_FILE="$PROJECT_DIR/group.csv"

# Atlas-specific files
if [[ "$ATLAS" == "difumo256" ]]; then
    SEEDS_JSON="$ATLASES_DIR/motor_cerebellar_seeds.json"
    NETWORKS_JSON="$ATLASES_DIR/difumo256_network_definitions.json"
    ATLAS_FILE="$ATLASES_DIR/difumo256_4D.nii"
elif [[ "$ATLAS" == "schaefer400" ]]; then
    SEEDS_JSON="$ATLASES_DIR/schaefer400_seeds.json"  # To be created
    NETWORKS_JSON="$ATLASES_DIR/schaefer400_7net_network_definitions.json"
    ATLAS_FILE="$ATLASES_DIR/schaefer400_7net.nii"
else
    echo "Error: Unknown atlas '$ATLAS'"
    echo "Supported: difumo256, schaefer400"
    exit 1
fi

# Verify atlas files exist
if [[ ! -f "$NETWORKS_JSON" ]]; then
    echo "Error: Network definitions not found: $NETWORKS_JSON"
    exit 1
fi

# Subjects to process
ALL_SUBJECTS=(sub-033 sub-034 sub-035 sub-036 sub-037 sub-038 sub-039 sub-040)
TEST_SUBJECTS=(sub-033 sub-034)

if $TEST_MODE; then
    SUBJECTS=("${TEST_SUBJECTS[@]}")
    echo "TEST MODE: Processing subset of data with atlas: $ATLAS"
else
    SUBJECTS=("${ALL_SUBJECTS[@]}")
    echo "FULL MODE: Processing all available data with atlas: $ATLAS"
fi

# Create directory structure
mkdir -p "$DERIVATIVE_ROOT"
mkdir -p "$GROUP_DIR"
mkdir -p "$REPORTS_DIR"

# =============================================================================
# GENERATE DATASET DESCRIPTION
# =============================================================================

DATASET_DESC="$DERIVATIVE_ROOT/dataset_description.json"

if [[ ! -f "$DATASET_DESC" ]]; then
    echo "Generating dataset_description.json..."
    cat > "$DATASET_DESC" << EOF
{
    "Name": "Connectivity Analysis - ${ATLAS}",
    "BIDSVersion": "1.9.0",
    "DatasetType": "derivative",
    "GeneratedBy": [
        {
            "Name": "custom-connectivity-pipeline",
            "Version": "2.0.0",
            "Description": "Subject-level connectivity analysis pipeline",
            "CodeURL": "$SCRIPT_DIR"
        }
    ],
    "SourceDatasets": [
        {
            "URL": "$FMRIPREP_DIR",
            "Name": "fMRIPrep",
            "Version": "25.1.4"
        }
    ],
    "Atlas": {
        "Name": "$ATLAS",
        "File": "$ATLAS_FILE"
    },
    "AnalysisParameters": {
        "TR": 0.8,
        "Smoothing_FWHM": 6.0,
        "HighPass_Hz": 0.01,
        "LowPass_Hz": 0.1,
        "ConfoundStrategy": "6motion+CSF+WM",
        "StatisticalModel": "value ~ Group * Time + Age + Sex + MeanFD + (1|Subject)"
    }
}
EOF
fi

# =============================================================================
# STEP 0: PREPARE METADATA
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 0: PREPARE METADATA"
echo "================================================================================"
echo ""

METADATA_FILE="$DERIVATIVE_ROOT/participants.tsv"

if [[ ! -f "$METADATA_FILE" ]]; then
    echo "Generating participants.tsv..."
    python "$SCRIPT_DIR/prepare_metadata.py" \
        --fmriprep "$FMRIPREP_DIR" \
        --group "$GROUP_FILE" \
        --output "$METADATA_FILE"
else
    echo "Metadata file already exists: $METADATA_FILE"
fi

# =============================================================================
# STEP 1: LOCAL MEASURES (fALFF, ReHo) - SUBJECT-LEVEL
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 1: LOCAL MEASURES (fALFF, ReHo) - Subject-Level"
echo "================================================================================"
echo ""

for SUBJECT in "${SUBJECTS[@]}"; do
    echo "Processing $SUBJECT..."

    # Create subject directory structure
    SUBJECT_DIR="$DERIVATIVE_ROOT/$SUBJECT"
    mkdir -p "$SUBJECT_DIR"

    # Process each session
    for SESSION_DIR in "$FMRIPREP_DIR/$SUBJECT"/ses-*/func; do
        if [[ ! -d "$SESSION_DIR" ]]; then
            continue
        fi

        SESSION=$(basename $(dirname "$SESSION_DIR"))
        OUTPUT_SESSION_DIR="$SUBJECT_DIR/$SESSION/func"
        mkdir -p "$OUTPUT_SESSION_DIR"

        echo "  $SESSION..."

        # Compute local measures
        python "$SCRIPT_DIR/compute_local_measures.py" \
            --fmriprep "$FMRIPREP_DIR" \
            --output "$OUTPUT_SESSION_DIR" \
            --measures fALFF ReHo \
            --subjects "$SUBJECT" \
            --sessions "$SESSION" \
            --tr 0.8 \
            --bids-naming \
            --space MNI152NLin2009cAsym
    done
done

# =============================================================================
# STEP 2: SEED-BASED CONNECTIVITY - SUBJECT-LEVEL
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 2: SEED-BASED CONNECTIVITY - Subject-Level"
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

if [[ -f "$SEEDS_JSON" ]]; then
    echo "Computing seed-based connectivity for ${#SEED_NAMES[@]} seeds..."

    for SUBJECT in "${SUBJECTS[@]}"; do
        echo "Processing $SUBJECT..."

        for SESSION_DIR in "$FMRIPREP_DIR/$SUBJECT"/ses-*/func; do
            if [[ ! -d "$SESSION_DIR" ]]; then
                continue
            fi

            SESSION=$(basename $(dirname "$SESSION_DIR"))
            OUTPUT_SESSION_DIR="$DERIVATIVE_ROOT/$SUBJECT/$SESSION/func"
            mkdir -p "$OUTPUT_SESSION_DIR"

            echo "  $SESSION - computing connectivity..."

            python "$SCRIPT_DIR/seed_based_connectivity.py" \
                --fmriprep "$FMRIPREP_DIR" \
                --seeds "$SEEDS_JSON" \
                --metadata "$METADATA_FILE" \
                --output "$OUTPUT_SESSION_DIR" \
                --subject "$SUBJECT" \
                --session "$SESSION" \
                --seed-names "${SEED_NAMES[@]}" \
                --atlas "$ATLAS" \
                --bids-naming
        done
    done
else
    echo "Skipping seed-based connectivity (seeds file not found: $SEEDS_JSON)"
fi

# =============================================================================
# STEP 3: EXTRACT TIMESERIES & NETWORK CONNECTIVITY - SUBJECT-LEVEL
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 3: ROI TIMESERIES EXTRACTION - Subject-Level"
echo "================================================================================"
echo ""

for SUBJECT in "${SUBJECTS[@]}"; do
    echo "Processing $SUBJECT..."

    for SESSION_DIR in "$FMRIPREP_DIR/$SUBJECT"/ses-*/func; do
        if [[ ! -d "$SESSION_DIR" ]]; then
            continue
        fi

        SESSION=$(basename $(dirname "$SESSION_DIR"))
        OUTPUT_SESSION_DIR="$DERIVATIVE_ROOT/$SUBJECT/$SESSION/connectivity"
        mkdir -p "$OUTPUT_SESSION_DIR"

        echo "  $SESSION - extracting timeseries..."

        python "$SCRIPT_DIR/extract_timeseries.py" \
            --fmriprep "$FMRIPREP_DIR" \
            --atlas "$ATLAS" \
            --subject "$SUBJECT" \
            --session "$SESSION" \
            --output "$OUTPUT_SESSION_DIR/${SUBJECT}_${SESSION}_atlas-${ATLAS}_timeseries.tsv"
    done
done

# =============================================================================
# STEP 4: GROUP-LEVEL ANALYSIS
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 4: GROUP-LEVEL STATISTICAL ANALYSIS"
echo "================================================================================"
echo ""

# Collect all subject-level maps for group analysis

# fALFF group analysis
echo "Analyzing fALFF (group-level)..."
GROUP_FALFF_DIR="$GROUP_DIR/fALFF"
mkdir -p "$GROUP_FALFF_DIR"

python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$DERIVATIVE_ROOT"/sub-*/ses-*/func/*_desc-fALFF_bold.nii.gz \
    --metadata "$METADATA_FILE" \
    --output "$GROUP_FALFF_DIR" \
    --cluster-threshold 0.05 \
    --n-permutations 1000 \
    --min-cluster-size 10

# ReHo group analysis
echo ""
echo "Analyzing ReHo (group-level)..."
GROUP_REHO_DIR="$GROUP_DIR/ReHo"
mkdir -p "$GROUP_REHO_DIR"

python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$DERIVATIVE_ROOT"/sub-*/ses-*/func/*_desc-ReHo_bold.nii.gz \
    --metadata "$METADATA_FILE" \
    --output "$GROUP_REHO_DIR" \
    --cluster-threshold 0.05 \
    --n-permutations 1000 \
    --min-cluster-size 10

# Seed-based group analyses
echo ""
echo "Analyzing seed-based connectivity (group-level)..."
for SEED_NAME in "${SEED_NAMES[@]}"; do
    SEED_PATTERN="*_seed-${SEED_NAME}_connectome.nii.gz"

    # Check if any maps exist
    if ls "$DERIVATIVE_ROOT"/sub-*/ses-*/func/$SEED_PATTERN 1> /dev/null 2>&1; then
        echo "  Processing seed: $SEED_NAME"
        GROUP_SEED_DIR="$GROUP_DIR/seed-${SEED_NAME}"
        mkdir -p "$GROUP_SEED_DIR"

        python "$SCRIPT_DIR/group_level_analysis.py" \
            --input-maps "$DERIVATIVE_ROOT"/sub-*/ses-*/func/$SEED_PATTERN \
            --metadata "$METADATA_FILE" \
            --output "$GROUP_SEED_DIR" \
            --cluster-threshold 0.05 \
            --n-permutations 1000 \
            --min-cluster-size 10
    else
        echo "  Skipping $SEED_NAME (no maps found)"
    fi
done

# Network connectivity analyses
echo ""
echo "Analyzing network connectivity (group-level)..."

# Collect all timeseries into single file for network analysis
COMBINED_TIMESERIES="$DERIVATIVE_ROOT/group/timeseries_combined.h5"
python "$SCRIPT_DIR/combine_timeseries.py" \
    --input-pattern "$DERIVATIVE_ROOT/sub-*/ses-*/connectivity/*_timeseries.tsv" \
    --output "$COMBINED_TIMESERIES"

# Within-network connectivity
WITHIN_NETWORKS=(
    "SalienceVentralAttention"
    "DefaultMode"
    "FrontoParietal"
)

for NETWORK in "${WITHIN_NETWORKS[@]}"; do
    echo "  Within-network: $NETWORK"
    OUTPUT_DIR="$GROUP_DIR/network-within${NETWORK}"
    mkdir -p "$OUTPUT_DIR"

    python "$SCRIPT_DIR/python_connectivity_analysis.py" \
        --timeseries "$COMBINED_TIMESERIES" \
        --metadata "$METADATA_FILE" \
        --networks "$NETWORKS_JSON" \
        --output "$OUTPUT_DIR" \
        --within-network "$NETWORK" \
        --alpha 0.05
done

# Between-network connectivity
BETWEEN_PAIRS=(
    "SalienceVentralAttention DefaultMode"
    "FrontoParietal Cerebellar_Cognitive"
    "Somatomotor Cerebellar_Motor"
)

for PAIR in "${BETWEEN_PAIRS[@]}"; do
    read -ra NETS <<< "$PAIR"
    NET1="${NETS[0]}"
    NET2="${NETS[1]}"
    echo "  Between-network: $NET1 ↔ $NET2"
    OUTPUT_DIR="$GROUP_DIR/network-between${NET1}${NET2}"
    mkdir -p "$OUTPUT_DIR"

    python "$SCRIPT_DIR/python_connectivity_analysis.py" \
        --timeseries "$COMBINED_TIMESERIES" \
        --metadata "$METADATA_FILE" \
        --networks "$NETWORKS_JSON" \
        --output "$OUTPUT_DIR" \
        --between-networks "$NET1" "$NET2" \
        --alpha 0.05
done

# =============================================================================
# STEP 5: GENERATE INTERACTIVE HTML REPORT
# =============================================================================

echo ""
echo "================================================================================"
echo "STEP 5: GENERATE INTERACTIVE HTML REPORT"
echo "================================================================================"
echo ""

REPORT_FILE="$REPORTS_DIR/connectivity-${ATLAS}_report.html"

python "$SCRIPT_DIR/generate_html_report.py" \
    --results-dir "$DERIVATIVE_ROOT" \
    --atlas "$ATLAS" \
    --output "$REPORT_FILE"

# =============================================================================
# WORKFLOW COMPLETE
# =============================================================================

echo ""
echo "================================================================================"
echo "WORKFLOW COMPLETE"
echo "================================================================================"
echo ""
echo "Atlas: $ATLAS"
echo "Derivative directory: $DERIVATIVE_ROOT"
echo "  - Subject-level: $DERIVATIVE_ROOT/sub-*/"
echo "  - Group-level: $GROUP_DIR/"
echo "Interactive report: $REPORT_FILE"
echo ""
echo "Dataset description: $DATASET_DESC"
echo "Metadata: $METADATA_FILE"
echo ""
echo "To view the report:"
echo "  firefox $REPORT_FILE"
echo ""
