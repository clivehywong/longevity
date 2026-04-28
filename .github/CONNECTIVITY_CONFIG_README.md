# Connectivity Analysis Configuration

This directory contains the centralized configuration for the longevity study connectivity analysis pipeline.

## Files

- **`connectivity_config.yaml`** — Master configuration file defining atlases, seeds, preprocessing parameters, HPC job specs, and output structure
- **`../script/config_loader.py`** — Python module to load, validate, and query the configuration

## Overview

The configuration system prevents combinatorial explosion in HPC job submissions and ensures reproducible, unambiguous analysis across the project.

### The Problem

Without this configuration:
- 17 seeds × 2 atlases × ~88 sessions = **2,992 individual HPC jobs**
- Inconsistent output paths across the pipeline
- Manual synchronization of preprocessing parameters across scripts
- Risk of invalid seed-atlas combinations

### The Solution

With this configuration:
- **34 array jobs** (17 seeds × 2 atlases) — each processes all sessions
- **68 total submissions** (34 session-level + 34 group-level)
- Reproducible, deterministic output paths
- Single source of truth for preprocessing parameters
- Validated atlas-seed combinations

## Quick Start

### Loading Configuration in Python

```python
from script.config_loader import load_config

# Load the configuration
config = load_config()

# Get all valid seeds for an atlas
seeds = config.get_valid_seeds(atlas='DiFuMo256')

# Check if a seed-atlas combination is valid
if config.get_valid_combination('Motor_Cortex', 'DiFuMo256'):
    print("Valid combination!")

# Generate output path for results
output_path = config.get_output_path(
    analysis_type='seed_based',
    subject_id='033',
    session='01',
    atlas='DiFuMo256',
    seed='Motor_Cortex'
)
# Returns: results/seed_based/DiFuMo256/Motor_Cortex/sub-033_ses-01/
```

### Command-Line Interface

```bash
# Validate configuration
python script/config_loader.py --validate

# Print summary
python script/config_loader.py --summary

# List all seeds
python script/config_loader.py --seeds

# Get seeds for specific atlas
python script/config_loader.py --get-seeds DiFuMo256

# Check a combination
python script/config_loader.py --check-combo Motor_Cortex DiFuMo256

# Generate output path
python script/config_loader.py --output-path seed_based 033 01 DiFuMo256 Motor_Cortex
```

## Configuration Structure

### Atlases

Two atlases are defined with their properties:

- **DiFuMo256** — Deterministic Functional Unit Mapping (256 components)
  - Resolution: 2mm MNI space
  - Resting-state ICA, good for network connectivity

- **Schaefer400** — Schaefer 2018 (400 parcels)
  - Resolution: 2mm MNI space
  - Large-scale networks, suitable for between-network analysis

### Seeds (17 Total)

Organized by network:

#### Salience Network (3 seeds)
- `Anterior_Insula` — Core salience network hub
- `dACC` — Dorsal anterior cingulate cortex
- `Insula_dACC_Combined` — Full salience network hub

#### Default Mode Network (4 seeds)
- `Hippocampus` — Bilateral unified
- `Hippocampus_Anterior` — Memory encoding
- `Hippocampus_Posterior` — Spatial navigation
- `Default_Mode` — DMN core nodes (mPFC, PCC, TPJ)

#### Motor & Cerebellar (5 seeds)
- `Motor_Cortex` — Primary motor cortex
- `Cerebellar_Motor` — Motor cerebellum
- `Cerebellar_Cognitive_L` — Left cerebellar hemisphere
- `Cerebellar_Cognitive_R` — Right cerebellar hemisphere
- `Cerebellar_Cognitive_Bilateral` — Both cerebellar hemispheres
- `Cerebellar_Vestibular` — Balance and spatial orientation

#### Frontoparietal Control (5 seeds)
- `Frontoparietal_Control` — Task-positive network hub
- `DLPFC_Coarse` — Unified dorsolateral prefrontal cortex
- `DLPFC_Dorsal` — Dorsal dlPFC (working memory)
- `DLPFC_Ventral` — Ventral dlPFC (retrieval control)

### Valid Combinations

**All 17 seeds work with both atlases** (no restrictions).

Total valid combinations: **34** (17 × 2)

### Preprocessing Parameters

Standardized for all analyses:

```yaml
preprocessing:
  high_pass_hz: 0.01       # 100s cutoff
  low_pass_hz: 0.1         # 10s cutoff
  smoothing_fwhm_mm: 6.0   # 6mm Gaussian kernel
  tr_s: 0.8                # 0.8s repetition time
  volumes_expected: 480    # 6.4 minute runs
```

### HPC Configuration

#### Session-Level Jobs
- CPUs: 4 per task
- Memory: 16GB per seed
- Time: 6 hours
- Workers: 4 (joblib parallelization)

#### Group-Level Jobs
- CPUs: 8 per task
- Memory: 32GB per seed
- Permutations: 5,000 for statistics

### Output Structure

#### Session-Level
```
results/seed_based/{atlas}/{seed}/sub-{subject}_ses-{session}/
├── *_zmap.nii.gz           # Z-scored connectivity map
├── *_zmap_fdr.nii.gz       # FDR-corrected map
├── *_mask.nii.gz           # Seed mask
└── individual_maps.csv     # Metadata for group analysis
```

#### Group-Level
```
results/group_analysis/seed_based/{atlas}/{seed}/
├── cope1_mean.nii.gz       # Mean connectivity
├── cope1_zstat.nii.gz      # Z-statistic
├── cope1_tstat.nii.gz      # T-statistic
├── mask.nii.gz             # Analysis mask
└── thresh_zstat1.nii.gz    # Thresholded map
```

## API Reference

### `config_loader.py` Functions

#### `load_config(config_path=None) -> ConnectivityConfig`

Load and validate configuration.

```python
config = load_config()  # Searches for config automatically
config = load_config('/path/to/connectivity_config.yaml')
```

#### `config.get_atlases() -> Dict[str, Dict]`

Get all atlas definitions.

#### `config.get_atlas(atlas_name: str) -> Dict`

Get specific atlas definition.

```python
difumo = config.get_atlas('DiFuMo256')
```

#### `config.get_valid_seeds(atlas=None, network=None) -> List[str]`

Get valid seeds, optionally filtered by atlas or network.

```python
# All seeds
all_seeds = config.get_valid_seeds()

# Seeds for specific atlas
difumo_seeds = config.get_valid_seeds(atlas='DiFuMo256')

# Seeds in network
motor_seeds = config.get_valid_seeds(network='Motor')

# Seeds in network for atlas
motor_difumo = config.get_valid_seeds(atlas='DiFuMo256', network='Motor')
```

#### `config.get_valid_combination(seed: str, atlas: str) -> bool`

Check if seed-atlas combination is valid.

```python
if config.get_valid_combination('Motor_Cortex', 'DiFuMo256'):
    print("Valid!")
```

#### `config.get_output_path(analysis_type, subject_id=None, session=None, atlas=None, seed=None, level='session') -> str`

Generate output path for analysis results.

```python
# Session-level path
path = config.get_output_path(
    analysis_type='seed_based',
    subject_id='033',
    session='01',
    atlas='DiFuMo256',
    seed='Motor_Cortex'
)
# Returns: results/seed_based/DiFuMo256/Motor_Cortex/sub-033_ses-01/

# Group-level path
path = config.get_output_path(
    analysis_type='seed_based',
    atlas='DiFuMo256',
    seed='Motor_Cortex',
    level='group'
)
# Returns: results/group_analysis/seed_based/DiFuMo256/Motor_Cortex/
```

#### `config.get_preprocessing() -> Dict`

Get preprocessing parameters.

```python
preproc = config.get_preprocessing()
high_pass = preproc['high_pass_hz']  # 0.01
low_pass = preproc['low_pass_hz']    # 0.1
```

#### `config.get_hpc() -> Dict`

Get HPC configuration.

```python
hpc = config.get_hpc()
cpus = hpc['session_level']['cpus_per_task']  # 4
mem = hpc['session_level']['mem_per_seed']    # '16G'
```

#### `config.validate_config(config_path=None) -> Tuple[bool, List[str]]`

Validate configuration file.

```python
is_valid, errors = validate_config()
if not is_valid:
    for error in errors:
        print(error)
```

#### `config.print_summary()`

Print human-readable configuration summary.

```python
config.print_summary()
```

## Usage Examples

### Example 1: List all seeds for a connectivity analysis

```python
from script.config_loader import load_config

config = load_config()
seeds = config.get_valid_seeds(atlas='DiFuMo256')
print(f"Processing {len(seeds)} seeds with DiFuMo256")
for seed in seeds:
    print(f"  • {seed}")
```

### Example 2: Batch job submission

```python
from script.config_loader import load_config
import subprocess

config = load_config()

# Submit array job for each seed
for seed in config.get_valid_seeds(atlas='DiFuMo256'):
    output_dir = config.get_output_path(
        analysis_type='seed_based',
        atlas='DiFuMo256',
        seed=seed,
        level='session'
    )
    
    # Create output directory
    import os
    os.makedirs(output_dir, exist_ok=True)
    
    # Submit job
    job_cmd = f"sbatch --export=SEED={seed} script/hpc_seed_connectivity.sh"
    print(f"Submitting: {job_cmd}")
    # subprocess.run(job_cmd, shell=True)
```

### Example 3: Validate analysis completeness

```python
from script.config_loader import load_config
from pathlib import Path
import json

config = load_config()

# Check which subject-seed-atlas combinations are complete
completed = {}
for subject in range(33, 83):
    subject_id = f"{subject:03d}"
    for session in ['01', '02']:
        for atlas in config.get_atlases():
            for seed in config.get_valid_seeds(atlas=atlas):
                path = config.get_output_path(
                    analysis_type='seed_based',
                    subject_id=subject_id,
                    session=session,
                    atlas=atlas,
                    seed=seed
                )
                zmapfile = Path(path) / f"sub-{subject_id}_ses-{session}_zmap.nii.gz"
                if zmapfile.exists():
                    completed[(subject_id, session, atlas, seed)] = True

print(f"Completed: {len(completed)} / {len(config.get_valid_seeds()) * 2 * 50} combinations")
```

## Integration with Scripts

### Using config_loader in HPC scripts

```bash
#!/bin/bash
# hpc_seed_connectivity.sh

# Load config
python3 << EOF
from script.config_loader import load_config
config = load_config()
seeds = config.get_valid_seeds(atlas='DiFuMo256')
for seed in seeds:
    print(seed)
EOF
```

### Using config in Python analysis scripts

```python
#!/usr/bin/env python3
from script.config_loader import load_config
from pathlib import Path

config = load_config()

# Get preprocessing parameters
preproc = config.get_preprocessing()
high_pass = preproc['high_pass_hz']
low_pass = preproc['low_pass_hz']

# Generate output path
output_dir = config.get_output_path(
    analysis_type='seed_based',
    subject_id='033',
    session='01',
    atlas='DiFuMo256',
    seed='Motor_Cortex'
)

# Ensure directory exists
Path(output_dir).mkdir(parents=True, exist_ok=True)

# Run analysis
print(f"Processing: seed=Motor_Cortex, atlas=DiFuMo256")
print(f"High-pass: {high_pass} Hz")
print(f"Low-pass: {low_pass} Hz")
print(f"Output: {output_dir}")
```

## Maintenance

### Adding a New Seed

1. Open `connectivity_config.yaml`
2. Add to `seeds:` section:

```yaml
NewSeed:
  region: "Description of region"
  description: "Brief description"
  coordinates_mni: [x, y, z]
  radius_mm: 10
  brain_regions: ["Primary_Region"]
  networks: ["NetworkName"]
  valid_atlases: [DiFuMo256, Schaefer400]
  notes: "Optional notes"
```

3. If not valid for all atlases, update `valid_combinations:` section
4. Validate: `python script/config_loader.py --validate`

### Adding a New Atlas

1. Open `connectivity_config.yaml`
2. Add to `atlases:` section:

```yaml
NewAtlas:
  name: "Full name"
  n_rois: 100  # or n_components for ICA
  space: MNI152NLin2009cAsym
  resolution_mm: 2
  description: "..."
  filepath: "path/to/atlas.nii.gz"
```

3. Update seed definitions if only valid for some seeds
4. Validate: `python script/config_loader.py --validate`

## Validation

Run validation checks:

```bash
# Validate configuration syntax
python script/config_loader.py --validate

# Run comprehensive tests
cd script && python -m pytest config_loader_test.py  # (if test file exists)
```

## Troubleshooting

### Configuration not found

```
ConfigLoadError: Config file not found...
```

Ensure `connectivity_config.yaml` is in `.github/` directory relative to project root.

### Invalid combination

```python
# This will return False:
config.get_valid_combination('UnknownSeed', 'DiFuMo256')

# Check valid seeds:
config.get_valid_seeds(atlas='DiFuMo256')
```

### YAML parsing error

```
ConfigLoadError: Invalid YAML...
```

Check YAML syntax. Common issues:
- Incorrect indentation (use spaces, not tabs)
- Missing colons after keys
- Unclosed brackets

## References

- **fMRIPrep**: Esteban et al. (2019). Nature Methods.
- **DiFuMo Atlas**: Dadi et al. (2020). NeuroImage.
- **Schaefer Atlas**: Schaefer et al. (2018). Cerebral Cortex.

---

**Last Updated**: 2025-04-24
**Version**: 1.0
