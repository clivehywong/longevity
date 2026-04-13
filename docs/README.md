# Documentation Index

Central navigation for all project documentation.

## Quick Links

- **[../CLAUDE.md](../CLAUDE.md)** - Start here! Essential project overview and Claude usage
- **[../QUICK_START.md](../QUICK_START.md)** - Essential commands and workflows
- **[../.claude/memory/](../.claude/memory/)** - Persistent context (HPC config, analysis params)

## Guides

### Analysis Pipelines
- **[CONNECTIVITY_ANALYSIS_GUIDE.md](CONNECTIVITY_ANALYSIS_GUIDE.md)** - Subject-level and group-level connectivity analysis
- **[HPC_SEED_CONNECTIVITY_GUIDE.md](HPC_SEED_CONNECTIVITY_GUIDE.md)** - HPC-based batch processing
- **[WORKFLOW_GUIDE.md](WORKFLOW_GUIDE.md)** - General workflow patterns

### Scripts
- **[../script/](../script/)** - 20+ Python/Bash scripts for preprocessing and analysis

## App Development

- **[../.claude/plans/moonlit-yawning-curry.md](../.claude/plans/moonlit-yawning-curry.md)** - NeuConn Streamlit app blueprint
  - Hierarchical navigation design
  - Page-by-page UI mockups
  - HPC space-efficient workflow
  - Group analysis with flexible QC thresholds

## Archived Documentation

- **[archive/](archive/)** - Historical status reports, implementation summaries, job logs
- **[archive/job_logs/](archive/job_logs/)** - SLURM job status files (2954, 2955)
- **[archive/implementations/](archive/implementations/)** - Old implementation plans

---

## Common Tasks

### Quality Control
```bash
# Visual QA report
python script/qa_check_images.py bids/ qa_images_full/

# Dimension checks
python script/dimensional_consistency.py bids/

# BIDS validation
python script/validate_bids_names.py bids/
```

### Preprocessing (HPC)
```bash
# Full workflow: upload → process → download → cleanup
bash script/batch_fmriprep.sh

# Check job status
bash script/batch_fmriprep.sh status
```

### Connectivity Analysis
```bash
# Test with 2 subjects
bash script/master_full_connectivity_workflow.sh --test

# Full analysis
bash script/master_full_connectivity_workflow.sh
```

---

**Need help?** Check [CLAUDE.md](../CLAUDE.md) for subagent usage or memory files for configuration details.
