# Atlas Label Files Fix

## Issue

CONN requires label files in specific format: `ROI_NUMBER ROI_LABEL` (space-separated)

Original format:
```
Background
LH_Vis_1
LH_Vis_2
```

CONN-required format:
```
0 Background
1 LH_Vis_1
2 LH_Vis_2
```

## Fixed Files Created

✅ `schaefer400_7net_conn.txt` - CONN-formatted (401 lines with ROI numbers)
✅ `schaefer200_7net_conn.txt` - CONN-formatted (201 lines with ROI numbers)

## Impact

- **DiFuMo 256**: ✅ No issue (4D probabilistic atlas, no label file needed)
- **Schaefer 400**: ⚠️ Warning (but will still work, uses default labels)
- **Schaefer 200**: ⚠️ Warning (but will still work, uses default labels)

## Recommendation

**For this project**: Focus on **DiFuMo 256** (includes cerebellum)
- No label file issues
- Whole brain coverage
- Already have network definitions with cerebellar zones

**If you want to use Schaefer later**:
Update `conn_batch_longitudinal.m` to use the `_conn.txt` label files:

```matlab
% OLD
atlas_names = {'schaefer400_7net', 'schaefer200_7net', 'difumo256_4D'};
atlas_labels = {
    fullfile(ATLAS_DIR, 'schaefer400_7net.txt'),
    fullfile(ATLAS_DIR, 'schaefer200_7net.txt'),
    ''  % DiFuMo doesn't need labels
};

% NEW
atlas_labels = {
    fullfile(ATLAS_DIR, 'schaefer400_7net_conn.txt'),  % ← Changed
    fullfile(ATLAS_DIR, 'schaefer200_7net_conn.txt'),  % ← Changed
    ''  % DiFuMo doesn't need labels
};
```

## Current Status

The running preprocessing script will:
- ✅ Work fine with DiFuMo 256
- ⚠️ Show warnings for Schaefer (but still process)
- Labels will be generic: "ROI 001", "ROI 002", etc. instead of "LH_Vis_1"

This doesn't affect connectivity analysis, only ROI naming in CONN GUI.
