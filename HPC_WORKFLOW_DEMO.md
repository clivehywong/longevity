# HPC Workflow Demonstration

This document shows a practical example of the HPC workflow in action.

## Scenario

Processing 40 subjects with 4 seeds using 2 atlases:
- **Subjects:** sub-033 to sub-072 (40 total)
- **Seeds:** dlpfc_l, dlpfc_r, anterior_insula, motor_cortex
- **Atlases:** difumo256, schaefer400
- **Total tasks:** 40 × 4 × 2 = 320 subject-level tasks

## Step 1: Start Pipeline

```bash
bash script/hpc_orchestrate_full_pipeline.sh
```

Output:
```
=========================================================================
HPC ORCHESTRATION: Master Full Pipeline
=========================================================================
Start time: Wed Apr 29 00:24:55 UTC 2025
Project: /home/clivewong/proj/longevity
Test mode: false
Submit group-level: true

Configuration:
  Subjects: 40 (sub-033...sub-072)
  Seeds: 4 (dlpfc_l...motor_cortex)
  Atlases: 2 (difumo256...schaefer400)

STEP 1: Submitting Subject-Level Jobs
======================================

[SUCCESS] Submitted local measures: 12345
[SUCCESS] Submitted seed connectivity: 12346 (depends on 12345)
[SUCCESS] Submitted between-network connectivity: 12347 (depends on 12346)

STEP 2: Submitting Synchronization Job
======================================

[SUCCESS] Submitted sync job: 12348 (depends on 12347)

STEP 3: Submitting Group-Level Analysis Jobs
=============================================

[SUCCESS] Submitted group-level analysis: 12349 (depends on 12348)

STEP 4: Job Dependency Chain
============================

Dependency chain (use 'squeue --dependency' to monitor):

    Local Measures (12345)
           ↓
    Seed Connectivity (12346)
           ↓
    Between-Network (12347)
           ↓
    Sync Results (12348)
           ↓
    Group Analysis (12349)

Monitor with: squeue -u clivewong
```

## Step 2: Monitor Progress

### Check Jobs in Queue
```bash
squeue -u $USER --priority
```

Output:
```
             JOBID PRIORITY      NAME    USER ST       TIME  NODES CPUS MIN_CPUS MIN_TMP_DISK END_TIME FEATURES OVER_SUBSCRIBE JOBID CONTIGUOUS PARTITION PRIORITY FLAGS STARTTIME ENDTIME DEPENDENCY
          12345_23    65536 local_mea clivewong R       2:15      1    4        4            0   None      *           OK* 12345_23        0*   default* 65536    NONE   2025-04-29T00:25:00   2025-04-29T00:27:30   None
          12345_24    65536 local_mea clivewong R       2:12      1    4        4            0   None      *           OK* 12345_24        0*   default* 65536    NONE   2025-04-29T00:25:03   2025-04-29T00:27:33   None
          12346_1    65536 seed_conn clivewong PD       0:00      1    4        4            0   None      *           OK* 12346_1        0*   default* 65536    NONE   2025-04-29T00:30:00   None          afterok:12345(1-40)
```

### Check Manifest Progress
```bash
python3 script/hpc_manifest.py --manifest results/.manifest.json status
```

Output (while jobs running):
```
================================================================================
HPC MANIFEST STATUS
================================================================================
Total tasks: 256  (not all submitted yet - local measures still running)
Analyses ready: 0

Seed-Atlas Progress:
--------------------------------------------------------------------------------
  dlpfc_l_difumo256                          24/ 40 ( 60.0%)   pending
  dlpfc_l_schaefer400                        24/ 40 ( 60.0%)   pending
  dlpfc_r_difumo256                          24/ 40 ( 60.0%)   pending
  dlpfc_r_schaefer400                        24/ 40 ( 60.0%)   pending
================================================================================
```

## Step 3: Check Completion Rate

```bash
python3 script/hpc_manifest.py --manifest results/.manifest.json check-ready \
    --seed dlpfc_l --atlas difumo256 --threshold 0.8
```

Output (before all complete):
```
Seed: dlpfc_l, Atlas: difumo256
Completion: 28/40 (70.0%)
Threshold: 80%
Ready for group analysis: NO

Missing 12 subject-sessions:
  - sub-045 ses-01 (NOT STARTED)
  - sub-047 ses-01 (NOT STARTED)
  - ... (10 more)
```

## Step 4: After Sync Completes

### View Sync Logs
```bash
tail -100 logs/hpc_sync_*.out
```

Output:
```
STEP 1: Syncing results from HPC
==================================
Syncing connectivity results...
receiving incremental file list
seed_based/dlpfc_l/sub-033_ses-01_zmap.nii.gz
seed_based/dlpfc_l/sub-034_ses-01_zmap.nii.gz
...
[INFO] Sync complete

STEP 2: Enforcing NFS Synchronization
======================================
[INFO] Flushing filesystem caches...
[INFO] Running sync command
[INFO] Waiting 5 seconds for NFS consistency...
[INFO] Verifying filesystem connectivity...
[SUCCESS] Filesystem is responsive

STEP 3: Validating Manifest Completion
========================================
[INFO] Checking completion status...
[SUCCESS] Manifest validation passed

STEP 4: Identifying Incomplete Tasks
=====================================
Checking dlpfc_l with difumo256:
  Completed: 38/40 (95.0%)
  Missing: 2 subjects
```

### Check Final Readiness
```bash
python3 script/hpc_manifest.py --manifest results/.manifest.json check-ready \
    --seed dlpfc_l --atlas difumo256
```

Output:
```
Seed: dlpfc_l, Atlas: difumo256
Completion: 38/40 (95.0%)
Threshold: 80%
Ready for group analysis: YES

(No missing subjects - all ready!)
```

## Step 5: Group Analysis Starts

After sync validates (38/40 = 95% > 80%), group analysis jobs automatically start.

### Monitor Group Jobs
```bash
squeue -u $USER | grep group_analysis
```

Output:
```
          12349_1 group_ana clivewong R       1:23      1   16       16            0   2025-04-29T00:35:00   *           OK* 12349_1        0*   default* 4294767296    NONE   None          None          None
          12349_2 group_ana clivewong R       1:20      1   16       16            0   2025-04-29T00:35:03   *           OK* 12349_2        0*   default* 4294767296    NONE   None          None          None
```

## Step 6: Final Manifest Report

```bash
python3 script/hpc_manifest.py --manifest results/.manifest.json status
```

Output (after all complete):
```
================================================================================
HPC MANIFEST STATUS
================================================================================
Total tasks: 320
Analyses ready: 8

Seed-Atlas Progress:
--------------------------------------------------------------------------------
  dlpfc_l_difumo256                          38/ 40 ( 95.0%) ✓ READY
  dlpfc_l_schaefer400                        39/ 40 ( 97.5%) ✓ READY
  dlpfc_r_difumo256                          36/ 40 ( 90.0%) ✓ READY
  dlpfc_r_schaefer400                        38/ 40 ( 95.0%) ✓ READY
  anterior_insula_difumo256                  35/ 40 ( 87.5%) ✓ READY
  anterior_insula_schaefer400                37/ 40 ( 92.5%) ✓ READY
  motor_cortex_difumo256                     38/ 40 ( 95.0%) ✓ READY
  motor_cortex_schaefer400                   39/ 40 ( 97.5%) ✓ READY
================================================================================
```

## Handling Failures

If any subject-level tasks fail:

### Check Failed Tasks
```bash
python3 script/hpc_manifest.py --manifest results/.manifest.json missing \
    --seed dlpfc_r --atlas difumo256
```

Output:
```
Seed: dlpfc_r, Atlas: difumo256
Total incomplete: 4
Failed: 2

Missing subject-sessions:
  - sub-045 ses-01 (FAILED)
  - sub-052 ses-01 (FAILED)
  - sub-064 ses-01 (NOT STARTED)
  - sub-070 ses-01 (NOT STARTED)
```

### Retry Failed Subjects
```bash
python3 script/hpc_job_manager.py --project-dir /home/clivewong/proj/longevity \
    submit-subject \
    --script script/hpc_seed_connectivity_array_with_manifest.sh \
    --job-name retry_seed_dlpfc_r \
    --subjects sub-045,sub-052 \
    --seeds dlpfc_r \
    --atlases difumo256
```

Output:
```
[INFO] Submitting job array: sbatch --array=1-2%20 ...
[SUCCESS] Submitted job array: 12350
Job ID: 12350
```

## Key Insights

### 1. Dependency Chain Prevents Partial Data
```
Local Measures COMPLETE
  → Seed Connectivity START (afterok:LocalMeasures)
    → Between-Network START (afterok:SeedConnectivity)
      → Sync START (afterok:BetweenNetwork)
        → Group Analysis START (afterok:Sync)
```

Without dependencies, Group Analysis might start before Sync completes, reading partial data.

### 2. Manifest Validates Readiness
```
Manifest checks:
  dlpfc_l: 38/40 (95%) ≥ 80% → READY ✓
  dlpfc_r: 36/40 (90%) ≥ 80% → READY ✓
  ...
  
If any < 80%, Group Analysis waits and user is alerted with missing subjects.
```

### 3. NFS Safety Prevents Race Conditions
```
Timeline:
  [Subject tasks writing to NFS]
  [Last subject finishes at 1:23:45]
  [Sync: rsync begins at 1:24:00]  ← copies data
  [Sync: cache flush at 1:24:30]   ← forces write to disk
  [Sync: sleep(5) at 1:24:30]      ← waits for NFS
  [Group analysis reads at 1:24:35] ← guaranteed complete data
```

### 4. Logging Trail for Debugging
```
logs/
  ├── orchestration_*.log        ← Full pipeline execution
  ├── job_submissions.log        ← JSON records of all submissions
  ├── job_retries.log            ← Retry attempts with reasons
  ├── hpc_sync_*.out             ← Sync details (rsync, nfs, validation)
  └── seed_connectivity_*.out    ← Individual task logs
```

## Common Queries

### "Is dlpfc_l analysis ready?"
```bash
python3 script/hpc_manifest.py check-ready \
    --seed dlpfc_l --atlas difumo256
```

### "Which subjects are missing for motor_cortex?"
```bash
python3 script/hpc_manifest.py missing \
    --seed motor_cortex --atlas difumo256
```

### "What's the overall status?"
```bash
python3 script/hpc_manifest.py status
```

### "Did sub-045 fail or not start?"
```bash
python3 script/hpc_manifest.py status | grep sub-045
# Or check manifest directly
cat results/.manifest.json | python3 -m json.tool | grep sub-045 -A 5
```

---

This demonstration shows how the HPC workflow:
1. ✓ Prevents partial data via job dependencies
2. ✓ Validates completion before proceeding
3. ✓ Enforces NFS safety
4. ✓ Provides clear failure identification
5. ✓ Enables automatic retry
6. ✓ Maintains full audit trail
