# HPC Workflow Quick Reference

## Quick Start

### 1. Run Full Pipeline with Dependencies

```bash
# Full production run
bash script/hpc_orchestrate_full_pipeline.sh

# Test mode (2 subjects, single seed/atlas)
bash script/hpc_orchestrate_full_pipeline.sh --test

# Skip group-level jobs
bash script/hpc_orchestrate_full_pipeline.sh --no-group
```

### 2. Check Progress

```bash
# View current jobs and dependencies
squeue -u $USER --priority

# Check manifest completion
python3 script/hpc_manifest.py --manifest results/.manifest.json status

# Check if specific seed-atlas is ready
python3 script/hpc_manifest.py --manifest results/.manifest.json check-ready \
    --seed dlpfc_l --atlas difumo256
```

### 3. List Missing Subjects

```bash
# Find incomplete/failed subjects for retry
python3 script/hpc_manifest.py --manifest results/.manifest.json missing \
    --seed dlpfc_l --atlas difumo256
```

## Common Commands

### Submit Individual Jobs with Dependencies

```bash
# Submit local measures
A=$(sbatch script/hpc_local_measures_all24.sh 2>&1 | grep -oE "[0-9]+$")

# Submit seed connectivity after local measures
B=$(sbatch --depend=afterok:$A script/hpc_seed_connectivity_array_with_manifest.sh 2>&1 | grep -oE "[0-9]+$")

# Submit between-network after seed connectivity
C=$(sbatch --depend=afterok:$B script/hpc_between_network_array.sh 2>&1 | grep -oE "[0-9]+$")

# Submit sync after all subject-level jobs
D=$(sbatch --depend=afterok:$C script/hpc_sync.sh 2>&1 | grep -oE "[0-9]+$")

# Submit group analysis after sync
E=$(sbatch --depend=afterok:$D script/hpc_group_analysis_array.sh 2>&1 | grep -oE "[0-9]+$")

echo "Job IDs: A=$A B=$B C=$C D=$D E=$E"
```

### Monitor Job Chain

```bash
# Watch jobs in queue
watch -n 5 'squeue -u $USER --priority'

# Check specific job status
scontrol show job 12345

# View job array progress
squeue --job 12345 --array

# Get job history
sacct --job 12345 --format=JobID,State,ExitCode
```

### View Logs

```bash
# Recent orchestration log
tail -f logs/orchestration_*.log

# Array job logs (example)
ls logs/seed_connectivity_12345_*.out

# Specific task log
tail -100 logs/seed_connectivity_12345_1.out

# Sync logs
tail -f logs/hpc_sync_*.out

# Job submission log (JSON)
cat logs/job_submissions.log | python3 -m json.tool | head -50
```

### Handle Failures

```bash
# Get failed subjects
python3 script/hpc_manifest.py --manifest results/.manifest.json missing \
    --seed dlpfc_l --atlas difumo256 | grep FAILED

# Check job logs for specific task
cat logs/seed_connectivity_12345_5.err

# Resubmit single subject
sbatch script/hpc_seed_connectivity_array_with_manifest.sh

# Retry failed tasks with automatic retry logic
python3 script/hpc_job_manager.py --project-dir /home/clivewong/proj/longevity \
    submit-subject \
    --script script/hpc_seed_connectivity_array_with_manifest.sh \
    --job-name retry_seed \
    --subjects sub-033 \
    --seeds dlpfc_l \
    --atlases difumo256
```

## Environment Variables

```bash
# Set subjects to process
export SUBJECTS="sub-033,sub-034,sub-035"

# Set seeds
export SEEDS="dlpfc_l,dlpfc_r,dlpfc_bilateral"

# Set atlases
export ATLASES="difumo256,schaefer400"

# Run pipeline with custom settings
bash script/hpc_orchestrate_full_pipeline.sh --test
```

## File Locations

```
/home/clivewong/proj/longevity/
├── script/
│   ├── hpc_manifest.py              # Manifest tracking
│   ├── hpc_job_manager.py           # Job submission & monitoring
│   ├── hpc_sync.sh                  # Result sync & validation
│   ├── hpc_orchestrate_full_pipeline.sh  # Master orchestration
│   ├── hpc_seed_connectivity_array_with_manifest.sh  # Updated seed script
│   └── hpc_local_measures_all24.sh  # Local measures
│
├── results/
│   ├── .manifest.json               # Task completion tracking
│   ├── seed_based/                  # Seed connectivity outputs
│   ├── local_measures/              # fALFF, ReHo outputs
│   └── group_analysis/              # Group-level statistical results
│
├── logs/
│   ├── orchestration_*.log          # Master workflow logs
│   ├── job_submissions.log          # All job submissions (JSON)
│   ├── job_retries.log              # Retry attempts (JSON)
│   ├── seed_connectivity_*.out      # Array job outputs
│   └── hpc_sync_*.out               # Sync operation logs
│
└── docs/
    └── HPC_WORKFLOW.md              # Full documentation
```

## Key Concepts

### Job Dependencies

```
withhold → afterok → afterany → afternotok
└─ Job only runs after previous completes ─┘
```

### Manifest Readiness

```
Task recorded → Completion rate calculated → Threshold checked
     ↓              ↓                             ↓
     ✓          > 80% complete?              YES → Ready for group analysis
                                              NO  → Retry missing subjects
```

### NFS Safety

```
Subject-level complete → Sync results → Flush caches → Group analysis safe
                         ↓               ↓
                      rsync             sync + sleep(5)
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Jobs stuck in queue | Check dependencies: `squeue --dependency` |
| Manifest incomplete | Records weren't written: `sbatch --test-only script/...` |
| Group analysis reads partial data | Ensure sync ran: `tail logs/hpc_sync_*.out` |
| Job failed silently | Check manifest: `missing --seed ... --atlas ...` |
| Too many jobs running | Reduce array parallelism: `--array=1-40%5` |
| NFS not syncing | Increase wait: modify `sleep 5` to `sleep 10` in hpc_sync.sh |

## Advanced Usage

### Debug Mode (Dry Run)

```bash
# Preview job submission without submitting
sbatch --test-only script/hpc_orchestrate_full_pipeline.sh

# Check manifest logic without running
python3 script/hpc_manifest.py --manifest /nonexistent/path.json status
```

### Custom Orchestration

```bash
#!/bin/bash
# Custom pipeline with only seed connectivity

PROJECT_DIR="/home/clivewong/proj/longevity"
SEEDS="dlpfc_l,dlpfc_r"
SUBJECTS="sub-033,sub-034"

A=$(python3 $PROJECT_DIR/script/hpc_job_manager.py \
    --project-dir $PROJECT_DIR \
    submit-subject \
    --script $PROJECT_DIR/script/hpc_seed_connectivity_array_with_manifest.sh \
    --job-name seed_custom \
    --subjects "$SUBJECTS" \
    --seeds "$SEEDS" \
    --atlases difumo256 \
    2>&1 | grep -oE "Job ID: [0-9]+" | awk '{print $3}')

echo "Submitted custom seed job: $A"
```

### Performance Tuning

```bash
# Increase parallelism (use if HPC has capacity)
sbatch --array=1-40%30 script/hpc_seed_connectivity_array_with_manifest.sh

# Reduce time (if analysis runs faster than wall-clock)
sbatch --time=04:00:00 script/hpc_seed_connectivity_array_with_manifest.sh

# Request more memory (if hitting memory limits)
sbatch --mem=32G script/hpc_seed_connectivity_array_with_manifest.sh
```

## Reference

- **Full documentation:** `docs/HPC_WORKFLOW.md`
- **Manifest API:** `python3 script/hpc_manifest.py --help`
- **Job manager API:** `python3 script/hpc_job_manager.py --help`
- **SLURM docs:** `man sbatch`, `man squeue`, `man scontrol`
