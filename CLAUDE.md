# CLAUDE.md

This file provides guidance to Claude Code when working with this neuroimaging research project.

## Overview

Longitudinal walking intervention study with resting-state fMRI. Data acquired at HKBU on 3T Siemens MAGNETOM Prisma, stored in BIDS format.

## Key Directories

```
longevity/
├── bids/                # BIDS-formatted raw data (sub-033 to sub-082)
├── fmriprep/            # Preprocessed outputs (MNI 2mm + T1w space)
├── atlases/             # DiFuMo 256, Schaefer 400 parcellations
├── script/              # Analysis scripts (Python/Bash)
├── docs/                # Documentation (guides, archived files)
├── .claude/memory/      # Persistent context for Claude
└── neuconn_app/         # Streamlit QC & analysis app (in development)
```

## Current Status

- **BIDS**: 44 subjects, 40 longitudinal (2 sessions each)
- **fMRIPrep**: Subset preprocessed, check fmriprep/ for current status
- **App**: NeuConn Streamlit app in development (see blueprint in .claude/plans/)

## Essential Commands

```bash
# Validate BIDS
python script/validate_bids_names.py bids/

# Generate QA report
python script/qa_check_images.py bids/ qa_images_full/

# HPC fMRIPrep submission (selective upload, auto-cleanup)
bash script/batch_fmriprep.sh

# Connectivity analysis
bash script/master_full_connectivity_workflow.sh --test
```

## Documentation

- **Quick Start**: `QUICK_START.md` - top-level navigation into the current docs hierarchy
- **User Docs**: `docs/user/README.md` - setup, workflows, troubleshooting, and parameter guidance
- **Developer Docs**: `docs/developer/README.md` - architecture, repository structure, and maintenance notes
- **Memory**: `.claude/memory/` - HPC config, analysis parameters

## Claude Code Usage

### Use Subagents to Reduce Context Window

**Always use subagents** for tasks requiring multiple file reads or searches:

- **Explore agent**: Codebase exploration, pattern finding, file searches
- **Plan agent**: Design implementation approaches before coding

```python
# Example: Find all connectivity-related scripts
Agent(subagent_type="Explore", prompt="Find all seed connectivity scripts...")
```

### When to Use Subagents

- Searching for files/patterns (>3 queries)
- Understanding multi-file features
- Designing implementations
- Any task that would read >5 files

**Launch agents in parallel** when tasks are independent (single message, multiple Agent calls).

---

## Data Acquisition Details

- **TR**: 0.8s | **Volumes**: 480 | **Task**: resting-state
- **T1w**: 0.9mm isotropic MPRAGE, 2 runs per session
- **Output spaces**: MNI152NLin2009cAsym:res-2 (primary), T1w

## Known Issues

Check app dynamically for current issues. Historical issues (may be resolved):
- sub-058/ses-01: Missing T1w run-02
- sub-057/ses-02: 460 volumes (not 480)

---

**For detailed guides**, see `docs/`. **For project context**, see `.claude/memory/`. **For app development**, see `.claude/plans/moonlit-yawning-curry.md`.
