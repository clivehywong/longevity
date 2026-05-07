# Quick Start

Use this file as the shortest path into the new documentation tree.

## Choose your entrypoint

- **Users**: start with [`docs/user/README.md`](docs/user/README.md)
- **Developers**: start with [`docs/developer/README.md`](docs/developer/README.md)
- **Legacy and historical notes**: use [`docs/archive/`](docs/archive/)

## Common workflows

### 1. Check raw BIDS data

```bash
python script/validate_bids_names.py bids/
python script/qa_check_images.py --bids-dir bids --output qa_images_full
```

Then read:

- [`docs/user/workflows/bids-validation-and-qc.md`](docs/user/workflows/bids-validation-and-qc.md)
- [`docs/user/troubleshooting/common-failures.md`](docs/user/troubleshooting/common-failures.md)

### 2. Run fMRIPrep batches on HPC

```bash
bash script/batch_fmriprep.sh
bash script/batch_fmriprep.sh status
```

Then read:

- [`docs/user/workflows/fmriprep-hpc-workflow.md`](docs/user/workflows/fmriprep-hpc-workflow.md)
- [`docs/user/troubleshooting/hpc-and-path-issues.md`](docs/user/troubleshooting/hpc-and-path-issues.md)

### 3. Run connectivity analysis

The connectivity pipeline is now **XCP-D-driven**. After XCP-D completes, subject-level and group-level analysis scripts read XCP-D outputs directly.

```bash
# Subject-level seed connectivity (XCP-D-driven)
python script/compute_seed_connectivity_xcpd.py \
    --bids-root /home/clivewong/proj/longevity \
    --pipeline fc --atlas 4S256Parcels \
    --measures pearson spearman \
    --analysis seed --seed-id dlpfc_L \
    --subjects sub-033 sub-034

# Subject-level network (parcel × parcel) connectivity
python script/compute_network_connectivity_xcpd.py \
    --bids-root /home/clivewong/proj/longevity \
    --pipeline fc --atlas 4S256Parcels \
    --measures pearson partial_correlation

# Group voxel stats (ALFF / ReHo / seed-to-voxel)
python script/group_voxel_stats_xcpd.py \
    --bids-root /home/clivewong/proj/longevity --pipeline fc

# Group matrix stats (parcel × parcel)
python script/group_matrix_stats.py \
    --bids-root /home/clivewong/proj/longevity --pipeline fc
```

> **Important:** `--bids-root` must be the **project root** (e.g., `/home/clivewong/proj/longevity`), not the `bids/` subdirectory, because XCP-D derivatives live at `<project_root>/derivatives/preprocessing/xcpd/`.

Then read:

- [`docs/user/workflows/connectivity-analysis.md`](docs/user/workflows/connectivity-analysis.md)
- [`docs/user/reference/parameter-considerations.md`](docs/user/reference/parameter-considerations.md)

### 4. Launch the NeuConn app

```bash
cd neuconn_app
pip install -r requirements.txt
python test_cli.py
streamlit run app.py
```

Then read:

- [`docs/user/workflows/neuconn-app.md`](docs/user/workflows/neuconn-app.md)
- [`docs/developer/architecture/neuconn-app-architecture.md`](docs/developer/architecture/neuconn-app-architecture.md)

### 5. Submit connectivity jobs from the UI

After XCP-D is complete, use the **fMRI Analysis → Subject Level** and **Group Level** menus in the NeuConn app to submit connectivity jobs directly without editing scripts.

**Pipeline selector** (fc / fc_gsr / ec) appears on every submit page. **Atlases** are the five XCP-D-native parcellations: 4S256Parcels, 4S456Parcels, Glasser, Gordon, Tian. **Measures** now include 8 options (pearson, spearman, partial_correlation, plv, wpli, coherence, amplitude_envelope_correlation, mutual_information).

| App page | Analysis |
|---|---|
| Subject Level → 📊 Local Measures Coverage | Discovery dashboard — shows ALFF/ReHo/fALFF coverage per subject/session (no submission) |
| Subject Level → 📤 Submit Seed Connectivity | Seed-based maps — pipeline + atlas + seed multi-select; 8 measures; produces seed-to-parcel TSV + seed-to-voxel NIfTI |
| Subject Level → 📤 Submit Network Connectivity | Parcel × parcel relmat — pipeline + atlas + 8 measures |
| Group Level → 📤 Submit Group Stats | Voxel branch (GRF/TFCE/FDR on ALFF/ReHo/seed-to-voxel) or Matrix branch (paired_t_fdr / NBS / TF-NBS) |

All pages use `ConnectivityWorkflowManager` to track submissions; state is persisted at `<bids_parent>/.neuconn/connectivity_workflow_state.json`.

Then read:

- [`docs/user/workflows/connectivity-analysis.md`](docs/user/workflows/connectivity-analysis.md)
- [`neuconn_app/pages_connectivity_submit/README.md`](neuconn_app/pages_connectivity_submit/README.md)

### 6. Run XCP-D post-processing pipeline

Requires the XCP-D Singularity image and FreeSurfer license — see the prerequisites section in the app workflow doc.

```bash
# In the NeuConn app:
# fMRI Analysis > XCP-D Pipeline
# 1. FD Inspection tab  → generate summary, approve thresholds
# 2. XCP-D Runs tab     → start FC (and optionally FC+GSR / EC)
# 3. Post-XCP-D QC tab  → review QC reports, approve gate
# 4. fMRI Analysis > Subject Level → index local measures, export seed connectivity
```

Then read:

- [`docs/user/workflows/neuconn-app.md#xcpd-pipeline`](docs/user/workflows/neuconn-app.md)

## What changed

- The primary docs are now organized by **audience** and **task**.
- Time-bound notes and old run-status material are no longer the main entrypoints.
- Script-folder markdown files are treated as legacy sources, not the main way to navigate the repo.
