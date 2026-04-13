# DiFuMo 256 Analysis Guide - Walking Intervention Study

**Focus**: DiFuMo 256 atlas for **whole-brain connectivity including cerebellum**

## Why DiFuMo for This Study?

✅ **Cerebellar coverage**: 23 cerebellar components (Lobules IV, V, VI, VIIb, VIII, IX, Crus I/II)
✅ **Motor system**: 40 motor-related components (cortical + cerebellar)
✅ **ICA-based**: Functionally-defined networks (not just anatomical)
✅ **Subcortical**: Includes thalamus, basal ganglia, amygdala

⚠️ **Schaefer limitation**: Cortical surface only - **no cerebellum**

---

## Network Definitions Created

**File**: `/Volumes/Work/Work/long/atlases/difumo256_network_definitions.json`

### Components per Network (GM-dominant only)

| Network | Components |
|---------|-----------|
| Visual | 39 |
| Somatomotor | 26 |
| Dorsal Attention | 29 |
| Salience/Ventral Attention | 27 |
| Limbic | 6 |
| Frontoparietal (FPCN) | 26 |
| Default Mode (DMN) | 32 |
| **Subcortical** | 37 |

**Total**: 222 GM-dominant components (out of 256 total)

### Special Regions

- **Cerebellar**: 23 components
  - Lobule IV, V, VI, VIIb, VIIIb, IX
  - Crus I (lateral, posterior, superior, anterior)
  - Crus II
- **Motor-related**: 40 components (cortical motor + cerebellar)
- **CSF-related**: 18 components (excluded from connectivity)

---

## Hypothesis-Driven Network Analyses

### 1. Motor-Cerebellar Connectivity ⭐ **PRIMARY**
**Why**: Walking intervention should strengthen sensorimotor integration

- **Network A**: Somatomotor (26 components)
- **Network B**: Cerebellum (23 components)
- **Connections**: 26 × 23 = **598 pairs**
- **Expected**: Increased connectivity Post vs Pre in Walking group

### 2. Motor-Salience Connectivity
**Why**: Walking intervention effects on motor-salience network

- **Network A**: Somatomotor (26 components)
- **Network B**: Salience/Ventral Attention (27 components)
- **Connections**: 26 × 27 = **702 pairs**

### 3. Salience-FPCN Connectivity
**Why**: Cognitive control network interactions

- **Network A**: Salience (27 components)
- **Network B**: Frontoparietal (26 components)
- **Connections**: 27 × 26 = **702 pairs**

### 4. DMN-FPCN Connectivity
**Why**: Default mode - control network balance

- **Network A**: Default Mode (32 components)
- **Network B**: Frontoparietal (26 components)
- **Connections**: 32 × 26 = **832 pairs**

### 5. Cerebellar-FPCN Connectivity ⭐ **NOVEL**
**Why**: Cognitive-motor integration (cerebellar cognitive functions)

- **Network A**: Cerebellum (23 components)
- **Network B**: Frontoparietal (26 components)
- **Connections**: 23 × 26 = **598 pairs**
- **Rationale**: Cerebellum contributes to cognitive functions beyond motor control

---

## Cerebellar Components (23 total)

### Lobules Identified

| Lobule | Components | Known Functions |
|--------|-----------|----------------|
| **IV** | 1 | Primary motor control |
| **V** | 3 | Sensorimotor coordination |
| **VI** | 7 | Sensorimotor + visual-motor |
| **Crus I** | 6 | Cognitive functions, working memory |
| **Crus II** | 2 | Executive functions |
| **VIIb** | 2 | Motor learning |
| **VIIIb** | 2 | Sensorimotor |
| **IX** | 1 | Vestibular, spatial orientation |

**Motor-dominant**: Lobules IV, V, VI, VIIIb (13 components)
**Cognitive-dominant**: Crus I, Crus II (8 components)

---

## Analysis Workflow

### Step 1: Export Timeseries from CONN

**After CONN preprocessing completes**, run:

```matlab
% In MATLAB
addpath('/Volumes/Work/Work/long/tools/conn');
addpath('/Volumes/Work/Work/long/tools/spm');

% Export DiFuMo 256 timeseries
export_roi_timeseries('difumo256_4D', '/Volumes/Work/Work/long/timeseries');
```

**Outputs**:
- CSV files: `/Volumes/Work/Work/long/timeseries/csv/sub-*_ses-*_difumo256_timeseries.csv`
- MAT file: `/Volumes/Work/Work/long/timeseries/difumo256_all_subjects.mat`
- Metadata: `/Volumes/Work/Work/long/timeseries/difumo256_metadata.json`

---

### Step 2: Convert to HDF5 for Python

```bash
python script/convert_mat_to_hdf5.py /Volumes/Work/Work/long/timeseries/difumo256_all_subjects.mat
```

**Output**: `/Volumes/Work/Work/long/timeseries/difumo256_all_subjects.h5`

---

### Step 3: Python Connectivity Analysis

```python
import json
import h5py
import numpy as np
import pandas as pd

# Load network definitions
with open('atlases/difumo256_network_definitions.json') as f:
    networks = json.load(f)

# Load timeseries
with h5py.File('timeseries/difumo256_all_subjects.h5', 'r') as f:
    # Get Motor-Cerebellar timeseries
    motor_rois = networks['networks']['Somatomotor']
    cerebellar_rois = networks['special_regions']['cerebellar']

    # Extract for subject
    ts = f['timeseries']['sub-033']['ses-01'][:]  # Shape: (480 timepoints, 256 components)

    motor_ts = ts[:, motor_rois]  # (480, 26)
    cereb_ts = ts[:, cerebellar_rois]  # (480, 23)

    # Compute connectivity
    from scipy.stats import pearsonr
    conn_matrix = np.zeros((len(motor_rois), len(cerebellar_rois)))
    for i, m_roi in enumerate(motor_rois):
        for j, c_roi in enumerate(cerebellar_rois):
            r, _ = pearsonr(ts[:, m_roi], ts[:, c_roi])
            conn_matrix[i, j] = r
```

---

### Step 4: Statistical Testing (Group × Time)

```python
import statsmodels.api as sm
from statsmodels.formula.api import mixedlm

# Prepare data for mixed ANOVA
# Subject | Group | Time | Motor-Cereb Connectivity
data = []
for subject in subjects:
    for session in ['ses-01', 'ses-02']:
        # Compute mean Motor-Cerebellar connectivity
        conn_mean = np.mean(conn_matrix)  # Average across all 598 pairs

        data.append({
            'subject': subject,
            'group': metadata[subject]['group'],  # Control vs Walking
            'time': 'Pre' if session == 'ses-01' else 'Post',
            'connectivity': conn_mean,
            'age': metadata[subject]['age'],
            'sex': metadata[subject]['sex'],
            'mean_FD': metadata[subject][f'mean_FD_{session}']
        })

df = pd.DataFrame(data)

# Mixed ANOVA: Group × Time interaction
# Formula: connectivity ~ group * time + age + sex + mean_FD + (1|subject)
model = mixedlm("connectivity ~ C(group) * C(time) + age + sex + mean_FD",
                df, groups=df["subject"])
result = model.fit()
print(result.summary())

# Extract interaction effect
# (Walking_Post - Walking_Pre) - (Control_Post - Control_Pre)
```

---

## Exploratory Analyses

### 1. Component-Level Analysis
- Test all 256 × 255 / 2 = **32,640 unique pairs**
- FDR correction for multiple comparisons
- Identify which specific components drive network effects

### 2. Graph Theory Metrics
```python
import networkx as nx

# Create graph from connectivity matrix
G = nx.from_numpy_array(conn_matrix, threshold=0.3)

# Global metrics
efficiency = nx.global_efficiency(G)
modularity = nx.algorithms.community.modularity(G, communities)

# Nodal metrics (per component)
degree = dict(G.degree())
betweenness = nx.betweenness_centrality(G)
```

### 3. Cerebellar-Specific Analyses

```python
# Within-cerebellar connectivity
cereb_rois = networks['special_regions']['cerebellar']
cereb_conn = connectivity_matrix[np.ix_(cereb_rois, cereb_rois)]

# Cerebellar lobule segregation
# Do motor lobules (IV, V, VI) connect more with motor cortex?
# Do cognitive lobules (Crus I, II) connect more with FPCN?
```

---

## Visualization Examples

### 1. Motor-Cerebellar Connectivity Matrix

```python
import matplotlib.pyplot as plt
import seaborn as sns

# Plot connectivity matrix
fig, ax = plt.subplots(figsize=(10, 8))
sns.heatmap(conn_matrix, cmap='RdBu_r', center=0,
            xticklabels=[f'Cereb_{i}' for i in range(23)],
            yticklabels=[f'Motor_{i}' for i in range(26)])
ax.set_title('Motor-Cerebellar Connectivity')
plt.tight_layout()
plt.savefig('motor_cerebellar_connectivity.pdf')
```

### 2. Network Graph on Brain

```python
# Use nilearn to plot on brain surface + cerebellum
from nilearn import plotting

# Create connectivity edges (thresholded)
coords = # Get component centroids from network definitions
plotting.plot_connectome(conn_matrix, coords,
                        edge_threshold='95%',
                        title='Motor-Cerebellar Connectivity')
```

---

## Expected Results

### Primary Hypothesis
**Motor-Cerebellar connectivity increases Post vs Pre in Walking group**

- Group × Time interaction: *p* < 0.05 (FDR corrected)
- Effect size: Cohen's *d* > 0.5 (medium-large effect)
- Specific lobules: VI, VIIb, Crus I (motor learning + cognitive)

### Secondary Findings
- Cerebellar-FPCN: Cognitive engagement during walking
- Motor-Salience: Attentional modulation
- DMN-FPCN: Task-positive network balance

---

## Next Steps

1. **Fill in demographics**: `covariates_template.csv`
2. **Wait for CONN preprocessing** (~7-8 hours remaining)
3. **Extract DiFuMo timeseries**: `export_roi_timeseries.m`
4. **Run Python connectivity analysis** (script to be created)
5. **Statistical testing**: Group × Time mixed ANOVA
6. **Visualization**: Matrices, brain renders, statistical plots

---

## Files Summary

### Created
- ✅ `atlases/difumo256_network_definitions.json` - Network definitions
- ✅ `script/create_difumo_network_definitions.py` - Parser script
- ✅ `script/export_roi_timeseries.m` - Timeseries extraction
- ✅ `script/convert_mat_to_hdf5.py` - HDF5 converter

### To Create (Next Priority)
- `script/python_connectivity_analysis.py` - Main analysis script
- `script/python_visualization.py` - Plotting functions
- `script/difumo_motor_cerebellar_analysis.py` - Focused Motor-Cerebellar

---

**Ready to proceed?** Let me know if you want me to create the Python analysis scripts next!
