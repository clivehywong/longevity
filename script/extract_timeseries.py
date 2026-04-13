#!/usr/bin/env python3
"""
Extract time series from preprocessed fMRI data using various atlases.
Supports multiple atlases for comparison and generates QC metrics.
"""

import argparse
import pandas as pd
import numpy as np
from pathlib import Path
from nilearn import datasets, image, masking
from nilearn.maskers import NiftiLabelsMasker
import json
import warnings
warnings.filterwarnings('ignore')


def get_atlas(atlas_name):
    """Load atlas based on name (lazy loading - only fetch requested atlas)."""

    # Gordon atlas requires special handling
    if atlas_name == 'gordon_333':
        from setup_gordon_atlas import load_gordon_atlas
        return load_gordon_atlas()

    # Available atlas names for error message
    available_atlases = [
        'schaefer_400_7', 'schaefer_200_7', 'schaefer_100_7', 'schaefer_400_17',
        'difumo_256', 'difumo_512', 'difumo_1024', 'difumo_128',
        'aal', 'harvard_oxford_cort', 'basc_122', 'basc_197', 'gordon_333'
    ]

    # Lazy loading - only fetch the requested atlas
    if atlas_name == 'schaefer_400_7':
        return datasets.fetch_atlas_schaefer_2018(n_rois=400, yeo_networks=7, resolution_mm=2)
    elif atlas_name == 'schaefer_200_7':
        return datasets.fetch_atlas_schaefer_2018(n_rois=200, yeo_networks=7, resolution_mm=2)
    elif atlas_name == 'schaefer_100_7':
        return datasets.fetch_atlas_schaefer_2018(n_rois=100, yeo_networks=7, resolution_mm=2)
    elif atlas_name == 'schaefer_400_17':
        return datasets.fetch_atlas_schaefer_2018(n_rois=400, yeo_networks=17, resolution_mm=2)
    elif atlas_name == 'difumo_256':
        return datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2)
    elif atlas_name == 'difumo_512':
        return datasets.fetch_atlas_difumo(dimension=512, resolution_mm=2)
    elif atlas_name == 'difumo_1024':
        return datasets.fetch_atlas_difumo(dimension=1024, resolution_mm=2)
    elif atlas_name == 'difumo_128':
        return datasets.fetch_atlas_difumo(dimension=128, resolution_mm=2)
    elif atlas_name == 'aal':
        return datasets.fetch_atlas_aal(version='SPM12')
    elif atlas_name == 'harvard_oxford_cort':
        return datasets.fetch_atlas_harvard_oxford('cort-maxprob-thr25-2mm')
    elif atlas_name == 'basc_122':
        return datasets.fetch_atlas_basc_multiscale_2015(version='sym', resolution=122)
    elif atlas_name == 'basc_197':
        return datasets.fetch_atlas_basc_multiscale_2015(version='sym', resolution=197)
    else:
        raise ValueError(f"Unknown atlas: {atlas_name}. Available: {available_atlases}")


def load_confounds(confounds_file, strategy='minimal'):
    """Load confounds based on denoising strategy."""

    df = pd.read_csv(confounds_file, sep='\t')

    strategies = {
        'minimal': [
            'trans_x', 'trans_y', 'trans_z',
            'rot_x', 'rot_y', 'rot_z',
            'csf', 'white_matter'
        ],
        'standard': [
            'trans_x', 'trans_y', 'trans_z',
            'rot_x', 'rot_y', 'rot_z',
            'csf', 'white_matter',
            'trans_x_derivative1', 'trans_y_derivative1', 'trans_z_derivative1',
            'rot_x_derivative1', 'rot_y_derivative1', 'rot_z_derivative1',
        ],
        'extended': [
            'trans_x', 'trans_y', 'trans_z',
            'rot_x', 'rot_y', 'rot_z',
            'csf', 'white_matter', 'global_signal',
            'trans_x_derivative1', 'trans_y_derivative1', 'trans_z_derivative1',
            'rot_x_derivative1', 'rot_y_derivative1', 'rot_z_derivative1',
            'csf_derivative1', 'white_matter_derivative1', 'global_signal_derivative1',
        ],
    }

    # Get available confounds
    confound_cols = [c for c in strategies[strategy] if c in df.columns]

    # Add framewise displacement if available
    if 'framewise_displacement' in df.columns:
        confound_cols.append('framewise_displacement')

    return df[confound_cols].values


def extract_timeseries(bold_file, atlas_name='schaefer_400_7',
                       confounds_file=None, confound_strategy='minimal',
                       smoothing_fwhm=6, high_pass=0.01, low_pass=0.1,
                       detrend=True, standardize=True):
    """
    Extract time series from BOLD data using specified atlas.

    Parameters
    ----------
    bold_file : str
        Path to preprocessed BOLD NIfTI file
    atlas_name : str
        Name of atlas to use
    confounds_file : str
        Path to confounds TSV file
    confound_strategy : str
        Confound regression strategy: 'minimal', 'standard', 'extended'
    smoothing_fwhm : float
        FWHM for spatial smoothing (mm)
    high_pass : float
        High-pass filter cutoff (Hz)
    low_pass : float
        Low-pass filter cutoff (Hz)
    detrend : bool
        Apply temporal detrending
    standardize : bool
        Standardize time series to z-scores

    Returns
    -------
    timeseries : ndarray
        ROI x time array
    labels : list
        ROI labels
    metadata : dict
        Extraction metadata
    """

    # Load atlas
    atlas = get_atlas(atlas_name)

    # Create masker
    masker = NiftiLabelsMasker(
        labels_img=atlas.maps,
        labels=atlas.labels,
        smoothing_fwhm=smoothing_fwhm,
        high_pass=high_pass,
        low_pass=low_pass,
        detrend=detrend,
        standardize=standardize,
        t_r=2.0,  # Adjust if different
        verbose=1
    )

    # Load confounds if provided
    confounds = None
    if confounds_file and Path(confounds_file).exists():
        confounds = load_confounds(confounds_file, confound_strategy)

    # Extract time series
    timeseries = masker.fit_transform(bold_file, confounds=confounds)

    # Metadata
    metadata = {
        'atlas': atlas_name,
        'n_rois': len(atlas.labels),
        'smoothing_fwhm': smoothing_fwhm,
        'high_pass': high_pass,
        'low_pass': low_pass,
        'confound_strategy': confound_strategy,
        'detrend': detrend,
        'standardize': standardize,
        'n_volumes': timeseries.shape[0],
    }

    return timeseries, atlas.labels, metadata


def compute_qc_metrics(timeseries, confounds_file=None):
    """Compute QC metrics for time series."""

    metrics = {
        'mean_fd': None,
        'n_volumes': timeseries.shape[0],
        'n_rois': timeseries.shape[1],
        'mean_tsnr': np.mean(np.mean(timeseries, axis=0) / np.std(timeseries, axis=0)),
        'global_correlation': np.mean(np.corrcoef(timeseries.T)[np.triu_indices(timeseries.shape[1], k=1)]),
    }

    if confounds_file and Path(confounds_file).exists():
        df = pd.read_csv(confounds_file, sep='\t')
        if 'framewise_displacement' in df.columns:
            metrics['mean_fd'] = df['framewise_displacement'].mean()
            metrics['n_high_motion'] = (df['framewise_displacement'] > 0.5).sum()

    return metrics


def main():
    parser = argparse.ArgumentParser(description='Extract ROI time series from fMRIPrep outputs')
    parser.add_argument('fmriprep_dir', type=Path, help='fMRIPrep derivatives directory')
    parser.add_argument('output_dir', type=Path, help='Output directory for time series')
    parser.add_argument('--atlas', default='schaefer_400_7',
                        choices=[
                            'schaefer_400_7', 'schaefer_200_7', 'schaefer_100_7', 'schaefer_400_17',
                            'gordon_333',
                            'difumo_256', 'difumo_512', 'difumo_128', 'difumo_1024',
                            'aal', 'harvard_oxford_cort',
                            'basc_122', 'basc_197'
                        ],
                        help='Atlas to use')
    parser.add_argument('--space', default='MNI152NLin2009cAsym', help='Space of BOLD data')
    parser.add_argument('--smoothing', type=float, default=6.0, help='Smoothing FWHM (mm)')
    parser.add_argument('--high-pass', type=float, default=0.01, help='High-pass filter (Hz)')
    parser.add_argument('--low-pass', type=float, default=0.1, help='Low-pass filter (Hz)')
    parser.add_argument('--confounds', default='minimal',
                        choices=['minimal', 'standard', 'extended'],
                        help='Confound regression strategy')
    parser.add_argument('--subjects', nargs='+', help='Specific subjects to process')
    parser.add_argument('--sessions', nargs='+', help='Specific sessions to process')

    args = parser.parse_args()

    # Create output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Find all BOLD files (try with res-2 first, then without)
    pattern = f'**/func/*_space-{args.space}_res-2_desc-preproc_bold.nii.gz'
    bold_files = sorted(args.fmriprep_dir.glob(pattern))
    if len(bold_files) == 0:
        pattern = f'**/func/*_space-{args.space}_desc-preproc_bold.nii.gz'
        bold_files = sorted(args.fmriprep_dir.glob(pattern))

    # Filter by subjects/sessions if specified
    if args.subjects:
        bold_files = [f for f in bold_files if any(f'sub-{s}' in str(f) for s in args.subjects)]
    if args.sessions:
        bold_files = [f for f in bold_files if any(f'ses-{s}' in str(f) for s in args.sessions)]

    print(f"Found {len(bold_files)} BOLD files to process")

    # Process each file
    all_qc = []

    for bold_file in bold_files:
        print(f"\nProcessing: {bold_file.name}")

        # Find corresponding confounds file (handle both res-2 and non-res patterns)
        bold_name = bold_file.name
        if '_res-2_' in bold_name:
            confounds_name = bold_name.replace(
                f'_space-{args.space}_res-2_desc-preproc_bold.nii.gz',
                '_desc-confounds_timeseries.tsv'
            )
        else:
            confounds_name = bold_name.replace(
                f'_space-{args.space}_desc-preproc_bold.nii.gz',
                '_desc-confounds_timeseries.tsv'
            )
        confounds_file = bold_file.parent / confounds_name

        # Extract time series
        timeseries, labels, metadata = extract_timeseries(
            str(bold_file),
            atlas_name=args.atlas,
            confounds_file=str(confounds_file) if confounds_file.exists() else None,
            confound_strategy=args.confounds,
            smoothing_fwhm=args.smoothing,
            high_pass=args.high_pass,
            low_pass=args.low_pass,
        )

        # Save time series
        parts = bold_file.stem.replace('.nii', '').split('_')
        sub = [p for p in parts if p.startswith('sub-')][0]
        ses = [p for p in parts if p.startswith('ses-')][0] if any('ses-' in p for p in parts) else 'ses-01'
        task = [p for p in parts if p.startswith('task-')][0]

        output_base = args.output_dir / f"{sub}_{ses}_{task}_atlas-{args.atlas}"

        # Save as TSV
        df = pd.DataFrame(timeseries, columns=[l.decode() if isinstance(l, bytes) else l for l in labels])
        df.to_csv(f"{output_base}_timeseries.tsv", sep='\t', index=False)

        # Save metadata
        with open(f"{output_base}_metadata.json", 'w') as f:
            json.dump(metadata, f, indent=2)

        # Compute QC
        qc = compute_qc_metrics(timeseries, str(confounds_file) if confounds_file.exists() else None)
        qc.update({'subject': sub, 'session': ses, 'task': task})
        all_qc.append(qc)

        print(f"  Saved: {output_base}_timeseries.tsv")
        print(f"  Shape: {timeseries.shape}")
        print(f"  Mean FD: {qc['mean_fd']:.3f}" if qc['mean_fd'] else "  No FD available")

    # Save QC summary
    qc_df = pd.DataFrame(all_qc)
    qc_df.to_csv(args.output_dir / 'qc_summary.tsv', sep='\t', index=False)
    print(f"\nQC summary saved to: {args.output_dir / 'qc_summary.tsv'}")


if __name__ == '__main__':
    main()
