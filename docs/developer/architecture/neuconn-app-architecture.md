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
| `templates/` | SLURM Jinja2 templates (`fmriprep_slurm.j2`, `xcpd_slurm.j2`) |

## Config model

- Defaults start in `config/default_config.yaml`.
- User/project overrides come from `~/neuconn_projects/<project>.yaml`.
- `utils/config.py` expands `${var}` references and `~`, merges configs, and hydrates derived defaults.
- `config.py` (the project facade) adds higher-level derived defaults on top of the raw YAML.

### Software / Singularity image config

All external tool image paths are stored in two parallel config sections:

| Section | Used for |
|---|---|
| `software.singularity_images` | **Local** execution on the machine running the app |
| `hpc.singularity_images` | **Remote** execution on the HPC cluster |

Both sections cover: `fmriprep`, `xcp_d`, `fmripost_aroma`, `qsiprep`, `qsirecon`, `freesurfer_license`.

`software.singularity_bind_mounts` lists local directories to bind-mount into the container.

The legacy `xcpd.singularity_image_path` key is kept for backward compatibility; `software.singularity_images.xcp_d` takes precedence when set.

`qsiprep` and `qsirecon` are present as empty placeholders ready for future DWI/structural connectivity pages.

### SLURM resource config

XCP-D SLURM job resources can be overridden separately from the fMRIPrep defaults:

```yaml
hpc:
  slurm:
    # fMRIPrep defaults (also used for XCP-D if overrides are absent)
    default_cpus: 8
    default_memory: "32GB"
    default_time: "24:00:00"
    # XCP-D-specific overrides (0/"" = fall back to defaults above)
    xcpd_cpus: 16
    xcpd_memory: "64GB"
    xcpd_time: "12:00:00"
```

## HPC submission model

### fMRIPrep (array job)
`utils/hpc.py` `HPCWorkflowManager.generate_slurm_script()` renders `templates/fmriprep_slurm.j2` into a SLURM array job (one task per subject) and submits via `sbatch`.

### XCP-D (single job)
`utils/xcpd.py` `generate_xcpd_slurm_script()` renders `templates/xcpd_slurm.j2` into a **single** SLURM job (XCP-D processes all subjects in one `singularity run` invocation). Submission flow:

1. `generate_xcpd_slurm_script()` — Jinja2 renders template with bind mounts and xcpd_args
2. Script is saved locally to `run_dir/xcpd_{pipeline}_job.sh` for inspection
3. Script is uploaded to the HPC via `HPCConnection.write_file()`
4. `sbatch xcpd_{pipeline}_job.sh` is executed over SSH
5. The returned SLURM job ID is stored in run_info as `job_id`
6. `refresh_xcpd_run()` polls `squeue`/`sacct` to update status
7. `stop_xcpd_run()` calls `scancel {job_id}`

Both templates initialize the module system identically (`/etc/profile.d/modules.sh`, then `module load singularity`).

## Settings page layout

The Settings page tabs are ordered to match the analysis workflow:

1. **Project** — name, description
2. **Paths** — local filesystem paths
3. **HPC Settings** — SSH connection, remote paths, SLURM defaults, XCP-D SLURM overrides
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
| `utils/hpc.py` | SSH and SLURM workflow objects; `HPCConfig` dataclass |
| `utils/xcpd.py` | XCP-D local and HPC execution; SLURM script generation |
| `utils/qc_database.py` | QC persistence helpers |
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
| `correlation_lengths` | 300 s | 300 s | — | Equalises data contribution per participant for FC matrices; not applicable to EC |
| `min_time` | 240 s | 240 s | 300 s | EC models need longer epochs; 4 min is sufficient for FC matrix estimation |

**Shared settings (all pipelines):** `mode=linc`, `file_format=cifti`, `motion_filter_type=bandstop`, `band_stop_min=12`, `band_stop_max=18`, `high_pass=0.01`, `dummy_scans=auto`, `despike=True`, `bandpass_filter=True`, `head_radius=auto`, `min_coverage=0.5`.

**Why two FC pipelines?** Global Signal Regression (GSR) is disputed in the FC literature. It can inflate specificity of network-level correlations but also removes genuine neural signal and distorts negative correlations. The default `fc` pipeline uses `acompcor` (no GSR) as the conservative choice. The `fc_gsr` pipeline uses `36P` (which includes GSR) so researchers can directly compare GSR vs. no-GSR results for the same dataset.

### Config key notes
- `high_pass` / `low_pass` map to XCP-D CLI flags `--high-pass` / `--low-pass` (XCP-D ≥ 0.6). The old names `lower_bpf` / `upper_bpf` are recognised as fallbacks in `xcpd.py` command builders but are deprecated.
- `correlation_lengths` is only emitted by the command builder if the config key is present and non-empty; the `ec` pipeline omits it.
- `despike` and `bandpass_filter` are boolean flags; they emit `--despike` / `--bandpass-filter` only when `True`.


- The app is strongest today in QC, configuration, and workflow support.
- Several pages still represent scaffolding or future work.
- DWI/structural connectivity pages (QSIPrep, QSIRecon) are planned; image path config placeholders are already in place.
- The README should stay honest about what is currently working versus planned.
