# CONN Longitudinal Batch Processing

This directory contains scripts for preprocessing and connectivity analysis using the CONN toolbox.

## Overview

- **24 subjects** (15 Control, 9 Walking) × 2 sessions (Pre/Post)
- **Preprocessing**: CONN pipeline from raw BIDS data
- **Denoising**: aCompCor (5 WM + 5 CSF components) + motion parameters
- **Atlases**: Schaefer 400/200 (Yeo 7-networks), DiFuMo 256
- **Analysis**: ROI-to-ROI connectivity

## Files

| File | Description |
|------|-------------|
| `download_atlases.py` | Download atlases from nilearn |
| `conn_batch_longitudinal.m` | Main CONN batch script with parallel support |
| `PARALLEL_PROCESSING_GUIDE.md` | Detailed guide for parallel processing |
| `README_CONN.md` | This file |

## Quick Start

### 1. Download Atlases (One-time setup)

```bash
cd /Volumes/Work/Work/long/script
python3 download_atlases.py
```

This downloads and converts:
- Schaefer 400 ROIs (Yeo 7-networks) - **PRIMARY atlas**
- Schaefer 200 ROIs (Yeo 7-networks)
- DiFuMo 256 components

Output: `/Volumes/Work/Work/long/atlases/*.nii` and `*.txt` label files

### 2. Run CONN Batch Processing

#### Option A: Setup Only (Recommended First)

```matlab
% In MATLAB
conn_batch_longitudinal('setup')
```

This creates the CONN project and opens the GUI without running preprocessing. Use this to:
- Verify all subjects loaded correctly
- Check file paths
- Inspect atlas ROIs
- Then manually run preprocessing steps

#### Option B: Full Pipeline (Local Processing)

```matlab
% Sequential processing (slow, ~66 hours)
conn_batch_longitudinal('full', 0)

% Parallel processing with 4 jobs (recommended, ~17 hours)
conn_batch_longitudinal('full', 4)

% Parallel processing with 8 jobs (~8.5 hours)
conn_batch_longitudinal('full', 8)
```

⚠️ **Parallel processing requires**: MATLAB Parallel Computing Toolbox

📖 **See**: `PARALLEL_PROCESSING_GUIDE.md` for detailed parallel setup

## Preprocessing Pipeline

The script applies the following preprocessing steps:

1. **Realignment & Unwarp** - Motion correction
2. **Functional Center** - Center to origin
3. **ART** - Artifact/outlier detection (z=5, motion=0.9mm)
4. **Structural Segment & Normalize** - Unified segmentation/normalization
5. **Functional Normalize** - Indirect normalization (via structural)
6. **Spatial Smoothing** - 6mm FWHM Gaussian

**Note**: Slice timing correction is **SKIPPED** (multiband TR=0.8s - minimal timing differences)

## Denoising Strategy

**aCompCor + Motion**:
- 5 WM principal components
- 5 CSF principal components
- 6 motion parameters + derivatives
- Scrubbing (ART outliers)
- Band-pass filter: 0.01-0.1 Hz
- Linear detrending

## Output

CONN project file: `/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat`

Preprocessed data stored in: `/Volumes/Work/Work/long/conn_project/data/`

## Verification

After running, check:

1. **Open CONN GUI**:
   ```matlab
   conn
   conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat')
   ```

2. **Quality Assurance** → Check:
   - Normalization quality (structural + functional)
   - Motion parameters (realignment plots)
   - ART outlier scans
   - FC-QC plots (denoising effectiveness)

3. **ROI definitions** → Verify atlas ROIs are correctly loaded

## Subject List

From `completed_subjects_with_groups.csv`:

**Control (n=15)**:
- sub-033, sub-034, sub-035, sub-036, sub-037
- sub-038, sub-039, sub-040, sub-058, sub-059
- sub-060, sub-061, sub-062, sub-063, sub-064

**Walking (n=9)**:
- sub-043, sub-045, sub-046, sub-047, sub-048
- sub-052, sub-055, sub-056, sub-057

## Second-Level Analyses

After preprocessing, you can run second-level analyses in CONN GUI:

### Suggested Contrasts:

1. **Group comparison** (Control vs Walking)
   - Contrast: [1 -1] on Group effect

2. **Time effect** (Pre vs Post)
   - Paired t-test within subjects

3. **Group × Time interaction**
   - Mixed ANOVA design

## Troubleshooting

**Issue**: "Atlas not found" error
**Solution**: Run `download_atlases.py` first

**Issue**: "SPM not found" error
**Solution**: Paths are added automatically, but verify SPM/CONN are in `/Volumes/Work/Work/long/tools/`

**Issue**: Missing functional/anatomical files
**Solution**: Check BIDS directory structure - script expects:
- `sub-XXX/ses-XX/func/sub-XXX_ses-XX_task-rest_bold.nii.gz`
- `sub-XXX/ses-XX/anat/sub-XXX_ses-XX_run-01_T1w.nii.gz`

## References

- **CONN Toolbox**: https://www.nitrc.org/projects/conn
- **Schaefer Atlas**: Schaefer et al. (2018) Cereb Cortex
- **DiFuMo**: Dadi et al. (2020) NeuroImage

## Notes

- Script automatically adds SPM and CONN to MATLAB path
- Uses run-01 of T1w anatomical (two runs available per session)
- Field maps (AP/PA) are present but not used in standard pipeline
- For fieldmap-based distortion correction, modify preprocessing steps
