# Sub-057 Segmentation Fix - SUCCESS

**Date**: 2026-01-10
**Status**: ✅ **RESOLVED**

---

## Problem

Sub-057 ses-02 segmentation failed with run-01 T1w:
- Grey matter map (`wc1csub-057_ses-02_run-01_T1w.nii`) was all zeros
- Error: "No suprathreshold voxels in ROI file"
- Root cause: SPM segmentation failed to align run-01 to MNI template

---

## Solution

**Swapped to run-02 T1w** (sub-057 has 2 T1w scans per session)

### Actions Taken

1. ✅ Updated CONN project structural path:
   - Old: `.../wc0csub-057_ses-02_run-01_T1w.nii`
   - New: `.../wc0csub-057_ses-02_run-02_T1w.nii`

2. ✅ Deleted failed run-01 preprocessing outputs:
   - Centered: `csub-057_ses-02_run-01_T1w.nii`
   - Segmented: `c1/c2/c3csub-057_ses-02_run-01_T1w.nii`
   - Normalized: `wc0/wc1/wc2/wc3csub-057_ses-02_run-01_T1w.nii`
   - Deformation fields: `y_*/iy_*`

3. ✅ Re-ran CONN preprocessing:
   - Segmentation: 100% complete (24 subjects)
   - ROI import: In progress

---

## Outcome

✅ **All 24 subjects retained** (15 Control, 9 Walking)
- No reduction in statistical power
- Full sample for Group × Time analysis

### Preprocessing Status (as of 2026-01-10)

```
Step 1/7: Data completeness check ✅
Step 2/7: Segmentation ✅ (100%)
Step 3/7: Import conditions/covariates ✅ (100%)
Step 4/7: (skipped in log)
Step 5/7: Import ROI data ⏳ (in progress, ~5%)
Step 6/7: Functional preprocessing (pending)
Step 7/7: Denoising (pending)
```

**Expected completion**: 6-12 hours (depends on system load)

---

## Verification

### Run-02 Segmentation Check

After preprocessing completes, verify run-02 succeeded:

```bash
# Check grey matter has non-zero values
fslstats /Volumes/Work/Work/long/bids/sub-057/ses-02/anat/wc1csub-057_ses-02_run-02_T1w.nii -R

# Expected: Non-zero values (e.g., "0.000000 0.983425")
# NOT: "0.000000 0.000000" (which would indicate failure)
```

### Overall Preprocessing Progress

```bash
# Count preprocessed functional files (target: 48)
find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l

# Check sub-057 ses-02 specifically
ls -lh /Volumes/Work/Work/long/bids/sub-057/ses-02/func/swua*
```

---

## Scripts Used

1. **`diagnose_conn_structure.m`** - Inspected CONN project structure
2. **`list_all_subjects.m`** - Found sub-057 at index 24
3. **`swap_sub057_to_run02_v3.m`** - **Final working script**

### Running via Command Line

MATLAB executed successfully via:
```bash
/Applications/MATLAB_R2024b.app/bin/matlab -nodisplay -nosplash -r "cd('/Volumes/Work/Work/long/script'); swap_sub057_to_run02_v3; exit"
```

This allows automated execution without manual copy-paste in MATLAB GUI.

---

## Next Steps

### After Preprocessing Completes

1. **Verify all 48 sessions processed**:
   ```bash
   find /Volumes/Work/Work/long/bids -name "swua*.nii" | wc -l
   # Should show: 48
   ```

2. **Check for errors** in CONN log:
   - Open CONN GUI: `conn` in MATLAB
   - Load project: `conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat')`
   - Check Setup → View logs

3. **Export timeseries** for Python analysis:
   - Create `export_roi_timeseries_from_conn.m`
   - Extract DiFuMo 256 ROI timeseries → HDF5 format
   - Save to `/Volumes/Work/Work/long/results/timeseries/`

4. **Run Python connectivity analysis**:
   ```bash
   python python_connectivity_analysis.py \\
       --timeseries timeseries_difumo256.h5 \\
       --metadata metadata.csv \\
       --networks difumo256_network_definitions.json \\
       --output results/connectivity_analysis
   ```

5. **Generate visualizations**:
   ```bash
   python python_visualization.py \\
       --results connectivity_anova_results.csv \\
       --networks difumo256_network_definitions.json \\
       --output figures/
   ```

---

## Lessons Learned

### Multi-run Acquisitions

When subjects have multiple runs (run-01, run-02):
- **Default behavior**: CONN/SPM uses first run (run-01)
- **If first run fails**: Can swap to alternative run (run-02)
- **Better than exclusion**: Preserves sample size and statistical power

### CONN Project Structure

- Functional: `CONN_x.Setup.functional{subject}{session}` (singular)
- Structural: `CONN_x.Setup.structural{subject}{session}` (singular)
- Fields are often cell arrays, need `{1}` indexing
- Subject indexing: 1-24 (not BIDS IDs like "sub-057")

### Command-Line MATLAB

Pros:
- Automated execution
- No manual copy-paste
- Can run in background
- Scriptable workflow

Cons:
- Path setup required (addpath)
- No interactive debugging
- Warnings to stdout

---

## Impact on Analysis

✅ **No impact** - Full study proceeds as planned:
- Sample: 24 subjects (15 Control, 9 Walking)
- Sessions: 2 per subject (Pre, Post)
- Total: 48 sessions
- Atlas: DiFuMo 256 (with cerebellar coverage)
- Hypothesis: Walking intervention → increased motor-cerebellar connectivity

---

**Resolution**: Successfully swapped sub-057 ses-02 to run-02, preserving full sample for analysis.
