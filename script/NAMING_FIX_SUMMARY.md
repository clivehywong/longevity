# BIDS Naming Error Fix - Summary

## Date: 2025-01-09

## Issue Discovered
Subject sub-056 had incorrect BIDS naming in ses-02 directory:
- Files were named with `ses-01` instead of `ses-02`
- This affected all modalities: func, anat, fmap, and dwi

## Files Fixed (32 total)

### Functional (2 files)
- `sub-056_ses-01_task-rest_bold.nii.gz` → `sub-056_ses-02_task-rest_bold.nii.gz`
- `sub-056_ses-01_task-rest_bold.json` → `sub-056_ses-02_task-rest_bold.json`

### Anatomical (6 files)
- `sub-056_ses-01_run-01_T1w.nii.gz` → `sub-056_ses-02_run-01_T1w.nii.gz`
- `sub-056_ses-01_run-01_T1w.json` → `sub-056_ses-02_run-01_T1w.json`
- `sub-056_ses-01_run-02_T1w.nii.gz` → `sub-056_ses-02_run-02_T1w.nii.gz`
- `sub-056_ses-01_run-02_T1w.json` → `sub-056_ses-02_run-02_T1w.json`
- `sub-056_ses-01_T2w.nii.gz` → `sub-056_ses-02_T2w.nii.gz`
- `sub-056_ses-01_T2w.json` → `sub-056_ses-02_T2w.json`

### Field Maps (4 files)
- `sub-056_ses-01_dir-AP_epi.nii.gz` → `sub-056_ses-02_dir-AP_epi.nii.gz`
- `sub-056_ses-01_dir-AP_epi.json` → `sub-056_ses-02_dir-AP_epi.json`
- `sub-056_ses-01_dir-PA_epi.nii.gz` → `sub-056_ses-02_dir-PA_epi.nii.gz`
- `sub-056_ses-01_dir-PA_epi.json` → `sub-056_ses-02_dir-PA_epi.json`

### Diffusion Weighted Imaging (20 files)
- run-01_dwi: .nii.gz, .json, .bval, .bvec
- run-02_dwi: .nii.gz, .json, .bval, .bvec
- run-03_dwi: .nii.gz, .json, .bval, .bvec
- run-04_dwi: .nii.gz, .json, .bval, .bvec
- run-b0PA_dwi: .nii.gz, .json, .bval, .bvec

## Verification

After fixing:
- ✅ ses-02 with ses-01 filenames: **0**
- ✅ ses-01 with ses-02 filenames: **0**
- ✅ All 24 completed subjects checked: **No other naming errors found**

## Impact

This naming error likely caused:
1. **fMRIPrep failures** for sub-056 ses-02 (couldn't match files to session)
2. **BIDS validation errors**
3. **Potential data loss** if preprocessing was attempted

## Tools Created

### 1. `fix_naming_errors.sh`
- Automated script to detect and fix session/directory mismatches
- Interactive confirmation before renaming
- Color-coded output

### 2. `validate_bids_names.py`
- Comprehensive BIDS naming validator
- Checks for:
  - Session-directory mismatches
  - Subject-directory mismatches
  - Missing JSON sidecars
- Returns exit code 1 if errors found (CI/CD compatible)

## Usage

To check for naming errors in the future:

```bash
# Quick check
cd /Volumes/Work/Work/long/script
python3 validate_bids_names.py

# Auto-fix any errors found
bash fix_naming_errors.sh
```

## Recommendation

Before running any preprocessing pipeline (fMRIPrep, CONN, etc.):
1. Run `validate_bids_names.py` to check for errors
2. Fix any errors found
3. Proceed with preprocessing

## Status
✅ **RESOLVED** - All naming errors fixed, BIDS dataset is now valid
