# fMRIPrep HPC Workflow

This repository uses `script/batch_fmriprep.sh` as the main preprocessing entrypoint. The script is designed around storage-constrained HPC processing: upload a batch, run fMRIPrep remotely, download selected outputs, then clean the remote workspace.

## Step-by-step

### Step 1: Confirm path assumptions

Review `script/batch_fmriprep.sh` before first use. The current script assumes:

- local BIDS: `/home/clivewong/proj/longevity/bids`
- local output: `/home/clivewong/proj/longevity/fmriprep`
- remote host: `clivewong@hpclogin1.eduhk.hk`
- remote project: `/home/clivewong/proj/long`

### Step 2: Run the batch workflow

```bash
bash script/batch_fmriprep.sh
```

This processes the configured subject list in batches and performs upload, submit, wait, download, and cleanup.

### Step 3: Monitor status

```bash
bash script/batch_fmriprep.sh status
```

### Step 4: Resume or control a specific batch

```bash
bash script/batch_fmriprep.sh 2
bash script/batch_fmriprep.sh upload 1
bash script/batch_fmriprep.sh submit 1
bash script/batch_fmriprep.sh download 1
bash script/batch_fmriprep.sh cleanup 1
```

## What the script downloads

- subject-level fMRIPrep derivatives
- subject HTML reports
- dataset-level logs

It explicitly excludes `*_space-fsnative_*` files during download to reduce storage use.

## NeuConn app submission (alternative to script)

The **fMRI Analysis → fMRIPrep Submit** page in the NeuConn app provides an HPC submission UI:

1. Open the page and expand **Test HPC Connection** to confirm the SSH tunnel is working.
2. Under **Subject Selection**, choose a session filter and a selection method:
   - **Select all** — all available subjects (optionally excluding already-processed ones)
   - **Select incomplete** — auto-selects subjects present in BIDS that do NOT yet have fMRIPrep output (useful for catching new subjects after partial runs)
   - **Select specific subjects** — manual pick from a multiselect
   - **Select range** — numeric ID range
3. Set **Batch size** and proceed to **Upload & Submit**.
4. Monitor the job in the **Monitor** tab, and download results in **Download & Cleanup**.

## After preprocessing

Once `fmriprep/` is populated locally, move on to [`connectivity-analysis.md`](connectivity-analysis.md).

## Things to watch

- Remote cleanup is part of the normal workflow, not an exceptional step.
- If you change path handling, update connected scripts together rather than patching one call site.
- The subject list is hardcoded in the script, so check it before starting a new run.
