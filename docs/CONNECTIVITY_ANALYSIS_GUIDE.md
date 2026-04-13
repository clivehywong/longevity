# Subject-Level Connectivity Analysis Implementation Guide

## Overview

This guide describes the complete implementation of subject-level connectivity analysis for the longitudinal walking intervention study. The analysis pipeline includes:

1. **Local measures** (fALFF, ReHo)
2. **Extended seed-based connectivity** (12 seeds including DLPFC, insula, dACC, hippocampus subdivisions)
3. **Network-based connectivity** (within/between network analyses)
4. **Group-level statistical analysis** (voxelwise LME with cluster correction)
5. **Interactive HTML report** (collapsible navigation, brain visualizations, stats tables)

## Quick Start

### Test with Single Subject

```bash
# Test local measures computation
bash script/test_local_measures.sh

# This will process sub-033 ses-01 and create:
# - test_output/local_measures/sub-033_ses-01_fALFF.nii.gz
# - test_output/local_measures/sub-033_ses-01_ReHo.nii.gz
# - test_output/local_measures/local_measures_summary.csv
```

### Run Full Workflow (All Subjects)

```bash
# Full workflow
bash script/master_full_connectivity_workflow.sh

# Test mode (subset of subjects)
bash script/master_full_connectivity_workflow.sh --test
```

## Implementation Details

### 1. Extended Seed Definitions

**File**: `atlases/motor_cerebellar_seeds.json`

**New Seeds Added**:
- `DLPFC_Coarse`: All FrontoParietal frontal components (15 components)
- `DLPFC_Dorsal`: Dorsal DLPFC/BA9 - superior frontal gyrus (3 components)
- `DLPFC_Ventral`: Ventral DLPFC/BA46 - middle frontal gyrus (4 components)
- `Anterior_Insula`: Key salience network hub (4 components)
- `dACC`: Dorsal anterior cingulate cortex (2 components)
- `Insula_dACC_Combined`: Core salience network (6 components)
- `Hippocampus_Anterior`: Anterior hippocampus (4 components)
- `Hippocampus_Posterior`: Posterior hippocampus (1 component)

**Note**: Existing `Hippocampus` seed (4 components) is retained for coarse analysis.

**Verification**:
```bash
# View seed definitions
cat atlases/motor_cerebellar_seeds.json | jq '.seeds | keys'
```

### 2. Local Measures Script

**Script**: `script/compute_local_measures.py`

**Features**:
- **fALFF**: Fractional amplitude of low-frequency fluctuations (0.01-0.1 Hz)
- **ReHo**: Regional homogeneity via Kendall's W (26-neighbor default)
- Confound regression (6 motion + CSF + WM)
- Detrending and bandpass filtering
- Summary statistics per subject

**Usage**:
```bash
python script/compute_local_measures.py \
    --fmriprep fmriprep/ \
    --output results/local_measures \
    --measures fALFF ReHo \
    --subjects sub-033 sub-034 \
    --sessions ses-01 ses-02 \
    --tr 0.8 \
    --low-freq 0.01 \
    --high-freq 0.1
```

**Output**:
```
results/local_measures/
├── sub-033_ses-01_fALFF.nii.gz
├── sub-033_ses-01_ReHo.nii.gz
├── sub-033_ses-02_fALFF.nii.gz
├── sub-033_ses-02_ReHo.nii.gz
├── ...
└── local_measures_summary.csv
```

**Expected Values**:
- fALFF: typically 0.4-0.8 in cortex (higher in DMN, lower in motor)
- ReHo: typically 0.2-0.4 (Kendall's W ranges 0-1)

### 3. Seed-Based Connectivity Script

**Script**: `script/seed_based_connectivity.py` (existing, extended)

**No code changes needed** - simply run with new seed names from updated JSON.

**Usage**:
```bash
python script/seed_based_connectivity.py \
    --fmriprep fmriprep/ \
    --seeds atlases/motor_cerebellar_seeds.json \
    --metadata results/metadata.csv \
    --output results/seed_based \
    --seed-names DLPFC_Coarse DLPFC_Dorsal DLPFC_Ventral \
                  Anterior_Insula dACC Insula_dACC_Combined \
                  Hippocampus_Anterior Hippocampus_Posterior \
    --smoothing 6.0 \
    --high-pass 0.01 \
    --low-pass 0.1
```

**Output**:
```
results/seed_based/
├── dlpfc_coarse/
│   ├── sub-033_ses-01_zmap.nii.gz
│   ├── sub-033_ses-02_zmap.nii.gz
│   └── individual_maps.csv
├── anterior_insula/
├── dacc/
└── ...
```

### 4. Network-Based Connectivity Analysis

**Script**: `script/python_connectivity_analysis.py` (modified)

**New Features**:
- `--within-network NETWORK`: Test all connections within a network
- `--between-networks NET1 NET2`: Test all connections between two networks
- `--all-within`: Test within-network for all networks
- `--all-between`: Test all pairwise between-network connectivity

**Usage Examples**:

```bash
# Within Salience Network
python script/python_connectivity_analysis.py \
    --timeseries results/timeseries_difumo256.h5 \
    --metadata results/metadata.csv \
    --networks atlases/difumo256_network_definitions.json \
    --output results/network_connectivity/within_salience \
    --within-network SalienceVentralAttention \
    --alpha 0.05

# Between FrontoParietal and Cerebellar_Cognitive
python script/python_connectivity_analysis.py \
    --timeseries results/timeseries_difumo256.h5 \
    --metadata results/metadata.csv \
    --networks atlases/difumo256_network_definitions.json \
    --output results/network_connectivity/between_fpcn_cerebcog \
    --between-networks FrontoParietal Cerebellar_Cognitive \
    --alpha 0.05
```

**Output**:
```
results/network_connectivity/within_salience/
├── connectivity_anova_results.csv
├── significant_interactions_fdr.csv
└── effect_sizes.csv
```

### 5. Group-Level Statistical Analysis

**Script**: `script/group_level_analysis.py`

**Features**:
- Voxelwise linear mixed-effects model: `value ~ Group * Time + Age + Sex + MeanFD + (1|Subject)`
- Permutation testing with TFCE for cluster correction (FWE p < 0.05)
- Cluster table extraction with anatomical labels (Harvard-Oxford atlas)
- Brain visualizations (orthogonal and mosaic views)

**Usage**:
```bash
python script/group_level_analysis.py \
    --input-maps results/local_measures/*_fALFF.nii.gz \
    --metadata results/metadata.csv \
    --output results/group_analysis/fALFF \
    --cluster-threshold 0.05 \
    --n-permutations 5000 \
    --min-cluster-size 10
```

**Output**:
```
results/group_analysis/fALFF/
├── interaction_tstat_map.nii.gz         # Unthresholded T-statistics
├── interaction_pval_map.nii.gz          # P-values
├── interaction_fwe_p05.nii.gz           # FWE-corrected thresholded map
├── interaction_neglog_pvals.nii.gz      # Negative log p-values
├── clusters_interaction.csv             # Cluster table
├── tstat_map_ortho.png                  # Visualization (uncorrected)
├── thresholded_map_ortho.png            # Visualization (FWE corrected)
└── thresholded_map_mosaic.png           # Mosaic view
```

**Cluster Table Columns**:
- `cluster_id`: Cluster identifier
- `size_voxels`: Cluster size in voxels
- `size_mm3`: Cluster size in mm³
- `peak_t`: Peak T-statistic
- `peak_x`, `peak_y`, `peak_z`: Peak MNI coordinates
- `anatomical_region`: Harvard-Oxford atlas label

### 6. Interactive HTML Report Generator

**Script**: `script/generate_html_report.py`

**Features**:
- Self-contained HTML file (embedded images, Plotly JSON)
- Collapsible sidebar with folder structure
- **Significance highlighting**: Green background for analyses with FDR q < 0.05
- Statistical summary tables
- Brain slice visualizations (base64-encoded PNG)
- Interactive effect size plots (Plotly)
- Cluster tables for whole-brain analyses

**Usage**:
```bash
python script/generate_html_report.py \
    --results-dir results/ \
    --output results/connectivity_report.html
```

**Report Structure**:
```
📊 Connectivity Analysis Report
├── 📁 Local Measures
│   ├── fALFF
│   └── ReHo
├── 📁 Seed-Based Connectivity
│   ├── Motor Cortex
│   ├── DLPFC Coarse
│   ├── DLPFC Dorsal
│   ├── DLPFC Ventral
│   ├── Anterior Insula
│   ├── dACC
│   ├── Insula dACC Combined
│   ├── Hippocampus Anterior
│   └── Hippocampus Posterior
└── 📁 Network Connectivity
    ├── 📁 Within Network
    │   ├── Salience
    │   ├── DMN
    │   └── FrontoParietal
    └── 📁 Between Network
        ├── Salience ↔ DMN
        ├── FrontoParietal ↔ Cerebellar Cognitive
        └── Somatomotor ↔ Cerebellar Motor
```

**Viewing Report**:
```bash
firefox results/connectivity_report.html
# or
google-chrome results/connectivity_report.html
```

## Master Workflow

**Script**: `script/master_full_connectivity_workflow.sh`

**Features**:
- Orchestrates all analysis steps in sequence
- Test mode (`--test`) for subset of subjects
- Automatic dependency checking (creates results directories)
- Progress reporting for each step

**Steps**:
1. Prepare metadata (group, age, sex, motion)
2. Compute local measures (fALFF, ReHo)
3. Extract timeseries and compute seed-based connectivity
4. Network-based connectivity (within/between)
5. Group-level statistical analysis
6. Generate interactive HTML report

**Usage**:
```bash
# Full workflow (all subjects)
bash script/master_full_connectivity_workflow.sh

# Test mode (sub-033, sub-034 only)
bash script/master_full_connectivity_workflow.sh --test
```

**Processing Time Estimates** (approximate):
- Local measures: ~5 min per subject-session (fALFF + ReHo)
- Seed-based connectivity: ~3 min per seed per subject-session
- Network connectivity: ~10-30 min per network pair (depends on # connections)
- Group-level analysis: ~15-60 min per measure (depends on permutations)
- HTML report: ~1-2 min

**For 8 subjects × 2 sessions = 16 observations**:
- Total time: ~4-8 hours (depending on permutation count)

## Data Requirements

### fMRIPrep Outputs

**Required files per subject-session**:
```
fmriprep/
└── sub-XXX/
    └── ses-XX/
        └── func/
            ├── *_space-MNI152NLin2009cAsym_res-2_desc-preproc_bold.nii.gz
            ├── *_space-MNI152NLin2009cAsym_res-2_desc-brain_mask.nii.gz
            └── *_desc-confounds_timeseries.tsv
```

### Metadata

**Required**: `group.csv` with columns:
- `subject_id`: e.g., "sub-033"
- `group`: "Control" or "Walking"

**Optional**: Demographics file with:
- `subject_id`
- `age`: Numeric
- `sex`: "M" or "F"

If demographics not provided, age and sex will be set to default values in metadata.

### Current Data Status

**Available**: 8 subjects with complete fMRIPrep preprocessing
- sub-033, sub-034, sub-035, sub-036 (sessions 01 & 02)
- sub-037, sub-038, sub-039, sub-040 (sessions 01 & 02)

**Total**: 16 subject-session pairs

## Testing Individual Components

### 1. Test Local Measures

```bash
bash script/test_local_measures.sh
```

**Checks**:
- fALFF values reasonable (0.4-0.8)
- ReHo values reasonable (0.2-0.4)
- No NaN in output maps
- Files created successfully

**Visualization**:
```bash
fsleyes test_output/local_measures/sub-033_ses-01_fALFF.nii.gz
```

### 2. Test Seed-Based Connectivity

```bash
python script/seed_based_connectivity.py \
    --fmriprep fmriprep/ \
    --seeds atlases/motor_cerebellar_seeds.json \
    --metadata results/metadata.csv \
    --output test_output/seed_based \
    --seed-names DLPFC_Coarse
```

**Checks**:
- Z-maps show expected connectivity patterns
- Fisher Z values typically -2 to +2 (stronger connections > 2)
- Mean connectivity visualization saved

### 3. Test Network Connectivity

```bash
# First ensure timeseries extracted
python script/extract_timeseries.py \
    --fmriprep fmriprep/ \
    --atlas difumo256 \
    --output results/timeseries_difumo256.h5

# Test within-network
python script/python_connectivity_analysis.py \
    --timeseries results/timeseries_difumo256.h5 \
    --metadata results/metadata.csv \
    --networks atlases/difumo256_network_definitions.json \
    --output test_output/within_salience \
    --within-network SalienceVentralAttention \
    --alpha 0.05
```

**Checks**:
- Connectivity matrices generated
- FDR correction applied
- Significant results (if any) reported

### 4. Test Group-Level Analysis

```bash
# Need at least 10 observations for LME
python script/group_level_analysis.py \
    --input-maps results/local_measures/*_fALFF.nii.gz \
    --metadata results/metadata.csv \
    --output test_output/group_fALFF \
    --cluster-threshold 0.05 \
    --n-permutations 1000 \
    --min-cluster-size 10
```

**Checks**:
- T-statistic maps generated
- Permutation testing completes
- Cluster table extracted (if significant clusters)

### 5. Test HTML Report

```bash
python script/generate_html_report.py \
    --results-dir results/ \
    --output test_output/test_report.html
```

**Checks**:
- HTML file created
- Sidebar navigation functional
- Brain images render
- Plotly plots interactive

## Troubleshooting

### Common Issues

**1. "No BOLD files found"**
- Check `--space` and `--res` parameters match fMRIPrep outputs
- Verify fMRIPrep directory path
- Run: `ls fmriprep/sub-*/ses-*/func/*_bold.nii.gz`

**2. "No metadata for subject X"**
- Ensure `metadata.csv` exists
- Check subject IDs match exactly (case-sensitive)
- Regenerate: `python script/prepare_metadata.py --fmriprep fmriprep/ --group group.csv --output results/metadata.csv`

**3. Permutation testing fails**
- Reduce `--n-permutations` (try 1000 instead of 5000)
- Check sufficient memory available
- Use fewer subjects for testing

**4. ReHo computation very slow**
- Expected for whole-brain voxelwise Kendall's W
- Progress printed every 50,000 voxels
- For 2mm brain: ~50,000-100,000 voxels in mask

**5. HTML report missing analyses**
- Check results directory structure
- Ensure CSV files named correctly:
  - `connectivity_anova_results.csv`
  - `significant_interactions_fdr.csv`
  - `clusters_interaction.csv`

## Output Structure

```
results/
├── metadata.csv                         # Subject metadata
├── timeseries_difumo256.h5              # Extracted timeseries
├── local_measures/
│   ├── sub-XXX_ses-XX_fALFF.nii.gz
│   ├── sub-XXX_ses-XX_ReHo.nii.gz
│   └── local_measures_summary.csv
├── seed_based/
│   ├── dlpfc_coarse/
│   │   ├── sub-XXX_ses-XX_zmap.nii.gz
│   │   └── individual_maps.csv
│   └── ...
├── network_connectivity/
│   ├── within_salience/
│   │   ├── connectivity_anova_results.csv
│   │   ├── significant_interactions_fdr.csv
│   │   └── effect_sizes.csv
│   └── ...
├── group_analysis/
│   ├── fALFF/
│   │   ├── interaction_tstat_map.nii.gz
│   │   ├── interaction_fwe_p05.nii.gz
│   │   ├── clusters_interaction.csv
│   │   └── *.png
│   ├── ReHo/
│   ├── seed_dlpfc_coarse/
│   └── ...
└── connectivity_report.html             # Interactive report
```

## Statistical Model

### Voxelwise LME
```
value ~ Group * Time + Age + Sex + MeanFD + (1|Subject)
```

**Variables**:
- `Group`: Control (0) vs Walking (1)
- `Time`: Pre/ses-01 (0) vs Post/ses-02 (1)
- `Age`: Centered and standardized
- `Sex`: M (0) vs F (1)
- `MeanFD`: Framewise displacement (centered and standardized)
- `(1|Subject)`: Random intercept per subject

**Test of Interest**: `Group:Time` interaction (differential change between groups)

### Multiple Comparisons Correction

**For ROI-to-ROI**: FDR correction (Benjamini-Hochberg)
**For voxelwise**: Permutation testing with TFCE, FWE p < 0.05

## References

**Atlases**:
- DiFuMo 256: Dadi et al. (2020). *NeuroImage*
- Schaefer 400: Schaefer et al. (2018). *Cerebral Cortex*

**Methods**:
- fALFF: Zou et al. (2008). *J Neurosci Methods*
- ReHo: Zang et al. (2004). *NeuroImage*
- TFCE: Smith & Nichols (2009). *NeuroImage*

## Contact

For questions or issues with the analysis pipeline, check:
1. This guide (`CONNECTIVITY_ANALYSIS_GUIDE.md`)
2. Project instructions (`CLAUDE.md`)
3. Dataset status (`BIDS_DATASET_STATUS.md`)
