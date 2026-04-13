# Quick Start Guide - Connectivity Analysis Pipeline

## Current Status
🔄 **Test workflow running** (started 2026-02-11)  
Processing: sub-033 and sub-034 (test mode)  
Estimated completion: 1-2 hours from start

## Monitor Progress

```bash
# Quick status check
bash monitor_workflow.sh

# Follow live output
tail -f /tmp/claude-1002/-home-clivewong-proj-longevity/tasks/bfcfbd1.output
```

## When Workflow Completes

### 1. View Results
```bash
# Open interactive HTML report in browser
firefox results/connectivity_report.html
```

### 2. Check Output Files
```bash
# List generated files
ls -lh results/local_measures/
ls -lh results/seed_based/
ls -lh results/group_analysis/

# View summary
cat results/local_measures/local_measures_summary.csv
```

### 3. Visualize Brain Maps
```bash
# View fALFF map
fsleyes results/local_measures/sub-033_ses-01_fALFF.nii.gz

# View seed connectivity z-map
fsleyes results/seed_based/dlpfc_coarse/sub-033_ses-01_zmap.nii.gz

# View group statistical map
fsleyes results/group_analysis/fALFF/interaction_fwe_p05.nii.gz
```

## Next Steps

### Run Full Analysis (All 8 Subjects)
Once test mode completes successfully:
```bash
bash script/master_full_connectivity_workflow.sh
```
- Processes all 16 subject-sessions
- Estimated time: 6-8 hours
- Creates complete analysis + HTML report

## Available Scripts

| Script | Purpose | Time |
|--------|---------|------|
| `master_full_connectivity_workflow.sh --test` | Test with 2 subjects | 1-2 hrs |
| `master_full_connectivity_workflow.sh` | Full analysis (all) | 6-8 hrs |
| `test_local_measures.sh` | Quick validation | 10 min |
| `compute_local_measures.py` | fALFF & ReHo only | Variable |
| `seed_based_connectivity.py` | Seed analysis only | Variable |
| `group_level_analysis.py` | Group stats only | Variable |
| `generate_html_report.py` | Create HTML report | 1-2 min |

## Documentation

- **`CONNECTIVITY_ANALYSIS_GUIDE.md`** - Complete usage guide
- **`CLAUDE.md`** - Project overview with connectivity section
- **`TEST_RESULTS_SUMMARY.md`** - Validation results

## Troubleshooting

### Workflow stuck?
```bash
# Check if process still running
ps aux | grep python

# View full log
less /tmp/claude-1002/-home-clivewong-proj-longevity/tasks/bfcfbd1.output
```

### Need to restart?
```bash
# Kill running workflow
pkill -f master_full_connectivity_workflow

# Restart test mode
bash script/master_full_connectivity_workflow.sh --test
```

### Missing dependencies?
All required packages are already installed:
- ✅ nilearn 0.13.0
- ✅ plotly 6.3.0  
- ✅ statsmodels 0.14.5
- ✅ nibabel, pandas, scipy, numpy, matplotlib

## Expected Output Structure

```
results/
├── connectivity_report.html          # Main deliverable
├── metadata.csv                      # Subject metadata
├── local_measures/
│   ├── *_fALFF.nii.gz               # 4 files (2 subjects × 2 sessions)
│   ├── *_ReHo.nii.gz                # 4 files
│   └── local_measures_summary.csv
├── seed_based/
│   ├── dlpfc_coarse/                # 4 z-maps
│   ├── dlpfc_dorsal/                # 4 z-maps
│   ├── anterior_insula/             # 4 z-maps
│   └── ... (12 seeds total)
├── network_connectivity/
│   ├── within_salience/             # ANOVA results
│   └── between_*/                   # Network pairs
└── group_analysis/
    ├── fALFF/                       # Statistical maps
    ├── ReHo/
    └── seed_*/                      # Cluster tables
```

## Key Features

✅ **Local Measures**: fALFF, ReHo  
✅ **15 Seed Regions**: DLPFC, insula, dACC, hippocampus  
✅ **Network Analysis**: Within/between connectivity  
✅ **Group Statistics**: Voxelwise LME with TFCE correction  
✅ **Interactive Report**: Browser-based with significance highlighting  
✅ **Motion QC**: Automated FD calculation and covariate control  

## Support

For detailed information, see:
- Usage examples: `CONNECTIVITY_ANALYSIS_GUIDE.md`
- Test results: `TEST_RESULTS_SUMMARY.md`
- Project overview: `CLAUDE.md`
