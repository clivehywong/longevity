# Atlas Labels - CONN Format Complete

## Summary

✅ **All three atlases now have proper CONN-formatted label files**

This ensures meaningful ROI names appear in CONN GUI instead of generic "Component 001", "Component 002", etc.

---

## Files Created

### 1. Schaefer 400
- **Atlas**: `schaefer400_7net.nii` (400 cortical ROIs)
- **Labels**: `schaefer400_7net_conn.txt` (401 lines: 0-400)
- **Format**: `ROI_NUMBER ROI_LABEL`
- **Example**:
  ```
  0 Background
  1 LH_Vis_1
  2 LH_Vis_2
  ```

### 2. Schaefer 200
- **Atlas**: `schaefer200_7net.nii` (200 cortical ROIs)
- **Labels**: `schaefer200_7net_conn.txt` (201 lines: 0-200)
- **Format**: `ROI_NUMBER ROI_LABEL`

### 3. DiFuMo 256 ⭐ **PRIMARY**
- **Atlas**: `difumo256_4D.nii` (256 components, includes cerebellum)
- **Labels**: `difumo256_conn.txt` (256 lines: 0-255)
- **Format**: `ROI_NUMBER ROI_LABEL`
- **Example**:
  ```
  0 Middle frontal gyrus anterior LH
  32 Cerebellum IX
  90 Cerebellum Crus I superior
  142 Cerebellum Crus I posterior
  ```

---

## Cerebellar Labels in DiFuMo

All 23 cerebellar components have proper anatomical names:

```
32 Cerebellum IX                          → Vestibular
35 Cerebellum VIIb                        → Cognitive
49 Cerebellum VIIIb posterior             → Motor
68 Cerebellum VIIIb anterior              → Motor
80 Cerebellum Crus I RH                   → Cognitive
90 Cerebellum Crus I superior             → Cognitive
95 Cerebellum IV                          → Motor
142 Cerebellum Crus I posterior           → Cognitive
146 Cerebellum Crus I lateral RH          → Cognitive
153 Cerebellum V                          → Motor
155 Cerebellum Crus II                    → Cognitive
160 Cerebellum VI superior LH             → Motor
171 Cerebellum Crus I anterior LH         → Cognitive
172 Cerebellum VI anterior                → Motor
178 Cerebellum Crus II                    → Cognitive
180 Cerebellum VI                         → Motor
186 Cerebellum VIIb                       → Cognitive
199 Cerebellum V                          → Motor
208 Cerebellum Crus I posterior LH        → Cognitive
210 Cerebellum VI RH                      → Motor
222 Cerebellum VI superior                → Motor
232 Cerebellum VI anterior                → Motor
```

*(Plus 1 CSF component: 164 Fluid between cerebellum and pons)*

---

## Updated Scripts

✅ **`conn_batch_longitudinal.m`** - Updated to include label files

**Changes**:
```matlab
% Added label files
atlas_labels = {
    fullfile(ATLAS_DIR, 'schaefer400_7net_conn.txt'),
    fullfile(ATLAS_DIR, 'schaefer200_7net_conn.txt'),
    fullfile(ATLAS_DIR, 'difumo256_conn.txt')
};

% Added to batch
batch.Setup.rois.labels = atlas_labels;
```

---

## CONN GUI Display

**Before** (without labels):
```
ROI 001
ROI 002
ROI 032
```

**After** (with labels):
```
Middle frontal gyrus anterior LH
Middle frontal gyrus anterior RH
Cerebellum IX
```

---

## Impact on Analysis

**No impact on connectivity values** - only affects:
- CONN GUI ROI names
- Exported timeseries CSV column headers
- Results interpretation (easier to identify ROIs)

---

## Verification

Check label files:
```bash
wc -l /Volumes/Work/Work/long/atlases/*_conn.txt
# Should show:
#  201 schaefer200_7net_conn.txt
#  401 schaefer400_7net_conn.txt
#  256 difumo256_conn.txt
```

Check cerebellar labels:
```bash
grep -i "cerebell" /Volumes/Work/Work/long/atlases/difumo256_conn.txt | wc -l
# Should show: 23
```

---

## Next Steps

Now that labels are fixed, you can:

1. **Resume preprocessing** with proper labels:
   ```bash
   cd /Volumes/Work/Work/long/script
   matlab -nodisplay -nosplash -r "conn_resume_difumo_only; exit"
   ```

2. **Or start fresh** (if you want to rerun from beginning with labels):
   ```bash
   # This would require deleting the existing project
   # Not recommended since realignment/segmentation already complete
   ```

---

## Files Location

All label files in: `/Volumes/Work/Work/long/atlases/`

```
atlases/
├── schaefer400_7net.nii
├── schaefer400_7net_conn.txt          ← NEW
├── schaefer200_7net.nii
├── schaefer200_7net_conn.txt          ← NEW
├── difumo256_4D.nii
├── difumo256_conn.txt                 ← NEW
├── difumo256_network_definitions.json ← Network zones
└── cerebellar_functional_zones_summary.csv
```

---

**Ready to resume preprocessing with proper labels!**
