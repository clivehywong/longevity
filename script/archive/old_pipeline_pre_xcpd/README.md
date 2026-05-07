# Archived: Old Self-Built Connectivity Pipeline (Pre-XCP-D)

**Date archived:** 2026-04-29

## Reason

Replaced by XCP-D-driven pipeline. XCP-D already computes ALFF, ReHo, parcellated mean timeseries, and Pearson correlation matrices; the new pipeline reads those directly and adds richer measures (Spearman, partial corr, PLV, wPLI, coherence, AEC, MI).

## What replaced it

| Archived | Replacement |
|---|---|
| `compute_local_measures.py` | XCP-D produces ALFF / ReHo directly; `00_local_measures_coverage.py` shows coverage |
| `compute_network_connectivity.py` | `script/compute_network_connectivity_xcpd.py` (8 measures, 5 atlases) |
| `hpc_seed_connectivity*.sh` | `script/compute_seed_connectivity_xcpd.py` via `ConnectivityWorkflowManager` |
| `hpc_*group*.sh` | `script/group_voxel_stats_xcpd.py` + `script/group_matrix_stats.py` |

**New utility modules:**
- `neuconn_app/utils/xcpd_outputs.py` — `XcpdDiscovery`, `XcpdOutputs`
- `neuconn_app/utils/seed_catalog.py` — refactored for XCP-D atlas parcels
- `neuconn_app/utils/connectivity_workflow.py` — `ConnectivityWorkflowManager`
- `neuconn_app/utils/connectivity_viewer.py` — viewer helpers

**Developer reference:** [`docs/developer/architecture/connectivity-pipeline.md`](../../../../docs/developer/architecture/connectivity-pipeline.md)

## File Index

| Archived File | Original Path |
|---|---|
| `compute_local_measures.py` | `script/compute_local_measures.py` |
| `compute_network_connectivity.py` | `script/compute_network_connectivity.py` |
| `create_difumo_network_definitions.py` | `script/create_difumo_network_definitions.py` |
| `create_network_definitions.py` | `script/create_network_definitions.py` |
| `functional_connectivity_analysis.py` | `script/functional_connectivity_analysis.py` |
| `connectivity_visualization.py` | `script/connectivity_visualization.py` |
| `compare_local_hpc_zmaps.py` | `script/compare_local_hpc_zmaps.py` |
| `COMPUTE_NETWORK_CONNECTIVITY_NOTES.md` | `script/COMPUTE_NETWORK_CONNECTIVITY_NOTES.md` |
| `hpc_between_network_array.sh` | `script/hpc_between_network_array.sh` |
| `hpc_full_connectivity_pipeline.sh` | `script/hpc_full_connectivity_pipeline.sh` |
| `hpc_individual_seeds_array.sh` | `script/hpc_individual_seeds_array.sh` |
| `hpc_individual_seeds_group_array.sh` | `script/hpc_individual_seeds_group_array.sh` |
| `hpc_local_measures_all24.sh` | `script/hpc_local_measures_all24.sh` |
| `hpc_seed_connectivity_array.sh` | `script/hpc_seed_connectivity_array.sh` |
| `hpc_seed_connectivity_array_with_manifest.sh` | `script/hpc_seed_connectivity_array_with_manifest.sh` |
| `hpc_seed_connectivity_phase2.sh` | `script/hpc_seed_connectivity_phase2.sh` |
| `hpc_seed_connectivity_priority.sh` | `script/hpc_seed_connectivity_priority.sh` |
| `hpc_seed_connectivity.sh` | `script/hpc_seed_connectivity.sh` |
| `hpc_seed_dlpfc_all24.sh` | `script/hpc_seed_dlpfc_all24.sh` |
| `hpc_group_analysis_local_measures.sh` | `script/hpc_group_analysis_local_measures.sh` |
| `01_submit_local_measures.py` | `neuconn_app/pages_connectivity_submit/01_submit_local_measures.py` |
| `test_network_connectivity.py` | `tests/test_network_connectivity.py` (archived to `tests/archive/old_pipeline_pre_xcpd/`) |
