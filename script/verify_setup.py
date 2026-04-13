#!/usr/bin/env python3
"""Comprehensive verification of environment setup for fMRIPrep longitudinal workflow"""

import subprocess
import sys
from pathlib import Path
import os

# Colors
GREEN = '\033[0;32m'
RED = '\033[0;31m'
YELLOW = '\033[1;33m'
BLUE = '\033[0;34m'
NC = '\033[0m'

errors = 0
warnings = 0

def pass_check(msg):
    print(f"{GREEN}✓{NC} {msg}")

def fail_check(msg):
    global errors
    print(f"{RED}✗{NC} {msg}")
    errors += 1

def warn_check(msg):
    global warnings
    print(f"{YELLOW}⚠{NC} {msg}")
    warnings += 1

def info(msg):
    print(f"{BLUE}ℹ{NC} {msg}")

print("=" * 50)
print("  fMRIPrep Workflow Verification")
print("=" * 50)
print()

# 1. Check local directories
print("1. Local filesystem checks...")
bids_dir = Path("/Volumes/Work/Work/long/bids")
if bids_dir.exists():
    n_subjects = len(list(bids_dir.glob("sub-*")))
    pass_check(f"BIDS directory exists with {n_subjects} subjects")
else:
    fail_check("BIDS directory not found")

script_dir = Path("/Volumes/Work/Work/long/script")
if script_dir.exists():
    pass_check("Script directory exists")
else:
    fail_check("Script directory not found")

# Check required scripts
scripts = [
    "batch_fmriprep.sh",
    "fmriprep_longitudinal.sh",
    "extract_timeseries.py",
    "extract_all_atlases.sh",
    "setup_gordon_atlas.py"
]

for script_name in scripts:
    script_path = script_dir / script_name
    if script_path.exists():
        if os.access(script_path, os.X_OK):
            pass_check(f"Script {script_name} exists and is executable")
        else:
            warn_check(f"Script {script_name} exists but not executable")
            script_path.chmod(0o755)
            pass_check(f"  Fixed: Made {script_name} executable")
    else:
        fail_check(f"Script {script_name} not found")

# 2. Check Python packages
print()
print("2. Python environment checks...")
print(f"   Python: {sys.version}")

required_packages = {
    'nibabel': 'nibabel',
    'nilearn': 'nilearn',
    'pandas': 'pandas',
    'numpy': 'numpy'
}

for package_name, import_name in required_packages.items():
    try:
        module = __import__(import_name)
        version = getattr(module, '__version__', 'unknown')
        pass_check(f"  {package_name} ({version})")
    except ImportError:
        fail_check(f"  {package_name} not installed")

# 3. Check HPC connection
print()
print("3. HPC server checks...")
try:
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "clivewong@hpclogin1.eduhk.hk", "echo connected"],
        capture_output=True, text=True, timeout=15
    )
    if result.returncode == 0:
        pass_check("SSH connection to HPC working")

        # Check Singularity
        result = subprocess.run(
            ["ssh", "clivewong@hpclogin1.eduhk.hk", "command -v singularity"],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            pass_check("Singularity available on HPC")
        else:
            fail_check("Singularity not found on HPC")

        # Check fMRIPrep image
        result = subprocess.run(
            ["ssh", "clivewong@hpclogin1.eduhk.hk", "test -f /home/clivewong/software/fmriprep-25.1.4.simg"],
            capture_output=True, timeout=15
        )
        if result.returncode == 0:
            pass_check("fMRIPrep Singularity image found")
        else:
            fail_check("fMRIPrep image not found")

        # Check FreeSurfer license
        result = subprocess.run(
            ["ssh", "clivewong@hpclogin1.eduhk.hk", "test -f /home/clivewong/freesurfer/license.txt"],
            capture_output=True, timeout=15
        )
        if result.returncode == 0:
            pass_check("FreeSurfer license found")
        else:
            fail_check("FreeSurfer license not found")

    else:
        fail_check("Cannot connect to HPC server")
except Exception as e:
    fail_check(f"HPC connection error: {e}")

# 4. Check atlases
print()
print("4. Atlas availability checks...")

try:
    from nilearn import datasets

    # Test Schaefer
    try:
        datasets.fetch_atlas_schaefer_2018(n_rois=100, yeo_networks=7, resolution_mm=2, verbose=0)
        pass_check("Schaefer atlas available (nilearn)")
    except:
        warn_check("Schaefer atlas not cached - will download on first use")

    # Test DiFuMo
    try:
        datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2, verbose=0)
        pass_check("DiFuMo atlas available (nilearn)")
    except:
        warn_check("DiFuMo atlas not cached - will download on first use")

except ImportError:
    fail_check("nilearn not available - cannot check atlases")

# Check Gordon
gordon_dir = Path.home() / "nilearn_data" / "gordon_2016"
gordon_atlas = gordon_dir / "Gordon333_MNI_2mm.nii.gz"
if gordon_atlas.exists():
    pass_check("Gordon 333 atlas installed")
else:
    warn_check("Gordon 333 atlas not installed")
    info("  Run: python script/setup_gordon_atlas.py")

# 5. Check longitudinal subjects
print()
print("5. Longitudinal subject verification...")
multi_session = []
for sub_dir in sorted(bids_dir.glob("sub-*")):
    ses01 = sub_dir / "ses-01"
    ses02 = sub_dir / "ses-02"
    if ses01.exists() and ses02.exists():
        multi_session.append(sub_dir.name)

if multi_session:
    pass_check(f"Found {len(multi_session)} subjects with both ses-01 and ses-02")
    info(f"  First 5: {', '.join(multi_session[:5])}...")
else:
    fail_check("No subjects with both sessions found")

# 6. Check sample data
print()
print("6. Sample data integrity check...")
sample_bold = Path("/Volumes/Work/Work/long/bids/sub-033/ses-01/func/sub-033_ses-01_task-rest_bold.nii.gz")
if sample_bold.exists():
    try:
        import nibabel as nib
        nib.load(str(sample_bold))
        pass_check("Sample BOLD file readable")
    except Exception as e:
        fail_check(f"Sample BOLD file corrupted: {e}")
else:
    warn_check("Sample BOLD file not found (sub-033)")

# 7. Optional tools
print()
print("7. Optional tools...")
try:
    result = subprocess.run(["parallel", "--version"], capture_output=True, timeout=5)
    if result.returncode == 0:
        pass_check("GNU parallel installed")
    else:
        warn_check("GNU parallel not found - extract_all_atlases.sh needs it")
        info("  Install: brew install parallel")
except:
    warn_check("GNU parallel not found")
    info("  Install: brew install parallel")

try:
    result = subprocess.run(["rsync", "--version"], capture_output=True, timeout=5)
    if result.returncode == 0:
        pass_check("rsync installed")
    else:
        fail_check("rsync not found (required)")
except:
    fail_check("rsync not found")

# Summary
print()
print("=" * 50)
print("          Summary")
print("=" * 50)

if errors == 0 and warnings == 0:
    print(f"{GREEN}✓ All checks passed! Ready to start.{NC}")
    print()
    print("Next steps:")
    print("  1. Setup Gordon atlas (optional):")
    print("     python script/setup_gordon_atlas.py")
    print()
    print("  2. Start fMRIPrep processing:")
    print("     ./script/batch_fmriprep.sh")
    print()
    print("  3. After processing, extract time series:")
    print("     ./script/extract_all_atlases.sh")
    sys.exit(0)
elif errors == 0:
    print(f"{YELLOW}⚠ {warnings} warning(s) - review above{NC}")
    print("You can proceed but may encounter issues")
    sys.exit(0)
else:
    print(f"{RED}✗ {errors} error(s), {warnings} warning(s){NC}")
    print("Please fix errors before proceeding")
    sys.exit(1)
