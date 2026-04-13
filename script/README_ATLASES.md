# Time Series Extraction - Atlas Comparison Guide

This repository includes scripts to extract ROI time series using multiple brain atlases for comparison.

## Available Atlases

### Functional Parcellations

| Atlas | ROIs | Type | Best For |
|-------|------|------|----------|
| **Schaefer 400 (7-net)** | 400 | Functional | **PRIMARY - Balanced resolution, network-based** |
| **Gordon 333** | 333 | Functional | Functional boundaries, community detection |
| **DiFuMo 256** | 256 | Data-driven | ICA-based components, continuous representation |
| Schaefer 200 (7-net) | 200 | Functional | Lower resolution alternative |
| Schaefer 400 (17-net) | 400 | Functional | Finer network subdivisions |
| DiFuMo 512 | 512 | Data-driven | Higher resolution ICA |
| DiFuMo 128 | 128 | Data-driven | Lower resolution ICA |
| BASC 122 | 122 | Functional | Multiscale bootstrap analysis |
| BASC 197 | 197 | Functional | Higher BASC resolution |

### Anatomical Parcellations

| Atlas | ROIs | Type | Best For |
|-------|------|------|----------|
| AAL | 116 | Anatomical | Classic anatomical regions |
| Harvard-Oxford | 96 | Anatomical | Probabilistic anatomical atlas |

## Quick Start

### 1. Setup Gordon Atlas (one-time)
```bash
python script/setup_gordon_atlas.py
```

### 2. Extract with Single Atlas
```bash
# Primary: Schaefer 400, Yeo 7-networks
python script/extract_timeseries.py \
    fmriprep/ \
    timeseries/schaefer400_7net \
    --atlas schaefer_400_7 \
    --smoothing 6 \
    --confounds minimal

# Comparison: Gordon 333
python script/extract_timeseries.py \
    fmriprep/ \
    timeseries/gordon333 \
    --atlas gordon_333

# Comparison: DiFuMo 256
python script/extract_timeseries.py \
    fmriprep/ \
    timeseries/difumo256 \
    --atlas difumo_256
```

### 3. Extract All Atlases (Parallel)
```bash
# Extracts with 8 recommended atlases in parallel
./script/extract_all_atlases.sh fmriprep/ timeseries/
```

## Output Structure

```
timeseries/
├── schaefer400_7net/
│   ├── sub-033_ses-01_task-rest_atlas-schaefer_400_7_timeseries.tsv
│   ├── sub-033_ses-01_task-rest_atlas-schaefer_400_7_metadata.json
│   ├── sub-033_ses-02_task-rest_atlas-schaefer_400_7_timeseries.tsv
│   └── qc_summary.tsv
├── gordon333/
│   └── ...
├── difumo256/
│   └── ...
└── logs/
    ├── schaefer400_7net.log
    └── gordon333.log
```

## Processing Parameters

### Spatial Preprocessing
- **Smoothing:** 6mm FWHM Gaussian kernel
- **Space:** MNI152NLin2009cAsym (2mm)

### Temporal Filtering
- **High-pass:** 0.01 Hz (removes slow drift)
- **Low-pass:** 0.1 Hz (removes high-frequency noise)
- **Detrending:** Linear

### Confound Regression Strategies

**Minimal** (default):
- 6 motion parameters (trans_x/y/z, rot_x/y/z)
- CSF signal
- White matter signal

**Standard** (recommended for connectivity):
- Minimal +
- 6 motion derivatives
- Framewise displacement

**Extended** (aggressive denoising):
- Standard +
- Global signal
- All signal derivatives

## QC Metrics

Each extraction generates `qc_summary.tsv`:
- `mean_fd`: Mean framewise displacement (motion)
- `n_high_motion`: Number of volumes with FD > 0.5mm
- `mean_tsnr`: Temporal SNR
- `global_correlation`: Mean pairwise correlation across ROIs

## Atlas Selection Recommendations

### For Network Analysis
1. **Schaefer 400 (7-net)** - Best balance
2. Gordon 333 - Alternative functional boundaries
3. BASC 122/197 - Multiscale comparison

### For Continuous Representations
1. **DiFuMo 256** - Good resolution
2. DiFuMo 512 - Higher detail
3. DiFuMo 128 - Faster computation

### For Anatomical Correspondence
1. AAL - Classic regions
2. Harvard-Oxford - Probabilistic regions

## References

- **Schaefer et al. (2018)** Cerebral Cortex - Local-global parcellation
- **Gordon et al. (2016)** Cerebral Cortex - Functional boundaries
- **Dadi et al. (2020)** NeuroImage - DiFuMo atlas
- **BASC (2015)** NeuroImage - Bootstrap multiscale
