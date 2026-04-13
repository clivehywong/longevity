# HPC Seed-Based Connectivity Analysis Guide

## Overview

The seed-based connectivity analysis can be run on EdUHK HPC for significantly faster processing:

| Platform | Workers | RAM | Expected Time |
|----------|---------|-----|---------------|
| **Local** | 1 | 4.7 GB | ~40 hours |
| **HPC** | 8 | 64 GB | **2-4 hours** |

## HPC Resources

- **RAM**: 251 GB total (245 GB available)
- **CPUs**: 32 cores
- **fMRIPrep data**: Already on HPC at `/home/clivewong/proj/long/fmriprep/`

## Quick Start

### One-Command Workflow

```bash
bash script/setup_and_run_hpc.sh
```

This automated script:
1. Checks/installs Python dependencies on HPC
2. Uploads scripts and metadata to HPC
3. Submits SLURM job (16 CPUs, 64GB RAM, 8 workers)
4. Monitors job progress
5. Downloads results when complete

### Expected Output

**Processing:**
- 12 seeds × 45 sessions = **540 z-maps**
- Runtime: **2-4 hours** (vs 40+ hours locally)
- Memory: ~48 GB peak (64 GB allocated)

**Results downloaded to:**
```
derivatives/connectivity-difumo256/subject-level/seed_based/
├── motor_cortex/
├── cerebellar_motor/
├── cerebellar_cognitive/
├── hippocampus/
├── dlpfc_coarse/
├── dlpfc_dorsal/
├── dlpfc_ventral/
├── anterior_insula/
├── dacc/
├── insula_dacc_combined/
├── hippocampus_anterior/
└── hippocampus_posterior/
```

## Manual Workflow (Step-by-Step)

### Step 1: Install Dependencies on HPC (First Time Only)

```bash
# Upload install script
rsync -avz script/hpc_install_deps.sh clivewong@hpclogin1.eduhk.hk:/home/clivewong/proj/long/script/

# SSH to HPC and run
ssh clivewong@hpclogin1.eduhk.hk
cd /home/clivewong/proj/long
bash script/hpc_install_deps.sh
exit
```

### Step 2: Upload Scripts and Metadata

```bash
# From local machine
HPC_HOST="clivewong@hpclogin1.eduhk.hk"
HPC_PROJECT="/home/clivewong/proj/long"

# Create directories
ssh $HPC_HOST "mkdir -p $HPC_PROJECT/script $HPC_PROJECT/atlases $HPC_PROJECT/derivatives/connectivity-difumo256 $HPC_PROJECT/logs"

# Upload Python script
rsync -avz script/seed_based_connectivity_parallel.py $HPC_HOST:$HPC_PROJECT/script/

# Upload SLURM script
rsync -avz script/hpc_seed_connectivity.sh $HPC_HOST:$HPC_PROJECT/script/

# Upload seeds definition
rsync -avz atlases/motor_cerebellar_seeds.json $HPC_HOST:$HPC_PROJECT/atlases/

# Upload metadata
rsync -avz derivatives/connectivity-difumo256/participants.tsv $HPC_HOST:$HPC_PROJECT/derivatives/connectivity-difumo256/
```

### Step 3: Submit SLURM Job

```bash
# SSH to HPC
ssh clivewong@hpclogin1.eduhk.hk

# Navigate to project
cd /home/clivewong/proj/long

# Submit job
sbatch script/hpc_seed_connectivity.sh

# Note the job ID (e.g., 123456)
```

### Step 4: Monitor Progress

```bash
# Check job status
squeue -u clivewong

# View live output
tail -f logs/seed_connectivity_<JOB_ID>.out

# View errors (if any)
tail -f logs/seed_connectivity_<JOB_ID>.err
```

### Step 5: Download Results

```bash
# From local machine
HPC_HOST="clivewong@hpclogin1.eduhk.hk"
HPC_PROJECT="/home/clivewong/proj/long"
LOCAL_PROJECT="/home/clivewong/proj/longevity"

# Download z-maps
rsync -avz --progress \
    $HPC_HOST:$HPC_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based/ \
    $LOCAL_PROJECT/derivatives/connectivity-difumo256/subject-level/seed_based/

# Download logs
rsync -avz --progress \
    $HPC_HOST:$HPC_PROJECT/logs/seed_connectivity_*.* \
    $LOCAL_PROJECT/logs/
```

## Monitoring Commands

### From HPC

```bash
# Job queue status
squeue -u clivewong

# Detailed job info
scontrol show job <JOB_ID>

# Live output
tail -f logs/seed_connectivity_<JOB_ID>.out

# Check progress (count z-maps)
find derivatives/connectivity-difumo256/subject-level/seed_based -name "*_zmap.nii.gz" | wc -l
```

### From Local Machine

```bash
# Check job status remotely
ssh clivewong@hpclogin1.eduhk.hk "squeue -u clivewong"

# View output remotely
ssh clivewong@hpclogin1.eduhk.hk "tail -20 /home/clivewong/proj/long/logs/seed_connectivity_<JOB_ID>.out"

# Count z-maps remotely
ssh clivewong@hpclogin1.eduhk.hk "find /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based -name '*_zmap.nii.gz' | wc -l"
```

## SLURM Job Settings

**File**: `script/hpc_seed_connectivity.sh`

```bash
#SBATCH --cpus-per-task=16    # 16 CPU cores
#SBATCH --mem=64G              # 64 GB RAM
#SBATCH --time=8:00:00         # 8 hour time limit
```

**Parallelization**:
- `--n-jobs 8` (8 workers)
- Each worker uses ~6-8 GB RAM
- Total: ~48-64 GB peak usage

## Troubleshooting

### Issue: Job Pending

**Cause**: HPC queue is busy

**Check**:
```bash
squeue -u clivewong
```

**Solution**: Wait for resources to become available, or adjust `--mem` if requesting too much.

### Issue: Out of Memory

**Symptoms**: Job killed with no output

**Solution**: Reduce `--n-jobs` in `hpc_seed_connectivity.sh`:
```bash
# Change line 36 from:
--n-jobs 8 \
# To:
--n-jobs 4 \
```

### Issue: Python Import Errors

**Cause**: Virtual environment not activated or packages missing

**Solution**:
```bash
ssh clivewong@hpclogin1.eduhk.hk
cd /home/clivewong/proj/long
bash script/hpc_install_deps.sh
```

### Issue: Missing fMRIPrep Data

**Symptoms**: "No BOLD files found"

**Check**:
```bash
ssh clivewong@hpclogin1.eduhk.hk "ls /home/clivewong/proj/long/fmriprep/sub-*/ses-*/func/*_bold.nii.gz" | wc -l
```

**Solution**: Upload fMRIPrep data from local to HPC if needed.

## File Locations

### On HPC
- **Project**: `/home/clivewong/proj/long/`
- **Scripts**: `/home/clivewong/proj/long/script/`
- **fMRIPrep**: `/home/clivewong/proj/long/fmriprep/`
- **Results**: `/home/clivewong/proj/long/derivatives/connectivity-difumo256/`
- **Logs**: `/home/clivewong/proj/long/logs/`

### On Local
- **Project**: `/home/clivewong/proj/longevity/`
- **Scripts**: `/home/clivewong/proj/longevity/script/`
- **Results**: `/home/clivewong/proj/longevity/derivatives/connectivity-difumo256/`
- **Logs**: `/home/clivewong/proj/longevity/logs/`

## Performance Comparison

| Platform | Workers | RAM Usage | Time per Seed | Total Time |
|----------|---------|-----------|---------------|------------|
| Local | 1 | 4.7 GB | ~3.7 hours | ~40 hours |
| Local | 2 | 9.4 GB | N/A | OOM killed |
| Local | 4 | 18.8 GB | N/A | OOM killed |
| **HPC** | **8** | **~48 GB** | **~15 min** | **~2-4 hours** |

## Next Steps After Completion

Once the HPC job completes and results are downloaded:

1. **Verify results**:
   ```bash
   # Should have ~540 z-maps
   find derivatives/connectivity-difumo256/subject-level/seed_based -name "*_zmap.nii.gz" | wc -l
   ```

2. **Run group-level analysis**:
   ```bash
   bash script/continue_from_step3_parallel.sh
   # Or manually run step 6 (group analysis)
   ```

3. **Generate HTML report**:
   ```bash
   python script/generate_html_report.py \
       --results-dir derivatives/connectivity-difumo256 \
       --output derivatives/reports/connectivity-difumo256_report.html
   ```

## Cleanup (Optional)

After downloading results, clean up HPC storage:

```bash
ssh clivewong@hpclogin1.eduhk.hk "rm -rf /home/clivewong/proj/long/derivatives/connectivity-difumo256/subject-level/seed_based"
```

Keep logs for reference:
```bash
ssh clivewong@hpclogin1.eduhk.hk "ls -lh /home/clivewong/proj/long/logs/seed_connectivity_*"
```
