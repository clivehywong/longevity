# HTML Report Exporter

Generate standalone, print-friendly HTML reports for neuroimaging analysis results.

## Overview

The report exporter creates self-contained HTML files with embedded:
- **Papaya 3D brain viewers** - Interactive NIfTI visualization
- **Correlation matrices** - Color-coded heatmaps with statistics
- **Cluster tables** - Group-level statistics with anatomical labels
- **Summary statistics** - Key metrics and analysis parameters
- **Print-friendly CSS** - Optimized layouts for screen and print

All assets are embedded as base64 to create truly standalone files that work offline.

## Files

### `utils/report_exporter.py`
Core report generation library with:
- `ReportBuilder` - Main class for building reports
- Asset embedding functions for NIfTI, images, and data
- HTML templating and CSS styling
- Convenience export functions

### `pages_fmri/connectivity/04_Export_Report.py`
Streamlit UI page for report generation with:
- Group statistics export
- Connectivity matrix export
- Local measures export (coming soon)
- Custom report builder

## Quick Start

### Using the Streamlit UI

1. Open the app: `streamlit run app.py`
2. Navigate to: **🧠 fMRI Analysis** → **Export Report**
3. Choose a report type:
   - **Group Statistics** - Export statistical maps with cluster tables
   - **Connectivity Matrix** - Export correlation matrices
   - **Local Measures** - Export ReHo, fALFF, etc. (coming soon)
   - **Custom Report** - Combine components manually

4. Fill in required fields and click **Export Report**
5. Report saves to `~/Downloads/`

### Using the Python API

```python
from utils.report_exporter import ReportBuilder, export_connectivity_report
import pandas as pd
import numpy as np

# Option 1: Use convenience function for quick export
export_connectivity_report(
    output_path="~/Downloads/report.html",
    fc_csv="connectivity_matrix.csv",
    title="My Connectivity Report",
)

# Option 2: Build custom report with multiple components
builder = ReportBuilder(
    title="Comprehensive Analysis",
    analysis_type="group_stats",
    output_path="~/Downloads/report.html",
)

# Add components in order
builder.add_header(metadata={"Analysis": "Seed-based", "N": "44"})

# Add Papaya viewer for brain map
builder.add_papaya_viewer(
    brain_map_path="/path/to/stat_map.nii.gz",
    colormap="Hot",
    threshold_range=(0, 100),
)

# Add cluster table
clusters_df = pd.read_csv("clusters.csv")
builder.add_cluster_table(clusters_df)

# Add summary stats
builder.add_summary_stats("Analysis Summary", {
    "Clusters": len(clusters_df),
    "Method": "GRF correction",
})

# Build and save
report_path = builder.build()
```

## Report Types

### Group Statistics Report

Export group-level analysis with:
- Statistical map in Papaya viewer
- Cluster table with MNI coordinates
- Anatomical labels
- Peak statistics (t-values, p-values)

**Inputs:**
- Statistical NIfTI map (e.g., t-stat, z-stat)
- Optional cluster CSV with columns:
  - `cluster_id`, `size_voxels`, `peak_t`
  - `peak_x`, `peak_y`, `peak_z`
  - `anatomical_region`, `p_value`, `q_value`

**Output:** Standalone HTML with interactive 3D viewer

### Connectivity Matrix Report

Export functional connectivity:
- Correlation matrix as interactive heatmap table
- Color-coded by strength (warm=positive, cool=negative)
- ROI labels and statistics

**Inputs:**
- Correlation matrix (CSV or NumPy array)
- ROI labels (optional, auto-generated if not provided)

**Output:** HTML with color-coded correlation table and statistics

### Local Measures Report

Export local measure analysis:
- ReHo (Regional Homogeneity) maps
- fALFF (Fractional Amplitude of Low Frequency Fluctuations)
- Other local measures with Papaya viewers

**Inputs:**
- NIfTI files for each measure
- Optional group-level statistics

**Output:** Multi-page HTML with 3D viewers

### Custom Report

Mix and match components:
- Select which components to include
- Order and title each section
- Add custom metadata

**Components:**
- Brain map (Papaya viewer)
- Correlation matrix
- Cluster table
- Summary statistics
- Custom HTML sections

## Component Reference

### Headers

```python
builder.add_header(metadata={
    "Analysis": "Seed-based connectivity",
    "Seed": "DLPFC L",
    "N": "44 subjects",
    "Method": "GRF correction",
})
```

### Papaya Viewer

```python
builder.add_papaya_viewer(
    brain_map_path="/path/to/stat_map.nii.gz",
    overlays=["/path/to/atlas.nii.gz"],  # Optional
    colormap="Hot",  # Hot, Jet, Viridis, Gray
    threshold_range=(0, 100),  # Percentile range
    overlay_alpha=0.7,  # Transparency
    title="Statistical Map",
    viewer_id="viewer1",  # Unique ID
)
```

**Supported Colormaps:**
- Hot, Jet, Viridis, Gray
- Spectrum, Rainbow, and others (see Papaya docs)

### Correlation Matrix

```python
builder.add_correlation_matrix(
    matrix=fc_matrix,  # (N, N) numpy array
    roi_labels=roi_names,  # List of N ROI names
    title="Functional Connectivity",
    threshold=0.3,  # Highlight correlations above this
)
```

### Cluster Table

```python
builder.add_cluster_table(
    clusters_df,  # pandas DataFrame
    title="Significant Clusters",
)
```

**Required columns:**
- `cluster_id` - Cluster number
- `size_voxels` - Size in voxels
- `peak_t` (or similar stat) - Peak statistic value
- `peak_x`, `peak_y`, `peak_z` - MNI coordinates
- Optional: `anatomical_region`, `p_value`, `q_value`

### Summary Statistics

```python
builder.add_summary_stats(
    title="Analysis Summary",
    stats={
        "Total Clusters": 42,
        "Mean T-value": 4.23,
        "Coverage": "15,243 voxels",
    },
)
```

### Custom HTML

```python
builder.add_html_section("""
<div class="report-section">
    <h2>Custom Section</h2>
    <p>Any valid HTML here...</p>
</div>
""")
```

## Features

### Standalone Files

All assets are embedded as base64, so reports:
- ✅ Work without internet access
- ✅ Can be emailed as single files
- ✅ Don't require external dependencies
- ✅ Load instantly in any modern browser

### Interactive 3D Viewer

Papaya viewer features:
- Mouse controls: left = rotate, scroll = zoom
- Crosshair for coordinate navigation
- Display MNI and voxel coordinates
- Threshold and colormap adjustment
- Overlay with multiple layers

### Print-Friendly Design

CSS optimizes for:
- Screen viewing (gradients, colors)
- Print output (black/white, page breaks)
- Responsive layout (desktop/tablet/mobile)
- PDF export (print to PDF from browser)

### Responsive Layout

- Desktop: Full width with side-by-side layouts
- Tablet: Single column, optimized touch targets
- Mobile: Simplified view with readable fonts

## Output

Reports save to `~/Downloads/` by default or custom location.

**File Structure:**
```
report.html  (Single file, ~100 KB - 1.5 MB depending on data)
├── HTML document
├── Embedded CSS
├── Embedded JavaScript
├── Papaya.js library
├── NIfTI data (base64)
├── Correlation matrices
└── Cluster tables
```

## Examples

### Example 1: Export Group Stats

```python
from utils.report_exporter import export_group_stats_report

export_group_stats_report(
    output_path="~/Downloads/group_stats.html",
    group_results_dir="/path/to/group_results/",
    brain_map_path="/path/to/t_stat_map.nii.gz",
    clusters_csv="/path/to/clusters.csv",
    title="Seed-based Connectivity - Group Analysis",
    metadata={
        "Seed": "DLPFC L",
        "Analysis": "Seed-based connectivity",
        "N subjects": "44",
        "Correction": "GRF",
    },
)
```

### Example 2: Build Custom Report

```python
from utils.report_exporter import ReportBuilder
import pandas as pd

builder = ReportBuilder(
    title="Comprehensive fMRI Analysis",
    analysis_type="combined",
    output_path="~/Downloads/combined_analysis.html",
)

# Add components
builder.add_header(metadata={"Project": "Longevity", "Date": "2024-04-29"})

# Brain map
builder.add_papaya_viewer(
    brain_map_path="reho_map.nii.gz",
    title="Regional Homogeneity",
)

# Connectivity
builder.add_correlation_matrix(
    matrix=my_fc_matrix,
    roi_labels=roi_names,
    title="Resting-State Connectivity",
)

# Stats
builder.add_cluster_table(pd.read_csv("clusters.csv"))

# Build
report_path = builder.build()
print(f"Report saved to: {report_path}")
```

### Example 3: Export from Results Directory

```python
from pathlib import Path
from utils.report_exporter import export_group_stats_report

# Find all group-level results
results_dir = Path("/home/clivewong/proj/longevity/results/group_analysis")

for analysis_dir in results_dir.glob("*/"):
    stat_map = analysis_dir / "t_stat.nii.gz"
    clusters = analysis_dir / "clusters.csv"
    
    if stat_map.exists():
        output_file = Path.home() / "Downloads" / f"{analysis_dir.name}_report.html"
        
        export_group_stats_report(
            output_path=str(output_file),
            group_results_dir=str(analysis_dir),
            brain_map_path=str(stat_map),
            clusters_csv=str(clusters) if clusters.exists() else None,
            title=f"Report: {analysis_dir.name}",
        )
```

## Styling and Customization

### CSS Classes

The generated HTML uses semantic CSS classes:

```css
.report-container      /* Main container */
.report-header        /* Report header */
.report-section       /* Content sections */
.stat-card            /* Statistics cards */
.papaya-container     /* Papaya viewer wrapper */
.matrix-container     /* Matrix table wrapper */
.cluster-table        /* Cluster table */
.report-footer        /* Footer */
```

### Custom CSS

Add custom CSS when building:

```python
custom_css = """
.report-header { background-color: #003366; }
.report-section h2 { color: #0066cc; }
"""

html = generate_base_html_template(
    title="My Report",
    content=sections,
    css=custom_css,
)
```

## Performance

- **Small reports** (connectivity only): ~1-2 MB
- **Large reports** (256×256 FC + NIfTI): ~2-4 MB
- **Render time**: < 1s for loading in browser
- **Print time**: < 5s for PDF export

## Browser Compatibility

Works in all modern browsers:
- ✅ Chrome/Edge (latest)
- ✅ Firefox (latest)
- ✅ Safari (latest)
- ✅ Mobile browsers

Requires:
- ES6 JavaScript support
- Canvas API (for Papaya viewer)
- SVG support (for plots)

## Troubleshooting

### Report shows blank

Check browser console (F12) for errors:
- Papaya library might not have loaded
- Base64 data might be corrupted
- JavaScript error in initialization

### Papaya viewer not showing

- Verify NIfTI file path is correct
- Check file exists and is valid NIfTI
- Try with different NIfTI file to isolate issue

### Large file size

Reports embedding large connectivity matrices or multiple NIfTI files can be large:
- ~1.5 MB for 256×256 correlation matrix
- ~350 KB per NIfTI file
- Consider splitting into multiple reports

### Print layout broken

- Use print preview before printing (Ctrl/Cmd+P)
- Try exporting to PDF via print dialog
- Some browsers handle page breaks better than others

## Advanced Usage

### Batch Export

```python
from pathlib import Path
from utils.report_exporter import export_group_stats_report
import glob

# Export all seed-based connectivity results
for seed_dir in Path("results/group_analysis").glob("seed_*"):
    stat_map = seed_dir / "t_stat.nii.gz"
    if stat_map.exists():
        seed_name = seed_dir.name.replace("seed_", "")
        export_group_stats_report(
            output_path=f"~/Downloads/{seed_name}_report.html",
            group_results_dir=str(seed_dir),
            brain_map_path=str(stat_map),
            title=f"Seed-based Connectivity: {seed_name}",
        )
        print(f"Exported {seed_name}")
```

### Dynamic Report Generation

```python
def create_analysis_report(results_dir, output_dir):
    """Auto-detect analysis type and generate appropriate report."""
    
    from utils.report_exporter import export_group_stats_report
    from pathlib import Path
    
    results_path = Path(results_dir)
    
    # Detect available files
    stat_map = results_path / "t_stat.nii.gz"
    clusters = results_path / "clusters.csv"
    
    if stat_map.exists():
        export_group_stats_report(
            output_path=str(Path(output_dir) / "report.html"),
            group_results_dir=str(results_path),
            brain_map_path=str(stat_map),
            clusters_csv=str(clusters) if clusters.exists() else None,
            title=f"Analysis Report: {results_path.name}",
        )
        return f"Report generated: {output_dir}/report.html"
    else:
        return "No statistical map found"
```

## See Also

- `utils/papaya_wrapper.py` - Papaya viewer component
- `utils/group_stats_ui.py` - Group statistics UI component
- `utils/matrix_renderer.py` - Correlation matrix visualization
- `pages/06_📊_Group_Statistics.py` - Group stats exploration page

## License

MIT License - Part of NeuConn neuroimaging analysis suite
