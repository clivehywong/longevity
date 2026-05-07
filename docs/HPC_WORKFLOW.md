# HPC Workflow: Robust Synchronization and Failure Handling

## Overview

This document explains the HPC workflow system for the longevity neuroimaging project, including:

- **Manifest-based tracking** — Records completion state for all tasks
- **Job dependencies** — Prevents race conditions via SLURM's `--depend` flag
- **NFS synchronization** — Enforces filesystem consistency before group analysis
- **Retry logic** — Automatically handles transient failures
- **Comprehensive logging** — Full audit trail of job submissions and completions

## Architecture

### Components

#### 1. **Manifest Manager** (`script/hpc_manifest.py`)

Tracks completion state of all HPC tasks in a JSON manifest file.

**Key Classes:**
- `ManifestManager` — Manages `.manifest.json` with task tracking

**Key Methods:**
- `record_completion()` — Record task completion/failure
- `get_completion_rate()` — Get (completed, total, percentage)
- `is_ready_for_group_analysis()` — Check if threshold met (default 80%)
- `get_missing_subjects()` — List incomplete subject-sessions
- `get_failed_subjects()` — List failed subject-sessions

**Usage:**

```bash
# Record successful task
python3 script/hpc_manifest.py --manifest results/.manifest.json record \
    --subject sub-033 --session ses-01 --seed dlpfc_l --atlas difumo256 \
    --status complete --job-id 12345

# Check if ready for group analysis
python3 script/hpc_manifest.py --manifest results/.manifest.json check-ready \
    --seed dlpfc_l --atlas difumo256

# List missing subjects
python3 script/hpc_manifest.py --manifest results/.manifest.json missing \
    --seed dlpfc_l --atlas difumo256

# View full status
python3 script/hpc_manifest.py --manifest results/.manifest.json status
```

**Manifest JSON Structure:**

```json
{
  "created_at": "2025-04-24T10:30:00",
  "updated_at": "2025-04-24T10:35:00",
  "tasks": {
    "sub-033_ses-01_dlpfc_l_difumo256": {
      "subject_id": "sub-033",
      "session": "ses-01",
      "seed": "dlpfc_l",
      "atlas": "difumo256",
      "status": "complete",
      "completed_at": "2025-04-24T10:35:00",
      "metadata": {
        "job_id": "12345",
        "output_path": "/path/to/output"
      }
    }
  },
  "analyses_ready": {
    "dlpfc_l_difumo256": {
      "ready_at": "2025-04-24T10:35:00",
      "completion_status": [28, 30, 93.3]
    }
  }
}
```

#### 2. **Job Manager** (`script/hpc_job_manager.py`)

Manages SLURM job submission with dependencies and retry logic.

**Key Classes:**
- `HpcJobManager` — Submits and tracks jobs
- `JobStatus` — Enum for job states (QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED)

**Key Methods:**
- `submit_subject_level_jobs()` — Submit array jobs for subjects
- `submit_group_level_jobs()` — Submit jobs dependent on subject-level completion
- `submit_with_retry()` — Submit with automatic retry on failure
- `get_job_status()` — Query job status via SLURM
- `wait_for_job()` — Block until job completes

**Usage:**

```bash
# Submit subject-level jobs
python3 script/hpc_job_manager.py \
    --project-dir /home/clivewong/proj/longevity \
    submit-subject \
    --script script/hpc_seed_connectivity_array_with_manifest.sh \
    --job-name seed_connectivity \
    --subjects sub-033,sub-034,sub-035 \
    --seeds dlpfc_l,dlpfc_r \
    --atlases difumo256

# Submit group-level jobs with dependency
python3 script/hpc_job_manager.py \
    --project-dir /home/clivewong/proj/longevity \
    submit-group \
    --script script/hpc_group_analysis_array.sh \
    --job-name group_analysis \
    --subject-job-id 12345 \
    --seeds dlpfc_l,dlpfc_r \
    --atlases difumo256

# Check job status
python3 script/hpc_job_manager.py --project-dir /home/clivewong/proj/longevity \
    status --job-id 12345

# Wait for job
python3 script/hpc_job_manager.py --project-dir /home/clivewong/proj/longevity \
    wait --job-id 12345 --max-wait 86400
```

#### 3. **Sync Script** (`script/hpc_sync.sh`)

Synchronizes results from HPC and validates manifest before group analysis.

**Steps:**
1. Sync results from HPC via rsync (with checksum verification)
2. Enforce NFS synchronization (filesystem cache flush)
3. Validate manifest completion against threshold
4. List missing/failed subjects for optional retry

**Features:**
- Conservative 5-second wait after NFS sync for consistency
- Filesystem responsiveness check
- Detailed logging to timestamped log file
- Graceful handling of missing manifest

**Usage:**

```bash
# Submit as SLURM job (automatically)
sbatch --depend=afterok:12345 script/hpc_sync.sh
```

#### 4. **Master Orchestration** (`script/hpc_orchestrate_full_pipeline.sh`)

Submits entire pipeline with proper job dependencies.

**Job Chain:**

```
Local Measures (job A)
    ↓ depends on A
Seed Connectivity (job B)
    ↓ depends on B
Between-Network (job C)
    ↓ depends on C
Sync Results (job D)
    ↓ depends on D
Group Analysis (job E)
```

**Usage:**

```bash
# Full pipeline
bash script/hpc_orchestrate_full_pipeline.sh

# Test mode (2 subjects)
bash script/hpc_orchestrate_full_pipeline.sh --test

# Skip group-level jobs
bash script/hpc_orchestrate_full_pipeline.sh --no-group
```

**Environment Variables:**

```bash
# Override defaults (optional)
export PROJECT_DIR="/home/clivewong/proj/longevity"
export SUBJECTS="sub-033,sub-034,sub-035"
export SEEDS="dlpfc_l,dlpfc_r"
export ATLASES="difumo256"
bash script/hpc_orchestrate_full_pipeline.sh
```

## How It Works

### Preventing Partial Data Propagation

**Problem:** Without dependencies, group analysis can start before subject-level jobs complete, reading partial/missing data.

**Solution:** Use SLURM job dependencies with validation.

1. **Subject-level jobs** submit as job array
2. **Sync job** depends on subject-level jobs (`--depend=afterok:JOBID`)
3. **Sync validates** manifest completion (e.g., 80%+)
4. **Sync enforces** NFS sync (filesystem cache flush)
5. **Group analysis** depends on sync job completing

This prevents group analysis from starting until:
- Subject-level jobs complete
- Results are synced back
- NFS caches are flushed
- Manifest validation passes

### Manifest Validation

**Completion Rate Calculation:**

```python
completed, total, percentage = manifest.get_completion_rate(seed, atlas)
# e.g., (28, 30, 93.3) = 28 of 30 subjects completed, 93.3%

# Check readiness (default threshold 80%)
is_ready = manifest.is_ready_for_group_analysis(seed, atlas, min_threshold=0.8)
```

**Missing Subject Identification:**

```python
missing = manifest.get_missing_subjects(seed, atlas)
# Returns: [('sub-033', 'ses-01'), ('sub-034', 'ses-01')]

failed = manifest.get_failed_subjects(seed, atlas)
# Returns: [('sub-033', 'ses-01')]
```

### Job Dependencies Chain

**SLURM Dependency Syntax:**

```bash
# Job B starts only after Job A completes successfully
sbatch --depend=afterok:JOB_A job_b.sh

# Job B starts only after Job A completes (success or failure)
sbatch --depend=afterany:JOB_A job_b.sh

# Job B starts after Job A fails
sbatch --depend=afternotok:JOB_A job_b.sh

# Multiple dependencies
sbatch --depend=afterok:JOB_A:JOB_B job_c.sh
```

**Monitoring Dependencies:**

```bash
# Check queued jobs and their dependencies
squeue -u $USER --priority

# View dependency chain
squeue -u $USER --dependency

# Cancel entire chain
scancel JOB_A  # Cancels JOB_A and all dependent jobs
```

### NFS Synchronization

**Why It's Needed:**

Network filesystems (NFS) cache data for performance. Without synchronization:
- Write completes locally but isn't flushed to shared storage
- Reader sees stale/partial data
- Race conditions between writer and reader

**Solution:**

```bash
sync                  # Flush all filesystem caches
sleep 5               # Conservative wait for NFS consistency
# Then read data
```

**Location in Workflow:**

```bash
# Sync results from HPC to local
rsync -avz HPC:results/ local/results/

# Flush filesystem
sync
sleep 5

# NOW safe to read for group analysis
```

## Updating Existing SLURM Scripts

To add manifest tracking to existing scripts:

### 1. Add Output Logging

```bash
#!/bin/bash
#SBATCH --output=logs/job_name_%A_%a.out    # %A = array job ID, %a = array task
#SBATCH --error=logs/job_name_%A_%a.err
```

### 2. Get Task Parameters

```bash
# For array jobs, calculate subject/seed/atlas for this task
TASK_INDEX=$((SLURM_ARRAY_TASK_ID - 1))
SUBJECT="${SUBJECT_ARRAY[$TASK_INDEX]}"
SEED="${SEED_ARRAY[$TASK_INDEX]}"
ATLAS="${ATLAS_ARRAY[$TASK_INDEX]}"
```

### 3. Run Analysis

```bash
if python script/analysis.py --subject "$SUBJECT" --seed "$SEED"; then
    EXIT_CODE=0
    STATUS="complete"
else
    EXIT_CODE=$?
    STATUS="failed"
fi
```

### 4. Record in Manifest

```bash
python3 script/hpc_manifest.py \
    --manifest "$MANIFEST_FILE" \
    record \
    --subject "$SUBJECT" \
    --session "ses-01" \
    --seed "$SEED" \
    --atlas "$ATLAS" \
    --status "$STATUS" \
    --job-id "$SLURM_JOB_ID"

exit $EXIT_CODE
```

## Failure Recovery

### Identifying Failed Tasks

```bash
# List failed subjects for a seed-atlas combination
python3 script/hpc_manifest.py \
    --manifest results/.manifest.json \
    missing --seed dlpfc_l --atlas difumo256
```

### Retrying Failed Subjects

```python
# Using job manager with retry logic
manager = HpcJobManager('/home/clivewong/proj/longevity')
job_id = manager.submit_with_retry(
    script='script/hpc_seed_connectivity_array_with_manifest.sh',
    subject_id='sub-033',
    session='ses-01',
    seed='dlpfc_l',
    atlas='difumo256',
    max_retries=3,
    wait_time=60
)
```

### Manual Resubmission

```bash
# After fixing the issue, resubmit specific subject
sbatch --array=1 \
    --job-name="retry_sub-033" \
    script/hpc_seed_connectivity_array_with_manifest.sh

# Delete old failed entries from manifest
python3 script/hpc_manifest.py --manifest results/.manifest.json \
    reset --subject sub-033 --seed dlpfc_l --atlas difumo256
```

## Monitoring and Debugging

### Check Job Status

```bash
# View current jobs
squeue -u $USER

# View job details
scontrol show job JOB_ID

# View job history (completed/failed)
sacct -u $USER --starttime=2025-04-24
```

### Check Manifest Progress

```bash
# Full status report
python3 script/hpc_manifest.py --manifest results/.manifest.json status

# Check specific seed-atlas
python3 script/hpc_manifest.py --manifest results/.manifest.json check-ready \
    --seed dlpfc_l --atlas difumo256 --threshold 0.8

# List incomplete tasks
python3 script/hpc_manifest.py --manifest results/.manifest.json missing \
    --seed dlpfc_l --atlas difumo256
```

### View Job Logs

```bash
# Recent sync logs
tail -f logs/hpc_sync_*.out

# Job array logs with task IDs
tail -f logs/seed_connectivity_JOBID_*.out

# Job submission log
cat logs/job_submissions.log | python3 -m json.tool

# Retry log
cat logs/job_retries.log | python3 -m json.tool
```

### Debug Manifest Issues

```bash
# View full manifest file
cat results/.manifest.json | python3 -m json.tool

# Count completed tasks
python3 -c "
import json
with open('results/.manifest.json') as f:
    data = json.load(f)
    for key, progress in data['seed_atlas_progress'].items():
        print(f'{key}: {progress[\"completed\"]}/{progress[\"total\"]}')"
```

## Best Practices

### 1. Always Use Dependencies

❌ **BAD:**
```bash
sbatch job_a.sh
sbatch job_b.sh
sbatch job_c.sh
```

✅ **GOOD:**
```bash
A=$(sbatch job_a.sh | awk '{print $NF}')
B=$(sbatch --depend=afterok:$A job_b.sh | awk '{print $NF}')
C=$(sbatch --depend=afterok:$B job_c.sh | awk '{print $NF}')
```

### 2. Always Record Completion

❌ **BAD:**
```bash
python script/analysis.py
# No manifest record
```

✅ **GOOD:**
```bash
python script/analysis.py
python3 script/hpc_manifest.py record \
    --subject "$SUBJECT" --seed "$SEED" --status "complete"
```

### 3. Validate Before Group Analysis

❌ **BAD:**
```bash
# Subject-level done, immediately run group analysis
sbatch group_analysis.sh
```

✅ **GOOD:**
```bash
# Subject-level done, sync and validate
sbatch --depend=afterok:$SUBJECT_JOB hpc_sync.sh
# Then group analysis (depends on sync)
sbatch --depend=afterok:$SYNC_JOB group_analysis.sh
```

### 4. Log Everything

```bash
# Capture all output
exec &> >(tee -a "$LOG_FILE")

# Log key events
echo "[$(date)] Starting analysis for $SUBJECT"
echo "[$(date)] Completed analysis, exit code $?"
```

### 5. Test Before Production

```bash
# Use test mode for scripts
bash script/hpc_orchestrate_full_pipeline.sh --test

# Verify output
python3 script/hpc_manifest.py --manifest results/.manifest.json status
```

## Troubleshooting

### Issue: Group analysis starts before subject-level completes

**Cause:** Missing or incorrect dependency specification

**Solution:**
```bash
# Verify dependency chain
squeue -u $USER --dependency

# Check job submission command
grep "submit-group" logs/job_submissions.log
```

### Issue: Manifest shows incomplete even when jobs finished

**Cause:** Jobs didn't record completion (missing manifest call)

**Solution:**
```bash
# Manually record completed tasks
for subj in sub-033 sub-034; do
    python3 script/hpc_manifest.py --manifest results/.manifest.json record \
        --subject $subj --session ses-01 --seed dlpfc_l --atlas difumo256 \
        --status complete
done
```

### Issue: NFS sync timeout

**Cause:** Too many files or slow network

**Solution:**
```bash
# Increase wait time in hpc_sync.sh
sleep 10  # Instead of 5

# Or sync in batches
rsync --include-from=include.txt results/ local/
```

### Issue: Job array fails on specific task

**Cause:** Task-specific input data issue or resource unavailable

**Solution:**
```bash
# Check task log
cat logs/seed_connectivity_JOBID_TASKID.out

# Identify failed task
python3 script/hpc_manifest.py --manifest results/.manifest.json missing \
    --seed dlpfc_l --atlas difumo256

# Resubmit just that task
sbatch script/hpc_seed_connectivity_array_with_manifest.sh
```

## Example Workflow

### Complete Example

```bash
# 1. Start orchestration with test mode
bash script/hpc_orchestrate_full_pipeline.sh --test

# 2. Monitor job submission
watch -n 5 'squeue -u $USER'

# 3. Check manifest progress
python3 script/hpc_manifest.py --manifest results/.manifest.json status

# 4. After completion, verify sync worked
ls -la results/seed_based/
ls -la results/local_measures/

# 5. Check final manifest
python3 script/hpc_manifest.py --manifest results/.manifest.json check-ready \
    --seed dlpfc_l --atlas difumo256

# 6. If ready, manually trigger group analysis
sbatch --array=1-4%2 script/hpc_group_analysis_array.sh

# 7. Monitor everything
tail -f logs/orchestration_*.log
```

## References

- **SLURM Documentation:** `man sbatch`, `man squeue`, `man scontrol`
- **NFS Synchronization:** `man sync`, `man fsync`
- **Job Dependencies:** `sinfo -p partition --format "%N %c %m"`

