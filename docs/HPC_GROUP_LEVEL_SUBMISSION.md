# HPC Group-Level Job Submission Wrapper

## Overview

This document describes the HPC group-level job submission wrapper for SLURM parallelization. The wrapper automates the submission of group-level statistical analysis jobs with proper dependency chaining, manifest validation, and parallel job array execution.

## Architecture

### Key Components

1. **hpc_submit_group_level.py** - Main submission wrapper
   - Validates subject-level completion via manifest
   - Generates SLURM job scripts from templates
   - Submits job arrays with dependencies
   - Monitors job status and handles retries

2. **templates/hpc_group_level_template.sh** - SLURM job template
   - Configurable job array structure
   - Per-job execution logic for different analysis types
   - Automatic cluster labeling with FSL atlasq

3. **integration_hpc_submit_all_levels.sh** - Integration wrapper
   - Chains subject-level and group-level submissions
   - Optional completion waiting
   - Comprehensive logging

## Job Array Structure

The job array is parallelized across three dimensions:

### Seed-Based Analysis (34 jobs)
- **Dimensions**: 17 seeds × 2 atlases
- **Jobs**: One per seed-atlas combination
- **Seeds** (17 total):
  - Salience Network: anterior_insula, dacc, insula_dacc_combined
  - Hippocampus: hippocampus, hippocampus_anterior, hippocampus_posterior
  - Cerebellum: cerebellar_cognitive_l, cerebellar_cognitive_r, cerebellar_cognitive_bilateral, cerebellar_motor, cerebellar_vestibular
  - Motor: motor_cortex
  - Default Mode: default_mode
  - Frontoparietal: frontoparietal_control
  - DLPFC: dlpfc_l, dlpfc_r, dlpfc_bilateral
- **Atlases** (2 total): DiFuMo256, Schaefer400

### Local Measures (2 jobs)
- **Dimensions**: 2 atlases (no seeds)
- **Jobs**: One per atlas
- Analyzes fALFF and ReHo across groups

### Network Connectivity (1 job)
- **Dimensions**: None
- **Jobs**: Single analysis across all networks

**Total: 37 parallel jobs (max 10 concurrent)**

## Usage

### Basic Submission

```bash
# Submit group-level jobs with dependency on subject-level job
python script/hpc_submit_group_level.py \
    --subject-job-id 12345 \
    --correction-method grf \
    --n-permutations 1000
```

### Test Mode

```bash
# Test mode: submit 1 job per analysis type (3 total)
python script/hpc_submit_group_level.py \
    --subject-job-id 12345 \
    --test-mode
```

### Dry Run

```bash
# Dry run: show what would be submitted without actually submitting
python script/hpc_submit_group_level.py \
    --subject-job-id 12345 \
    --dry-run
```

### With Custom Configuration

```bash
# Use custom config file
python script/hpc_submit_group_level.py \
    --subject-job-id 12345 \
    --config .github/connectivity_config.yaml \
    --correction-method tfce \
    --n-permutations 5000
```

### Integration with Subject-Level

```bash
# Chain subject-level and group-level submissions
bash script/integration_hpc_submit_all_levels.sh --wait --test-mode
```

## Command-Line Arguments

| Argument | Required | Type | Default | Description |
|----------|----------|------|---------|-------------|
| `--subject-job-id` | Yes | str | — | SLURM job ID from subject-level submission |
| `--config` | No | str | None | Path to connectivity configuration YAML |
| `--correction-method` | No | str | grf | Multiple comparison correction (grf, tfce, fdr) |
| `--n-permutations` | No | int | 1000 | Number of permutations for testing |
| `--test-mode` | No | flag | False | Test mode: 1 job per analysis type |
| `--dry-run` | No | flag | False | Dry run: show without submitting |
| `--log-dir` | No | str | logs/ | Directory for logs |
| `--project-dir` | No | str | /home/clivewong/proj/longevity | Local project directory |
| `--remote-project-dir` | No | str | /home/clivewong/proj/long | Remote project directory (HPC) |

## Multiple Comparison Correction Methods

### GRF (Gaussian Random Field)
- **Method**: FSL's Gaussian Random Field theory
- **Speed**: Fast (~30 min for full 37 jobs)
- **Best for**: Standard volumetric analysis
- **Permutations**: N/A (uses parametric inference)

### TFCE (Threshold-Free Cluster Enhancement)
- **Method**: Permutation-based TFCE
- **Speed**: Medium (~2 hours for 1000 permutations)
- **Best for**: Non-parametric validation
- **Permutations**: Configurable (default 1000)

### FDR (False Discovery Rate)
- **Method**: Benjamini-Hochberg FDR control
- **Speed**: Fast
- **Best for**: Conservative multiple comparison control
- **Permutations**: N/A

## SLURM Directives

Generated SLURM scripts include:

```bash
#SBATCH --job-name=group_level_20260429_011906
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=12:00:00
#SBATCH --array=1-37%10              # 37 jobs, max 10 parallel
#SBATCH --output=logs/group_level_%A_%a.out
#SBATCH --error=logs/group_level_%A_%a.err
#SBATCH --depend=afterok:12345       # Dependency on subject-level job
```

## Dependency Chain

SLURM dependency chaining ensures group-level jobs wait for subject-level completion:

```
Subject-Level Job: 12345 (running)
    ↓
    └─→ Group-Level Job: 54321 (depends on 12345)
           - Holds in PENDING until 12345 completes
           - Auto-starts when 12345 succeeds
           - Fails if 12345 fails (afterok flag)
```

## Pre-Submission Validation

The wrapper performs several checks before submission:

1. **Manifest Validation**
   - Checks subject-level completion via `.manifest.json`
   - Verifies ≥80% of subjects completed (configurable)
   - Lists missing subjects if threshold not met

2. **Template Existence**
   - Verifies `script/templates/hpc_group_level_template.sh` exists
   - Reports helpful error if template missing

3. **Configuration Loading**
   - Loads connectivity configuration (optional)
   - Validates analysis types, seeds, atlases
   - Falls back to defaults if config unavailable

4. **Job Array Size**
   - Calculates total jobs based on configuration
   - Reports summary before submission

## Job Monitoring

### Check Job Status

```bash
# Check all group-level jobs
squeue -j 54321

# Check specific array task
squeue -j 54321_5

# Monitor with updates every 10 seconds
watch -n 10 squeue -j 54321
```

### View Job Logs

```bash
# View output from job array task 1
tail -f logs/group_level_54321_1.out

# View errors from all tasks
cat logs/group_level_54321_*.err

# Search for specific errors
grep -r "ERROR" logs/group_level_54321_*.err
```

### Get Job Statistics

```bash
# Get resource usage after job completes
sacct -j 54321 --format=JobID,Elapsed,CPUTime,MaxRSS

# Get completion status
sacct -j 54321 --format=JobID,State -X
```

## Output Organization

Results are organized by analysis type:

```
results/group_analysis/
├── seed_based/
│   ├── DiFuMo256/
│   │   ├── anterior_insula/
│   │   │   ├── tstat_map.nii.gz
│   │   │   ├── pval_map_corrected.nii.gz
│   │   │   ├── cluster_table_annotated.csv
│   │   │   └── group_analysis.log
│   │   ├── dacc/
│   │   └── ...
│   └── Schaefer400/
│       └── ...
├── local_measures/
│   ├── DiFuMo256/
│   │   ├── fALFF_tstat_map.nii.gz
│   │   ├── ReHo_tstat_map.nii.gz
│   │   └── group_analysis.log
│   └── Schaefer400/
│       └── ...
└── network_connectivity/
    ├── network_stats.json
    ├── network_tstat_map.nii.gz
    └── group_analysis.log
```

## Example Workflow

### Complete End-to-End Submission

```bash
# 1. Submit subject-level connectivity analysis
SUBJECT_JOB=$(sbatch script/hpc_seed_connectivity_array_with_manifest.sh | grep -o '[0-9]*' | head -1)
echo "Subject-level job: $SUBJECT_JOB"

# 2. Submit group-level analysis with dependency
GROUP_JOB=$(python script/hpc_submit_group_level.py \
    --subject-job-id $SUBJECT_JOB \
    --correction-method tfce \
    --n-permutations 5000 \
    --test-mode)
echo "Group-level job: $GROUP_JOB"

# 3. Monitor progress
watch -n 30 'squeue -j $GROUP_JOB && echo "---" && sacct -j $GROUP_JOB --format=JobID,State -X'
```

### Test Run

```bash
# Quick test with minimal data
python script/hpc_submit_group_level.py \
    --subject-job-id 12345 \
    --test-mode \
    --correction-method grf
```

### Production Run with Permutation Testing

```bash
# Full production run with TFCE correction
python script/hpc_submit_group_level.py \
    --subject-job-id 12345 \
    --correction-method tfce \
    --n-permutations 10000 \
    --log-dir logs/group_analysis_20260429
```

## Troubleshooting

### Job Submission Fails

**Problem**: `sbatch: error: Batch script is empty`

**Solution**: 
1. Verify template exists: `ls script/templates/hpc_group_level_template.sh`
2. Check template is not corrupted: `head -20 script/templates/hpc_group_level_template.sh`
3. Verify placeholders were substituted: `grep "{{" logs/group_level_*.sh`

### Jobs Hold in PENDING

**Problem**: Group-level jobs stay in PENDING state

**Solution**:
1. Check dependency: `squeue -j [job-id]` (should show `Dependency=`dependency_indicator)
2. Check subject-level job: `squeue -j [subject-job-id]`
3. If subject-level failed: `sacct -j [subject-job-id] --format=State -X`
4. View dependency details: `scontrol show job [job-id]` (look for `Dependency=`)

### Individual Task Failures

**Problem**: Some array tasks fail but others succeed

**Solution**:
1. Check task-specific error: `cat logs/group_level_[array-id]_[task-id].err`
2. Look for missing input data: Task failures often indicate incomplete subject-level results
3. Identify failed task type: Parse error log to determine which seed/atlas failed
4. Resubmit individual task: Create a single-task job for debugging

### Out of Memory Errors

**Problem**: `Segmentation fault` or `out of memory` messages

**Solution**:
- Increase memory in template: Change `#SBATCH --mem=32G` to `#SBATCH --mem=64G`
- Reduce permutations for TFCE: Use `--n-permutations 500` instead of 5000
- Check for memory leaks in analysis script

## Integration with Existing Infrastructure

### With HPC Job Manager

```python
from script.hpc_job_manager import HpcJobManager

manager = HpcJobManager("/home/clivewong/proj/longevity")

# Submit group-level with manager's submission tracking
group_job_id = manager.submit_group_level_jobs(
    script="logs/group_level_20260429_011906.sh",
    job_name="group_level_analysis",
    subject_job_id="12345",
    seeds=["anterior_insula", "dacc", "motor_cortex"],
    atlases=["DiFuMo256", "Schaefer400"]
)
```

### With Manifest Manager

```python
from script.hpc_manifest import ManifestManager

manager = ManifestManager(".manifest.json")

# Check readiness before submission
is_ready = manager.is_ready_for_group_analysis(
    seed="anterior_insula",
    atlas="DiFuMo256",
    min_threshold=0.8
)

if is_ready:
    print("Ready for group analysis")
else:
    missing = manager.get_missing_subjects("anterior_insula", "DiFuMo256")
    print(f"Missing: {missing}")
```

## Performance Expectations

| Analysis Type | Typical Runtime | Jobs | Total Time |
|---------------|-----------------|------|-----------|
| Seed-based GRF | 5 min each | 34 | ~20 min (10 parallel) |
| Seed-based TFCE | 30 min each | 34 | ~3 hrs (10 parallel) |
| Local measures | 10 min each | 2 | ~10 min (parallel) |
| Network connectivity | 15 min | 1 | ~15 min |

**Full run (all 37 jobs, GRF correction, 10 parallel)**:
- Estimated: 30-40 minutes
- Actual depends on cluster load and I/O

## Best Practices

1. **Start with Test Mode**: Always test with `--test-mode` first
2. **Use Dry Run**: Verify configuration with `--dry-run` before actual submission
3. **Monitor Initial Jobs**: Watch first few tasks to catch configuration issues early
4. **Use Appropriate Correction**: 
   - GRF for fast turnaround
   - TFCE for rigorous validation
   - FDR for conservative results
5. **Archive Results**: Copy results to secure location after successful completion
6. **Document Runs**: Include submission parameters in analysis notes
7. **Check Completion**: Always verify output files before downstream analyses

## References

- SLURM Documentation: https://slurm.schedmd.com/
- FSL GRF Correction: https://fsl.fmrib.ox.ac.uk/fsl/fslwiki/Randomise/
- TFCE Method: Salimi-Khorshidi et al. (2011) NeuroImage
- Repository Integration: See `script/master_full_connectivity_workflow.sh`
