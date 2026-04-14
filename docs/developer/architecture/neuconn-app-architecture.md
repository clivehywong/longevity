# NeuConn App Architecture

The app uses a custom navigation model rather than relying on Streamlit's default multipage routing.

## Entry point

`neuconn_app/app.py`

## Navigation model

- `app.py` renders a top-level sidebar with category selection.
- Each branch then renders deeper navigation controls.
- Leaf pages are loaded dynamically with `importlib.util`.
- Page implementation modules conventionally expose a top-level `render()` function.

## Directory layout

| Path | Role |
|---|---|
| `pages/` | top-level section entrypoints |
| `pages_general_qc/` | QC tools |
| `pages_fmri/` | fMRI preprocessing and analysis pages |
| `pages_dmri/` | dMRI pages |
| `pages_settings/` | settings UI |
| `utils/` | shared behavior and state helpers |
| `templates/` | SLURM templates |

## Config model

- Defaults start in `config/default_config.yaml`.
- User/project overrides come from `~/neuconn_projects/<project>.yaml`.
- `utils/config.py` expands `${var}` references and `~`, merges configs, and hydrates derived defaults.

## Important utility modules

| Module | Responsibility |
|---|---|
| `utils/bids.py` | dataset scanning, parameter detection, exclusion support |
| `utils/hpc.py` | SSH and SLURM workflow objects |
| `utils/qc_database.py` | QC persistence helpers |
| `utils/image_cache.py` | cached QC-image lifecycle |
| `utils/qa_image_generator.py` | image generation used by both app and CLI-style workflows |
| `utils/pipeline_state.py` | pipeline gate summaries and state loading |

## Current practical notes

- The app is strongest today in QC, configuration, and workflow support.
- Several pages still represent scaffolding or future work.
- The README should stay honest about what is currently working versus planned.
