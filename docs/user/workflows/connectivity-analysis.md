# Connectivity Analysis

> **Current pipeline:** XCP-D-driven (as of 2026-04-29). The self-built DiFuMo256/Schaefer400 pipeline is archived at `script/archive/old_pipeline_pre_xcpd/`. See [`docs/developer/architecture/connectivity-pipeline.md`](../../developer/architecture/connectivity-pipeline.md) for the full technical reference.

The connectivity pipeline reads XCP-D outputs directly. XCP-D produces ALFF, ReHo, parcellated timeseries, and Pearson correlation matrices; the new scripts build on those to compute additional measures and run group statistics.

## Supported XCP-D pipelines

| Pipeline | Strategy | Use |
|---|---|---|
| `fc` | acompcor, no GSR | Primary FC pipeline |
| `fc_gsr` | 36P with GSR | GSR comparison |
| `ec` | acompcor, no scrubbing | Effective connectivity |

## Supported atlases (5)

All are native to XCP-D outputs in `MNI152NLin6Asym` space:

| Atlas | Parcels |
|---|---|
| 4S256Parcels | 256 (Schaefer cortical + 56 subcortical) |
| 4S456Parcels | 456 |
| Glasser | 360 (HCP multi-modal) |
| Gordon | 333 |
| Tian | subcortical |

## Connectivity measures (8)

Fisher-z transform is applied automatically to correlation-type measures before group statistics.

| Measure | Notes |
|---|---|
| `pearson` | Standard Pearson r — fast, widely used |
| `spearman` | Rank-order correlation — robust to outliers |
| `partial_correlation` | Pairwise correlation controlling for all other parcels |
| `plv` | Phase Locking Value — phase synchrony; bandpass before use |
| `wpli` | Weighted Phase Lag Index — de-biased PLV; robust to volume conduction |
| `coherence` | Spectral coherence in the BOLD band |
| `amplitude_envelope_correlation` | AEC — slow amplitude coupling |
| `mutual_information` | Non-linear dependency; no Fisher-z applied |

## End-to-end workflow

### Prerequisites

- fMRIPrep outputs at `derivatives/func/preprocessing/fmriprep/`
- XCP-D outputs at `derivatives/preprocessing/xcpd/{fc,fc_gsr,ec}/`
- `bids/participants.tsv` with subject group assignments in tab-separated columns

### Step 1: Verify XCP-D coverage

Use the **Local Measures Coverage** dashboard in the app (fMRI Analysis → Subject Level → 📊 Local Measures Coverage). This is a read-only discovery view — it does not submit any jobs.

### Step 2: Run subject-level seed connectivity

```bash
python script/compute_seed_connectivity_xcpd.py \
    --bids-root /home/clivewong/proj/longevity \
    --pipeline fc \
    --atlas 4S256Parcels \
    --measures pearson spearman \
    --analysis seed \
    --seed-id dlpfc_L \
    --subjects sub-033 sub-034
```

Outputs per subject/session:
- `derivatives/connectivity/fc/sub-XX/ses-YY/seed/<seed_id>/*_atlas-X_measure-Y_seed-to-parcel.tsv`
- `derivatives/connectivity/fc/sub-XX/ses-YY/seed/<seed_id>/*_seed-to-voxel_zmap.nii.gz`

### Step 3: Run subject-level network connectivity

```bash
python script/compute_network_connectivity_xcpd.py \
    --bids-root /home/clivewong/proj/longevity \
    --pipeline fc \
    --atlas 4S256Parcels \
    --measures pearson partial_correlation
```

Outputs: `derivatives/connectivity/fc/sub-XX/ses-YY/network/atlas-X/*_measure-Y_relmat[-z].tsv`

### Step 4: Group voxel statistics

```bash
python script/group_voxel_stats_xcpd.py \
    --bids-root /home/clivewong/proj/longevity \
    --pipeline fc \
    --correction grf   # or tfce / fdr
```

Correction methods: `grf` (Gaussian Random Field cluster-extent), `tfce` (permutation, ≥5000 recommended), `fdr` (Benjamini-Hochberg).

### Step 5: Group matrix statistics

```bash
python script/group_matrix_stats.py \
    --bids-root /home/clivewong/proj/longevity \
    --pipeline fc \
    --method paired_t_fdr   # or nbs / tf_nbs
```

Methods: `paired_t_fdr`, `nbs` (Network-Based Statistic), `tf_nbs` (threshold-free NBS).

> **`--bids-root` must be the project root** (e.g. `/home/clivewong/proj/longevity`), not the `bids/` subdirectory — XCP-D derivatives live at `<project_root>/derivatives/preprocessing/xcpd/`.

## Submit from the app {#submit-from-the-app}

The NeuConn app exposes the connectivity stages as interactive pages under **fMRI Analysis**:

### Subject Level

| Page | What it does |
|---|---|
| 📊 Local Measures Coverage | Read-only dashboard — ALFF / ReHo / fALFF coverage per subject/session |
| 📤 Submit Seed Connectivity | Pipeline + atlas + seed multi-select; 8 measures; submits seed-to-parcel + seed-to-voxel |
| 📤 Submit Network Connectivity | Pipeline + atlas + 8 measures; submits parcel × parcel relmat |

### Group Level

| Page | What it does |
|---|---|
| 📤 Submit Group Stats | **Voxel** kind: GRF/TFCE/FDR on ALFF/ReHo/seed-to-voxel; **Matrix** kind: paired_t_fdr/NBS/TF-NBS |

See [`neuconn_app/pages_connectivity_submit/README.md`](../../neuconn_app/pages_connectivity_submit/README.md) for per-page option details.

## Deprecated: self-built DiFuMo/Schaefer pipeline

The previous pipeline (`compute_local_measures.py`, `compute_network_connectivity.py`, DiFuMo256/Schaefer400 atlases) is archived at `script/archive/old_pipeline_pre_xcpd/`. The master workflow script (`script/master_full_connectivity_workflow.sh`) targets the legacy pipeline and is no longer the primary entrypoint.

See [`script/archive/old_pipeline_pre_xcpd/README.md`](../../../script/archive/old_pipeline_pre_xcpd/README.md) for what was archived and what replaced it.
