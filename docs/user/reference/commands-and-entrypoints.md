# Commands and Entrypoints

## Core validation and QC

| Command | Purpose |
|---|---|
| `python script/validate_bids_names.py bids/` | Validate BIDS naming and sidecar consistency |
| `python script/qa_check_images.py --bids-dir bids --output qa_images_full` | Generate visual QA images |

## Preprocessing

| Command | Purpose |
|---|---|
| `bash script/batch_fmriprep.sh` | Run the full batch HPC preprocessing workflow |
| `bash script/batch_fmriprep.sh status` | Check SLURM queue status |
| `bash script/batch_fmriprep.sh upload 1` | Upload one batch manually |
| `bash script/batch_fmriprep.sh submit 1` | Submit one batch manually |
| `bash script/batch_fmriprep.sh download 1` | Download one batch manually |
| `bash script/batch_fmriprep.sh cleanup 1` | Clean one remote batch manually |

## Connectivity analysis

| Command | Purpose |
|---|---|
| `bash script/test_local_measures.sh` | Smoke-test the local-measures pipeline |
| `python script/prepare_metadata.py --fmriprep fmriprep --group group.csv --output results/metadata.csv` | Build metadata for downstream analysis |
| `bash script/master_full_connectivity_workflow.sh --test` | Run the end-to-end workflow on a subset |
| `bash script/master_full_connectivity_workflow.sh` | Run the full end-to-end workflow |

## NeuConn app

| Command | Purpose |
|---|---|
| `cd neuconn_app && pip install -r requirements.txt` | Install app dependencies |
| `cd neuconn_app && python test_cli.py` | Smoke-test config loading and BIDS scanning |
| `cd neuconn_app && streamlit run app.py` | Launch the Streamlit app |

## Narrow-scope scripts behind the master workflow

| Script | Selected parameters |
|---|---|
| `compute_local_measures.py` | `--measures`, `--subjects`, `--sessions`, `--tr`, `--low-freq`, `--high-freq`, `--neighborhood` |
| `extract_timeseries.py` | `--atlas`, `--smoothing`, `--high-pass`, `--low-pass`, `--confounds`, `--subjects`, `--sessions` |
| `seed_based_connectivity.py` | `--seed-names`, `--space`, `--smoothing`, `--high-pass`, `--low-pass` |
| `python_connectivity_analysis.py` | `--within-network`, `--between-networks`, `--all-within`, `--all-between`, `--alpha` |
| `group_level_analysis.py` | `--cluster-threshold`, `--n-permutations`, `--min-cluster-size`, `--no-uncorrected-fallback` |
| `generate_html_report.py` | `--results-dir`, `--output` |
