# HPC Subject-Level Job Submission Wrapper

## Overview

`hpc_submit_subject_level.py` is a Python wrapper for submitting SLURM job arrays that parallelize subject-level connectivity analysis across all subjects and sessions in the study.

## Key Features

- **Job Array Parallelization**: Submits SLURM array jobs for 44 subjects × 2 sessions = 88 parallel jobs (with configurable limits)
- **Three Analysis Pipelines**:
  - Local Measures (fALFF, ReHo)
  - Seed-Based Connectivity (all 17 seeds, both atlases)
  - Network Connectivity (both atlases)
- **Manifest Tracking**: Records completion status for group-level readiness validation
- **Test Mode**: Submit jobs for just 2 subjects to test configuration
- **Dry-Run Mode**: Preview generated SLURM script without submitting
- **Configuration-Driven**: All parameters from `.github/connectivity_config.yaml`

## Usage

### Basic submission (production)

```bash
cd /home/clivewong/proj/longevity
python script/hpc_submit_subject_level.py
```

### Test mode (2 subjects only)

```bash
python script/hpc_submit_subject_level.py --test-mode
```

### Dry-run (preview SLURM script)

```bash
python script/hpc_submit_subject_level.py --dry-run
```

### Validate requirements without submitting

```bash
python script/hpc_submit_subject_level.py --validate
```

### View submission summary

```bash
python script/hpc_submit_subject_level.py --summary
```

### Check job status

```bash
python script/hpc_submit_subject_level.py --check-job 12345678
```

## Command-Line Options

```
--config CONFIG               Path to connectivity config YAML (default: .github/connectivity_config.yaml)
--log-dir LOG_DIR            Directory for SLURM logs (default: logs)
--output-dir OUTPUT_DIR      Base directory for results (default: results)
--test-mode                  Only submit jobs for 2 subjects
--dry-run                    Print SLURM script without submitting
--check-job CHECK_JOB        Check status of submitted job (provide job ID)
--validate                   Validate requirements without submitting
--summary                    Print submission summary
```

## Execution Flow

For each subject-session pair, the generated SLURM job:

1. **Local Measures** (per subject-session)
   - Computes fALFF and ReHo
   - Output: `results/local_measures/sub-XXX_ses-YY/`
   - Records completion in manifest

2. **Seed-Based Connectivity** (per subject-session-seed-atlas)
   - Runs all 17 seeds
   - For both DiFuMo256 and Schaefer400
   - Output: `results/seed_based/{atlas}/{seed}/sub-XXX_ses-YY/`
   - Tracks completion in manifest

3. **Network Connectivity** (per subject-session-atlas)
   - Computes between-network connectivity
   - For both DiFuMo256 and Schaefer400
   - Output: `results/network_connectivity/{atlas}/sub-XXX_ses-YY/`
   - Records in manifest

## Job Array Configuration

From config file (`hpc.session_level`):
- **Time limit**: 6 hours (configurable)
- **Memory**: 16G per task
- **CPUs**: 4 cores per task
- **Partition**: `cpu-long` (customizable)
- **Array limit**: 100 parallel jobs max (adjustable)
- **Job array**: `--array=1-44%20` (44 subjects, max 20 parallel)

## Output Structure

```
results/
├── local_measures/
│   ├── sub-033_ses-01/
│   │   ├── sub-033_ses-01_fALFF.nii.gz
│   │   ├── sub-033_ses-01_ReHo.nii.gz
│   │   └── ...
│   └── ...
├── seed_based/
│   ├── DiFuMo256/
│   │   ├── Anterior_Insula/
│   │   │   ├── sub-033_ses-01/
│   │   │   │   ├── sub-033_ses-01_zmap.nii.gz
│   │   │   │   └── ...
│   │   │   └── ...
│   │   └── ...
│   └── Schaefer400/
│       └── ...
├── network_connectivity/
│   ├── DiFuMo256/
│   │   ├── sub-033_ses-01/
│   │   │   ├── sub-033_ses-01_connectivity_matrix.csv
│   │   │   └── ...
│   │   └── ...
│   └── Schaefer400/
│       └── ...
└── .manifest.json  # Completion tracking
```

## Manifest Tracking

The `.manifest.json` file records:
- Subject ID, Session, Seed, Atlas
- Completion status (complete/failed/partial)
- Timestamp
- Output path
- Job ID

Query manifest:
```bash
python script/hpc_manifest.py --manifest results/.manifest.json status
python script/hpc_manifest.py --manifest results/.manifest.json check-ready \
    --seed Anterior_Insula --atlas DiFuMo256 --threshold 0.8
```

## Error Handling

- **Missing fMRIPrep outputs**: Logged as warnings, skips that subject-session
- **Failed analyses**: Creates `.{subject}_{session}_{analysis}.failed` marker in logs
- **Missing dependencies**: Validation checks Python packages and data availability
- **SLURM unavailable**: Provides helpful message suggesting `--dry-run` option

## Dependencies

Python:
- `pyyaml` (config parsing)
- `pathlib` (file operations)
- Standard library: `subprocess`, `json`, `argparse`, `datetime`

System:
- SLURM (for actual job submission; not needed for dry-run)
- `sbatch` command available in PATH

Analysis:
- `compute_local_measures.py`
- `seed_based_connectivity.py`
- `compute_network_connectivity.py`
- `hpc_manifest.py`

## Integration with Group Analysis

After subject-level jobs complete, use manifest to check readiness:

```bash
# Check if sufficient subjects completed for group analysis
python script/hpc_manifest.py --manifest results/.manifest.json \
    check-ready --seed Motor_Cortex --atlas DiFuMo256

# If ready (exit code 0), submit group-level jobs
if [ $? -eq 0 ]; then
    python script/hpc_submit_group_level.py --seed Motor_Cortex --atlas DiFuMo256
fi
```

## Performance Considerations

- **Subject Parallelization**: Up to 20 subjects run simultaneously (configurable)
- **Per-Job Time**: ~6 hours per subject (includes all analyses)
- **Per-Subject Computation**:
  - Local measures: ~30 min
  - Seed connectivity × 17 seeds: ~2-3 hours
  - Network connectivity × 2 atlases: ~30 min
- **Total Execution**: ~10-15 minutes on 44 subjects (with parallelization)

## Testing Workflow

1. Validate setup:
   ```bash
   python script/hpc_submit_subject_level.py --validate
   ```

2. Preview job script:
   ```bash
   python script/hpc_submit_subject_level.py --dry-run --test-mode
   ```

3. Submit test with 2 subjects:
   ```bash
   python script/hpc_submit_subject_level.py --test-mode
   ```

4. Monitor test run:
   ```bash
   watch -n 10 "squeue -j <job_id>"
   python script/hpc_submit_subject_level.py --check-job <job_id>
   ```

5. Check logs:
   ```bash
   tail -f logs/subject_level_*.log
   ```

6. If successful, submit full run:
   ```bash
   python script/hpc_submit_subject_level.py
   ```

## Troubleshooting

**SLURM not found**:
- Dry-run works: `python script/hpc_submit_subject_level.py --dry-run`
- For actual submission, ensure SLURM is installed and `sbatch` is in PATH

**fMRIPrep outputs missing**:
- Check that `fmriprep/` directory exists with preprocessed BOLD files
- Validation warning: "fMRIPrep available: ✗"
- Run only on HPC where fMRIPrep outputs are accessible

**Validation fails**:
- Review validation output: `python script/hpc_submit_subject_level.py --validate`
- Check disk space: `df -h`
- Verify config file: `cat .github/connectivity_config.yaml | head -20`

**Job submission fails**:
- Check SLURM partition available: `sinfo -p cpu-long`
- Review sbatch error message
- Try dry-run to verify script generation: `python script/hpc_submit_subject_level.py --dry-run`

## References

- **Config Schema**: `.github/connectivity_config.yaml`
- **Manifest Manager**: `script/hpc_manifest.py`
- **SLURM Job Arrays**: https://slurm.schedmd.com/job_array.html
- **SLURM Directives**: https://slurm.schedmd.com/sbatch.html
