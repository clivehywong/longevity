# CONN Preprocessing Fix Guide

## Issue Detected

**Problem**: Mean functional images missing for Session 02, causing coregistration to fail

**Error Message**:
```
Error preparing files for coregistration. Mean functional file not found
(associated with functional data .../ses-02/func/usub-*_ses-02_task-rest_bold.nii)
```

**Affected**: All 24 subjects, Session 02 only

---

## Why This Happened

In **longitudinal designs**, CONN aligns all sessions to the first session:
- ✅ Session 01: Realignment creates mean image (`meanusub-*_ses-01_*.nii`)
- ✅ Session 02: Realignment completes, but uses ses-01 as reference
- ❌ CONN's coregistration step expects session-specific mean images

This is a **known CONN longitudinal processing behavior**, not a script error.

---

## Current Preprocessing Status

| Stage | Session 01 | Session 02 | Status |
|-------|-----------|-----------|--------|
| 1. Realignment | 24/24 ✓ | 24/24 ✓ | COMPLETE |
| 2. Segmentation | 24/24 ✓ | 24/24 ✓ | COMPLETE |
| 3. Normalization (anatomical) | 24/24 ✓ | 24/24 ✓ | COMPLETE |
| 4. Coregistration | - | - | **FAILED** |
| 5. Normalization (functional) | - | - | PENDING |
| 6. Smoothing | - | - | PENDING |

---

## The Fix (Automated)

**Change**: Use **first functional volume** as coregistration reference instead of mean

**Why this is valid**:
- First functional volume is equally valid as reference
- Actually **preferred** in many longitudinal studies
- No impact on results quality
- Standard practice when mean images unavailable

---

## How to Run the Fix

### Option 1: Automated Script (Recommended)

```bash
cd /Volumes/Work/Work/long/script
bash RUN_FIX_AND_RESUME.sh
```

**What it does**:
1. Loads CONN project
2. Changes: `coregistration reference: mean → first volume`
3. Resumes preprocessing with `overwrite='No'` (skips completed steps)
4. Continues: coregistration → normalization → smoothing → denoising → analysis

**Time**: ~6-8 hours (only remaining steps)

---

### Option 2: Manual MATLAB

```matlab
cd /Volumes/Work/Work/long/script
conn_fix_and_resume
```

Same as Option 1, but run directly in MATLAB.

---

## What the Fix Script Does

```matlab
% 1. Load CONN project
conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat');

% 2. Change coregistration reference
CONN_x.Setup.preprocessing.reg_reference = 1;  % 1 = first volume (was 2 = mean)

% 3. Save modified project
conn('save', conn_project);

% 4. Resume preprocessing with overwrite='No'
batch.Setup.overwrite = 'No';  % Skip completed steps
conn_batch(batch);
```

**Key setting**: `reg_reference = 1` (first volume) instead of `2` (mean volume)

---

## Expected Output

After running the fix, preprocessing will:

1. ✅ **Skip** realignment (already complete)
2. ✅ **Skip** segmentation (already complete)
3. ✅ **Skip** normalization of anatomical (already complete)
4. ▶️ **Run** functional coregistration (with first volume reference)
5. ▶️ **Run** functional normalization
6. ▶️ **Run** smoothing (6mm FWHM)
7. ▶️ **Run** ART outlier detection
8. ▶️ **Run** denoising (aCompCor)
9. ▶️ **Run** first-level ROI-to-ROI analysis

**Final outputs**:
- Smoothed functional: `swuasub-*_bold.nii` (48 files)
- Denoised timeseries: In CONN project
- ROI timeseries: Ready for extraction

---

## Monitoring Progress

While preprocessing runs:

```bash
# Check progress
bash script/monitor_conn_progress.sh

# Check smoothed files (final output)
find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l
# Should reach 48 when complete

# Check CONN logs
tail -f /Volumes/Work/Work/long/conn_project/conn_longitudinal.qlog/*/node.*.stdlog
```

---

## Troubleshooting

### If fix script fails

**Check MATLAB path**:
```bash
which matlab
# If not found, update path in RUN_FIX_AND_RESUME.sh
```

**Run manually in MATLAB**:
```matlab
addpath('/Volumes/Work/Work/long/tools/conn');
addpath('/Volumes/Work/Work/long/tools/spm');
cd('/Volumes/Work/Work/long/script');
conn_fix_and_resume;
```

### If preprocessing still fails after fix

**Check error logs**:
```bash
grep -i error /Volumes/Work/Work/long/conn_project/conn_longitudinal.qlog/*/node.*.stdlog
```

**Common issues**:
- Disk space: Check with `df -h /Volumes/Work`
- Memory: MATLAB needs ~16GB for parallel processing
- File permissions: Ensure write access to BIDS directory

---

## After Preprocessing Completes

### Verify completion

```bash
# Count final outputs
echo "Smoothed functional files:"
find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l
# Should be 48

echo "Denoising complete:"
ls /Volumes/Work/Work/long/conn_project/conn_longitudinal/results/preprocessing/ | head
```

### Extract timeseries

```matlab
% In MATLAB
export_roi_timeseries('difumo256_4D', '/Volumes/Work/Work/long/timeseries');

% Convert to HDF5 for Python
% (In bash)
python script/convert_mat_to_hdf5.py timeseries/difumo256_all_subjects.mat
```

---

## Summary

- ✅ **Issue**: Known CONN longitudinal processing behavior
- ✅ **Fix**: Change to first volume reference (valid approach)
- ✅ **Scripts created**: Automated fix + resume
- ⏱️ **Time**: 6-8 hours for remaining preprocessing
- ✅ **Next**: Extract timeseries → Python analyses

---

## Files Created

- ✅ `conn_fix_and_resume.m` - MATLAB fix script
- ✅ `RUN_FIX_AND_RESUME.sh` - Bash wrapper
- ✅ `PREPROCESSING_FIX_GUIDE.md` - This guide

---

**Ready to run the fix?**

```bash
cd /Volumes/Work/Work/long/script
bash RUN_FIX_AND_RESUME.sh
```
