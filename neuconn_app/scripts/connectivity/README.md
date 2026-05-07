# neuconn_app/scripts/connectivity

App-resident connectivity scripts. Files here are symlinks into the canonical
`script/` directory at the repo root — keeping the app self-contained while
avoiding code duplication.

When the app submits a connectivity job to HPC, it uploads from this directory
(resolving symlinks) so the remote sees the actual script files.

| File | Purpose |
|---|---|
| `compute_seed_connectivity_xcpd.py` | Subject-level seed-to-voxel & seed-to-parcel |
| `compute_network_connectivity_xcpd.py` | Subject-level network/parcel-to-parcel |
| `connectivity_measures.py` | 8-measure library |
| `group_voxel_stats_xcpd.py` | Group voxel-level stats (TFCE/GRF/FDR) |
| `group_matrix_stats.py` | Group matrix-level stats |
| `hpc_submit_subject_level.py` | SLURM array submit (legacy CLI path) |
| `hpc_submit_group_level.py` | SLURM group submit (legacy CLI path) |

Source of truth: `<repo>/script/`. Edit there.
