# CONN Resume & Skip Completed Steps Guide

## Your Current Situation

✅ **Let your current script finish** - It's still in setup phase (no processing yet)

The script is just building the job list. No actual preprocessing has started, so:
- No files have been unzipped
- No realignment has run
- No data has been overwritten

## About Unzipping

CONN handles `.nii.gz` files intelligently:

1. **First run**: CONN will unzip `.nii.gz` → `.nii` in CONN project directory
2. **Subsequent runs**: CONN checks if `.nii` already exists and skips unzipping
3. **With `overwrite='Yes'`**: May re-unzip, but only if target doesn't exist

### Where unzipped files go:
```
/Volumes/Work/Work/long/conn_project/conn_longitudinal/data/
├── NIFTI_Subject001_Session001/  # Unzipped functional
├── NIFTI_Subject001_Session002/
├── ...
```

**Important**: Original BIDS `.nii.gz` files are **never modified**

## Resuming Interrupted Processing

If you need to stop and resume later:

### Option 1: Use the new resume script (RECOMMENDED)

```matlab
% Stop current run (Ctrl+C)

% Later, resume with parallelization
conn_batch_resume(4)  % Resume with 4 parallel jobs
```

This script:
- ✅ Sets `overwrite='No'` (skips completed steps)
- ✅ Supports parallelization
- ✅ Won't re-process already-done subjects

### Option 2: Modify main script

Change this in `conn_batch_longitudinal.m`:

```matlab
% BEFORE (current - will redo everything)
batch.Setup.overwrite = 'Yes';
batch.Denoising.overwrite = 'Yes';
batch.Analysis.overwrite = 'Yes';

% AFTER (smart resume - skips completed)
batch.Setup.overwrite = 'No';
batch.Denoising.overwrite = 'No';
batch.Analysis.overwrite = 'No';
```

## What Gets Skipped with `overwrite='No'`

CONN checks for these output files and skips if they exist:

| Stage | Output Files Checked |
|-------|---------------------|
| **Realignment** | `rp_*.txt`, `u*.nii` |
| **Normalization** | `w*.nii` |
| **Smoothing** | `sw*.nii` |
| **Denoising** | `*_REST_*.mat` |
| **ROI extraction** | `ROI_Subject*_*.mat` |

If output exists → Step is skipped ✅

## When to Use Resume vs Fresh Run

### Use Resume (`overwrite='No'`) when:
- ✅ Script was interrupted (crash, Ctrl+C, power loss)
- ✅ Want to add parallelization to existing project
- ✅ Only some subjects failed, want to re-run those
- ✅ Adding new subjects to existing project

### Use Fresh Run (`overwrite='Yes'`) when:
- ✅ First time running
- ✅ Changed preprocessing parameters (smoothing, filtering, etc.)
- ✅ Want to redo everything from scratch
- ✅ Suspect corrupted output files

## Checking What's Already Done

```matlab
% Load CONN project
conn
conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat')

% Check preprocessing status
% Setup → Check preprocessing pipeline
% → View completed steps per subject

% Or check output files directly
ls /Volumes/Work/Work/long/conn_project/conn_longitudinal/data/
```

## Current Run Status

Based on the log file, your current run is:
- ✅ In setup phase (building job list)
- ✅ Found all 24 subjects × 2 sessions
- ✅ Correctly detected sub-056 ses-02 (with fixed filenames!)
- ⏳ About to start preprocessing (realignment)

### Recommendation: **Let it finish**

## If You Need to Stop Now

```matlab
% In MATLAB console
Ctrl+C  % Stop execution

% Check what was completed
conn
conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat')

% Resume later with parallelization
conn_batch_resume(4)
```

## File Organization

```
conn_project/conn_longitudinal/
├── conn_longitudinal.mat          # Main project file
├── data/                           # Unzipped & preprocessed data
│   ├── NIFTI_Subject001_Session001/
│   ├── roi/                        # ROI timeseries
│   └── results/                    # Processing outputs
├── logs/                           # Preprocessing logs
└── logfile.txt                     # Main log
```

## Performance Impact

### With `overwrite='Yes'` (current):
- Fresh preprocessing: ~66 hours (sequential) or ~8-17 hours (parallel)
- May re-process already-done work

### With `overwrite='No'` (resume):
- Only processes incomplete subjects
- If 10/24 subjects done → only 14 subjects to process
- Time = (~66 hours × 14/24) = ~38.5 hours sequential

## Quick Commands

```matlab
% Let current run finish (RECOMMENDED)
% → Just wait

% Stop and resume with parallel later
Ctrl+C
conn_batch_resume(4)

% Check project status
conn
conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat')

% Check preprocessing completion
% GUI → Setup → Preprocessing pipeline → Status
```

## Summary

**For your current situation:**
1. ✅ **Keep it running** - Still in setup, no processing yet
2. ✅ **Unzipping is smart** - Won't re-unzip existing files
3. ✅ **Fixed filenames working** - sub-056 ses-02 now detected correctly
4. ⏭️ **Next time**: Use `conn_batch_resume()` for smart resuming

The first run will be slow, but subsequent runs with `overwrite='No'` will skip completed steps!
