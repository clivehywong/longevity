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

```bash
bash script/master_full_connectivity_workflow.sh --test
bash script/master_full_connectivity_workflow.sh
```

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

## What changed

- The primary docs are now organized by **audience** and **task**.
- Time-bound notes and old run-status material are no longer the main entrypoints.
- Script-folder markdown files are treated as legacy sources, not the main way to navigate the repo.
