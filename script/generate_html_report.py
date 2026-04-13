#!/usr/bin/env python3
"""
Interactive HTML Report Generator for Connectivity Analysis Results

Creates a self-contained HTML report with:
- Collapsible sidebar navigation with significance highlighting
- Statistical summary tables
- Brain visualizations (axial, coronal, sagittal slices)
- Interactive plots with Plotly
- Cluster tables for whole-brain analyses
- Effect size plots

Usage:
    python generate_html_report.py \
        --results-dir results/ \
        --output results/connectivity_report.html

Dependencies:
    pip install pandas numpy matplotlib plotly nibabel nilearn
"""

import argparse
import base64
import json
import warnings
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from nilearn import plotting, image

warnings.filterwarnings('ignore')


def scan_results_directory(results_dir):
    """
    Scan results directory and categorize analyses.

    Returns
    -------
    structure : dict
        Hierarchical structure of analyses with file paths
    """
    results_dir = Path(results_dir)

    structure = {
        'local_measures': {},
        'seed_based': {},
        'network_connectivity': {
            'within_network': {},
            'between_network': {}
        }
    }

    # Scan for local measures
    local_dir = results_dir / 'local_measures'
    if local_dir.exists():
        structure['local_measures']['fALFF'] = scan_analysis_dir(results_dir / 'group_analysis' / 'fALFF')
        structure['local_measures']['ReHo'] = scan_analysis_dir(results_dir / 'group_analysis' / 'ReHo')

    # Scan for seed-based analyses
    # Check both group_analysis/seed_* and seed_* patterns
    seed_dir = results_dir / 'group_analysis'
    if seed_dir.exists():
        for analysis_dir in seed_dir.glob('seed_*'):
            seed_name = analysis_dir.name.replace('seed_', '').replace('_', ' ').title()
            structure['seed_based'][seed_name] = scan_analysis_dir(analysis_dir)
    else:
        # Also check for seed_* directly in results_dir
        for analysis_dir in results_dir.glob('seed_*'):
            seed_name = analysis_dir.name.replace('seed_', '').replace('_', ' ').title()
            structure['seed_based'][seed_name] = scan_analysis_dir(analysis_dir)

    # Scan for network connectivity
    network_dir = results_dir / 'network_connectivity'
    if network_dir.exists():
        for analysis_dir in network_dir.iterdir():
            if not analysis_dir.is_dir():
                continue

            if analysis_dir.name.startswith('within_'):
                network_name = analysis_dir.name.replace('within_', '').replace('_', ' ').title()
                structure['network_connectivity']['within_network'][network_name] = scan_analysis_dir(analysis_dir)
            elif analysis_dir.name.startswith('between_'):
                pair_name = analysis_dir.name.replace('between_', '').replace('_', ' ↔ ').title()
                structure['network_connectivity']['between_network'][pair_name] = scan_analysis_dir(analysis_dir)

    return structure


def scan_analysis_dir(analysis_dir):
    """
    Scan an individual analysis directory for result files.

    Returns
    -------
    files : dict
        Dictionary with keys: anova_results, significant_results, effect_sizes,
                              tstat_map, thresholded_map, cluster_table,
                              cluster_barplots, correction_info, model_info
    """
    if not analysis_dir or not Path(analysis_dir).exists():
        return {}

    analysis_dir = Path(analysis_dir)
    files = {}

    # CSV files
    if (analysis_dir / 'connectivity_anova_results.csv').exists():
        files['anova_results'] = str(analysis_dir / 'connectivity_anova_results.csv')
    if (analysis_dir / 'significant_interactions_fdr.csv').exists():
        files['significant_results'] = str(analysis_dir / 'significant_interactions_fdr.csv')
    if (analysis_dir / 'effect_sizes.csv').exists():
        files['effect_sizes'] = str(analysis_dir / 'effect_sizes.csv')
    if (analysis_dir / 'clusters_interaction.csv').exists():
        files['cluster_table'] = str(analysis_dir / 'clusters_interaction.csv')

    # JSON files for metadata
    if (analysis_dir / 'correction_info.json').exists():
        with open(analysis_dir / 'correction_info.json') as f:
            files['correction_info'] = json.load(f)
    else:
        files['correction_info'] = {}

    if (analysis_dir / 'model_info.json').exists():
        with open(analysis_dir / 'model_info.json') as f:
            files['model_info'] = json.load(f)
    else:
        files['model_info'] = {}

    # NIfTI maps (check both FWE-corrected and uncorrected)
    if (analysis_dir / 'interaction_tstat_map.nii.gz').exists():
        files['tstat_map'] = str(analysis_dir / 'interaction_tstat_map.nii.gz')

    # Priority: FWE-corrected map first, then uncorrected fallback
    thresholded_map = None
    correction_method = 'unknown'

    for thresh_file in analysis_dir.glob('interaction_fwe_p*.nii.gz'):
        thresholded_map = str(thresh_file)
        correction_method = 'FWE'
        break

    if not thresholded_map:
        for thresh_file in analysis_dir.glob('interaction_uncorr_p*.nii.gz'):
            thresholded_map = str(thresh_file)
            correction_method = 'uncorrected'
            break

    if thresholded_map:
        files['thresholded_map'] = thresholded_map
        if not files['correction_info']:
            files['correction_info'] = {'method': correction_method}

    # Cluster barplots
    barplot_dir = analysis_dir / 'cluster_barplots'
    if barplot_dir.exists():
        barplots = list(barplot_dir.glob('cluster_*_barplot.png'))
        if barplots:
            files['cluster_barplots'] = sorted([str(bp) for bp in barplots])

    # Brain visualizations
    viz_files = {
        'tstat_ortho': analysis_dir / 'tstat_map_ortho.png',
        'thresh_ortho': analysis_dir / 'thresholded_map_ortho.png',
        'thresh_mosaic': analysis_dir / 'thresholded_map_mosaic.png',
        'thresh_glass': analysis_dir / 'thresholded_map_glass.png'
    }

    for key, path in viz_files.items():
        if path.exists():
            files[key] = str(path)

    # Check if significant results exist
    files['has_significant'] = False
    if 'significant_results' in files:
        sig_df = pd.read_csv(files['significant_results'])
        files['has_significant'] = len(sig_df) > 0
    elif 'cluster_table' in files:
        cluster_df = pd.read_csv(files['cluster_table'])
        files['has_significant'] = len(cluster_df) > 0

    return files


def render_brain_slices(stat_map_file, threshold=2.0):
    """
    Render brain slices as base64-encoded PNG.

    Returns
    -------
    img_base64 : str
        Base64-encoded PNG image
    """
    try:
        stat_img = image.load_img(stat_map_file)

        # Create figure
        display = plotting.plot_stat_map(
            stat_img,
            threshold=threshold,
            display_mode='ortho',
            colorbar=True,
            cmap='RdBu_r',
            symmetric_cbar=True,
            annotate=False,
            draw_cross=False
        )

        # Save to BytesIO
        buf = BytesIO()
        display.savefig(buf, format='png', dpi=100, bbox_inches='tight')
        buf.seek(0)

        # Encode as base64
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        buf.close()
        plt.close()

        return img_base64

    except Exception as e:
        print(f"  Warning: Could not render brain slices for {stat_map_file}: {e}")
        return None


def create_effect_size_plot(effect_df, analysis_name):
    """
    Create interactive effect size plot with Plotly.

    Returns
    -------
    plotly_json : str
        JSON string for Plotly figure
    """
    if effect_df.empty:
        return None

    # Take top 20 connections by effect size
    effect_df = effect_df.sort_values('cohens_d_interaction', key=abs, ascending=False).head(20)

    # Create bar plot
    fig = go.Figure()

    fig.add_trace(go.Bar(
        x=effect_df['cohens_d_interaction'],
        y=[f"ROI {row['roi_i']} - ROI {row['roi_j']}" for _, row in effect_df.iterrows()],
        orientation='h',
        marker=dict(
            color=effect_df['cohens_d_interaction'],
            colorscale='RdBu_r',
            cmid=0,
            colorbar=dict(title="Cohen's d")
        ),
        hovertemplate='<b>%{y}</b><br>Cohen\'s d: %{x:.3f}<extra></extra>'
    ))

    fig.update_layout(
        title=f"{analysis_name}: Effect Sizes (Top 20 Connections)",
        xaxis_title="Cohen's d (Group × Time Interaction)",
        yaxis_title="Connection",
        height=600,
        margin=dict(l=200, r=50, t=50, b=50),
        hovermode='closest'
    )

    return fig.to_json()


def create_sidebar_html(structure):
    """
    Generate HTML for collapsible sidebar navigation.

    Returns
    -------
    sidebar_html : str
    """
    html = '<ul class="analysis-tree">'

    # Local Measures
    if structure['local_measures']:
        html += '<li class="collapsible">'
        html += '<span class="folder-icon">📁</span> Local Measures'
        html += '<ul class="nested">'
        for measure_name, files in structure['local_measures'].items():
            if files:
                css_class = 'significant' if files.get('has_significant', False) else ''
                html += f'<li class="{css_class}"><a href="#" data-analysis="local_{measure_name}">{measure_name}</a></li>'
        html += '</ul></li>'

    # Seed-Based Connectivity
    if structure['seed_based']:
        html += '<li class="collapsible">'
        html += '<span class="folder-icon">📁</span> Seed-Based Connectivity'
        html += '<ul class="nested">'
        for seed_name, files in structure['seed_based'].items():
            if files:
                css_class = 'significant' if files.get('has_significant', False) else ''
                html += f'<li class="{css_class}"><a href="#" data-analysis="seed_{seed_name}">{seed_name}</a></li>'
        html += '</ul></li>'

    # Network Connectivity
    if structure['network_connectivity']['within_network'] or structure['network_connectivity']['between_network']:
        html += '<li class="collapsible">'
        html += '<span class="folder-icon">📁</span> Network Connectivity'
        html += '<ul class="nested">'

        # Within-network
        if structure['network_connectivity']['within_network']:
            html += '<li class="collapsible">'
            html += '<span class="folder-icon">📁</span> Within Network'
            html += '<ul class="nested">'
            for net_name, files in structure['network_connectivity']['within_network'].items():
                if files:
                    css_class = 'significant' if files.get('has_significant', False) else ''
                    html += f'<li class="{css_class}"><a href="#" data-analysis="within_{net_name}">{net_name}</a></li>'
            html += '</ul></li>'

        # Between-network
        if structure['network_connectivity']['between_network']:
            html += '<li class="collapsible">'
            html += '<span class="folder-icon">📁</span> Between Network'
            html += '<ul class="nested">'
            for pair_name, files in structure['network_connectivity']['between_network'].items():
                if files:
                    css_class = 'significant' if files.get('has_significant', False) else ''
                    html += f'<li class="{css_class}"><a href="#" data-analysis="between_{pair_name}">{pair_name}</a></li>'
            html += '</ul></li>'

        html += '</ul></li>'

    html += '</ul>'
    return html


def create_analysis_content_html(analysis_id, files):
    """
    Generate HTML content for an analysis.

    Returns
    -------
    content_html : str
    """
    html = f'<div class="analysis-content" id="content_{analysis_id}" style="display:none;">'
    html += f'<h2>{analysis_id.replace("_", " ").title()}</h2>'

    # Summary statistics
    if 'anova_results' in files:
        anova_df = pd.read_csv(files['anova_results'])
        html += '<h3>Statistical Summary</h3>'
        html += '<table class="stats-table">'
        html += '<tr><th>Metric</th><th>Value</th></tr>'
        html += f'<tr><td>Total connections tested</td><td>{len(anova_df)}</td></tr>'

        if 'interaction_significant_fdr' in anova_df.columns:
            n_sig = anova_df['interaction_significant_fdr'].sum()
            html += f'<tr><td>Significant interactions (FDR q<0.05)</td><td><b>{n_sig}</b></td></tr>'

    # Significant results table
    if 'significant_results' in files:
        sig_df = pd.read_csv(files['significant_results'])
        if len(sig_df) > 0:
            html += '<h3>Significant Connections (FDR Corrected)</h3>'
            # Show top 10
            display_df = sig_df.head(10)[['roi_i', 'roi_j', 'interaction_coef', 'interaction_tstat', 'interaction_pval_fdr']]
            html += display_df.to_html(classes='results-table', index=False, float_format='%.4f')

            if len(sig_df) > 10:
                html += f'<p><i>Showing top 10 of {len(sig_df)} significant connections</i></p>'

    # Cluster table
    if 'cluster_table' in files:
        cluster_df = pd.read_csv(files['cluster_table'])
        if len(cluster_df) > 0:
            html += '<h3>Cluster Table</h3>'
            html += cluster_df.to_html(classes='results-table', index=False, float_format='%.2f')

    # Brain visualization
    if 'thresholded_map' in files:
        html += '<h3>Brain Visualization (FWE Corrected)</h3>'
        img_base64 = render_brain_slices(files['thresholded_map'], threshold=0.1)
        if img_base64:
            html += f'<img src="data:image/png;base64,{img_base64}" class="brain-img" />'
    elif 'tstat_map' in files:
        html += '<h3>Brain Visualization (T-statistic Map)</h3>'
        img_base64 = render_brain_slices(files['tstat_map'], threshold=2.0)
        if img_base64:
            html += f'<img src="data:image/png;base64,{img_base64}" class="brain-img" />'

    # Effect size plot (embedded Plotly JSON)
    if 'effect_sizes' in files:
        effect_df = pd.read_csv(files['effect_sizes'])
        plotly_json = create_effect_size_plot(effect_df, analysis_id)
        if plotly_json:
            html += '<h3>Effect Sizes (Top Connections)</h3>'
            html += f'<div id="plotly_{analysis_id}" class="plotly-plot"></div>'
            html += f'<script>renderPlotly("plotly_{analysis_id}", {plotly_json});</script>'

    html += '</div>'
    return html


def generate_html_report(results_dir, output_file):
    """
    Generate complete HTML report.

    Parameters
    ----------
    results_dir : str
        Path to results directory
    output_file : str
        Output HTML file path
    """
    print("=" * 60)
    print("GENERATING HTML REPORT")
    print("=" * 60)

    # Scan results directory
    print("Scanning results directory...")
    structure = scan_results_directory(results_dir)

    # Count total analyses
    n_local = len([f for f in structure['local_measures'].values() if f])
    n_seed = len([f for f in structure['seed_based'].values() if f])
    n_within = len([f for f in structure['network_connectivity']['within_network'].values() if f])
    n_between = len([f for f in structure['network_connectivity']['between_network'].values() if f])
    n_total = n_local + n_seed + n_within + n_between

    print(f"  Local measures: {n_local}")
    print(f"  Seed-based: {n_seed}")
    print(f"  Within-network: {n_within}")
    print(f"  Between-network: {n_between}")
    print(f"  Total analyses: {n_total}")

    if n_total == 0:
        print("ERROR: No analyses found in results directory")
        return 1

    # Generate sidebar HTML
    print("Generating sidebar navigation...")
    sidebar_html = create_sidebar_html(structure)

    # Generate content for each analysis
    print("Generating analysis content...")
    all_content_html = []

    # Flatten structure for content generation
    all_analyses = {}
    for measure_name, files in structure['local_measures'].items():
        if files:
            all_analyses[f"local_{measure_name}"] = files
    for seed_name, files in structure['seed_based'].items():
        if files:
            all_analyses[f"seed_{seed_name}"] = files
    for net_name, files in structure['network_connectivity']['within_network'].items():
        if files:
            all_analyses[f"within_{net_name}"] = files
    for pair_name, files in structure['network_connectivity']['between_network'].items():
        if files:
            all_analyses[f"between_{pair_name}"] = files

    for analysis_id, files in all_analyses.items():
        print(f"  Processing {analysis_id}...")
        content_html = create_analysis_content_html(analysis_id, files)
        all_content_html.append(content_html)

    # Complete HTML template
    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Walking Intervention Connectivity Analysis Report</title>
    <script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f5f5f5;
        }}
        #sidebar {{
            width: 320px;
            position: fixed;
            height: 100vh;
            overflow-y: auto;
            background-color: #2c3e50;
            color: white;
            padding: 20px;
        }}
        #sidebar h1 {{
            font-size: 20px;
            margin-bottom: 20px;
            color: #ecf0f1;
        }}
        #main-panel {{
            margin-left: 340px;
            padding: 30px;
            background-color: white;
            min-height: 100vh;
        }}
        .analysis-tree {{
            list-style-type: none;
            margin: 0;
            padding: 0;
        }}
        .analysis-tree li {{
            margin: 5px 0;
        }}
        .analysis-tree a {{
            color: #ecf0f1;
            text-decoration: none;
            display: block;
            padding: 8px 10px;
            border-radius: 4px;
            transition: background-color 0.2s;
        }}
        .analysis-tree a:hover {{
            background-color: #34495e;
        }}
        .collapsible {{
            cursor: pointer;
            user-select: none;
        }}
        .folder-icon {{
            margin-right: 5px;
        }}
        .nested {{
            display: none;
            padding-left: 20px;
        }}
        .nested.active {{
            display: block;
        }}
        .significant {{
            background-color: #27ae60;
            border-radius: 4px;
            font-weight: bold;
        }}
        .significant a {{
            color: white !important;
        }}
        .stats-table, .results-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 20px 0;
        }}
        .stats-table th, .stats-table td,
        .results-table th, .results-table td {{
            border: 1px solid #ddd;
            padding: 12px;
            text-align: left;
        }}
        .stats-table th, .results-table th {{
            background-color: #34495e;
            color: white;
        }}
        .stats-table tr:nth-child(even),
        .results-table tr:nth-child(even) {{
            background-color: #f2f2f2;
        }}
        .brain-img {{
            max-width: 100%;
            height: auto;
            margin: 20px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
        }}
        .plotly-plot {{
            margin: 20px 0;
        }}
        h2 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        h3 {{
            color: #34495e;
            margin-top: 30px;
            margin-bottom: 15px;
        }}
    </style>
</head>
<body>
    <div id="sidebar">
        <h1>📊 Connectivity Analysis Report</h1>
        <p style="font-size: 12px; color: #bdc3c7; margin-bottom: 20px;">
            Walking Intervention Study<br>
            Generated: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')}
        </p>
        {sidebar_html}
    </div>

    <div id="main-panel">
        <div id="welcome" class="analysis-content">
            <h2>Welcome to the Connectivity Analysis Report</h2>
            <p>This interactive report contains results from the longitudinal walking intervention connectivity analysis.</p>
            <p><strong>Total analyses: {n_total}</strong></p>
            <ul>
                <li>Local measures (fALFF, ReHo): {n_local}</li>
                <li>Seed-based connectivity: {n_seed}</li>
                <li>Within-network connectivity: {n_within}</li>
                <li>Between-network connectivity: {n_between}</li>
            </ul>
            <p style="margin-top: 20px;">
                <strong>Legend:</strong><br>
                <span style="background-color: #27ae60; color: white; padding: 5px 10px; border-radius: 4px; display: inline-block; margin-top: 5px;">
                    Significant Results (FDR q &lt; 0.05)
                </span>
            </p>
            <p style="margin-top: 20px;">Select an analysis from the sidebar to view detailed results.</p>
        </div>
        {"".join(all_content_html)}
    </div>

    <script>
        // Collapsible tree functionality
        var toggler = document.getElementsByClassName("collapsible");
        for (var i = 0; i < toggler.length; i++) {{
            toggler[i].addEventListener("click", function() {{
                this.querySelector(".nested")?.classList.toggle("active");
            }});
        }}

        // Analysis content switching
        var analysisLinks = document.querySelectorAll('a[data-analysis]');
        analysisLinks.forEach(function(link) {{
            link.addEventListener('click', function(e) {{
                e.preventDefault();
                var analysisId = this.getAttribute('data-analysis');

                // Hide all content
                var allContent = document.querySelectorAll('.analysis-content');
                allContent.forEach(function(content) {{
                    content.style.display = 'none';
                }});

                // Show selected content
                var selectedContent = document.getElementById('content_' + analysisId);
                if (selectedContent) {{
                    selectedContent.style.display = 'block';
                }}

                // Scroll to top
                window.scrollTo(0, 0);
            }});
        }});

        // Plotly rendering function
        function renderPlotly(divId, plotlyJson) {{
            var data = JSON.parse(plotlyJson);
            Plotly.newPlot(divId, data.data, data.layout);
        }}
    </script>
</body>
</html>"""

    # Write to file
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html_template)

    print(f"\n{'='*60}")
    print("HTML REPORT GENERATED")
    print(f"{'='*60}")
    print(f"Output file: {output_path}")
    print(f"File size: {output_path.stat().st_size / 1024:.1f} KB")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate interactive HTML report for connectivity analysis results"
    )
    parser.add_argument('--results-dir', required=True,
                        help='Results directory containing analysis subdirectories')
    parser.add_argument('--output', required=True,
                        help='Output HTML file path')

    args = parser.parse_args()

    return generate_html_report(args.results_dir, args.output)


if __name__ == '__main__':
    exit(main())
