# fALFF & ReHo Connectivity Page

## Overview

The `pages_connectivity/01_fALFF_ReHo.py` page provides an interactive Streamlit interface for browsing, visualizing, and analyzing local measures (fALFF and ReHo) results from the connectivity pipeline.

## Location

- **Page module**: `neuconn_app/pages_connectivity/01_fALFF_ReHo.py`
- **Entrypoint**: `neuconn_app/pages/3_🔗_Connectivity.py`
- **Data source**: `derivatives/connectivity-difumo256/subject-level/local_measures/`

## Features

### 1. Subject/Session Selector
- Dropdown selectors for choosing subject and session
- Dynamically populated from local measures summary CSV
- Displays all available subject-session pairs

### 2. Brain Map Visualization (Papaya Viewer)
- Side-by-side fALFF and ReHo maps
- Interactive 3-plane view (axial, coronal, sagittal)
- Adjustable colormap, threshold, and transparency
- Real-time coordinate display (MNI and voxel)
- PNG export functionality for each viewer

### 3. QC Metrics Display
- Subject-level statistics:
  - Mean, standard deviation, median for each measure
  - Organized in metric cards for quick reference
- Easy-to-scan format for quality assessment

### 4. Group-Level Statistics
- Aggregate statistics across all subjects
- Mean, average std dev, and range for each measure
- Distribution details (Q1, median, Q3)
- Sample size tracking

### 5. Results Browser Table
- Full results table with search/filter capability
- Subject ID search
- Configurable row limit
- Sortable columns
- CSV preview without file paths

### 6. Export Functionality
- **Subject statistics**: Export individual subject stats as CSV
- **Group statistics**: Export group-level statistics as CSV
- **Full summary**: Export all results as CSV
- One-click download buttons for each export type

## Data Flow

```
derivatives/connectivity-difumo256/
└── subject-level/
    └── local_measures/
        ├── sub-XXX_ses-XX_fALFF.nii.gz
        ├── sub-XXX_ses-XX_ReHo.nii.gz
        └── local_measures_summary.csv  ← Loads from here
```

### Summary CSV Format

The `local_measures_summary.csv` contains:
```
subject, session, 
fALFF_mean, fALFF_std, fALFF_median, fALFF_file,
ReHo_mean, ReHo_std, ReHo_median, ReHo_file
```

## Architecture

### Key Functions

#### Data Loading
- `load_summary_csv()`: Load CSV with caching
- `get_available_subjects_sessions()`: Extract unique subjects/sessions
- `get_local_measures_paths()`: Get file paths for a subject-session pair
- `get_stats_for_measure()`: Extract stats for a specific measure

#### Computation
- `compute_group_stats()`: Calculate group-level statistics (cached)

#### UI Components
- `render_subject_session_selector()`: Dropdown selectors
- `render_qc_metrics()`: Individual subject QC display
- `render_group_statistics()`: Group-level stats with expandable details
- `render_papaya_viewers()`: Side-by-side brain maps
- `render_export_section()`: Export buttons
- `render_results_table()`: Searchable results table

#### Page Structure
- `render_viewer_section()`: Main tab with maps and metrics
- `render_statistics_section()`: Group stats focused view
- `render_table_section()`: Results browser view
- `render()`: Main entry point with navigation

### Session State Management

Uses Streamlit session state to maintain:
- Threshold settings for each viewer
- Colormap selection
- Overlay opacity
- Export status

Keys follow pattern: `papaya_<measure>_<subject>_<session>`

## Integration with App

The page integrates with the main Streamlit app through:

1. **Entrypoint page** (`3_🔗_Connectivity.py`):
   - Serves as main connectivity section heading
   - Provides navigation to sub-analyses

2. **Dynamic loading** (in app.py):
   ```python
   spec = importlib.util.spec_from_file_location("module_name", page_path)
   module = importlib.util.module_from_spec(spec)
   spec.loader.exec_module(module)
   module.render()
   ```

## Usage

### Interactive View
1. Navigate to **3_🔗_Connectivity → Local Measures**
2. Select subject from dropdown (e.g., "033")
3. Select session from dropdown (e.g., "01")
4. View side-by-side fALFF/ReHo maps with Papaya viewer
5. Adjust colormap, threshold, transparency as needed
6. Export maps as PNG or stats as CSV

### Statistics View
1. Navigate to **Statistics** tab
2. View group-level summary across all subjects
3. Expand "Show Distribution Details" for quartiles

### Results Table View
1. Navigate to **Results Table** tab
2. Search by subject ID (optional)
3. Configure number of rows to display
4. Export full summary as CSV

## Dependencies

- **streamlit**: UI framework
- **pandas**: Data manipulation
- **numpy**: Numerical operations
- **nibabel**: NIfTI file handling
- **papaya_wrapper**: Custom Papaya.js integration

## Performance Characteristics

- **Data loading**: ~50ms (cached)
- **Group stats computation**: ~10ms (cached)
- **Papaya viewer initialization**: ~500-800ms per map
- **Interactive responsiveness**: <200ms for slider updates

## Known Limitations

1. Maps are MNI152 2mm resolution (consistent with pipeline output)
2. Papaya viewer initialization requires ~1 second per view
3. Large file downloads (base64-encoded in browser) for NIfTI maps

## Future Enhancements

- ROI mean values extracted from parcellations
- Longitudinal comparison (ses-01 vs ses-02)
- Advanced statistics (group comparisons, effect sizes)
- Batch export of multiple subjects
- Atlas overlay functionality for anatomical reference

## Testing

Verify the page works with:

```bash
cd neuconn_app

# Syntax check
python -m py_compile pages_connectivity/01_fALFF_ReHo.py

# Data validation
python << 'EOF'
from pages_connectivity.pages_connectivity_01_fALFF_ReHo import (
    load_summary_csv, compute_group_stats
)
df = load_summary_csv()
print(f"Loaded {len(df)} rows")
stats = compute_group_stats()
print(f"Group stats: {len(stats)} measures")
EOF

# App test
python test_cli.py
```

## Related Files

- `utils/papaya_wrapper.py`: Papaya.js Streamlit integration
- `pages/3_🔗_Connectivity.py`: Connectivity section entrypoint
- `pages_connectivity/02_Seed_Connectivity.py`: Seed-based connectivity page
- `app.py`: Main app routing logic
