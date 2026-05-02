# Agent Conventions & Guidelines

> **The authoritative conventions document is `AGENTS.md` at repository root.**
> This file provides supplementary patterns for AI agents working in `.github/` context.

For all conventions — root directory discipline, HPC standards, Playwright testing,
output path structure, analysis rules, and more — see **`AGENTS.md`**.

---

## Temporary Scripts Convention

Create temporary scripts in `tmp/scripts/` with pattern: `_<purpose>_<timestamp>.sh`

```bash
tmp/scripts/_monitor_fmriprep_20260427.sh       # Monitor fMRIPrep jobs
tmp/scripts/_download_outputs_20260427.sh       # Download HPC results
```

- `_` prefix: Makes it obvious these are temporary
- Session-scoped, never committed
- Automatically gitignored

## Quick Reference

- **Full conventions**: `AGENTS.md`
- **App architecture**: `neuconn_app/README.md`
- **User guides**: `docs/user/`
- **Developer docs**: `docs/developer/`
- **Connectivity config**: `.github/connectivity_config.yaml`
