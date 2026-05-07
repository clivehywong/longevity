# Nilearn & Nibabel Integration Skill

## 1. Introduction: Nilearn vs Nibabel

**Nibabel** (NIfTI and ANALYZE formats handler):
- Low-level NIfTI file I/O, header/affine manipulation
- Direct voxel access and coordinate transforms
- **When to use**: File I/O, affine surgery, quick voxel operations, saving processed images

**Nilearn** (Brain imaging analysis):
- High-level neuroimaging workflows (smoothing, masking, timeseries extraction)
- Visualization (glass brain, statistical overlays)
- Built on nibabel; abstracts away affine complexity
- **When to use**: Most brain image operations, atlas handling, connectivity pipelines

**Project context** (longevity, resting-state fMRI):
- TR = 0.8s, 480 volumes per session
- Output spaces: MNI152NLin2009cAsym:res-2 (primary), T1w
- Atlases: DiFuMo 256, Schaefer 400 (local_measures, connectivity)
- Typical workflow: Load preprocessed → smooth → mask → extract timeseries/stats

---

## 2. Nibabel Essentials

### Loading & Saving NIfTI Files

```python
import nibabel as nib
import numpy as np

# Load a NIfTI image
img = nib.load('path/to/image.nii.gz')

# Access the image data (4D array for fMRI: x, y, z, t)
data = img.get_fdata()  # Returns float64
data_uint8 = img.get_data_dtype()  # Check original dtype

# Get affine (voxel-to-world coordinate transformation)
affine = img.affine  # 4x4 matrix

# Get header for metadata (TR, voxel size, orientation)
header = img.header
print(header.get_zooms())  # Voxel dimensions in mm (x, y, z, t)
print(header.get_data_shape())  # Array shape

# Save image back to disk
nib.save(img, 'output/image.nii.gz')

# Create new NIfTI from data + affine
new_img = nib.Nifti1Image(data, affine, header)
nib.save(new_img, 'output/new_image.nii.gz')
```

### Coordinate Systems: Voxel vs World (LPI vs RAS)

```python
# Nibabel uses LPI convention (Left-Posterior-Inferior)
# Affine maps voxel indices to world coordinates (mm)

# Voxel-to-world (point at voxel i,j,k):
voxel_coord = np.array([10, 20, 15, 1])  # Homogeneous coords (x,y,z,1)
world_coord = affine @ voxel_coord  # Result: (x_mm, y_mm, z_mm, 1)

# World-to-voxel (reverse):
affine_inv = np.linalg.inv(affine)
voxel_from_world = affine_inv @ world_coord

# Typical MNI152 affine for 2mm resolution:
# [[  2   0   0 -90]
#  [  0   2   0-126]
#  [  0   0   2 -72]
#  [  0   0   0   1]]
```

### Resampling to Standard Space (MNI152)

```python
# Load target template in MNI space
template = nib.load('/path/to/fmriprep/tpl-MNI152NLin2009cAsym_res-2_T1w.nii.gz')
template_affine = template.affine

# Use scipy.ndimage for resampling (nibabel utility)
from scipy import ndimage

# Resample source image to template grid
source_img = nib.load('source_native_space.nii.gz')
source_data = source_img.get_fdata()

# Calculate transform from source to template space
source_to_template = np.linalg.inv(source_img.affine) @ template_affine

# Apply resampling
resampled_data = ndimage.affine_transform(
    source_data,
    matrix=np.linalg.inv(source_to_template)[:3, :3],
    offset=np.linalg.inv(source_to_template)[:3, 3],
    output_shape=template.shape[:3],
    order=1,  # Linear interpolation
    mode='constant',
    cval=0
)

resampled_img = nib.Nifti1Image(resampled_data, template_affine)
nib.save(resampled_img, 'output_mni_space.nii.gz')
```

### Squeezing Singleton Dimensions (BIDS Compliance)

```python
# Remove dimensions of size 1 (e.g., 91x109x91x1 -> 91x109x91)
data = img.get_fdata()
data_squeezed = np.squeeze(data)
affine_squeezed = img.affine

# Create new image without singleton dims
img_squeezed = nib.Nifti1Image(data_squeezed, affine_squeezed)
nib.save(img_squeezed, 'output_squeezed.nii.gz')

# Verify shape
print(img_squeezed.shape)  # Should be 3D or 4D, no singleton dims
```

---

## 3. Nilearn Brain Imaging

### Loading and Lazy Loading

```python
from nilearn import image
from nilearn import plotting

# Load with nibabel backend (full load into memory)
img = image.load_img('fmriprep/sub-001/ses-01/func/preproc_bold.nii.gz')
data = img.get_fdata()  # Now in memory, 4D: (x, y, z, t)

# For large 4D files (memory concerns), use lazy loading:
# Nilearn's masking functions accept file paths directly
# and load data on-the-fly in chunks (no full 4D array in RAM)
from nilearn import masking
brain_mask = masking.compute_brain_mask(
    'fmriprep/sub-001/ses-01/func/preproc_bold.nii.gz',
    threshold=0.5
)
# Mask is computed without holding full 4D array in memory
```

### Gaussian Smoothing

```python
from nilearn import image

# Smooth with 6mm FWHM Gaussian kernel
smoothed_img = image.smooth_img(
    'input_func.nii.gz',
    fwhm=6.0  # Full width at half maximum in mm
)

# For 4D timeseries, applies kernel to each volume
nilearn.image.smooth_img(
    'bold_4d.nii.gz',
    fwhm=6.0
)
# Output shape matches input shape

# Specify affine explicitly (rarely needed)
smoothed = image.smooth_img(
    img_data,
    fwhm=6.0,
    image_interpolation='continuous'  # or 'nearest'
)
```

### Resampling to Atlas/Target Space

```python
from nilearn import image

# Resample source image to match target image grid
source_img = 'source_native_space.nii.gz'
target_img = 'target_atlas_mni.nii.gz'

resampled = image.resample_to_img(
    source_img,
    target_img,
    interpolation='continuous'  # 'continuous' for weighted data, 'nearest' for labels
)

# Often used for atlas resampling:
resampled_atlas = image.resample_to_img(
    atlas_mni_space,
    subject_native_space,
    interpolation='nearest'  # Preserve integer labels
)
```

### Brain Masking

```python
from nilearn import masking

# Compute brain mask from 4D functional data
brain_mask = masking.compute_brain_mask(
    'fmriprep/sub-001/func/preproc_bold.nii.gz',
    threshold=0.5,
    connected_label=True  # Remove small isolated voxels
)

# Apply mask to extract timeseries (removes out-of-brain voxels)
masked_data = masking.apply_mask(
    'fmriprep/sub-001/func/preproc_bold.nii.gz',
    brain_mask
)
# Output shape: (n_voxels, n_timepoints)
# n_voxels ≈ 200k-400k for typical brain mask

# Unmask back to 3D/4D space
unmasked_4d = masking.unmask(
    masked_data,
    brain_mask
)
# Output shape matches original (91, 109, 91, 480)
```

### Image Math: Binarization and Thresholding

```python
from nilearn import image
import nibabel as nib
import numpy as np

# Load statistical map
stat_map = nib.load('seed_correlation_map.nii.gz')
stat_data = stat_map.get_fdata()

# Threshold at correlation > 0.3
thresholded = np.where(stat_data > 0.3, stat_data, 0)
thresholded_img = nib.Nifti1Image(thresholded, stat_map.affine)

# Binarize (convert to 0/1)
binary = np.where(stat_data > 0.3, 1, 0)
binary_img = nib.Nifti1Image(binary, stat_map.affine)

# Absolute value (useful for correlation maps that can be negative)
abs_stat = np.abs(stat_data)
abs_img = nib.Nifti1Image(abs_stat, stat_map.affine)

# Mask out zeros and small values
from scipy import ndimage
labeled, num_features = ndimage.label(binary)
sizes = ndimage.sum(binary, labeled, range(num_features + 1))
mask = sizes > 10  # Keep clusters with >10 voxels
binary_cleaned = np.isin(labeled, np.where(mask)[0])
```

---

## 4. Atlas Handling

### Fetching Standard Atlases

```python
from nilearn import datasets

# DiFuMo 256 (256 intrinsic components, recommended for resting-state)
difumo_atlas = datasets.fetch_atlas_difumo(
    dimension=256,
    resolution_mm=2,  # Match fMRIPrep resolution
    maps_dir=None,  # Use default cache (~/.cache/nilearn_data)
    resume=True,
    verbose=1
)
difumo_maps = difumo_atlas['maps']  # Path to 4D NIfTI (91x109x91x256)
difumo_labels = difumo_atlas['labels']  # List of 256 component names

# Schaefer 400 parcellation (400 regions, good for connectivity)
schaefer_atlas = datasets.fetch_atlas_schaefer_2018(
    n_rois=400,
    yeo_networks=7,  # 7-network or 17-network partition
    resolution_mm=2,
    data_dir=None,
    resume=True,
    verbose=1
)
schaefer_maps = schaefer_atlas['maps']  # Path to 3D NIfTI

# AAL atlas (Automated Anatomical Labeling, 116 regions)
aal_atlas = datasets.fetch_atlas_aal(
    version='SPM12',
    data_dir=None,
    resume=True,
    verbose=1
)
aal_maps = aal_atlas['maps']  # 3D label image
aal_labels = aal_atlas['labels']  # List of region names
```

### Resampling Atlases to Subject Space

```python
from nilearn import image
import nibabel as nib

# Load subject's native-space reference (e.g., T1w)
native_ref = nib.load('fmriprep/sub-001/ses-01/anat/sub-001_T1w.nii.gz')

# Load atlas in MNI space (from fetch)
atlas_mni = 'difumo_256_2mm.nii.gz'

# Resample atlas to subject's native space
# Use 'nearest' to preserve integer labels
atlas_native = image.resample_to_img(
    atlas_mni,
    native_ref,
    interpolation='nearest'
)

# Verify resampling
atlas_native_data = atlas_native.get_fdata()
print(f"Unique atlas labels: {len(np.unique(atlas_native_data)) - 1}")  # -1 for background (0)
```

### Extracting Labels and Indices

```python
import numpy as np
import nibabel as nib

# Load atlas
atlas = nib.load('difumo_256_2mm.nii.gz')
atlas_data = atlas.get_fdata()

# Extract voxel indices for each region
def get_region_voxels(atlas_data, region_id):
    """Return (i, j, k) voxel coordinates for a given region."""
    return np.where(atlas_data == region_id)

# Example: Get voxels in region 42
region_42_voxels = get_region_voxels(atlas_data, 42)
print(f"Region 42 has {len(region_42_voxels[0])} voxels")

# Get centroid (center of mass) of a region
from scipy import ndimage
mask = atlas_data == 42
centroid_voxel = ndimage.center_of_mass(mask.astype(float))
centroid_world = atlas.affine @ (*centroid_voxel, 1)
print(f"Region 42 centroid (world coords): {centroid_world[:3]} mm")

# List all unique regions
unique_regions = np.unique(atlas_data)
print(f"Total regions: {len(unique_regions) - 1}")  # -1 for background
```

---

## 5. Timeseries Extraction

### ROI-Based Extraction with apply_mask

```python
from nilearn import masking
import numpy as np

# Load ROI mask (binary image: 1 inside ROI, 0 outside)
roi_mask = 'seed_region_mask.nii.gz'  # e.g., sphere around MNI coord (0,0,0)

# Load 4D functional data
bold_4d = 'fmriprep/sub-001/ses-01/func/preproc_bold.nii.gz'

# Extract timeseries (mean signal within ROI across all timepoints)
roi_timeseries = masking.apply_mask(bold_4d, roi_mask)
# Output shape: (n_timepoints,) = (480,) for single ROI
# For multiple ROIs, roi_mask should be 3D with integer labels (1, 2, 3, ...)
# Then output shape: (n_rois, n_timepoints)

print(f"Timeseries shape: {roi_timeseries.shape}")
print(f"Mean signal in ROI: {roi_timeseries.mean():.2f}")

# Extract for multiple ROIs (atlas-based)
atlas_mask = 'difumo_256_resampled_to_subject.nii.gz'  # Integer labels 1-256
atlas_timeseries = masking.apply_mask(bold_4d, atlas_mask)
# Output shape: (256, 480)
# Row i is mean timeseries for region i
```

### Creating ROI Masks from Coordinates

```python
from nilearn import datasets
from nilearn.regions import SpheresMasker
import nibabel as nib
import numpy as np

# Define seed regions (MNI coordinates)
seed_coords = [
    (0, 0, 0),  # Midline seed
    (8, -50, 8),  # Posterior cingulate cortex (PCC)
    (-6, 50, 8),  # Medial prefrontal cortex (mPFC)
]

# Create sphere masks around each coordinate
masker = SpheresMasker(
    radius=5,  # 5mm radius sphere
    standardize=True,  # Z-score normalize timeseries
    detrend=False  # Already detrended in fMRIPrep
)

# Extract timeseries for each seed
bold_4d = 'fmriprep/sub-001/ses-01/func/preproc_bold.nii.gz'
seeds_timeseries = masker.fit_transform(bold_4d)
# Output shape: (480, 3) — 480 timepoints, 3 seeds

# Create binary mask for first seed (useful for visualization)
mask_img = masker.mask_img_
mask_data = mask_img.get_fdata()
seed_mask_0 = np.where(mask_data > 0, 1, 0).astype(np.uint8)
seed_mask_img = nib.Nifti1Image(seed_mask_0, mask_img.affine)
nib.save(seed_mask_img, 'seed_0_mask.nii.gz')
```

### Handling 4D Timeseries Data

```python
import numpy as np
from nilearn import masking

# Load 4D data (x, y, z, t)
bold_4d = masking.load_masker_data('bold.nii.gz')  # (91, 109, 91, 480)

# Ensure it's truly 4D (handle edge cases)
if bold_4d.ndim == 3:
    # Add time dimension if missing
    bold_4d = bold_4d[:, :, :, np.newaxis]

# Reshape to 2D: (n_voxels, n_timepoints)
n_voxels = np.prod(bold_4d.shape[:3])
n_timepoints = bold_4d.shape[3]
bold_2d = bold_4d.reshape(n_voxels, n_timepoints)

# Remove low-variance voxels (likely noise outside brain)
variance = bold_2d.var(axis=1)
keep_idx = variance > np.percentile(variance, 10)
bold_2d_filtered = bold_2d[keep_idx, :]

# De-mean and standardize
bold_z = (bold_2d_filtered - bold_2d_filtered.mean(axis=1, keepdims=True)) / bold_2d_filtered.std(axis=1, keepdims=True)

print(f"Shape: voxels={bold_z.shape[0]}, timepoints={bold_z.shape[1]}")
print(f"Mean={bold_z.mean():.4f}, Std={bold_z.std():.4f}")
```

---

## 6. Statistical Maps

### Z-Score Normalization

```python
import numpy as np
import nibabel as nib

# Load a statistical map (e.g., correlation map)
stat_map = nib.load('correlation_map.nii.gz')
stat_data = stat_map.get_fdata()

# Z-score normalize (subtract mean, divide by std)
# Exclude zero voxels (background)
nonzero = stat_data[stat_data != 0]

z_score_data = np.zeros_like(stat_data)
z_score_data[stat_data != 0] = (stat_data[stat_data != 0] - nonzero.mean()) / nonzero.std()

z_score_img = nib.Nifti1Image(z_score_data, stat_map.affine)
nib.save(z_score_img, 'z_score_map.nii.gz')

print(f"Z-scored data: mean={z_score_data[z_score_data != 0].mean():.4f}, std={z_score_data[z_score_data != 0].std():.4f}")
```

### Creating Seed-Based Correlation Maps

```python
import numpy as np
from nilearn import masking
import nibabel as nib

# Load seed timeseries and whole-brain 4D data
seed_coords = (-6, 50, 8)  # mPFC
radius = 5

# Method 1: Use SpheresMasker for seed extraction
from nilearn.regions import SpheresMasker
seed_masker = SpheresMasker(radius=radius)
seed_ts = seed_masker.fit_transform('bold_4d.nii.gz').mean(axis=1)  # Average across seed voxels

# Extract whole-brain timeseries (voxel × time)
brain_mask = masking.compute_brain_mask('bold_4d.nii.gz')
whole_brain_ts = masking.apply_mask('bold_4d.nii.gz', brain_mask)
# Shape: (n_brain_voxels, 480)

# Compute correlation between seed and each voxel
seed_ts_norm = (seed_ts - seed_ts.mean()) / seed_ts.std()
correlations = np.corrcoef(seed_ts_norm, whole_brain_ts)[0, 1:]
# Shape: (n_brain_voxels,)

# Unmask back to 3D
corr_map_3d = masking.unmask(correlations, brain_mask)

# Fisher Z-transform for better statistics
z_transform = 0.5 * np.log((1 + correlations) / (1 - correlations))
z_map_3d = masking.unmask(z_transform, brain_mask)

# Save
nib.save(corr_map_3d, 'seed_correlation_map.nii.gz')
nib.save(z_map_3d, 'seed_z_transform_map.nii.gz')
```

### Thresholding and Multiple Comparison Correction

```python
import numpy as np
import nibabel as nib
from scipy import stats

# Load correlation map
corr_map = nib.load('seed_correlation_map.nii.gz')
corr_data = corr_map.get_fdata()

# Simple threshold (e.g., r > 0.3)
threshold_simple = np.where(corr_data > 0.3, corr_data, 0)

# FDR correction (False Discovery Rate)
# Convert correlation to p-value first
from scipy.stats import pearsonr
n_timepoints = 480
r_values = corr_data[corr_data != 0]
t_values = r_values * np.sqrt(n_timepoints - 2) / np.sqrt(1 - r_values**2)
p_values = 2 * (1 - stats.t.cdf(np.abs(t_values), n_timepoints - 2))

# FDR correction using Benjamini-Hochberg method
from statsmodels.stats.multitest import multipletests
rejected, corrected_p, _, _ = multipletests(p_values, alpha=0.05, method='fdr_bh')

# Reconstruct thresholded map
threshold_fdr = np.zeros_like(corr_data)
threshold_fdr[corr_data != 0] = corr_data[corr_data != 0] * rejected.astype(float)

# Bonferroni correction (stringent)
bonferroni_threshold = 0.05 / len(p_values)
rejected_bonf, _, _, _ = multipletests(p_values, alpha=bonferroni_threshold, method='bonferroni')
threshold_bonf = np.zeros_like(corr_data)
threshold_bonf[corr_data != 0] = corr_data[corr_data != 0] * rejected_bonf.astype(float)

# Save thresholded maps
nib.save(nib.Nifti1Image(threshold_fdr, corr_map.affine), 'corr_fdr_thresholded.nii.gz')
nib.save(nib.Nifti1Image(threshold_bonf, corr_map.affine), 'corr_bonferroni_thresholded.nii.gz')
```

---

## 7. Coordinate Transforms

### Subject to MNI Space Transformation

```python
import numpy as np
import nibabel as nib
from scipy.ndimage import affine_transform

# Assume you have a subject-native-space image and a transform to MNI
# fMRIPrep produces these in the subject func directory

# Load subject's native BOLD and its affine
subject_bold = nib.load('sub-001_ses-01_bold_native.nii.gz')
subject_affine = subject_bold.affine

# Load MNI template (fMRIPrep provides a template reference)
mni_template = nib.load('tpl-MNI152NLin2009cAsym_res-2_T1w.nii.gz')
mni_affine = mni_template.affine

# If image is already in MNI space (typical for fMRIPrep output), it's already registered
# Otherwise, use the warp file from ANTs/fMRIPrep
# This requires loading the warp deformation field (advanced)

# Simpler: Use fMRIPrep's pre-computed native→MNI image
mni_bold = nib.load('sub-001_ses-01_bold_space-MNI152NLin2009cAsym_res-2.nii.gz')
print(f"MNI-space shape: {mni_bold.shape}")
```

### Affine Matrix Manipulation

```python
import numpy as np

# Standard MNI affine (2mm resolution, origin at brain anterior-left-inferior)
mni_affine_2mm = np.array([
    [2.0, 0.0, 0.0, -90.0],
    [0.0, 2.0, 0.0, -126.0],
    [0.0, 0.0, 2.0, -72.0],
    [0.0, 0.0, 0.0, 1.0]
])

# Extract components
scale = np.diag(mni_affine_2mm[:3, :3])  # (2, 2, 2) — voxel size
translation = mni_affine_2mm[:3, 3]  # (-90, -126, -72) — origin in world coords

# Create custom affine (e.g., for 3mm resolution)
custom_affine_3mm = np.array([
    [3.0, 0.0, 0.0, -90.0],
    [0.0, 3.0, 0.0, -126.0],
    [0.0, 0.0, 3.0, -72.0],
    [0.0, 0.0, 0.0, 1.0]
])

# Compose affines (concatenate transforms)
# If transform A maps voxel→world and B maps world→canonical:
# Combined = B @ A
transform_1 = np.eye(4)  # Identity (no transform)
transform_2 = mni_affine_2mm
combined = transform_2 @ transform_1

# Invert affine (world→voxel)
affine_inv = np.linalg.inv(mni_affine_2mm)
print("Inverse affine (world→voxel):")
print(affine_inv)
```

### Reverse Transforms (MNI to Subject)

```python
import numpy as np
import nibabel as nib
from scipy.ndimage import affine_transform as scipy_affine_transform

# Load MNI-space statistical map
mni_stat_map = nib.load('stat_map_mni.nii.gz')
mni_data = mni_stat_map.get_fdata()
mni_affine = mni_stat_map.affine

# Load subject's native T1w to define target space
native_t1 = nib.load('sub-001_T1w.nii.gz')
native_shape = native_t1.shape[:3]
native_affine = native_t1.affine

# Compute transform from MNI to native space
# This is NOT a simple affine (requires actual deformation field)
# For an approximation, compose the affines:
transform_matrix = np.linalg.inv(native_affine) @ mni_affine

# Apply (expensive; typically requires warp fields from fMRIPrep)
# In practice, use fMRIPrep's pre-computed inverse warps
native_stat_map_data = scipy_affine_transform(
    mni_data,
    matrix=transform_matrix[:3, :3],
    offset=transform_matrix[:3, 3],
    output_shape=native_shape,
    order=1,
    mode='constant',
    cval=0
)

native_stat_map = nib.Nifti1Image(native_stat_map_data, native_affine)
nib.save(native_stat_map, 'stat_map_native.nii.gz')
```

### Multi-Session Alignment

```python
import numpy as np
import nibabel as nib
from nilearn import image

# For longitudinal studies (longevity: sub-XXX/ses-01 and ses-02)
# fMRIPrep already registers each session to MNI independently
# To compare sessions, either:

# Option 1: Work in MNI space (recommended, simpler)
ses_01_mni = nib.load('sub-001_ses-01_bold_space-MNI152NLin2009cAsym.nii.gz')
ses_02_mni = nib.load('sub-001_ses-02_bold_space-MNI152NLin2009cAsym.nii.gz')
# Both are already in common MNI space → can compare directly

# Option 2: Average across sessions in native space (requires reverse warps)
# Load native space BIOLDs
ses_01_native = nib.load('sub-001_ses-01_bold_native.nii.gz')
ses_02_native = nib.load('sub-001_ses-02_bold_native.nii.gz')

# Resample ses-02 native to ses-01 native space
ses_02_resampled = image.resample_to_img(ses_02_native, ses_01_native)

# Average (example: mean across sessions)
avg_data = (ses_01_native.get_fdata() + ses_02_resampled.get_fdata()) / 2
avg_img = nib.Nifti1Image(avg_data, ses_01_native.affine)
nib.save(avg_img, 'sub-001_avg_sessions.nii.gz')
```

---

## 8. Visualization

### Static Plots

```python
from nilearn import plotting
import matplotlib.pyplot as plt
import nibabel as nib

# Plot statistical map (e.g., seed-based correlation)
stat_map = 'seed_correlation_map.nii.gz'

# Glass brain (projected view, good for overview)
fig = plotting.plot_glass_brain(
    stat_map,
    display_mode='lzr',  # Left-Anterior-Right view
    threshold=0.3,  # Only show correlations > 0.3
    colorbar=True,
    title='Seed-Based Connectivity (r > 0.3)'
)
plt.savefig('glassbrains_seed_connectivity.png', dpi=150, bbox_inches='tight')

# Orthogonal slices (3 planes: sagittal, coronal, axial)
fig = plotting.plot_img(
    stat_map,
    threshold=0.3,
    colorbar=True,
    title='Seed Connectivity Map'
)
plt.savefig('orthoslices_seed_connectivity.png', dpi=150, bbox_inches='tight')

# ROI overlay (atlas regions on background)
atlas = 'difumo_256_2mm.nii.gz'
fig = plotting.plot_roi(
    atlas,
    colorbar=True,
    cmap='tab20',
    draw_cross=True
)
plt.savefig('atlas_roi_overlay.png', dpi=150, bbox_inches='tight')

plt.close('all')
```

### Overlay Plots (Statistical Map + Atlas)

```python
from nilearn import plotting
import matplotlib.pyplot as plt

# Combine a statistical map (color) with an atlas (contours)
stat_map = 'seed_correlation_map.nii.gz'
atlas = 'difumo_256_2mm.nii.gz'

# Plot stat map as background
fig = plotting.plot_img(
    stat_map,
    threshold=0.2,
    colorbar=True,
    cmap='viridis'
)

# Overlay atlas contours
fig.add_contours(
    atlas,
    levels=[1],  # Draw contours at specific atlas levels
    colors='red',
    linewidths=1
)

plt.title('Seed Correlation + Atlas Overlay')
plt.savefig('overlay_seed_atlas.png', dpi=150, bbox_inches='tight')
plt.close()
```

### HTML Report Generation

```python
from nilearn import reporting, plotting, datasets
import nibabel as nib
import os

# Create an HTML report with multiple views
stat_maps = [
    'seed_correlation_mPFC.nii.gz',
    'seed_correlation_PCC.nii.gz'
]

html_report = reporting.make_glm_report(
    contrast_map=stat_maps[0],  # Primary map
    title='Seed-Based Connectivity Report',
    threshold=0.2
)

# Save report
report_file = 'connectivity_report.html'
with open(report_file, 'w') as f:
    f.write(html_report)

print(f"Report saved to {report_file}")

# Alternative: Create custom multi-view HTML
def create_custom_report(stat_maps, output_file):
    """Create HTML report with multiple statistical maps."""
    html_lines = [
        '<!DOCTYPE html>',
        '<html>',
        '<head><title>fMRI Connectivity Report</title></head>',
        '<body style="margin:20px;">',
        '<h1>Seed-Based Connectivity Analysis</h1>',
    ]
    
    for i, stat_map in enumerate(stat_maps):
        # Create PNG for each map
        png_file = f'map_{i}.png'
        plotting.plot_glass_brain(stat_map, output_file=png_file, threshold=0.2)
        html_lines.append(f'<h2>Map {i+1}</h2>')
        html_lines.append(f'<img src="{png_file}" width="800" />')
    
    html_lines.extend([
        '</body>',
        '</html>'
    ])
    
    with open(output_file, 'w') as f:
        f.write('\n'.join(html_lines))

create_custom_report(stat_maps, 'custom_connectivity_report.html')
```

---

## 9. Code Examples: Real Use Cases

### Load fALFF Map and Overlay Atlas

```python
"""
Example: Load locally computed fALFF map and overlay atlas for verification.
Typical output: fALFF_2mm_mni.nii.gz
"""
import nibabel as nib
from nilearn import plotting, datasets
from nilearn import image
import numpy as np

# Load fALFF map (from local_measures pipeline)
falff_map = nib.load('results/local_measures/fALFF_2mm_mni.nii.gz')

# Fetch DiFuMo atlas
difumo = datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2)
atlas_path = difumo['maps']

# Plot with glass brain
fig = plotting.plot_glass_brain(
    falff_map,
    threshold=np.percentile(falff_map.get_fdata(), 90),  # Top 10%
    colorbar=True,
    cmap='hot',
    title='fALFF Map (Global Signal Removed)'
)

# Add atlas contours
fig.add_contours(atlas_path, colors='cyan', linewidths=0.5)

plotting.show()
```

### Seed-Based Connectivity Map Extraction

```python
"""
Extract seed-based connectivity map for ROI at MNI coordinates.
Output: seed_connectivity_map.nii.gz (correlation map)
"""
import numpy as np
from nilearn import masking
from nilearn.regions import SpheresMasker
import nibabel as nib

# Define seed (example: mPFC at MNI -6, 50, 8)
seed_coords = [(-6, 50, 8)]
radius = 5  # 5mm radius sphere

# Extract seed timeseries
seed_masker = SpheresMasker(seed_coords, radius=radius, standardize=True)
seed_ts = seed_masker.fit_transform('fmriprep/sub-001_ses-01_bold_mni.nii.gz')
seed_ts = seed_ts.squeeze()  # (480,)

# Load whole-brain timeseries
bold_path = 'fmriprep/sub-001_ses-01_bold_mni.nii.gz'
brain_mask = masking.compute_brain_mask(bold_path)
whole_brain_ts = masking.apply_mask(bold_path, brain_mask)  # (n_voxels, 480)

# Compute correlation
from scipy.stats import pearsonr
correlations = np.array([
    pearsonr(seed_ts, whole_brain_ts[i, :])[0]
    for i in range(whole_brain_ts.shape[0])
])

# Unmask and save
corr_map = masking.unmask(correlations, brain_mask)
nib.save(corr_map, 'seed_connectivity_mPFC.nii.gz')
print("Seed connectivity map saved.")
```

### Multi-Subject Atlas Resampling

```python
"""
Resample DiFuMo atlas to each subject's native space for timeseries extraction.
Required: BIDS directory with preprocessed data.
"""
import os
import nibabel as nib
from nilearn import image, datasets
from pathlib import Path

# Fetch atlas
difumo = datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2)
atlas_mni = difumo['maps']

bids_root = 'bids/'
subjects = [f.name for f in Path(bids_root).glob('sub-*')]

for sub in sorted(subjects)[:5]:  # Example: first 5 subjects
    for ses in ['01', '02']:
        # Path to subject's native T1w
        t1w_path = f'{bids_root}/{sub}/ses-{ses}/anat/{sub}_ses-{ses}_T1w.nii.gz'
        
        if not os.path.exists(t1w_path):
            continue
        
        print(f"Resampling atlas for {sub}/ses-{ses}...")
        
        # Resample atlas to subject's native space
        atlas_native = image.resample_to_img(
            atlas_mni,
            t1w_path,
            interpolation='nearest'
        )
        
        # Save
        output_dir = f'{bids_root}/{sub}/ses-{ses}/derivatives/atlas/'
        os.makedirs(output_dir, exist_ok=True)
        nib.save(atlas_native, f'{output_dir}/difumo_256_native.nii.gz')
```

### Timeseries Extraction from ROI

```python
"""
Extract mean timeseries from each DiFuMo region for connectivity analysis.
Output: (256, 480) matrix — 256 regions, 480 timepoints (TR=0.8s → 6.4 min)
"""
import numpy as np
from nilearn import masking
import nibabel as nib

def extract_atlas_timeseries(bold_path, atlas_path, standardize=True):
    """Extract mean timeseries for each atlas region."""
    # Load atlas (3D or 4D with integer labels)
    atlas = nib.load(atlas_path)
    atlas_data = atlas.get_fdata()
    
    if atlas_data.ndim == 4:
        # If 4D (e.g., DiFuMo 256), take first time point
        atlas_data = atlas_data[:, :, :, 0]
    
    # Get unique region IDs
    regions = np.unique(atlas_data)
    regions = regions[regions != 0]  # Exclude background
    
    # Load BOLD (lazy load via masking)
    timeseries_list = []
    
    for region_id in regions:
        # Create binary mask for this region
        region_mask = (atlas_data == region_id).astype(np.uint8)
        region_mask_img = nib.Nifti1Image(region_mask, atlas.affine)
        
        # Extract timeseries (mean within region)
        ts = masking.apply_mask(bold_path, region_mask_img)  # (n_voxels, 480)
        ts_mean = ts.mean(axis=0)  # Average across voxels → (480,)
        
        timeseries_list.append(ts_mean)
    
    # Stack: (n_regions, n_timepoints)
    timeseries_matrix = np.array(timeseries_list)
    
    if standardize:
        # Z-score normalize each region's timeseries
        timeseries_matrix = (timeseries_matrix - timeseries_matrix.mean(axis=1, keepdims=True)) / timeseries_matrix.std(axis=1, keepdims=True)
    
    return timeseries_matrix

# Usage
bold = 'fmriprep/sub-001_ses-01_bold_mni.nii.gz'
atlas = 'difumo_256_2mm.nii.gz'

timeseries = extract_atlas_timeseries(bold, atlas, standardize=True)
print(f"Timeseries shape: {timeseries.shape}")  # (256, 480)

# Save for downstream use
np.save('sub-001_ses-01_timeseries_difumo256.npy', timeseries)
```

---

## 10. Performance & Best Practices

### Memory Management for Large 4D Datasets

```python
import numpy as np
from nilearn import masking
import gc

# Problem: Loading full 4D (91, 109, 91, 480) into memory uses ~3.5 GB
# Solution: Work with 2D (masked) data or process in chunks

# Strategy 1: Use masking to reduce dimensionality early
brain_mask = masking.compute_brain_mask('bold_4d.nii.gz')  # ~1 MB
bold_2d = masking.apply_mask('bold_4d.nii.gz', brain_mask)  # (200k, 480) → ~380 MB

# Strategy 2: Process in time chunks
def process_timeseries_chunks(bold_path, chunk_size=100):
    """Process 4D data in chunks to reduce memory footprint."""
    bold_img = nib.load(bold_path)
    n_timepoints = bold_img.shape[3]
    
    for t_start in range(0, n_timepoints, chunk_size):
        t_end = min(t_start + chunk_size, n_timepoints)
        chunk_4d = bold_img.get_fdata()[:, :, :, t_start:t_end]
        
        # Process chunk
        yield chunk_4d
        
        # Explicitly free memory
        del chunk_4d
        gc.collect()

# Strategy 3: Use nibabel's lazy loading
# Most nilearn functions accept file paths and load on-the-fly
brain_mask = masking.compute_brain_mask('bold_4d.nii.gz')  # No full 4D in memory
```

### Caching with Joblib

```python
from joblib import Memory
import os

# Set up cache directory
cache_dir = './cache'
os.makedirs(cache_dir, exist_ok=True)
memory = Memory(cache_dir, verbose=0)

# Decorator caches function results
@memory.cache
def expensive_operation(bold_path):
    """This result will be cached; subsequent calls reuse the result."""
    from nilearn import masking
    brain_mask = masking.compute_brain_mask(bold_path, threshold=0.5)
    return brain_mask

# First call: computes and caches
mask_1 = expensive_operation('bold_4d.nii.gz')

# Second call: loads from cache instantly
mask_2 = expensive_operation('bold_4d.nii.gz')

# Clear cache if needed
memory.clear()
```

### Error Handling

```python
import nibabel as nib
import numpy as np
from nilearn import masking

def safe_load_nifti(path):
    """Load NIfTI with error checking."""
    try:
        img = nib.load(path)
        data = img.get_fdata()
    except FileNotFoundError:
        print(f"Error: File not found: {path}")
        return None
    except nib.spatialimages.HeaderDataError:
        print(f"Error: Invalid NIfTI header in {path}")
        return None
    
    # Check for NaN/Inf
    if np.isnan(data).any():
        print(f"Warning: NaN values detected in {path}")
    if np.isinf(data).any():
        print(f"Warning: Inf values detected in {path}")
    
    return img

def safe_apply_mask(bold_path, mask_path):
    """Apply mask with dimension checking."""
    try:
        bold = nib.load(bold_path)
        mask = nib.load(mask_path)
        
        # Verify shapes match (first 3 dimensions)
        if bold.shape[:3] != mask.shape[:3]:
            print(f"Error: Shape mismatch. BOLD: {bold.shape}, Mask: {mask.shape}")
            return None
        
        # Apply mask
        timeseries = masking.apply_mask(bold_path, mask_path)
        return timeseries
    
    except Exception as e:
        print(f"Error applying mask: {e}")
        return None
```

### Validation Checks

```python
import numpy as np
import nibabel as nib

def validate_nifti(img_path):
    """Validate NIfTI file integrity."""
    try:
        img = nib.load(img_path)
        data = img.get_fdata()
        affine = img.affine
        
        # Check 1: Data shape
        print(f"✓ Shape: {data.shape}")
        
        # Check 2: Affine validity
        if np.linalg.det(affine) == 0:
            print("✗ Affine is singular (non-invertible)")
            return False
        else:
            print("✓ Affine is valid")
        
        # Check 3: NaN/Inf
        nan_count = np.isnan(data).sum()
        inf_count = np.isinf(data).sum()
        
        if nan_count > 0:
            print(f"✗ NaN values: {nan_count}")
        if inf_count > 0:
            print(f"✗ Inf values: {inf_count}")
        
        if nan_count == 0 and inf_count == 0:
            print("✓ No NaN/Inf values")
        
        # Check 4: Data range
        print(f"✓ Data range: [{data.min():.2f}, {data.max():.2f}]")
        
        # Check 5: Singleton dimensions
        singleton_dims = [i for i, s in enumerate(data.shape) if s == 1]
        if singleton_dims:
            print(f"⚠ Singleton dimensions: {singleton_dims} (consider squeezing)")
        
        return True
    
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

# Example usage
validate_nifti('bold_4d.nii.gz')
```

---

## Summary: When to Use Nilearn vs Nibabel

| Task | Tool |
|------|------|
| Load/save NIfTI files | **nibabel** |
| Get/manipulate affine | **nibabel** |
| Smooth images | **nilearn** |
| Mask/extract timeseries | **nilearn** |
| Fetch atlases | **nilearn** |
| Resample images | **nilearn** |
| Statistical analysis (fALFF, ReHo) | **nibabel** (low-level) + **scipy** |
| Seed-based connectivity | **nilearn** (timeseries) + **scipy** (correlations) |
| Visualization | **nilearn** |
| Coordinate transforms | **nibabel** (affine) |

---

## Further Reading

- **Nilearn docs**: https://nilearn.github.io/
- **Nibabel docs**: https://nipy.org/nibabel/
- **fMRIPrep outputs**: https://fmriprep.org/en/stable/outputs/index.html
- **SPM BIDS**: https://www.fil.ion.ucl.ac.uk/spm/
