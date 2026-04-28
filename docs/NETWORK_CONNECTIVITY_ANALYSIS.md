# Network Connectivity Analysis Guide

## Overview

The DiFuMo 256 network connectivity backend computes whole-brain functional connectivity at the network level using independent component analysis (ICA)-based parcellation.

### Key Features

- **DiFuMo 256 Atlas**: Whole-brain coverage including cerebellum and subcortical structures
- **Within-Network Connectivity**: Correlations between ROIs in same functional network
- **Between-Network Connectivity**: Correlations between ROIs in different networks
- **Confound Regression**: Removes motion, physiological, and scanner-related artifacts
- **Filtering**: High-pass (0.01 Hz) and low-pass (0.1 Hz) filtering for resting-state frequency range
- **Statistical Output**: HDF5 correlation matrices + CSV summary statistics

## Quick Start

### Basic Usage

```bash
python script/compute_network_connectivity.py \
    --bold fmriprep/sub-033/ses-01/func/sub-033_ses-01_space-MNI152NLin2009cAsym_res-2_bold.nii.gz \
    --confounds fmriprep/sub-033/ses-01/func/sub-033_ses-01_bold_confounds.tsv \
    --output results/network_connectivity/sub-033_ses-01/
```

### With Custom Parameters

```bash
python script/compute_network_connectivity.py \
    --bold fmriprep/sub-033/ses-01/func/sub-033_ses-01_space-MNI152NLin2009cAsym_res-2_bold.nii.gz \
    --confounds fmriprep/sub-033/ses-01/func/sub-033_ses-01_bold_confounds.tsv \
    --output results/network_connectivity/sub-033_ses-01/ \
    --atlas DiFuMo256 \
    --atlas-path atlases/difumo256.nii \
    --networks-json atlases/difumo256_network_definitions.json \
    --tr 0.8 \
    --high-pass 0.01 \
    --low-pass 0.1
```

## Input Requirements

### Preprocessed BOLD Data

- **File format**: 4D NIfTI (x, y, z, time)
- **Source**: fMRIPrep output in standard space (typically `space-MNI152NLin2009cAsym`)
- **Resolution**: 2mm or higher (script handles resampling)
- **Expected dimensions**: ~91×109×91 × 480 volumes (for TR=0.8s, 6.4 min acquisition)

### Confound Regressors

- **File format**: TSV (tab-separated values)
- **Source**: fMRIPrep confounds file (`*_desc-confounds_timeseries.tsv`)
- **Required columns** (automatically detected):
  - Motion parameters: `trans_x`, `trans_y`, `trans_z`, `rot_x`, `rot_y`, `rot_z`
  - Framewise displacement: `framewise_displacement` or `FD`
  - DVARS: `dvars` or `DVARS`
  - Tissue signals: `csf`, `white_matter`
- **Optional**: Motion derivatives (`trans_*_derivative1`, `rot_*_derivative1`)

### DiFuMo 256 Atlas

- **Location**: `atlases/difumo256.nii` (3D labeled map)
- **Dimensions**: 104×123×104 voxels
- **Component labels**: 1–256 (0 = background)
- **Alternative**: `atlases/difumo256_4D.nii` (probabilistic maps, automatically handled)

### Network Definitions

- **Location**: `atlases/difumo256_network_definitions.json`
- **Format**: JSON with `networks` key mapping network names to ROI indices
- **Example**:
  ```json
  {
    "networks": {
      "DefaultMode": [0, 1, 14, 15, ...],
      "FrontoParietal": [1, 3, 23, 28, ...],
      ...
    }
  }
  ```

## Output Files

```
results/network_connectivity/sub-{id}_ses-{ses}/
├── correlation_matrix.h5          # Full connectivity matrix + cleaned timeseries
├── correlation_stats.csv          # Summary statistics
├── network_definitions.json       # Network mappings
└── compute_network_connectivity.log  # Processing log
```

### HDF5 Format

The `correlation_matrix.h5` file contains:

- **`correlation_matrix`**: (256, 256) Pearson correlation matrix
  - Rows/columns indexed 0–255 (one per component)
  - Symmetric matrix with diagonal = 1.0
  - Values in range [-1, 1]
- **`timeseries_cleaned`**: (n_volumes, 256) Preprocessed timeseries
  - Confound-regressed, filtered, and standardized
  - Mean ≈ 0, std ≈ 1
- **Attributes**:
  - `n_rois`: 256
  - `n_volumes`: Number of timepoints

### CSV Statistics

`correlation_stats.csv` contains:

- **Global statistics**:
  - `n_rois`: Total number of regions (256)
  - `mean_correlation`: Mean of all pairwise correlations
  - `std_correlation`: Standard deviation
  - `within_network_mean`: Mean within-network correlation
  - `within_network_std`: Std dev of within-network correlations
  - `between_network_mean`: Mean between-network correlation
  - `between_network_std`: Std dev of between-network correlations

- **Per-network statistics**:
  - `within_{network}_mean`: Within-network mean for each network
  - `within_{network}_n_pairs`: Number of within-network ROI pairs
  - `between_{net1}_{net2}_mean`: Between-network mean
  - `between_{net1}_{net2}_n_pairs`: Number of between-network ROI pairs

## Processing Pipeline

### Step 1: Load Data

- Load BOLD from NIfTI
- Load confounds from TSV
- Load atlas and resample to BOLD space if needed

### Step 2: Extract Timeseries

- For each of 256 components, extract mean timeseries
- Uses 3D labeled atlas (if available) or probabilistic maps
- Handles voxel-wise averaging within ROI boundaries

### Step 3: Confound Regression

- Apply confound regressors: motion (6 DoF), FD, DVARS, CSF, WM
- Remove linear trends
- Standardize to zero mean, unit variance

### Step 4: Frequency Filtering

- **High-pass**: 0.01 Hz (removes slow scanner drifts)
- **Low-pass**: 0.1 Hz (removes physiological noise)
- Uses Butterworth IIR filters (nilearn default)

### Step 5: Correlation Computation

- Compute Pearson correlations between all ROI pairs
- Produces symmetric 256×256 matrix
- Applies Fisher z-transform for statistical tests (if needed)

### Step 6: Network Statistics

- Calculate within-network and between-network means
- Group by network definitions from JSON
- Save summary statistics to CSV

## Parameters

### TR (Repetition Time)
- **Default**: 0.8 s
- **Description**: Time between BOLD acquisitions
- **Range**: Typically 0.5–2.0 s for resting-state

### High-Pass Filter Cutoff
- **Default**: 0.01 Hz
- **Description**: Removes frequencies below this cutoff
- **Range**: 0.005–0.02 Hz (common)
- **Rationale**: Removes slow scanner drifts while preserving resting-state activity

### Low-Pass Filter Cutoff
- **Default**: 0.1 Hz
- **Description**: Removes frequencies above this cutoff
- **Range**: 0.08–0.15 Hz (common)
- **Rationale**: Removes physiological noise (respiration, heart rate)

### Smoothing FWHM
- **Default**: 6.0 mm
- **Description**: Gaussian smoothing kernel (currently not applied in preprocessing)
- **Note**: Can be enabled in future versions for spatial smoothing

## Quality Control

### Check Logs

The `compute_network_connectivity.log` file contains:
- Processing time for each step
- Number of voxels per ROI
- Correlation matrix statistics
- Warnings about empty ROIs or NaN values

### Verify Outputs

```python
import h5py
import numpy as np

# Load results
with h5py.File('results/network_connectivity/sub-033_ses-01/correlation_matrix.h5', 'r') as f:
    corr = f['correlation_matrix'][:]
    ts = f['timeseries_cleaned'][:]

# Check dimensions
assert corr.shape == (256, 256), "Correlation matrix size"
assert ts.shape[1] == 256, "Timeseries ROI count"

# Check valid range
assert -1 <= corr.min() and corr.max() <= 1, "Correlations out of range"

# Check symmetry
assert np.allclose(corr, corr.T), "Correlation matrix not symmetric"

# Check diagonal
assert np.allclose(np.diag(corr), 1.0), "Diagonal not 1.0"

# Check no NaN/Inf
assert np.isfinite(corr).all(), "NaN or Inf in correlation matrix"
```

## Integration with Pipeline

The script is designed to run as part of the master connectivity workflow:

```bash
# Step 3 of master_full_connectivity_workflow.sh
python script/compute_network_connectivity.py \
    --bold "${BOLD_FILE}" \
    --confounds "${CONFOUNDS_FILE}" \
    --output "${OUTPUT_DIR}"
```

## Troubleshooting

### Empty ROIs

**Problem**: Many warnings about "No voxels found" for ROIs

**Causes**:
- Atlas not properly resampled to BOLD space
- Atlas file corrupted or wrong format
- BOLD and atlas in different coordinate systems

**Solution**: Verify atlas and BOLD have compatible affine matrices

### NaN Correlations

**Problem**: Correlation matrix contains NaN values

**Causes**:
- ROI with zero variance (all voxels same value)
- Entire ROI masked out by confound regression
- Numerical instability

**Solution**: Check raw timeseries for pathological voxels

### Poor Correlation Statistics

**Problem**: All correlations near zero or very low

**Causes**:
- Over-aggressive filtering removes signal
- Excessive confound regression
- Poor data quality

**Solution**:
1. Adjust filter cutoffs
2. Check confound regression aggressiveness
3. Verify BOLD quality (SNR, head motion)

## Performance

### Computation Time

For a typical 480-volume BOLD scan:
- Timeseries extraction: ~5–10 s
- Preprocessing: ~2–5 s
- Correlation computation: ~2–5 s
- **Total**: ~10–20 s

### Memory Usage

- BOLD (480 volumes): ~200 MB
- Timeseries (256 ROIs): ~1 MB
- Correlation matrix: ~512 KB
- **Total**: ~200 MB

## Advanced Usage

### Batch Processing

```bash
# Process multiple subjects
for sub in sub-033 sub-034 sub-035; do
    for ses in ses-01 ses-02; do
        python script/compute_network_connectivity.py \
            --bold "fmriprep/${sub}/${ses}/func/${sub}_${ses}_bold.nii.gz" \
            --confounds "fmriprep/${sub}/${ses}/func/${sub}_${ses}_confounds.tsv" \
            --output "results/network_connectivity/${sub}_${ses}/" \
            &  # Run in parallel
    done
done
wait
```

### Custom Networks

To analyze custom networks, edit `atlases/difumo256_network_definitions.json`:

```json
{
  "networks": {
    "MyCustomNetwork": [0, 15, 30, 45, 60],
    ...
  }
}
```

The script will automatically compute within/between statistics for all networks.

## References

- **DiFuMo Atlas**: Schäfer et al. (2017) "Brain Topography" - ICA-based functional parcellation
- **Yeo 7 Networks**: Yeo et al. (2011) "Journal of Neurophysiology" - Default network classification
- **fMRIPrep**: Esteban et al. (2019) "Nature Methods" - Standardized preprocessing

## Citation

If you use this script, please cite:

```
Clivewong et al. Network connectivity analysis using DiFuMo 256 atlas.
Longitudinal Walking Intervention Study. 2024.
```

## Support

For issues or questions:
1. Check the log file: `results/network_connectivity/*/compute_network_connectivity.log`
2. Run tests: `python -m pytest tests/test_network_connectivity.py -v`
3. Check code comments: `script/compute_network_connectivity.py`
