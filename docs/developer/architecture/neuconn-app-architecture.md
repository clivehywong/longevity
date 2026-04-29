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
| `pages_general_qc/` | QC tools and subject data management |
| `pages_fmri/` | fMRI preprocessing and analysis pages |
| `pages_dmri/` | dMRI pages |
| `pages_settings/` | settings UI |
| `pages_connectivity_submit/` | Connectivity HPC submit pages (local measures, seed, network, group stats) |
| `utils/` | shared behavior and state helpers |
| `tests/` | Playwright smoke tests (`test_redesign.py`) |

### Key pages

| File | Purpose |
|---|---|
| `pages_general_qc/08_subject_data.py` | Subject Data — editable group.csv, BIDS conflict detection |
| `pages_fmri/preprocessing/00_fmri_dashboard.py` | fMRI Dashboard — per-subject preprocessing status table |
| `pages_fmri/preprocessing/06_xcpd_pipeline.py` | XCP-D Pipeline — FD gating, runs, QC, per-subject status |

### Connectivity submit pages (`pages_connectivity_submit/`)

Four pages under **fMRI Analysis** expose subject-level and group-level connectivity stages. All pages carry a **pipeline selector** (fc / fc_gsr / ec) and use XCP-D atlas names (4S256Parcels, 4S456Parcels, Glasser, Gordon, Tian).

| File | Page | Session-state prefix |
|---|---|---|
| `00_local_measures_coverage.py` | 📊 Local Measures Coverage | `submit_local_` |
| `02_submit_seed_connectivity.py` | 📤 Submit Seed Connectivity | `submit_seed_` |
| `03_submit_network_connectivity.py` | 📤 Submit Network Connectivity | `submit_network_` |
| `04_submit_group_stats.py` | 📤 Submit Group Stats | `submit_group_` |

`00_local_measures_coverage.py` is a read-only discovery dashboard — it calls `XcpdDiscovery` to enumerate per-subject ALFF/ReHo/fALFF files and displays coverage; it does **not** submit any HPC jobs.

`02_submit_seed_connectivity.py` cascading **Pipeline → Atlas → Seed** multi-select with three seed sources:
- `xcpd_atlas_parcel` — parcels from the selected XCP-D atlas
- `custom_nifti_roi` — ROI NIfTI files from config
- `sphere` — MNI coordinate + radius

`04_submit_group_stats.py` has a **kind** toggle: **Voxel** (runs `group_voxel_stats_xcpd.py`, GRF/TFCE/FDR correction) or **Matrix** (runs `group_matrix_stats.py`, paired_t_fdr/NBS/TF-NBS).

### Connectivity output tree

```
derivatives/connectivity/
  {fc,fc_gsr,ec}/
    sub-XX/ses-YY/
      seed/<seed_id>/
        *_atlas-<A>_measure-<M>_seed-to-parcel.tsv
        *_seed-to-voxel_zmap.nii.gz
      network/atlas-<A>/
        *_measure-<M>_relmat.tsv
        *_measure-<M>_relmat-z.tsv   # Fisher-z for correlation measures
  group/
    voxel/...     # group_voxel_stats_xcpd.py outputs
    matrix/...    # group_matrix_stats.py outputs
```



- Defaults start in `config/default_config.yaml`.
- User/project overrides come from `~/neuconn_projects/<project>.yaml`.
- `utils/config.py` expands `${var}` references and `~`, merges configs, and hydrates derived defaults.
- `config.py` (the project facade) adds higher-level derived defaults on top of the raw YAML.

### Output path conventions

All derivatives are split by modality under the derivatives directory:

```
derivatives/
  func/
    preprocessing/
      fmriprep/          # fMRIPrep outputs
      xcpd/
        fc/              # XCP-D FC (no GSR)
        fc_gsr/          # XCP-D FC+GSR
        ec/              # XCP-D EC (effective connectivity)
    subject_level/
      fc/                # subject-level FC manifests
  dwi/
    preprocessing/
      qsiprep/           # QSIPrep (future)
      qsirecon/          # QSIRecon (future)
  pipeline_runs/
    xcpd_fc/run_YYYYMMDD_HHMMSS/   # SLURM scripts, manifests, log refs
    xcpd_fc_gsr/...
    xcpd_ec/...
```

The `pipeline_runs_dir` config key controls where run artifacts (SLURM scripts, manifests) are written. Previous versions wrote these into the XCP-D QC directory, which was misleading.

### Software / Singularity image config

All external tool image paths are stored in two parallel config sections:

| Section | Used for |
|---|---|
| `software.singularity_images` | **Local** execution on the machine running the app |
| `hpc.singularity_images` | **Remote** execution on the HPC cluster |

Both sections cover: `fmriprep`, `xcp_d`, `fmripost_aroma`, `qsiprep`, `qsirecon`, `freesurfer_license`.

`software.singularity_bind_mounts` lists local directories to bind-mount into the container.

The legacy `xcpd.singularity_image_path` key is kept for backward compatibility; `software.singularity_images.xcp_d` takes precedence when set.

### SLURM resource config

XCP-D SLURM job CPUs are computed at submit time from `nprocs × omp_nthreads`, which the user sets
in the **⚙️ SLURM Resources** expander on the XCP-D Runs tab. The `xcpd_max_cpus` guard prevents
accidentally requesting more CPUs than the cluster QOS allows:

```yaml
hpc:
  slurm:
    # fMRIPrep defaults (also used for XCP-D if overrides are absent)
    default_cpus: 8
    default_memory: "32GB"
    default_time: "24:00:00"
    # XCP-D-specific overrides (0/"" = fall back to defaults above)
    xcpd_cpus: 0          # 0 = use nprocs × omp_nthreads (set at submit time)
    xcpd_max_cpus: 15     # UI warning threshold; does not block submission
    xcpd_memory: "64GB"
    xcpd_time: "12:00:00"
```

`nprocs` and `omp_nthreads` are saved to `config["xcpd"][pipeline_name]` on each submit so that
the values persist in the YAML config for future submissions.

### XCP-D pipeline status values

`run_info["status"]` (stored in `.neuconn/xcpd_pipeline_state.json`) can be:

| Value | Set by | Meaning |
|---|---|---|
| `not_started` | init / cancel (queued) | No active SLURM job |
| `queued` | `start_remote_xcpd_run` | SLURM job submitted; PENDING in queue |
| `running` | `refresh_xcpd_run` | SLURM job state is RUNNING |
| `completed` | `refresh_xcpd_run` | SLURM job state is COMPLETED |
| `failed` | `refresh_xcpd_run` | SLURM FAILED / DependencyNeverSatisfied |
| `cancelled` | `stop_xcpd_run` (running) | User called scancel on a RUNNING job |

`refresh_xcpd_run()` queries `squeue -j {job_id} -h -o '%T|%r'`. The pipeline cascades cancel
downstream: cancelling FC also scancels FC+GSR and EC if they are queued.

### SSH Port config

`hpc.port` (default `22`) controls the SSH port passed to `paramiko.SSHClient.connect()`.
For SSH tunnels (e.g. `ssh -p 2222 localhost`), set host to `localhost` and port to `2222` in **Settings → HPC Connection Settings**.

```yaml
hpc:
  host: localhost
  port: 2222
```

## Pipeline gates

`app.py:render_pipeline_gate_summary()` shows two independent groups in the sidebar:

- **fMRI gates** — FD approval, XCP-D QC approval, Subject-level outputs
- **dMRI gates** — QSIPrep outputs, Tractography QC (placeholder; full dMRI gate logic planned)

## HPC submission model

### fMRIPrep (array job)
`utils/hpc.py` `HPCWorkflowManager.generate_slurm_script()` renders `templates/fmriprep_slurm.j2` into a SLURM array job (one task per subject) and submits via `sbatch`.

### XCP-D (array job)
`utils/xcpd.py` `generate_xcpd_slurm_script()` renders `templates/xcpd_slurm.j2` into a **SLURM array job** (one task per subject). Each array task reads its subject ID from a subject-list file on the HPC and runs XCP-D inside Singularity for that single subject. Submission flow:

1. `generate_xcpd_slurm_script()` — Jinja2 renders template with bind mounts and `xcpd_arg_lines` (list of multiline args); CPUs = `nprocs × omp_nthreads`; `omit_work_dir=True` so the template adds `-w` at runtime
2. Script is saved locally to `pipeline_runs_dir/xcpd_{pipeline}/run_TIMESTAMP/xcpd_{pipeline}_job.sh`
3. A subject-list file (`sublist_xcpd_{pipeline}.txt`) is uploaded alongside the script
4. Script is uploaded to the HPC via `HPCConnection.write_file()`
5. `sbatch xcpd_{pipeline}_job.sh` is executed over SSH; submit-all launches FC, FC+GSR, and EC as independent jobs because they all consume fMRIPrep derivatives directly
6. The returned SLURM job ID is stored in run_info as `job_id`; a `remote_log_prefix` (e.g., `logs/xcpd_fc_4143`) is stored for log enumeration; initial status is **`queued`**
7. `refresh_xcpd_run()` polls `squeue -j {job_id} -h -o '%T|%r'` across all array tasks, prioritising status as RUNNING > COMPLETING > PENDING, and transitions accordingly
8. `stop_xcpd_run()` calls `scancel {job_id}` for the selected pipeline

#### Per-subject work directories

Each array task creates its own Nipype work directory at `{work_dir}/sub-{SUBID}` to prevent file-based lock contention between parallel tasks. `build_remote_xcpd_command()` accepts `omit_work_dir=True` so that the generated XCP-D argument list omits `-w`; the SLURM template then adds `-w "${WORK_DIR}"` at runtime after computing `WORK_DIR` from the array task's subject ID.

#### Array job log handling

SLURM produces per-task log files using `%A_%a` (array job ID + task index), e.g., `xcpd_fc_4143_1.out`, `xcpd_fc_4143_2.out`, etc. The run_info stores a `remote_log_prefix` (e.g., `logs/xcpd_fc_4143`) and a `remote_sublist` path. Log collection and cleanup use `find -name '{prefix}.out' -o -name '{prefix}.err' -o -name '{prefix}_*.out' -o -name '{prefix}_*.err'` to enumerate only the relevant files without accidentally matching logs from other jobs sharing a numeric prefix. `parse_xcpd_progress()` accepts `n_expected_tasks` to compute the correct total node count across all array tasks.

The SLURM template redirects all stdout/stderr to node-local `/tmp` at startup (`exec > /tmp/xcpd_...log 2>&1`). A `_cleanup()` EXIT trap copies the `/tmp` log to the NFS `logs/` directory when the task exits. This means:

- **During a run**: `.out` / `.err` files on NFS are 0 bytes (log lives in `/tmp`)
- **After a run**: `.log` files appear alongside `.out` / `.err` files (copied from `/tmp` by `_cleanup()`)

`fetch_hpc_xcpd_log()` matches both `.log` and `.out`/`.err` patterns. Cleanup removes all four file patterns.

#### NFS preflight (disk quota protection)

Before writing any output, the SLURM template executes a preflight write:

```bash
printf 'data' > "$OUTPUT_DIR/.nfs_preflight" && [ -s "$OUTPUT_DIR/.nfs_preflight" ]
```

This detects `EDQUOT` (NFS disk quota exceeded) reliably — `touch` succeeds even over quota but `printf + -s check` fails because data writes return `EDQUOT` silently. If the preflight fails the job exits immediately rather than producing 0-byte output files.

> **Disk quota note**: Each pipeline's Nipype work directory grows to ~10–15 GB per subject (~400 GB for 33 subjects). Run `🗑️ Clean up HPC files` between pipelines to free the work directory before submitting the next pipeline.

#### rsync download filter order

`download_xcpd_outputs_from_hpc()` uses rsync with explicit include/exclude rules. Rule ordering is critical: **first match wins**.

When `participant_labels` is provided, each subject generates `--include=sub-XXX/` + `--include=sub-XXX/**` rules, followed by shared includes (`logs/`, `sourcedata/atlases/`) and finally `--exclude=*` (strict allowlisting). Any `--include` rules placed after `--exclude=*` are dead code and have no effect. Use `--exclude=*` (not `--exclude=*/`) to block both unmatched files and unmatched directories.

The subprocess has a wall-clock timeout (7200 s) and rsync uses `--timeout=60` to abort if the connection is idle for 60 s. Full downloads without `participant_labels` can exceed 100 GB per pipeline; subject-filtered downloads are much smaller.

#### SLURM multiline rendering

The generated SLURM script renders each XCP-D CLI flag on its own line with `\` continuation for readability. `generate_xcpd_slurm_script()` builds `xcpd_arg_lines: list[str]` by parsing flags and their values into logical pairs/groups. The Jinja2 template (`xcpd_slurm.j2`) iterates the list with a `\` continuation on each line.

### Atlas catalog (`utils/xcpd_atlases.py`)

XCP-D v26+ ships **16 built-in atlases** that require no `--datasets` flag. The catalog is defined in `XCPD_BUILTIN_ATLASES` (dict of `XCPDAtlasSpec` keyed by atlas ID). Custom project atlases are registered separately via `get_project_atlas_specs()`.

Key functions:
- `get_xcpd_atlas_catalog()` → dict of all 21 atlases (16 built-in + 5 custom)
- `recommended_xcpd_atlases()` → `["4S256Parcels", "4S456Parcels", "Glasser", "Gordon", "Tian"]`
- `all_builtin_atlas_ids()` → sorted list of 16 built-in IDs
- `format_xcpd_atlas_label(id)` → `"📦 4S256Parcels — ..."` (built-in) or `"🔧 LongevitySchaefer200 — ..."` (custom)
- `atlas_cli_dataset_args()` → returns `--datasets longevity=/path` only when custom atlases are selected

### Remove all XCP-D outputs

The **🗑️ Remove all XCP-D outputs** button (bottom of XCP-D Runs tab) uses `shutil.rmtree()` on local FC, FC+GSR, and EC output directories and resets pipeline state for all five steps (`xcpd_fc`, `xcpd_fc_gsr`, `xcpd_ec`, `post_xcpd_qc`, `qc_gate`). It does **not** affect HPC files (use **🗑️ Clean up HPC files** for that).

### Per-subject status files

After each XCP-D run, `_write_subject_status_files()` writes
`<xcpd_output_dir>/<sub>/status` with content `completed <ISO>` or `failed <ISO>`.
`get_xcpd_subject_status()` (in `utils/xcpd_qc.py`) reads these files first, with a fallback to detecting HTML reports.

Both templates initialize the module system identically (`/etc/profile.d/modules.sh`, then `module load singularity`).

## Settings page layout

The Settings page tabs are ordered to match the analysis workflow:

1. **Project** — name, description
2. **Paths** — local filesystem paths
3. **HPC Settings** — SSH connection (host + **port**), remote paths, SLURM defaults, XCP-D SLURM overrides
4. **Software / Images** — local and HPC Singularity image paths for all tools (side-by-side)
5. **Analysis Parameters** — sections ordered to match the pipeline:
   - fMRIPrep Settings
   - XCP-D Pipeline Settings
   - Connectivity Analysis Settings
   - Group Analysis Settings
   - External Tools
   - Effective Connectivity Methods
   - Study Design
6. **ROI Config**
7. **QC Profiles**
8. **Import/Export**

The "Software / Images" tab was separated from HPC Settings so local execution paths are equally visible and editable, independent of whether HPC is enabled.

## Important utility modules

| Module | Responsibility |
|---|---|
| `utils/bids.py` | dataset scanning, parameter detection, exclusion support |
| `utils/hpc.py` | SSH and SLURM workflow objects; `HPCConfig` dataclass (includes `port` field) |
| `utils/xcpd.py` | XCP-D local and HPC execution; SLURM script generation; status file writing |
| `utils/xcpd_atlases.py` | Atlas catalog (16 XCP-D built-in + custom project atlases); CLI arg builder |
| `utils/xcpd_qc.py` | XCP-D QC rendering helpers; `get_xcpd_subject_status()` |
| `utils/xcpd_outputs.py` | `XcpdDiscovery` + `XcpdOutputs` — enumerate XCP-D derivative files (ALFF, ReHo, timeseries, relmat) per pipeline/atlas/subject |
| `utils/seed_catalog.py` | `SeedCatalog` — now built on XCP-D atlas parcels; merges `xcpd_atlas_parcel`, `custom_nifti_roi`, and `sphere` seed sources |
| `utils/connectivity_workflow.py` | `ConnectivityWorkflowManager` — submission tracking for all connectivity stages; emits `--analysis seed\|network --pipeline <p> --measures …`; state at `<bids_parent>/.neuconn/connectivity_workflow_state.json` |
| `utils/connectivity_viewer.py` | Viewer helpers — load relmat/zmap outputs from the new derivatives tree |
| `utils/image_cache.py` | cached QC-image lifecycle |
| `utils/qa_image_generator.py` | image generation used by both app and CLI-style workflows |
| `utils/pipeline_state.py` | pipeline gate summaries and state loading |

## XCP-D pipeline parameter rationale

Three pipelines run through XCP-D to support both functional connectivity (FC) analysis and effective connectivity (EC) modelling.

| Parameter | `fc` | `fc_gsr` | `ec` | Rationale |
|---|---|---|---|---|
| `nuisance_regressors` | `acompcor` | `36P` | `acompcor` | `acompcor` avoids GSR (controversial); `36P` includes GSR for comparison |
| `smoothing` | 6 mm | 6 mm | 0 mm | Smoothing boosts BOLD SNR for correlation-based FC; corrupts parcel-level temporal dynamics for EC |
| `low_pass` | 0.08 Hz | 0.08 Hz | 0.1 Hz | 0.08 Hz is the canonical BOLD FC band; wider band preserves temporal structure for EC |
| `fd_thresh` | 0.3 mm | 0.3 mm | 0.5 mm | FC tolerates censoring gaps; EC needs maximal data continuity |
| `min_time` | 240 s | 240 s | 300 s | EC models need longer epochs; 4 min is sufficient for FC matrix estimation |

**Shared settings (all pipelines):** `mode=linc`, `file_format=cifti`, `motion_filter_type=notch`, `band_stop_min=12`, `band_stop_max=18`, `high_pass=0.01`, `dummy_scans=auto`, `despike=True`, `bandpass_filter=True`, `head_radius=auto`, `min_coverage=0.5`.

**Why two FC pipelines?** Global Signal Regression (GSR) is disputed in the FC literature. It can inflate specificity of network-level correlations but also removes genuine neural signal and distorts negative correlations. The default `fc` pipeline uses `acompcor` (no GSR) as the conservative choice. The `fc_gsr` pipeline uses `36P` (which includes GSR) so researchers can directly compare GSR vs. no-GSR results for the same dataset.

### Config key notes
- `high_pass` / `low_pass` in config map to XCP-D CLI flags `--lower-bpf` / `--upper-bpf`. The old config names `lower_bpf` / `upper_bpf` are also accepted as fallbacks in `xcpd.py` for backward compatibility.
- Bandpass filtering is **on by default** in XCP-D. When `bandpass_filter=False`, the builder emits `--disable-bandpass-filter`. When `True` (the default), it emits `--lower-bpf` / `--upper-bpf` to set the cutoffs.
- `despike` is a boolean; emits `--despike` when `True`.
- `motion_filter_type=notch` is the correct XCP-D value for a band-stop (respiratory) filter. The old value `bandstop` is not recognised by XCP-D; valid choices are `notch`, `lp`, `none`.
- `--create-matrices` (the XCP-D flag for per-subject equal-length correlation windows) is only valid in `abcd`/`hbcd` modes, not `linc`. There is no equivalent for `linc` mode; the `correlation_lengths` config key is therefore unused and has been removed.

## Current state notes

- The app is strongest today in QC, configuration, and workflow support.
- Several pages still represent scaffolding or future work.
- DWI/structural connectivity pages (QSIPrep, QSIRecon) are planned; image path config placeholders and dMRI gate stubs are already in place.
- The README should stay honest about what is currently working versus planned.
