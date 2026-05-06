# AGENTS.md — Authoritative Agent & Developer Conventions

> This file is the single source of truth for AI coding agents (Claude Code, GitHub Copilot, etc.)
> and human developers working in this repository.

---

## 1. Root Directory Discipline

### Allowed root-level files (whitelist)

Only these files may exist at the repository root:

| File | Purpose |
|------|---------|
| `AGENTS.md` | Agent/developer conventions (this file) |
| `CLAUDE.md` | Thin pointer to AGENTS.md for Claude Code |
| `QUICK_START.md` | User-facing navigation entry point |
| `pytest.ini` | Pytest configuration |
| `.gitignore` | Git ignore rules |

**Note**: Study metadata is in `bids/participants.tsv` (BIDS standard). Root files `.coverage` and `qc_status.json` are gitignored.

### Hard rules

- **NO** new `.md`, `.py`, `.sh`, `.csv`, `.txt`, or any other files at root without updating this whitelist.
- All scripts → `script/` (permanent) or `tmp/scripts/` (session-only)
- All documentation → `docs/`
- All test code → `tests/`
- All app code → `neuconn_app/`
- All temporary/session artifacts → `tmp/` (gitignored)
- Delivery summaries, implementation notes, changelogs → `docs/archive/delivery-notes/`

### Where things go

| Content type | Location | Tracked? |
|---|---|---|
| Permanent analysis scripts | `script/` | ✓ |
| Streamlit app code | `neuconn_app/` | ✓ |
| Unit/integration tests | `tests/` | ✓ |
| End-to-end tests | `tests/e2e/` | ✓ |
| User documentation | `docs/user/` | ✓ |
| Developer documentation | `docs/developer/` | ✓ |
| Historical/archived docs | `docs/archive/` | ✓ |
| Session helpers (ephemeral) | `tmp/scripts/` | ✗ |
| Test result screenshots | `docs/test-results/{type}-{date}/images/` | ✗ |
| GitHub workflows/config | `.github/` | ✓ |

---

## 2. End-to-End Testing Standards (Playwright)

### Mandatory configuration

- **Framework**: Python Playwright via `pytest-playwright`
- **Mode**: Headless (`headless=True`) — always
- **Viewport**: `1920 × 1080` — no compromise, no workaround
- **Browser**: Chromium (default)

### Screenshot policy

- Screenshots are taken on test failure automatically.
- **If screenshot capture fails, STOP and REPORT the error.** Do NOT work around it, do NOT continue, do NOT substitute with alternative approaches. This applies even in autopilot/unattended mode.

### File locations

| Artifact | Path |
|---|---|
| Test code | `tests/e2e/` |
| Shared fixtures | `tests/e2e/conftest.py` |
| Screenshots (gitignored) | `docs/test-results/{test-name}-{date}/images/` |

### Conftest fixture (reference)

```python
@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Fixed 1920×1080 viewport for all E2E tests — no compromise."""
    return {
        **browser_context_args,
        "viewport": {"width": 1920, "height": 1080},
    }
```

### Forbidden

- No TypeScript/Node.js Playwright (`playwright.config.ts`, `package.json` for Playwright)
- No viewport sizes other than 1920×1080
- No `headless=False` in committed code
- No workarounds for screenshot failures

---

## 3. HPC Configuration Standards

### Single source of truth

All HPC connection details are read from the project YAML config:
- **Project config**: `neuconn_app/config/longevity_config.yaml`
- **Default fallback**: `neuconn_app/config/default_config.yaml`
- **Runtime precedence**: `default_config.yaml` → project config → runtime overrides

### Zero hardcoding

- **No hardcoded hostnames** (e.g., `hpclogin1.eduhk.hk`) in `.py` or `.sh` code
- **No hardcoded ports** (e.g., `2222`) in application code
- **No hardcoded paths** (e.g., `/home/clivewong/...`) in application code
- **No hardcoded usernames** in application code

### Pattern

```python
from utils.hpc import HPCConfig
hpc_config = HPCConfig.from_config(config)  # single source
```

Remote paths use `${base}` variable expansion defined in config:
```yaml
hpc:
  remote_paths:
    base: "/home/username/project"
    bids: "${base}/bids"
    work: "${base}/work"
```

### Exception

- The `longevity_config.yaml` file itself is the one place where concrete values live.
- Scripts in `script/` may accept `--bids-root` arguments but must NOT hardcode defaults.

---

## 4. HPC Module Architecture (Dashboard + 5 Subpages)

### Required structure

Every preprocessing pipeline module (fMRIPrep, XCP-D, QSIPrep/QSIRecon, future pipelines) **MUST** implement these pages:

| # | Page | Purpose |
|---|------|---------|
| 00 | **Dashboard** | Per-subject/session traffic-light completion table |
| 01 | **Upload** | Selective transfer of required inputs to HPC |
| 02 | **Processing** | SLURM script generation + job submission |
| 03 | **Monitoring** | Job status polling, progress visualization |
| 04 | **Download** | Retrieve results with integrity verification |
| 05 | **Cleanup** | Remove remote working data after successful download |

Some pages may be combined where appropriate (e.g., Upload + Processing + Monitoring in a single workflow page with tabs/steps), but all five functions must be accessible.

### Dashboard conventions

- File naming: `00_<modality>_dashboard.py`
- Status indicators: ⚪ not started · 🔄 in progress · ✅ completed · ❌ failed
- "Rescan" button to re-read output directories on demand
- Summary metrics row (total subjects, per-step completion counts)
- Filter by completion status (All, Incomplete, Failed)
- Cache in `st.session_state` — NO expensive scans on every rerun

### Reference implementations

- **Dashboard**: `neuconn_app/pages_fmri/preprocessing/00_fmri_dashboard.py`
- **HPC workflow**: `neuconn_app/pages_fmri/preprocessing/01_hpc_submit.py`

### State persistence

- Workflow state: `<bids_parent>/.neuconn/hpc_workflow_state.json`
- Pattern: `WorkflowState` dataclass with `to_dict()` / `from_dict()` serialization

---

## 5. Analysis Output Path Structure

### Principle

All connectivity analysis outputs are organized by:
1. **Preprocessing pipeline** (`fc`, `fc_gsr`, `ec`) — which XCP-D denoising variant
2. **Atlas** (e.g., `4S256Parcels`, `Schaefer400`)
3. **Seed** (for seed-based) or **network** (for network-level)

### Subject-level seed-to-whole-brain

```
derivatives/connectivity/<pipeline>/<atlas>/<seed>/sub-<ID>/ses-<session>/
    *_zmap.nii.gz           # Fisher z-transformed correlation map
    *_mask.nii.gz           # Seed mask used
    metadata.json           # Processing parameters
```

### Group-level seed-to-whole-brain

Group outputs use an extra **model** layer so different statistical approaches live in separate sibling folders:

```
derivatives/connectivity/<pipeline>/group/seed/<seed>/measure-<measure>/
│
├── 2x2_mixed/                  # 2×2 mixed ANOVA (group × session)
│   ├── randomise_outputs/      # FSL randomise results (TFCE / GRF / FDR corrp maps)
│   ├── randomise_logs/
│   └── lmm_outputs/            # Parametric LMM fast-path results
│
└── delta/                      # Post−Pre delta contrast
    ├── delta_maps/             # Per-subject delta (ses-02 − ses-01) NIfTIs
    ├── randomise_outputs/      # FSL randomise on stacked delta maps
    └── randomise_logs/
```

For ALFF / ReHo (no seed sub-level):
```
derivatives/connectivity/<pipeline>/group/alff/
└── 2x2_mixed/
    └── lmm_outputs/
```

New model types (e.g. `longitudinal/`, `covariate_age/`) should be added as additional siblings at the same level as `2x2_mixed/` and `delta/`.

### Network connectivity (atlas-based)

```
derivatives/connectivity/<pipeline>/<atlas>/network/sub-<ID>/ses-<session>/
    connectivity_matrix.h5  # Full ROI×ROI matrix
    network_stats.csv       # Network-level summary statistics

derivatives/connectivity/<pipeline>/<atlas>/network/group/
    group_matrix.h5         # Group-level connectivity matrices
    group_stats.csv         # Statistical comparisons
```

### Key: networks are defined by predefined atlases (sets of ROIs), NOT individual seeds.

---

## 6. Analysis Conventions

### XCP-D and confound regression

**XCP-D has already regressed out confounds.** The denoised BOLD timeseries from XCP-D output are clean. Therefore:

- Do **NOT** re-include motion regressors, aCompCor, or any noise regressors in subsequent seed-based or network connectivity analyses.
- The only post-XCP-D processing allowed: bandpass filtering (if not already done by XCP-D variant), spatial smoothing, and the connectivity computation itself.

### Brain mask for voxelwise analyses

**All whole-brain voxelwise analyses MUST apply a dilated MNI brain mask** to reduce the number of voxels computed:

- Mask: `atlases/MNI152_T1_2mm_brain_mask_dil.nii.gz`
- This is FSL's MNI152NLin6Asym 2mm dilated brain mask (slightly larger than the standard mask to include cortical surface voxels)
- Apply before computing connectivity maps and before group statistics

### Statistical conventions

- Fisher-z transform applied to Pearson/Spearman correlation maps before group statistics
- 8 connectivity measures available in `script/connectivity_measures.py`: pearson, spearman, partial_correlation, plv, wpli, coherence, amplitude_envelope_correlation, mutual_information
- Group statistics: FSL `randomise` with TFCE correction (5000 permutations default)

### Connectivity config

Central configuration: `.github/connectivity_config.yaml`
- 2 atlases: DiFuMo256, Schaefer400
- 17 priority seeds across 5 networks
- HPC job specifications
- Output path patterns

---

## 7. Project Structure Overview

```
longevity/
├── AGENTS.md              # This file (conventions)
├── CLAUDE.md              # Thin pointer for Claude Code
├── QUICK_START.md         # User navigation entry point
├── group.csv              # Study design metadata
├── pytest.ini             # Test configuration
│
├── bids/                  # BIDS raw data (sub-033 to sub-082)
├── derivatives/           # All analysis outputs
│   ├── preprocessing/     # fMRIPrep, XCP-D, QSIPrep outputs
│   ├── connectivity/      # Seed/network connectivity (by pipeline/atlas/seed)
│   ├── qc/                # Quality control reports
│   └── pipeline_runs/     # Run logs and manifests
│
├── script/                # Permanent analysis scripts
├── neuconn_app/           # Streamlit application
│   ├── app.py             # Main entry point
│   ├── config/            # YAML configs (default + project-specific)
│   ├── pages_fmri/        # fMRI pipeline pages
│   ├── pages_dmri/        # dMRI pipeline pages
│   ├── pages_general_qc/  # General QC pages
│   ├── pages_connectivity/ # Connectivity visualization
│   ├── pages_connectivity_submit/  # HPC submission pages
│   ├── pages_settings/    # Settings/configuration
│   ├── utils/             # Shared utilities
│   └── scripts/           # App-bundled analysis scripts
│
├── tests/                 # All test code
│   ├── e2e/               # End-to-end Playwright tests
│   └── archive/           # Historical/exploratory test scripts
│
├── docs/                  # Documentation
│   ├── user/              # User-facing guides
│   ├── developer/         # Developer architecture docs
│   ├── archive/           # Historical notes
│   └── test-results/      # Test execution reports (gitignored images)
│
├── atlases/               # Brain atlas files
├── tmp/                   # Session-only artifacts (gitignored)
│   └── scripts/           # Temporary helper scripts
│
└── .github/               # GitHub config
    ├── connectivity_config.yaml  # Analysis parameters
    ├── workflows/         # CI/CD
    └── extensions/        # Copilot extensions/skills
```

---

## 8. App Architecture

- Entry point: `neuconn_app/app.py`
- Routing: Custom hierarchical sidebar (NOT Streamlit default multipage)
- Page loading: `importlib.util` dynamic import calling `render()` function
- Page naming: `{NN}_{name}.py` where NN controls navigation order
- Session state prefixes per page family (see section 10)

### Page module contract

Every page module MUST expose:
```python
def render() -> None:
    """Main entry point called by app.py dynamic loader."""
    ...

if __name__ == "__main__":
    render()
```

---

## 9. Configuration & Environment

### Config precedence

1. `neuconn_app/config/default_config.yaml` (universal fallback)
2. `neuconn_app/config/longevity_config.yaml` (project-specific)
3. `~/neuconn_projects/<project>.yaml` (user-level overrides)
4. Runtime overrides (CLI arguments)

### Path expansion

Config values support:
- `~` expansion (home directory)
- `${var}` references (cross-referencing other config keys)

Preserve this behavior — never flatten derived paths into hardcoded strings.

### State locations

| State | Location |
|---|---|
| User config | `~/neuconn_projects/<project>.yaml` |
| QC status | `<bids_parent>/derivatives/qc/qc_status.json` (legacy fallback: `<bids_parent>/qc_status.json`) |
| Exclusion files | sibling `bids_excluded/` |
| HPC workflow state | `<bids_parent>/.neuconn/hpc_workflow_state.json` |
| QC image cache | `<bids>/derivatives/qc_images/` |

---

## 10. Session State Conventions

Connectivity submit pages use per-page key prefixes:

| Page | Prefix |
|---|---|
| Submit Local Measures | `submit_local_` |
| Submit Seed Connectivity | `submit_seed_` |
| Submit Network Connectivity | `submit_network_` |
| Submit Group Stats | `submit_group_` |

Always use these prefixes when adding new state keys in `pages_connectivity_submit/`.

---

## 11. Git Commit Practices

### Required trailer

```
Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

### Message format

- Imperative mood ("Add feature" not "Added feature")
- First line ≤ 50 characters
- Detailed explanation after blank line if needed

### What to commit

- ✓ Code in `script/`, `neuconn_app/`, `tests/`, `docs/`
- ✓ Configuration changes
- ✗ Never: `tmp/`, `*.log`, `*.pid`, `*.out`, screenshots

---

## 12. Data Acquisition Details

- **Study**: Longitudinal walking intervention, resting-state fMRI
- **Site**: HKBU, 3T Siemens MAGNETOM Prisma
- **TR**: 0.8s | **Volumes**: 480 | **Duration**: 6.4 min
- **T1w**: 0.9mm isotropic MPRAGE, 2 runs per session
- **Subjects**: 44 total (40 longitudinal with 2 sessions)
- **Output spaces**: MNI152NLin2009cAsym:res-2 (primary), T1w

---

## 13. Essential Commands

```bash
# Validate BIDS structure
python script/validate_bids_names.py bids/

# Run the Streamlit app
cd neuconn_app && streamlit run app.py

# Lightweight CLI smoke test
cd neuconn_app && python test_cli.py

# Connectivity analysis (XCP-D-driven, --bids-root = project root)
python script/compute_seed_connectivity_xcpd.py \
    --bids-root . --pipeline fc --atlas 4S256Parcels --measures pearson
python script/compute_network_connectivity_xcpd.py \
    --bids-root . --pipeline fc --atlas 4S256Parcels --measures pearson

# Group statistics
python script/group_voxel_stats_xcpd.py --bids-root . --pipeline fc
python script/group_matrix_stats.py --bids-root . --pipeline fc

# End-to-end tests (Python Playwright)
pytest tests/e2e/ --headed  # for debugging only; CI uses headless
```

---

## 14. Common Pitfalls

### ❌ Don't

1. Create files at repository root (use proper directories)
2. Hardcode HPC paths/hosts in application code (use config)
3. Re-regress confounds after XCP-D processing
4. Run voxelwise analyses without the dilated MNI mask
5. Use Node.js Playwright (use Python pytest-playwright)
6. Use viewports other than 1920×1080 for E2E tests
7. Work around screenshot failures (stop and report)
8. Skip the dashboard page for new preprocessing modules

### ✓ Do

1. Follow the whitelist for root-level files
2. Read all HPC connection details from config
3. Implement all 6 pages (dashboard + 5 workflow) for HPC modules
4. Apply dilated MNI mask for all whole-brain analyses
5. Use Fisher-z before group statistics on correlation maps
6. Organize outputs by `pipeline/atlas/seed` hierarchy
7. Cache dashboard scans in session_state with explicit Rescan button
