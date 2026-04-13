# Python Analysis Workflow - Longitudinal Walking Intervention Study

**Status**: Ready for use after CONN preprocessing completes

## Overview

This workflow provides Python-based connectivity analysis for the longitudinal walking intervention study. It operates on timeseries data exported from CONN preprocessing.

**Key Advantages**:
- Flexible statistical models (mixed-effects ANOVA with covariates)
- Publication-ready visualizations
- Hypothesis-driven cerebellar analyses
- Cross-platform compatibility

---

## Study Design

- **Groups**: Control (n=15) vs Walking intervention (n=9)
- **Time Points**: Pre (ses-01) vs Post (ses-02)
- **Design**: 2×2 mixed ANOVA (Group × Time interaction)
- **Primary Atlas**: DiFuMo 256 (whole brain including cerebellum)
- **Covariates**: Age, sex, mean framewise displacement

**Primary Hypothesis**: Walking intervention increases motor-cerebellar connectivity

---

## Complete Workflow

### Step 1: CONN Preprocessing (MATLAB)

**Status**: In progress (awaiting sub-057 ses-02 fix)

Run in MATLAB:
```matlab
cd /Volumes/Work/Work/long/script
swap_sub057_to_run02  % Fix segmentation failure
conn_batch_longitudinal('full', 3)  % Resume with 3 parallel workers
```

**Expected Outputs**:
```
/Volumes/Work/Work/long/conn_project/
├── conn_longitudinal.mat           ← CONN project
└── results/
    └── preprocessing/
        ├── swua*.nii                ← Preprocessed functional (48 files)
        ├── wc1*.nii                 ← Grey matter (48 files)
        └── ROI_Subject*.mat         ← ROI timeseries (48 files)
```

**Duration**: ~6-12 hours (depends on parallel workers)

---

### Step 2: Export Timeseries from CONN (MATLAB)

**Purpose**: Extract denoised ROI timeseries for Python analysis

**Script**: `export_roi_timeseries_from_conn.m` (needs creation)

```matlab
% Load CONN project
conn_project = '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat';
conn('load', conn_project);

% Export timeseries for DiFuMo 256 atlas
atlas_name = 'difumo256';
output_dir = '/Volumes/Work/Work/long/results/timeseries/';

% Extract timeseries per subject/session
% Save to HDF5 format for Python
```

**Expected Output**:
```
/Volumes/Work/Work/long/results/timeseries/
└── timeseries_difumo256.h5
    ├── sub-033/
    │   ├── ses-01/timeseries [480 × 256]
    │   └── ses-02/timeseries [480 × 256]
    ├── sub-034/
    │   ├── ses-01/timeseries [480 × 256]
    │   └── ses-02/timeseries [480 × 256]
    └── ... (24 subjects × 2 sessions)
```

---

### Step 3: Prepare Metadata (Python/Manual)

**Purpose**: Create subject-level metadata file with covariates

**File**: `/Volumes/Work/Work/long/results/metadata.csv`

**Required Columns**:
```csv
subject,session,group,age,sex,mean_fd
sub-033,ses-01,Control,65,F,0.15
sub-033,ses-02,Control,65,F,0.18
sub-034,ses-01,Control,62,M,0.12
...
```

**How to Get Mean FD**:
- Extract from CONN: `CONN_x.Setup.rois.QA.FD` (per subject/session)
- Or use `conn gui` → Results → QA plots

**Manual Input Required**:
- Age: From participant demographics
- Sex: From participant demographics

**Script** (if demographics available):
```python
import pandas as pd

# Load completed subjects
subjects_df = pd.read_csv('/Volumes/Work/Work/long/completed_subjects_with_groups.csv')

# Load demographics (if you have a file)
demographics = pd.read_csv('path/to/demographics.csv')  # age, sex

# Load mean FD from CONN (extract from MATLAB)
mean_fd_df = pd.read_csv('mean_fd_from_conn.csv')

# Merge
metadata = subjects_df.merge(demographics, on='subject')
metadata = metadata.merge(mean_fd_df, on=['subject', 'session'])

# Save
metadata.to_csv('/Volumes/Work/Work/long/results/metadata.csv', index=False)
```

---

### Step 4: Run Connectivity Analysis (Python)

**Script**: `python_connectivity_analysis.py`

**Full Exploratory Analysis** (all ROI pairs):
```bash
cd /Volumes/Work/Work/long/script

python python_connectivity_analysis.py \\
    --timeseries /Volumes/Work/Work/long/results/timeseries/timeseries_difumo256.h5 \\
    --metadata /Volumes/Work/Work/long/results/metadata.csv \\
    --networks /Volumes/Work/Work/long/atlases/difumo256_network_definitions.json \\
    --output /Volumes/Work/Work/long/results/connectivity_analysis \\
    --alpha 0.05
```

**Hypothesis-Driven Analysis** (cerebellar network pairs only):
```bash
python python_connectivity_analysis.py \\
    --timeseries /Volumes/Work/Work/long/results/timeseries/timeseries_difumo256.h5 \\
    --metadata /Volumes/Work/Work/long/results/metadata.csv \\
    --networks /Volumes/Work/Work/long/atlases/difumo256_network_definitions.json \\
    --output /Volumes/Work/Work/long/results/connectivity_analysis_hypothesis \\
    --hypothesis-driven \\
    --alpha 0.05
```

**Outputs**:
```
/Volumes/Work/Work/long/results/connectivity_analysis/
├── connectivity_anova_results.csv          ← All ROI pairs with statistics
├── significant_interactions_fdr.csv        ← Significant Group×Time interactions
└── effect_sizes.csv                        ← Cohen's d for significant connections
```

**Duration**: ~30-60 minutes (depends on number of ROI pairs)

---

### Step 5: Generate Visualizations (Python)

**Script**: `python_visualization.py`

```bash
python python_visualization.py \\
    --results /Volumes/Work/Work/long/results/connectivity_analysis/connectivity_anova_results.csv \\
    --networks /Volumes/Work/Work/long/atlases/difumo256_network_definitions.json \\
    --effect-sizes /Volumes/Work/Work/long/results/connectivity_analysis/effect_sizes.csv \\
    --output /Volumes/Work/Work/long/figures/ \\
    --alpha 0.05 \\
    --top-n 50
```

**Outputs**:
```
/Volumes/Work/Work/long/figures/
├── connectivity_matrix_interaction.png     ← 256×256 matrix (network-ordered)
├── connectivity_matrix_group.png
├── connectivity_matrix_time.png
├── network_graph_interaction.png           ← Graph visualization (top 50 edges)
├── network_graph_group.png
├── network_graph_time.png
├── top_connections_interaction.png         ← Table with top 20 connections
├── top_connections_group.png
├── top_connections_time.png
└── effect_size_distribution.png            ← Cohen's d histogram
```

**Duration**: ~5 minutes

---

## Hypothesis-Driven Network Pairs

From `difumo256_network_definitions.json`:

### Refined Cerebellar Pairs

1. **Motor_Cerebellar_Motor** (286 connections)
   - Somatomotor cortex ↔ Motor cerebellum (Lobules IV, V, VI, VIIIb)
   - Hypothesis: Walking strengthens primary sensorimotor loop

2. **Motor_Cerebellar_Cognitive** (260 connections)
   - Somatomotor cortex ↔ Cognitive cerebellum (Crus I, Crus II, VIIb)
   - Hypothesis: Walking engages cerebellar learning systems

3. **FPCN_Cerebellar_Cognitive** (260 connections)
   - Frontoparietal control ↔ Cognitive cerebellum
   - Hypothesis: Executive control of complex motor sequences

4. **DMN_Cerebellar_Cognitive** (320 connections)
   - Default mode ↔ Cognitive cerebellum
   - Hypothesis: Cerebellar contributions to predictive processing

---

## Expected Results

### Successful Run

```
Loading timeseries from: timeseries_difumo256.h5
  Loaded 48 subject-session pairs

Computing connectivity matrices and preparing ANOVA data...
  Prepared 1,568,640 connectivity observations
  Subjects: 24
  ROI pairs: 32,640

Running mixed-effects ANOVA (Group × Time)...
    Processed 32,640/32,640 ROI pairs
  Completed 32,640 statistical tests

Applying FDR correction (alpha=0.05)...
  Significant interactions (FDR q<0.05): 152/32,640
  Significant group effects: 89/32,640
  Significant time effects: 234/32,640

Computing effect sizes for significant connections...
  Computed effect sizes for 152 connections

Saved full results to: results/connectivity_analysis/connectivity_anova_results.csv
Saved significant interactions to: results/connectivity_analysis/significant_interactions_fdr.csv
Saved effect sizes to: results/connectivity_analysis/effect_sizes.csv

Connectivity analysis complete!
```

---

## Statistical Model

**Mixed-Effects ANOVA**:
```
connectivity_z ~ Group × Time + Age + Sex + MeanFD + (1|Subject)
```

**Variables**:
- `connectivity_z`: Fisher Z-transformed correlation
- `Group`: Control (0) vs Walking (1)
- `Time`: Pre (0) vs Post (1)
- Covariates: Age (standardized), Sex (0=M, 1=F), Mean FD (standardized)
- Random effect: Subject (to account for repeated measures)

**Primary Contrast**: Group × Time interaction
- Tests: (Walking_Post - Walking_Pre) - (Control_Post - Control_Pre)
- Interpretation: Differential change in connectivity

**Multiple Comparisons**: FDR correction (Benjamini-Hochberg)

---

## Interpreting Results

### Significant Interaction

If `Motor_Cerebellar_Motor` connection shows:
- **interaction_coef = 0.25**
- **interaction_pval_fdr = 0.001**
- **cohens_d_interaction = 0.65** (medium-large effect)

**Interpretation**:
> Walking intervention significantly increased connectivity between motor cortex and motor cerebellum (β = 0.25, p_FDR < 0.001, d = 0.65), supporting the hypothesis that aerobic exercise strengthens sensorimotor integration.

### Connectivity Matrix

- **Blue regions**: Decreased connectivity
- **Red regions**: Increased connectivity
- **Black dots**: Significant connections (FDR q<0.05)
- **White grid lines**: Network boundaries

### Network Graph

- **Node size**: Degree (number of connections)
- **Node color**: Network membership
- **Edge thickness**: Effect size magnitude
- **Only shows**: Top N strongest significant connections

---

## Troubleshooting

### Issue: "No timeseries file"
**Solution**: Complete Step 2 (export from CONN)

### Issue: "Metadata missing for subject"
**Solution**: Ensure metadata.csv has all 24 subjects × 2 sessions = 48 rows

### Issue: "No significant results"
**Solution**:
- Check if preprocessing completed successfully
- Check motion (high mean FD may reduce power)
- Try hypothesis-driven analysis (fewer comparisons → better power)

### Issue: "Model convergence failed"
**Solution**:
- This is normal for some ROI pairs (insufficient variance)
- Script skips failed models and continues

---

## Dependencies

### Python Packages

```bash
# Core scientific computing
pip install numpy pandas scipy

# Statistics
pip install statsmodels

# Data I/O
pip install h5py

# Visualization
pip install matplotlib seaborn

# Graph analysis (optional)
pip install networkx
```

### MATLAB Toolboxes

- SPM12 (already installed)
- CONN toolbox (already installed)

---

## Citation

If using this workflow, cite:

1. **CONN Toolbox**: Whitfield-Gabrieli & Nieto-Castanon (2012). Conn: A functional connectivity toolbox.

2. **DiFuMo Atlas**: Dadi et al. (2020). Fine-grain atlases of functional modes for fMRI analysis. NeuroImage.

3. **Statsmodels**: Seabold & Perktold (2010). Statsmodels: Econometric and statistical modeling with Python.

---

## Next Steps After Analysis

1. **Manuscript Preparation**:
   - Use significant_interactions_fdr.csv for main results table
   - Include connectivity_matrix_interaction.png as Figure 1
   - Include network_graph_interaction.png as Figure 2
   - Report effect sizes (Cohen's d) from effect_sizes.csv

2. **Extended Analyses** (Optional):
   - Julia rDCM for effective connectivity (directional)
   - Graph theory metrics (global efficiency, modularity)
   - Granger causality (temporal precedence)

3. **Sensitivity Analyses**:
   - Rerun without motion covariate (check if FD explains effects)
   - Rerun with different atlas (Schaefer 400 for cortical validation)
   - Age/sex stratified analyses

---

## Contact

For questions about this workflow:
- Check documentation in `/Volumes/Work/Work/long/script/`
- Review plan file: `~/.claude/plans/hazy-brewing-deer.md`

**Created**: 2026-01-09
**Last Updated**: 2026-01-09
