# NeuConn App

The app is the interactive layer for QC, configuration, and workflow orchestration. It does not replace the script-driven research pipeline; it wraps and assists it.

## Start the app

```bash
cd neuconn_app
pip install -r requirements.txt
python test_cli.py
streamlit run app.py
```

## First-run flow

1. Open the app.
2. Go to **Settings** if you need to confirm paths or config values.
3. Use **Dataset Overview** to scan the dataset.
4. Continue into QC or workflow-specific pages.

## Navigation overview

The sidebar has two levels:

1. **Category** (radio) — Data QC / fMRI Analysis / dMRI Analysis / Comparison / Pipeline Builder / Settings
2. **Page** (radio or selectbox) — depends on the selected category

### Data QC category

| Page | Purpose |
|---|---|
| 📊 Dataset Overview | BIDS structure, modality breakdown, QC image cache |
| 📋 Subject Data | Group assignments, demographics, BIDS conflict detection |
| 🧠 Anatomical | T1w visual QC |
| 🎯 Functional | EPI visual QC |
| 🔗 Diffusion | DWI visual QC |
| 🗺️ Field Maps | Fieldmap visual QC |

### fMRI Analysis category

| Page | Purpose |
|---|---|
| 📊 fMRI Dashboard | At-a-glance preprocessing status per subject |
| fMRIPrep Submit | HPC submission and status monitoring |
| fMRIPrep QC Reports | Browse HTML QC reports |
| XCP-D Pipeline | FD gating, XCP-D runs, post-QC, per-subject status |
| XCP-D QC Reports | Browse XCP-D QC reports |

## Subject Data page

**Data QC → 📋 Subject Data** shows and edits the project's `group.csv`.

- The table is editable directly in the UI. Click **Save** to write changes back.
- Use the file uploader to replace or merge a CSV from disk.
- Subjects present in the BIDS folder but missing from `group.csv` are flagged as "unlabeled" — they are not auto-assigned a group.

## fMRI Preprocessing Dashboard

**fMRI Analysis → 📊 fMRI Dashboard** gives a one-line status per subject:

| Column | Meaning |
|---|---|
| fMRIPrep | HTML report found in `derivatives/func/preprocessing/fmriprep/<sub>/` |
| XCP-D FC | output directory found for FC (no GSR) pipeline |
| XCP-D FC+GSR | output directory found for FC+GSR pipeline |
| XCP-D EC | output directory found for EC pipeline |

Click **🔄 Rescan** to recheck the filesystem after adding new subjects or running preprocessing.

## Pipeline gates

The sidebar shows two independent gate summaries:

- **fMRI gates** — FD approval, XCP-D QC approval, Subject-level outputs
- **dMRI gates** — QSIPrep outputs, Tractography QC

Gates are green/amber/grey depending on what has been completed or approved.

## Prerequisites for the XCP-D pipeline

Before using **fMRI Analysis → XCP-D Pipeline**, you need:

| Item | Default path | Notes |
|---|---|---|
| XCP-D Singularity image | `~/software/xcp-d-*.sif` | Set in **Settings → Software / Images** |
| FreeSurfer license | `~/freesurfer/license.txt` | Set in **Settings → Software / Images** |
| fMRIPrep derivatives | `derivatives/func/preprocessing/fmriprep/` | Must contain `dataset_description.json` |
| Custom atlas datasets | `atlases/LongevitySchaefer200/`, `atlases/tian/` | Packaged as BIDS derivative datasets |

For HPC runs, configure SSH host, **Port**, remote project root, and HPC Singularity image path in **Settings → HPC**.

### SSH tunnel shortcut

If you are using an SSH tunnel to get around rate limits:

```bash
ssh -p 2222 localhost   # starts tunnel
```

In **Settings → HPC Connection Settings** set:
- **Host**: `localhost`
- **Port**: `2222`

## XCP-D pipeline workflow {#xcpd-pipeline}

The full pipeline is gated — each stage must be approved before the next unlocks.

```
fMRIPrep → FD Inspection → [FD Gate] → XCP-D FC / FC+GSR / EC → Post-XCP-D QC → [QC Gate] → Subject Level → Group Level
```

### Step 1 — FD Inspection

Open **fMRI Analysis → XCP-D Pipeline → FD Inspection tab**.

- Click **Generate / Refresh FD Summary** to scan all confound TSV files.
- Review the mean-FD distribution, projected data-retention percentages, and the subject-exclusion preview.
- Set FC FD threshold, EC mean-FD threshold, and minimum scan time.
- Click **Approve thresholds** to unlock the XCP-D run panel.

### Step 2 — XCP-D Runs

Open **fMRI Analysis → XCP-D Pipeline → XCP-D Runs tab**.

Three pipelines are available; each has its own atlas selection (configured in Settings):

| Pipeline | Nuisance strategy | Key feature |
|---|---|---|
| **FC (no GSR)** | `acompcor` (default) | Primary FC pipeline; no global signal removal |
| **FC + GSR** | `36P` (default) | Comparison pipeline; includes global signal |
| **Effective Connectivity** | `acompcor` | No scrubbing; interpolated; wider bandpass |

For each pipeline:

1. Select subjects and sessions.
2. Toggle **Run on HPC** if needed; use the **Upload fMRIPrep to HPC** expander if the derivatives are not yet on the cluster.
3. Click **Start … XCP-D**. A SLURM job ID (HPC) or PID (local) is shown.
4. Monitor progress with the inline progress bar and **🔄 Refresh status** button.
   - The bar shows `N/total nodes` — a *node* is one Nipype processing step (e.g. denoising, atlasing) for one subject/run.
5. After HPC completion, use **📥 Download XCP-D outputs from HPC** to rsync results locally.

> **Re-run safety**: if a pipeline is already completed and the QC gate has been approved, re-running automatically invalidates the QC approval and you must re-review QC.

### Monitoring per-subject completion

Expand **📋 Subject Completion Status** (below the three run panels) to see which subjects have finished for each pipeline. The status is read from a `status` sentinel file written inside each subject's output directory when the run completes, with a fallback to HTML report detection.

Click **Rescan** inside the expander to refresh after a run finishes.

### Step 3 — Post-XCP-D QC

Open **fMRI Analysis → XCP-D Pipeline → Post-XCP-D QC tab**.

- Three columns show QC report counts for FC, FC+GSR, and EC.
- The **FC Motion / Censoring Summary** table shows `n_censored` and `pct_retained` per subject.
- The **EC Exclusion Preview** lists subjects above the mean-FD threshold approved in Step 1.
- Click **Approve and Proceed** to unlock subject-level and group-level analysis.

### Step 4 — Subject Level

After QC approval, open **fMRI Analysis → Subject Level**.

- **Local Measures**: click **Refresh local-measure manifests** to index ALFF, fALFF, and ReHo outputs.
- **Seed Connectivity**: click **Export atlas-based seed summaries** to compute seed timeseries and connectivity matrices.

## Where the app keeps state

| Path | Contents |
|---|---|
| `~/neuconn_projects/<project>.yaml` | User/project config and path overrides |
| `<bids parent>/qc_status.json` | QC decisions (pass/fail per scan) |
| `<bids parent>/.neuconn/xcpd_pipeline_state.json` | Pipeline step statuses, gate approvals, run metadata |
| `sibling bids_excluded/` | Excluded scans (original structure preserved) |
| `<bids>/derivatives/qc_images/` | QC image cache |
| `derivatives/func/preprocessing/fmriprep/` | fMRIPrep outputs |
| `derivatives/func/preprocessing/xcpd_fc/` | XCP-D FC (no GSR) outputs |
| `derivatives/func/preprocessing/xcpd_fc_gsr/` | XCP-D FC+GSR outputs |
| `derivatives/func/preprocessing/xcpd_ec/` | XCP-D EC outputs |
| `derivatives/dwi/preprocessing/qsiprep/` | QSIPrep outputs (future) |
| `derivatives/pipeline_runs/` | SLURM scripts, run manifests, and log references |
| `derivatives/func/subject_level/fc/` | Subject-level FC manifests and seed exports |

## What the smoke test covers

`python test_cli.py` checks:

- config loading
- BIDS scanning
- acquisition-parameter detection

## When to use the app

- interactive QC review
- XCP-D pipeline gating and monitoring
- config-driven project setup
- monitoring cache and dataset state

## When to stay in the shell

- batch fMRIPrep preprocessing (`script/batch_fmriprep.sh`)
- master connectivity runs (`script/master_full_connectivity_workflow.sh`)
- one-off script execution with explicit flags
