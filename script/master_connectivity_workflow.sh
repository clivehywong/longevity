#!/bin/bash
# Master Connectivity Analysis Workflow
#
# This script orchestrates the complete Phase 2 connectivity analysis pipeline:
# 1. Extract ROI timeseries from fMRIPrep outputs (3 atlases)
# 2. Prepare metadata (group, demographics, motion)
# 3. Convert timeseries to HDF5 format
# 4. Run seed-based connectivity analysis
# 5. Run ROI-to-ROI connectivity analysis (hypothesis-driven + exploratory)
# 6. Generate publication-quality visualizations
#
# Usage:
#   bash master_connectivity_workflow.sh [--skip-extraction] [--skip-seed-based]
#
# Options:
#   --skip-extraction   Skip timeseries extraction (if already done)
#   --skip-seed-based   Skip seed-based analysis (ROI-to-ROI only)
#   --help              Show this help message

set -e

# Configuration
PROJECT_DIR="/home/clivewong/proj/longevity"
FMRIPREP_DIR="${PROJECT_DIR}/fmriprep"
TIMESERIES_DIR="${PROJECT_DIR}/timeseries"
RESULTS_DIR="${PROJECT_DIR}/results"
FIGURES_DIR="${PROJECT_DIR}/figures"
SCRIPT_DIR="${PROJECT_DIR}/script"
ATLAS_DIR="${PROJECT_DIR}/atlases"

# Parse arguments
SKIP_EXTRACTION=0
SKIP_SEED_BASED=0

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-extraction)
            SKIP_EXTRACTION=1
            shift
            ;;
        --skip-seed-based)
            SKIP_SEED_BASED=1
            shift
            ;;
        --help)
            head -n 20 "$0" | tail -n +2 | sed 's/^# //'
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Run with --help for usage information"
            exit 1
            ;;
    esac
done

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] WARNING:${NC} $1"; }
error() { echo -e "${RED}[$(date '+%H:%M:%S')] ERROR:${NC} $1"; exit 1; }
section() { echo -e "\n${BLUE}========================================${NC}\n${BLUE}$1${NC}\n${BLUE}========================================${NC}"; }

cd "$PROJECT_DIR"

section "MASTER CONNECTIVITY ANALYSIS WORKFLOW"
log "Project directory: $PROJECT_DIR"
log "Start time: $(date)"

# Check prerequisites
section "Step 0: Checking Prerequisites"

# Check fMRIPrep outputs
if [ ! -d "$FMRIPREP_DIR" ]; then
    error "fMRIPrep directory not found: $FMRIPREP_DIR"
fi

n_bold=$(find "$FMRIPREP_DIR" -name "*_space-MNI152NLin2009cAsym_desc-preproc_bold.nii.gz" 2>/dev/null | wc -l)
log "Found $n_bold preprocessed BOLD files"

if [ "$n_bold" -eq 0 ]; then
    error "No fMRIPrep outputs found. Has preprocessing completed?"
fi

# Check Python packages
log "Checking Python dependencies..."
python3 -c "import nibabel, nilearn, pandas, numpy, scipy, statsmodels, h5py, matplotlib, seaborn, networkx" 2>/dev/null || {
    warn "Some Python packages are missing"
    log "Installing required packages..."
    pip install nibabel nilearn pandas numpy scipy statsmodels h5py matplotlib seaborn networkx
}

log "✓ All prerequisites satisfied"

# Step 1: Extract timeseries
if [ $SKIP_EXTRACTION -eq 0 ]; then
    section "Step 1: Extracting ROI Timeseries"

    log "Extracting timeseries for 3 atlases (DiFuMo 256, Schaefer 400, Schaefer 200)..."
    bash "${SCRIPT_DIR}/extract_timeseries_linux.sh" "$FMRIPREP_DIR" "$TIMESERIES_DIR"

    if [ $? -ne 0 ]; then
        error "Timeseries extraction failed"
    fi

    log "✓ Timeseries extraction complete"
else
    log "Skipping timeseries extraction (--skip-extraction)"
fi

# Step 2: Prepare metadata
section "Step 2: Preparing Metadata"

log "Combining group assignments with fMRIPrep confounds..."
python3 "${SCRIPT_DIR}/prepare_metadata.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --group "${PROJECT_DIR}/group.csv" \
    --output "${RESULTS_DIR}/metadata.csv"

if [ $? -ne 0 ]; then
    error "Metadata preparation failed"
fi

log "✓ Metadata prepared: ${RESULTS_DIR}/metadata.csv"

# Step 3: Convert timeseries to HDF5
section "Step 3: Converting Timeseries to HDF5 Format"

for atlas in difumo256 schaefer400_7net schaefer200_7net; do
    log "Converting ${atlas} to HDF5..."

    python3 "${SCRIPT_DIR}/convert_tsv_to_hdf5.py" \
        --timeseries-dir "${TIMESERIES_DIR}/${atlas}" \
        --output "${RESULTS_DIR}/timeseries_${atlas}.h5" \
        --atlas "$atlas" \
        --verify

    if [ $? -ne 0 ]; then
        error "${atlas} HDF5 conversion failed"
    fi
done

log "✓ All timeseries converted to HDF5"

# Step 4A: Seed-based connectivity
if [ $SKIP_SEED_BASED -eq 0 ]; then
    section "Step 4A: Seed-Based Connectivity Analysis"

    log "Running seed-based analysis (Motor, Cerebellar, Hippocampus seeds)..."
    python3 "${SCRIPT_DIR}/seed_based_connectivity.py" \
        --fmriprep "$FMRIPREP_DIR" \
        --seeds "${ATLAS_DIR}/motor_cerebellar_seeds.json" \
        --metadata "${RESULTS_DIR}/metadata.csv" \
        --output "${RESULTS_DIR}/seed_based"

    if [ $? -ne 0 ]; then
        warn "Seed-based analysis had errors (check logs)"
    else
        log "✓ Seed-based connectivity complete"
    fi
else
    log "Skipping seed-based analysis (--skip-seed-based)"
fi

# Step 4B: ROI-to-ROI connectivity (hypothesis-driven)
section "Step 4B: ROI-to-ROI Connectivity (Hypothesis-Driven)"

log "Running hypothesis-driven ROI-to-ROI analysis (motor-cerebellar focus)..."
python3 "${SCRIPT_DIR}/python_connectivity_analysis.py" \
    --timeseries "${RESULTS_DIR}/timeseries_difumo256.h5" \
    --metadata "${RESULTS_DIR}/metadata.csv" \
    --networks "${ATLAS_DIR}/difumo256_network_definitions.json" \
    --output "${RESULTS_DIR}/connectivity_hypothesis" \
    --hypothesis-driven \
    --alpha 0.05

if [ $? -ne 0 ]; then
    error "Hypothesis-driven connectivity analysis failed"
fi

log "✓ Hypothesis-driven connectivity complete"

# Step 4C: ROI-to-ROI connectivity (exploratory)
section "Step 4C: ROI-to-ROI Connectivity (Exploratory)"

log "Running exploratory ROI-to-ROI analysis (all pairwise connections)..."
python3 "${SCRIPT_DIR}/python_connectivity_analysis.py" \
    --timeseries "${RESULTS_DIR}/timeseries_difumo256.h5" \
    --metadata "${RESULTS_DIR}/metadata.csv" \
    --networks "${ATLAS_DIR}/difumo256_network_definitions.json" \
    --output "${RESULTS_DIR}/connectivity_exploratory" \
    --alpha 0.05

if [ $? -ne 0 ]; then
    warn "Exploratory connectivity analysis had errors (check logs)"
else
    log "✓ Exploratory connectivity complete"
fi

# Step 5: Generate visualizations
section "Step 5: Generating Visualizations"

mkdir -p "$FIGURES_DIR"

log "Creating figures for hypothesis-driven results..."
python3 "${SCRIPT_DIR}/python_visualization.py" \
    --results "${RESULTS_DIR}/connectivity_hypothesis/connectivity_anova_results.csv" \
    --networks "${ATLAS_DIR}/difumo256_network_definitions.json" \
    --effect-sizes "${RESULTS_DIR}/connectivity_hypothesis/effect_sizes.csv" \
    --output "${FIGURES_DIR}/hypothesis_driven" \
    --alpha 0.05 \
    --top-n 50

if [ $? -ne 0 ]; then
    warn "Visualization generation had errors"
else
    log "✓ Visualizations complete"
fi

# Summary
section "WORKFLOW COMPLETE!"

log "Results summary:"
log "  1. Timeseries: ${TIMESERIES_DIR}/"
log "  2. Metadata: ${RESULTS_DIR}/metadata.csv"
log "  3. Seed-based maps: ${RESULTS_DIR}/seed_based/"
log "  4. ROI-to-ROI (hypothesis): ${RESULTS_DIR}/connectivity_hypothesis/"
log "  5. ROI-to-ROI (exploratory): ${RESULTS_DIR}/connectivity_exploratory/"
log "  6. Figures: ${FIGURES_DIR}/hypothesis_driven/"

log ""
log "Key output files:"
log "  - ${RESULTS_DIR}/connectivity_hypothesis/connectivity_anova_results.csv"
log "  - ${RESULTS_DIR}/connectivity_hypothesis/significant_interactions_fdr.csv"
log "  - ${RESULTS_DIR}/connectivity_hypothesis/effect_sizes.csv"

log ""
log "End time: $(date)"

# Check for significant results
if [ -f "${RESULTS_DIR}/connectivity_hypothesis/significant_interactions_fdr.csv" ]; then
    n_sig=$(tail -n +2 "${RESULTS_DIR}/connectivity_hypothesis/significant_interactions_fdr.csv" | wc -l)
    log ""
    if [ "$n_sig" -gt 0 ]; then
        log "🎉 Found $n_sig significant Group × Time interactions (FDR q<0.05)!"
        log "   Review: ${RESULTS_DIR}/connectivity_hypothesis/significant_interactions_fdr.csv"
    else
        log "ℹ️  No significant interactions found (increase alpha or check power)"
    fi
fi

log ""
log "✓ All analyses complete. Ready for manuscript preparation!"
