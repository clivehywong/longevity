# Longitudinal fMRIPrep Workflow Guide

## Overview

This workflow processes 24 subjects with longitudinal data (ses-01 and ses-02) using fMRIPrep's `--longitudinal` flag for cross-session FreeSurfer template creation.

## Environment Status

### ✓ Ready
- Python 3.12.6 with nibabel, nilearn, pandas, numpy
- 42 subjects in BIDS directory (24 with both sessions)
- SSH connection to HPC working
- fMRIPrep 25.1.4 Singularity image on HPC
- FreeSurfer license on HPC
- Schaefer and DiFuMo atlases cached

### ⚠ Optional
- Gordon 333 atlas (run `python script/setup_gordon_atlas.py` if needed)
- GNU parallel (for faster multi-atlas extraction - not required)

## Workflow Steps

### Step 1: Start fMRIPrep Processing (Automated)

```bash
cd /Volumes/Work/Work/long
./script/batch_fmriprep.sh
```

This script will automatically:
1. **Batch 1** (sub-033 to sub-040):
   - Upload BIDS data to HPC
   - Submit SLURM job with `--longitudinal` flag
   - Wait for completion (~24 hours)
   - Download results (preprocessed BOLD, confounds, QC reports)
   - Clean up HPC to free space

2. **Batch 2** (sub-043 to sub-056): Repeat
3. **Batch 3** (sub-057 to sub-064): Repeat

**Total time:** ~3-4 days (24h per batch × 3 batches)

**Where files go:**
- Local BIDS: `/Volumes/Work/Work/long/bids/`
- HPC temporary: `/home/clivewong/proj/long/` (cleaned after each batch)
- Local output: `/Volumes/Work/Work/long/fmriprep/`

### Step 2: Extract Time Series (After All Batches)

After all fMRIPrep processing is complete:

```bash
# Extract with 3 main atlases (Schaefer 400, DiFuMo 256, Schaefer 200)
./script/extract_all_atlases_simple.sh

# Or extract individually
python script/extract_timeseries.py \
    fmriprep/ \
    timeseries/schaefer400_7net \
    --atlas schaefer_400_7 \
    --smoothing 6 \
    --confounds minimal
```

**Output:**
- `timeseries/schaefer400_7net/` - Schaefer 400 ROIs (primary)
- `timeseries/difumo256/` - DiFuMo 256 components
- `timeseries/schaefer200_7net/` - Schaefer 200 ROIs
- Each contains:
  - `sub-XXX_ses-XX_task-rest_atlas-NAME_timeseries.tsv` (ROI × time)
  - `qc_summary.tsv` (motion, tSNR metrics)

## Manual Controls

### Check Job Status
```bash
./script/batch_fmriprep.sh status
```

### Resume From Specific Batch
```bash
./script/batch_fmriprep.sh 2  # Start from batch 2
```

### Run Individual Steps
```bash
./script/batch_fmriprep.sh upload 1      # Upload batch 1
./script/batch_fmriprep.sh submit 1      # Submit job
./script/batch_fmriprep.sh download 1    # Download results
./script/batch_fmriprep.sh cleanup 1     # Clean remote
```

## Data Flow

```
Local Mac                    HPC Server                     Local Mac
-----------                 --------------                  -----------
BIDS data    --upload-->    BIDS (temp)
                           ↓
                         fMRIPrep
                         (longitudinal)
                           ↓
                         Derivatives    --download-->    fmriprep/
                                                            ↓
                                                      Time series
                                                      extraction
                                                            ↓
                                                      timeseries/
```

## Storage Requirements

- **Local:** ~150GB (BIDS: 20GB, fMRIPrep outputs: 130GB)
- **HPC:** ~150GB per batch (cleaned after each)

## Expected Outputs Per Subject

### fMRIPrep Derivatives
- `sub-XXX/ses-0X/anat/` - T1w, brain masks, tissue segmentation
- `sub-XXX/ses-0X/func/` - Preprocessed BOLD in MNI space (smoothed + unsmoothed)
- `sub-XXX/ses-0X/func/*confounds_timeseries.tsv` - Motion, physiological confounds
- `sub-XXX/ses-0X/figures/` - QC plots
- `sub-XXX.html` - Visual QC report

### Time Series
- ROI time series: 400 ROIs × ~480 timepoints (Schaefer 400)
- Format: TSV with ROI labels as column headers
- QC metrics: Mean FD, tSNR, global correlation

## Troubleshooting

### If batch fails:
1. Check logs: `/Volumes/Work/Work/long/fmriprep/logs/`
2. Check HPC logs via SSH
3. Resume from failed batch: `./script/batch_fmriprep.sh N`

### If extraction fails:
1. Check `timeseries/logs/atlas_name.log`
2. Verify fMRIPrep outputs exist
3. Try single subject: add `--subjects 033` flag

## Next Steps After Extraction

With time series extracted, you can:
1. Compute functional connectivity matrices
2. Perform network analysis
3. Compare pre/post intervention (ses-01 vs ses-02)
4. Compare different atlases for robustness

## Contact Info

HPC: clivewong@hpclogin1.eduhk.hk
Local: /Volumes/Work/Work/long/
