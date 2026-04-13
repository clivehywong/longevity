#!/usr/bin/env python3
"""
Generate HTML report for DLPFC group-level analysis results.

Creates a self-contained HTML report with embedded base64 images including:
- Seed visualization images (ortho + glass brain views)
- Statistical results
- Brain maps (t-stat, thresholded)
- Cluster tables

Usage:
    python script/generate_dlpfc_report.py \
        --results-dir derivatives/connectivity-difumo256/group-level/seed_based \
        --seed-viz-dir atlases/seed_visualizations \
        --output derivatives/connectivity-difumo256/group-level/dlpfc_group_analysis_report.html

    # With lower threshold:
    python script/generate_dlpfc_report.py --p-threshold 0.01 --min-cluster-size 20
"""

import argparse
import base64
import json
from io import BytesIO
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats, ndimage
from nilearn import plotting, image, datasets

# Seed name mapping: directory name -> display name (matches visualization filenames)
SEED_MAPPING = {
    'dlpfc_l': 'DLPFC_L',
    'dlpfc_r': 'DLPFC_R',
    'dlpfc_bilateral': 'DLPFC_Bilateral'
}

# Seed descriptions
SEED_DESCRIPTIONS = {
    'DLPFC_L': 'Left Dorsolateral Prefrontal Cortex (BA 9/46) - 5 DiFuMo components, 97.5% left hemisphere',
    'DLPFC_R': 'Right Dorsolateral Prefrontal Cortex (BA 9/46) - 7 DiFuMo components, 95.1% right hemisphere',
    'DLPFC_Bilateral': 'Bilateral Dorsolateral Prefrontal Cortex - Union of DLPFC_L and DLPFC_R (12 components)'
}


def apply_threshold_and_extract_clusters(tstat_path, pval_path, p_threshold=0.01,
                                          min_cluster_size=50):
    """
    Apply threshold to t-stat map and extract clusters.

    Parameters
    ----------
    tstat_path : Path
        Path to t-statistic map
    pval_path : Path
        Path to p-value map
    p_threshold : float
        P-value threshold (default 0.01)
    min_cluster_size : int
        Minimum cluster size in voxels (default 50)

    Returns
    -------
    thresholded_img : Nifti1Image
        Thresholded t-stat map
    clusters_df : DataFrame
        Cluster information
    cluster_imgs : list of Nifti1Image
        Individual cluster images
    labeled_array : ndarray
        Labeled cluster array
    """
    # Load images
    tstat_img = image.load_img(str(tstat_path))
    pval_img = image.load_img(str(pval_path))

    tstat_data = tstat_img.get_fdata()
    pval_data = pval_img.get_fdata()

    # Load brain mask
    mask_img = datasets.load_mni152_brain_mask(resolution=2)
    mask_resampled = image.resample_to_img(mask_img, tstat_img, interpolation='nearest')
    mask_data = mask_resampled.get_fdata().astype(bool)

    # Apply threshold: p < threshold AND within brain mask AND p > 0 (to exclude fill values)
    sig_mask = (pval_data < p_threshold) & (pval_data > 0) & mask_data

    # Create thresholded t-stat map
    thresholded_data = np.zeros_like(tstat_data)
    thresholded_data[sig_mask] = tstat_data[sig_mask]

    # Label connected components (clusters)
    structure = ndimage.generate_binary_structure(3, 2)  # 18-connectivity
    labeled_array, n_clusters = ndimage.label(sig_mask, structure=structure)

    # Extract cluster information
    clusters = []
    cluster_imgs = []
    voxel_volume = np.prod(np.abs(np.diag(tstat_img.affine[:3, :3])))

    for cluster_id in range(1, n_clusters + 1):
        cluster_mask = labeled_array == cluster_id
        cluster_size = np.sum(cluster_mask)

        if cluster_size < min_cluster_size:
            # Remove small clusters from thresholded map
            thresholded_data[cluster_mask] = 0
            continue

        # Find peak voxel
        cluster_tstat = tstat_data.copy()
        cluster_tstat[~cluster_mask] = 0

        # Get peak (max absolute t-value)
        peak_idx = np.unravel_index(np.argmax(np.abs(cluster_tstat)), cluster_tstat.shape)
        peak_t = tstat_data[peak_idx]

        # Convert to MNI coordinates
        peak_mni = image.coord_transform(peak_idx[0], peak_idx[1], peak_idx[2],
                                          tstat_img.affine)

        # Determine direction
        direction = 'positive' if peak_t > 0 else 'negative'

        # Create individual cluster image
        cluster_data = np.zeros_like(tstat_data)
        cluster_data[cluster_mask] = tstat_data[cluster_mask]
        cluster_img = image.new_img_like(tstat_img, cluster_data)
        cluster_imgs.append(cluster_img)

        clusters.append({
            'cluster_id': len(clusters) + 1,
            'size_voxels': int(cluster_size),
            'size_mm3': int(cluster_size * voxel_volume),
            'peak_t': round(peak_t, 3),
            'peak_x': round(peak_mni[0], 1),
            'peak_y': round(peak_mni[1], 1),
            'peak_z': round(peak_mni[2], 1),
            'direction': direction
        })

    # Create thresholded image
    thresholded_img = image.new_img_like(tstat_img, thresholded_data)

    # Create DataFrame
    clusters_df = pd.DataFrame(clusters)

    return thresholded_img, clusters_df, cluster_imgs, labeled_array


def image_to_base64(img_path):
    """Convert image file to base64 string."""
    img_path = Path(img_path)
    if not img_path.exists():
        return None
    with open(img_path, 'rb') as f:
        img_base64 = base64.b64encode(f.read()).decode('utf-8')
    return f'data:image/png;base64,{img_base64}'


def nifti_to_base64_from_img(nifti_img, threshold=None, display_mode='ortho', colorbar=True):
    """
    Render NIfTI image object and return as base64 image.

    Parameters
    ----------
    nifti_img : Nifti1Image
        NIfTI image object
    threshold : float, optional
        Threshold for display
    display_mode : str
        Display mode: 'ortho', 'x', 'y', 'z', 'mosaic'
    colorbar : bool
        Whether to include colorbar

    Returns
    -------
    str
        Base64-encoded PNG image
    """
    try:
        fig = plt.figure(figsize=(12, 4))
        display = plotting.plot_stat_map(
            nifti_img,
            display_mode=display_mode,
            threshold=threshold,
            colorbar=colorbar,
            cmap='RdBu_r',
            symmetric_cbar=True,
            annotate=True,
            draw_cross=True,
            figure=fig
        )

        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='white')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        return f'data:image/png;base64,{img_base64}'

    except Exception as e:
        print(f"  Warning: Could not render image: {e}")
        return None


def render_cluster_plot(cluster_img, peak_coords, cluster_id):
    """
    Render individual cluster plot with cuts at peak coordinates.

    Parameters
    ----------
    cluster_img : Nifti1Image
        Individual cluster image
    peak_coords : tuple
        Peak MNI coordinates (x, y, z)
    cluster_id : int
        Cluster ID number

    Returns
    -------
    str
        Base64-encoded PNG image
    """
    try:
        fig = plt.figure(figsize=(10, 3))

        display = plotting.plot_stat_map(
            cluster_img,
            display_mode='ortho',
            cut_coords=peak_coords,
            threshold=0.1,
            colorbar=True,
            cmap='RdBu_r',
            symmetric_cbar=True,
            annotate=True,
            draw_cross=True,
            figure=fig,
            title=f'Cluster {cluster_id} (peak at {peak_coords})'
        )

        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='white')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        return f'data:image/png;base64,{img_base64}'

    except Exception as e:
        print(f"  Warning: Could not render cluster {cluster_id}: {e}")
        return None


def nifti_to_base64(nifti_path, threshold=None, display_mode='ortho', colorbar=True):
    """
    Render NIfTI file and return as base64 image.

    Parameters
    ----------
    nifti_path : str or Path
        Path to NIfTI file
    threshold : float, optional
        Threshold for display
    display_mode : str
        Display mode: 'ortho', 'x', 'y', 'z', 'mosaic'
    colorbar : bool
        Whether to include colorbar

    Returns
    -------
    str
        Base64-encoded PNG image
    """
    nifti_path = Path(nifti_path)
    if not nifti_path.exists():
        return None

    try:
        img = image.load_img(str(nifti_path))

        fig = plt.figure(figsize=(12, 4))
        display = plotting.plot_stat_map(
            img,
            display_mode=display_mode,
            threshold=threshold,
            colorbar=colorbar,
            cmap='RdBu_r',
            symmetric_cbar=True,
            annotate=True,
            draw_cross=True,
            figure=fig
        )

        buf = BytesIO()
        fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='white')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close(fig)

        return f'data:image/png;base64,{img_base64}'

    except Exception as e:
        print(f"  Warning: Could not render {nifti_path}: {e}")
        return None


def load_seed_data(results_dir, seed_viz_dir, p_threshold=0.01, min_cluster_size=50):
    """
    Load data for all DLPFC seeds.

    Parameters
    ----------
    results_dir : Path
        Directory containing seed analysis results
    seed_viz_dir : Path
        Directory containing seed visualization images
    p_threshold : float
        P-value threshold for significance
    min_cluster_size : int
        Minimum cluster size in voxels

    Returns
    -------
    list of dict
        List of seed data dictionaries
    """
    results_dir = Path(results_dir)
    seed_viz_dir = Path(seed_viz_dir)

    seed_sections = []

    for seed_dir_name, seed_display_name in SEED_MAPPING.items():
        seed_dir = results_dir / seed_dir_name

        if not seed_dir.exists():
            print(f"  Warning: Seed directory not found: {seed_dir}")
            continue

        print(f"  Loading {seed_display_name}...")

        # Load seed visualizations
        seed_ortho = seed_viz_dir / f'{seed_display_name}_ortho.png'
        seed_glass = seed_viz_dir / f'{seed_display_name}_glass.png'

        # Load analysis results
        tstat_map = seed_dir / 'interaction_tstat_map.nii.gz'
        pval_map = seed_dir / 'interaction_pval_map.nii.gz'
        tstat_ortho_png = seed_dir / 'interaction_tstat_ortho.png'
        model_info_file = seed_dir / 'model_info.json'

        # Load model info
        model_info = {}
        if model_info_file.exists():
            with open(model_info_file) as f:
                model_info = json.load(f)

        # Apply threshold and extract clusters on-the-fly
        clusters_df = pd.DataFrame()
        thresholded_img = None
        cluster_imgs = []
        n_clusters = 0

        if tstat_map.exists() and pval_map.exists():
            print(f"    Applying threshold (p < {p_threshold}, k >= {min_cluster_size})...")
            thresholded_img, clusters_df, cluster_imgs, labeled_array = apply_threshold_and_extract_clusters(
                tstat_map, pval_map,
                p_threshold=p_threshold,
                min_cluster_size=min_cluster_size
            )
            n_clusters = len(clusters_df)
            print(f"    Found {n_clusters} clusters")

        # Convert images to base64
        section_data = {
            'name': seed_display_name,
            'description': SEED_DESCRIPTIONS.get(seed_display_name, ''),
            'seed_ortho': image_to_base64(seed_ortho),
            'seed_glass': image_to_base64(seed_glass),
            'tstat_ortho': image_to_base64(tstat_ortho_png),
            'thresh_map_b64': None,
            'clusters_df': clusters_df,
            'cluster_imgs': cluster_imgs,
            'n_clusters': n_clusters,
            'model_info': model_info,
            'has_significant': n_clusters > 0,
            'p_threshold': p_threshold,
            'min_cluster_size': min_cluster_size
        }

        # Render thresholded map if we have clusters
        if thresholded_img is not None:
            print(f"    Rendering thresholded map...")
            # Use a small threshold to show all surviving voxels
            section_data['thresh_map_b64'] = nifti_to_base64_from_img(
                thresholded_img, threshold=0.1
            )

        # Render individual cluster plots
        if n_clusters > 0:
            print(f"    Rendering {n_clusters} individual cluster plots...")
            cluster_plots = []
            for i, (cluster_img, (_, row)) in enumerate(zip(cluster_imgs, clusters_df.iterrows())):
                peak_coords = (row['peak_x'], row['peak_y'], row['peak_z'])
                cluster_plot = render_cluster_plot(cluster_img, peak_coords, row['cluster_id'])
                cluster_plots.append(cluster_plot)
            section_data['cluster_plots'] = cluster_plots

        # If no pre-rendered t-stat image, generate one
        if section_data['tstat_ortho'] is None and tstat_map.exists():
            print(f"    Rendering t-stat map...")
            section_data['tstat_ortho'] = nifti_to_base64(tstat_map, threshold=2.0)

        seed_sections.append(section_data)

    return seed_sections


def generate_seed_section_html(seed_data):
    """Generate HTML for a single seed section."""
    name = seed_data['name']

    html = f'''
    <div class="seed-section" id="seed_{name.lower().replace(" ", "_")}">
        <h2>{name}</h2>
        <p class="seed-description">{seed_data['description']}</p>

        <!-- Seed Visualization -->
        <div class="seed-viz">
            <h3>🎯 Seed Definition</h3>
            <div class="image-row">
    '''

    if seed_data['seed_ortho']:
        html += f'''
                <div class="image-container">
                    <h4>Orthogonal View</h4>
                    <img src="{seed_data['seed_ortho']}" alt="{name} ortho view">
                </div>
        '''

    if seed_data['seed_glass']:
        html += f'''
                <div class="image-container">
                    <h4>Glass Brain</h4>
                    <img src="{seed_data['seed_glass']}" alt="{name} glass brain">
                </div>
        '''

    html += '''
            </div>
        </div>
    '''

    # Model Information
    model_info = seed_data['model_info']
    html += '''
        <div class="model-section">
            <h3>📊 Statistical Model</h3>
            <table class="stats-table">
                <tr><th>Parameter</th><th>Value</th></tr>
    '''

    if model_info:
        html += f'''
                <tr><td>Formula</td><td><code>{model_info.get('formula', 'N/A')}</code></td></tr>
                <tr><td>Observations</td><td>{model_info.get('n_observations', 'N/A')}</td></tr>
                <tr><td>Subjects</td><td>{model_info.get('n_subjects', 'N/A')}</td></tr>
                <tr><td>Brain Voxels</td><td>{model_info.get('n_voxels', 'N/A'):,}</td></tr>
                <tr><td>Covariates</td><td>{', '.join(model_info.get('included_covariates', ['None']))}</td></tr>
        '''

        # Show warnings if any
        warnings = model_info.get('covariate_warnings', [])
        if warnings:
            html += f'''
                <tr><td>Warnings</td><td style="color: #e67e22;">{'; '.join(warnings)}</td></tr>
            '''

    p_thresh = seed_data.get('p_threshold', 0.001)
    k_thresh = seed_data.get('min_cluster_size', 50)
    html += f'''
            </table>
            <p class="threshold-info">
                <strong>Threshold:</strong> p &lt; {p_thresh} uncorrected, k ≥ {k_thresh} voxels
            </p>
        </div>
    '''

    # Brain Maps
    html += '''
        <div class="brain-maps">
            <h3>🧠 Group × Time Interaction Maps</h3>
            <div class="image-row">
    '''

    if seed_data['tstat_ortho']:
        html += f'''
                <div class="image-container">
                    <h4>T-statistic Map</h4>
                    <img src="{seed_data['tstat_ortho']}" alt="T-stat map">
                </div>
        '''

    if seed_data['thresh_map_b64']:
        p_thresh = seed_data.get('p_threshold', 0.001)
        k_thresh = seed_data.get('min_cluster_size', 50)
        html += f'''
                <div class="image-container">
                    <h4>Thresholded Map (p &lt; {p_thresh}, k ≥ {k_thresh})</h4>
                    <img src="{seed_data['thresh_map_b64']}" alt="Thresholded map">
                </div>
        '''

    html += '''
            </div>
        </div>
    '''

    # Cluster Table
    html += '''
        <div class="cluster-section">
            <h3>📋 Significant Clusters</h3>
    '''

    if seed_data['n_clusters'] > 0:
        html += seed_data['clusters_df'].to_html(
            classes='results-table',
            index=False,
            float_format='%.2f'
        )

        # Individual Cluster Plots
        html += '''
            <h3 style="margin-top: 30px;">🔍 Individual Cluster Visualizations</h3>
            <p style="margin-bottom: 20px; color: #7f8c8d;">Each cluster shown at its peak coordinate location.</p>
        '''

        cluster_plots = seed_data.get('cluster_plots', [])
        clusters_df = seed_data['clusters_df']

        for i, (plot_b64, (_, row)) in enumerate(zip(cluster_plots, clusters_df.iterrows())):
            if plot_b64:
                cluster_info = f"Cluster {row['cluster_id']}: {row['size_voxels']} voxels, peak t={row['peak_t']:.2f} at ({row['peak_x']:.0f}, {row['peak_y']:.0f}, {row['peak_z']:.0f})"
                html += f'''
                <div class="cluster-plot-container">
                    <h4>Cluster {row['cluster_id']}</h4>
                    <table class="cluster-info-table">
                        <tr>
                            <td><strong>Size:</strong></td>
                            <td>{row['size_voxels']} voxels ({row['size_mm3']} mm³)</td>
                            <td><strong>Peak t-value:</strong></td>
                            <td>{row['peak_t']:.3f}</td>
                        </tr>
                        <tr>
                            <td><strong>Peak MNI:</strong></td>
                            <td>({row['peak_x']:.0f}, {row['peak_y']:.0f}, {row['peak_z']:.0f})</td>
                            <td><strong>Direction:</strong></td>
                            <td>{row['direction']}</td>
                        </tr>
                    </table>
                    <img src="{plot_b64}" alt="Cluster {row['cluster_id']} plot">
                </div>
                '''
    else:
        p_thresh = seed_data.get('p_threshold', 0.001)
        k_thresh = seed_data.get('min_cluster_size', 50)
        html += f'''
            <div class="no-clusters">
                <p>No significant clusters found at p &lt; {p_thresh} uncorrected, k ≥ {k_thresh} voxels.</p>
                <p class="interpretation">This indicates no voxels showed a statistically significant
                Group × Time interaction effect at this threshold for seed-based connectivity
                with the {seed_data['name']}.</p>
            </div>
        '''

    html += '''
        </div>
    </div>
    <hr class="section-divider">
    '''

    return html


def generate_html_template(seed_sections, p_threshold=0.01, min_cluster_size=50):
    """Generate the complete HTML document."""
    timestamp = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M')

    # Generate content for each seed
    all_seed_html = ''
    nav_links = ''

    for i, seed_data in enumerate(seed_sections):
        all_seed_html += generate_seed_section_html(seed_data)

        # Navigation link
        anchor_id = f"seed_{seed_data['name'].lower().replace(' ', '_')}"
        sig_class = 'nav-significant' if seed_data['has_significant'] else ''
        nav_links += f'''
            <li><a href="#{anchor_id}" class="{sig_class}">{seed_data['name']}</a></li>
        '''

    # Summary statistics
    n_seeds = len(seed_sections)
    n_significant = sum(1 for s in seed_sections if s['has_significant'])
    total_clusters = sum(s['n_clusters'] for s in seed_sections)

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>DLPFC Group-Level Analysis Report</title>
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        header {{
            background: linear-gradient(135deg, #2c3e50, #3498db);
            color: white;
            padding: 30px 40px;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }}
        header h1 {{
            font-size: 28px;
            margin-bottom: 10px;
        }}
        header p {{
            font-size: 14px;
            opacity: 0.9;
        }}
        nav {{
            background-color: #34495e;
            padding: 15px 40px;
            position: sticky;
            top: 0;
            z-index: 99;
        }}
        nav ul {{
            list-style: none;
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
        }}
        nav a {{
            color: #ecf0f1;
            text-decoration: none;
            padding: 8px 15px;
            border-radius: 4px;
            transition: background-color 0.2s;
        }}
        nav a:hover {{
            background-color: #2c3e50;
        }}
        nav a.nav-significant {{
            background-color: #27ae60;
            font-weight: bold;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            padding: 30px 40px;
        }}
        .summary-section {{
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}
        .summary-section h2 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 20px;
        }}
        .summary-card {{
            background: linear-gradient(135deg, #f8f9fa, #e9ecef);
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }}
        .summary-card .number {{
            font-size: 36px;
            font-weight: bold;
            color: #2c3e50;
        }}
        .summary-card .label {{
            font-size: 14px;
            color: #7f8c8d;
            margin-top: 5px;
        }}
        .seed-section {{
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            margin-bottom: 30px;
        }}
        .seed-section h2 {{
            color: #2c3e50;
            border-bottom: 3px solid #3498db;
            padding-bottom: 10px;
            margin-bottom: 15px;
        }}
        .seed-description {{
            color: #7f8c8d;
            font-style: italic;
            margin-bottom: 20px;
        }}
        .seed-viz {{
            background-color: #f8f9fa;
            padding: 20px;
            margin: 20px 0;
            border-radius: 8px;
            border-left: 4px solid #3498db;
        }}
        .seed-viz h3 {{
            color: #2c3e50;
            margin-bottom: 15px;
        }}
        .model-section {{
            margin: 20px 0;
        }}
        .model-section h3 {{
            color: #2c3e50;
            margin-bottom: 15px;
        }}
        .brain-maps {{
            margin: 20px 0;
        }}
        .brain-maps h3 {{
            color: #2c3e50;
            margin-bottom: 15px;
        }}
        .cluster-section {{
            margin: 20px 0;
        }}
        .cluster-section h3 {{
            color: #2c3e50;
            margin-bottom: 15px;
        }}
        .image-row {{
            display: flex;
            justify-content: space-around;
            flex-wrap: wrap;
            gap: 20px;
        }}
        .image-container {{
            flex: 1;
            min-width: 400px;
            max-width: 600px;
            text-align: center;
        }}
        .image-container h4 {{
            color: #34495e;
            margin-bottom: 10px;
            font-size: 14px;
        }}
        .image-container img {{
            max-width: 100%;
            height: auto;
            border: 1px solid #ddd;
            border-radius: 4px;
            background-color: white;
        }}
        .stats-table, .results-table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
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
        .stats-table code {{
            background-color: #ecf0f1;
            padding: 2px 6px;
            border-radius: 3px;
            font-size: 13px;
        }}
        .threshold-info {{
            margin-top: 15px;
            padding: 10px 15px;
            background-color: #e8f4f8;
            border-radius: 4px;
            font-size: 14px;
        }}
        .no-clusters {{
            background-color: #f8f9fa;
            padding: 20px;
            border-radius: 4px;
            border: 1px dashed #bdc3c7;
            text-align: center;
        }}
        .no-clusters p {{
            margin: 10px 0;
        }}
        .no-clusters .interpretation {{
            font-size: 14px;
            color: #7f8c8d;
        }}
        .cluster-plot-container {{
            background-color: #f8f9fa;
            padding: 20px;
            margin: 20px 0;
            border-radius: 8px;
            border-left: 4px solid #e67e22;
        }}
        .cluster-plot-container h4 {{
            color: #2c3e50;
            margin-bottom: 10px;
        }}
        .cluster-info-table {{
            width: 100%;
            margin: 10px 0 15px 0;
            border-collapse: collapse;
        }}
        .cluster-info-table td {{
            padding: 5px 10px;
            font-size: 14px;
        }}
        .cluster-info-table strong {{
            color: #34495e;
        }}
        .cluster-plot-container img {{
            width: 100%;
            max-width: 900px;
            height: auto;
            border: 1px solid #ddd;
            border-radius: 4px;
            background-color: white;
            display: block;
            margin: 0 auto;
        }}
        .section-divider {{
            border: none;
            border-top: 2px dashed #bdc3c7;
            margin: 40px 0;
        }}
        footer {{
            background-color: #2c3e50;
            color: #ecf0f1;
            padding: 20px 40px;
            text-align: center;
            font-size: 14px;
        }}
        footer a {{
            color: #3498db;
        }}
        h3 {{
            margin-top: 25px;
        }}
        @media (max-width: 768px) {{
            .image-container {{
                min-width: 100%;
            }}
            header, .container {{
                padding: 20px;
            }}
        }}
    </style>
</head>
<body>
    <header>
        <h1>🧠 DLPFC Group-Level Analysis Report</h1>
        <p>Walking Intervention Longitudinal Study | Generated: {timestamp}</p>
    </header>

    <nav>
        <ul>
            <li><a href="#summary">Summary</a></li>
            {nav_links}
        </ul>
    </nav>

    <div class="container">
        <div class="summary-section" id="summary">
            <h2>📈 Analysis Summary</h2>
            <p>This report presents group-level seed-based connectivity analysis results for
            the Dorsolateral Prefrontal Cortex (DLPFC) regions, examining Group × Time
            interaction effects in the walking intervention study.</p>

            <div class="summary-grid">
                <div class="summary-card">
                    <div class="number">{n_seeds}</div>
                    <div class="label">DLPFC Seeds Analyzed</div>
                </div>
                <div class="summary-card">
                    <div class="number">24</div>
                    <div class="label">Subjects</div>
                </div>
                <div class="summary-card">
                    <div class="number">48</div>
                    <div class="label">Total Sessions</div>
                </div>
                <div class="summary-card">
                    <div class="number">{total_clusters}</div>
                    <div class="label">Significant Clusters</div>
                </div>
            </div>

            <h3 style="margin-top: 30px;">Statistical Approach</h3>
            <ul style="margin: 15px 0 0 25px;">
                <li><strong>Model:</strong> <code>Connectivity ~ Group × Time + MeanFD + (1|Subject)</code></li>
                <li><strong>Threshold:</strong> p &lt; {p_threshold} uncorrected, cluster size ≥ {min_cluster_size} voxels</li>
                <li><strong>Brain Mask:</strong> MNI152 2mm (235,375 voxels)</li>
                <li><strong>Atlas:</strong> DiFuMo 256 probabilistic atlas for seed definition</li>
            </ul>

            <h3 style="margin-top: 25px;">Seeds Analyzed</h3>
            <table class="stats-table">
                <tr>
                    <th>Seed</th>
                    <th>Description</th>
                    <th>Clusters Found</th>
                </tr>
'''

    for seed_data in seed_sections:
        status = f'<span style="color: #27ae60; font-weight: bold;">{seed_data["n_clusters"]} clusters</span>' if seed_data['n_clusters'] > 0 else '0 clusters'
        html += f'''
                <tr>
                    <td>{seed_data['name']}</td>
                    <td>{seed_data['description']}</td>
                    <td>{status}</td>
                </tr>
'''

    html += f'''
            </table>
        </div>

        {all_seed_html}
    </div>

    <footer>
        <p>Report generated by <code>generate_dlpfc_report.py</code></p>
        <p>Walking Intervention Longitudinal Neuroimaging Study | Hong Kong Baptist University</p>
    </footer>
</body>
</html>
'''

    return html


def generate_report(results_dir, seed_viz_dir, output_file, p_threshold=0.01,
                    min_cluster_size=50):
    """
    Generate HTML report for DLPFC analyses.

    Parameters
    ----------
    results_dir : str
        Directory containing DLPFC analysis subdirectories
    seed_viz_dir : str
        Directory containing seed visualization images
    output_file : str
        Output HTML file path
    p_threshold : float
        P-value threshold for significance (default 0.01)
    min_cluster_size : int
        Minimum cluster size in voxels (default 20)
    """
    print("=" * 60)
    print("GENERATING DLPFC GROUP-LEVEL ANALYSIS REPORT")
    print("=" * 60)

    results_dir = Path(results_dir)
    seed_viz_dir = Path(seed_viz_dir)
    output_file = Path(output_file)

    print(f"\nResults directory: {results_dir}")
    print(f"Seed visualization directory: {seed_viz_dir}")
    print(f"Output file: {output_file}")
    print(f"P-value threshold: {p_threshold}")
    print(f"Minimum cluster size: {min_cluster_size} voxels")

    # Load data for all seeds
    print("\nLoading seed data...")
    seed_sections = load_seed_data(results_dir, seed_viz_dir,
                                   p_threshold=p_threshold,
                                   min_cluster_size=min_cluster_size)

    if not seed_sections:
        print("\nERROR: No seed data found!")
        return 1

    print(f"\nLoaded {len(seed_sections)} seeds")

    # Generate HTML
    print("\nGenerating HTML...")
    html = generate_html_template(seed_sections, p_threshold=p_threshold,
                                  min_cluster_size=min_cluster_size)

    # Write to file
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html)

    file_size_kb = output_file.stat().st_size / 1024
    file_size_mb = file_size_kb / 1024

    print(f"\n{'='*60}")
    print("REPORT GENERATED SUCCESSFULLY")
    print(f"{'='*60}")
    print(f"Output file: {output_file}")
    print(f"File size: {file_size_kb:.1f} KB ({file_size_mb:.2f} MB)")
    print(f"\nOpen in browser: file://{output_file.absolute()}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Generate HTML report for DLPFC group-level analysis results"
    )
    parser.add_argument(
        '--results-dir',
        default='derivatives/connectivity-difumo256/group-level/seed_based',
        help='Directory containing DLPFC analysis subdirectories'
    )
    parser.add_argument(
        '--seed-viz-dir',
        default='atlases/seed_visualizations',
        help='Directory containing seed visualization images'
    )
    parser.add_argument(
        '--output',
        default='derivatives/connectivity-difumo256/group-level/dlpfc_group_analysis_report.html',
        help='Output HTML file path'
    )
    parser.add_argument(
        '--p-threshold',
        type=float,
        default=0.01,
        help='P-value threshold for significance (default: 0.01)'
    )
    parser.add_argument(
        '--min-cluster-size',
        type=int,
        default=50,
        help='Minimum cluster size in voxels (default: 50)'
    )

    args = parser.parse_args()

    return generate_report(
        args.results_dir,
        args.seed_viz_dir,
        args.output,
        p_threshold=args.p_threshold,
        min_cluster_size=args.min_cluster_size
    )


if __name__ == '__main__':
    exit(main())
