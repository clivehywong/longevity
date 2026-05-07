# Connectivity Pipeline — Developer Reference

The connectivity pipeline is **XCP-D-driven**. All scripts read XCP-D derivative outputs directly; no separate timeseries extraction step is needed.

## Legacy / archived components

The self-built DiFuMo256 / Schaefer400 pipeline is archived at `script/archive/old_pipeline_pre_xcpd/`. See that directory's `README.md` for a file index and migration notes.

Archived scripts (no longer in `script/`):

| Script | Was |
|---|---|
| `compute_local_measures.py` | Computed fALFF/ALFF/ReHo from fMRIPrep outputs |
| `compute_network_connectivity.py` | Extracted DiFuMo256 timeseries and computed Pearson relmat |
| `create_difumo_network_definitions.py` | Generated DiFuMo network label files |
| `hpc_*.sh` (14 scripts) | Legacy HPC array-job wrappers |

## New scripts

| Script | Purpose |
|---|---|
| `script/connectivity_measures.py` | 8-measure library; imported by subject-level scripts |
| `script/compute_seed_connectivity_xcpd.py` | Subject-level seed connectivity (seed-to-parcel + seed-to-voxel) |
| `script/compute_network_connectivity_xcpd.py` | Subject-level parcel × parcel relmat (8 measures) |
| `script/group_voxel_stats_xcpd.py` | Group voxel statistics (ALFF / ReHo / seed-to-voxel) |
| `script/group_matrix_stats.py` | Group matrix statistics (parcel × parcel) |

## Dependency graph

```
XcpdDiscovery / XcpdOutputs   (utils/xcpd_outputs.py)
         │
         ▼
    SeedCatalog               (utils/seed_catalog.py)
    — xcpd_atlas_parcel
    — custom_nifti_roi
    — sphere
         │
         ▼
ConnectivityWorkflowManager   (utils/connectivity_workflow.py)
    emits: --analysis seed|network --pipeline <p> --measures …
         │
    ┌────┴──────────────────────┐
    ▼                           ▼
Submit pages                connectivity_measures.py
pages_connectivity_submit/    └─ compute_seed_connectivity_xcpd.py
                              └─ compute_network_connectivity_xcpd.py
                              └─ group_voxel_stats_xcpd.py
                              └─ group_matrix_stats.py
```

## Connectivity measures (8)

Implemented in `script/connectivity_measures.py`. Fisher-z is applied automatically to correlation-type measures before group statistics; `mutual_information` is excluded.

| Key | Type | Technical notes |
|---|---|---|
| `pearson` | correlation | Standard Pearson r on parcel timeseries |
| `spearman` | correlation | Rank-order correlation; robust to outliers and non-normal distributions |
| `partial_correlation` | correlation | Regularised inverse covariance (precision matrix); controls for all other parcels |
| `plv` | phase | Phase Locking Value in the BOLD band; requires bandpass filtering first |
| `wpli` | phase | Weighted Phase Lag Index; de-biases PLV by down-weighting near-zero phase lags (volume-conduction rejection) |
| `coherence` | spectral | Welch power spectral coherence; captures both amplitude and phase coupling |
| `amplitude_envelope_correlation` | amplitude | AEC on Hilbert envelope of bandpassed signal; measures slow amplitude co-fluctuations |
| `mutual_information` | information | Non-parametric; captures non-linear dependencies; no Fisher-z applied |

## Seed sources (3)

| Source type | Identified by | Example |
|---|---|---|
| `xcpd_atlas_parcel` | parcel index in XCP-D atlas TSV | `4S256Parcels:LH_DefaultA_PFCm_1` |
| `custom_nifti_roi` | NIfTI ROI file + config entry | custom DLPFC mask |
| `sphere` | MNI coords + radius | `dlpfc_L` at [-44, 36, 20] r=6 mm |

## CLI flags

All subject-level scripts accept:

```
--bids-root   project root (NOT bids/ subdir)
--pipeline    fc | fc_gsr | ec
--atlas       4S256Parcels | 4S456Parcels | Glasser | Gordon | Tian
--measures    space-separated list of measure keys
--analysis    seed | network   (compute_seed_connectivity_xcpd only)
--subjects    optional subject filter
```

> **`--bids-root` constraint:** must be the project root (e.g. `/home/clivewong/proj/longevity`) because XCP-D outputs live at `<project_root>/derivatives/preprocessing/xcpd/`, not under `bids/`.

## Output tree

```
derivatives/connectivity/
  {fc,fc_gsr,ec}/
    sub-XX/ses-YY/
      seed/<seed_id>/
        *_atlas-<A>_measure-<M>_seed-to-parcel.tsv
        *_measure-<M>_seed-to-voxel_zmap.nii.gz
      network/atlas-<A>/
        *_measure-<M>_relmat.tsv
        *_measure-<M>_relmat-z.tsv   # Fisher-z for correlation measures
  group/
    voxel/...     # group_voxel_stats_xcpd.py outputs
    matrix/...    # group_matrix_stats.py outputs
```

## Group statistics methods

### Voxel branch (`group_voxel_stats_xcpd.py`)

Inputs: ALFF, ReHo, seed-to-voxel zmaps. Applies one of:

| Method | Notes |
|---|---|
| `grf` | Gaussian Random Field cluster-extent correction; fast |
| `tfce` | Threshold-Free Cluster Enhancement; permutation-based; ≥ 5000 permutations for publication |
| `fdr` | Benjamini-Hochberg FDR; set q threshold (default 0.05) |

### Matrix branch (`group_matrix_stats.py`)

Inputs: parcel × parcel relmat TSV files.

| Method | Notes |
|---|---|
| `paired_t_fdr` | Paired t-test per edge; FDR across edges |
| `nbs` | Network-Based Statistic; controls FWER at the component level |
| `tf_nbs` | Threshold-Free NBS; no cluster-forming threshold required |

## Validation

235 unit tests + 21 e2e tests, all passing. Pearson sanity check vs XCP-D's built-in relmat: max absolute difference 2 × 10⁻¹⁵.

See `CONNECTIVITY_UI_VALIDATION_V2.md` for full test results.
