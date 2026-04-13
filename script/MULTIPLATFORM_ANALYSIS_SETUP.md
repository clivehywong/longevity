# Multi-Platform Analysis Setup Guide

**Status**: Foundation scripts created, awaiting CONN preprocessing completion

## Overview

This guide covers the multi-platform analysis pipeline for the longitudinal walking intervention study. The pipeline supports **flexible analysis** using CONN, Python, and Julia, allowing you to choose the tools that best fit each analysis.

## Analysis Plan Summary

Your approved plan includes:

1. **Data Export** (MATLAB): Extract ROI timeseries from CONN → portable formats
2. **CONN Analyses** (MATLAB): Standard connectivity benchmarks
3. **Python Analyses**: Connectivity, graph theory, Granger causality
4. **Julia rDCM**: Regression Dynamic Causal Modeling for effective connectivity
5. **Visualization**: Tool-agnostic outputs for flexible visualization

---

## Current Status

### ✅ Completed Scripts (Must Have - Core Pipeline)

#### 1. **export_roi_timeseries.m**
*MATLAB script to extract ROI timeseries from CONN*

**Purpose**: Foundation of all analyses - extracts denoised BOLD timeseries for all subjects/sessions

**Outputs**:
- CSV files: Individual timeseries per subject/session
- MAT file: All data in MATLAB format
- Metadata JSON: ROI names, networks, coordinates

**Usage** (after CONN preprocessing completes):
```matlab
% Extract timeseries for Schaefer 400 atlas
export_roi_timeseries('schaefer400_7net', '/Volumes/Work/Work/long/timeseries')

% Extract for other atlases
export_roi_timeseries('schaefer200_7net', '/Volumes/Work/Work/long/timeseries')
export_roi_timeseries('difumo256_4D', '/Volumes/Work/Work/long/timeseries')
```

**Converts to HDF5 for Python**:
```bash
python script/convert_mat_to_hdf5.py /path/to/schaefer400_all_subjects.mat
```

---

#### 2. **Network Definitions JSON**
*Portable network definitions for all platforms*

**Created files**:
- `atlases/schaefer400_7net_network_definitions.json` (400 ROIs)
- `atlases/schaefer200_7net_network_definitions.json` (200 ROIs)

**Contents**:
- ROI-to-network mapping (7 Yeo networks)
- Hypothesis-driven network pairs:
  - **Motor-Salience**: 77 × 47 ROI pairs (walking intervention effect)
  - **Salience-FPCN**: 47 × 52 ROI pairs
  - **DMN-FPCN**: 91 × 52 ROI pairs

**Usage in Python**:
```python
import json

with open('atlases/schaefer400_7net_network_definitions.json') as f:
    networks = json.load(f)

# Get ROI indices for Motor network
motor_rois = networks['networks']['Somatomotor']  # List of ROI indices

# Get hypothesis-driven pairs
motor_salience = networks['hypothesis_driven_pairs']['Motor_Salience']
```

**Network breakdown** (Schaefer 400):
| Network | ROIs |
|---------|------|
| Visual | 61 |
| Somatomotor | 77 |
| Dorsal Attention | 46 |
| Salience/Ventral Attention | 47 |
| Limbic | 26 |
| Frontoparietal (FPCN) | 52 |
| Default Mode (DMN) | 91 |

---

#### 3. **prepare_metadata.py**
*Create centralized metadata for covariates*

**Purpose**: Consolidate all subject-level variables (group, age, sex, motion)

**Created**:
- `covariates_template.csv` - Template for you to fill in demographics

**Next steps**:
1. Open `/Volumes/Work/Work/long/covariates_template.csv`
2. Fill in `age` and `sex` for all 24 subjects
3. Re-run: `python script/prepare_metadata.py`

This will create:
- `metadata.json` - Complete metadata
- `metadata.csv` - Flattened for Python/R
- `covariates_for_conn/` - CONN-compatible covariate files

**After CONN preprocessing**, motion parameters (mean FD) will be extracted from CONN's QA outputs and added to metadata.

---

## Pending Scripts (To Be Created)

### Core Pipeline (Should Have Next)

#### 4. python_connectivity_analysis.py
- Load exported timeseries (HDF5 or CSV)
- Compute connectivity matrices (Pearson, partial correlation)
- Statistical testing: Group × Time mixed ANOVA
- FDR correction, effect sizes

#### 5. python_visualization.py
- Connectivity matrix heatmaps
- Network graphs
- Statistical results tables

#### 6. python_graph_analysis.py
- Graph theory metrics (efficiency, modularity, clustering)
- Community detection
- Statistical testing across groups/time

---

### Extended Pipeline (Nice to Have)

#### 7. Julia rDCM Scripts
- `setup_rdcm.jl` - Install RegressionDynamicCausalModeling.jl
- `rdcm_analysis.jl` - Effective connectivity estimation
- `rdcm_stats.jl` - Statistical testing on connectivity parameters

#### 8. Python Granger Causality
- `python_granger_causality.py` - Directed connectivity analysis

#### 9. CONN Standard Analyses (Benchmark)
- `conn_standard_analyses.m` - CONN's built-in analyses for comparison

---

## Workflow Diagram

```
CONN Preprocessing (Running)
         ↓
export_roi_timeseries.m
         ↓
    ┌────────────┬──────────────┬───────────┐
    ↓            ↓              ↓           ↓
  CSV         HDF5 (Python)   MAT      Metadata
    ↓            ↓              ↓
    └────────────┴──────────────┴───────────┐
                                             ↓
    ┌─────────────┬──────────────────┬───────────────┐
    ↓             ↓                  ↓               ↓
 Python     Julia rDCM         MATLAB/CONN    Visualization
Connectivity  Effective        Standard       (Tool-agnostic)
 + Graph    Connectivity      Analyses
 + Granger
```

---

## Current CONN Preprocessing Progress

**Status**: 3 parallel workers running (~8/14 CPU cores in use)

Check progress:
```bash
bash script/monitor_conn_progress.sh
```

**Estimated completion**: ~7-8 hours (started ~Jan 9 11:24 AM)

**What's happening**:
- Realignment & unwarp (motion correction + distortion correction)
- Segmentation & normalization (to MNI space)
- Smoothing (6mm FWHM)
- ART outlier detection
- aCompCor denoising (5 WM + 5 CSF components)

---

## Next Steps

### Immediate (While Preprocessing Runs)

1. **Fill in demographics**:
   ```bash
   # Open in spreadsheet editor
   open /Volumes/Work/Work/long/covariates_template.csv

   # Fill in age and sex for all 24 subjects
   # Save the file

   # Re-run to create metadata
   python script/prepare_metadata.py
   ```

2. **Review network definitions**:
   ```bash
   cat atlases/schaefer400_7net_network_definitions.json | head -50
   ```

3. **Decide on priority**: Which analyses do you want first?
   - **Minimal core** (1-2 days): Export data → Python connectivity → Visualization
   - **Extended** (+2-3 days): Add Julia rDCM
   - **Full comparison** (+1 week): All platforms

### After Preprocessing Completes

4. **Extract timeseries**:
   ```matlab
   % In MATLAB
   addpath('/Volumes/Work/Work/long/tools/conn');
   addpath('/Volumes/Work/Work/long/tools/spm');

   export_roi_timeseries('schaefer400_7net', '/Volumes/Work/Work/long/timeseries');
   ```

5. **Convert to HDF5**:
   ```bash
   python script/convert_mat_to_hdf5.py /Volumes/Work/Work/long/timeseries/schaefer400_all_subjects.mat
   ```

6. **Create Python analysis scripts** (I can create these next)

---

## File Locations

### Scripts
- `/Volumes/Work/Work/long/script/export_roi_timeseries.m`
- `/Volumes/Work/Work/long/script/convert_mat_to_hdf5.py`
- `/Volumes/Work/Work/long/script/create_network_definitions.py`
- `/Volumes/Work/Work/long/script/prepare_metadata.py`

### Data Files
- `/Volumes/Work/Work/long/atlases/schaefer400_7net_network_definitions.json`
- `/Volumes/Work/Work/long/atlases/schaefer200_7net_network_definitions.json`
- `/Volumes/Work/Work/long/covariates_template.csv` ← **Fill this in!**

### CONN Project
- `/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat`

### Future Outputs (After Timeseries Export)
- `/Volumes/Work/Work/long/timeseries/csv/` - Individual CSV files
- `/Volumes/Work/Work/long/timeseries/*.h5` - HDF5 for Python
- `/Volumes/Work/Work/long/timeseries/*.mat` - MATLAB format

---

## Dependencies

### Already Installed
- MATLAB with CONN toolbox ✅
- SPM12 ✅
- Python 3 ✅

### To Install for Python Analyses
```bash
pip install numpy pandas scipy statsmodels
pip install matplotlib seaborn plotly
pip install networkx bctpy  # Brain Connectivity Toolbox
pip install h5py  # For HDF5 files
```

### To Install for Julia rDCM
```julia
using Pkg
Pkg.add(url="https://github.com/ComputationalPsychiatry/RegressionDynamicCausalModeling.jl")
Pkg.add("DataFrames")
Pkg.add("CSV")
Pkg.add("Statistics")
```

---

## Questions?

**Which workflow should I implement next?**
1. Minimal core (Python connectivity + visualization)?
2. Extended (add Julia rDCM)?
3. Something else first?

**Need help with**:
- Demographics data entry?
- Understanding the network definitions?
- Deciding on analysis priorities?

Let me know!
