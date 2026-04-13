# Repository instructions

## Commands

- This repository does not define a standard build target, lint target, or pytest-based test suite in root config files. Prefer the existing script-level entrypoints and smoke tests instead of inventing new commands.
- Root workflow and validation commands:
  - `python script/validate_bids_names.py bids/`
  - `python script/qa_check_images.py bids/ qa_images_full/`
  - `bash script/batch_fmriprep.sh`
  - `bash script/batch_fmriprep.sh status`
  - `bash script/master_full_connectivity_workflow.sh --test`
  - `bash script/master_full_connectivity_workflow.sh`
- Single-test / narrow-scope commands:
  - `bash script/test_local_measures.sh` runs the local-measures pipeline on `sub-033 ses-01`
  - `cd neuconn_app && python test_cli.py` runs a lightweight CLI smoke test for config loading and BIDS scanning
- App run command:
  - `cd neuconn_app && pip install -r requirements.txt`
  - `cd neuconn_app && streamlit run app.py`
- Cloud-agent setup:
  - `.github/workflows/copilot-setup-steps.yml` preinstalls `neuconn_app` Python dependencies and Chromium so future Copilot cloud-agent sessions can use Playwright against the Streamlit app without re-discovering the environment setup

## High-level architecture

- The repository has two main layers:
  1. Root-level neuroimaging workflows and datasets (`bids/`, `fmriprep/`, `atlases/`, `results/`, `script/`)
  2. `neuconn_app/`, a Streamlit UI for QC, configuration, and HPC orchestration
- `script/master_full_connectivity_workflow.sh` is the main end-to-end connectivity pipeline. It orchestrates metadata preparation, local measures, seed-based connectivity, network connectivity, group-level statistics, and final HTML report generation. The workflow consumes `fmriprep/`, `atlases/`, and `group.csv`, and writes into `results/`.
- Root preprocessing/HPC automation is script-driven. `script/batch_fmriprep.sh` handles upload, SLURM submission, download, and remote cleanup in batches because the project assumes storage-constrained HPC processing.
- `neuconn_app/app.py` is not using Streamlit's default multipage routing as the primary architecture. It builds its own hierarchical sidebar, then dynamically imports leaf page modules with `importlib.util` and calls each page's `render()` function.
- Shared app behavior lives in `neuconn_app/utils/`:
  - `config.py` loads YAML config with precedence `default_config.yaml` -> `~/neuconn_projects/*.yaml` -> runtime overrides
  - `bids.py` scans datasets and handles exclusion/restore operations
  - `hpc.py` holds the SSH/SLURM workflow objects
  - `image_cache.py` manages cached QC images under the BIDS tree
  - `qc_database.py` persists QC decisions
- The app stores state outside the code directory:
  - user config: `~/neuconn_projects/<project>.yaml`
  - QC status: `<bids parent>/qc_status.json`
  - exclusion files: sibling `bids_excluded/`
  - HPC workflow state: `<bids parent>/.neuconn/hpc_workflow_state.json`
  - QC image cache: `<bids>/derivatives/qc_images/`

## Key conventions

- Treat the root `script/` workflows as the source of truth for the research pipeline. The Streamlit app wraps or assists those workflows; it does not replace the script-based pipeline.
- Many scripts hardcode this repository's local paths (for example `/home/clivewong/proj/longevity` and sibling dataset directories). When changing path handling, update all connected scripts and defaults together rather than fixing only one call site.
- App page modules conventionally expose a top-level `render()` function and often prepend their parent directory to `sys.path` for local imports. Follow that pattern when adding new pages or moving shared logic.
- Page filenames are intentionally numbered (`00_`, `01_`, etc.) to reflect navigation order. The real implementation pages live under folders such as `pages_general_qc/`, `pages_fmri/`, `pages_dmri/`, and `pages_settings/`; the top-level `pages/` files are mostly section entrypoints.
- Config values intentionally support `${var}` references and `~` expansion. Preserve that behavior in defaults and settings UI instead of flattening derived paths into hardcoded strings.
- QC operations preserve BIDS-relative paths. Failed scans are first marked in `qc_status.json`, then moved to `bids_excluded/` while keeping the original directory structure and sidecar files together.
- The QC image cache is designed to live inside the dataset as a derivatives-style artifact (`bids/derivatives/qc_images/`), not in an arbitrary temp folder.
- The fMRI preprocessing/HPC path assumes selective upload of `anat`, `fmap`, and `func` by default and treats remote cleanup as part of the normal workflow.
- The study assumptions are longitudinal and resting-state specific: two-session subjects are common, TR is typically 0.8 s, and the main outputs are expected in `MNI152NLin2009cAsym:res-2` and `T1w` spaces.
