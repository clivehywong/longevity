# Agent Conventions & Guidelines

This file documents conventions for Copilot agents and other AI assistants working in this repository.

---

## Directory Structure

When generating or modifying files, follow this structure:

| Directory | Purpose | Tracked? | Persistence | Example |
|-----------|---------|----------|-------------|---------|
| `script/` | Permanent analysis code | ✓ Yes | Long-term | `script/functional_connectivity_analysis.py` |
| `neuconn_app/` | Streamlit app code | ✓ Yes | Long-term | `neuconn_app/pages_fmri/preprocessing/00_fmri_dashboard.py` |
| `tmp/scripts/` | Temporary helper scripts | ✗ No | Session-only | `tmp/scripts/_monitor_fmriprep_20260427.sh` |
| `docs/` | Documentation | ✓ Yes | Long-term | `docs/user/workflows.md` |
| `.github/` | Workflows, extensions | ✓ Yes | Long-term | `.github/workflows/ci.yml` |
| `.claude/` | Session context & memory | Varies | Session/long-term | `.claude/memory/`, `.claude/session-state/` |

---

## Temporary Scripts Convention

### When to Use `tmp/scripts/`

Create temporary scripts in `tmp/scripts/` when:
- Running one-time monitoring/orchestration (e.g., job orchestration, batch downloads)
- Testing new logic before integrating into permanent code
- Session-specific workflow helpers that shouldn't be committed

### Do NOT use `tmp/scripts/` for:
- Production analysis code (use `script/` instead)
- Application code (use `neuconn_app/` instead)
- Permanent utilities (use `script/utils/` instead)

### Naming Convention

Use the pattern: `tmp/scripts/_<purpose>_<timestamp>.sh`

**Examples**:
```bash
tmp/scripts/_monitor_fmriprep_20260427.sh       # Monitor fMRIPrep jobs
tmp/scripts/_download_outputs_20260427.sh       # Download HPC results
tmp/scripts/_verify_xcpd_fc_20260424.sh        # Verify XCP-D FC outputs
tmp/scripts/_test_connectivity_20260426.sh     # Test connectivity analysis
```

**Why this pattern**:
- `_` prefix: Makes it obvious these are temporary when viewing file lists
- `<purpose>`: Describes what the script does
- `<timestamp>`: Enables parallel session scripts without collision (date format: YYYYMMDD)

### .gitignore Patterns

These files are automatically ignored:
```
tmp/*.sh              # All shell scripts in tmp/
*_monitor*.sh        # Monitor scripts at root level
*.log                # All log files
*.out                # Standard output files (SLURM logs)
*.pid                # Process ID files
```

---

## Code Organization Best Practices

### When Writing New Code

1. **Analysis/utility code** → `script/`
   - Keep functions reusable and well-documented
   - Example: `script/functional_connectivity_analysis.py`

2. **Application/UI code** → `neuconn_app/`
   - Follow Streamlit conventions (see neuconn_app/README.md for app architecture)
   - Example: `neuconn_app/pages_fmri/preprocessing/06_xcpd_pipeline.py`

3. **Session helpers** → `tmp/scripts/`
   - One-off scripts that assist a specific session task
   - No need for extensive documentation (session-scoped)
   - Use proper naming convention

### Imports & Module Structure

**Always include a sys.path adjustment** in temporary scripts if using local modules:
```bash
#!/bin/bash
# If calling Python with local imports:
cd /home/clivewong/proj/longevity
python3 -c "
import sys
sys.path.insert(0, '/home/clivewong/proj/longevity')
# ... code here
"
```

**For permanent code in `script/`**: Use proper package structure (see `neuconn_app/` for examples with `__init__.py` patterns)

---

## Documentation Requirements

### For `script/` code (permanent)
- [ ] Docstring at function level (purpose, args, returns)
- [ ] Comments for non-obvious logic
- [ ] README or docstring describing overall script purpose
- [ ] Example usage in comments

### For `neuconn_app/` code (permanent)
- [ ] Follow Streamlit conventions (see CLAUDE.md for app architecture)
- [ ] Document page `render()` function
- [ ] Include config assumptions as comments
- [ ] Update app README if adding new features

### For `tmp/scripts/` code (temporary, session-scoped)
- [ ] Brief header comment with purpose
- [ ] Key variable definitions with comments
- [ ] No extensive docstrings required (session-only)

---

## Git Commit Practices

### Commits Should Include

1. **Co-authored-by trailer** (required for all commits):
   ```
   Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
   ```

2. **Clear message** describing what changed:
   - Use imperative mood ("Add feature" not "Added feature")
   - First line ≤50 characters
   - Detailed explanation after blank line if needed

3. **Files to commit**:
   - ✓ Code in `script/`, `neuconn_app/`, `docs/`
   - ✓ `.gitignore` updates
   - ✓ Configuration changes
   - ✗ Do NOT commit files in `tmp/`, `*.log`, `*.pid`, `*.out` (automatically ignored)

### Example Good Commit

```
Add functional connectivity analysis pipeline

- Compute Pearson correlations from XCP-D timeseries
- Apply Fisher z-transform for normalization
- Generate group-level connectome and visualizations
- Add connectivity_report.md with methodology and results

Fixes: Issue #42 (FC analysis implementation)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
```

---

## Configuration & Environment

### Config Locations

The app loads config in this precedence order:
1. `~/neuconn_projects/longevity.yaml` (user-specific, takes precedence)
2. `neuconn_app/config/default_config.yaml` (fallback)
3. Runtime overrides (from command line, if any)

**For agents**: If modifying config behavior:
- Update BOTH `default_config.yaml` AND `longevity.yaml` if they diverge
- Document path assumptions in code comments
- Check that both local and HPC remote paths are consistent

### Environment Variables

Key HPC connection details (stored in config, not env vars):
- Remote SSH host: `localhost` (port 2222 by convention)
- Remote paths: Defined in config under `hpc.paths`
- HPC templates: `neuconn_app/templates/*.j2`

---

## Testing & Verification

### For `script/` code
- Run smoke tests before committing: `cd neuconn_app && python test_cli.py`
- Test with real data subset if possible
- Check for common issues: path resolution, file permissions, module imports

### For `tmp/scripts/` code
- No formal testing required (session-scoped)
- Verify it runs without errors before sharing
- Include error handling for critical steps (e.g., HPC connections)

### For app changes
- Test Streamlit UI if changes affect UI layer
- Use Playwright for integration testing (infrastructure exists in .github/workflows/)
- Verify dashboard/monitoring functions work correctly

---

## Common Pitfalls

### ❌ Don't

1. **Commit temporary scripts to permanent locations**
   - Wrong: `script/monitor_fmriprep_temp.sh` (temp code in permanent dir)
   - Right: `tmp/scripts/_monitor_fmriprep_20260427.sh` (temp code in temp dir)

2. **Hardcode HPC paths in permanent code**
   - Wrong: `"/home/clivewong/proj/long/derivatives/..."` hardcoded in Python
   - Right: Read from config: `config['hpc']['paths']['fmriprep']`

3. **Leave stray files in root directory**
   - Wrong: `pipeline_monitor.sh`, `output_20260427.log` at repo root
   - Right: Use `tmp/scripts/_monitor_*.sh` and let .gitignore handle `.log` files

4. **Modify .gitignore without testing**
   - Commit a change to .gitignore
   - Verify stray files are now ignored: `git status` should not show them

### ✓ Do

1. **Use proper directory structure** for file type
2. **Update both code AND config** when changing paths
3. **Document all permanent code** with docstrings
4. **Follow naming conventions** for temporary files
5. **Use session workspace** (`~/.copilot/session-state/`) for plans/notes, NOT repo root

---

## Useful Patterns

### Pattern 1: Monitor a Long-Running Job

```bash
#!/bin/bash
# tmp/scripts/_monitor_job_YYYYMMDD.sh

JOB_ID=$1
INTERVAL=30m

while true; do
    echo "--- Check at $(date) ---"
    ssh -p 2222 localhost "squeue -j $JOB_ID" || break
    sleep $INTERVAL
done
```

### Pattern 2: Temporary Python Analysis

```python
#!/usr/bin/env python3
# tmp/scripts/_analyze_outputs_YYYYMMDD.py

import sys
sys.path.insert(0, '/home/clivewong/proj/longevity')

from neuconn_app.utils.xcpd import load_xcpd_outputs
# ... analysis code
```

### Pattern 3: Download with Verification

```bash
#!/bin/bash
# tmp/scripts/_download_verify_YYYYMMDD.sh

rsync -avz --progress remote:path/ local/
local_count=$(find local/ -name "*.nii.gz" | wc -l)
remote_count=$(ssh -p 2222 localhost "find remote/ -name '*.nii.gz' | wc -l")
[ "$local_count" -eq "$remote_count" ] && echo "✓ Verified" || echo "✗ Mismatch"
```

---

## Questions?

Refer to:
- **Repository structure**: See `CLAUDE.md` (for humans) or this file (for agents)
- **App architecture**: `neuconn_app/README.md`
- **Workflows**: `docs/user/` and `docs/developer/`
- **Session context**: `.claude/memory/`

---

**Last updated**: 2026-04-27
**Maintained by**: Copilot agents + human team
