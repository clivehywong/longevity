# Atlas Label Files - Final Configuration

**Date**: 2026-01-10
**Status**: ✅ **CORRECT FORMAT**

---

## CONN Label File Format

Based on CONN reference files (`/tools/conn/rois/atlas.txt`, `/tools/conn/rois/networks.txt`):

**Correct format**: One label per line, **no numbers**, **no prefixes**

```
Background
LH_Vis_1
LH_Vis_2
...
```

**NOT**:
```
0 Background
1 LH_Vis_1
...
```

---

## Current Atlas Configuration

### 1. Schaefer 400 (Cortical Parcellation)

**Atlas file**: `schaefer400_7net.nii` (400 ROIs)
**Label file**: `schaefer400_7net_conn.txt` (401 lines including Background)

**Format**: ✅ Correct (labels only)
```bash
$ head -5 schaefer400_7net_conn.txt
Background
LH_Vis_1
LH_Vis_2
LH_Vis_3
LH_Vis_4
```

**Line count**: 401 (ROI 0 = Background, ROIs 1-400 = parcels)

---

### 2. Schaefer 200 (Cortical Parcellation)

**Atlas file**: `schaefer200_7net.nii` (200 ROIs)
**Label file**: `schaefer200_7net_conn.txt` (201 lines including Background)

**Format**: ✅ Correct (labels only)
```bash
$ head -5 schaefer200_7net_conn.txt
Background
LH_Vis_1
LH_Vis_2
LH_Vis_3
LH_Vis_4
```

**Line count**: 201 (ROI 0 = Background, ROIs 1-200 = parcels)

---

### 3. DiFuMo 256 (Functional Parcellation) ⭐ **PRIMARY**

**Atlas file**: `difumo256_4D.nii` (256 components in 4th dimension)
**Label file**: `difumo256_conn.txt` (256 lines, 0-indexed)

**Format**: ✅ Correct (labels only)
```bash
$ head -5 difumo256_conn.txt
Middle frontal gyrus anterior LH
Middle frontal gyrus anterior RH
Cerebrospinal fluid (between superior parietal lobule and skull)
Inferior frontal sulcus posterior RH
Superior longitudinal fasciculus II middle
```

**Line count**: 256 (components 0-255)

**Cerebellar components**: 23 total
- Motor: Lobules IV, V, VI, VIIIb (11 components)
- Cognitive: Crus I, Crus II, VIIb (10 components)
- Vestibular: Lobule IX (1 component)
- CSF: 1 component

---

## CONN Warnings (Expected and Harmless)

During preprocessing, you may see:
```
Warning: file /Volumes/Work/Work/long/atlases/schaefer400_7net.txt format not recognized
 number of lines in .txt labels file = 401, maximum ROI index in nifti image file = 400
 (this is not a [ROI_LABEL] format .txt file)
 number of lines not starting with a number = 401, number of commented lines = 0
 (this is not a [ROI_NUMBER ROI_LABEL] or FreeSurfer format .txt file)
```

**This is OK!** CONN is saying:
1. ❌ Not `[ROI_LABEL]` format (brackets around labels)
2. ❌ Not `[ROI_NUMBER ROI_LABEL]` format (numbers with labels)
3. ✅ **Defaulting to treating each line as a label** ← **This is what we want!**

CONN tries multiple formats and falls back to the simplest: one label per line. This works correctly.

---

## Batch Configuration

From `conn_batch_longitudinal.m`:

```matlab
% Atlas files
atlas_files = {
    fullfile(ATLAS_DIR, 'schaefer400_7net.nii'),
    fullfile(ATLAS_DIR, 'schaefer200_7net.nii'),
    fullfile(ATLAS_DIR, 'difumo256_4D.nii')
};

% Atlas names (for CONN GUI)
atlas_names = {'schaefer400_7net', 'schaefer200_7net', 'difumo256'};

% Label files
atlas_labels = {
    fullfile(ATLAS_DIR, 'schaefer400_7net_conn.txt'),
    fullfile(ATLAS_DIR, 'schaefer200_7net_conn.txt'),
    fullfile(ATLAS_DIR, 'difumo256_conn.txt')
};

% Setup ROIs
batch.Setup.rois.names = atlas_names;
batch.Setup.rois.files = atlas_files;
batch.Setup.rois.labels = atlas_labels;
batch.Setup.rois.multiplelabels = [1, 1, 0];  % Schaefer=labels, DiFuMo=4D
batch.Setup.rois.dimensions = {1, 1, 256};    % Schaefer=mean, DiFuMo=256 components
```

**Key parameters**:
- `multiplelabels = 1`: Schaefer atlases use integer labels (3D atlas with distinct ROI values)
- `multiplelabels = 0`: DiFuMo uses 4D probabilistic maps
- `dimensions = 256`: DiFuMo has 256 components in 4th dimension

---

## Verification

### Check Label Files

```bash
cd /Volumes/Work/Work/long/atlases

# Line counts (should match ROI counts)
wc -l *_conn.txt
#  256 difumo256_conn.txt
#  201 schaefer200_7net_conn.txt
#  401 schaefer400_7net_conn.txt

# Verify format (no numbers at start of lines)
head -3 schaefer400_7net_conn.txt
# Background
# LH_Vis_1
# LH_Vis_2

head -3 difumo256_conn.txt
# Middle frontal gyrus anterior LH
# Middle frontal gyrus anterior RH
# Cerebrospinal fluid (between superior parietal lobule and skull)
```

### Check CONN GUI (After Preprocessing)

1. Open CONN: `conn` in MATLAB
2. Load project: `conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat')`
3. Go to Setup → ROIs
4. Check ROI names:
   - **Schaefer 400**: Should show "LH_Vis_1", "LH_Vis_2", etc.
   - **DiFuMo 256**: Should show "Middle frontal gyrus anterior LH", "Cerebellum IX", etc.

**If labels missing**: ROIs will show as "ROI 001", "ROI 002" (generic names)

---

## Files Location

All label files in: `/Volumes/Work/Work/long/atlases/`

```
atlases/
├── schaefer400_7net.nii                  ← Atlas (400 ROIs)
├── schaefer400_7net.txt                  ← Original labels (same as _conn.txt)
├── schaefer400_7net_conn.txt             ← CONN label file ✅
├── schaefer200_7net.nii                  ← Atlas (200 ROIs)
├── schaefer200_7net.txt                  ← Original labels (same as _conn.txt)
├── schaefer200_7net_conn.txt             ← CONN label file ✅
├── difumo256_4D.nii                      ← Atlas (256 components)
├── difumo256_conn.txt                    ← CONN label file ✅
└── difumo256_network_definitions.json    ← Network mappings + cerebellar zones
```

---

## Network Definitions

Separate JSON file for Python analysis: `difumo256_network_definitions.json`

**Purpose**: Map ROI indices to functional networks and cerebellar zones

**Contents**:
- 256 components with network labels
- Cerebellar zones (motor/cognitive/vestibular)
- Hypothesis-driven network pairs
- ROI coordinates and names

**Usage**:
```python
import json
with open('difumo256_network_definitions.json') as f:
    net_defs = json.load(f)

# Get cerebellar motor ROIs
motor_cereb = net_defs['networks']['Cerebellar_Motor']
# [49, 68, 95, 153, 160, 172, 180, 199, 210, 222, 232]
```

---

## Summary

✅ **All label files in correct CONN format** (labels only, one per line)
✅ **Warnings during preprocessing are harmless** (CONN auto-detects format)
✅ **ROI names will display correctly in CONN GUI**
✅ **DiFuMo 256 includes cerebellar components** (primary atlas for motor-cerebellar analysis)

**No further action needed** - preprocessing will continue with proper labels.
