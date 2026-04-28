# Quick Start: HPC Subject-Level Job Submission

## 60-Second Overview

This wrapper submits SLURM job arrays that run three connectivity analyses (local measures, seed-based connectivity, network connectivity) for all 44 subjects × 2 sessions in parallel.

## Quick Commands

### 1. Preview what will be submitted (no SLURM needed)

```bash
python script/hpc_submit_subject_level.py --dry-run --test-mode | less
```

### 2. Validate everything is ready

```bash
python script/hpc_submit_subject_level.py --validate
```

Expected output (with all checks passing):
```
[✓] Config loaded
[✓] Subjects found
[✓] Seeds found
[✓] fMRIPrep available
[✓] Disk space
[✓] SLURM available
```

### 3. Submit test job (2 subjects only)

```bash
python script/hpc_submit_subject_level.py --test-mode
```

Output:
```
Job ID: 12345678
Script: logs/tmp...sh
Log dir: logs
Output dir: results
(Test mode: 2 subjects only)
```

### 4. Monitor test job

```bash
watch -n 10 "squeue -j 12345678"
tail -f logs/subject_level_*.log
```

### 5. If test succeeds, submit full job

```bash
python script/hpc_submit_subject_level.py
```

This will submit:
- 44 subjects × 2 sessions = 88 parallel jobs
- Max 20 running simultaneously
- Each subject takes ~6 hours
- Total wall time: ~15-20 minutes (with parallelization)

### 6. Check submission summary

```bash
python script/hpc_submit_subject_level.py --summary
```

## What Gets Computed

For each subject-session pair:

1. **Local Measures**
   - fALFF (Fractional Amplitude of Low-Frequency Fluctuations)
   - ReHo (Regional Homogeneity)
   - Output: `results/local_measures/sub-XXX_ses-YY/`

2. **Seed-Based Connectivity**
   - All 17 seeds (Anterior_Insula, dACC, Hippocampus, etc.)
   - Both atlases (DiFuMo256, Schaefer400)
   - Output: `results/seed_based/{atlas}/{seed}/sub-XXX_ses-YY/`

3. **Network Connectivity**
   - Between-network connectivity matrices
   - Both atlases
   - Output: `results/network_connectivity/{atlas}/sub-XXX_ses-YY/`

## Output Files

```
results/
├── local_measures/
│   ├── sub-033_ses-01/
│   │   ├── sub-033_ses-01_fALFF.nii.gz
│   │   └── sub-033_ses-01_ReHo.nii.gz
│   └── ...
├── seed_based/
│   ├── DiFuMo256/
│   │   ├── Anterior_Insula/
│   │   │   ├── sub-033_ses-01/
│   │   │   │   └── sub-033_ses-01_zmap.nii.gz
│   │   │   └── ...
│   │   └── ...
│   └── Schaefer400/
│       └── ...
├── network_connectivity/
│   ├── DiFuMo256/
│   │   └── sub-033_ses-01/
│   │       └── sub-033_ses-01_connectivity_matrix.csv
│   └── Schaefer400/
│       └── ...
└── .manifest.json  # Tracks job completion
```

## Manifest Status

After jobs complete, check progress:

```bash
# Show overall status
python script/hpc_manifest.py --manifest results/.manifest.json status

# Check if ready for group analysis (80% threshold)
python script/hpc_manifest.py --manifest results/.manifest.json \
    check-ready --seed Motor_Cortex --atlas DiFuMo256

# List missing subjects
python script/hpc_manifest.py --manifest results/.manifest.json \
    missing --seed Motor_Cortex --atlas DiFuMo256
```

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Command not found | `cd /home/clivewong/proj/longevity` first |
| SLURM not available | Use `--dry-run` to preview script |
| fMRIPrep files missing | Ensure running on HPC with fmriprep/ directory |
| Job submission fails | Check with `--validate` and review SLURM partition |
| Low disk space | Check `df -h` - need ~500GB |

## Configuration

All parameters are in `.github/connectivity_config.yaml`. Key settings:

```yaml
hpc:
  session_level:
    time_limit_hours: 6          # Time per subject
    cpus_per_task: 4             # Cores per job
    mem_per_seed: "16G"          # Memory per job
    partition: "cpu-long"        # SLURM partition
    job_array_limit: 100         # Max concurrent jobs
```

To modify, edit YAML and re-run submission command.

## Integration with Group Analysis

After subject-level jobs complete:

1. Check manifest status
2. Run group-level analysis (separate job array)
3. Generate statistical maps and reports

## Performance

- **Per-subject compute time**: ~6 hours
- **Parallelization**: Up to 20 subjects simultaneously
- **Total wall time**: 15-20 minutes for all 44 subjects
- **Disk usage**: ~50-100 GB per analysis type

## Getting Help

Full documentation: `script/HPC_SUBJECT_LEVEL_README.md`

For script debugging:

```bash
python script/hpc_submit_subject_level.py --help
python script/hpc_manifest.py --help
```
