# Connectivity Submit Pages

These pages expose the XCP-D-driven connectivity pipeline as interactive forms inside the **fMRI Analysis** section of the NeuConn app.

Submission state (job IDs, status, parameters) is persisted by `ConnectivityWorkflowManager` at `<bids_parent>/.neuconn/connectivity_workflow_state.json`.

**Common options on every submit page:**

| Option | Values | Notes |
|---|---|---|
| Pipeline | `fc` / `fc_gsr` / `ec` | Selects which XCP-D derivative tree to read from |
| Atlas | 4S256Parcels, 4S456Parcels, Glasser, Gordon, Tian | XCP-D native atlases in MNI152NLin6Asym space |

---

## 00 — Local Measures Coverage

**Menu path:** fMRI Analysis → Subject Level → 📊 Local Measures Coverage
**Session-state prefix:** `submit_local_`

Read-only discovery dashboard. Uses `XcpdDiscovery` to enumerate ALFF, fALFF, and ReHo files from XCP-D outputs and displays per-subject/session coverage. **No jobs are submitted.**

| Display | Notes |
|---|---|
| Coverage table | Pipeline × subject × session coverage for ALFF / fALFF / ReHo |
| Missing subjects | Listed for easy identification before running group stats |

---

## 02 — Submit Seed Connectivity

**Menu path:** fMRI Analysis → Subject Level → 📤 Submit Seed Connectivity
**Session-state prefix:** `submit_seed_`

Submits `script/compute_seed_connectivity_xcpd.py` per subject/session.

### Cascading Pipeline → Atlas → Seed multi-select

1. **Pipeline radio** — fc / fc_gsr / ec
2. **Atlas radio** — one of the 5 XCP-D atlases
3. **Seed list** — filtered to seeds valid for the selected atlas, grouped by source:
   - 🗺️ **xcpd_atlas_parcel** — individual parcels from the selected atlas
   - 🔧 **custom_nifti_roi** — NIfTI ROI files from config
   - ✨ **sphere** — MNI coordinate + radius seeds from connectivity config
4. Changing the atlas or pipeline resets seed selection.

| Option | Default | Notes |
|---|---|---|
| Pipeline | `fc` | |
| Atlas | `4S256Parcels` | |
| Seeds | — | one or more seed IDs |
| Measures | `pearson` | any subset of the 8 connectivity measures |
| Subjects / sessions | first 4 pairs | multi-select |

Outputs per subject/session:
- `derivatives/connectivity/<pipeline>/sub-XX/ses-YY/seed/<seed_id>/*_atlas-<A>_measure-<M>_seed-to-parcel.tsv`
- `derivatives/connectivity/<pipeline>/sub-XX/ses-YY/seed/<seed_id>/*_measure-<M>_seed-to-voxel_zmap.nii.gz`

---

## 03 — Submit Network Connectivity

**Menu path:** fMRI Analysis → Subject Level → 📤 Submit Network Connectivity
**Session-state prefix:** `submit_network_`

Submits `script/compute_network_connectivity_xcpd.py` — computes parcel × parcel relmat.

| Option | Default | Notes |
|---|---|---|
| Pipeline | `fc` | |
| Atlas | `4S256Parcels` | |
| Measures | `pearson` | any subset of the 8 connectivity measures |
| Subjects / sessions | first 4 pairs | multi-select |

Outputs: `derivatives/connectivity/<pipeline>/sub-XX/ses-YY/network/atlas-<A>/*_measure-<M>_relmat[-z].tsv`

---

## 04 — Submit Group Stats

**Menu path:** fMRI Analysis → Group Level → 📤 Submit Group Stats
**Session-state prefix:** `submit_group_`

Two branches selected via **Kind** toggle:

### Voxel kind

Submits `script/group_voxel_stats_xcpd.py` on ALFF / ReHo / seed-to-voxel zmaps.

| UI label | CLI method | Notes |
|---|---|---|
| GRF (cluster-based) | `grf` | Gaussian Random Field cluster-extent correction |
| TFCE (permutation) | `tfce` | Threshold-Free Cluster Enhancement; ≥ 5000 permutations recommended |
| FDR | `fdr` | Benjamini-Hochberg FDR; default q = 0.05 |

### Matrix kind

Submits `script/group_matrix_stats.py` on parcel × parcel relmat files.

| UI label | CLI method | Notes |
|---|---|---|
| Paired t + FDR | `paired_t_fdr` | Per-edge paired t-test, FDR across edges |
| NBS | `nbs` | Network-Based Statistic; FWER at component level |
| TF-NBS | `tf_nbs` | Threshold-free NBS |

### Shared options

| Option | Default | Notes |
|---|---|---|
| Pipeline | `fc` | |
| Atlas | `4S256Parcels` | matrix kind only |
| Measure | `pearson` | matrix kind only |
| Formula | `value ~ group * session + age_std + sex_code + fd_std + (1\|subject)` | lme4-style mixed model |
| Permutations | 1000 | increase to ≥ 5000 for TFCE publication analyses |
| Cluster threshold (GRF) | 0.05 | uncorrected p-threshold for cluster extent |
