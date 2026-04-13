#!/bin/bash
#SBATCH --job-name=indiv_seeds
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=8:00:00
#SBATCH --array=1-43
#SBATCH --output=logs/indiv_seed_%A_%a.out
#SBATCH --error=logs/indiv_seed_%A_%a.err

# =============================================================================
# HPC SLURM Array Script: Individual DiFuMo Component Seeds
# =============================================================================
# Runs seed-based connectivity for 43 individual DiFuMo components:
# - 10 FrontoParietal frontal (key executive/cognitive regions)
# - 23 Somatomotor (ALL motor/sensory/sensorimotor components)
# - 10 Cerebellar Cognitive (all cognitive cerebellar components)
#
# Hypothesis: Walking intervention enhances motor network, which facilitates
# cognitive function through motor-cognitive integration.
#
# Processing time: ~3-5 min per subject per seed
# Parallelized via SLURM array (43 jobs)
# =============================================================================

set -e

echo "================================================================"
echo "Individual DiFuMo Component Seed Analysis - Array Job"
echo "================================================================"
echo "Job Array ID: $SLURM_ARRAY_JOB_ID"
echo "Array Task ID: $SLURM_ARRAY_TASK_ID"
echo "Job ID: $SLURM_JOB_ID"
echo "Node: $SLURM_NODELIST"
echo "CPUs: $SLURM_CPUS_PER_TASK"
echo "Memory: 16GB"
echo "Start time: $(date)"
echo ""

# Paths on HPC
PROJECT_DIR="/home/clivewong/proj/long"
FMRIPREP_DIR="$PROJECT_DIR/fmriprep"
SCRIPT_DIR="$PROJECT_DIR/script"
ATLASES_DIR="$PROJECT_DIR/atlases"
DERIVATIVE_ROOT="$PROJECT_DIR/derivatives/connectivity-difumo256"
METADATA_FILE="$DERIVATIVE_ROOT/participants_all24_final.csv"
SEED_DIR="$DERIVATIVE_ROOT/subject-level/seed_based"

mkdir -p "$SEED_DIR"
mkdir -p logs

# Activate conda environment
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate connectivity

# Define individual component seed list (43 seeds)
SEED_LIST=(
    # FrontoParietal frontal - key executive/cognitive regions (10 seeds)
    "FP_001"  # Middle frontal gyrus anterior RH
    "FP_056"  # Inferior frontal gyrus LH (BA 44/45)
    "FP_066"  # Middle frontal gyrus middle RH
    "FP_093"  # Inferior frontal sulcus anterior LH
    "FP_115"  # Superior frontal gyrus medial mid-posterior
    "FP_120"  # Dorsomedial prefrontal cortex
    "FP_140"  # Inferior frontal gyrus anterior LH
    "FP_143"  # Inferior frontal sulcus anterior RH
    "FP_191"  # Middle frontal gyrus posterior RH
    "FP_213"  # Middle frontal gyrus anterior

    # Somatomotor - ALL motor/sensory/sensorimotor (23 seeds)
    "SM_022"  # Postcentral gyrus LH
    "SM_025"  # Superior temporal gyrus LH
    "SM_043"  # Precentral sulcus medial (SMA)
    "SM_047"  # Frontal operculum RH
    "SM_050"  # Central sulcus superior RH
    "SM_082"  # Central sulcus inferior
    "SM_085"  # Heschl's gyrus (auditory)
    "SM_086"  # Central and postcentral sulci mid-superior
    "SM_099"  # Central sulcus middle
    "SM_114"  # Superior parts of central and postcentral sulci LH
    "SM_122"  # Callosomarginal sulcus
    "SM_136"  # Paracentral lobule posterior
    "SM_141"  # Central and postcentral sulci superior
    "SM_151"  # Precentral gyrus superior (M1 leg)
    "SM_162"  # Superior temporal gyrus medial
    "SM_166"  # Planum temporale LH
    "SM_185"  # Superior temporal sulcus RH
    "SM_190"  # Central opercular cortex
    "SM_200"  # Cingulate sulcus posterior
    "SM_203"  # Planum temporale RH
    "SM_218"  # Paracentral lobule
    "SM_238"  # Precentral gyrus middle (M1 arm/hand)
    "SM_254"  # Parietal operculum RH

    # Cerebellar Cognitive - all components (10 seeds)
    "CB_035"  # Cerebellum VIIb
    "CB_080"  # Cerebellum Crus I RH
    "CB_090"  # Cerebellum Crus I superior
    "CB_142"  # Cerebellum Crus I posterior
    "CB_146"  # Cerebellum Crus I lateral RH
    "CB_155"  # Cerebellum Crus II
    "CB_171"  # Cerebellum Crus I anterior LH
    "CB_178"  # Cerebellum Crus II
    "CB_186"  # Cerebellum VIIb
    "CB_208"  # Cerebellum Crus I posterior LH
)

# Get seed for this array task
SEED=${SEED_LIST[$SLURM_ARRAY_TASK_ID-1]}

echo "Processing individual component seed: $SEED"
echo "Array task: $SLURM_ARRAY_TASK_ID / ${#SEED_LIST[@]}"
echo ""

# Determine seed file based on prefix
if [[ $SEED == FP_* ]] || [[ $SEED == SM_* ]] || [[ $SEED == CB_* ]]; then
    # Individual component seeds use indices directly from DiFuMo 256
    SEED_FILE="$ATLASES_DIR/individual_component_seeds.json"
else
    SEED_FILE="$ATLASES_DIR/motor_cerebellar_seeds.json"
fi

# Run seed-based connectivity for individual component
python "$SCRIPT_DIR/seed_based_connectivity.py" \
    --fmriprep "$FMRIPREP_DIR" \
    --seeds "$SEED_FILE" \
    --metadata "$METADATA_FILE" \
    --output "$SEED_DIR" \
    --seed-names "$SEED" \
    --smoothing 6.0 \
    --high-pass 0.01 \
    --low-pass 0.1

echo ""
echo "================================================================"
echo "Individual Seed Connectivity Complete for $SEED"
echo "================================================================"
echo "End time: $(date)"
echo ""

# Count results for this seed
SEED_LOWER=$(echo $SEED | tr '[:upper:]' '[:lower:]' | tr '_' '_')
SEED_OUTPUT_DIR="$SEED_DIR/$SEED_LOWER"
if [ -d "$SEED_OUTPUT_DIR" ]; then
    zmap_count=$(find "$SEED_OUTPUT_DIR" -name "*_zmap.nii.gz" 2>/dev/null | wc -l)
    echo "Results: $zmap_count z-maps generated for $SEED"
    echo "Output: $SEED_OUTPUT_DIR"
else
    echo "WARNING: Output directory not found: $SEED_OUTPUT_DIR"
fi
