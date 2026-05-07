# Subject-Level Seed Connectivity Analysis - Code Review

## Implementation Overview

**File**: `script/compute_seed_connectivity_xcpd.py`

### What It Does:
1. Uses XCP-D preprocessed BOLD outputs (denoised or denoised+smoothed)
2. Extracts seed timeseries (from atlas parcels, sphere, or custom NIfTI ROI)
3. Computes seed-to-parcel connectivity (multiple measures: Pearson, Spearman, PLV, wPLI, etc.)
4. Computes seed-to-voxel Fisher-z maps (Pearson correlation only)

### Data Sources:
- **Input BOLD**: `derivatives/preprocessing/xcpd/{pipeline}/sub-XX/ses-YY/func/`
  - File: `*_space-MNI152NLin6Asym_res-2_desc-denoised_bold.nii.gz` OR
  - File: `*_space-MNI152NLin6Asym_res-2_desc-denoisedSmoothed_bold.nii.gz`
- **Seed Timeseries**: From XCP-D atlas mean timeseries TSVs (already extracted)

### Seed-to-Voxel Computation (`_compute_seed_to_voxel_zmap`)

Lines 309-342:

```python
def _compute_seed_to_voxel_zmap(seed_ts, bold_data, bold_img):
    # 1. Reshape BOLD to (n_voxels, n_timepoints)
    voxels = bold_data.reshape(n, T)
    
    # 2. Demean seed timeseries
    seed_dm = seed_ts - seed_ts.mean()
    seed_norm = np.linalg.norm(seed_dm)
    
    # 3. Demean all voxels
    vox_mean = voxels.mean(axis=1, keepdims=True)
    voxels_dm = voxels - vox_mean
    vox_norms = np.linalg.norm(voxels_dm, axis=1)
    
    # 4. Compute Pearson correlation (voxel-wise)
    r = (voxels_dm @ seed_dm) / (vox_norms * seed_norm)
    
    # 5. Fisher-z transform
    z = arctanh(clip(r, -1+eps, 1-eps))
    
    # 6. Return as NIfTI image
    return NIfTI(z, affine)
```

## Potential Issues

### 🔴 **No Temporal Filtering**
- **Missing**: No bandpass filtering (typically 0.01-0.1 Hz for resting-state)
- **Missing**: No high-pass filtering to remove low-frequency drift
- **Result**: Low-frequency noise and scanner drift can dominate the signal

**Example from connectivity_measures.py**:
- Other measures (PLV, wPLI, coherence) DO apply bandpass filtering
- But seed-to-voxel does NOT

### 🔴 **No Confound Regression**
- **Input**: XCP-D "denoised" BOLD already has some denoising applied
- **BUT**: Seed-to-voxel does not apply any residual confound regression
- **Missing**: Motion regression, CSF/white matter regression
- **Result**: Motion-related noise and physiological artifacts remain

### 🟡 **Denoising Variant Choice**
- Script allows choosing between:
  - "denoised" — less aggressive denoising
  - "denoisedSmoothed" — more aggressive denoising + spatial smoothing
- Default is "denoisedSmoothed"
- If "denoised" is used without filtering, result will have MORE noise

### 🟡 **Seed Timeseries is Already Preprocessed**
- Seed timeseries comes from XCP-D atlas mean TSVs
- XCP-D has already done some denoising
- But again: no explicit high-pass filtering in seed-to-voxel computation

## Why It Might Show "Only Noise"

1. **No Filtering**: Raw denoised BOLD contains significant low-frequency components (scanner drift, physiological noise not removed by denoising)

2. **Motion Not Regressed**: Even with XCP-D denoising, seed-to-voxel doesn't explicitly handle residual motion effects

3. **Comparison to Standard Methods**:
   - Standard fMRI connectivity tools typically apply:
     - High-pass filtering (0.01 Hz)
     - Motion regression (6 parameters or ICA-AROMA)
     - Low-pass filtering (0.1 Hz)
   - This script does none of that

4. **XCP-D Philosophy**:
   - XCP-D is designed for **parcel-level** connectivity (atlas-based)
   - Individual parcels already have denoising applied
   - Voxel-level connectivity on denoised BOLD is less common and less validated

## Code Flow

```
Input: XCP-D denoised BOLD + seed timeseries (atlas parcel)
  ↓
No preprocessing applied
  ↓
Voxel-wise Pearson correlation computed
  ↓
Fisher-z transformed
  ↓
Output: Noisy z-map (dominated by low-frequency components)
```

## What Would Fix It

Option 1: **Apply Filtering**
- Add high-pass filtering (remove DC and low-frequency drift)
- Add temporal smoothing or band-pass filtering

Option 2: **Apply Confound Regression**
- Regress out motion parameters
- Regress out mean CSF/WM signal

Option 3: **Use Parcel-Level Analysis**
- Use seed-to-parcel TSV outputs instead
- These are already properly denoised by XCP-D

Option 4: **Different Input Data**
- Use preprocessed BOLD from fMRIPrep that has explicit confound regression
- Then apply your own filtering

## Conclusion

The seed-to-voxel analysis is **bare-bones**:
- ✅ Correctly computes Pearson correlation
- ✅ Correctly applies Fisher-z transform
- ❌ No temporal filtering
- ❌ No confound regression
- ❌ No physiological noise removal

For resting-state fMRI, this typically results in maps dominated by low-frequency noise and motion artifacts.
