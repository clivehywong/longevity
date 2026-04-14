# Script Catalog

This catalog separates active workflow entrypoints from narrower utilities and legacy materials.

## Primary operational entrypoints

| Script | Role | Notes |
|---|---|---|
| `script/batch_fmriprep.sh` | Batch HPC preprocessing | Upload, submit, download, cleanup |
| `script/master_full_connectivity_workflow.sh` | End-to-end connectivity pipeline | Current documented primary workflow |
| `script/test_local_measures.sh` | Narrow smoke test | Useful before larger runs |
| `script/validate_bids_names.py` | BIDS naming validation | Safe preflight check |
| `script/qa_check_images.py` | Batch QA image generation | Supports subject/session filters |

## Analysis components behind the master workflow

| Script | Role |
|---|---|
| `script/prepare_metadata.py` | Build subject/session metadata |
| `script/compute_local_measures.py` | Compute fALFF and ReHo |
| `script/extract_timeseries.py` | Extract ROI time series from fMRIPrep outputs |
| `script/seed_based_connectivity.py` | Generate seed-to-voxel maps |
| `script/python_connectivity_analysis.py` | ROI/network connectivity statistics |
| `script/group_level_analysis.py` | Voxelwise group-level statistics |
| `script/generate_html_report.py` | Build the final HTML report |

## HPC and workflow variants

The script directory also contains:

- HPC submission variants
- DLPFC-specific exploratory scripts
- reprocessing helpers
- older workflow variants such as `master_full_connectivity_workflow_v2.sh`

Treat these as advanced or historical until they are promoted into the main documented path.

## Legacy material

Legacy material still in `script/` includes:

- CONN/MATLAB workflows
- subject-specific fix notes
- parallel-processing snapshots
- old atlas or label fix notes

These files are useful as historical sources, but new docs should summarize reusable knowledge instead of sending users directly into them.
