# Repository instructions

> **Authoritative conventions are in `AGENTS.md` at repository root.**
> This file provides GitHub Copilot-specific overrides and quick-reference commands.

## Commands

- `python script/validate_bids_names.py bids/` — BIDS validation
- `cd neuconn_app && streamlit run app.py` — Run the app
- `cd neuconn_app && python test_cli.py` — Smoke test
- `pytest tests/e2e/` — End-to-end tests (Python Playwright, 1920×1080 headless)
- `bash script/master_full_connectivity_workflow.sh --test` — Connectivity pipeline dry run

## Key conventions (summary — see AGENTS.md for full details)

- Root directory whitelist enforced — no new files at root
- All HPC connections from config, no hardcoded paths
- Every preprocessing module needs: Dashboard + Upload + Processing + Monitoring + Download + Cleanup
- XCP-D already handles confound regression — don't re-regress
- All voxelwise analyses use dilated MNI mask
- E2E tests: Python Playwright, headless, 1920×1080 viewport — no exceptions
- Output paths: `derivatives/connectivity/<pipeline>/<atlas>/<seed>/`

## Architecture quick-ref

- Entry point: `neuconn_app/app.py` (custom sidebar routing, `render()` pattern)
- Config: `neuconn_app/config/default_config.yaml` → project YAML → runtime overrides
- HPC: `neuconn_app/utils/hpc.py` (`HPCConfig.from_config(config)`)
- Connectivity config: `.github/connectivity_config.yaml`

