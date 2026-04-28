# Statsmodels + FSL Thresholding Skill

**Purpose**: Guide for implementing group-level statistical analysis (Linear Mixed Effects models via statsmodels) and anatomical labeling (FSL thresholding + atlasq).

**Context**: Longevity study (44 subjects, 40 with 2 longitudinal sessions). Group-level analysis on connectivity maps, seed-based correlations, or local measures (fractional anisotropy, mean diffusivity).

---

## 1. Introduction

### Statsmodels for Mixed-Effects Models

**Why statsmodels?**
- Handles repeated measures (longitudinal designs with random intercepts/slopes)
- Supports formula-based syntax (similar to R, e.g., `y ~ group + session + (1|subject)`)
- Provides inference (t-statistics, p-values, confidence intervals)
- Efficient parallel computation via joblib for voxel-wise maps

**When to use:**
- Comparing group differences (intervention vs control) across brain regions
- Testing session effects (pre/post) with subject random effects
- Brain region contrasts with mixed designs

### FSL for Thresholding & Labeling

**Key tools:**
- **`fsl_cluster` / `fsl-cluster`**: Gaussian Random Field (GRF) thresholding; cluster-based multiple comparison correction
- **`fslmaths`**: Image algebra (thresholding, binarization, masking)
- **`atlasq query`**: Map cluster coordinates to anatomical labels (AAL, Harvard-Oxford, cerebellum atlases)
- **`smoothest`**: Estimate image smoothness (for GRF correction)
- **`std2imgcoord`**: Convert standard space (mm) to voxel coordinates

**Why FSL?**
- Proven GRF correction widely used in neuroimaging
- Integrated with major atlases (AAL3, Harvard-Oxford, FSL's own atlases)
- TFCE (Threshold-Free Cluster Enhancement) support for more sensitive thresholding

---

## 2. Statsmodels Linear Mixed Effects (LME)

### Formula Syntax

**Basic structure:**
```
y ~ fixed_effects + (random_effects|grouping_variable)
```

**Examples:**

1. **Simple intervention effect with random intercept:**
   ```
   value ~ group + (1|subject)
   ```
   - `value`: Dependent variable (voxel intensity, connectivity strength)
   - `group`: Fixed effect (intervention vs control)
   - `(1|subject)`: Random intercept per subject (accounts for within-subject variation)

2. **Longitudinal (pre-post) with interaction:**
   ```
   value ~ session * group + (1|subject)
   ```
   - `session`: Time effect (pre = 0, post = 1)
   - `session * group`: Interaction (group × time; tests differential change)
   - Random intercept allows baseline shifts per subject

3. **Longitudinal with random slopes:**
   ```
   value ~ session * group + (1 + session|subject)
   ```
   - `(1 + session|subject)`: Random intercept + random slope
   - Allows each subject's trajectory to differ in both starting point and slope
   - ⚠️ More parameters; requires sufficient data (rule of thumb: ≥30 subjects)

4. **Multi-region analysis with fixed region effect:**
   ```
   value ~ atlas_region + group + (1|subject)
   ```
   - `atlas_region`: Categorical (e.g., "dlpfc_l", "dlpfc_r", "acc")
   - Tests group effect within each region (region is a covariate)

5. **With covariates (age, sex):**
   ```
   value ~ group + session + age_std + sex_code + (1|subject)
   ```
   - `age_std`: Standardized age (mean=0, SD=1)
   - `sex_code`: Binary (e.g., 0=female, 1=male)
   - Covariates adjust for confounds

### Random Effects

**Random Intercepts (`(1|subject)`):**
- Each subject has its own baseline value
- Models between-subject variability
- Common; reduces False Positives when data are clustered by subject

**Random Slopes (`(1 + session|subject)`):**
- Each subject's slope differs
- Needed when subjects respond to treatment heterogeneously
- Increases model complexity; use only when justified

**Nested random effects (`(1|site/subject)`):**
- Multiple subjects per site, multiple sites per study
- Longevity study: single site, so typically not needed

### Fixed vs Random Effects

| Effect | Definition | In Model |
|--------|-----------|----------|
| **Fixed** | Population-level parameter; interest is in the effect magnitude | `y ~ group + session` |
| **Random** | Subject/site-specific deviation; interest is in population-level variation structure | `(1\|subject)` |
| **Covariate (fixed)** | Control variable (age, sex); typically not of primary interest but included for adjustment | `y ~ group + age_std` |

**Longevity context:**
- `group` (intervention/control), `session` (pre/post): **Fixed**
- `subject`: **Random** (intercept; each subject is a draw from population)
- `age`, `sex`: **Fixed** (covariates for adjustment)
- `site`: Not needed (single site)

### Fitting Models: `MixedLM.fit()`

**Python example:**
```python
from statsmodels.formula.api import mixedlm
import pandas as pd

# Prepare data: long format
# Columns: subject, session, group, value, age, sex
df = pd.DataFrame({
    'subject': [1, 1, 2, 2, ...],     # subject ID (repeated)
    'session': [0, 1, 0, 1, ...],     # 0=pre, 1=post
    'group': ['control', 'control', 'intervention', 'intervention', ...],
    'value': [0.5, 0.55, 0.4, 0.6, ...],  # voxel intensity or connectivity
    'age': [50, 50, 55, 55, ...],
    'sex': ['M', 'M', 'F', 'F', ...]
})

# Fit model
formula = "value ~ group + session + group:session + (1|subject)"
model = mixedlm(formula, data=df, groups=df['subject'])
result = model.fit(reml=True, method='nm', disp=False)

# Inspect results
print(result.summary())
print(result.tvalues)  # t-statistics for each effect
print(result.pvalues)  # p-values
print(result.conf_int())  # 95% confidence intervals
```

**Key parameters:**
- `reml=True`: Use Restricted Maximum Likelihood (preferred for inference; conservative)
- `reml=False`: Use Full ML (for likelihood ratio tests comparing nested models)
- `method='nm'`: Nelder-Mead optimization (robust; slower but reliable)
- `method='powell'`: Powell optimization (faster; may fail for ill-conditioned problems)
- `disp=False`: Suppress iteration output (useful for parallel jobs)

### Extracting Results

**Coefficients:**
```python
# Extract fixed effects
coef = result.fe_params  # Named Series: group, session, group:session, etc.
print(coef['group[T.intervention]'])  # Reference coding (control is baseline)
```

**Inference:**
```python
# T-statistics and p-values
tval = result.tvalues['group[T.intervention]']
pval = result.pvalues['group[T.intervention]']

# Confidence intervals
ci = result.conf_int(alpha=0.05)  # 95% CI
ci_intervention = ci.loc['group[T.intervention]']  # [lower, upper]
```

**Model diagnostics:**
```python
# Likelihood Ratio Test (nested models)
# model1 = value ~ group + (1|subject)
# model2 = value ~ group + session + (1|subject)
lr_stat = 2 * (result2.llf - result1.llf)
p_value = 1 - scipy.stats.chi2.cdf(lr_stat, df=1)  # 1 df for 1 additional param

# Residual diagnostics
residuals = result.resid
fitted = result.fittedvalues
# Check normality and homoscedasticity
```

---

## 3. Preparing Data for LME

### Flattening Brain Maps

**Input:** NIfTI voxel-wise maps (e.g., seed-based connectivity z-maps, t-statistics)
**Output:** Long-format DataFrame for model fitting

**Example workflow:**
```python
import nibabel as nib
import numpy as np
import pandas as pd
from nilearn.masking import apply_mask

# Load map and brain mask
map_nii = nib.load('sub-001_ses-01_seed-dlpfc_zmap.nii.gz')
mask_nii = nib.load('MNI152_T1_2mm_brain_mask.nii.gz')

# Flatten voxels (apply mask to reduce dimensionality)
map_data = apply_mask(map_nii, mask_nii)  # Shape: (n_voxels,)

# For all subjects/sessions, load and stack
maps_list = []
subjects = [1, 2, 3, ..., 44]
sessions = [1, 2]  # 40 subjects have 2 sessions; some have 1

for sub in subjects:
    for ses in sessions:
        fpath = f'results/seed_based/dlpfc_l/sub-{sub:03d}_ses-{ses:02d}_zmap.nii.gz'
        try:
            nii = nib.load(fpath)
            voxel_data = apply_mask(nii, mask_nii)
            maps_list.append(voxel_data)
        except FileNotFoundError:
            print(f"  Skipping {fpath}")

maps_array = np.array(maps_list)  # Shape: (n_scans, n_voxels)
```

### Organizing as Long-Format DataFrame

**Design:**
```python
# Load metadata
metadata = pd.read_csv('results/metadata.csv')
# Columns: subject, session, group (intervention/control), age, sex, ...

# Expand for voxels
n_voxels = maps_array.shape[1]
rows = []

for i, (sub, ses) in enumerate(zip(metadata['subject'], metadata['session'])):
    for vox_idx in range(n_voxels):
        rows.append({
            'subject': sub,
            'session': ses,
            'group': metadata.loc[i, 'group'],
            'age': metadata.loc[i, 'age'],
            'sex': metadata.loc[i, 'sex'],
            'value': maps_array[i, vox_idx],
            'voxel_id': vox_idx
        })

df_long = pd.DataFrame(rows)
print(df_long.shape)  # (n_scans × n_voxels, 7)
```

**Result shape:** (~80 scans) × (50,000 voxels) = 4M rows. ⚠️ Memory-intensive; see **Parallel Voxel-Wise Analysis** below.

### Handling Missing Data and Exclusions

**QC-based exclusions:**
- Use `bids_excluded/` directory and `qc_status.json` to identify bad scans
- Drop excluded rows from metadata before loading maps

```python
import json

# Load QC exclusions
with open('bids/derivatives/qc_status.json', 'r') as f:
    qc_status = json.load(f)

excluded = [item for item, status in qc_status.items() if status == 'excluded']
excluded_subs_sessions = [tuple(ex.split('/')) for ex in excluded]  # [('sub-033', 'ses-01'), ...]

# Filter metadata
metadata_filtered = metadata[
    ~metadata[['subject_label', 'session']].apply(
        lambda row: (f"sub-{row[0]:03d}", f"ses-{row[1]:02d}") in excluded_subs_sessions,
        axis=1
    )
]
```

**Within-subject missing data:**
- Some sessions may have missing voxels (e.g., motion artifacts)
- LME handles missing data via listwise deletion on affected rows
- Verify expected n per group before fitting

```python
# Check for completeness
print(df_long.groupby('subject')['session'].count())
print(df_long.groupby('group')['subject'].nunique())
```

### Within-Subject Repeated Measures Structure

**DataFrame structure for repeated measures:**
```
subject | session | group     | value   | voxel_id
--------|---------|-----------|---------|----------
1       | 1       | control   | 0.50    | 0
1       | 2       | control   | 0.55    | 0
2       | 1       | control   | 0.48    | 0
2       | 2       | control   | 0.54    | 0
3       | 1       | interv.   | 0.40    | 0
3       | 2       | interv.   | 0.60    | 0
...
```

**Key requirements:**
- `subject` column uniquely identifies each individual
- Multiple rows per subject (one per session) → LME recognizes repeated structure
- `(1|subject)` in formula tells model to account for clustering within subject
- Missing data: If subject has only 1 session, one row per subject (unbalanced design)

---

## 4. Model Specifications

### Formula Examples for Different Designs

#### 1. Intervention Effect (Cross-Sectional or Collapsed Sessions)
```
value ~ group + (1|subject)
```
- **Tests:** Does intervention group differ from control in mean connectivity?
- **Output:** `group[T.intervention]` coefficient (assumes control is reference)
- **Effect size:** Cohen's d ≈ coef / residual_sd

#### 2. Longitudinal: Pre-Post with Interaction
```
value ~ session * group + (1|subject)
```
- **Tests:**
  - `session`: Overall pre-post change (across groups)
  - `group[T.intervention]`: Baseline group difference (at session 0)
  - `session:group[T.intervention]`: **Interaction—differential change (main effect of interest)**
- **Interpretation:** Interaction = group-by-time; tests if post-pre change differs by group

#### 3. Within-Subject Session Effect
```
value ~ session + (1 + session|subject)
```
- **Tests:** Does connectivity change over sessions (random slope model)?
- **Output:** `session` coefficient (population-level change) + random slopes (subject heterogeneity)
- **Caution:** Requires sufficient data; not recommended for <30 subjects per group

#### 4. Brain Region Contrasts
```
value ~ atlas_region + group + (1|subject)
```
- **Tests:** Group difference controlling for anatomical region
- **Output:** `atlas_region[T.region_name]` + `group[T.intervention]`
- **Use case:** Meta-region analysis (e.g., compare DMN components)

#### 5. Full Longitudinal Model with Covariates
```
value ~ (session + group)^2 + age_std + sex_code + (1|subject)
```
- `(session + group)^2` expands to `session + group + session:group`
- **Covariates:** Age, sex (centered/coded as needed)
- **Rationale:** Adjust for confounds; improves power

### Contrast Testing (Partial F-Tests)

**Compare nested models to test specific effects:**

```python
# Reduced model (no interaction)
formula_reduced = "value ~ session + group + (1|subject)"
model_reduced = mixedlm(formula_reduced, data=df, groups=df['subject'])
result_reduced = model_reduced.fit(reml=False)  # Use ML for LRT

# Full model (with interaction)
formula_full = "value ~ session * group + (1|subject)"
model_full = mixedlm(formula_full, data=df, groups=df['subject'])
result_full = model_full.fit(reml=False)

# Likelihood Ratio Test
from scipy.stats import chi2
lr_stat = 2 * (result_full.llf - result_reduced.llf)
p_value = 1 - chi2.cdf(lr_stat, df=1)
print(f"LRT: χ² = {lr_stat:.2f}, p = {p_value:.4f}")
```

**Wald test (simpler; less powerful):**
```python
# Test if session:group interaction term = 0
test_result = result_full.wald_test_terms()
print(test_result)
```

---

## 5. Post-Hoc Analysis

### Extracting Regional Average Effects

**Aggregate voxels within anatomical regions:**

```python
import nibabel as nib
from nilearn.masking import apply_mask

# Load region mask (e.g., DiFuMo 256, region #10 = mPFC)
region_mask = nib.load('atlases/difumo_256_region_10.nii.gz')

# Average connectivity within region
maps_regional = []
for sub in subjects:
    for ses in sessions:
        fpath = f'results/seed_based/dlpfc_l/sub-{sub:03d}_ses-{ses:02d}_zmap.nii.gz'
        nii = nib.load(fpath)
        region_mean = apply_mask(nii, region_mask).mean()
        maps_regional.append(region_mean)

# Fit LME on regional summary
df_regional = metadata.copy()
df_regional['connectivity'] = maps_regional
result_region = mixedlm("connectivity ~ session * group + (1|subject)", 
                        data=df_regional, groups=df_regional['subject']).fit()
```

### Confidence Intervals

```python
# 95% CI for intervention effect
ci = result.conf_int(alpha=0.05)
intervention_ci = ci.loc['group[T.intervention]']
print(f"Intervention effect: {coef['group[T.intervention]']:.4f}")
print(f"95% CI: [{intervention_ci[0]:.4f}, {intervention_ci[1]:.4f}]")

# Profile CI (more accurate for complex models)
# ci_profile = result.conf_int(method='profile')
```

### Effect Sizes (Cohen's d)

**From model parameters:**
```python
# Standardized effect size
coef_intervention = result.fe_params['group[T.intervention]']
residual_sd = np.sqrt(result.scale)  # or result.cov_params().loc['Residual.Var', 'Residual.Var']

cohens_d = coef_intervention / residual_sd
print(f"Cohen's d = {cohens_d:.3f}")

# Interpretation: d < 0.2 (negligible), 0.2-0.5 (small), 0.5-0.8 (medium), > 0.8 (large)
```

---

## 6. FSL Integration

### Key FSL Commands

#### **fsl_cluster / fsl-cluster**
Identify clusters in a statistical map using GRF correction.

**Usage:**
```bash
fsl-cluster -i input_stat.nii.gz \
  -t 2.3 \                           # Voxel threshold (e.g., z > 2.3)
  -p 0.05 \                          # Cluster p-value (FWE correction)
  -d dlh_value \                     # DLH (Euler characteristic density)
  -m brain_mask.nii.gz \             # Brain mask
  -c input_cope.nii.gz \             # COPE image (effect size map)
  --minextent 10 \                   # Minimum cluster size (voxels)
  --mm                               # Report coords in mm (not voxels)
```

**Outputs:**
- Cluster index image (integer labels for each cluster)
- Cluster summary table (voxel count, p-value, peak coords)
- Peak voxel coordinates (x, y, z in mm)

#### **fslmaths**
Image algebra for preprocessing statistical maps.

**Common operations:**
```bash
# Threshold at z > 2.3
fslmaths zstat.nii.gz -thr 2.3 zstat_thresh.nii.gz

# Binarize
fslmaths zstat_thresh.nii.gz -bin zstat_binary.nii.gz

# Multiply by factor
fslmaths zstat.nii.gz -mul -1 zstat_neg.nii.gz

# Apply mask
fslmaths zstat.nii.gz -mas brain_mask.nii.gz zstat_masked.nii.gz

# Boolean operations
fslmaths activation.nii.gz -sub deactivation.nii.gz contrast.nii.gz
```

#### **atlasq query**
Map voxels/regions to anatomical labels.

**Syntax:**
```bash
atlasq query atlas_name [ -m mask.nii.gz ] [ -c x y z ] [ -l ]

# Example: Query AAL3 atlas at cluster
atlasq query aal3v1 -m cluster.nii.gz

# With label percentages
atlasq query harvardoxford-cortical -l -m cluster.nii.gz
```

**Available atlases:**
- `aal3v1`: AAL3 (advanced anatomical labeling, v3.1)
- `harvardoxford-cortical`: Harvard-Oxford cortical atlas
- `harvardoxford-subcortical`: Harvard-Oxford subcortical atlas
- `cerebellum_mnifnirt`: Cerebellar parcellation
- `juelich`: Juelich (cytoarchitectonic) atlas

**Output format:**
```
Region Label | Voxel Count | Percentage
mPFC         | 250         | 45.2%
ACC          | 180         | 32.5%
...
```

#### **smoothest**
Estimate spatial smoothness (FWHM, DLH, RESELS) for GRF correction.

**Usage:**
```bash
# From residual sum of squares (res4d)
smoothest -d dof_value -m brain_mask.nii.gz -r res4d.nii.gz

# From z-stat (if res4d unavailable)
smoothest -z zstat.nii.gz -m brain_mask.nii.gz
```

**Output:** DLH, RESELS, VOLUME (needed for fsl-cluster)

#### **std2imgcoord**
Convert standard space (mm) to image/voxel coordinates.

**Usage:**
```bash
# Convert from mm to voxel coords
echo "10.5 -20.3 8.2" | std2imgcoord -img MNI152_T1_2mm.nii.gz -std MNI152_T1_2mm.nii.gz -vox -
```

### Example: FSL Cluster from LME t-Stat Map

**Workflow:**
1. Fit LME model → save t-statistic map (NIfTI)
2. Estimate smoothness
3. Run fsl-cluster with GRF correction
4. Annotate clusters with atlasq

**Bash script template (from `script/fsl/cluster.sh`):**
```bash
#!/bin/bash

input_tstat=results/group_stats/intervention_vs_control_tstat.nii.gz
outdir=results/group_stats/clusters
mask=${FSLDIR}/data/standard/MNI152_T1_2mm_brain_mask.nii.gz

mkdir -p $outdir

# Estimate smoothness
res4d=results/group_stats/res4d.nii.gz  # If available from FEAT
smoothest -d 40 -m $mask -r $res4d > smoothness.txt

# Extract DLH, RESELS
dlh=$(grep DLH smoothness.txt | awk '{print $NF}')
resels=$(grep RESELS smoothness.txt | awk '{print $NF}')

# Threshold and cluster
fslmaths $input_tstat -thr 2.3 ${outdir}/tstat_thresh

fsl-cluster -i ${outdir}/tstat_thresh \
  -t 2.3 -p 0.05 -d $dlh --volume=... \
  -m $mask \
  -c ${input_tstat} \
  --minextent 10 --mm \
  | tee ${outdir}/clusters.txt

# Save cluster-indexed image
fslmaths ${outdir}/tstat_thresh -mas cluster_index ${outdir}/tstat_cluster.nii.gz
```

---

## 7. TFCE & Permutation Testing

### TFCE (Threshold-Free Cluster Enhancement)

**Concept:**
- Does not require a priori voxel threshold
- Scores voxels based on local clustering (multiresolution)
- More sensitive than fixed-threshold GRF for small/scattered effects

**FSL TFCE:**
- Built into FEAT (outputs `tfce_corrp_tstat*.nii.gz`)
- Via command-line: not directly available in standard FSL; use external tools or custom Python

**Python alternative (scipy permutation framework):**
```python
from scipy import stats as scipy_stats

# Permutation testing for TFCE-like correction
def permutation_test_tfce(maps, group_labels, n_perm=1000):
    """
    Permutation test with TFCE-like scoring.
    
    Args:
        maps: (n_scans, n_voxels) array
        group_labels: (n_scans,) binary array [0=control, 1=intervention]
        n_perm: number of permutations
    
    Returns:
        corrected_pvalues: (n_voxels,) array of permutation p-values
    """
    n_scans, n_voxels = maps.shape
    observed_stats = np.zeros(n_voxels)
    perm_max_stats = np.zeros(n_perm)
    
    # Observed t-statistics (per voxel)
    for v in range(n_voxels):
        t_stat, _ = scipy_stats.ttest_ind(
            maps[group_labels == 1, v],
            maps[group_labels == 0, v]
        )
        observed_stats[v] = np.abs(t_stat)
    
    # Permutations
    for perm in range(n_perm):
        perm_labels = np.random.permutation(group_labels)
        perm_stats = np.zeros(n_voxels)
        for v in range(n_voxels):
            t_stat, _ = scipy_stats.ttest_ind(
                maps[perm_labels == 1, v],
                maps[perm_labels == 0, v]
            )
            perm_stats[v] = np.abs(t_stat)
        perm_max_stats[perm] = np.max(perm_stats)  # Max-T approach
    
    # P-value per voxel
    corrected_pvalues = np.array([
        np.mean(perm_max_stats >= observed_stats[v])
        for v in range(n_voxels)
    ])
    
    return corrected_pvalues
```

### Corrected P-Values and Thresholds

**Multiple comparison methods:**

| Method | Pros | Cons |
|--------|------|------|
| **FWE (Bonferroni)** | Simple, conservative | Too strict; many false negatives |
| **GRF** | Accounts for spatial smoothness | Depends on smoothness estimate |
| **TFCE** | Sensitive to multi-scale clusters | Computationally expensive |
| **Permutation** | Nonparametric; no distributional assumptions | Expensive (1000+ permutations) |
| **FDR** | Balance sensitivity/specificity | Less stringent (p < 0.05 → 5% false discoveries) |

**FDR correction (less stringent, faster):**
```python
from statsmodels.stats.multitest import multipletests

# Voxelwise p-values from LME
pvalues = np.array([...])  # (n_voxels,)

# FDR correction at α=0.05
rejected, pvalues_fdr, _, _ = multipletests(pvalues, alpha=0.05, method='fdr_bh')
# rejected: boolean array (True = significant)
# pvalues_fdr: adjusted p-values
```

---

## 8. Workflow: GRF/TFCE/Permutation Correction

### Step-by-Step Example: Intervention vs Control

**Scenario:**
- 44 subjects (22 intervention, 22 control)
- 40 with 2 sessions, 4 with 1 session
- Seed: bilateral DLPFC; outcome: seed-based connectivity z-maps
- Goal: Identify regions where intervention group shows greater connectivity increase

### A. Fit LME Model on Voxel-Wise Data

```python
import pandas as pd
import numpy as np
from statsmodels.formula.api import mixedlm
from joblib import Parallel, delayed

# Load metadata & maps
metadata = pd.read_csv('results/metadata.csv')
# Columns: subject, session, group, age, sex, ...

# Load maps (voxel x scan)
maps_data = np.load('results/seed_dlpfc_zmaps.npy')  # (n_scans, n_voxels)

# Prepare template dataframe
df_template = metadata.copy()

# Parallel voxel-wise LME fitting
def fit_voxel(vox_idx, maps_data, df_template):
    df = df_template.copy()
    df['value'] = maps_data[:, vox_idx]
    
    # Skip if no variance
    if df['value'].std() < 1e-10:
        return np.nan, 1.0, np.nan, np.nan
    
    try:
        formula = "value ~ session * group + age_std + sex_code + (1|subject)"
        model = mixedlm(formula, data=df, groups=df['subject'])
        result = model.fit(reml=True, method='nm', disp=False)
        
        # Extract session:group interaction (main effect of interest)
        tstat = result.tvalues.get('session:group[T.intervention]', np.nan)
        pval = result.pvalues.get('session:group[T.intervention]', np.nan)
        
        # Also extract main group effect (baseline difference)
        group_tstat = result.tvalues.get('group[T.intervention]', np.nan)
        
        return tstat, pval, group_tstat, np.nan
    except Exception as e:
        print(f"Voxel {vox_idx}: {e}")
        return np.nan, 1.0, np.nan, np.nan

# Run in parallel
n_voxels = maps_data.shape[1]
n_jobs = 8
results = Parallel(n_jobs=n_jobs)(
    delayed(fit_voxel)(vox, maps_data, df_template)
    for vox in range(n_voxels)
)

# Unpack results
t_stats, p_vals, group_t, _ = zip(*results)
t_stats = np.array(t_stats)
p_vals = np.array(p_vals)

print(f"Mean |t| = {np.nanmean(np.abs(t_stats)):.3f}")
print(f"Min p = {np.nanmin(p_vals):.2e}")
```

### B. Save T-Stat Map (NIfTI)

```python
import nibabel as nib
from nilearn.masking import unmask

# Reconstruct t-stat image
mask = nib.load(mask_path)
tstat_img = unmask(t_stats, mask)

# Save
nib.save(tstat_img, 'results/group_stats/intervention_vs_control_interaction_tstat.nii.gz')
```

### C. Choose Correction Method

#### **Option 1: GRF Correction (FSL)**

```bash
#!/bin/bash

tstat_map=results/group_stats/intervention_vs_control_interaction_tstat.nii.gz
outdir=results/group_stats/grf_corrected
mask=${FSLDIR}/data/standard/MNI152_T1_2mm_brain_mask.nii.gz

mkdir -p $outdir

# Estimate smoothness (from zstat, if available)
smoothest -z $tstat_map -m $mask > $outdir/smoothness.txt
dlh=$(grep DLH $outdir/smoothness.txt | awk '{print $NF}')
volume=$(grep VOLUME $outdir/smoothness.txt | awk '{print $NF}')

# Threshold
voxt=2.3  # z > 2.3
fslmaths $tstat_map -thr $voxt $outdir/tstat_thresh

# Cluster with GRF correction
fsl-cluster -i $outdir/tstat_thresh \
  -t $voxt -p 0.05 -d $dlh --volume=$volume \
  -m $mask \
  --minextent 10 --mm \
  | tee $outdir/clusters.txt
```

#### **Option 2: Permutation Testing (Python)**

```python
# Permutation-corrected p-values
from longevity.script.utils import permutation_test_max_t

corrected_pvals = permutation_test_max_t(
    maps_data=maps_data,
    group_labels=metadata['group_code'].values,  # [0=control, 1=intervention]
    formula="value ~ session * group + age_std + sex_code + (1|subject)",
    metadata=metadata,
    n_permutations=1000,
    n_jobs=8
)

# Threshold at α=0.05 (FWE)
significant_voxels = corrected_pvals < 0.05
print(f"Significant voxels: {significant_voxels.sum()} / {len(corrected_pvals)}")
```

#### **Option 3: FDR Correction (Python, Fastest)**

```python
from statsmodels.stats.multitest import multipletests

# FDR correction
_, p_fdr, _, _ = multipletests(p_vals, alpha=0.05, method='fdr_bh')

# Threshold
significant_voxels = p_fdr < 0.05
print(f"Significant voxels (FDR): {significant_voxels.sum()}")

# Save corrected p-value map
p_fdr_img = unmask(p_fdr, mask)
nib.save(p_fdr_img, 'results/group_stats/fdr_corrected_pvals.nii.gz')
```

### D. Generate Cluster Output

**From FSL:**
```bash
# clusters.txt contains cluster info; extract cluster indices
fsl-cluster -i $outdir/tstat_thresh \
  -t 2.3 -p 0.05 --minextent 10 --mm \
  -o $outdir/cluster_index.nii.gz \
  | tee $outdir/clusters.txt
```

**From Python (for permutation/FDR):**
```python
from scipy.ndimage import label as ndimage_label

# Binarize significant voxels
sig_binary = significant_voxels.astype(int)
sig_img = unmask(sig_binary, mask)

# Label connected components
cluster_labels, n_clusters = ndimage_label(sig_img.get_fdata())
print(f"Number of clusters: {n_clusters}")

nib.save(nib.Nifti1Image(cluster_labels, sig_img.affine), 
         'results/group_stats/cluster_index.nii.gz')
```

---

## 9. FSL atlasq Integration

### Parsing Cluster Centers (x, y, z Coordinates)

**From FSL cluster output:**
```bash
# clusters.txt (from fsl-cluster) format:
# Cluster Index | Voxels | p-value | Max t | x (mm) | y (mm) | z (mm)
#       1       |  450   | 0.001   | 5.23  |  -8.5  |  22.3  |  12.1
#       2       |  320   | 0.012   | 4.11  | 15.2   |  -5.0  |  8.7

# Extract coordinates
awk 'NR>1 {print $5, $6, $7}' clusters.txt > cluster_coords.txt
```

**From Python (connected components):**
```python
from scipy.ndimage import center_of_mass

# Find cluster centers
cluster_coords = center_of_mass(cluster_labels, cluster_labels, 
                                range(1, n_clusters + 1))
# cluster_coords: list of (i, j, k) voxel indices

# Convert to mm (MNI space)
affine = mask.affine
coords_mm = np.array([
    affine @ np.append(coord, 1)  # Homogeneous coords
    for coord in cluster_coords
])[:, :3]
```

### Running atlasq for Each Cluster

**Bash loop (from `script/fsl/cluster.sh`):**
```bash
#!/bin/bash

cluster_index_img=results/group_stats/cluster_index.nii.gz
outdir=results/group_stats/atlas_labels

mkdir -p $outdir

# For each cluster (1 to N), extract region and query atlas
for cluster_id in $(seq 1 10); do  # Assume 10 clusters
    # Extract binary mask for this cluster
    fslmaths $cluster_index_img -thr $cluster_id -uthr $cluster_id -bin \
        ${outdir}/cluster_${cluster_id}.nii.gz
    
    # Query multiple atlases
    atlasq query aal3v1 -m ${outdir}/cluster_${cluster_id}.nii.gz \
        > ${outdir}/cluster_${cluster_id}_aal.txt
    
    atlasq query harvardoxford-cortical -l -m ${outdir}/cluster_${cluster_id}.nii.gz \
        > ${outdir}/cluster_${cluster_id}_hoc.txt
    
    atlasq query harvardoxford-subcortical -l -m ${outdir}/cluster_${cluster_id}.nii.gz \
        > ${outdir}/cluster_${cluster_id}_hos.txt
    
    atlasq query cerebellum_mnifnirt -l -m ${outdir}/cluster_${cluster_id}.nii.gz \
        > ${outdir}/cluster_${cluster_id}_cerebellum.txt
done
```

**Python equivalent:**
```python
import subprocess
import os

for cluster_id in range(1, n_clusters + 1):
    cluster_mask_path = f'{outdir}/cluster_{cluster_id}.nii.gz'
    
    # Extract mask
    os.system(f'fslmaths {cluster_index_img} -thr {cluster_id} -uthr {cluster_id} -bin {cluster_mask_path}')
    
    # Query atlases
    for atlas in ['aal3v1', 'harvardoxford-cortical', 'harvardoxford-subcortical']:
        output_file = f'{outdir}/cluster_{cluster_id}_{atlas}.txt'
        cmd = f'atlasq query {atlas} -l -m {cluster_mask_path}'
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        with open(output_file, 'w') as f:
            f.write(result.stdout)
```

### Extracting Regional Labels

**Parse atlasq output:**
```bash
# atlasq output format:
# Region Label | Voxels | Percentage
# mPFC         | 250    | 45.2%
# ACC          | 180    | 32.5%

# Extract top region (highest %)
top_region=$(cat cluster_1_aal.txt | \
    grep -v "^|\|^-\|^$" | \
    awk -F '|' 'NR>1 {print $1, $3}' | \
    sort -k2 -rn | \
    head -1)

echo $top_region  # "mPFC 45.2%"
```

**Python parsing:**
```python
def parse_atlasq_output(filepath):
    """Parse atlasq query result; return list of (region, percentage)."""
    regions = []
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('-') or line.startswith('|'):
                continue
            parts = line.split('|')
            if len(parts) >= 3:
                region = parts[1].strip()
                pct_str = parts[2].strip().rstrip('%')
                try:
                    pct = float(pct_str)
                    regions.append((region, pct))
                except ValueError:
                    pass
    return sorted(regions, key=lambda x: x[1], reverse=True)

# Get top region for cluster 1
regions = parse_atlasq_output('atlas_labels/cluster_1_aal.txt')
top_region = regions[0][0] if regions else 'Unknown'
print(f"Top region: {top_region}")
```

### Creating Annotated Cluster Table

**Combined summary CSV:**
```python
import pandas as pd

clusters_data = []

for cluster_id in range(1, n_clusters + 1):
    # Cluster metrics
    voxel_count = cluster_voxel_counts[cluster_id]
    peak_tstat = cluster_peak_tstats[cluster_id]
    peak_pval = cluster_peak_pvals[cluster_id]
    peak_x, peak_y, peak_z = cluster_coords_mm[cluster_id - 1]
    
    # Anatomical labels (from atlasq)
    aal_regions = parse_atlasq_output(f'atlas_labels/cluster_{cluster_id}_aal.txt')
    hoc_regions = parse_atlasq_output(f'atlas_labels/cluster_{cluster_id}_hoc.txt')
    
    top_aal = aal_regions[0][0] if aal_regions else 'Unknown'
    top_hoc = hoc_regions[0][0] if hoc_regions else 'Unknown'
    
    clusters_data.append({
        'Cluster_ID': cluster_id,
        'Voxels': voxel_count,
        'Peak_t': peak_tstat,
        'Peak_p': peak_pval,
        'X_mm': peak_x,
        'Y_mm': peak_y,
        'Z_mm': peak_z,
        'AAL_Label': top_aal,
        'HO_Label': top_hoc,
    })

df_clusters = pd.DataFrame(clusters_data)
df_clusters.to_csv('results/group_stats/cluster_summary.csv', index=False)
print(df_clusters)
```

**Example output:**
```
Cluster_ID | Voxels | Peak_t | Peak_p | X_mm  | Y_mm | Z_mm | AAL_Label | HO_Label
    1      |  450   | 5.23   | 0.001  | -8.5  | 22.3 | 12.1 | mPFC      | Medial PFC
    2      |  320   | 4.11   | 0.012  | 15.2  | -5.0 | 8.7  | dlPFC     | Dorsolateral PFC
    3      |  210   | 3.89   | 0.018  |-12.3  |-45.2 | 35.1 | pSTS      | Posterior STS
```

---

## 10. Output Format

### CSV Cluster Table

**Recommended columns:**
```python
cluster_table = pd.DataFrame({
    'Cluster_ID': cluster_ids,
    'Voxels': voxel_counts,
    'Peak_t': peak_tstats,
    'Peak_p': peak_pvalues,
    'Peak_FWE_p': fwe_corrected_pvalues,  # After GRF/permutation
    'X_mm': x_coords,
    'Y_mm': y_coords,
    'Z_mm': z_coords,
    'AAL_Region': aal_labels,
    'HarvardOxford_Cortical': ho_cortical_labels,
    'HarvardOxford_Subcortical': ho_subcortical_labels,
    'Cerebellum_Region': cerebellum_labels,
    'Effect_Direction': effect_directions,  # 'Positive' or 'Negative'
})

cluster_table.to_csv('results/group_stats/clusters_annotated.csv', index=False)
```

### Statistical Maps (NIfTI Format)

**Save multiple maps:**
```python
import nibabel as nib
from nilearn.masking import unmask

mask = nib.load(mask_path)

# T-statistic map (raw)
nib.save(unmask(t_stats, mask), 'results/group_stats/tstat_map.nii.gz')

# P-value map (uncorrected)
nib.save(unmask(p_vals, mask), 'results/group_stats/pval_map.nii.gz')

# Cluster index map
nib.save(unmask(cluster_labels, mask), 'results/group_stats/cluster_index.nii.gz')

# Binary significance map (FWE-corrected, p < 0.05)
sig_binary = (corrected_pvals < 0.05).astype(int)
nib.save(unmask(sig_binary, mask), 'results/group_stats/significant_voxels_fwe.nii.gz')
```

### Summary Report

**HTML report template:**
```html
<!DOCTYPE html>
<html>
<head>
    <title>Group-Level Analysis Report</title>
    <style>
        body { font-family: Arial; margin: 20px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 10px; text-align: left; }
        th { background-color: #4CAF50; color: white; }
    </style>
</head>
<body>
    <h1>Group-Level Statistical Analysis</h1>
    
    <h2>Model Summary</h2>
    <ul>
        <li>Formula: <code>value ~ session * group + age_std + sex_code + (1|subject)</code></li>
        <li>N Subjects: 44 (22 intervention, 22 control)</li>
        <li>N Scans: 80 (40 subjects × 2 sessions, 4 subjects × 1 session)</li>
        <li>N Voxels: 50,000 (MNI152 2mm brain mask)</li>
        <li>Multiple Comparison Correction: GRF (p_FWE < 0.05)</li>
    </ul>
    
    <h2>Significant Clusters</h2>
    <table>
        <tr>
            <th>Cluster ID</th>
            <th>Voxels</th>
            <th>Peak t</th>
            <th>Peak p (FWE)</th>
            <th>x, y, z (mm)</th>
            <th>Top Region (AAL)</th>
        </tr>
        <!-- Populated from cluster_summary.csv -->
    </table>
    
    <h2>Effect Interpretation</h2>
    <p>The session:group interaction term tests whether the change in connectivity (pre to post) 
    differs between intervention and control groups. Positive interaction: intervention group shows 
    greater increase (or smaller decrease) in connectivity over time.</p>
    
    <h2>Files Generated</h2>
    <ul>
        <li>cluster_summary.csv: Annotated cluster table</li>
        <li>tstat_map.nii.gz: Raw t-statistic map</li>
        <li>cluster_index.nii.gz: Cluster labels (visualize in FSLView)</li>
    </ul>
</body>
</html>
```

---

## 11. Code Examples

### Complete Example: Fit LME on Seed Connectivity Maps

**File:** `script/group_level_analysis_complete.py`

```python
#!/usr/bin/env python3
"""
Complete workflow: Load seed-based connectivity maps → Fit LME model → 
Generate t-stat map → Apply GRF correction → Annotate clusters.
"""

import os
import argparse
import json
import subprocess
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
from scipy.stats import chi2
from nilearn.masking import apply_mask, unmask
from nilearn.image import resample_to_img
from statsmodels.formula.api import mixedlm
from joblib import Parallel, delayed
import warnings

warnings.filterwarnings('ignore')

def load_metadata(csv_path):
    """Load and standardize metadata."""
    df = pd.read_csv(csv_path)
    
    # Standardize continuous covariates
    if 'age' in df.columns:
        df['age_std'] = (df['age'] - df['age'].mean()) / df['age'].std()
    else:
        df['age_std'] = 0
    
    # Code sex binary
    if 'sex' in df.columns:
        df['sex_code'] = (df['sex'] == 'M').astype(int)
    else:
        df['sex_code'] = 0
    
    return df

def fit_voxel_lme(vox_idx, maps_array, df_template, formula):
    """Fit LME for single voxel."""
    df = df_template.copy()
    df['value'] = maps_array[:, vox_idx]
    
    if df['value'].std() < 1e-10:
        return np.nan, 1.0
    
    try:
        model = mixedlm(formula, data=df, groups=df['subject'])
        result = model.fit(reml=True, method='nm', disp=False)
        
        # Extract interaction term (main effect of interest)
        tstat = result.tvalues.get('session:group[T.intervention]', np.nan)
        pval = result.pvalues.get('session:group[T.intervention]', np.nan)
        return tstat, pval
    except Exception:
        return np.nan, 1.0

def main(args):
    # Setup
    outdir = Path(args.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    
    # Load metadata
    metadata = load_metadata(args.metadata)
    
    # Load connectivity maps
    print("[1/5] Loading connectivity maps...")
    maps_list = []
    valid_scans = []
    
    for idx, row in metadata.iterrows():
        map_path = Path(args.input_maps.format(
            subject=f"sub-{row['subject']:03d}",
            session=f"ses-{row['session']:02d}"
        ))
        
        if map_path.exists():
            nii = nib.load(map_path)
            maps_list.append(nii.get_fdata().flatten())
            valid_scans.append(idx)
        else:
            print(f"  Warning: Missing {map_path}")
    
    maps_array = np.array(maps_list)
    metadata_valid = metadata.iloc[valid_scans].reset_index(drop=True)
    
    print(f"  Loaded {maps_array.shape[0]} scans × {maps_array.shape[1]} voxels")
    
    # Load brain mask
    print("[2/5] Loading brain mask...")
    mask = nib.load(args.brain_mask)
    n_voxels = np.sum(mask.get_fdata() > 0)
    
    # Fit LME (parallel)
    print(f"[3/5] Fitting LME models (n_jobs={args.n_jobs})...")
    formula = "value ~ session * group + age_std + sex_code + (1|subject)"
    
    results = Parallel(n_jobs=args.n_jobs, verbose=10)(
        delayed(fit_voxel_lme)(v, maps_array, metadata_valid, formula)
        for v in range(maps_array.shape[1])
    )
    
    t_stats, p_vals = zip(*results)
    t_stats = np.array(t_stats)
    p_vals = np.array(p_vals)
    
    print(f"  Mean |t| = {np.nanmean(np.abs(t_stats)):.3f}")
    print(f"  Min p-value = {np.nanmin(p_vals):.2e}")
    
    # Save t-stat map
    print("[4/5] Saving statistical maps...")
    tstat_img = unmask(t_stats, mask)
    nib.save(tstat_img, outdir / 'tstat_map.nii.gz')
    
    pval_img = unmask(p_vals, mask)
    nib.save(pval_img, outdir / 'pval_map.nii.gz')
    
    # Run FSL cluster (GRF correction)
    print("[5/5] Running FSL cluster-based thresholding...")
    cmd = f"""
    fslmaths {outdir}/tstat_map.nii.gz -thr 2.3 {outdir}/tstat_thresh.nii.gz
    fsl-cluster -i {outdir}/tstat_thresh.nii.gz \\
        -t 2.3 -p 0.05 \\
        -m {args.brain_mask} \\
        --minextent 10 --mm \\
        -o {outdir}/cluster_index.nii.gz \\
        | tee {outdir}/clusters.txt
    """
    subprocess.run(cmd, shell=True)
    
    print(f"\nResults saved to: {outdir}")
    print(f"  - tstat_map.nii.gz")
    print(f"  - clusters.txt")
    print(f"  - cluster_index.nii.gz")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Group-level LME analysis on connectivity maps')
    parser.add_argument('--input-maps', required=True, 
                        help='Path template with {subject}, {session} placeholders')
    parser.add_argument('--metadata', required=True, help='Path to metadata CSV')
    parser.add_argument('--output-dir', required=True, help='Output directory')
    parser.add_argument('--brain-mask', default='${FSLDIR}/data/standard/MNI152_T1_2mm_brain_mask.nii.gz')
    parser.add_argument('--n-jobs', type=int, default=8)
    
    main(parser.parse_args())
```

**Usage:**
```bash
python script/group_level_analysis_complete.py \
    --input-maps 'results/seed_based/dlpfc_l/{subject}_{session}_zmap.nii.gz' \
    --metadata results/metadata.csv \
    --output-dir results/group_stats/dlpfc_l_intervention_vs_control \
    --n-jobs 8
```

### Apply GRF Correction via FSL

**Script:** `script/fsl/apply_grf_correction.sh`

```bash
#!/bin/bash
set -e

usage() {
    echo "Usage: $0 <tstat_map> <output_dir> [voxel_threshold] [cluster_p] [min_extent]"
    echo "  tstat_map: Input t-statistic map (NIfTI)"
    echo "  output_dir: Output directory"
    echo "  voxel_threshold: Voxel-level threshold (default: 2.3, ~p<0.05 for z-stats)"
    echo "  cluster_p: Cluster-level FWE p-value (default: 0.05)"
    echo "  min_extent: Minimum cluster size in voxels (default: 10)"
    exit 1
}

[ $# -lt 2 ] && usage

tstat_map=$1
outdir=$2
voxt=${3:-2.3}
fwep=${4:-0.05}
k=${5:-10}

mask=${FSLDIR}/data/standard/MNI152_T1_2mm_brain_mask.nii.gz
mni=${FSLDIR}/data/standard/MNI152_T1_2mm.nii.gz

mkdir -p $outdir

echo ">>> Input: $tstat_map"
echo ">>> Voxel threshold: $voxt"
echo ">>> Cluster p (FWE): $fwep"
echo ">>> Min extent: $k voxels"

# Estimate smoothness
echo "Estimating smoothness..."
smoothest -z $tstat_map -m $mask > $outdir/smoothness.txt
dlh=$(grep DLH $outdir/smoothness.txt | awk '{print $NF}')
vol=$(grep VOLUME $outdir/smoothness.txt | awk '{print $NF}')

echo "  DLH = $dlh"
echo "  Volume = $vol"

# Threshold
echo "Thresholding..."
fslmaths $tstat_map -thr $voxt $outdir/tstat_thresh

# Cluster
echo "Running fsl-cluster..."
fsl-cluster -i $outdir/tstat_thresh \
    -t $voxt -p $fwep -d $dlh --volume=$vol \
    -m $mask \
    --minextent $k --mm \
    -o $outdir/cluster_index \
    | tee $outdir/clusters.txt

echo "Done. Results:"
echo "  Cluster index: $outdir/cluster_index.nii.gz"
echo "  Cluster summary: $outdir/clusters.txt"
```

### Query Atlases and Generate Summary Table

**Python:** `script/atlas_annotation.py`

```python
#!/usr/bin/env python3
"""
Query FSL atlases (atlasq) for cluster labels and generate annotated CSV.
"""

import subprocess
import pandas as pd
import numpy as np
from pathlib import Path

def parse_atlasq_output(filepath):
    """Parse atlasq query result."""
    regions = []
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('-') or line.startswith('|'):
                    continue
                parts = line.split('|')
                if len(parts) >= 3:
                    region = parts[1].strip()
                    pct_str = parts[2].strip().rstrip('%')
                    try:
                        pct = float(pct_str)
                        regions.append((region, pct))
                    except ValueError:
                        pass
    except FileNotFoundError:
        pass
    return sorted(regions, key=lambda x: x[1], reverse=True)

def main(cluster_dir, cluster_index_img, n_clusters=None):
    """
    Annotate clusters with atlas labels.
    """
    outdir = Path(cluster_dir)
    outdir.mkdir(parents=True, exist_ok=True)
    
    # Read cluster summary
    clusters_txt = Path(cluster_dir) / 'clusters.txt'
    cluster_data = pd.read_csv(clusters_txt, sep='\s+', skiprows=1)
    
    if n_clusters is None:
        n_clusters = len(cluster_data)
    
    # Process each cluster
    results = []
    for cluster_id in range(1, n_clusters + 1):
        # Extract binary mask
        mask_file = outdir / f'cluster_{cluster_id}.nii.gz'
        cmd = f'fslmaths {cluster_index_img} -thr {cluster_id} -uthr {cluster_id} -bin {mask_file}'
        subprocess.run(cmd, shell=True, capture_output=True)
        
        # Query atlases
        aal_regions = []
        hoc_regions = []
        hos_regions = []
        cbn_regions = []
        
        for atlas, out_list in [
            ('aal3v1', aal_regions),
            ('harvardoxford-cortical', hoc_regions),
            ('harvardoxford-subcortical', hos_regions),
            ('cerebellum_mnifnirt', cbn_regions)
        ]:
            output_file = outdir / f'cluster_{cluster_id}_{atlas}.txt'
            cmd = f'atlasq query {atlas} -l -m {mask_file}'
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            with open(output_file, 'w') as f:
                f.write(result.stdout)
            
            regions = parse_atlasq_output(output_file)
            if regions:
                out_list.append(regions[0][0])
        
        # Extract cluster metrics from cluster_data
        cluster_row = cluster_data.iloc[cluster_id - 1]
        
        results.append({
            'Cluster_ID': cluster_id,
            'Voxels': cluster_row['Voxels'],
            'Peak_t': cluster_row['Max'],
            'Peak_p': cluster_row['p-value'],
            'X_mm': cluster_row['x'],
            'Y_mm': cluster_row['y'],
            'Z_mm': cluster_row['z'],
            'AAL_Region': aal_regions[0] if aal_regions else 'Unknown',
            'HO_Cortical': hoc_regions[0] if hoc_regions else 'Unknown',
            'HO_Subcortical': hos_regions[0] if hos_regions else 'Unknown',
            'Cerebellum': cbn_regions[0] if cbn_regions else 'Unknown',
        })
    
    # Save annotated table
    df_clusters = pd.DataFrame(results)
    output_csv = outdir / 'clusters_annotated.csv'
    df_clusters.to_csv(output_csv, index=False)
    print(f"Saved: {output_csv}")
    print(df_clusters)

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--cluster-dir', required=True)
    parser.add_argument('--cluster-index', required=True)
    parser.add_argument('--n-clusters', type=int)
    args = parser.parse_args()
    main(args.cluster_dir, args.cluster_index, args.n_clusters)
```

---

## 12. Error Handling & Validation

### Singularity of Design Matrix

**Problem:** Rank-deficient design matrix (e.g., perfect collinearity between predictors)

**Detection:**
```python
import numpy as np
from statsmodels.formula.api import mixedlm

try:
    model = mixedlm(formula, data=df, groups=df['subject'])
    result = model.fit(reml=True, method='nm', disp=False)
    
    # Check rank
    X = model.exog
    rank = np.linalg.matrix_rank(X)
    expected_rank = X.shape[1]
    
    if rank < expected_rank:
        print(f"Warning: Rank deficiency. Rank={rank}, Expected={expected_rank}")
except Exception as e:
    print(f"Model fitting failed: {e}")
```

**Solutions:**
- Remove redundant predictors (e.g., don't include both `session` and `session_numeric`)
- Drop one level from categorical variables (reference coding handles this automatically)
- Check for perfect separation (e.g., all subjects in intervention group are male)

### Rank Deficiency Checks

```python
def check_design_matrix(df, formula):
    """Validate design matrix rank."""
    from statsmodels.formula.api import mixedlm
    import numpy as np
    
    model = mixedlm(formula, data=df, groups=df['subject'])
    X = model.exog
    rank = np.linalg.matrix_rank(X)
    
    if rank < X.shape[1]:
        print(f"ERROR: Rank deficiency detected!")
        print(f"  Rank = {rank}, Columns = {X.shape[1]}")
        print(f"  Model matrix condition number: {np.linalg.cond(X):.2e}")
        return False
    return True
```

### Convergence Diagnostics

**Check if optimizer converged:**
```python
result = model.fit(reml=True, method='nm', disp=False)

# Check convergence flag
if not result.converged:
    print("Warning: Optimizer did not converge!")
    print(f"  Message: {result.message}")
    print(f"  LLF: {result.llf}")
    
    # Try alternative optimizer
    result = model.fit(reml=True, method='powell', disp=False)
```

### FSL Command Failures

**Graceful error handling:**
```bash
#!/bin/bash

set -e  # Exit on error

trap_handler() {
    echo "ERROR: Pipeline failed at line $1"
    exit 1
}

trap 'trap_handler $LINENO' ERR

# Check if FSL is available
if ! command -v fsl-cluster &> /dev/null; then
    echo "ERROR: FSL not found. Check FSLDIR and PATH."
    exit 1
fi

# Validate input
if [ ! -f "$tstat_map" ]; then
    echo "ERROR: Input map not found: $tstat_map"
    exit 1
fi

# Run cluster
if ! fsl-cluster -i "$tstat_map" ... ; then
    echo "ERROR: fsl-cluster failed"
    exit 1
fi

echo "Success!"
```

**Python equivalent:**
```python
import subprocess
import sys

def run_fsl_command(cmd, description):
    """Run FSL command with error checking."""
    print(f"Running: {description}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"ERROR: {description} failed")
        print(f"  Command: {cmd}")
        print(f"  Stderr: {result.stderr}")
        sys.exit(1)
    
    return result.stdout

# Usage
stdout = run_fsl_command(
    f'fsl-cluster -i {tstat_map} ...',
    "FSL cluster thresholding"
)
```

---

## 13. Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| **No clusters found** | Threshold too high; effect too small | Lower `voxt` (e.g., 1.96 for z<0.05) or use FDR |
| **LME fitting fails** | Rank-deficient design matrix | Drop redundant predictors; check for perfect separation |
| **"FSLDIR not set"** | FSL environment not configured | `export FSLDIR=/usr/local/fsl` (or appropriate path) |
| **Memory error** | Too many voxels × scans | Use sparse matrices; fit voxels in batches (not all at once) |
| **atlasq returns "NA"** | Cluster outside atlas template | Use multiple atlases; check image alignment to MNI |
| **Cluster index has gaps** | Some cluster IDs missing | Normal (clusters renumbered after thresholding); use `-o cluster_index.nii.gz` to preserve |

---

## Summary

**Workflow:**
1. **Prepare data**: Long-format DataFrame (subject, session, group, value, covariates)
2. **Fit LME model**: Voxel-wise or region-wise using statsmodels
3. **Extract statistics**: t-stats, p-values, confidence intervals
4. **Save map**: Export t-statistic map (NIfTI)
5. **Apply correction**: GRF (via FSL), TFCE (via FSL or permutation), or FDR
6. **Annotate clusters**: Run atlasq queries to label regions
7. **Generate report**: CSV summary + HTML figures

**Key commands:**
```bash
# Parallel LME
python script/group_level_analysis_complete.py --input-maps ... --metadata ... --output-dir ...

# FSL cluster
bash script/fsl/apply_grf_correction.sh results/group_stats/tstat_map.nii.gz results/group_stats/clusters

# Annotate
python script/atlas_annotation.py --cluster-dir results/group_stats/clusters --cluster-index ...
```

**Output:**
- `tstat_map.nii.gz`: Statistical map (visualize in FSLView)
- `clusters.txt`: Cluster summary table
- `cluster_index.nii.gz`: Cluster labels
- `clusters_annotated.csv`: Annotated with anatomy
- `report.html`: Visual summary with figures

