#!/bin/bash
#
# Full Analysis with DiFuMo256 - BIDS-Derivatives Structure
# Uses existing scripts with proper output organization
#
# This is a simplified workflow that:
# 1. Uses existing analysis scripts (no modifications needed)
# 2. Organizes outputs into BIDS-Derivatives structure
# 3. Processes all 8 subjects (16 sessions)
#

set -e

PROJECT_DIR="/home/clivewong/proj/longevity"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
SCRIPT_DIR="$PROJECT_DIR/script"
ATLASES_DIR="$PROJECT_DIR/atlases"

# Output to derivatives
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
mkdir -p "$DERIVATIVE_ROOT"

echo "================================================================================"
echo "FULL CONNECTIVITY ANALYSIS - DiFuMo256"
echo "================================================================================"
echo ""
echo "Processing all available subjects with BIDS-Derivatives organization"
echo "Output: $DERIVATIVE_ROOT"
echo ""

# Generate dataset description
cat > "$DERIVATIVE_ROOT/dataset_description.json" << 'EOF'
{
    "Name": "Connectivity Analysis - DiFuMo256",
    "BIDSVersion": "1.9.0",
    "DatasetType": "derivative",
    "GeneratedBy": [
        {
            "Name": "custom-connectivity-pipeline",
            "Version": "2.0.0",
            "CodeURL": "script/"
        }
    ],
    "SourceDatasets": [
        {
            "URL": "fmriprep/",
            "Name": "fMRIPrep",
            "Version": "25.1.4"
        }
    ],
    "Atlas": {
        "Name": "DiFuMo256",
        "Dimension": 256
    },
    "AnalysisParameters": {
        "TR": 0.8,
        "Smoothing_FWHM": 6.0,
        "HighPass_Hz": 0.01,
        "LowPass_Hz": 0.1
    }
}
EOF

echo "✓ Created dataset_description.json"
echo ""

# =============================================================================
# STEP 1: PREPARE METADATA
# =============================================================================

echo "STEP 1: Prepare Metadata"
echo "--------------------------------------------------------------------------------"

METADATA_FILE="$DERIVATIVE_ROOT/participants.tsv"

python "$SCRIPT_DIR/prepare_metadata.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --group "$PROJECT_DIR/group.csv" \
    --output "$METADATA_FILE"

echo ""

# =============================================================================
# STEP 2: LOCAL MEASURES (Subject-Level)
# =============================================================================

echo "STEP 2: Local Measures (fALFF, ReHo)"
echo "--------------------------------------------------------------------------------"

LOCAL_DIR="$DERIVATIVE_ROOT/subject-level/local_measures"
mkdir -p "$LOCAL_DIR"

python "$SCRIPT_DIR/compute_local_measures.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --output "$LOCAL_DIR" \
    --measures fALFF ReHo \
    --tr 0.8

echo ""

# =============================================================================
# STEP 3: SEED-BASED CONNECTIVITY (Subject-Level)
# =============================================================================

echo "STEP 3: Seed-Based Connectivity"
echo "--------------------------------------------------------------------------------"

SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"
mkdir -p "$SEED_DIR"

python "$SCRIPT_DIR/seed_based_connectivity.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$ATLASES_DIR/motor_cerebellar_seeds.json" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --seed-names Motor_Cortex Cerebellar_Motor Cerebellar_Cognitive \
                  Hippocampus DLPFC_Coarse DLPFC_Dorsal DLPFC_Ventral \
                  Anterior_Insula dACC Insula_dACC_Combined \
                  Hippocampus_Anterior Hippocampus_Posterior

echo ""

# =============================================================================
# STEP 4: EXTRACT TIMESERIES (Subject-Level)
# =============================================================================

echo "STEP 4: Extract Timeseries"
echo "--------------------------------------------------------------------------------"

TIMESERIES_FILE="$DERIVATIVE_ROOT/subject-level/timeseries_difumo256.h5"

python "$SCRIPT_DIR/extract_timeseries.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --atlas difumo256 \
    --output "$TIMESERIES_FILE"

echo ""

# =============================================================================
# STEP 5: NETWORK CONNECTIVITY (Group-Level)
# =============================================================================

echo "STEP 5: Network Connectivity"
echo "--------------------------------------------------------------------------------"

NETWORK_DIR="$DERIVATIVE_ROOT/group-level/network_connectivity"
mkdir -p "$NETWORK_DIR"

# Within-network analyses
for NETWORK in SalienceVentralAttention DefaultMode FrontoParietal; do
    echo "  Within-network: $NETWORK"
    python "$SCRIPT_DIR/python_connectivity_analysis.py" \
        --timeseries "$TIMESERIES_FILE" \
        --metadata "$METADATA_FILE" \
        --networks "$ATLASES_DIR/difumo256_network_definitions.json" \
        --output "$NETWORK_DIR/within_${NETWORK}" \
        --within-network "$NETWORK" \
        --alpha 0.05
done

# Between-network analyses
echo "  Between-network: Salience ↔ Default Mode"
python "$SCRIPT_DIR/python_connectivity_analysis.py" \
    --timeseries "$TIMESERIES_FILE" \
    --metadata "$METADATA_FILE" \
    --networks "$ATLASES_DIR/difumo256_network_definitions.json" \
    --output "$NETWORK_DIR/between_Salience_DMN" \
    --between-networks SalienceVentralAttention DefaultMode \
    --alpha 0.05

echo "  Between-network: FrontoParietal ↔ Cerebellar_Cognitive"
python "$SCRIPT_DIR/python_connectivity_analysis.py" \
    --timeseries "$TIMESERIES_FILE" \
    --metadata "$METADATA_FILE" \
    --networks "$ATLASES_DIR/difumo256_network_definitions.json" \
    --output "$NETWORK_DIR/between_FrontoParietal_Cerebellar" \
    --between-networks FrontoParietal Cerebellar_Cognitive \
    --alpha 0.05

echo ""

# =============================================================================
# STEP 6: GROUP-LEVEL STATISTICAL ANALYSIS
# =============================================================================

echo "STEP 6: Group-Level Statistical Analysis"
echo "--------------------------------------------------------------------------------"

GROUP_DIR="$DERIVATIVE_ROOT/group-level"
mkdir -p "$GROUP_DIR"

# fALFF
echo "  Analyzing fALFF..."
python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$LOCAL_DIR"/*_fALFF.nii.gz \
    --metadata "$METADATA_FILE" \
    --output "$GROUP_DIR/fALFF" \
    --cluster-threshold 0.05 \
    --n-permutations 1000

# ReHo
echo "  Analyzing ReHo..."
python "$SCRIPT_DIR/group_level_analysis.py" \
    --input-maps "$LOCAL_DIR"/*_ReHo.nii.gz \
    --metadata "$METADATA_FILE" \
    --output "$GROUP_DIR/ReHo" \
    --cluster-threshold 0.05 \
    --n-permutations 1000

# Seed-based
SEEDS=(Motor_Cortex Cerebellar_Motor DLPFC_Coarse DLPFC_Dorsal DLPFC_Ventral \
       Anterior_Insula dACC Insula_dACC_Combined Hippocampus_Anterior Hippocampus_Posterior)

for SEED in "${SEEDS[@]}"; do
    SEED_LOWER=$(echo "$SEED" | tr '[:upper:]' '[:lower:]')
    SEED_PATTERN="$SEED_DIR/${SEED_LOWER}/*_zmap.nii.gz"

    if ls $SEED_PATTERN 1> /dev/null 2>&1; then
        echo "  Analyzing seed: $SEED"
        python "$SCRIPT_DIR/group_level_analysis.py" \
            --input-maps $SEED_PATTERN \
            --metadata "$METADATA_FILE" \
            --output "$GROUP_DIR/seed_${SEED}" \
            --cluster-threshold 0.05 \
            --n-permutations 1000
    fi
done

echo ""

# =============================================================================
# STEP 7: GENERATE HTML REPORT
# =============================================================================

echo "STEP 7: Generate HTML Report"
echo "--------------------------------------------------------------------------------"

REPORTS_DIR="$PROJECT_DIR/derivatives/reports"
mkdir -p "$REPORTS_DIR"

python "$SCRIPT_DIR/generate_html_report.py" \
    --results-dir "$DERIVATIVE_ROOT" \
    --output "$REPORTS_DIR/connectivity-difumo256_report.html"

echo ""

# =============================================================================
# COMPLETE
# =============================================================================

echo "================================================================================"
echo "ANALYSIS COMPLETE!"
echo "================================================================================"
echo ""
echo "Output directory: $DERIVATIVE_ROOT"
echo "  - Subject-level: $DERIVATIVE_ROOT/subject-level/"
echo "  - Group-level: $DERIVATIVE_ROOT/group-level/"
echo ""
echo "Report: $REPORTS_DIR/connectivity-difumo256_report.html"
echo ""
echo "To view:"
echo "  firefox $REPORTS_DIR/connectivity-difumo256_report.html"
echo ""
