"""
HTML Report Exporter for Connectivity Analysis Results

Generates standalone, static HTML reports with embedded:
- Papaya 3D brain map viewers
- Interactive correlation matrices
- Group statistics and cluster tables
- Summary statistics panels
- Print-friendly CSS styling

Features:
- Base64-embedded assets (no external dependencies)
- Responsive layout for screen and print
- Standalone executable HTML files
- Support for multiple analysis types
"""

import base64
import json
import os
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple
from datetime import datetime
import pandas as pd
import numpy as np
import nibabel as nib
import logging

logger = logging.getLogger(__name__)


# ==============================================================================
# Asset Embedding
# ==============================================================================

def load_file_as_base64(file_path: str) -> str:
    """Load any file and convert to base64 for embedding."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")
    
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    
    return base64.b64encode(file_bytes).decode("utf-8")


def load_nifti_as_base64(file_path: str) -> str:
    """Load NIfTI file and convert to base64."""
    file_path = str(file_path)
    
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"NIfTI file not found: {file_path}")
    
    # Validate NIfTI format
    try:
        nib.load(file_path)
    except Exception as e:
        raise ValueError(f"Invalid NIfTI file {file_path}: {e}")
    
    return load_file_as_base64(file_path)


def get_nifti_stats(file_path: str) -> Dict[str, Any]:
    """Get statistics about NIfTI file for display."""
    file_path = str(file_path)
    
    try:
        img = nib.load(file_path)
        data = img.get_fdata()
        valid_data = data[~np.isnan(data) & ~np.isinf(data)]
        
        if len(valid_data) == 0:
            return {
                "shape": tuple(data.shape),
                "min": 0,
                "max": 1,
                "mean": 0,
                "nonzero_voxels": 0,
            }
        
        return {
            "shape": tuple(data.shape),
            "min": float(np.min(valid_data)),
            "max": float(np.max(valid_data)),
            "mean": float(np.mean(valid_data)),
            "nonzero_voxels": int(np.count_nonzero(valid_data)),
        }
    except Exception as e:
        logger.error(f"Error getting NIfTI stats: {e}")
        return {"shape": (0, 0, 0), "min": 0, "max": 1, "mean": 0, "nonzero_voxels": 0}


# ==============================================================================
# HTML Template Builders
# ==============================================================================

def generate_base_html_template(
    title: str,
    content: str,
    css: Optional[str] = None,
    javascript: Optional[str] = None,
) -> str:
    """Generate base HTML structure with embedded CSS and JS."""
    
    default_css = get_default_css()
    final_css = default_css + ("\n" + css if css else "")
    
    final_js = javascript or ""
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    
    <!-- Papaya Viewer -->
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <!-- Plotly for interactive charts -->
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    
    <style>
{final_css}
    </style>
</head>
<body>
    <div class="report-container">
        {content}
    </div>
    
    <script>
{final_js}
    </script>
</body>
</html>"""
    
    return html


def get_default_css() -> str:
    """Return comprehensive CSS for report styling and print support."""
    return """
    * {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }
    
    body {
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        line-height: 1.6;
        color: #333;
        background-color: #f5f5f5;
    }
    
    .report-container {
        max-width: 1400px;
        margin: 0 auto;
        background-color: white;
        box-shadow: 0 0 10px rgba(0, 0, 0, 0.1);
    }
    
    /* Header and Title */
    .report-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        padding: 40px;
        text-align: center;
    }
    
    .report-header h1 {
        font-size: 2.5em;
        margin-bottom: 10px;
    }
    
    .report-header .metadata {
        font-size: 0.9em;
        opacity: 0.9;
    }
    
    /* Sections */
    .report-section {
        padding: 30px 40px;
        border-bottom: 1px solid #e0e0e0;
    }
    
    .report-section h2 {
        font-size: 1.8em;
        margin-bottom: 20px;
        color: #667eea;
        border-bottom: 3px solid #667eea;
        padding-bottom: 10px;
    }
    
    .report-section h3 {
        font-size: 1.3em;
        margin-top: 20px;
        margin-bottom: 15px;
        color: #555;
    }
    
    /* Summary Stats Grid */
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
        gap: 20px;
        margin: 20px 0;
    }
    
    .stat-card {
        background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
        padding: 20px;
        border-radius: 8px;
        box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
    }
    
    .stat-card h4 {
        font-size: 0.9em;
        color: #667eea;
        text-transform: uppercase;
        margin-bottom: 10px;
        letter-spacing: 1px;
    }
    
    .stat-card .value {
        font-size: 1.8em;
        font-weight: bold;
        color: #333;
    }
    
    .stat-card .unit {
        font-size: 0.85em;
        color: #888;
        margin-left: 5px;
    }
    
    /* Viewer Containers */
    .papaya-container {
        background-color: #f9f9f9;
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 15px;
        margin: 20px 0;
        min-height: 500px;
    }
    
    .papaya {
        width: 100% !important;
        height: 500px !important;
        border-radius: 5px;
    }
    
    .viewer-title {
        font-size: 1.1em;
        font-weight: bold;
        color: #333;
        margin-bottom: 10px;
    }
    
    /* Table Styling */
    table {
        width: 100%;
        border-collapse: collapse;
        margin: 20px 0;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
    }
    
    table thead {
        background-color: #667eea;
        color: white;
    }
    
    table th {
        padding: 15px;
        text-align: left;
        font-weight: 600;
        border: 1px solid #ddd;
    }
    
    table td {
        padding: 12px 15px;
        border: 1px solid #e0e0e0;
    }
    
    table tbody tr:nth-child(even) {
        background-color: #f9f9f9;
    }
    
    table tbody tr:hover {
        background-color: #f0f0f0;
    }
    
    /* Matrix Visualization */
    .matrix-container {
        background-color: #fff;
        border: 1px solid #ddd;
        border-radius: 8px;
        padding: 15px;
        margin: 20px 0;
        overflow-x: auto;
    }
    
    .plotly-container {
        width: 100%;
        height: 600px;
        margin: 20px 0;
    }
    
    /* Cluster Table Specific */
    .cluster-table {
        font-size: 0.95em;
    }
    
    .cluster-table td.cluster-id {
        font-weight: bold;
        color: #667eea;
    }
    
    .cluster-table td.size {
        text-align: right;
        font-family: monospace;
    }
    
    .cluster-table td.stats {
        text-align: right;
        font-family: monospace;
    }
    
    /* Statistics Sections */
    .stats-summary {
        background: #f9f9f9;
        border-left: 4px solid #667eea;
        padding: 15px;
        margin: 15px 0;
        border-radius: 4px;
    }
    
    .stats-summary dt {
        font-weight: bold;
        color: #667eea;
        margin-top: 10px;
    }
    
    .stats-summary dd {
        margin-left: 20px;
        color: #555;
    }
    
    /* Footer */
    .report-footer {
        padding: 20px 40px;
        text-align: center;
        background-color: #f5f5f5;
        color: #888;
        font-size: 0.9em;
        border-top: 1px solid #ddd;
    }
    
    /* Print Styles */
    @media print {
        body {
            background-color: white;
        }
        
        .report-container {
            box-shadow: none;
            max-width: 100%;
        }
        
        .report-section {
            page-break-inside: avoid;
            padding: 20px;
        }
        
        .papaya-container,
        .plotly-container,
        .matrix-container {
            page-break-inside: avoid;
        }
        
        table {
            page-break-inside: avoid;
        }
        
        .report-header {
            break-after: always;
        }
    }
    
    /* Responsive */
    @media (max-width: 768px) {
        .report-section {
            padding: 20px;
        }
        
        .stats-grid {
            grid-template-columns: 1fr;
        }
        
        .report-header h1 {
            font-size: 1.8em;
        }
        
        .report-section h2 {
            font-size: 1.4em;
        }
    }
"""


# ==============================================================================
# Report Component Generators
# ==============================================================================

def generate_header(
    title: str,
    analysis_type: str,
    timestamp: Optional[str] = None,
    metadata: Optional[Dict[str, str]] = None,
) -> str:
    """Generate report header section."""
    
    if timestamp is None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    metadata_str = ""
    if metadata:
        for key, value in metadata.items():
            metadata_str += f"<span>{key}: <strong>{value}</strong></span> | "
        metadata_str = metadata_str.rstrip(" | ")
    
    return f"""
    <div class="report-header">
        <h1>{title}</h1>
        <p class="metadata">
            Analysis: <strong>{analysis_type}</strong> | 
            Generated: <strong>{timestamp}</strong> | 
            {metadata_str}
        </p>
    </div>
    """


def generate_papaya_viewer(
    brain_map_path: str,
    overlays: Optional[List[str]] = None,
    colormap: str = "Hot",
    threshold_range: Tuple[float, float] = (0, 100),
    overlay_alpha: float = 0.5,
    title: str = "Brain Map",
    viewer_id: str = "papayaViewer1",
) -> Tuple[str, str]:
    """
    Generate Papaya viewer HTML and JavaScript.
    
    Args:
        brain_map_path: Path to primary brain map (must exist for embedding)
        overlays: List of overlay file paths (must exist)
        colormap: Primary image colormap name
        threshold_range: (min, max) threshold percentiles
        overlay_alpha: Transparency for overlays (0-1)
        title: Title for viewer section
        viewer_id: Unique HTML ID for viewer
    
    Returns:
        (html_content, javascript_code)
    """
    
    # Embed brain map as base64
    try:
        brain_map_b64 = load_nifti_as_base64(brain_map_path)
        brain_map_data = f"data:application/octet-stream;base64,{brain_map_b64}"
    except Exception as e:
        logger.error(f"Failed to embed brain map {brain_map_path}: {e}")
        return "", ""
    
    # Embed overlays
    overlay_data = []
    if overlays:
        for overlay_path in overlays:
            try:
                overlay_b64 = load_nifti_as_base64(overlay_path)
                overlay_data.append(f"data:application/octet-stream;base64,{overlay_b64}")
            except Exception as e:
                logger.warning(f"Failed to embed overlay {overlay_path}: {e}")
    
    # Build image array for Papaya
    images = [brain_map_b64]
    if overlay_data:
        # Need to handle base64 data URLs differently in Papaya
        images.extend([b64.split(",")[1] for b64 in overlay_data if "," in b64])
    
    # Params for Papaya
    min_thresh, max_thresh = threshold_range
    params = [images]  # Papaya expects array of images
    
    html = f"""
    <div class="report-section">
        <h2>{title}</h2>
        <div class="viewer-title">{title}</div>
        <div id="{viewer_id}" class="papaya-container">
            <div class="papaya" style="width: 100%; height: 500px;"></div>
        </div>
        <div class="stats-grid" style="margin-top: 10px;">
            <div class="stat-card">
                <h4>Colormap</h4>
                <div class="value" style="font-size: 1.0em; color: #667eea;">{colormap}</div>
            </div>
            <div class="stat-card">
                <h4>Threshold Range</h4>
                <div class="value" style="font-size: 1.0em;">
                    {min_thresh:.1f} - {max_thresh:.1f}%
                </div>
            </div>
            <div class="stat-card">
                <h4>Overlay Opacity</h4>
                <div class="value" style="font-size: 1.0em;">
                    {overlay_alpha * 100:.0f}%
                </div>
            </div>
        </div>
    </div>
    """
    
    javascript = f"""
    // Initialize Papaya viewer {viewer_id}
    (function() {{
        var params = {json.dumps(params)};
        
        // Delay initialization to ensure Papaya library is loaded
        if (typeof papaya !== 'undefined' && papaya.Container) {{
            var viewer = papaya.Container.addViewer("{viewer_id.replace('papayaViewer', 'papaya')}", params);
            
            setTimeout(function() {{
                if (viewer && viewer.viewer && viewer.viewer.screenVolumes) {{
                    var screenVolumes = viewer.viewer.screenVolumes;
                    
                    // Configure primary image
                    if (screenVolumes.length > 0) {{
                        screenVolumes[0].colorMap = "{colormap}";
                        screenVolumes[0].intensityMin = {min_thresh};
                        screenVolumes[0].intensityMax = {max_thresh};
                    }}
                    
                    // Configure overlays
                    if (screenVolumes.length > 1) {{
                        for (var i = 1; i < screenVolumes.length; i++) {{
                            screenVolumes[i].alpha = {overlay_alpha};
                        }}
                    }}
                }}
            }}, 500);
        }}
    }})();
    """
    
    return html, javascript


def generate_summary_stats(
    title: str,
    stats: Dict[str, Any],
) -> str:
    """Generate summary statistics panel."""
    
    cards_html = ""
    for key, value in stats.items():
        if isinstance(value, float):
            display_value = f"{value:.4f}"
        else:
            display_value = str(value)
        
        cards_html += f"""
        <div class="stat-card">
            <h4>{key}</h4>
            <div class="value">{display_value}</div>
        </div>
        """
    
    return f"""
    <div class="report-section">
        <h2>{title}</h2>
        <div class="stats-grid">
            {cards_html}
        </div>
    </div>
    """


def generate_cluster_table(
    clusters_df: pd.DataFrame,
    title: str = "Cluster Statistics",
) -> str:
    """Generate formatted cluster table."""
    
    # Format DataFrame for display
    display_df = clusters_df.copy()
    
    # Format numeric columns
    numeric_cols = display_df.select_dtypes(include=[np.number]).columns
    for col in numeric_cols:
        if col in ['peak_t', 'peak_f', 'stat', 'p_value', 'q_value']:
            display_df[col] = display_df[col].apply(lambda x: f"{x:.4f}" if pd.notna(x) else "N/A")
        elif col in ['size_voxels', 'size_mm3']:
            display_df[col] = display_df[col].apply(lambda x: f"{int(x)}" if pd.notna(x) else "N/A")
        else:
            display_df[col] = display_df[col].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "N/A")
    
    # Generate table HTML
    table_html = display_df.to_html(index=False, escape=False, classes="cluster-table")
    
    return f"""
    <div class="report-section">
        <h2>{title}</h2>
        <div class="matrix-container">
            {table_html}
        </div>
    </div>
    """


def generate_correlation_matrix_table(
    matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None,
    title: str = "Correlation Matrix",
    threshold: float = 0.3,
) -> str:
    """Generate correlation matrix as interactive table."""
    
    n = matrix.shape[0]
    
    if roi_labels is None:
        roi_labels = [f"ROI_{i+1}" for i in range(n)]
    
    # Create DataFrame for display with limited decimal places
    display_matrix = np.round(matrix, 3)
    df = pd.DataFrame(display_matrix, index=roi_labels, columns=roi_labels)
    
    # Generate table with conditional formatting
    table_html = '<table class="correlation-matrix">\n<thead><tr><th>ROI</th>'
    for label in roi_labels:
        table_html += f'<th>{label}</th>'
    table_html += '</tr></thead>\n<tbody>\n'
    
    for i, row_label in enumerate(roi_labels):
        table_html += f'<tr><td><strong>{row_label}</strong></td>'
        for j in range(n):
            value = display_matrix[i, j]
            # Color intensity based on correlation strength
            if abs(value) >= threshold:
                intensity = int((abs(value) - threshold) / (1 - threshold) * 255)
                if value > 0:
                    color = f"rgb(200, {255-intensity}, {255-intensity})"
                else:
                    color = f"rgb({255-intensity}, 200, 255)"
                table_html += f'<td style="background-color: {color};">{value:.3f}</td>'
            else:
                table_html += f'<td>{value:.3f}</td>'
        table_html += '</tr>\n'
    
    table_html += '</tbody></table>'
    
    return f"""
    <div class="report-section">
        <h2>{title}</h2>
        <div class="matrix-container">
            {table_html}
        </div>
        <p style="color: #888; font-size: 0.9em; margin-top: 10px;">
            Values below {threshold} threshold not highlighted. Warm colors = positive correlation, Cool colors = negative correlation.
        </p>
    </div>
    """


def generate_footer(
    generated_by: str = "NeuConn HTML Report Exporter",
) -> str:
    """Generate report footer."""
    
    return f"""
    <div class="report-footer">
        <p>Generated by {generated_by}</p>
        <p>© 2024 Longevity Neuroimaging Study. All rights reserved.</p>
        <p style="font-size: 0.8em; margin-top: 10px;">
            This is a static HTML file with all assets embedded. 
            It can be viewed in any modern web browser without internet access.
        </p>
    </div>
    """


# ==============================================================================
# Main Report Builder
# ==============================================================================

class ReportBuilder:
    """
    Build comprehensive HTML reports from neuroimaging analysis results.
    
    Handles multiple content types and generates standalone HTML files.
    """
    
    def __init__(
        self,
        title: str,
        analysis_type: str,
        output_path: str,
    ):
        """
        Initialize report builder.
        
        Args:
            title: Report title
            analysis_type: Type of analysis (e.g., 'seed_based', 'group_stats')
            output_path: Where to save the generated HTML file
        """
        self.title = title
        self.analysis_type = analysis_type
        self.output_path = Path(output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.sections = []
        self.javascripts = []
        self.metadata = {}
    
    def add_header(
        self,
        metadata: Optional[Dict[str, str]] = None,
    ) -> "ReportBuilder":
        """Add header section."""
        header_html = generate_header(
            self.title,
            self.analysis_type,
            metadata=metadata,
        )
        self.sections.append(header_html)
        if metadata:
            self.metadata.update(metadata)
        return self
    
    def add_papaya_viewer(
        self,
        brain_map_path: str,
        overlays: Optional[List[str]] = None,
        colormap: str = "Hot",
        threshold_range: Tuple[float, float] = (0, 100),
        overlay_alpha: float = 0.5,
        title: str = "Brain Map",
        viewer_id: Optional[str] = None,
    ) -> "ReportBuilder":
        """Add Papaya brain map viewer."""
        if viewer_id is None:
            viewer_id = f"papayaViewer{len(self.sections)}"
        
        html, js = generate_papaya_viewer(
            brain_map_path=brain_map_path,
            overlays=overlays,
            colormap=colormap,
            threshold_range=threshold_range,
            overlay_alpha=overlay_alpha,
            title=title,
            viewer_id=viewer_id,
        )
        
        if html and js:
            self.sections.append(html)
            self.javascripts.append(js)
        
        return self
    
    def add_summary_stats(
        self,
        title: str,
        stats: Dict[str, Any],
    ) -> "ReportBuilder":
        """Add summary statistics panel."""
        html = generate_summary_stats(title, stats)
        self.sections.append(html)
        return self
    
    def add_cluster_table(
        self,
        clusters_df: pd.DataFrame,
        title: str = "Cluster Statistics",
    ) -> "ReportBuilder":
        """Add cluster statistics table."""
        html = generate_cluster_table(clusters_df, title)
        self.sections.append(html)
        return self
    
    def add_correlation_matrix(
        self,
        matrix: np.ndarray,
        roi_labels: Optional[List[str]] = None,
        title: str = "Correlation Matrix",
        threshold: float = 0.3,
    ) -> "ReportBuilder":
        """Add correlation matrix table."""
        html = generate_correlation_matrix_table(
            matrix=matrix,
            roi_labels=roi_labels,
            title=title,
            threshold=threshold,
        )
        self.sections.append(html)
        return self
    
    def add_html_section(self, html_content: str) -> "ReportBuilder":
        """Add custom HTML section."""
        self.sections.append(html_content)
        return self
    
    def build(self) -> str:
        """
        Build and save the HTML report.
        
        Returns:
            Path to generated HTML file
        """
        # Add footer
        footer_html = generate_footer()
        self.sections.append(footer_html)
        
        # Combine all sections
        content = "\n".join(self.sections)
        
        # Combine all JavaScript
        js = "\n".join(self.javascripts)
        
        # Generate final HTML
        html = generate_base_html_template(
            title=self.title,
            content=content,
            javascript=js,
        )
        
        # Save to file
        with open(self.output_path, "w", encoding="utf-8") as f:
            f.write(html)
        
        logger.info(f"Report generated: {self.output_path}")
        
        return str(self.output_path)


# ==============================================================================
# Convenience Functions
# ==============================================================================

def export_group_stats_report(
    output_path: str,
    group_results_dir: str,
    brain_map_path: str,
    clusters_csv: Optional[str] = None,
    title: str = "Group-Level Statistics Report",
    metadata: Optional[Dict[str, str]] = None,
) -> str:
    """
    Export group statistics as HTML report.
    
    Args:
        output_path: Where to save HTML file
        group_results_dir: Directory containing group analysis results
        brain_map_path: Path to statistical map (NIfTI)
        clusters_csv: Optional path to cluster table CSV
        title: Report title
        metadata: Optional metadata to display
    
    Returns:
        Path to generated HTML file
    """
    
    builder = ReportBuilder(
        title=title,
        analysis_type="group_statistics",
        output_path=output_path,
    )
    
    # Add header
    builder.add_header(metadata=metadata)
    
    # Add brain map viewer
    builder.add_papaya_viewer(
        brain_map_path=brain_map_path,
        title="Statistical Map",
        colormap="Hot",
    )
    
    # Add cluster table if available
    if clusters_csv and os.path.exists(clusters_csv):
        try:
            clusters_df = pd.read_csv(clusters_csv)
            builder.add_cluster_table(clusters_df)
        except Exception as e:
            logger.warning(f"Could not load cluster table: {e}")
    
    return builder.build()


def export_connectivity_report(
    output_path: str,
    fc_matrix: Optional[np.ndarray] = None,
    fc_csv: Optional[str] = None,
    roi_labels: Optional[List[str]] = None,
    title: str = "Connectivity Report",
    metadata: Optional[Dict[str, str]] = None,
) -> str:
    """
    Export functional connectivity as HTML report.
    
    Args:
        output_path: Where to save HTML file
        fc_matrix: Correlation matrix (N×N)
        fc_csv: Alternative path to CSV file
        roi_labels: Optional ROI labels
        title: Report title
        metadata: Optional metadata
    
    Returns:
        Path to generated HTML file
    """
    
    # Load matrix if CSV provided
    if fc_matrix is None and fc_csv:
        try:
            df = pd.read_csv(fc_csv, index_col=0)
            fc_matrix = df.values
            if roi_labels is None:
                roi_labels = df.columns.tolist()
        except Exception as e:
            logger.error(f"Could not load FC matrix: {e}")
            return ""
    
    if fc_matrix is None:
        logger.error("No matrix data provided")
        return ""
    
    builder = ReportBuilder(
        title=title,
        analysis_type="connectivity_analysis",
        output_path=output_path,
    )
    
    builder.add_header(metadata=metadata)
    builder.add_correlation_matrix(fc_matrix, roi_labels=roi_labels)
    
    return builder.build()
