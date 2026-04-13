#!/usr/bin/env python3
"""
Quality Assurance - Visual Check Image Generator

Generates montage images showing mid-slices for:
- T1w/T2w structural images (7 axial + 7 sagittal slices)
- Functional BOLD images (timepoint sampling + quality maps)
- DWI images (b0 and high-b volumes)
- Field maps (AP/PA comparison)

This module can be used both as:
1. A CLI tool for batch generation
2. A library for on-demand generation in the NeuConn app

Usage (CLI):
    python -m utils.qa_image_generator --bids-dir /path/to/bids --output qa_images/

Usage (Library):
    from utils.qa_image_generator import (
        generate_anat_montage,
        generate_func_timepoints,
        generate_func_quality,
        generate_dwi_montage,
        generate_fmap_comparison
    )

Ported from: script/qa_check_images.py
"""

import argparse
import base64
import io
import os
from pathlib import Path
from typing import Optional, Dict, List, Any, Tuple

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np

try:
    import pandas as pd
    HAS_PANDAS = True
except ImportError:
    HAS_PANDAS = False


def load_nifti_data(nifti_path: Path) -> Optional[Tuple[np.ndarray, Tuple]]:
    """
    Load and prepare NIfTI data for visualization.

    Args:
        nifti_path: Path to NIfTI file

    Returns:
        Tuple of (data array, original shape) or None on error
    """
    if not nifti_path.exists():
        return None

    try:
        img = nib.load(str(nifti_path))
        data = img.get_fdata()
        original_shape = data.shape
        return data, original_shape
    except Exception as e:
        print(f"Error loading {nifti_path}: {e}")
        return None


def generate_anat_montage(nifti_path: Path) -> Optional[plt.Figure]:
    """
    Generate anatomical montage (7 axial + 7 sagittal slices).

    Works for T1w, T2w, and other 3D structural images.

    Args:
        nifti_path: Path to anatomical NIfTI file

    Returns:
        matplotlib Figure or None on error
    """
    result = load_nifti_data(nifti_path)
    if result is None:
        return None

    data, original_shape = result

    # Handle 4D (take mean)
    if len(data.shape) == 4:
        data = data.mean(axis=-1)
    elif len(data.shape) < 3:
        return None

    # Ensure 3D
    data = np.squeeze(data)
    if len(data.shape) != 3:
        return None

    # Create figure with 7 axial + 7 sagittal slices
    fig, axes = plt.subplots(2, 7, figsize=(21, 6))

    # 7 axial slices (evenly spaced through z-axis, middle 50%)
    z_indices = np.linspace(data.shape[2] // 4, 3 * data.shape[2] // 4, 7, dtype=int)
    for i, z_idx in enumerate(z_indices):
        axes[0, i].imshow(data[:, :, z_idx].T, cmap='gray', origin='lower')
        axes[0, i].set_title(f'Axial {z_idx}', fontsize=8)
        axes[0, i].axis('off')

    # 7 sagittal slices (evenly spaced through x-axis, middle 50%)
    x_indices = np.linspace(data.shape[0] // 4, 3 * data.shape[0] // 4, 7, dtype=int)
    for i, x_idx in enumerate(x_indices):
        axes[1, i].imshow(data[x_idx, :, :].T, cmap='gray', origin='lower')
        axes[1, i].set_title(f'Sagittal {x_idx}', fontsize=8)
        axes[1, i].axis('off')

    fig.suptitle(f'{nifti_path.name} - Shape: {data.shape}',
                 fontsize=12, fontweight='bold')

    plt.tight_layout()
    return fig


# Alias for backwards compatibility
generate_t1w_montage = generate_anat_montage


def generate_func_timepoints(nifti_path: Path) -> Optional[plt.Figure]:
    """
    Generate functional timepoint montage (3 timepoints x 3 views).

    Shows volumes at 10%, 50%, and 90% of timeseries.

    Args:
        nifti_path: Path to BOLD NIfTI file

    Returns:
        matplotlib Figure or None on error
    """
    result = load_nifti_data(nifti_path)
    if result is None:
        return None

    data, original_shape = result

    if len(data.shape) != 4:
        return None

    n_vols = data.shape[3]

    # Select 3 volumes: early (10%), middle (50%), late (90%)
    vol_indices = [
        int(n_vols * 0.1),
        int(n_vols * 0.5),
        int(n_vols * 0.9)
    ]

    # Create figure: 3 rows (timepoints) x 3 columns (views)
    fig, axes = plt.subplots(3, 3, figsize=(12, 12))

    # Get mid-slice indices
    mid_x = data.shape[0] // 2
    mid_y = data.shape[1] // 2
    mid_z = data.shape[2] // 2

    for row, vol_idx in enumerate(vol_indices):
        vol_data = data[:, :, :, vol_idx]

        # Axial (mid z)
        axes[row, 0].imshow(vol_data[:, :, mid_z].T, cmap='gray', origin='lower')
        axes[row, 0].set_title(f'Vol {vol_idx} - Axial (z={mid_z})', fontsize=9)
        axes[row, 0].axis('off')

        # Coronal (mid y)
        axes[row, 1].imshow(vol_data[:, mid_y, :].T, cmap='gray', origin='lower')
        axes[row, 1].set_title(f'Vol {vol_idx} - Coronal (y={mid_y})', fontsize=9)
        axes[row, 1].axis('off')

        # Sagittal (mid x)
        axes[row, 2].imshow(vol_data[mid_x, :, :].T, cmap='gray', origin='lower')
        axes[row, 2].set_title(f'Vol {vol_idx} - Sagittal (x={mid_x})', fontsize=9)
        axes[row, 2].axis('off')

    fig.suptitle(f'{nifti_path.name} - Shape: {data.shape[:3]} x {n_vols} vols',
                 fontsize=12, fontweight='bold')

    plt.tight_layout()
    return fig


def generate_func_quality(nifti_path: Path) -> Optional[plt.Figure]:
    """
    Generate functional quality maps (Mean, Std, tSNR).

    Computes temporal statistics across the timeseries.

    Args:
        nifti_path: Path to BOLD NIfTI file

    Returns:
        matplotlib Figure or None on error
    """
    result = load_nifti_data(nifti_path)
    if result is None:
        return None

    data, original_shape = result

    if len(data.shape) != 4:
        return None

    # Compute quality metrics
    mean_img = np.mean(data, axis=3)
    std_img = np.std(data, axis=3)
    with np.errstate(divide='ignore', invalid='ignore'):
        tsnr_img = np.divide(mean_img, std_img, where=std_img > 0)
        tsnr_img = np.nan_to_num(tsnr_img, nan=0, posinf=0, neginf=0)

    # Create figure: 3 rows (metrics) x 3 columns (views)
    fig, axes = plt.subplots(3, 3, figsize=(12, 12))

    # Get mid-slice indices
    mid_x = mean_img.shape[0] // 2
    mid_y = mean_img.shape[1] // 2
    mid_z = mean_img.shape[2] // 2

    # Mean image (3 views)
    axes[0, 0].imshow(mean_img[:, :, mid_z].T, cmap='gray', origin='lower')
    axes[0, 0].set_title('Mean - Axial', fontsize=9)
    axes[0, 0].axis('off')

    axes[0, 1].imshow(mean_img[:, mid_y, :].T, cmap='gray', origin='lower')
    axes[0, 1].set_title('Mean - Coronal', fontsize=9)
    axes[0, 1].axis('off')

    axes[0, 2].imshow(mean_img[mid_x, :, :].T, cmap='gray', origin='lower')
    axes[0, 2].set_title('Mean - Sagittal', fontsize=9)
    axes[0, 2].axis('off')

    # Std image (3 views) - hot colormap highlights variability
    axes[1, 0].imshow(std_img[:, :, mid_z].T, cmap='hot', origin='lower')
    axes[1, 0].set_title('Std - Axial', fontsize=9)
    axes[1, 0].axis('off')

    axes[1, 1].imshow(std_img[:, mid_y, :].T, cmap='hot', origin='lower')
    axes[1, 1].set_title('Std - Coronal', fontsize=9)
    axes[1, 1].axis('off')

    axes[1, 2].imshow(std_img[mid_x, :, :].T, cmap='hot', origin='lower')
    axes[1, 2].set_title('Std - Sagittal', fontsize=9)
    axes[1, 2].axis('off')

    # tSNR image (3 views) - viridis with fixed scale 0-100
    axes[2, 0].imshow(tsnr_img[:, :, mid_z].T, cmap='viridis', origin='lower', vmin=0, vmax=100)
    axes[2, 0].set_title('tSNR - Axial', fontsize=9)
    axes[2, 0].axis('off')

    axes[2, 1].imshow(tsnr_img[:, mid_y, :].T, cmap='viridis', origin='lower', vmin=0, vmax=100)
    axes[2, 1].set_title('tSNR - Coronal', fontsize=9)
    axes[2, 1].axis('off')

    axes[2, 2].imshow(tsnr_img[mid_x, :, :].T, cmap='viridis', origin='lower', vmin=0, vmax=100)
    axes[2, 2].set_title('tSNR - Sagittal', fontsize=9)
    axes[2, 2].axis('off')

    fig.suptitle(f'{nifti_path.name} - Quality Maps', fontsize=12, fontweight='bold')

    plt.tight_layout()
    return fig


def generate_dwi_montage(nifti_path: Path) -> Optional[plt.Figure]:
    """
    Generate DWI montage showing b0 and high-b volumes.

    Shows first (b0), middle, and last volumes.

    Args:
        nifti_path: Path to DWI NIfTI file

    Returns:
        matplotlib Figure or None on error
    """
    result = load_nifti_data(nifti_path)
    if result is None:
        return None

    data, original_shape = result

    if len(data.shape) != 4:
        return None

    n_vols = data.shape[3]

    # Assume first volume is b0, show first, middle, last volumes
    volumes_to_show = [0, n_vols // 2, n_vols - 1]

    fig, axes = plt.subplots(3, 3, figsize=(12, 12))

    for row, vol_idx in enumerate(volumes_to_show):
        vol_data = data[:, :, :, vol_idx]

        # Get mid-slice indices
        mid_x = vol_data.shape[0] // 2
        mid_y = vol_data.shape[1] // 2
        mid_z = vol_data.shape[2] // 2

        axes[row, 0].imshow(vol_data[:, :, mid_z].T, cmap='gray', origin='lower')
        axes[row, 0].set_title(f'Axial (vol={vol_idx})', fontsize=8)
        axes[row, 0].axis('off')

        axes[row, 1].imshow(vol_data[:, mid_y, :].T, cmap='gray', origin='lower')
        axes[row, 1].set_title(f'Coronal (vol={vol_idx})', fontsize=8)
        axes[row, 1].axis('off')

        axes[row, 2].imshow(vol_data[mid_x, :, :].T, cmap='gray', origin='lower')
        axes[row, 2].set_title(f'Sagittal (vol={vol_idx})', fontsize=8)
        axes[row, 2].axis('off')

    fig.suptitle(f'{nifti_path.name} - DWI Volumes ({n_vols} total)',
                 fontsize=12, fontweight='bold')

    plt.tight_layout()
    return fig


def generate_fmap_montage(nifti_path: Path, pa_path: Optional[Path] = None) -> Optional[plt.Figure]:
    """
    Generate field map montage (AP alone or AP/PA comparison).

    Args:
        nifti_path: Path to AP (or single) field map NIfTI file
        pa_path: Optional path to PA field map for comparison

    Returns:
        matplotlib Figure or None on error
    """
    result = load_nifti_data(nifti_path)
    if result is None:
        return None

    data_ap, _ = result

    if len(data_ap.shape) == 4:
        data_ap = data_ap.mean(axis=-1)

    # Get mid-slice indices
    mid_x = data_ap.shape[0] // 2
    mid_y = data_ap.shape[1] // 2
    mid_z = data_ap.shape[2] // 2

    if pa_path and pa_path.exists():
        # Side-by-side AP and PA
        result_pa = load_nifti_data(pa_path)
        if result_pa is None:
            return None

        data_pa, _ = result_pa
        if len(data_pa.shape) == 4:
            data_pa = data_pa.mean(axis=-1)

        fig, axes = plt.subplots(2, 3, figsize=(12, 8))

        # AP views
        axes[0, 0].imshow(data_ap[:, :, mid_z].T, cmap='gray', origin='lower')
        axes[0, 0].set_title('AP - Axial', fontsize=9)
        axes[0, 0].axis('off')

        axes[0, 1].imshow(data_ap[:, mid_y, :].T, cmap='gray', origin='lower')
        axes[0, 1].set_title('AP - Coronal', fontsize=9)
        axes[0, 1].axis('off')

        axes[0, 2].imshow(data_ap[mid_x, :, :].T, cmap='gray', origin='lower')
        axes[0, 2].set_title('AP - Sagittal', fontsize=9)
        axes[0, 2].axis('off')

        # PA views
        axes[1, 0].imshow(data_pa[:, :, mid_z].T, cmap='gray', origin='lower')
        axes[1, 0].set_title('PA - Axial', fontsize=9)
        axes[1, 0].axis('off')

        axes[1, 1].imshow(data_pa[:, mid_y, :].T, cmap='gray', origin='lower')
        axes[1, 1].set_title('PA - Coronal', fontsize=9)
        axes[1, 1].axis('off')

        axes[1, 2].imshow(data_pa[mid_x, :, :].T, cmap='gray', origin='lower')
        axes[1, 2].set_title('PA - Sagittal', fontsize=9)
        axes[1, 2].axis('off')

        fig.suptitle(f'{nifti_path.name} (AP) vs {pa_path.name} (PA)',
                     fontsize=12, fontweight='bold')
    else:
        # Just AP/single fmap
        fig, axes = plt.subplots(1, 3, figsize=(12, 4))

        axes[0].imshow(data_ap[:, :, mid_z].T, cmap='gray', origin='lower')
        axes[0].set_title('Axial', fontsize=9)
        axes[0].axis('off')

        axes[1].imshow(data_ap[:, mid_y, :].T, cmap='gray', origin='lower')
        axes[1].set_title('Coronal', fontsize=9)
        axes[1].axis('off')

        axes[2].imshow(data_ap[mid_x, :, :].T, cmap='gray', origin='lower')
        axes[2].set_title('Sagittal', fontsize=9)
        axes[2].axis('off')

        fig.suptitle(f'{nifti_path.name}', fontsize=12, fontweight='bold')

    plt.tight_layout()
    return fig


def fig_to_base64(fig: plt.Figure) -> str:
    """Convert matplotlib figure to base64 encoded PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight', facecolor='white')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    return img_base64


def save_figure(fig: plt.Figure, output_path: Path, dpi: int = 100):
    """Save figure to file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=dpi, bbox_inches='tight', facecolor='white')


# ============================================================================
# CLI Functions (for standalone usage)
# ============================================================================

def scan_and_generate_all(
    bids_dir: Path,
    output_dir: Path,
    subjects: Optional[List[str]] = None,
    sessions: Optional[List[str]] = None,
    generate_html: bool = True,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    Scan BIDS directory and generate all QC images.

    Args:
        bids_dir: Path to BIDS directory
        output_dir: Output directory for images and report
        subjects: List of subjects to process (None = all)
        sessions: List of sessions to process (None = all)
        generate_html: Whether to generate HTML report
        verbose: Print progress messages

    Returns:
        Dict with processing results
    """
    results = {'t1w': {}, 'functional': {}}

    # Get subjects
    if subjects is None:
        subjects = sorted([d.name for d in bids_dir.iterdir()
                          if d.is_dir() and d.name.startswith('sub-')])

    # Get sessions
    if sessions is None:
        sessions = ['ses-01', 'ses-02']

    if verbose:
        print("=" * 60)
        print("QUALITY ASSURANCE - IMAGE GENERATION")
        print("=" * 60)
        print(f"BIDS directory: {bids_dir}")
        print(f"Output directory: {output_dir}")
        print(f"Subjects: {len(subjects)}")
        print(f"Sessions: {sessions}")

    output_dir.mkdir(parents=True, exist_ok=True)

    for subject in subjects:
        if verbose:
            print(f"\nProcessing {subject}...")

        if subject not in results['t1w']:
            results['t1w'][subject] = {}
        if subject not in results['functional']:
            results['functional'][subject] = {}

        for session in sessions:
            subject_dir = bids_dir / subject / session

            if not subject_dir.exists():
                continue

            # Process T1w files
            anat_dir = subject_dir / 'anat'
            t1w_files = sorted(anat_dir.glob(f'{subject}_{session}_run-*_T1w.nii.gz')) if anat_dir.exists() else []

            session_t1w = []
            for t1w_file in t1w_files:
                run = t1w_file.name.split('_')[2]  # Extract run-XX
                fig = generate_anat_montage(t1w_file)

                if fig:
                    # Save PNG
                    output_file = output_dir / 'structural' / f'{subject}_{session}_{run}_T1w.png'
                    save_figure(fig, output_file)

                    session_t1w.append({
                        'shape': tuple(nib.load(str(t1w_file)).shape[:3]),
                        'file': str(t1w_file),
                        'run': run,
                        'img_base64': fig_to_base64(fig),
                        'type': 'anat'
                    })
                    plt.close(fig)

            results['t1w'][subject][session] = session_t1w

            # Process functional files
            func_dir = subject_dir / 'func'
            func_file = func_dir / f'{subject}_{session}_task-rest_bold.nii.gz' if func_dir.exists() else None

            if func_file and func_file.exists():
                fig = generate_func_timepoints(func_file)

                if fig:
                    # Save PNG
                    output_file = output_dir / 'functional' / f'{subject}_{session}_func.png'
                    save_figure(fig, output_file)

                    img = nib.load(str(func_file))
                    results['functional'][subject][session] = {
                        'shape': img.shape[:3],
                        'n_volumes': img.shape[3] if len(img.shape) == 4 else 1,
                        'file': str(func_file),
                        'file_size_mb': func_file.stat().st_size / (1024**2),
                        'img_base64': fig_to_base64(fig),
                        'type': 'func'
                    }
                    plt.close(fig)
            else:
                results['functional'][subject][session] = None

    # Generate HTML report if requested
    if generate_html:
        create_html_report(results, output_dir)

    return results


def create_html_report(results: Dict[str, Any], output_dir: Path):
    """Create HTML report with embedded base64 images."""

    # Build summary table data
    summary_data = []
    all_subjects = sorted(set(list(results['t1w'].keys()) + list(results['functional'].keys())))

    for subject in all_subjects:
        row = {'subject': subject}

        # Check ses-01
        for scan_type in ['ses01_run01_T1w', 'ses01_run02_T1w', 'ses01_rest']:
            row[scan_type] = 'X'

        if subject in results['t1w'] and 'ses-01' in results['t1w'][subject]:
            t1w_list = results['t1w'][subject]['ses-01']
            if t1w_list and isinstance(t1w_list, list):
                runs = [info.get('run', '') for info in t1w_list]
                if 'run-01' in runs:
                    row['ses01_run01_T1w'] = 'OK'
                if 'run-02' in runs:
                    row['ses01_run02_T1w'] = 'OK'

        if subject in results['functional'] and 'ses-01' in results['functional'][subject]:
            if results['functional'][subject]['ses-01']:
                row['ses01_rest'] = 'OK'

        # Check ses-02
        for scan_type in ['ses02_run01_T1w', 'ses02_run02_T1w', 'ses02_rest']:
            row[scan_type] = 'X'

        if subject in results['t1w'] and 'ses-02' in results['t1w'][subject]:
            t1w_list = results['t1w'][subject]['ses-02']
            if t1w_list and isinstance(t1w_list, list):
                runs = [info.get('run', '') for info in t1w_list]
                if 'run-01' in runs:
                    row['ses02_run01_T1w'] = 'OK'
                if 'run-02' in runs:
                    row['ses02_run02_T1w'] = 'OK'

        if subject in results['functional'] and 'ses-02' in results['functional'][subject]:
            if results['functional'][subject]['ses-02']:
                row['ses02_rest'] = 'OK'

        summary_data.append(row)

    # Collect all images
    all_images = []

    for subject in sorted(results['t1w'].keys()):
        for session in sorted(results['t1w'][subject].keys()):
            t1w_list = results['t1w'][subject][session]
            if t1w_list and isinstance(t1w_list, list):
                for info in t1w_list:
                    all_images.append({
                        'subject': subject,
                        'session': session,
                        'type': 'anat',
                        'run': info.get('run', 'run-01'),
                        'shape': info['shape'],
                        'img_base64': info.get('img_base64', ''),
                        'file': info['file']
                    })

            # Add functional
            if subject in results['functional'] and session in results['functional'][subject]:
                if results['functional'][subject][session]:
                    info = results['functional'][subject][session]
                    all_images.append({
                        'subject': subject,
                        'session': session,
                        'type': 'func',
                        'run': 'task-rest',
                        'shape': info['shape'],
                        'n_volumes': info['n_volumes'],
                        'file_size_mb': info['file_size_mb'],
                        'img_base64': info.get('img_base64', ''),
                        'file': info['file']
                    })

    all_images.sort(key=lambda x: (x['subject'], x['session'], x['type'], x['run']))

    # Calculate summary stats
    n_subjects = len(set(img['subject'] for img in all_images))
    n_anat = sum(1 for img in all_images if img['type'] == 'anat')
    n_func = sum(1 for img in all_images if img['type'] == 'func')
    total_scans = len(all_images)

    # Generate table rows
    table_rows = ""
    for row in summary_data:
        ok_mark = lambda v: '<span style="color: green;">OK</span>' if v == 'OK' else '<span style="color: red;">X</span>'
        table_rows += f"""
                    <tr>
                        <td><strong>{row['subject']}</strong></td>
                        <td>{ok_mark(row['ses01_run01_T1w'])}</td>
                        <td>{ok_mark(row['ses01_run02_T1w'])}</td>
                        <td>{ok_mark(row['ses01_rest'])}</td>
                        <td>{ok_mark(row['ses02_run01_T1w'])}</td>
                        <td>{ok_mark(row['ses02_run02_T1w'])}</td>
                        <td>{ok_mark(row['ses02_rest'])}</td>
                    </tr>"""

    # Generate HTML
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>BIDS QA Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
        }}
        .header h1 {{ margin: 0 0 10px 0; }}
        .summary {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 30px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            margin-top: 15px;
        }}
        .summary-card {{
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            border-left: 4px solid #667eea;
        }}
        .summary-card h3 {{
            margin: 0 0 5px 0;
            color: #667eea;
            font-size: 14px;
            text-transform: uppercase;
        }}
        .summary-card p {{
            margin: 0;
            font-size: 24px;
            font-weight: bold;
            color: #333;
        }}
        .image-container {{
            background: white;
            margin-bottom: 30px;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .image-header {{
            background: #667eea;
            color: white;
            padding: 15px 20px;
            font-weight: 500;
        }}
        .image-meta {{
            padding: 15px 20px;
            background: #f8f9fa;
            border-bottom: 1px solid #e0e0e0;
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            font-size: 13px;
        }}
        .meta-item {{
            display: flex;
            flex-direction: column;
        }}
        .meta-label {{
            color: #666;
            font-size: 11px;
            text-transform: uppercase;
        }}
        .meta-value {{
            color: #333;
            font-weight: 500;
            margin-top: 2px;
        }}
        .image-content {{
            padding: 20px;
            text-align: center;
            background: #fafafa;
        }}
        .image-content img {{
            max-width: 100%;
            height: auto;
            border-radius: 4px;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
            margin-left: 10px;
        }}
        .badge-anat {{
            background: #e3f2fd;
            color: #1976d2;
        }}
        .badge-func {{
            background: #f3e5f5;
            color: #7b1fa2;
        }}
        .data-table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 20px;
            font-size: 13px;
        }}
        .data-table th {{
            background: #667eea;
            color: white;
            padding: 10px 8px;
            text-align: center;
            font-weight: 500;
        }}
        .data-table td {{
            padding: 8px;
            text-align: center;
            border-bottom: 1px solid #e0e0e0;
        }}
        .data-table tr:hover {{
            background: #f8f9fa;
        }}
        .data-table td:first-child {{
            text-align: left;
        }}
        .table-container {{
            max-height: 600px;
            overflow-y: auto;
            border-radius: 8px;
            border: 1px solid #e0e0e0;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>BIDS Quality Assurance Report</h1>
        <p>Automated visual inspection of anatomical and functional MRI data</p>
    </div>

    <div class="summary">
        <h2>Summary Statistics</h2>
        <div class="summary-grid">
            <div class="summary-card">
                <h3>Total Scans</h3>
                <p>{total_scans}</p>
            </div>
            <div class="summary-card">
                <h3>Anatomical</h3>
                <p>{n_anat}</p>
            </div>
            <div class="summary-card">
                <h3>Functional</h3>
                <p>{n_func}</p>
            </div>
            <div class="summary-card">
                <h3>Subjects</h3>
                <p>{n_subjects}</p>
            </div>
        </div>
    </div>

    <div class="summary">
        <h2>Scan Availability by Subject</h2>
        <p style="margin-bottom: 10px; color: #666;">OK = Available, X = Missing</p>
        <div class="table-container">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Subject</th>
                        <th colspan="3">Session 1</th>
                        <th colspan="3">Session 2</th>
                    </tr>
                    <tr>
                        <th></th>
                        <th>T1w run-01</th>
                        <th>T1w run-02</th>
                        <th>fMRI rest</th>
                        <th>T1w run-01</th>
                        <th>T1w run-02</th>
                        <th>fMRI rest</th>
                    </tr>
                </thead>
                <tbody>
{table_rows}
                </tbody>
            </table>
        </div>
    </div>
"""

    # Add images
    for img_data in all_images:
        badge_class = 'badge-anat' if img_data['type'] == 'anat' else 'badge-func'
        badge_text = 'Anatomical' if img_data['type'] == 'anat' else 'Functional'

        meta_items = f"""
            <div class="meta-item">
                <span class="meta-label">Shape</span>
                <span class="meta-value">{img_data['shape']}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">Run</span>
                <span class="meta-value">{img_data['run']}</span>
            </div>
        """

        if img_data['type'] == 'func':
            meta_items += f"""
            <div class="meta-item">
                <span class="meta-label">Volumes</span>
                <span class="meta-value">{img_data['n_volumes']}</span>
            </div>
            <div class="meta-item">
                <span class="meta-label">File Size</span>
                <span class="meta-value">{img_data['file_size_mb']:.1f} MB</span>
            </div>
            """

        html += f"""
    <div class="image-container">
        <div class="image-header">
            {img_data['subject']} / {img_data['session']}
            <span class="badge {badge_class}">{badge_text}</span>
        </div>
        <div class="image-meta">
            {meta_items}
            <div class="meta-item">
                <span class="meta-label">File</span>
                <span class="meta-value" style="font-size: 11px; word-break: break-all;">{img_data['file']}</span>
            </div>
        </div>
        <div class="image-content">
            <img src="data:image/png;base64,{img_data['img_base64']}" alt="{img_data['subject']} {img_data['session']} {badge_text}">
        </div>
    </div>
"""

    html += """
</body>
</html>
"""

    # Save HTML
    html_file = output_dir / 'qa_report.html'
    with open(html_file, 'w') as f:
        f.write(html)

    print(f"\nHTML report saved: {html_file}")
    return html_file


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='QA visual check of T1w and functional images'
    )
    parser.add_argument('--bids-dir', default='bids',
                        help='BIDS directory path')
    parser.add_argument('--output', default='qa_images',
                        help='Output directory for QA images and HTML report')
    parser.add_argument('--subjects', nargs='+',
                        help='List of subject IDs (e.g., sub-033 sub-034). If not specified, scans all.')
    parser.add_argument('--sessions', nargs='+', default=['ses-01', 'ses-02'],
                        help='List of sessions to process (default: ses-01 ses-02)')
    parser.add_argument('--no-html', action='store_true',
                        help='Skip HTML report generation')

    args = parser.parse_args()

    scan_and_generate_all(
        bids_dir=Path(args.bids_dir),
        output_dir=Path(args.output),
        subjects=args.subjects,
        sessions=args.sessions,
        generate_html=not args.no_html,
        verbose=True
    )


if __name__ == '__main__':
    main()
