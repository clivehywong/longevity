# System Setup

This repository combines shell scripts, Python workflows, and a Streamlit app. The practical setup depends on which part of the project you need.

## Minimum working setup

### For command-line workflows

- A Unix-like shell environment
- Python available for the scripts under `script/`
- The repository cloned with access to `bids/`, `fmriprep/`, `atlases/`, and `results/`

### For HPC preprocessing

- SSH access to the SLURM cluster
- `rsync` available locally
- The path assumptions in `script/batch_fmriprep.sh` matching your environment

### For the NeuConn app

```bash
cd neuconn_app
pip install -r requirements.txt
python test_cli.py
streamlit run app.py
```

The app reads configuration from `~/neuconn_projects/<project>.yaml` when present and otherwise starts from the default config.

## First checks

### Validate the raw dataset

```bash
python script/validate_bids_names.py bids/
python script/qa_check_images.py --bids-dir bids --output qa_images_full
```

### Check the app environment

```bash
cd neuconn_app
python test_cli.py
```

## Environment assumptions to review early

- Many workflow scripts assume the repository lives at `/home/clivewong/proj/longevity`.
- HPC scripts assume a remote project root at `/home/clivewong/proj/long`.
- The main connectivity workflow writes to `results/`.
- The app stores important state outside the code directory, including:
  - `~/neuconn_projects/<project>.yaml`
  - `<bids parent>/qc_status.json`
  - `<bids>/derivatives/qc_images/`
  - `<bids parent>/.neuconn/hpc_workflow_state.json`

If your machine differs from those assumptions, read [`../troubleshooting/hpc-and-path-issues.md`](../troubleshooting/hpc-and-path-issues.md) before running batch workflows.
