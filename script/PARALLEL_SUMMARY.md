# Parallel Processing - Quick Reference

## ✅ Yes! Parallel processing is now supported

The `conn_batch_longitudinal.m` script has been updated to support parallel processing.

## Quick Commands

### Check if you have Parallel Computing Toolbox

```matlab
% In MATLAB command window
ver('parallel')

% If installed, you'll see:
% Parallel Computing Toolbox Version X.X
```

### Run with Parallel Processing

```matlab
% Setup only (verify first)
conn_batch_longitudinal('setup')

% Run with 4 parallel jobs (RECOMMENDED)
conn_batch_longitudinal('full', 4)

% Run with 8 parallel jobs (if you have 8+ CPU cores)
conn_batch_longitudinal('full', 8)

% Run sequentially (no parallelization)
conn_batch_longitudinal('full', 0)
```

## Performance Gains

| Configuration | Estimated Time | Speedup |
|---------------|----------------|---------|
| Sequential (N=0) | ~66 hours | 1× |
| 4 parallel jobs | ~17 hours | **4×** |
| 8 parallel jobs | ~8.5 hours | **8×** |
| 16 parallel jobs (cluster) | ~4 hours | **16×** |

## System Requirements

### For Local Parallel (4-8 jobs)

- ✅ MATLAB Parallel Computing Toolbox
- ✅ 16-32 GB RAM (4-8 GB per job)
- ✅ Multi-core CPU (4-8 cores recommended)
- ✅ SSD storage (recommended for I/O performance)

### For Cluster Parallel (12-24 jobs)

- ✅ HPC cluster access (SLURM, PBS, SGE, etc.)
- ✅ MATLAB Parallel Server on cluster
- ✅ Configured CONN parallel profile

## What Gets Parallelized?

CONN parallelizes these stages across subjects:

1. ✅ **Preprocessing** (biggest time saver)
   - Realignment
   - Normalization
   - Smoothing
   - ART detection

2. ✅ **Denoising**
   - aCompCor extraction
   - Confound regression
   - Filtering

3. ✅ **ROI extraction**
   - BOLD signal extraction from atlases

4. ✅ **First-level analysis**
   - ROI-to-ROI connectivity matrices

## How It Works

```
Without Parallel (Sequential):
Subject 1 → Subject 2 → Subject 3 → ... → Subject 24
[========================================] 66 hours

With 4 Parallel Jobs:
Job 1: Sub 1 → Sub 5 → Sub 9  → ...
Job 2: Sub 2 → Sub 6 → Sub 10 → ...
Job 3: Sub 3 → Sub 7 → Sub 11 → ...
Job 4: Sub 4 → Sub 8 → Sub 12 → ...
[==========] 17 hours
```

## Common Issues

### "Parallel Computing Toolbox not found"

**Solution 1**: Run without parallelization
```matlab
conn_batch_longitudinal('full', 0)
```

**Solution 2**: Install Parallel Computing Toolbox

### Out of Memory

**Solution**: Reduce number of parallel jobs
```matlab
% Try 2 instead of 4
conn_batch_longitudinal('full', 2)
```

### Jobs stuck/frozen

**Check MATLAB pool**:
```matlab
delete(gcp('nocreate'))  % Delete current pool
conn_batch_longitudinal('full', 4)  % Try again
```

## Best Practice Workflow

```matlab
% Step 1: Setup and verify (no processing)
conn_batch_longitudinal('setup')
% → Opens CONN GUI, check all looks good

% Step 2: Close MATLAB, restart fresh

% Step 3: Run with parallel processing
conn_batch_longitudinal('full', 4)

% Step 4: Monitor in CONN GUI (separate MATLAB window)
conn
conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat')
% Tools → See Pending Jobs
```

## Monitoring Progress

While parallel jobs are running:

```matlab
% In another MATLAB window
conn('grid', 'status')  % Check job status

% View pending jobs
conn gui_tools seependingjobs
```

## References

- 📖 Full guide: `PARALLEL_PROCESSING_GUIDE.md`
- 📖 Main README: `README_CONN.md`
- 📖 CONN documentation: https://web.conn-toolbox.org/resources/parallelization
