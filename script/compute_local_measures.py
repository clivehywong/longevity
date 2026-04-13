#!/usr/bin/env python3
"""
Local Measures: fALFF and ReHo for Longitudinal Walking Intervention Study

Computes voxelwise local measures from fMRIPrep preprocessed BOLD data:
- fALFF (fractional Amplitude of Low-Frequency Fluctuations)
- ReHo (Regional Homogeneity via Kendall's W)

Usage:
    python compute_local_measures.py \
        --fmriprep /path/to/fmriprep \
        --output results/local_measures \
        --measures fALFF ReHo \
        --subjects sub-033 sub-034

Dependencies:
    pip install nibabel nilearn numpy scipy pandas
"""

import argparse
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
from scipy import signal
from scipy.stats import rankdata
from nilearn.masking import apply_mask, unmask
from nilearn.image import clean_img, load_img, math_img

warnings.filterwarnings('ignore')


def load_confounds(confounds_file, strategy='basic'):
    """
    Load confound regressors from fMRIPrep confounds TSV.

    Parameters
    ----------
    confounds_file : str
        Path to *_desc-confounds_timeseries.tsv
    strategy : str
        'basic' = 6 motion + CSF + WM
        'extended' = basic + derivatives

    Returns
    -------
    confounds_array : ndarray
        Confound regressors (n_volumes x n_confounds)
    """
    df = pd.read_csv(confounds_file, sep='\t')

    if strategy == 'basic':
        cols = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z',
                'csf', 'white_matter']
    elif strategy == 'extended':
        cols = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z',
                'trans_x_derivative1', 'trans_y_derivative1', 'trans_z_derivative1',
                'rot_x_derivative1', 'rot_y_derivative1', 'rot_z_derivative1',
                'csf', 'white_matter']
    else:
        cols = ['trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z',
                'csf', 'white_matter']

    available = [c for c in cols if c in df.columns]
    confounds = df[available].values

    # Fill NaN (first row for derivatives)
    confounds = np.nan_to_num(confounds, nan=0.0)

    return confounds


def compute_falff(bold_file, mask_file, confounds_file, tr=0.8,
                  low_freq=0.01, high_freq=0.1):
    """
    Compute fractional Amplitude of Low-Frequency Fluctuations (fALFF).

    fALFF = power in 0.01-0.1 Hz / power in full frequency range (up to Nyquist)

    Parameters
    ----------
    bold_file : str
        Preprocessed BOLD NIfTI file
    mask_file : str
        Brain mask NIfTI file
    confounds_file : str
        fMRIPrep confounds TSV
    tr : float
        Repetition time in seconds
    low_freq : float
        Lower bound of frequency band of interest (Hz)
    high_freq : float
        Upper bound of frequency band of interest (Hz)

    Returns
    -------
    falff_img : Nifti1Image
        Whole-brain fALFF map
    """
    print(f"    Computing fALFF (band: {low_freq}-{high_freq} Hz, TR={tr}s)...")

    # Load confounds
    confounds = load_confounds(confounds_file)

    # Clean image: regress confounds and detrend (no bandpass yet)
    bold_img = load_img(bold_file)
    mask_img = load_img(mask_file)

    cleaned_img = clean_img(
        bold_img,
        confounds=confounds,
        detrend=True,
        standardize=False,
        t_r=tr,
        mask_img=mask_img
    )

    # Extract masked data
    data_2d = apply_mask(cleaned_img, mask_img)  # (n_volumes, n_voxels)
    n_volumes, n_voxels = data_2d.shape

    # Compute power spectral density for each voxel
    fs = 1.0 / tr  # Sampling frequency
    nyquist = fs / 2.0

    # Use Welch's method for PSD estimation
    nperseg = min(n_volumes, 256)
    freqs, psd = signal.welch(data_2d, fs=fs, nperseg=nperseg, axis=0)

    # Frequency masks
    band_mask = (freqs >= low_freq) & (freqs <= high_freq)
    full_mask = freqs > 0  # Exclude DC component

    # Compute fALFF
    power_band = np.sum(psd[band_mask, :], axis=0)
    power_full = np.sum(psd[full_mask, :], axis=0)

    # Avoid division by zero
    falff_values = np.zeros(n_voxels)
    valid = power_full > 0
    falff_values[valid] = power_band[valid] / power_full[valid]

    # Convert back to image
    falff_img = unmask(falff_values, mask_img)

    return falff_img


def compute_reho(bold_file, mask_file, confounds_file, tr=0.8,
                 neighborhood='faces_edges_corners', low_freq=0.01, high_freq=0.1):
    """
    Compute Regional Homogeneity (ReHo) using Kendall's W.

    ReHo measures the similarity (concordance) of a voxel's timeseries
    with its neighbors using Kendall's coefficient of concordance.

    Parameters
    ----------
    bold_file : str
        Preprocessed BOLD NIfTI file
    mask_file : str
        Brain mask NIfTI file
    confounds_file : str
        fMRIPrep confounds TSV
    tr : float
        Repetition time in seconds
    neighborhood : str
        'faces' (6 neighbors), 'faces_edges' (18), 'faces_edges_corners' (26)
    low_freq : float
        Low-pass filter cutoff (Hz)
    high_freq : float
        High-pass filter cutoff (Hz)

    Returns
    -------
    reho_img : Nifti1Image
        Whole-brain ReHo map
    """
    print(f"    Computing ReHo (neighborhood={neighborhood})...")

    # Load confounds
    confounds = load_confounds(confounds_file)

    # Clean image: regress confounds, detrend, and bandpass filter
    bold_img = load_img(bold_file)
    mask_img = load_img(mask_file)

    cleaned_img = clean_img(
        bold_img,
        confounds=confounds,
        detrend=True,
        standardize=False,
        low_pass=high_freq,
        high_pass=low_freq,
        t_r=tr,
        mask_img=mask_img
    )

    # Get 4D data
    data_4d = cleaned_img.get_fdata()
    mask_data = mask_img.get_fdata().astype(bool)
    nx, ny, nz, nt = data_4d.shape

    # Define neighborhood offsets
    if neighborhood == 'faces':
        offsets = [(-1, 0, 0), (1, 0, 0), (0, -1, 0), (0, 1, 0), (0, 0, -1), (0, 0, 1)]
    elif neighborhood == 'faces_edges':
        offsets = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                for dz in [-1, 0, 1]:
                    if abs(dx) + abs(dy) + abs(dz) <= 2 and (dx, dy, dz) != (0, 0, 0):
                        offsets.append((dx, dy, dz))
    else:  # faces_edges_corners (26 neighbors)
        offsets = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                for dz in [-1, 0, 1]:
                    if (dx, dy, dz) != (0, 0, 0):
                        offsets.append((dx, dy, dz))

    # Compute ReHo for each voxel in mask
    reho_data = np.zeros((nx, ny, nz))
    mask_coords = np.argwhere(mask_data)
    total_voxels = len(mask_coords)

    for idx, (x, y, z) in enumerate(mask_coords):
        if (idx + 1) % 50000 == 0:
            print(f"      Progress: {idx + 1}/{total_voxels} voxels")

        # Collect timeseries from voxel and neighbors
        timeseries_list = [data_4d[x, y, z, :]]

        for dx, dy, dz in offsets:
            nx2, ny2, nz2 = x + dx, y + dy, z + dz
            if (0 <= nx2 < nx and 0 <= ny2 < ny and 0 <= nz2 < nz
                    and mask_data[nx2, ny2, nz2]):
                timeseries_list.append(data_4d[nx2, ny2, nz2, :])

        n_neighbors = len(timeseries_list)
        if n_neighbors < 2:
            continue

        # Compute Kendall's W (coefficient of concordance)
        reho_data[x, y, z] = kendalls_w(np.array(timeseries_list))

    # Create NIfTI image
    reho_img = nib.Nifti1Image(reho_data, cleaned_img.affine, cleaned_img.header)

    return reho_img


def kendalls_w(timeseries_matrix):
    """
    Compute Kendall's coefficient of concordance (W).

    Parameters
    ----------
    timeseries_matrix : ndarray
        Shape (n_judges, n_items) - each row is a judge (voxel), each column is an item (timepoint)

    Returns
    -------
    w : float
        Kendall's W (0 to 1, 1 = perfect concordance)
    """
    k, n = timeseries_matrix.shape  # k judges, n items

    if k < 2 or n < 2:
        return 0.0

    # Rank each judge's ratings
    ranked = np.zeros_like(timeseries_matrix, dtype=float)
    for i in range(k):
        ranked[i, :] = rankdata(timeseries_matrix[i, :])

    # Sum of ranks for each item
    rank_sums = np.sum(ranked, axis=0)

    # Mean rank sum
    mean_rank_sum = np.mean(rank_sums)

    # S = sum of squared deviations of rank sums from mean
    s = np.sum((rank_sums - mean_rank_sum) ** 2)

    # Maximum possible S
    s_max = (k ** 2) * (n ** 3 - n) / 12.0

    if s_max == 0:
        return 0.0

    w = s / s_max
    return w


def find_bold_files(fmriprep_dir, space='MNI152NLin2009cAsym', res='2',
                    subjects=None, sessions=None):
    """
    Find preprocessed BOLD files and their associated masks and confounds.

    Returns
    -------
    file_list : list of dict
        Each dict has keys: subject, session, bold, mask, confounds
    """
    fmriprep_dir = Path(fmriprep_dir)
    file_list = []

    bold_pattern = f'**/func/*_space-{space}_res-{res}_desc-preproc_bold.nii.gz'
    bold_files = sorted(fmriprep_dir.glob(bold_pattern))

    for bold_file in bold_files:
        # Parse subject and session
        parts = bold_file.stem.replace('.nii', '').split('_')
        subject = [p for p in parts if p.startswith('sub-')][0]
        session_matches = [p for p in parts if p.startswith('ses-')]
        session = session_matches[0] if session_matches else 'ses-01'

        # Filter by subject/session if specified
        if subjects and subject not in subjects:
            continue
        if sessions and session not in sessions:
            continue

        # Find associated mask
        mask_file = bold_file.parent / bold_file.name.replace(
            '_desc-preproc_bold.nii.gz', '_desc-brain_mask.nii.gz')

        # Find confounds
        confounds_file = bold_file.parent / bold_file.name.replace(
            f'_space-{space}_res-{res}_desc-preproc_bold.nii.gz',
            '_desc-confounds_timeseries.tsv')

        if not mask_file.exists():
            print(f"  Warning: No mask for {subject} {session}, skipping")
            continue
        if not confounds_file.exists():
            print(f"  Warning: No confounds for {subject} {session}, skipping")
            continue

        file_list.append({
            'subject': subject,
            'session': session,
            'bold': str(bold_file),
            'mask': str(mask_file),
            'confounds': str(confounds_file)
        })

    return file_list


def main():
    parser = argparse.ArgumentParser(
        description="Compute local measures (fALFF, ReHo) from fMRIPrep preprocessed data"
    )
    parser.add_argument('--fmriprep', type=str, required=True,
                        help='fMRIPrep derivatives directory')
    parser.add_argument('--output', type=str, required=True,
                        help='Output directory for local measures')
    parser.add_argument('--measures', nargs='+', default=['fALFF', 'ReHo'],
                        choices=['fALFF', 'ReHo'],
                        help='Measures to compute (default: fALFF ReHo)')
    parser.add_argument('--subjects', nargs='+',
                        help='Specific subjects to process (e.g., sub-033 sub-034)')
    parser.add_argument('--sessions', nargs='+',
                        help='Specific sessions (e.g., ses-01 ses-02)')
    parser.add_argument('--space', default='MNI152NLin2009cAsym',
                        help='BOLD space (default: MNI152NLin2009cAsym)')
    parser.add_argument('--res', default='2',
                        help='Resolution (default: 2)')
    parser.add_argument('--tr', type=float, default=0.8,
                        help='Repetition time in seconds (default: 0.8)')
    parser.add_argument('--low-freq', type=float, default=0.01,
                        help='Low frequency cutoff in Hz (default: 0.01)')
    parser.add_argument('--high-freq', type=float, default=0.1,
                        help='High frequency cutoff in Hz (default: 0.1)')
    parser.add_argument('--neighborhood', default='faces_edges_corners',
                        choices=['faces', 'faces_edges', 'faces_edges_corners'],
                        help='ReHo neighborhood type (default: faces_edges_corners, 26 neighbors)')

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LOCAL MEASURES COMPUTATION")
    print("=" * 60)
    print(f"Measures: {args.measures}")
    print(f"TR: {args.tr}s")
    print(f"Frequency band: {args.low_freq}-{args.high_freq} Hz")
    print(f"Output: {output_dir}")

    # Find BOLD files
    file_list = find_bold_files(
        args.fmriprep, space=args.space, res=args.res,
        subjects=args.subjects, sessions=args.sessions
    )

    print(f"\nFound {len(file_list)} BOLD files to process")

    if len(file_list) == 0:
        print("ERROR: No BOLD files found. Check fMRIPrep directory.")
        return 1

    # Summary table
    summary_rows = []

    # Process each file
    for i, finfo in enumerate(file_list):
        subject = finfo['subject']
        session = finfo['session']
        print(f"\n{'='*60}")
        print(f"[{i+1}/{len(file_list)}] {subject} {session}")
        print(f"{'='*60}")

        row = {'subject': subject, 'session': session}

        # Compute fALFF
        if 'fALFF' in args.measures:
            try:
                falff_img = compute_falff(
                    finfo['bold'], finfo['mask'], finfo['confounds'],
                    tr=args.tr, low_freq=args.low_freq, high_freq=args.high_freq
                )
                falff_file = output_dir / f'{subject}_{session}_fALFF.nii.gz'
                nib.save(falff_img, falff_file)
                print(f"    Saved: {falff_file.name}")

                # Summary stats
                falff_data = falff_img.get_fdata()
                mask_data = nib.load(finfo['mask']).get_fdata().astype(bool)
                masked_vals = falff_data[mask_data]
                row['fALFF_mean'] = np.mean(masked_vals)
                row['fALFF_std'] = np.std(masked_vals)
                row['fALFF_median'] = np.median(masked_vals)
                row['fALFF_file'] = str(falff_file)

            except Exception as e:
                print(f"    ERROR computing fALFF: {e}")
                row['fALFF_mean'] = np.nan

        # Compute ReHo
        if 'ReHo' in args.measures:
            try:
                reho_img = compute_reho(
                    finfo['bold'], finfo['mask'], finfo['confounds'],
                    tr=args.tr, neighborhood=args.neighborhood,
                    low_freq=args.low_freq, high_freq=args.high_freq
                )
                reho_file = output_dir / f'{subject}_{session}_ReHo.nii.gz'
                nib.save(reho_img, reho_file)
                print(f"    Saved: {reho_file.name}")

                # Summary stats
                reho_data = reho_img.get_fdata()
                mask_data = nib.load(finfo['mask']).get_fdata().astype(bool)
                masked_vals = reho_data[mask_data]
                row['ReHo_mean'] = np.mean(masked_vals)
                row['ReHo_std'] = np.std(masked_vals)
                row['ReHo_median'] = np.median(masked_vals)
                row['ReHo_file'] = str(reho_file)

            except Exception as e:
                print(f"    ERROR computing ReHo: {e}")
                row['ReHo_mean'] = np.nan

        summary_rows.append(row)

    # Save summary
    summary_df = pd.DataFrame(summary_rows)
    summary_file = output_dir / 'local_measures_summary.csv'
    summary_df.to_csv(summary_file, index=False)

    print(f"\n{'='*60}")
    print("LOCAL MEASURES COMPLETE")
    print(f"{'='*60}")
    print(f"Processed: {len(file_list)} files")
    print(f"Summary: {summary_file}")

    if 'fALFF_mean' in summary_df.columns:
        print(f"\nfALFF statistics:")
        print(f"  Mean across subjects: {summary_df['fALFF_mean'].mean():.4f}")
        print(f"  Range: [{summary_df['fALFF_mean'].min():.4f}, {summary_df['fALFF_mean'].max():.4f}]")

    if 'ReHo_mean' in summary_df.columns:
        print(f"\nReHo statistics:")
        print(f"  Mean across subjects: {summary_df['ReHo_mean'].mean():.4f}")
        print(f"  Range: [{summary_df['ReHo_mean'].min():.4f}, {summary_df['ReHo_mean'].max():.4f}]")

    return 0


if __name__ == '__main__':
    exit(main())
