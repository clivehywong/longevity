# Connectivity Analysis

The current end-to-end entrypoint is `script/master_full_connectivity_workflow.sh`. It writes outputs into `results/` and orchestrates metadata preparation, local measures, seed-based connectivity, network connectivity, group analysis, and HTML report generation.

## Recommended sequence

### Step 1: Make sure preprocessing outputs exist

You need `fmriprep/` outputs plus the atlas definitions used by the workflow.

### Step 2: Generate metadata if needed

```bash
python script/prepare_metadata.py \
    --fmriprep fmriprep \
    --group group.csv \
    --output results/metadata.csv
```

### Step 3: Smoke-test local measures

```bash
bash script/test_local_measures.sh
```

### Step 4: Run the test workflow

```bash
bash script/master_full_connectivity_workflow.sh --test
```

Use this before a full run whenever you are changing inputs, paths, or parameters.

### Step 5: Run the full workflow

```bash
bash script/master_full_connectivity_workflow.sh
```

## What the master workflow currently uses

- local measures: `fALFF`, `ReHo`
- local-measure defaults: `TR=0.8`, `low-freq=0.01`, `high-freq=0.1`
- seed connectivity defaults: `smoothing=6.0`, `high-pass=0.01`, `low-pass=0.1`
- timeseries extraction: `difumo256`
- network analysis: selected within-network and between-network runs
- group analysis: `cluster-threshold=0.05`, `n-permutations=1000`, `min-cluster-size=10`

## Key outputs

| Output | Location |
|---|---|
| Metadata | `results/metadata.csv` |
| Local measures | `results/local_measures/` |
| Seed-based maps | `results/seed_based/` |
| Network results | `results/network_connectivity/` |
| Group analysis | `results/group_analysis/` |
| HTML report | `results/connectivity_report.html` |

## If you need narrower workflows

Use the individual scripts behind the master workflow:

- `compute_local_measures.py`
- `extract_timeseries.py`
- `seed_based_connectivity.py`
- `python_connectivity_analysis.py`
- `group_level_analysis.py`
- `generate_html_report.py`

See [`../reference/commands-and-entrypoints.md`](../reference/commands-and-entrypoints.md) and [`../reference/parameter-considerations.md`](../reference/parameter-considerations.md).
