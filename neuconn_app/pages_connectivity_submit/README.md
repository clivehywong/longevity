# Connectivity Submit Pages

These four pages expose the connectivity analysis pipeline as interactive HPC
submit forms inside the **fMRI Analysis** section of the NeuConn app.

Submission state (job IDs, status, parameters) is persisted by
`ConnectivityWorkflowManager` at
`<bids_parent>/.neuconn/connectivity_workflow_state.json`.

---

## 01 — Submit Local Measures

**Menu path:** fMRI Analysis → Subject Level → Submit Local Measures  
**Session-state prefix:** `submit_local_`

Submits per-subject/session fALFF, ALFF, and ReHo computation.

| Option | Default | Notes |
|---|---|---|
| Subjects / sessions | first 4 pairs | multi-select from available BIDS pairs |
| TR | from config | seconds |
| Bandpass low / high | 0.01 / 0.1 Hz | matching fMRIPrep defaults |
| Output directory | from config | |

---

## 02 — Submit Seed Connectivity

**Menu path:** fMRI Analysis → Subject Level → Submit Seed Connectivity  
**Session-state prefix:** `submit_seed_`

Submits seed-based correlation-map computation.

### Cascading Atlas → Seed multi-select

1. **Atlas radio** — select one atlas from those registered in the seed catalog.
2. **Seed list** — immediately filtered to seeds valid for that atlas, grouped by source:
   - ✨ **Priority** — MNI-sphere seeds from `.github/connectivity_config.yaml`
   - 🔧 **Custom** — ROI definitions from `neuconn_app/roi_config.json`
   - 🗺️ **Atlas parcels** — individual parcels from the selected atlas
3. Changing the atlas resets the selection (stale cross-atlas seeds are removed).

The seed catalog is built by `utils/seed_catalog.py` (`SeedCatalog`).

| Option | Notes |
|---|---|
| Atlas | one of `list_atlases()` from the merged catalog |
| Seeds | one or more seed IDs; tri-state source grouping |
| Subjects / sessions | multi-select |
| Smoothing (mm) | applied to functional data before correlation |
| High-pass / low-pass | bandpass filter cutoffs |

---

## 03 — Submit Network Connectivity

**Menu path:** fMRI Analysis → Subject Level → Submit Network Connectivity  
**Session-state prefix:** `submit_network_`

Submits parcel-timeseries extraction and within/between-network correlation
computation.

| Option | Notes |
|---|---|
| Atlas | DiFuMo256, Schaefer400, Schaefer200_Tian, etc. |
| Network grouping | None / Yeo7 / Yeo17 |
| Subjects / sessions | multi-select |
| Output format | NPZ / CSV |

---

## 04 — Submit Group Stats

**Menu path:** fMRI Analysis → Group Level → Submit Group Stats  
**Session-state prefix:** `submit_group_`

Submits second-level mixed-effects group analysis.

### Manifest preflight

Before building the HPC job the page reads a `.manifest.json` file from the
subject-level output directory to verify which subjects have completed outputs.
Subjects without valid outputs are listed and excluded from the submission.

Manifest candidates are checked in order:
1. `<subject_level_dir>/.manifest.json`
2. `results/.manifest.json`
3. `derivatives/connectivity-difumo256/subject-level/.manifest.json`

### Multiple-comparison correction

| UI label | CLI method | Notes |
|---|---|---|
| GRF (cluster-based) | `grf` | Gaussian Random Field cluster-extent correction |
| TFCE (permutation) | `tfce` | Threshold-Free Cluster Enhancement; recommend ≥ 5000 permutations |
| FDR | `fdr` | Benjamini-Hochberg FDR; set q threshold (default 0.05) |

### Other options

| Option | Default | Notes |
|---|---|---|
| Analysis source | Local Measures / Seed / Network | determines input directory |
| Formula | `value ~ group * session + age_std + sex_code + fd_std + (1\|subject)` | lme4-style mixed model |
| Permutations | 1000 | increase to ≥ 5000 for TFCE publication analyses |
| Cluster threshold (GRF) | 0.05 | uncorrected p-threshold for cluster extent |
| Min cluster size | 10 | voxels |
