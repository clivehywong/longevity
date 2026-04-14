# Documentation Index

This directory is organized as a task-oriented documentation hierarchy.

## Start here

| Audience | Entry point | Purpose |
|---|---|---|
| Users | [`user/README.md`](user/README.md) | Step-by-step setup, workflows, troubleshooting, and parameter guidance |
| Developers | [`developer/README.md`](developer/README.md) | Architecture, repository structure, script catalog, and maintenance notes |
| Historical material | [`archive/`](archive/) | Archived status logs, old implementation notes, and superseded records |

## Documentation map

### User docs

- [`user/getting-started/README.md`](user/getting-started/README.md)
  - [`system-setup.md`](user/getting-started/system-setup.md)
  - [`repository-orientation.md`](user/getting-started/repository-orientation.md)
- [`user/workflows/README.md`](user/workflows/README.md)
  - [`bids-validation-and-qc.md`](user/workflows/bids-validation-and-qc.md)
  - [`fmriprep-hpc-workflow.md`](user/workflows/fmriprep-hpc-workflow.md)
  - [`connectivity-analysis.md`](user/workflows/connectivity-analysis.md)
  - [`neuconn-app.md`](user/workflows/neuconn-app.md)
- [`user/troubleshooting/README.md`](user/troubleshooting/README.md)
  - [`common-failures.md`](user/troubleshooting/common-failures.md)
  - [`hpc-and-path-issues.md`](user/troubleshooting/hpc-and-path-issues.md)
- [`user/reference/README.md`](user/reference/README.md)
  - [`parameter-considerations.md`](user/reference/parameter-considerations.md)
  - [`commands-and-entrypoints.md`](user/reference/commands-and-entrypoints.md)

### Developer docs

- [`developer/architecture/README.md`](developer/architecture/README.md)
  - [`repository-structure.md`](developer/architecture/repository-structure.md)
  - [`data-and-derivatives-flow.md`](developer/architecture/data-and-derivatives-flow.md)
  - [`neuconn-app-architecture.md`](developer/architecture/neuconn-app-architecture.md)
- [`developer/maintenance/README.md`](developer/maintenance/README.md)
  - [`script-catalog.md`](developer/maintenance/script-catalog.md)
  - [`documentation-sources-and-archive-policy.md`](developer/maintenance/documentation-sources-and-archive-policy.md)

## Current source-of-truth entrypoints

These scripts are the main operational entrypoints reflected by the user docs:

- `python script/validate_bids_names.py bids/`
- `python script/qa_check_images.py --bids-dir bids --output qa_images_full`
- `bash script/batch_fmriprep.sh`
- `bash script/master_full_connectivity_workflow.sh --test`
- `cd neuconn_app && python test_cli.py`

## Older top-level guides

The former flat guides remain as compatibility wrappers:

- [`WORKFLOW_GUIDE.md`](WORKFLOW_GUIDE.md)
- [`HPC_SEED_CONNECTIVITY_GUIDE.md`](HPC_SEED_CONNECTIVITY_GUIDE.md)
- [`CONNECTIVITY_ANALYSIS_GUIDE.md`](CONNECTIVITY_ANALYSIS_GUIDE.md)

Use the new nested docs for the maintained versions.
