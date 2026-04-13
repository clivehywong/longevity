#!/bin/bash
# Comprehensive verification of environment setup for fMRIPrep longitudinal workflow

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓${NC} $1"; }
fail() { echo -e "${RED}✗${NC} $1"; }
warn() { echo -e "${YELLOW}⚠${NC} $1"; }
info() { echo -e "${BLUE}ℹ${NC} $1"; }

ERRORS=0
WARNINGS=0

echo "=================================="
echo "  fMRIPrep Workflow Verification"
echo "=================================="
echo ""

# 1. Check local directories and files
echo "1. Local filesystem checks..."
if [ -d "/Volumes/Work/Work/long/bids" ]; then
    n_subjects=$(ls -d /Volumes/Work/Work/long/bids/sub-* 2>/dev/null | wc -l)
    pass "BIDS directory exists with $n_subjects subjects"
else
    fail "BIDS directory not found"
    ((ERRORS++))
fi

if [ -d "/Volumes/Work/Work/long/script" ]; then
    pass "Script directory exists"
else
    fail "Script directory not found"
    ((ERRORS++))
fi

# Check scripts exist and are executable
scripts=(
    "batch_fmriprep.sh"
    "fmriprep_longitudinal.sh"
    "extract_timeseries.py"
    "extract_all_atlases.sh"
    "setup_gordon_atlas.py"
)

for script in "${scripts[@]}"; do
    if [ -f "/Volumes/Work/Work/long/script/$script" ]; then
        if [ -x "/Volumes/Work/Work/long/script/$script" ]; then
            pass "Script $script exists and is executable"
        else
            warn "Script $script exists but not executable"
            chmod +x "/Volumes/Work/Work/long/script/$script"
            pass "  Fixed: Made $script executable"
        fi
    else
        fail "Script $script not found"
        ((ERRORS++))
    fi
done

# Check storage space
echo ""
echo "2. Storage space checks..."
available=$(df -h /Volumes/Work/Work/long | tail -1 | awk '{print $4}')
avail_gb=$(df -k /Volumes/Work/Work/long | tail -1 | awk '{print int($4/1024/1024)}')
if [ "$avail_gb" -gt 100 ]; then
    pass "Local storage: ${available} available"
else
    warn "Local storage low: ${available} available (recommend 100GB+)"
    ((WARNINGS++))
fi

# 3. Check Python environment
echo ""
echo "3. Python environment checks..."
if command -v python3 &> /dev/null; then
    python_version=$(python3 --version)
    pass "Python3 installed: $python_version"
else
    fail "Python3 not found"
    ((ERRORS++))
fi

# Check required packages
packages=(
    "nibabel"
    "nilearn"
    "pandas"
    "numpy"
)

echo "   Checking Python packages..."
for package in "${packages[@]}"; do
    if python3 -c "import $package" 2>/dev/null; then
        version=$(python3 -c "import $package; print($package.__version__)" 2>/dev/null || echo "unknown")
        pass "  $package ($version)"
    else
        fail "  $package not installed"
        ((ERRORS++))
    fi
done

# 4. Check HPC connection
echo ""
echo "4. HPC server checks..."
if ssh -o ConnectTimeout=10 clivewong@hpclogin1.eduhk.hk "echo 'connected'" &>/dev/null; then
    pass "SSH connection to HPC working"

    # Check HPC environment
    singularity_check=$(ssh clivewong@hpclogin1.eduhk.hk "command -v singularity" 2>/dev/null || echo "not found")
    if [ "$singularity_check" != "not found" ]; then
        pass "Singularity available on HPC"
    else
        fail "Singularity not found on HPC"
        ((ERRORS++))
    fi

    # Check fMRIPrep image
    if ssh clivewong@hpclogin1.eduhk.hk "test -f /home/clivewong/software/fmriprep-25.1.4.simg" 2>/dev/null; then
        pass "fMRIPrep Singularity image found"
    else
        fail "fMRIPrep image not found at /home/clivewong/software/fmriprep-25.1.4.simg"
        ((ERRORS++))
    fi

    # Check FreeSurfer license
    if ssh clivewong@hpclogin1.eduhk.hk "test -f /home/clivewong/freesurfer/license.txt" 2>/dev/null; then
        pass "FreeSurfer license found"
    else
        fail "FreeSurfer license not found"
        ((ERRORS++))
    fi

    # Check HPC storage
    hpc_storage=$(ssh clivewong@hpclogin1.eduhk.hk "df -h /home/clivewong | tail -1 | awk '{print \$4}'")
    hpc_avail_gb=$(ssh clivewong@hpclogin1.eduhk.hk "df -k /home/clivewong | tail -1 | awk '{print int(\$4/1024/1024)}'")
    if [ "$hpc_avail_gb" -gt 500 ]; then
        pass "HPC storage: ${hpc_storage} available"
    else
        warn "HPC storage: ${hpc_storage} available (need 500GB+)"
        ((WARNINGS++))
    fi

    # Check if fmriprep script uploaded to HPC
    if ssh clivewong@hpclogin1.eduhk.hk "test -f /home/clivewong/proj/long/fmriprep_longitudinal.sh" 2>/dev/null; then
        pass "fMRIPrep script uploaded to HPC"
    else
        warn "fMRIPrep script not on HPC - will upload when running batch"
    fi

else
    fail "Cannot connect to HPC server"
    ((ERRORS++))
fi

# 5. Check atlases
echo ""
echo "5. Atlas availability checks..."

# Check if nilearn can fetch atlases
if python3 -c "from nilearn import datasets; datasets.fetch_atlas_schaefer_2018(n_rois=100, yeo_networks=7, resolution_mm=2)" &>/dev/null; then
    pass "Schaefer atlas available (nilearn)"
else
    warn "Schaefer atlas not cached - will download on first use"
fi

if python3 -c "from nilearn import datasets; datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2)" &>/dev/null; then
    pass "DiFuMo atlas available (nilearn)"
else
    warn "DiFuMo atlas not cached - will download on first use"
fi

# Check Gordon atlas
if [ -d "$HOME/nilearn_data/gordon_2016" ]; then
    if [ -f "$HOME/nilearn_data/gordon_2016/Gordon333_MNI_2mm.nii.gz" ]; then
        pass "Gordon 333 atlas installed"
    else
        warn "Gordon atlas directory exists but incomplete"
        info "  Run: python script/setup_gordon_atlas.py"
        ((WARNINGS++))
    fi
else
    warn "Gordon 333 atlas not installed"
    info "  Run: python script/setup_gordon_atlas.py"
    ((WARNINGS++))
fi

# 6. Verify subject data
echo ""
echo "6. Longitudinal subject verification..."
multi_session_subjects=()
for sub in /Volumes/Work/Work/long/bids/sub-*/; do
    subname=$(basename "$sub")
    ses1=$(ls -d "$sub"ses-01 2>/dev/null)
    ses2=$(ls -d "$sub"ses-02 2>/dev/null)
    if [ -n "$ses1" ] && [ -n "$ses2" ]; then
        multi_session_subjects+=("$subname")
    fi
done

if [ ${#multi_session_subjects[@]} -gt 0 ]; then
    pass "Found ${#multi_session_subjects[@]} subjects with both ses-01 and ses-02"
    info "  Subjects: ${multi_session_subjects[*]:0:5}..."
else
    fail "No subjects with both sessions found"
    ((ERRORS++))
fi

# Check sample data integrity
echo ""
echo "7. Sample data integrity check..."
sample_bold="/Volumes/Work/Work/long/bids/sub-033/ses-01/func/sub-033_ses-01_task-rest_bold.nii.gz"
if [ -f "$sample_bold" ]; then
    if python3 -c "import nibabel as nib; nib.load('$sample_bold')" 2>/dev/null; then
        pass "Sample BOLD file readable"
    else
        fail "Sample BOLD file corrupted"
        ((ERRORS++))
    fi
else
    warn "Sample BOLD file not found (sub-033)"
fi

# 8. Optional tools
echo ""
echo "8. Optional tools..."
if command -v parallel &> /dev/null; then
    pass "GNU parallel installed (for multi-atlas extraction)"
else
    warn "GNU parallel not found - extract_all_atlases.sh needs it"
    info "  Install: brew install parallel"
    ((WARNINGS++))
fi

if command -v rsync &> /dev/null; then
    rsync_version=$(rsync --version | head -1)
    pass "rsync installed: $rsync_version"
else
    fail "rsync not found (required for batch upload/download)"
    ((ERRORS++))
fi

# Summary
echo ""
echo "=================================="
echo "          Summary"
echo "=================================="
if [ $ERRORS -eq 0 ] && [ $WARNINGS -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed! Ready to start.${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Start fMRIPrep processing:"
    echo "     ./script/batch_fmriprep.sh"
    echo ""
    echo "  2. After processing, extract time series:"
    echo "     ./script/extract_all_atlases.sh"
    exit 0
elif [ $ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠ ${WARNINGS} warning(s) - review above${NC}"
    echo "You can proceed but may encounter issues"
    exit 0
else
    echo -e "${RED}✗ ${ERRORS} error(s), ${WARNINGS} warning(s)${NC}"
    echo "Please fix errors before proceeding"
    exit 1
fi
