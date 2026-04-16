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

## Prerequisites for the XCP-D pipeline

Before using **fMRI Analysis → XCP-D Pipeline**, you need:

| Item | Default path | Notes |
|---|---|---|
| XCP-D Singularity image | `~/software/xcp-d-*.sif` | Set in **Settings → Software / Images** |
| FreeSurfer licence | `~/software/license.txt` | Set in **Settings → Software / Images** |
| fMRIPrep derivatives | `derivatives/preprocessing/fmriprep/` | Must contain `dataset_description.json` |
| Custom atlas datasets | `atlases/LongevitySchaefer200/`, `atlases/tian/` | Packaged as BIDS derivative datasets |

For HPC runs, configure SSH host, remote project root, and HPC Singularity image path in **Settings → HPC**.

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

Three pipelines are available; all share the same atlas selection:

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
5. After HPC completion, use **📥 Download XCP-D outputs from HPC** to rsync results locally.

> **Re-run safety**: if a pipeline is already completed and the QC gate has been approved, re-running automatically invalidates the QC approval and you must re-review QC.

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
| `derivatives/preprocessing/xcpd/fc/` | XCP-D FC outputs |
| `derivatives/preprocessing/xcpd/fc_gsr/` | XCP-D FC+GSR outputs |
| `derivatives/preprocessing/xcpd/ec/` | XCP-D EC outputs |
| `derivatives/subject_level/fc/` | Subject-level FC manifests and seed exports |

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
