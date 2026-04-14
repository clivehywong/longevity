# Repository Structure

The repository is split between script-driven neuroimaging workflows at the root and the `neuconn_app/` Streamlit interface.

## High-level layout

```text
longevity/
├── bids/                # raw BIDS data
├── fmriprep/            # preprocessing outputs
├── atlases/             # atlas assets and seed/network definitions
├── results/             # current connectivity outputs
├── script/              # workflow entrypoints and legacy support material
├── docs/                # maintained docs hierarchy
└── neuconn_app/         # Streamlit QC/orchestration app
```

## Two main layers

### 1. Root workflow layer

This is the research pipeline layer. The most important entrypoints are:

- `batch_fmriprep.sh`
- `master_full_connectivity_workflow.sh`
- validation and QA scripts
- analysis scripts that the master workflow orchestrates

### 2. App layer

`neuconn_app/` provides:

- dataset scanning
- interactive QC workflows
- configuration management
- SSH/HPC orchestration helpers
- cached QC image browsing

The app supports the workflow layer but does not replace it.

## Documentation strategy

- `docs/user/`: operational guidance
- `docs/developer/`: codebase map and maintenance notes
- `docs/archive/`: historical or deprecated material
- `script/*.md`: legacy sources to mine when needed, not primary entrypoints
