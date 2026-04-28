# HPC Group-Level Job Submission Wrapper - README

## Quick Start

```bash
# Submit group-level analysis jobs (requires subject-level job ID)
python script/hpc_submit_group_level.py --subject-job-id 12345

# Monitor progress
squeue -j 54321  # (output job ID from above command)

# Check results
ls -lh results/group_analysis/seed_based/DiFuMo256/*/
```

## What This Does

This wrapper **automates the submission of 37 parallel group-level statistical analysis jobs** to SLURM with proper dependency chaining, manifest validation, and error handling.

### The Problem It Solves

Without this wrapper, group-level analysis requires:
1. Manually checking if all subject-level jobs completed
2. Manually creating SLURM job arrays for each analysis type
3. Manually specifying dependencies
4. Manual retry logic if jobs fail
5. Manual monitoring and result collection

### The Solution

One command submits all 37 jobs with:
- ✓ Automatic dependency on subject-level completion
- ✓ Parallel execution across multiple seeds, atlases, and analysis types
- ✓ Configurable multiple comparison correction (GRF, TFCE, FDR)
- ✓ Built-in error handling and recovery
- ✓ Comprehensive logging and monitoring

## How It Works

### Job Array Structure

The wrapper generates a SLURM job array with **37 total jobs**:

```
Seed-Based Connectivity (34 jobs)
├── 17 seeds × 2 atlases
├── Seed examples: anterior_insula, dacc, motor_cortex, dlpfc_l, ...
└── Atlas examples: DiFuMo256, Schaefer400

Local Measures Analysis (2 jobs)
├── fALFF and ReHo group statistics
└── One job per atlas

Network Connectivity (1 job)
└── Graph-based network analysis
```

### Dependency Chain

```
Subject-Level Job: 12345 (running connectivity analyses)
    ↓
    └─→ Group-Level Job: 54321 (depends on 12345)
           - Holds in PENDING until 12345 completes
           - Auto-starts if 12345 succeeds
           - Fails if 12345 fails (safety feature)
```

## Usage

### Basic Submission

```bash
# Submit with default settings (GRF correction, 1000 permutations)
python script/hpc_submit_group_level.py --subject-job-id 12345

Output:
  Group job ID: 54321
  Total jobs: 37
  Dependency: afterok:12345
```

### Test Run (Quick Validation)

```bash
# Test with 3 jobs (1 per analysis type)
python script/hpc_submit_group_level.py --subject-job-id 12345 --test-mode

Output:
  Group job ID: 54321
  Total jobs: 3 (test mode)
```

### Dry Run (No Submission)

```bash
# Preview what would be submitted
python script/hpc_submit_group_level.py --subject-job-id 12345 --dry-run

Output:
  [DRY RUN] Would submit above command
  Group job ID: DRY_RUN_000000
```

### Advanced: Different Correction Methods

```bash
# TFCE correction (rigorous, permutation-based)
python script/hpc_submit_group_level.py \
    --subject-job-id 12345 \
    --correction-method tfce \
    --n-permutations 5000

# FDR correction (conservative, single-step)
python script/hpc_submit_group_level.py \
    --subject-job-id 12345 \
    --correction-method fdr
```

### Integration: Submit Both Levels

```bash
# Chain subject-level and group-level in one script
bash script/integration_hpc_submit_all_levels.sh --wait --test-mode

Output:
  [STEP 1] Submit subject-level jobs → 12345
  [STEP 2] Wait for completion (polling every 60s)
  [STEP 3] Submit group-level jobs → 54321 (depends on 12345)
```

## Command-Line Reference

```
python script/hpc_submit_group_level.py [OPTIONS]

Required:
  --subject-job-id ID              SLURM job ID from subject-level

Optional:
  --config PATH                    Connectivity config YAML
  --correction-method {grf|tfce|fdr}  Default: grf
  --n-permutations N               Default: 1000
  --test-mode                      Submit 1 job per analysis type
  --dry-run                        Don't actually submit
  --log-dir DIR                    Default: logs/
  --project-dir DIR                Default: /home/clivewong/proj/longevity
  --remote-project-dir DIR         Default: /home/clivewong/proj/long
```

## Monitoring

### Check Job Status

```bash
# View all job array tasks
squeue -j 54321

# View only running tasks
squeue -j 54321 --state=RUNNING

# Monitor with live updates
watch -n 10 'squeue -j 54321'

# Get completion summary
squeue -j 54321 --format=%T | sort | uniq -c
```

### View Logs

```bash
# Tail output from first task
tail -f logs/group_level_54321_1.out

# View errors from specific task
cat logs/group_level_54321_5.err

# Search all error logs
grep -r ERROR logs/group_level_54321_*.err
```

### Get Performance Data

```bash
# View resource usage after completion
sacct -j 54321 --format=JobID,Elapsed,CPUTime,MaxRSS

# Export to CSV
sacct -j 54321 --format=JobID,Start,End,Elapsed,State --parsable2 > job_stats.csv
```

## Results Location

```
results/group_analysis/
├── seed_based/
│   ├── DiFuMo256/
│   │   ├── anterior_insula/
│   │   │   ├── tstat_map.nii.gz              # Test statistic map
│   │   │   ├── pval_map_corrected.nii.gz    # Corrected p-values
│   │   │   ├── cluster_table.csv            # Cluster statistics
│   │   │   ├── cluster_table_annotated.csv  # With anatomy labels
│   │   │   └── group_analysis.log
│   │   ├── dacc/
│   │   └── ... (remaining 15 seeds)
│   └── Schaefer400/
│       ├── anterior_insula/
│       └── ... (all seeds)
│
├── local_measures/
│   ├── DiFuMo256/
│   │   ├── fALFF_tstat_map.nii.gz
│   │   ├── ReHo_tstat_map.nii.gz
│   │   └── group_analysis.log
│   └── Schaefer400/
│       └── ...
│
└── network_connectivity/
    ├── network_stats.json
    ├── network_tstat_map.nii.gz
    └── group_analysis.log
```

## Expected Runtime

| Scenario | Time | Notes |
|----------|------|-------|
| Test run (3 jobs, GRF) | ~10 min | Minimal |
| Full run (37 jobs, GRF) | ~30-40 min | 10 parallel |
| Full run (37 jobs, TFCE 1000) | ~2 hours | Permutation overhead |
| Full run (37 jobs, TFCE 5000) | ~6 hours | High-resolution |

## Correction Methods Explained

### GRF (Gaussian Random Field) - DEFAULT
- **Speed**: Fast (~30 min for 37 jobs)
- **Method**: Parametric inference using FSL
- **Best for**: Standard neuroimaging analysis
- **Pros**: Quick, reliable, FSL-native
- **Cons**: Assumes normality

### TFCE (Threshold-Free Cluster Enhancement)
- **Speed**: Medium (~2-6 hours for 37 jobs depending on permutations)
- **Method**: Permutation-based, non-parametric
- **Best for**: Rigorous validation, unconventional analysis
- **Pros**: No assumptions, handles non-normal distributions
- **Cons**: Computationally intensive

### FDR (False Discovery Rate)
- **Speed**: Fast (~20 min for 37 jobs)
- **Method**: Benjamini-Hochberg FDR control
- **Best for**: Conservative results, multiple comparisons
- **Pros**: Fast, well-established
- **Cons**: Less powerful than GRF

## Troubleshooting

### Jobs Stay in PENDING State

```bash
# Check dependency
squeue -j 54321
# Look for "Dependency=afterok:12345"

# If subject-level job failed:
squeue -j 12345  # Should show FAILED or CANCELLED

# Solution: Resubmit subject-level jobs first
```

### Individual Task Failures

```bash
# Check error log
cat logs/group_level_54321_5.err

# Common causes:
# 1. Missing input data
# 2. Insufficient memory (increase in template)
# 3. Analysis script error (see detailed log)

# Resubmit if needed
python script/hpc_submit_group_level.py --subject-job-id 12345 --dry-run
```

### Out of Memory

```bash
# Edit template to increase memory
# In script/templates/hpc_group_level_template.sh:
# Change: #SBATCH --mem=32G
# To:     #SBATCH --mem=64G

# Resubmit
```

## Integration with Existing Workflows

This wrapper integrates seamlessly with:
- ✓ `hpc_manifest.py` - Completion tracking
- ✓ `hpc_job_manager.py` - Job lifecycle management
- ✓ `group_analysis_statistics.py` - Per-job analysis execution
- ✓ `label_clusters_with_fsl_atlasq.py` - Cluster annotation
- ✓ `master_full_connectivity_workflow.sh` - Pipeline orchestration

## Documentation

- **Full Guide**: `docs/HPC_GROUP_LEVEL_SUBMISSION.md`
- **Quick Reference**: `docs/HPC_GROUP_LEVEL_QUICK_REFERENCE.md`
- **Delivery Summary**: `HPC_GROUP_LEVEL_DELIVERY.md`

## Examples

### Example 1: Complete Workflow

```bash
# 1. Submit subject-level jobs (on HPC)
SUBJ=$(ssh hpclogin1 'sbatch /home/clivewong/proj/long/script/hpc_seed_connectivity_array.sh' \
       | grep -o '[0-9]*' | head -1)
echo "Subject-level job: $SUBJ"

# 2. Wait and submit group-level (local, can chain immediately due to dependencies)
GROUP=$(python script/hpc_submit_group_level.py --subject-job-id $SUBJ | tail -5 | grep "Group job ID")
echo "Group-level job: $GROUP"

# 3. Monitor progress
watch -n 30 "squeue -j $GROUP && echo '---' && sacct -j $GROUP -X"
```

### Example 2: Test Run Before Production

```bash
# 1. Dry run to verify configuration
python script/hpc_submit_group_level.py --subject-job-id 12345 --dry-run

# 2. Test run with minimal jobs
python script/hpc_submit_group_level.py --subject-job-id 12345 --test-mode

# 3. Check test results
ls logs/group_level_*_*.out
tail -20 logs/group_level_*_1.out

# 4. Full production run
python script/hpc_submit_group_level.py --subject-job-id 12345
```

## Getting Help

```bash
# Show command-line help
python script/hpc_submit_group_level.py --help

# Check detailed documentation
cat docs/HPC_GROUP_LEVEL_SUBMISSION.md

# View quick reference
cat docs/HPC_GROUP_LEVEL_QUICK_REFERENCE.md

# Check logs for errors
grep ERROR logs/*.log
```

## Summary

The HPC group-level submission wrapper simplifies neuroimaging group-level analysis from a complex multi-step process to a single command, while maintaining flexibility and robustness for production use.

**Key benefits:**
- ✓ Automated SLURM job submission with dependencies
- ✓ 37 parallel jobs for comprehensive analysis
- ✓ Flexible correction methods (GRF/TFCE/FDR)
- ✓ Robust error handling and monitoring
- ✓ Full integration with existing infrastructure
- ✓ Production-ready with comprehensive documentation

**Quick start:**
```bash
python script/hpc_submit_group_level.py --subject-job-id 12345
```

For more information, see the full documentation in `docs/`.
