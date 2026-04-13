# CONN Parallel Processing Guide

## Overview

The CONN batch script supports parallel processing to significantly speed up preprocessing and analysis. With 24 subjects × 2 sessions = 48 datasets, parallel processing can reduce total runtime from days to hours.

## Quick Start

### Local Parallel Processing (Easiest)

```matlab
% Use 4 parallel workers on your local machine
conn_batch_longitudinal('full', 4)

% Use 8 parallel workers (recommended if you have 8+ CPU cores)
conn_batch_longitudinal('full', 8)
```

### Setup Only (No Processing)

```matlab
% Setup project without processing (for verification)
conn_batch_longitudinal('setup')
```

## Parallelization Options

### 1. Local Parallel Processing (MATLAB Parallel Computing Toolbox)

**Requirements**: MATLAB Parallel Computing Toolbox

**Pros**:
- Easiest to set up
- No cluster configuration needed
- Good for 4-8 cores

**Cons**:
- Limited by your computer's CPU cores
- Uses your local machine resources

**Usage**:
```matlab
% Check if you have Parallel Computing Toolbox
ver('parallel')

% Start parallel pool manually (optional)
parpool('local', 4)

% Run CONN with 4 parallel jobs
conn_batch_longitudinal('full', 4)
```

**Recommended number of jobs**:
- 4 jobs for 4-core CPU
- 8 jobs for 8+ core CPU
- Don't exceed your CPU core count

### 2. Cluster/HPC Parallel Processing

**Requirements**:
- Access to cluster (SLURM, PBS, SGE, LSF, etc.)
- MATLAB Parallel Server (on cluster)

**Pros**:
- Can run 10-24 jobs simultaneously
- Frees up your local machine
- Much faster for large datasets

**Cons**:
- Requires cluster setup
- Need to configure CONN parallel profile

**Usage**:
```matlab
% First, configure cluster profile in CONN GUI:
% 1. Open CONN: conn
% 2. Go to Tools → Grid Settings
% 3. Create new profile or select existing one
% 4. Configure: scheduler type, queue, walltime, etc.

% Then run with cluster profile
conn_batch_longitudinal('full', 12, 'my_cluster_profile')
```

### 3. Background Processing

Run preprocessing in background and continue working:

```matlab
% Modify script to enable background mode
% Edit conn_batch_longitudinal.m, add:
% batch.parallel.immediatereturn = 1;

% Check job status
conn('grid', 'status')

% View pending jobs
conn('gui_tools', 'seependingjobs')
```

## Parallelization Stages

CONN can parallelize different processing stages:

| Stage | Parallelizable | Speed Gain |
|-------|----------------|------------|
| Setup | ❌ No | - |
| Preprocessing | ✅ Yes | High (subjects run independently) |
| Denoising | ✅ Yes | High (subjects run independently) |
| ROI extraction | ✅ Yes | Medium |
| First-level analysis | ✅ Yes | Medium |
| Second-level analysis | ❌ No | - |

## Performance Estimates

Approximate processing times for 24 subjects × 2 sessions:

| Configuration | Preprocessing | Denoising | Analysis | Total |
|---------------|---------------|-----------|----------|-------|
| **Local (no parallel)** | ~48 hours | ~12 hours | ~6 hours | **~66 hours** |
| **Local (4 jobs)** | ~12 hours | ~3 hours | ~2 hours | **~17 hours** |
| **Local (8 jobs)** | ~6 hours | ~1.5 hours | ~1 hour | **~8.5 hours** |
| **Cluster (16 jobs)** | ~3 hours | ~45 min | ~30 min | **~4 hours** |

*Note*: Times are estimates and depend on CPU speed, I/O performance, and workload.

## Best Practices

### 1. Start Small
```matlab
% Test on 2-3 subjects first
batch.subjects = [1 2 3];  % Add this line in the script
conn_batch_longitudinal('full', 4)
```

### 2. Monitor Resources
```matlab
% Check CPU usage during parallel processing
% On macOS/Linux terminal:
top -o cpu

% On MATLAB:
parpool('local', 4)
parallel.pool.DataQueue % Monitor worker status
```

### 3. Memory Considerations
- Each parallel job needs ~4-8 GB RAM
- 4 jobs = ~16-32 GB total RAM needed
- Don't oversubscribe your RAM

### 4. Disk I/O
- Parallel jobs create heavy disk I/O
- Use SSD if possible
- External HDDs may bottleneck

## Troubleshooting

### "Parallel Computing Toolbox not found"

**Solution**: Run locally without parallelization
```matlab
conn_batch_longitudinal('full', 0)  % N=0 means no parallelization
```

Or install Parallel Computing Toolbox.

### Jobs fail with memory errors

**Solution**: Reduce number of parallel jobs
```matlab
% Try 2-3 jobs instead of 4-8
conn_batch_longitudinal('full', 2)
```

### Cluster jobs timeout

**Solution**: Increase walltime in cluster profile settings
- CONN GUI → Tools → Grid Settings
- Increase "cmd_submitoptions" walltime parameter

### Jobs stuck in queue

**Check status**:
```matlab
conn('grid', 'status')
```

**Cancel stuck jobs**:
```matlab
conn('grid', 'cancel')
```

## Example Workflows

### Workflow 1: Local Computer (Recommended)

```matlab
% Step 1: Setup and verify (no processing)
conn_batch_longitudinal('setup')
% → Opens CONN GUI, verify all subjects loaded

% Step 2: Test preprocessing on 2 subjects
% Edit script: batch.subjects = [1 2];
conn_batch_longitudinal('full', 2)

% Step 3: Run full preprocessing with 4 jobs
% Edit script: remove batch.subjects line
conn_batch_longitudinal('full', 4)

% Step 4: Check QA plots in CONN GUI
conn
conn('load', '/Volumes/Work/Work/long/conn_project/conn_longitudinal.mat')
% → Quality Assurance → Check all QA plots
```

### Workflow 2: HPC Cluster (Advanced)

```bash
# On cluster, create SLURM job script
cat > conn_parallel.sh <<'EOF'
#!/bin/bash
#SBATCH --job-name=conn_preproc
#SBATCH --nodes=1
#SBATCH --ntasks=12
#SBATCH --mem=96G
#SBATCH --time=12:00:00

module load matlab
matlab -nodisplay -r "conn_batch_longitudinal('full', 12); exit"
EOF

sbatch conn_parallel.sh
```

## Configuration Files

### Create Custom Parallel Profile

In CONN GUI:
1. **Tools** → **Grid Settings**
2. Click **New Profile**
3. Configure:
   - **Profile name**: `local_4cores`
   - **Scheduler**: Local
   - **Number of workers**: 4
   - **Memory per job**: 8 GB
4. Save profile
5. Use in script:
   ```matlab
   conn_batch_longitudinal('full', 4, 'local_4cores')
   ```

## Monitoring Progress

### During Execution

```matlab
% In another MATLAB window or terminal
conn('grid', 'status')  % Check job status
```

### Check Log Files

Log files are created in:
```
/Volumes/Work/Work/long/conn_project/
├── data/
├── results/
└── logs/  # Parallel job logs here
```

### Real-time Progress

```matlab
% Enable verbose output in script
batch.Setup.overwrite = 'Yes';
% Watch preprocessing progress in MATLAB console
```

## Summary

**Recommended approach for this dataset**:

1. ✅ **Local with 4-8 jobs** (if you have Parallel Computing Toolbox)
   ```matlab
   conn_batch_longitudinal('full', 4)
   ```

2. ✅ **Cluster with 12-16 jobs** (if you have HPC access)
   ```matlab
   conn_batch_longitudinal('full', 12, 'cluster_profile')
   ```

3. ⚠️ **Local without parallelization** (fallback if no toolbox)
   ```matlab
   conn_batch_longitudinal('full', 0)
   ```

**Time savings**: Parallel processing can reduce 66 hours → 8-17 hours (4-8× speedup)
