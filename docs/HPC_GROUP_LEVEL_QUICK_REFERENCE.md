# Quick Reference: HPC Group-Level Job Submission

## One-Liners

### Test Run (1 job per analysis type)
```bash
python script/hpc_submit_group_level.py --subject-job-id 12345 --test-mode
```

### Production Run (All 37 jobs)
```bash
python script/hpc_submit_group_level.py --subject-job-id 12345
```

### Dry Run (See what would happen)
```bash
python script/hpc_submit_group_level.py --subject-job-id 12345 --dry-run
```

### TFCE Correction (Permutation-based)
```bash
python script/hpc_submit_group_level.py --subject-job-id 12345 \
  --correction-method tfce --n-permutations 5000
```

## Job Array Details

| Component | Count | Notes |
|-----------|-------|-------|
| Seed-based jobs | 34 | 17 seeds × 2 atlases |
| Local measures jobs | 2 | 2 atlases (no seeds) |
| Network connectivity jobs | 1 | Single analysis |
| **Total** | **37** | Max 10 parallel |

## Common Commands

```bash
# Check job status
squeue -j JOBID

# Monitor job array
watch -n 10 squeue -j JOBID

# View task output
tail -f logs/group_level_JOBID_1.out

# View task errors
cat logs/group_level_JOBID_1.err

# Cancel job
scancel JOBID

# Get completed status
sacct -j JOBID --format=State -X
```

## Output Locations

```
results/group_analysis/seed_based/{ATLAS}/{SEED}/
├── tstat_map.nii.gz              # Test statistic map
├── pval_map_corrected.nii.gz     # Corrected p-value map
├── cluster_table_annotated.csv   # Labeled clusters
└── group_analysis.log             # Execution log
```

## Typical Runtimes

- **GRF correction**: ~30 min (all 37 jobs)
- **TFCE (1000 perm)**: ~2 hours
- **TFCE (5000 perm)**: ~6 hours

## Failure Recovery

```bash
# If jobs fail, check specific task
cat logs/group_level_JOBID_5.err

# Resubmit with same parameters
python script/hpc_submit_group_level.py \
  --subject-job-id 12345 \
  --correction-method grf
```

## Integration Example

```bash
# Submit both levels in sequence
SUBJ=$(sbatch script/hpc_seed_connectivity_array.sh | grep -o '[0-9]*' | head -1)
GROUP=$(python script/hpc_submit_group_level.py --subject-job-id $SUBJ | tail -5)
echo "Jobs submitted: Subject=$SUBJ, Group=$GROUP"
```
