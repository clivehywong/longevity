"""
Dimension Consistency Utilities

Ported from script/dimensional_consistency.py

Implementation: Phase 2 ✅
"""

import nibabel as nib
import numpy as np
from pathlib import Path
from typing import Dict, Optional, Tuple
import pandas as pd


def get_image_dimensions(nifti_path: Path) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Get image dimensions from NIfTI file.

    Ported from script/dimensional_consistency.py:56-78

    Returns:
        (dims_dict, error_message)
    """
    try:
        img = nib.load(str(nifti_path))
        header = img.header

        dims = {
            'shape': list(img.shape),
            'x': img.shape[0],
            'y': img.shape[1],
            'z': img.shape[2],
            't': img.shape[3] if len(img.shape) == 4 else 1,
            'voxel_dims': [round(float(z), 4) for z in header.get_zooms()[:3]],
            'data_dtype': str(header.get_data_dtype())
        }

        return dims, None

    except Exception as e:
        return None, str(e)


def scan_all_dimensions(bids_dir: Path, modalities: list = None) -> pd.DataFrame:
    """
    Scan all NIfTI files in BIDS directory and return dimension table.

    Args:
        bids_dir: BIDS directory path
        modalities: List of modalities to check (default: all)

    Returns:
        DataFrame with columns: subject, session, modality, run, x, y, z, t, status
    """
    bids_dir = Path(bids_dir)

    if modalities is None:
        modalities = ['anat', 'func', 'dwi', 'fmap']

    results = []

    # Scan all NIfTI files
    for modality in modalities:
        nifti_files = list(bids_dir.rglob(f"**/{modality}/*.nii.gz"))

        for nifti_file in nifti_files:
            # Extract BIDS entities
            parts = nifti_file.parts
            subject = session = run = None

            for part in parts:
                if part.startswith('sub-'):
                    subject = part
                elif part.startswith('ses-'):
                    session = part

            # Extract run from filename
            filename = nifti_file.stem.replace('.nii', '')
            if 'run-' in filename:
                run = [p for p in filename.split('_') if p.startswith('run-')][0]
            else:
                run = 'single'

            # Get dimensions
            dims, error = get_image_dimensions(nifti_file)

            if dims:
                results.append({
                    'subject': subject,
                    'session': session,
                    'modality': modality,
                    'run': run,
                    'file': nifti_file.name,
                    'x': dims['x'],
                    'y': dims['y'],
                    'z': dims['z'],
                    't': dims['t'],
                    'voxel_x': dims['voxel_dims'][0],
                    'voxel_y': dims['voxel_dims'][1],
                    'voxel_z': dims['voxel_dims'][2],
                    'status': 'OK',
                    'error': None
                })
            else:
                results.append({
                    'subject': subject,
                    'session': session,
                    'modality': modality,
                    'run': run,
                    'file': nifti_file.name,
                    'x': None,
                    'y': None,
                    'z': None,
                    't': None,
                    'voxel_x': None,
                    'voxel_y': None,
                    'voxel_z': None,
                    'status': 'ERROR',
                    'error': error
                })

    df = pd.DataFrame(results)

    # Flag inconsistencies
    if not df.empty:
        df = flag_inconsistencies(df)

    return df


def flag_inconsistencies(df: pd.DataFrame) -> pd.DataFrame:
    """Flag inconsistent dimensions within each modality."""

    for modality in df['modality'].unique():
        mask = df['modality'] == modality

        # Get mode (most common) dimensions for this modality
        mode_x = df.loc[mask, 'x'].mode()[0] if not df.loc[mask, 'x'].mode().empty else None
        mode_y = df.loc[mask, 'y'].mode()[0] if not df.loc[mask, 'y'].mode().empty else None
        mode_z = df.loc[mask, 'z'].mode()[0] if not df.loc[mask, 'z'].mode().empty else None

        # For functional, check t (volumes)
        if modality == 'func':
            mode_t = df.loc[mask, 't'].mode()[0] if not df.loc[mask, 't'].mode().empty else None

            # Flag if different from mode
            df.loc[mask & (df['t'] != mode_t), 'status'] = 'WARN'

        # Flag spatial dimension mismatches
        df.loc[mask & ((df['x'] != mode_x) | (df['y'] != mode_y) | (df['z'] != mode_z)), 'status'] = 'WARN'

    return df
