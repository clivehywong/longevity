# Repository Orientation

This project has two main layers: script-driven neuroimaging workflows at the repository root and the `neuconn_app/` Streamlit interface.

## Main directories

| Path | What it is for |
|---|---|
| `bids/` | Raw BIDS-formatted study data |
| `fmriprep/` | Preprocessed derivatives downloaded from HPC or produced externally |
| `atlases/` | Atlas files and seed/network definitions |
| `script/` | Source-of-truth workflow scripts plus legacy notes |
| `results/` | Current connectivity-analysis outputs from the master workflow |
| `docs/` | Maintained documentation hierarchy |
| `neuconn_app/` | Streamlit QC and orchestration app |

## How to think about the repo

### If you are a user

- Treat `script/` as the operational layer.
- Treat `docs/user/` as the maintained guide layer.
- Use the app when you want interactive QC, configuration, or orchestration help.

### If you are a developer

- Treat `script/` and `neuconn_app/` as the codebase.
- Treat `docs/developer/` as the architectural map.
- Treat `docs/archive/` and `script/*.md` as historical context, not the default source of truth.

## Outputs and side effects

- QC image generation creates derivative-style cache artifacts under `bids/derivatives/qc_images/`.
- QC decisions are stored beside the dataset rather than inside the app code directory.
- Batch HPC workflows assume upload, remote processing, download, and remote cleanup are part of the normal lifecycle.
