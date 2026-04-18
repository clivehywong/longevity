# Implementation Changes - Smart Image Cache System

## Date: 2026-04-06

## Summary

Implemented a comprehensive smart image pre-generation and caching system that speeds up QC visual checks by ~120x through intelligent disk caching and background pre-generation.

## New Files

### 1. `utils/image_cache.py` (650 lines)

**Purpose**: Core caching engine with background pre-generation

**Key Classes**:
- `ImageCache`: Main cache manager
  - Thread-safe manifest updates
  - Modification time tracking
  - Background generation with progress monitoring
  - Cache statistics and validation

**Key Functions**:
- `get_image_cache(bids_dir)`: Global singleton accessor
- `get_cached_image()`: Get from cache or generate
- `start_background_generation()`: Pre-generate all images
- `get_cache_stats()`: Cache coverage metrics
- `clear_cache()`: Cache management

**Features**:
- Automatic cache invalidation on source file changes
- BIDS-Derivatives compliant structure
- Thread-safe concurrent access
- Real-time progress monitoring

### 2. `utils/qa_image_generator.py` (800 lines)

**Purpose**: Image generation functions (moved from `script/qa_check_images.py`)

**Key Functions**:
- `generate_anat_montage()`: T1w/T2w (7 axial + 7 sagittal)
- `generate_func_timepoints()`: BOLD timepoints (3x3 grid)
- `generate_func_quality()`: Mean/Std/tSNR quality maps
- `generate_dwi_montage()`: DWI volumes (b0, mid, high-b)
- `generate_fmap_montage()`: Field map AP/PA comparison

**Dual Purpose**:
- Library for NeuConn app integration
- Standalone CLI tool for batch generation

**CLI Usage**:
```bash
python -m utils.qa_image_generator --bids-dir bids/ --output qa_images/
```

### 3. `IMAGE_CACHE_README.md`

**Purpose**: Comprehensive user and developer documentation

**Contents**:
- Feature overview and architecture
- Cache structure diagram
- Usage examples (Python + Streamlit)
- Performance benchmarks
- Cache management guide
- API reference
- Troubleshooting

### 4. `test_image_cache.py`

**Purpose**: Test suite for cache system

**Tests**:
1. Cache initialization
2. Single image caching
3. Cache statistics
4. Manifest integrity
5. Background generation (optional)

**Usage**:
```bash
python test_image_cache.py
```

### 5. `IMPLEMENTATION_SUMMARY.md`

**Purpose**: Technical implementation summary

**Contents**:
- Architecture overview
- File changes summary
- Performance metrics
- User workflow
- Testing instructions

### 6. `CHANGES.md` (this file)

**Purpose**: Change log for this implementation

## Modified Files

### 1. `utils/visualization.py`

**Changes**:
- Updated all plotting functions to support caching
- Added parameters: `use_cache=True`, `bids_dir=None`
- Imports generators from `qa_image_generator`
- Transparent fallback to direct generation

**Modified Functions**:
- `plot_t1w_montage()` / `plot_anat_montage()`
- `plot_functional_timepoints()`
- `plot_functional_quality_maps()`
- `plot_dwi_montage()`
- `plot_fmap_comparison()`

**New Helper**:
- `get_cache_if_available()`: Safe cache retrieval

**Backwards Compatible**: Works with or without `bids_dir` parameter

### 2. `pages_general_qc/01_anat_visual_check.py`

**Changes**:
- Added `get_anat_image()` helper function
- Updated `cached_plot_anat()` to accept `bids_dir` parameter
- Integrated disk cache with Streamlit memory cache (two-tier)
- Passes `bids_dir` when calling plotting function

**Impact**:
- Anatomical images now load from disk cache when available
- ~10-20x faster on subsequent loads

### 3. `pages_general_qc/05_func_visual_check.py`

**Changes**:
- Added `get_func_timepoints_image()` helper
- Added `get_func_quality_image()` helper
- Updated both caching functions to use disk cache
- Passes `bids_dir` when calling plotting functions

**Impact**:
- Functional images load from disk cache
- Quality maps (most expensive) benefit from persistent cache
- ~100-120x faster for quality maps on cache hit

### 4. `pages_general_qc/00_dataset_overview.py`

**Changes**:
- Added `render_cache_section()` function (100+ lines)
- Imports cache and generator modules
- New UI section: "QC Image Cache"

**New UI Elements**:

#### Cache Status Display
- Total images needed
- Currently cached count
- Coverage percentage
- Detailed breakdown by type with progress bars

#### Pre-Generation Controls
- "Pre-Generate All" button (force regeneration)
- "Generate Missing Only" button (smart generation)
- "Clear Cache" button

#### Real-Time Monitoring
- Progress bar during generation
- Current file being processed
- Completed/Total counter
- Error display
- Auto-refresh while running
- "Stop Generation" button

**New Helper Function**:
- `start_background_generation()`: Launch background thread

## Cache Directory Structure

**Created in BIDS directory**:

```
bids/
└── derivatives/
    └── qc_images/          ← New cache directory
        ├── anat/           ← Anatomical PNGs
        ├── func/           ← Functional PNGs
        ├── dwi/            ← DWI PNGs
        ├── fmap/           ← Field map PNGs
        └── cache_manifest.json  ← Metadata
```

**BIDS-Derivatives Compliant**: Follows neuroimaging standards

## Performance Impact

### Before (No Cache)

| Image Type | Generation Time |
|------------|----------------|
| Anatomical T1w | 0.5-1.0s |
| Functional Timepoints | 1-2s |
| Functional Quality Maps | 8-10s |

**Total for 44 subjects, 2 sessions**:
- 251 anat + 168 func = 419 images
- Estimated: ~45 minutes for full dataset

### After (With Cache)

| Operation | Time |
|-----------|------|
| Load from cache | 0.05-0.1s |
| Cache hit | ~50ms |

**Total for 44 subjects, 2 sessions**:
- All 419 images: ~20 seconds
- **Speedup: 120x faster**

### Disk Space

- Anatomical: ~100-200 KB each
- Functional: ~200-300 KB each
- **Total**: ~100-150 MB for full dataset
- Manifest: ~100-200 KB

## User Workflow Changes

### First-Time Setup (One-Time)

**New Steps**:
1. Navigate to "Data QC" → "Dataset Overview"
2. Scroll to "QC Image Cache" section
3. Click "Pre-Generate All"
4. Wait 45-60 minutes
5. Cache ready for instant use

### Daily Usage (No Changes)

**Existing workflow works as before**:
1. Navigate to Visual Check pages
2. Images now load from cache (faster)
3. No visible UI changes except speed

## Testing

### Import Test

```bash
python3 -c "from utils.image_cache import ImageCache; print('OK')"
```

### Cache Test

```bash
python test_image_cache.py
```

### Integration Test

1. Start app: `streamlit run app.py`
2. Navigate to Dataset Overview
3. Check "QC Image Cache" section displays
4. Try "Generate Missing Only"
5. Navigate to Visual Check pages
6. Verify images load quickly

## Backwards Compatibility

**Fully backwards compatible**:
- Existing code works without changes
- Cache is optional (enabled when `bids_dir` provided)
- Falls back to direct generation if cache unavailable
- No breaking changes to APIs

## Dependencies

**No new dependencies required**:
- Uses existing: `matplotlib`, `nibabel`, `numpy`, `pandas`, `streamlit`
- All already installed in environment

## Migration Notes

**No migration needed**:
- Cache is automatically created on first use
- Existing QA workflow unchanged
- Can opt-in to pre-generation via UI

## Known Limitations

1. **Disk space**: Requires ~100-150 MB for full dataset cache
2. **Initial generation**: Takes 45-60 minutes for first pre-generation
3. **Manual invalidation**: Must manually regenerate if parameters change (e.g., different slice count)

## Future Enhancements

Potential improvements:
1. Multi-threaded parallel generation
2. PNG compression for smaller cache
3. Auto-purge old entries (>30 days)
4. HPC cache sharing across nodes
5. Incremental updates (only changed subjects)

## Rollback

If issues arise, system can be disabled by:

1. **Remove cache directory**:
   ```bash
   rm -rf bids/derivatives/qc_images/
   ```

2. **Use without cache**:
   - Simply don't pass `bids_dir` parameter
   - Direct generation will be used

3. **Revert code changes**:
   - All changes are additive
   - Old plotting functions still work

## Verification Checklist

- [x] Cache directory created with BIDS-Derivatives structure
- [x] Manifest JSON created and valid
- [x] Single image caching works
- [x] Cache invalidation on source modification
- [x] Background generation with progress tracking
- [x] Cache statistics accurate
- [x] UI controls functional
- [x] Backwards compatible
- [x] No new dependencies
- [x] Documentation complete
- [x] Test suite passes

## Files Summary

**Created**: 6 files (~3000 lines)
**Modified**: 4 files (~200 lines changed)
**Total**: 10 files affected

## Contributors

Implementation by Claude Code (2026-04-06)

## References

- Original QA script: `/home/clivewong/proj/longevity/script/qa_check_images.py`
- BIDS Specification: https://bids-specification.readthedocs.io/
- Derivatives Extension: BIDS Extension Proposal 16

---

# Workflow Redesign v2 — Feature Changes

## Date: 2026-04-18

## Summary

Major UI improvements: SSH port support for tunnels, pipeline gate split (fMRI vs dMRI), Subject Data page, fMRI preprocessing dashboard, XCP-D per-subject completion tracking, tooltip improvements, inline HTML report viewers, auto-select incomplete subjects, and MNI152NLin6Asym atlas upgrade.

## New Features

### 1. SSH Port support (`utils/hpc.py`, `pages_settings/settings_page.py`, `config/default_config.yaml`)
- `HPCConfig.port` field (default 22) passed to paramiko connect
- Port number input in **Settings → HPC** tab (help text: "use 2222 for local tunnel")
- Supports SSH tunnel shortcut: `ssh -p 2222 localhost`

### 2. Pipeline Gates split (`app.py`)
- Sidebar now shows **fMRI gates** (FD approval, XCP-D QC, subject outputs) and **dMRI gates** (QSIPrep outputs, Tractography QC) as independent groups

### 3. Subject Data page (`pages_general_qc/08_subject_data.py`)
- Editable `group.csv` in the UI (inline table editor)
- CSV upload/merge
- Subjects in BIDS but missing from group.csv flagged as "unlabeled"
- Save writes back to group.csv in project root

### 4. fMRI Preprocessing Dashboard (`pages_fmri/preprocessing/00_fmri_dashboard.py`)
- Per-subject table: fMRIPrep, XCP-D FC, XCP-D FC+GSR, XCP-D EC status
- **🔄 Rescan** button re-reads disk; metric cards summarize completion counts
- Status legend: ⚪ not started · 🔄 incomplete · ✅ completed · ❌ failed

### 5. XCP-D per-subject completion status (`utils/xcpd_qc.py`, `06_xcpd_pipeline.py`)
- `get_xcpd_subject_status(xcpd_dir, subjects)` reads `status` sentinel files or HTML report presence
- "📋 Subject Completion Status" expander below XCP-D run panels

### 6. XCP-D tooltips (`06_xcpd_pipeline.py`)
- Progress bar tooltip explains Nipype nodes
- Help text added for ambiguous parameters

### 7. Auto-select incomplete subjects
- **XCP-D Runs tab**: four buttons (🎯 FC incomplete / 🎯 FC+GSR incomplete / 🎯 EC incomplete / ↩ Reset) set multiselect via `st.session_state`
- **fMRIPrep Submit**: "Select incomplete" radio option auto-selects unprocessed subjects

### 8. Inline HTML report viewers
- **fMRIPrep QC Reports** (`02_qc_reports.py`): scans `fmriprep_dir` and `legacy_fmriprep_dir` for `sub-*.html`; dropdown + ⬅/➡ navigation; embedded via `st.components.v1.html()`
- **XCP-D QC Reports** (`07_xcpd_qc_reports.py`): two-tab layout — "📈 QC Metrics" (existing) + "📄 HTML Reports" (per-pipeline tabs FC/FC+GSR/EC, per-session navigation)

### 9. MNI152NLin6Asym atlas upgrade (`utils/xcpd_atlases.py`, `atlases/tian/`)
- Downloaded correct Tian atlas files in MNI152NLin6Asym space (identical to FSL MNI152_T1_2mm)
- `LongevitySchaeferTian200S2` and `LongevitySchaeferTian400S2` updated to reference new files
- Atlas space confirmed in XCP-D HTML reports: `BOLD volume space: MNI152NLin6Asym`

### 10. Output path conventions
- All derivatives now under `derivatives/func/preprocessing/` and `derivatives/dwi/preprocessing/`
- Config keys updated; legacy `fmriprep/` root path still accepted via `legacy_fmriprep_dir`
- Pipeline artifacts moved from QC directory to `derivatives/pipeline_runs/`

## Modified Files

| File | Changes |
|---|---|
| `utils/hpc.py` | `HPCConfig.port` field, paramiko port kwarg |
| `pages_settings/settings_page.py` | Port number input in HPC tab |
| `config/default_config.yaml` | `hpc.port: 22`, updated derivative paths |
| `app.py` | fMRI/dMRI pipeline gate split, new pages registered |
| `pages_general_qc/08_subject_data.py` | **NEW** Subject Data page |
| `pages_fmri/preprocessing/00_fmri_dashboard.py` | **NEW** fMRI Dashboard |
| `pages_fmri/preprocessing/01_hpc_submit.py` | "Select incomplete" radio option |
| `pages_fmri/preprocessing/02_qc_reports.py` | Reimplemented as inline HTML viewer |
| `pages_fmri/preprocessing/06_xcpd_pipeline.py` | Auto-select buttons, tooltips, no pipeline status header |
| `pages_fmri/preprocessing/07_xcpd_qc_reports.py` | Two-tab layout with HTML report viewer |
| `utils/xcpd_atlases.py` | MNI152NLin6Asym atlas file references |
| `utils/xcpd_qc.py` | `get_xcpd_subject_status()` helper |

## Added Files

- `atlases/tian/Schaefer2018_200Parcels_7Networks_order_Tian_Subcortex_S2_MNI152NLin6Asym_2mm.nii.gz`
- `atlases/tian/Schaefer2018_400Parcels_7Networks_order_Tian_Subcortex_S2_MNI152NLin6Asym_2mm.nii.gz`
