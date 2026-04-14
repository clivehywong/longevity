# Data and Derivatives Flow

This page describes where inputs, outputs, and state live across the repository and adjacent project files.

## Main flow

```text
bids/
  -> validate_bids_names.py
  -> qa_check_images.py
  -> batch_fmriprep.sh
  -> fmriprep/
  -> master_full_connectivity_workflow.sh
  -> results/
```

## Root workflow outputs

| Stage | Main inputs | Main outputs |
|---|---|---|
| Validation/QC | `bids/` | console reports, `qa_images_full/` |
| Preprocessing | `bids/` + HPC | `fmriprep/` |
| Metadata | `fmriprep/`, `group.csv` | `results/metadata.csv` |
| Local measures | `fmriprep/` | `results/local_measures/` |
| Time series | `fmriprep/`, atlases | `results/timeseries_difumo256.h5` |
| Seed/network analysis | `results/metadata.csv`, atlases | `results/seed_based/`, `results/network_connectivity/` |
| Group analysis | subject-level maps + metadata | `results/group_analysis/` |
| Report generation | `results/` | `results/connectivity_report.html` |

## App-managed state outside the code directory

| Path | Role |
|---|---|
| `~/neuconn_projects/<project>.yaml` | user/project config overrides |
| `<bids parent>/qc_status.json` | QC decisions |
| sibling `bids_excluded/` | excluded scans with preserved structure |
| `<bids parent>/.neuconn/hpc_workflow_state.json` | HPC workflow state |
| `<bids>/derivatives/qc_images/` | QC image cache and manifest |

## Design implications

- The repository is not the only place state lives.
- Path changes ripple into scripts, config defaults, and app logic.
- Documentation should distinguish between durable derivatives and temporary or historical artifacts.
