# Connectivity Configuration - Quick Start

## Overview

This configuration system prevents HPC job explosion and ensures reproducible analysis:

- **2,992 individual jobs → 68 array jobs** (97.7% reduction)
- **17 seeds × 2 atlases = 34 valid combinations**
- **Deterministic, unambiguous output paths**
- **Single source of truth for all parameters**

## Files

| File | Purpose | Size |
|------|---------|------|
| `.github/connectivity_config.yaml` | Master configuration (atlases, seeds, HPC specs) | 19KB |
| `script/config_loader.py` | Python module + CLI | 21KB |
| `.github/CONNECTIVITY_CONFIG_README.md` | Full documentation | 13KB |
| `.github/CONFIGURATION_QUICK_START.md` | This file | - |

## 5-Minute Setup

### 1. Validate Configuration
```bash
python script/config_loader.py --validate
```

### 2. Load in Python
```python
from script.config_loader import load_config

config = load_config()
seeds = config.get_valid_seeds(atlas='DiFuMo256')
```

### 3. Generate Output Paths
```python
path = config.get_output_path(
    analysis_type='seed_based',
    subject_id='033',
    session='01',
    atlas='DiFuMo256',
    seed='Motor_Cortex'
)
# Returns: results/seed_based/DiFuMo256/Motor_Cortex/sub-033_ses-01/
```

## Configuration Contents

### Atlases (2)
- **DiFuMo256** — 256 components, ICA-based, good for networks
- **Schaefer400** — 400 parcels, anatomically-guided networks

### Seeds (17)
Organized by 5 networks:

**Salience** (3): Anterior_Insula, dACC, Insula_dACC_Combined
**Motor** (2): Motor_Cortex, Cerebellar_Motor
**Cerebellar** (4): Cognitive_L, Cognitive_R, Cognitive_Bilateral, Vestibular
**DefaultMode** (4): Hippocampus, Hippocampus_Anterior, Hippocampus_Posterior, Default_Mode
**Frontoparietal** (4): DLPFC_Coarse, DLPFC_Dorsal, DLPFC_Ventral, Frontoparietal_Control

### Valid Combinations
✓ All 17 seeds work with both atlases = **34 combinations**

### Preprocessing
- High-pass: 0.01 Hz (100s)
- Low-pass: 0.1 Hz (10s)
- Smoothing: 6mm FWHM
- TR: 0.8s
- Volumes: 480 (6.4 minutes)

### HPC Jobs
**Session-level**: 4 CPUs, 16GB, 6 hours
**Group-level**: 8 CPUs, 32GB, 5000 permutations

## Common Tasks

### List all seeds
```bash
python script/config_loader.py --seeds
```

### Get seeds for one atlas
```bash
python script/config_loader.py --get-seeds DiFuMo256
```

### Check if combination is valid
```bash
python script/config_loader.py --check-combo Motor_Cortex DiFuMo256
```

### Generate output path
```bash
python script/config_loader.py --output-path seed_based 033 01 DiFuMo256 Motor_Cortex
```

### Print summary
```bash
python script/config_loader.py --summary
```

## Integration Examples

### Use in HPC Script
```bash
#!/bin/bash
SEEDS=$(python3 << 'PYTHON'
from script.config_loader import load_config
config = load_config()
for seed in config.get_valid_seeds(atlas='DiFuMo256'):
    print(seed)
PYTHON
)

for SEED in $SEEDS; do
    sbatch --export=SEED=$SEED hpc_seed_connectivity.sh
done
```

### Use in Python Analysis
```python
from script.config_loader import load_config
from pathlib import Path

config = load_config()

# Get preprocessing parameters
preproc = config.get_preprocessing()

# Iterate over all combinations
for atlas in config.get_atlases():
    for seed in config.get_valid_seeds(atlas=atlas):
        output_path = config.get_output_path(
            analysis_type='seed_based',
            subject_id='033',
            session='01',
            atlas=atlas,
            seed=seed
        )
        Path(output_path).mkdir(parents=True, exist_ok=True)
        # Process...
```

## API Reference

| Function | Purpose |
|----------|---------|
| `load_config()` | Load configuration |
| `config.get_valid_seeds(atlas=None, network=None)` | Get seed list |
| `config.get_valid_combination(seed, atlas)` | Validate pair |
| `config.get_output_path(...)` | Generate output path |
| `config.get_preprocessing()` | Get preprocessing params |
| `config.get_hpc()` | Get HPC specs |
| `config.get_atlases()` | Get atlas definitions |
| `config.print_summary()` | Print human-readable summary |

## Key Statistics

| Metric | Value |
|--------|-------|
| Total Seeds | 17 |
| Total Atlases | 2 |
| Valid Combinations | 34 |
| Networks | 5 |
| Subjects | 44 |
| Expected Sessions | ~88 |
| HPC Array Jobs (session-level) | 34 |
| HPC Array Jobs (group-level) | 34 |
| Total Submissions | 68 |
| Job Reduction | 97.7% |

## Troubleshooting

**Config not found**
```
ConfigLoadError: Config file not found...
```
→ Ensure `.github/connectivity_config.yaml` exists relative to project root

**Invalid combination**
```python
config.get_valid_combination('UnknownSeed', 'DiFuMo256')  # Returns False
```
→ Use `config.get_valid_seeds()` to see valid options

**YAML parsing error**
```
ConfigLoadError: Invalid YAML...
```
→ Check indentation (spaces, not tabs) and YAML syntax

## Next Steps

1. ✓ Configuration system created
2. ✓ All 17 seeds configured
3. ✓ Both atlases configured
4. ✓ All combinations validated
5. **→ Integrate into HPC submission scripts**
6. **→ Update analysis pipelines to use config**
7. **→ Add manifest tracking**

## More Information

See `.github/CONNECTIVITY_CONFIG_README.md` for:
- Complete configuration structure
- Detailed API documentation
- Extended usage examples
- Maintenance guide

---

**Status**: ✓ Complete and validated
**Last Updated**: 2025-04-29
**Version**: 1.0
