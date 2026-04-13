#!/usr/bin/env python3
"""
Quality Assurance - Visual Check of T1w and Functional Images

Creates montage images showing mid-slices (axial, coronal, sagittal) for:
- T1w structural images (all subjects, all sessions)
- Functional BOLD images (all subjects, all sessions)

Also reports:
- Number of volumes per functional run
- File sizes and dimensions

Usage:
    python qa_check_images.py --output qa_images/
"""

import argparse
import base64
import io
import os
from pathlib import Path

import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd


def load_nifti_mid_slices(nifti_file):
    """
    Load middle slices from a NIfTI file.

    Returns:
        dict with 'axial', 'coronal', 'sagittal' slices
    """
    img = nib.load(nifti_file)
    data = img.get_fdata()

    # Handle 4D (functional) or 3D (structural)
    if len(data.shape) == 4:
        # Take mean across time for functional
        data = data.mean(axis=-1)

    # Get middle slices
    slices = {
        'axial': data[:, :, data.shape[2] // 2],
        'coronal': data[:, data.shape[1] // 2, :],
        'sagittal': data[data.shape[0] // 2, :, :]
    }

    return slices, data.shape


def fig_to_base64(fig):
    """Convert matplotlib figure to base64 encoded PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=100, bbox_inches='tight')
    buf.seek(0)
    img_base64 = base64.b64encode(buf.read()).decode('utf-8')
    buf.close()
    return img_base64


def plot_subject_t1w(bids_dir, subject, session, run, output_dir):
    """
    Plot T1w structural for one subject/session/run.
    Creates 7 axial and 7 sagittal slices.

    Args:
        bids_dir: BIDS directory path
        subject: Subject ID (e.g., 'sub-033')
        session: Session ID (e.g., 'ses-01')
        run: Run ID (e.g., 'run-01')
        output_dir: Output directory
    """
    t1w_path = Path(bids_dir) / subject / session / 'anat' / f"{subject}_{session}_{run}_T1w.nii.gz"

    if not t1w_path.exists():
        print(f"  T1w not found: {t1w_path}")
        return None

    try:
        img = nib.load(str(t1w_path))
        data = img.get_fdata()

        # Handle different dimensionalities
        if len(data.shape) == 4:
            # Take mean if 4D
            data = data.mean(axis=-1)
        elif len(data.shape) < 3:
            print(f"  Warning: {t1w_path} has invalid shape {data.shape}")
            return None

        # Ensure 3D
        data = np.squeeze(data)
        if len(data.shape) != 3:
            print(f"  Warning: {t1w_path} could not be converted to 3D, shape: {data.shape}")
            return None

        # Create figure with 7 axial + 7 sagittal slices
        fig, axes = plt.subplots(2, 7, figsize=(21, 6))

        # 7 axial slices (evenly spaced through z-axis)
        z_indices = np.linspace(data.shape[2] // 4, 3 * data.shape[2] // 4, 7, dtype=int)
        for i, z_idx in enumerate(z_indices):
            axes[0, i].imshow(data[:, :, z_idx].T, cmap='gray', origin='lower')
            axes[0, i].set_title(f'Axial {z_idx}', fontsize=8)
            axes[0, i].axis('off')

        # 7 sagittal slices (evenly spaced through x-axis)
        x_indices = np.linspace(data.shape[0] // 4, 3 * data.shape[0] // 4, 7, dtype=int)
        for i, x_idx in enumerate(x_indices):
            axes[1, i].imshow(data[x_idx, :, :].T, cmap='gray', origin='lower')
            axes[1, i].set_title(f'Sagittal {x_idx}', fontsize=8)
            axes[1, i].axis('off')

        fig.suptitle(f'{subject} {session} {run} T1w - Shape: {data.shape}',
                     fontsize=12, fontweight='bold')

        plt.tight_layout()

        # Save as PNG
        output_file = Path(output_dir) / 'structural' / f'{subject}_{session}_{run}_T1w.png'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_file, dpi=100, bbox_inches='tight')

        # Convert to base64
        img_base64 = fig_to_base64(fig)
        plt.close()

        return {
            'shape': data.shape,
            'file': str(t1w_path),
            'run': run,
            'img_base64': img_base64,
            'type': 'anat'
        }

    except Exception as e:
        print(f"  Error processing {t1w_path}: {e}")
        return None


def plot_subject_functional(bids_dir, subject, session, output_dir):
    """
    Plot functional BOLD for one subject/session.
    Creates mid-axial, mid-sagittal, mid-coronal for 3 volumes (early, middle, late).
    """
    func_path = Path(bids_dir) / subject / session / 'func' / f"{subject}_{session}_task-rest_bold.nii.gz"

    if not func_path.exists():
        print(f"  Functional not found: {func_path}")
        return None

    try:
        img = nib.load(str(func_path))
        data = img.get_fdata()

        n_volumes = data.shape[3] if len(data.shape) == 4 else 1

        if len(data.shape) != 4:
            print(f"  Warning: {func_path} is not 4D")
            return None

        # Select 3 volumes: early (10%), middle (50%), late (90%)
        vol_indices = [
            int(n_volumes * 0.1),
            int(n_volumes * 0.5),
            int(n_volumes * 0.9)
        ]

        # Create figure: 3 rows (volumes) × 3 columns (axial, coronal, sagittal)
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

        fig.suptitle(f'{subject} {session} Functional - Shape: {data.shape[:3]} × {n_volumes} vols',
                     fontsize=12, fontweight='bold')

        plt.tight_layout()

        # Save as PNG
        output_file = Path(output_dir) / 'functional' / f'{subject}_{session}_func.png'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_file, dpi=100, bbox_inches='tight')

        # Convert to base64
        img_base64 = fig_to_base64(fig)
        plt.close()

        return {
            'shape': data.shape[:3],
            'n_volumes': n_volumes,
            'file': str(func_path),
            'file_size_mb': func_path.stat().st_size / (1024**2),
            'img_base64': img_base64,
            'type': 'func'
        }

    except Exception as e:
        print(f"  Error processing {func_path}: {e}")
        return None


def create_html_report(results, output_dir):
    """Create HTML report with embedded base64 images."""

    # Build summary table data
    summary_data = []
    all_subjects = sorted(set(list(results['t1w'].keys()) + list(results['functional'].keys())))

    for subject in all_subjects:
        row = {'subject': subject}

        # Check ses-01
        for scan_type in ['ses01_run01_T1w', 'ses01_run02_T1w', 'ses01_rest']:
            row[scan_type] = '❌'

        if subject in results['t1w'] and 'ses-01' in results['t1w'][subject]:
            t1w_list = results['t1w'][subject]['ses-01']
            if t1w_list:
                if isinstance(t1w_list, list):
                    runs = [info.get('run', '') for info in t1w_list]
                    if 'run-01' in runs:
                        row['ses01_run01_T1w'] = '✅'
                    if 'run-02' in runs:
                        row['ses01_run02_T1w'] = '✅'
                else:
                    if t1w_list.get('run') == 'run-01':
                        row['ses01_run01_T1w'] = '✅'

        if subject in results['functional'] and 'ses-01' in results['functional'][subject]:
            if results['functional'][subject]['ses-01']:
                row['ses01_rest'] = '✅'

        # Check ses-02
        for scan_type in ['ses02_run01_T1w', 'ses02_run02_T1w', 'ses02_rest']:
            row[scan_type] = '❌'

        if subject in results['t1w'] and 'ses-02' in results['t1w'][subject]:
            t1w_list = results['t1w'][subject]['ses-02']
            if t1w_list:
                if isinstance(t1w_list, list):
                    runs = [info.get('run', '') for info in t1w_list]
                    if 'run-01' in runs:
                        row['ses02_run01_T1w'] = '✅'
                    if 'run-02' in runs:
                        row['ses02_run02_T1w'] = '✅'
                else:
                    if t1w_list.get('run') == 'run-01':
                        row['ses02_run01_T1w'] = '✅'

        if subject in results['functional'] and 'ses-02' in results['functional'][subject]:
            if results['functional'][subject]['ses-02']:
                row['ses02_rest'] = '✅'

        summary_data.append(row)

    # Collect all images ordered by subject, session, type (anat/func), run
    all_images = []

    for subject in sorted(results['t1w'].keys()):
        for session in sorted(results['t1w'][subject].keys()):
            # Add T1w (can be multiple runs)
            t1w_list = results['t1w'][subject][session]
            if t1w_list:
                # Handle both list and dict formats
                if isinstance(t1w_list, list):
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
                else:
                    # Old format (single dict)
                    info = t1w_list
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

    # Sort by subject, session, type (anat before func), run
    all_images.sort(key=lambda x: (x['subject'], x['session'], x['type'], x['run']))

    # Calculate summary stats
    n_subjects = len(set(img['subject'] for img in all_images))
    n_anat = sum(1 for img in all_images if img['type'] == 'anat')
    n_func = sum(1 for img in all_images if img['type'] == 'func')
    total_scans = len(all_images)

    # Generate table rows
    table_rows = ""
    for row in summary_data:
        table_rows += f"""
                    <tr>
                        <td>{row['subject']}</td>
                        <td>{row['ses01_run01_T1w']}</td>
                        <td>{row['ses01_run02_T1w']}</td>
                        <td>{row['ses01_rest']}</td>
                        <td>{row['ses02_run01_T1w']}</td>
                        <td>{row['ses02_run02_T1w']}</td>
                        <td>{row['ses02_rest']}</td>
                    </tr>"""

    # Generate HTML (using double braces for literal braces in CSS)
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
        .header h1 {{
            margin: 0 0 10px 0;
        }}
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
            position: sticky;
            top: 0;
            z-index: 10;
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
            font-weight: 500;
            color: #667eea;
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
        <p style="margin-bottom: 10px; color: #666;">✅ = Available, ❌ = Missing</p>
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
    html_file = Path(output_dir) / 'qa_report.html'
    with open(html_file, 'w') as f:
        f.write(html)

    print(f"\nHTML report saved: {html_file}")
    return html_file


def create_summary_report(results, output_dir):
    """Create summary CSV and HTML report."""

    # T1w summary
    t1w_data = []
    for subject, sessions in results['t1w'].items():
        for session, t1w_list in sessions.items():
            if t1w_list:
                # Handle both list and dict formats
                if isinstance(t1w_list, list):
                    for info in t1w_list:
                        t1w_data.append({
                            'subject': subject,
                            'session': session,
                            'shape': str(info['shape']),
                            'run': info.get('run', 'run-01'),
                            'file': info['file']
                        })
                else:
                    # Old format (single dict)
                    info = t1w_list
                    t1w_data.append({
                        'subject': subject,
                        'session': session,
                        'shape': str(info['shape']),
                        'run': info.get('run', 'run-01'),
                        'file': info['file']
                    })

    t1w_df = pd.DataFrame(t1w_data)
    t1w_csv = Path(output_dir) / 't1w_summary.csv'
    t1w_df.to_csv(t1w_csv, index=False)
    print(f"\nT1w summary saved: {t1w_csv}")

    # Functional summary
    func_data = []
    for subject, sessions in results['functional'].items():
        for session, info in sessions.items():
            if info:
                func_data.append({
                    'subject': subject,
                    'session': session,
                    'shape': str(info['shape']),
                    'n_volumes': info['n_volumes'],
                    'file_size_mb': f"{info['file_size_mb']:.1f}",
                    'file': info['file']
                })

    func_df = pd.DataFrame(func_data)
    func_csv = Path(output_dir) / 'functional_summary.csv'
    func_df.to_csv(func_csv, index=False)
    print(f"Functional summary saved: {func_csv}")

    # Create HTML report
    create_html_report(results, output_dir)

    # Summary statistics
    print("\n" + "="*60)
    print("QA SUMMARY")
    print("="*60)
    print(f"\nT1w images: {len(t1w_df)}")
    print(f"  Sessions: {t1w_df.groupby('subject').size().value_counts().to_dict()}")

    print(f"\nFunctional images: {len(func_df)}")
    print(f"  Volume counts:")
    print(func_df.groupby('n_volumes').size().to_frame('count'))
    print(f"\n  Mean file size: {func_df['file_size_mb'].astype(float).mean():.1f} MB")

    # Check for issues
    print("\n" + "="*60)
    print("ISSUES CHECK")
    print("="*60)

    # Volume count variations
    vol_counts = func_df['n_volumes'].value_counts()
    if len(vol_counts) > 1:
        print(f"\n⚠️  Volume count variations detected:")
        for vol, count in vol_counts.items():
            print(f"     {vol} volumes: {count} sessions")
    else:
        print(f"\n✓  All sessions have {func_df['n_volumes'].iloc[0]} volumes")

    # Missing data
    expected_sessions = len(t1w_df)
    if len(func_df) < expected_sessions:
        print(f"\n⚠️  Missing functional data: {expected_sessions - len(func_df)} sessions")
    else:
        print(f"\n✓  All {expected_sessions} sessions have functional data")


def main():
    parser = argparse.ArgumentParser(
        description='QA visual check of T1w and functional images'
    )
    parser.add_argument('--bids-dir', default='bids',
                        help='BIDS directory path')
    parser.add_argument('--output', default='qa_images',
                        help='Output directory for QA images and HTML report')
    parser.add_argument('--subjects', nargs='+',
                        help='List of subject IDs (e.g., sub-033 sub-034). If not specified, scans all subjects in BIDS directory.')
    parser.add_argument('--sessions', nargs='+', default=['ses-01', 'ses-02'],
                        help='List of sessions to process (default: ses-01 ses-02)')

    args = parser.parse_args()

    # Get subjects
    if args.subjects:
        subjects = args.subjects
    else:
        # Auto-detect subjects from BIDS directory
        bids_path = Path(args.bids_dir)
        subjects = sorted([d.name for d in bids_path.iterdir()
                          if d.is_dir() and d.name.startswith('sub-')])

    sessions = args.sessions

    print("="*60)
    print("QUALITY ASSURANCE - IMAGE CHECK")
    print("="*60)
    print(f"\nBIDS directory: {args.bids_dir}")
    print(f"Output directory: {args.output}")
    print(f"Subjects: {len(subjects)}")
    print(f"Sessions: {sessions}")
    print(f"Total expected: {len(subjects) * len(sessions)} scans")

    # Create output directory
    Path(args.output).mkdir(parents=True, exist_ok=True)

    # Process all images
    results = {'t1w': {}, 'functional': {}}

    for subject in subjects:
        print(f"\nProcessing {subject}...")
        if subject not in results['t1w']:
            results['t1w'][subject] = {}
        if subject not in results['functional']:
            results['functional'][subject] = {}

        for session in sessions:
            # Find all T1w runs for this subject/session
            anat_dir = Path(args.bids_dir) / subject / session / 'anat'
            t1w_files = []
            if anat_dir.exists():
                t1w_files = sorted(anat_dir.glob(f'{subject}_{session}_run-*_T1w.nii.gz'))

            if not t1w_files:
                print(f"  No T1w files found for {subject}/{session}")
                results['t1w'][subject][session] = []
            else:
                # Process all runs
                session_t1w = []
                for t1w_file in t1w_files:
                    # Extract run number from filename
                    run = t1w_file.name.split('_')[2]  # e.g., 'run-01'
                    t1w_info = plot_subject_t1w(args.bids_dir, subject, session, run, args.output)
                    if t1w_info:
                        session_t1w.append(t1w_info)
                results['t1w'][subject][session] = session_t1w

            # Functional
            func_info = plot_subject_functional(args.bids_dir, subject, session, args.output)
            results['functional'][subject][session] = func_info

    # Create summary report
    create_summary_report(results, args.output)

    print("\n" + "="*60)
    print("QA CHECK COMPLETE")
    print("="*60)
    print(f"\nImages saved to: {args.output}")
    print(f"  - {args.output}/structural/ (T1w)")
    print(f"  - {args.output}/functional/ (BOLD mean)")


if __name__ == '__main__':
    main()
