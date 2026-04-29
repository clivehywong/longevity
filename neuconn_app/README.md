# NeuConn

NeuConn is the Streamlit-based QC and workflow support layer for this repository.

## What it is for

- dataset scanning and overview
- interactive QC review
- configuration management
- HPC/orchestration helpers
- cached QC image browsing

The app supports the root workflow scripts; it does not replace them.

## Run it

```bash
cd neuconn_app
pip install -r requirements.txt
python test_cli.py
streamlit run app.py
```

## Configuration

- default config: `config/default_config.yaml`
- project overrides: `~/neuconn_projects/<project>.yaml`
- config loading and hydration: `utils/config.py`

## Pages

### Data QC (`pages_general_qc/`)
Dataset overview, subject data, anatomical/functional/diffusion/fieldmap QC.

### fMRI Analysis (`pages_fmri/`)
fMRI dashboard, fMRIPrep submit, QC reports, XCP-D pipeline, XCP-D QC reports.

### Connectivity Submit (`pages_connectivity_submit/`)
| File | Page |
|---|---|
| `01_submit_local_measures.py` | Subject Level → Submit Local Measures |
| `02_submit_seed_connectivity.py` | Subject Level → Submit Seed Connectivity |
| `03_submit_network_connectivity.py` | Subject Level → Submit Network Connectivity |
| `04_submit_group_stats.py` | Group Level → Submit Group Stats |

See [`pages_connectivity_submit/README.md`](pages_connectivity_submit/README.md) for details.

### Settings (`pages_settings/`)
Project, paths, HPC, software images, analysis parameters, ROI config, QC profiles, import/export.



- `app.py` builds a custom hierarchical sidebar
- page modules are loaded dynamically and expose `render()`
- shared behavior lives in `utils/`
- QC image caching writes derivative-style artifacts under the BIDS tree

## Documentation

- User guide: [`../docs/user/workflows/neuconn-app.md`](../docs/user/workflows/neuconn-app.md)
- App architecture: [`../docs/developer/architecture/neuconn-app-architecture.md`](../docs/developer/architecture/neuconn-app-architecture.md)
- Script/repo context: [`../docs/developer/maintenance/script-catalog.md`](../docs/developer/maintenance/script-catalog.md)
