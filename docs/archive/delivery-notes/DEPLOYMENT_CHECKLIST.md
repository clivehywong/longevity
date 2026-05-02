# HPC Subject-Level Job Submission - Deployment Checklist

## Pre-Deployment Verification ✓

- [x] Main script created: `script/hpc_submit_subject_level.py` (26 KB)
- [x] SLURM template created: `script/templates/hpc_subject_level_template.sh` (8.4 KB)
- [x] Documentation complete:
  - [x] `HPC_SUBJECT_LEVEL_IMPLEMENTATION.md` - Complete implementation guide
  - [x] `script/HPC_SUBJECT_LEVEL_README.md` - Full user manual
  - [x] `script/QUICKSTART_HPC_SUBJECT_LEVEL.md` - Quick reference
- [x] All tests passed (6/6 categories)
- [x] Module imports without errors
- [x] CLI interface verified
- [x] Integration with existing components verified

## Quick Command Reference

### Validation & Testing

```bash
# Verify configuration
python script/hpc_submit_subject_level.py --summary

# Validate all requirements
python script/hpc_submit_subject_level.py --validate

# Preview generated SLURM script (test mode, 2 subjects)
python script/hpc_submit_subject_level.py --dry-run --test-mode
```

### Job Submission

```bash
# Submit test job (2 subjects only)
python script/hpc_submit_subject_level.py --test-mode

# Submit production job (all 44 subjects)
python script/hpc_submit_subject_level.py

# Monitor job status
python script/hpc_submit_subject_level.py --check-job <JOB_ID>
```

### Manifest Operations

```bash
# Check overall completion status
python script/hpc_manifest.py --manifest results/.manifest.json status

# Check if ready for group analysis (80% threshold)
python script/hpc_manifest.py --manifest results/.manifest.json \
    check-ready --seed Motor_Cortex --atlas DiFuMo256

# List missing subjects for a seed-atlas pair
python script/hpc_manifest.py --manifest results/.manifest.json \
    missing --seed Motor_Cortex --atlas DiFuMo256
```

## Expected Execution Flow

### Step 1: Validate Setup (5 min)
```bash
cd /home/clivewong/proj/longevity
python script/hpc_submit_subject_level.py --validate
```
**Expected output**: All 6 checks pass

### Step 2: Test with 2 Subjects (10 min)
```bash
python script/hpc_submit_subject_level.py --test-mode
# Job ID: 12345678
```

### Step 3: Monitor Test (Real-time)
```bash
watch -n 10 "squeue -j 12345678"
tail -f logs/subject_level_*.log
```

### Step 4: Submit Full Production (< 1 min)
```bash
python script/hpc_submit_subject_level.py
# Job ID: 12346789
```

### Step 5: Monitor Production (Real-time)
```bash
watch -n 30 "squeue -j 12346789"
python script/hpc_submit_subject_level.py --check-job 12346789
```

### Step 6: Check Completion (Periodic)
```bash
python script/hpc_manifest.py --manifest results/.manifest.json status
```

### Step 7: Verify Group-Level Readiness (Final)
```bash
# For each seed-atlas combination
python script/hpc_manifest.py --manifest results/.manifest.json \
    check-ready --seed <SEED> --atlas DiFuMo256 --threshold 0.8
```

## Job Array Structure

```
SLURM Array: 1-44%20
├── Index 1   → sub-033 (ses-01, ses-02)
├── Index 2   → sub-034 (ses-01, ses-02)
├── ...
└── Index 44  → sub-082 (ses-01, ses-02)

Per-Job Analyses:
├── Local Measures (fALFF, ReHo)
├── Seed Connectivity (17 seeds × 2 atlases)
└── Network Connectivity (2 atlases)

Total Jobs: 88 subject-sessions
Max Parallel: 20
Array Time Limit: 6 hours
Expected Wall Time: 15-20 minutes
```

## Output Locations

```
results/
├── local_measures/
│   └── sub-{subject}_ses-{session}/
│       ├── *_fALFF.nii.gz
│       └── *_ReHo.nii.gz
├── seed_based/
│   ├── DiFuMo256/
│   │   ├── {seed}/sub-{subject}_ses-{session}/
│   │   └── ...
│   └── Schaefer400/
│       └── ...
├── network_connectivity/
│   ├── DiFuMo256/
│   │   └── sub-{subject}_ses-{session}/
│   └── Schaefer400/
│       └── ...
└── .manifest.json
```

## Logging

```
logs/
├── subject_level_{JOB_ID}_{ARRAY_ID}_{SUBJECT}.log
├── subject_level_{JOB_ID}_{ARRAY_ID}.out
├── subject_level_{JOB_ID}_{ARRAY_ID}.err
└── .{subject}_{session}_{analysis}.failed  (if failed)
```

## Troubleshooting Quick Links

| Issue | Quick Fix |
|-------|-----------|
| Command not found | `cd /home/clivewong/proj/longevity` first |
| Validation fails | Run `--validate` to see specific failures |
| SLURM unavailable | Use `--dry-run` to test script generation |
| fMRIPrep missing | Run on HPC system with preprocessed outputs |
| Disk space low | Check `df -h` - need ~500 GB |
| Job submission error | Check SLURM partition with `sinfo` |

## Related Files

- Main implementation: `script/hpc_submit_subject_level.py`
- Configuration: `.github/connectivity_config.yaml`
- Manifest system: `script/hpc_manifest.py`
- Full documentation: `script/HPC_SUBJECT_LEVEL_README.md`
- Quick start: `script/QUICKSTART_HPC_SUBJECT_LEVEL.md`
- Implementation guide: `HPC_SUBJECT_LEVEL_IMPLEMENTATION.md`

## Deployment Status

✅ **READY FOR PRODUCTION**

All requirements met:
- Code implementation complete and tested
- Documentation comprehensive
- Integration verified
- CLI interface functional
- Error handling in place
- Performance optimized

Ready to submit jobs to SLURM cluster.
