# NeuConn App

The app is the interactive layer for QC, configuration, and workflow orchestration. It does not replace the script-driven research pipeline; it wraps and assists it.

## Start the app

```bash
cd neuconn_app
pip install -r requirements.txt
python test_cli.py
streamlit run app.py
```

## First-run flow

1. Open the app.
2. Go to **Settings** if you need to confirm paths or config values.
3. Use **Dataset Overview** to scan the dataset.
4. Continue into QC or workflow-specific pages.

## Where the app keeps state

- config: `~/neuconn_projects/<project>.yaml`
- QC status: `<bids parent>/qc_status.json`
- exclusions: sibling `bids_excluded/`
- HPC workflow state: `<bids parent>/.neuconn/hpc_workflow_state.json`
- QC image cache: `<bids>/derivatives/qc_images/`

## What the smoke test covers

`python test_cli.py` checks:

- config loading
- BIDS scanning
- acquisition-parameter detection

## When to use the app

- interactive QC review
- config-driven project setup
- monitoring cache and dataset state
- browsing the project structure without dropping into multiple scripts

## When to stay in the shell

- batch preprocessing
- master connectivity runs
- one-off script execution with explicit flags
