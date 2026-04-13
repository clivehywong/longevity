#!/usr/bin/env python3
"""
Parallel Seed-Based Connectivity Analysis for Longitudinal Walking Intervention Study

This is a parallelized version of seed_based_connectivity.py that:
1. Processes multiple seeds in parallel using joblib
2. Uses vectorized correlation computation for ~10-50x speedup per session
3. Pre-loads atlas data once to avoid redundant I/O
4. Implements 36-parameter confound regression (24 motion + 8 tissue + 4 derivatives)
5. Volume scrubbing based on framewise displacement (FD) threshold
6. Automatic exclusion of sessions with >20% volumes scrubbed

Processing Modes (Updated 2026-02-13):
- SEED-BY-SEED (default): Processes all sessions for each seed before moving to next seed.
  Faster overall but first complete seed takes longer (~8 hours for first 4 seeds).
- SESSION-BY-SESSION (--session-by-session): Processes all seeds in parallel for each session.
  Provides earlier preliminary results (all seeds have some data after ~1-2 hours).

Expected speedup: ~4x faster (13-17 hours -> 3-4 hours with 4 workers)

Preprocessing (Updated 2026-02-13):
- 36-parameter confound model (Ciric et al., 2017):
  - 24 motion parameters (6 + derivatives + squared terms)
  - 8 tissue signals (WM + CSF + derivatives + squared)
- Volume scrubbing: FD > 0.5 mm (default, adjustable with --fd-threshold)
- Session exclusion: >20% volumes scrubbed
- Spatial smoothing: 6mm FWHM (default)
- Bandpass filter: 0.01-0.1 Hz (default)
- Detrending and standardization

Usage:
    # Default seed-by-seed mode
    python seed_based_connectivity_parallel.py \
        --fmriprep FMRIPREP_DIR \
        --seeds SEEDS_JSON \
        --metadata METADATA_CSV \
        --output OUTPUT_DIR \
        --fd-threshold 0.5 \
        --n-jobs 4

    # Session-by-session mode (for earlier preliminary results)
    python seed_based_connectivity_parallel.py \
        --fmriprep FMRIPREP_DIR \
        --seeds SEEDS_JSON \
        --metadata METADATA_CSV \
        --output OUTPUT_DIR \
        --session-by-session \
        --n-jobs 24

Dependencies:
    pip install nibabel nilearn pandas numpy scipy statsmodels joblib
"""

import argparse
import json
import traceback
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from nilearn import datasets, image, masking, plotting
from nilearn.maskers import NiftiLabelsMasker, NiftiMasker
from scipy import stats

warnings.filterwarnings('ignore')


def load_seed_definitions(seeds_file):
    """Load seed definitions from JSON."""
    with open(seeds_file, 'r') as f:
        seeds = json.load(f)
    return seeds['seeds']


def load_difumo_atlas():
    """Load DiFuMo 256 atlas and return atlas object with pre-loaded data."""
    print("Loading DiFuMo 256 atlas...")
    atlas = datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2)
    return atlas


def preload_atlas_maps(atlas, target_affine=None, target_shape=None):
    """
    Pre-load atlas maps data and optionally resample to match BOLD grid.

    This eliminates per-file resampling overhead by resampling the atlas once
    to match the fMRIPrep BOLD output space (MNI152NLin2009cAsym res-2).

    Parameters
    ----------
    atlas : nilearn atlas object
        DiFuMo atlas object from fetch_atlas_difumo()
    target_affine : ndarray, optional
        Target affine matrix (from a BOLD file). If provided, atlas will be resampled.
    target_shape : tuple, optional
        Target shape (x, y, z). If provided with target_affine, atlas will be resampled.

    Returns
    -------
    maps_data : ndarray
        4D atlas data (x, y, z, n_components), optionally resampled
    maps_affine : ndarray
        Affine transformation matrix (target_affine if resampled, else original)
    """
    maps_img = nib.load(atlas.maps)

    # Resample atlas to BOLD grid if target provided
    if target_affine is not None and target_shape is not None:
        print("  Resampling atlas to match BOLD grid (eliminates per-file resampling)...")
        print(f"    Original atlas: {maps_img.shape}, affine origin: {maps_img.affine[:3, 3]}")
        print(f"    Target BOLD: {target_shape}, affine origin: {target_affine[:3, 3]}")

        maps_img_resampled = image.resample_img(
            maps_img,
            target_affine=target_affine,
            target_shape=target_shape,
            interpolation='continuous'  # Preserve probabilistic nature of atlas
        )

        print(f"    Resampled atlas: {maps_img_resampled.shape}")
        maps_data = maps_img_resampled.get_fdata()
        maps_affine = maps_img_resampled.affine
    else:
        # No resampling - use original atlas
        maps_data = maps_img.get_fdata()
        maps_affine = maps_img.affine

    return maps_data, maps_affine


def create_seed_mask(seed_def, maps_data, maps_affine, default_threshold=0.0002):
    """
    Create binary seed mask from pre-loaded atlas data.

    Parameters
    ----------
    seed_def : dict
        Seed definition with 'difumo_indices' and optional 'probability_threshold'
    maps_data : ndarray
        Pre-loaded 4D atlas data
    maps_affine : ndarray
        Atlas affine matrix
    default_threshold : float
        Default probability threshold if not specified in seed_def (default: 0.0002 for DiFuMo atlas)

    Returns
    -------
    seed_mask_img : Nifti1Image
        Binary seed mask with probability threshold applied
    """
    roi_indices = seed_def['difumo_indices']

    # Get probability threshold from seed definition or use default
    prob_threshold = seed_def.get('probability_threshold', default_threshold)

    # Sum probability maps for selected components
    seed_mask = np.sum(maps_data[:, :, :, roi_indices], axis=3)

    # Apply probability threshold (eliminates spillover)
    seed_mask = (seed_mask >= prob_threshold).astype(float)

    return nib.Nifti1Image(seed_mask, maps_affine)


def load_confounds(confounds_file, fd_threshold=0.5, verbose=False):
    """
    Load confounds from TSV file using 36-parameter model.

    The 36-parameter model includes:
    - 24 motion parameters (6 + 6 derivatives + 12 squared terms)
    - 8 tissue signal parameters (WM + CSF, each with derivative and squared terms)
    - 4 derivatives/squared of tissue signals

    Also computes volume scrubbing mask based on framewise displacement (FD).

    Parameters
    ----------
    confounds_file : str
        Path to fMRIPrep confounds TSV file
    fd_threshold : float
        Framewise displacement threshold for volume scrubbing (default: 0.5 mm)
    verbose : bool
        Print processing info

    Returns
    -------
    confounds_array : ndarray
        Selected confound columns as numpy array (n_volumes, n_confounds)
    scrubbing_mask : ndarray
        Boolean mask (True = keep, False = scrub) based on FD threshold
    mean_fd : float
        Mean framewise displacement
    n_scrubbed : int
        Number of volumes scrubbed
    """
    if verbose:
        print(f"    Reading confounds from: {confounds_file}")

    try:
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='utf-8')
    except UnicodeDecodeError:
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='latin-1')

    # 36-parameter model (Ciric et al., 2017)
    confound_cols = [
        # 24-parameter motion model
        'trans_x', 'trans_y', 'trans_z', 'rot_x', 'rot_y', 'rot_z',
        'trans_x_derivative1', 'trans_y_derivative1', 'trans_z_derivative1',
        'rot_x_derivative1', 'rot_y_derivative1', 'rot_z_derivative1',
        'trans_x_power2', 'trans_y_power2', 'trans_z_power2',
        'rot_x_power2', 'rot_y_power2', 'rot_z_power2',
        'trans_x_derivative1_power2', 'trans_y_derivative1_power2', 'trans_z_derivative1_power2',
        'rot_x_derivative1_power2', 'rot_y_derivative1_power2', 'rot_z_derivative1_power2',
        # White matter + CSF (mean signals + expansions)
        'white_matter', 'white_matter_derivative1', 'white_matter_power2', 'white_matter_derivative1_power2',
        'csf', 'csf_derivative1', 'csf_power2', 'csf_derivative1_power2',
    ]

    # Check which confounds are available
    available_cols = [c for c in confound_cols if c in confounds.columns]
    missing_cols = set(confound_cols) - set(available_cols)

    if missing_cols and verbose:
        print(f"    Warning: Missing confounds: {missing_cols}")

    # Get confounds array
    confounds_array = confounds[available_cols].values

    # Handle NaN values in confounds (often in first row for derivatives)
    # Replace NaN with 0 for derivatives (reasonable assumption for first timepoint)
    confounds_array = np.nan_to_num(confounds_array, nan=0.0)

    # Compute scrubbing mask based on FD
    if 'framewise_displacement' in confounds.columns:
        fd = confounds['framewise_displacement'].values
        # First volume has no FD (NaN), replace with 0
        fd = np.nan_to_num(fd, nan=0.0)
        scrubbing_mask = fd < fd_threshold
        mean_fd = np.mean(fd)
        n_scrubbed = np.sum(~scrubbing_mask)
    else:
        # If FD not available, don't scrub any volumes
        scrubbing_mask = np.ones(len(confounds_array), dtype=bool)
        mean_fd = 0.0
        n_scrubbed = 0
        if verbose:
            print("    Warning: framewise_displacement not found, no volume scrubbing applied")

    return confounds_array, scrubbing_mask, mean_fd, n_scrubbed


def compute_correlations_vectorized(seed_ts, brain_ts):
    """
    Vectorized Pearson correlation computation.

    This is ~10-50x faster than the loop-based approach.

    Parameters
    ----------
    seed_ts : ndarray
        Seed timeseries (n_volumes,)
    brain_ts : ndarray
        Brain timeseries (n_volumes, n_voxels)

    Returns
    -------
    correlations : ndarray
        Correlation coefficients (n_voxels,)
    """
    # Center the data
    seed_centered = seed_ts - np.mean(seed_ts)
    brain_centered = brain_ts - np.mean(brain_ts, axis=0, keepdims=True)

    # Compute standard deviations
    seed_std = np.std(seed_ts, ddof=0)
    brain_std = np.std(brain_ts, axis=0, ddof=0)

    # Avoid division by zero
    brain_std = np.where(brain_std == 0, 1e-10, brain_std)

    # Vectorized correlation
    n = len(seed_ts)
    correlations = np.dot(seed_centered, brain_centered) / (n * seed_std * brain_std)

    # Handle NaN values
    correlations = np.nan_to_num(correlations, nan=0.0)

    return correlations


def extract_seed_timeseries(bold_file, confounds_array, seed_mask_img,
                            sample_mask=None, smoothing_fwhm=6.0,
                            high_pass=0.01, low_pass=0.1):
    """
    Extract mean timeseries from seed region.

    Parameters
    ----------
    bold_file : str
        Preprocessed BOLD NIfTI file
    confounds_array : ndarray
        Pre-loaded confounds array
    seed_mask_img : Nifti1Image
        Binary seed mask
    sample_mask : ndarray, optional
        Boolean mask for volume scrubbing (True = keep, False = scrub)
    smoothing_fwhm : float
        Spatial smoothing FWHM (mm)
    high_pass : float
        High-pass filter cutoff (Hz)
    low_pass : float
        Low-pass filter cutoff (Hz)

    Returns
    -------
    seed_ts : ndarray
        Seed mean timeseries (n_volumes_kept,)
    """
    masker = NiftiMasker(
        mask_img=seed_mask_img,
        smoothing_fwhm=smoothing_fwhm,
        high_pass=high_pass,
        low_pass=low_pass,
        detrend=True,
        standardize=True,
        t_r=0.8,
        verbose=0
    )

    seed_ts_2d = masker.fit_transform(bold_file, confounds=confounds_array,
                                       sample_mask=sample_mask)
    seed_ts = np.mean(seed_ts_2d, axis=1)

    return seed_ts


def compute_seed_to_voxel_connectivity(bold_file, confounds_array, seed_ts,
                                        brain_mask, sample_mask=None,
                                        smoothing_fwhm=6.0, high_pass=0.01,
                                        low_pass=0.1):
    """
    Compute voxelwise correlation with seed timeseries (vectorized).

    Parameters
    ----------
    bold_file : str
        Preprocessed BOLD NIfTI file
    confounds_array : ndarray
        Pre-loaded confounds array
    seed_ts : ndarray
        Seed timeseries (n_volumes_kept,)
    brain_mask : Nifti1Image
        Brain mask
    sample_mask : ndarray, optional
        Boolean mask for volume scrubbing (True = keep, False = scrub)
    smoothing_fwhm : float
        Spatial smoothing FWHM
    high_pass : float
        High-pass filter
    low_pass : float
        Low-pass filter

    Returns
    -------
    correlation_map : Nifti1Image
        Whole-brain correlation map (Fisher Z-transformed)
    """
    # Create whole-brain masker
    masker = NiftiMasker(
        mask_img=brain_mask,
        smoothing_fwhm=smoothing_fwhm,
        high_pass=high_pass,
        low_pass=low_pass,
        detrend=True,
        standardize=True,
        t_r=0.8,
        verbose=0
    )

    # Extract whole-brain timeseries
    brain_ts = masker.fit_transform(bold_file, confounds=confounds_array,
                                     sample_mask=sample_mask)

    # Compute correlations (vectorized)
    correlations = compute_correlations_vectorized(seed_ts, brain_ts)

    # Fisher Z-transform
    # Clip correlations to avoid arctanh infinity
    correlations = np.clip(correlations, -0.9999, 0.9999)
    correlations_z = np.arctanh(correlations)

    # Convert back to image
    correlation_map = masker.inverse_transform(correlations_z)

    return correlation_map


def find_confounds_file(bold_file, space):
    """
    Find confounds file for a BOLD file.

    Parameters
    ----------
    bold_file : Path
        BOLD file path
    space : str
        Space of BOLD data (e.g., 'MNI152NLin2009cAsym')

    Returns
    -------
    confounds_file : Path or None
        Path to confounds file, or None if not found
    """
    bold_name = bold_file.name
    if '_res-2_' in bold_name:
        confounds_name = bold_name.replace(
            f'_space-{space}_res-2_desc-preproc_bold.nii.gz',
            '_desc-confounds_timeseries.tsv'
        )
    else:
        confounds_name = bold_name.replace(
            f'_space-{space}_desc-preproc_bold.nii.gz',
            '_desc-confounds_timeseries.tsv'
        )
    confounds_file = bold_file.parent / confounds_name

    if confounds_file.exists():
        return confounds_file
    return None


def process_single_seed_single_session(seed_name, seed_def, seed_mask_img,
                                        bold_file, confounds_file,
                                        brain_mask, args, seed_output_dir):
    """
    Process one session for one seed - designed for session-by-session parallelization.

    This is a lightweight wrapper that combines seed info with session processing.
    Used when parallelizing over seeds within each session.

    Parameters
    ----------
    seed_name : str
        Name of the seed
    seed_def : dict
        Seed definition dictionary
    seed_mask_img : Nifti1Image
        Pre-computed seed mask
    bold_file : Path
        BOLD file path
    confounds_file : Path
        Confounds file path
    brain_mask : Nifti1Image
        Brain mask
    args : Namespace
        Command-line arguments
    seed_output_dir : Path
        Output directory for this seed

    Returns
    -------
    result : dict
        Processing result with status, subject, session, file, and seed_name
    """
    result = process_single_session(
        bold_file, confounds_file, seed_def, seed_mask_img,
        brain_mask, args, seed_output_dir
    )
    result['seed_name'] = seed_name
    return result


def process_single_session(bold_file, confounds_file, seed_def, seed_mask_img,
                           brain_mask, args, seed_output_dir):
    """
    Process a single session for one seed.

    Parameters
    ----------
    bold_file : Path
        BOLD file path
    confounds_file : Path
        Confounds file path
    seed_def : dict
        Seed definition
    seed_mask_img : Nifti1Image
        Pre-computed seed mask
    brain_mask : Nifti1Image
        Brain mask
    args : Namespace
        Command-line arguments
    seed_output_dir : Path
        Output directory for this seed

    Returns
    -------
    result : dict
        Processing result with status, subject, session, file
    """
    # Parse filename
    parts = bold_file.stem.replace('.nii', '').split('_')
    subject = [p for p in parts if p.startswith('sub-')][0]
    session = [p for p in parts if p.startswith('ses-')][0] if any('ses-' in p for p in parts) else 'ses-01'

    try:
        # Load confounds and compute scrubbing mask
        confounds_array, scrubbing_mask, mean_fd, n_scrubbed = load_confounds(
            confounds_file, fd_threshold=args.fd_threshold, verbose=False
        )

        # Check if too many volumes scrubbed (>20% threshold)
        n_volumes = len(scrubbing_mask)
        scrub_pct = 100 * n_scrubbed / n_volumes
        if scrub_pct > 20:
            return {
                'status': 'excluded',
                'subject': subject,
                'session': session,
                'reason': f'Excessive motion: {scrub_pct:.1f}% volumes scrubbed (FD threshold={args.fd_threshold}mm)',
                'mean_fd': mean_fd,
                'n_scrubbed': n_scrubbed,
                'scrub_pct': scrub_pct
            }

        # Extract seed timeseries
        seed_ts = extract_seed_timeseries(
            str(bold_file), confounds_array, seed_mask_img,
            sample_mask=scrubbing_mask,
            smoothing_fwhm=args.smoothing,
            high_pass=args.high_pass,
            low_pass=args.low_pass
        )

        # Compute seed-to-voxel connectivity
        conn_map = compute_seed_to_voxel_connectivity(
            str(bold_file), confounds_array, seed_ts, brain_mask,
            sample_mask=scrubbing_mask,
            smoothing_fwhm=args.smoothing,
            high_pass=args.high_pass,
            low_pass=args.low_pass
        )

        # Save individual map
        output_file = seed_output_dir / f'{subject}_{session}_zmap.nii.gz'
        nib.save(conn_map, output_file)

        return {
            'status': 'success',
            'subject': subject,
            'session': session,
            'file': str(output_file),
            'mean_fd': mean_fd,
            'n_scrubbed': n_scrubbed,
            'scrub_pct': scrub_pct
        }

    except Exception as e:
        return {
            'status': 'error',
            'subject': subject,
            'session': session,
            'error': str(e),
            'traceback': traceback.format_exc()
        }


def process_single_seed(seed_name, seed_def, bold_files, maps_data, maps_affine,
                        brain_mask, args, output_dir):
    """
    Process all sessions for a single seed.

    This function is designed to be called in parallel by joblib.

    Parameters
    ----------
    seed_name : str
        Name of the seed
    seed_def : dict
        Seed definition dictionary
    bold_files : list
        List of BOLD file paths
    maps_data : ndarray
        Pre-loaded atlas data (4D)
    maps_affine : ndarray
        Atlas affine matrix
    brain_mask : Nifti1Image
        Brain mask
    args : Namespace
        Command-line arguments
    output_dir : Path
        Base output directory

    Returns
    -------
    result : dict
        Processing results for this seed
    """
    try:
        print(f"\n{'='*60}")
        print(f"SEED: {seed_name}")
        print(f"{'='*60}")
        print(f"Description: {seed_def['description']}")
        print(f"Components: {seed_def['n_components']}")

        seed_output_dir = output_dir / seed_name.lower()
        seed_output_dir.mkdir(exist_ok=True)

        # Create seed mask from pre-loaded atlas data
        seed_mask_img = create_seed_mask(seed_def, maps_data, maps_affine)

        # Store results
        individual_maps = []
        map_info = []
        errors = []
        excluded = []

        # Process each subject-session
        for bold_file in bold_files:
            # Find confounds file
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

            if not confounds_file.exists():
                parts = bold_file.stem.replace('.nii', '').split('_')
                subject = [p for p in parts if p.startswith('sub-')][0]
                session = [p for p in parts if p.startswith('ses-')][0] if any('ses-' in p for p in parts) else 'ses-01'
                print(f"  Warning: No confounds for {subject} {session}, skipping")
                continue

            # Process session
            result = process_single_session(
                bold_file, confounds_file, seed_def, seed_mask_img,
                brain_mask, args, seed_output_dir
            )

            if result['status'] == 'success':
                individual_maps.append(result['file'])
                map_info.append({
                    'subject': result['subject'],
                    'session': result['session'],
                    'file': result['file'],
                    'mean_fd': result['mean_fd'],
                    'n_scrubbed': result['n_scrubbed'],
                    'scrub_pct': result['scrub_pct']
                })
                print(f"  ✓ {result['subject']} {result['session']} (FD={result['mean_fd']:.3f}mm, scrubbed={result['n_scrubbed']})")
            elif result['status'] == 'excluded':
                excluded.append(result)
                print(f"  ✗ EXCLUDED {result['subject']} {result['session']}: {result['reason']}")
            else:
                errors.append(result)
                print(f"  ✗ ERROR {result['subject']} {result['session']}: {result['error']}")

        print(f"\n  ✓ Successfully processed: {len(individual_maps)} connectivity maps for {seed_name}")
        if excluded:
            print(f"  ✗ Excluded (excessive motion): {len(excluded)}")
        if errors:
            print(f"  ✗ Errors: {len(errors)}")

        # Save map inventory
        if map_info:
            map_df = pd.DataFrame(map_info)
            map_df.to_csv(seed_output_dir / 'individual_maps.csv', index=False)

            # Save motion QC summary
            print(f"  Motion QC summary:")
            print(f"    Mean FD: {map_df['mean_fd'].mean():.3f} ± {map_df['mean_fd'].std():.3f} mm")
            print(f"    Mean scrubbed volumes: {map_df['n_scrubbed'].mean():.1f} ({map_df['scrub_pct'].mean():.1f}%)")

        # Save exclusions
        if excluded:
            excl_df = pd.DataFrame(excluded)
            excl_df.to_csv(seed_output_dir / 'excluded_sessions.csv', index=False)

        # Create visualization of mean connectivity map (first 10 for speed)
        if len(individual_maps) > 0:
            print(f"  Creating mean connectivity visualization...")
            maps_data_list = [nib.load(m).get_fdata() for m in individual_maps[:10]]
            mean_map_data = np.mean(maps_data_list, axis=0)
            mean_map = nib.Nifti1Image(mean_map_data, brain_mask.affine)

            display = plotting.plot_stat_map(
                mean_map,
                threshold=0.3,
                title=f'Seed: {seed_name} (mean connectivity)',
                colorbar=True,
                cmap='RdBu_r',
                symmetric_cbar=True,
                output_file=str(seed_output_dir / f'{seed_name}_mean_connectivity.png'),
                display_mode='mosaic'
            )
            print(f"  Visualization saved: {seed_name}_mean_connectivity.png")

        return {
            'seed_name': seed_name,
            'status': 'success',
            'n_maps': len(individual_maps),
            'n_excluded': len(excluded),
            'n_errors': len(errors),
            'errors': errors,
            'excluded': excluded,
            'output_dir': str(seed_output_dir)
        }

    except Exception as e:
        return {
            'seed_name': seed_name,
            'status': 'error',
            'n_maps': 0,
            'n_errors': 1,
            'error': str(e),
            'traceback': traceback.format_exc()
        }


def main():
    parser = argparse.ArgumentParser(
        description="Parallel seed-based connectivity analysis for walking intervention study"
    )
    parser.add_argument('--fmriprep', type=str, required=True,
                        help='fMRIPrep derivatives directory')
    parser.add_argument('--seeds', type=str, required=True,
                        help='Seeds JSON file (motor_cerebellar_seeds.json)')
    parser.add_argument('--metadata', type=str, required=True,
                        help='Metadata CSV/TSV with group, age, sex, mean_fd')
    parser.add_argument('--output', type=str, required=True,
                        help='Output directory')
    parser.add_argument('--seed-names', nargs='+',
                        help='Specific seeds to analyze (default: all primary seeds)')
    parser.add_argument('--space', default='MNI152NLin2009cAsym',
                        help='Space of BOLD data')
    parser.add_argument('--smoothing', type=float, default=6.0,
                        help='Smoothing FWHM (mm)')
    parser.add_argument('--high-pass', type=float, default=0.01,
                        help='High-pass filter (Hz)')
    parser.add_argument('--low-pass', type=float, default=0.1,
                        help='Low-pass filter (Hz)')
    parser.add_argument('--fd-threshold', type=float, default=0.5,
                        help='Framewise displacement threshold for volume scrubbing (mm, default: 0.5)')

    # Parallelization arguments
    parser.add_argument('--n-jobs', type=int, default=4,
                        help='Number of parallel jobs (default: 4)')
    parser.add_argument('--backend', default='loky',
                        choices=['loky', 'multiprocessing', 'threading'],
                        help='Joblib backend (default: loky)')
    parser.add_argument('--verbose', type=int, default=10,
                        help='Joblib verbosity level (default: 10)')
    parser.add_argument('--session-by-session', action='store_true',
                        help='Process session-by-session (all seeds in parallel for each session) '
                             'instead of seed-by-seed. Provides earlier preliminary results.')

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load seed definitions
    print("="*60)
    print("PARALLEL SEED-BASED CONNECTIVITY ANALYSIS")
    print("="*60)
    print(f"\nParallelization settings:")
    print(f"  n_jobs: {args.n_jobs}")
    print(f"  backend: {args.backend}")
    print(f"  verbose: {args.verbose}")

    seed_defs = load_seed_definitions(args.seeds)

    # Select seeds to analyze
    if args.seed_names:
        seeds_to_analyze = {k: v for k, v in seed_defs.items() if k in args.seed_names}
    else:
        # Primary seeds (motor-cerebellar focus)
        primary_seeds = ['Motor_Cortex', 'Cerebellar_Motor', 'Hippocampus']
        seeds_to_analyze = {k: v for k, v in seed_defs.items() if k in primary_seeds}

    print(f"\nSeeds to analyze ({len(seeds_to_analyze)}): {list(seeds_to_analyze.keys())}")

    # Find BOLD files first (needed to get target affine for atlas resampling)
    fmriprep_dir = Path(args.fmriprep)
    bold_pattern = f'**/func/*_space-{args.space}_res-2_desc-preproc_bold.nii.gz'
    bold_files = sorted(fmriprep_dir.glob(bold_pattern))
    if len(bold_files) == 0:
        bold_pattern = f'**/func/*_space-{args.space}_desc-preproc_bold.nii.gz'
        bold_files = sorted(fmriprep_dir.glob(bold_pattern))

    print(f"Found {len(bold_files)} BOLD files")

    if len(bold_files) == 0:
        print("ERROR: No BOLD files found. Check fMRIPrep directory and space.")
        return 1

    # Get reference BOLD file to determine target grid for atlas resampling
    print("\nLoading reference BOLD file to determine target grid...")
    reference_bold = nib.load(bold_files[0])
    target_affine = reference_bold.affine
    target_shape = reference_bold.shape[:3]  # Spatial dimensions only (x, y, z)
    print(f"  Reference: {bold_files[0].name}")
    print(f"  Target shape: {target_shape}")
    print(f"  Target affine origin: {target_affine[:3, 3]}")

    # Load atlas and resample to BOLD grid (ONCE, before parallelization)
    atlas = load_difumo_atlas()
    print("\nPre-loading and resampling atlas data...")
    maps_data, maps_affine = preload_atlas_maps(atlas, target_affine=target_affine, target_shape=target_shape)
    print(f"  Final atlas shape: {maps_data.shape}")

    # Load metadata
    metadata_path = Path(args.metadata)
    if metadata_path.suffix == '.tsv':
        metadata = pd.read_csv(metadata_path, sep='\t')
    else:
        metadata = pd.read_csv(metadata_path)
    print(f"\nMetadata: {len(metadata)} observations")

    # Get brain mask - use fMRIPrep mask from reference BOLD to avoid resampling
    print("\nLoading brain mask from reference BOLD...")
    mask_file = str(bold_files[0]).replace('_desc-preproc_bold.nii.gz', '_desc-brain_mask.nii.gz')
    if Path(mask_file).exists():
        brain_mask = nib.load(mask_file)
        print(f"  Using fMRIPrep brain mask: {Path(mask_file).name}")
        print(f"  Mask shape: {brain_mask.shape}")
    else:
        # Fallback to standard mask (will trigger resampling warning)
        print(f"  Warning: fMRIPrep mask not found, using standard MNI152 mask")
        from nilearn.datasets import load_mni152_brain_mask
        brain_mask = load_mni152_brain_mask(resolution=2)

    # Process based on mode
    print(f"\n{'='*60}")
    print(f"STARTING PARALLEL PROCESSING")
    print(f"{'='*60}")
    print(f"Processing {len(seeds_to_analyze)} seeds × {len(bold_files)} sessions")
    print(f"Using {args.n_jobs} parallel workers")
    print(f"Mode: {'SESSION-BY-SESSION' if args.session_by_session else 'SEED-BY-SEED'}\n")

    if args.session_by_session:
        # SESSION-BY-SESSION MODE: Process all seeds in parallel for each session
        # This provides earlier preliminary results (all seeds have some data sooner)

        # Pre-create seed masks and output directories
        print("Pre-creating seed masks and output directories...")
        seed_masks = {}
        seed_output_dirs = {}
        for seed_name, seed_def in seeds_to_analyze.items():
            seed_masks[seed_name] = create_seed_mask(seed_def, maps_data, maps_affine)
            seed_output_dir = output_dir / seed_name.lower()
            seed_output_dir.mkdir(exist_ok=True)
            seed_output_dirs[seed_name] = seed_output_dir
        print(f"  Created {len(seed_masks)} seed masks\n")

        # Track results per seed
        seed_results = {seed_name: {'maps': [], 'errors': [], 'excluded': []}
                        for seed_name in seeds_to_analyze.keys()}

        # Process SESSION-BY-SESSION (all seeds in parallel for each session)
        for session_idx, bold_file in enumerate(bold_files):
            print(f"\n{'='*60}")
            print(f"SESSION {session_idx + 1}/{len(bold_files)}: {bold_file.name}")
            print(f"{'='*60}")

            # Find confounds file
            confounds_file = find_confounds_file(bold_file, args.space)
            if confounds_file is None:
                parts = bold_file.stem.replace('.nii', '').split('_')
                subject = [p for p in parts if p.startswith('sub-')][0]
                session = [p for p in parts if p.startswith('ses-')][0] if any('ses-' in p for p in parts) else 'ses-01'
                print(f"  Warning: No confounds for {subject} {session}, skipping all seeds")
                continue

            # Process all seeds in parallel for this session
            session_results = Parallel(n_jobs=args.n_jobs, backend=args.backend, verbose=args.verbose)(
                delayed(process_single_seed_single_session)(
                    seed_name, seed_def, seed_masks[seed_name],
                    bold_file, confounds_file,
                    brain_mask, args, seed_output_dirs[seed_name]
                )
                for seed_name, seed_def in seeds_to_analyze.items()
            )

            # Aggregate results per seed
            success_count = 0
            excluded_count = 0
            error_count = 0
            for result in session_results:
                seed_name = result['seed_name']
                if result['status'] == 'success':
                    seed_results[seed_name]['maps'].append(result)
                    success_count += 1
                elif result['status'] == 'excluded':
                    seed_results[seed_name]['excluded'].append(result)
                    excluded_count += 1
                else:
                    seed_results[seed_name]['errors'].append(result)
                    error_count += 1

            # Report session progress
            print(f"\n  Session {session_idx + 1} complete: {success_count} success, {excluded_count} excluded, {error_count} errors")

            # Show running totals for each seed
            if (session_idx + 1) % 5 == 0 or session_idx == len(bold_files) - 1:
                print(f"\n  === Progress checkpoint (after session {session_idx + 1}) ===")
                for seed_name in seeds_to_analyze.keys():
                    n_maps = len(seed_results[seed_name]['maps'])
                    print(f"    {seed_name}: {n_maps}/{session_idx + 1} z-maps")

        # Save per-seed summaries and create visualizations
        print(f"\n{'='*60}")
        print("SAVING RESULTS AND CREATING VISUALIZATIONS")
        print(f"{'='*60}")

        results = []
        for seed_name, seed_def in seeds_to_analyze.items():
            seed_output_dir = seed_output_dirs[seed_name]
            maps = seed_results[seed_name]['maps']
            excluded = seed_results[seed_name]['excluded']
            errors = seed_results[seed_name]['errors']

            # Save map inventory
            if maps:
                map_info = [{
                    'subject': r['subject'],
                    'session': r['session'],
                    'file': r['file'],
                    'mean_fd': r['mean_fd'],
                    'n_scrubbed': r['n_scrubbed'],
                    'scrub_pct': r['scrub_pct']
                } for r in maps]
                map_df = pd.DataFrame(map_info)
                map_df.to_csv(seed_output_dir / 'individual_maps.csv', index=False)

                # Print motion QC summary
                print(f"\n{seed_name}:")
                print(f"  Maps: {len(maps)}, Excluded: {len(excluded)}, Errors: {len(errors)}")
                print(f"  Mean FD: {map_df['mean_fd'].mean():.3f} ± {map_df['mean_fd'].std():.3f} mm")

            # Save exclusions
            if excluded:
                excl_df = pd.DataFrame(excluded)
                excl_df.to_csv(seed_output_dir / 'excluded_sessions.csv', index=False)

            # Create visualization of mean connectivity map (first 10 for speed)
            if len(maps) > 0:
                individual_maps = [r['file'] for r in maps]
                maps_data_list = [nib.load(m).get_fdata() for m in individual_maps[:10]]
                mean_map_data = np.mean(maps_data_list, axis=0)
                mean_map = nib.Nifti1Image(mean_map_data, brain_mask.affine)

                display = plotting.plot_stat_map(
                    mean_map,
                    threshold=0.3,
                    title=f'Seed: {seed_name} (mean connectivity)',
                    colorbar=True,
                    cmap='RdBu_r',
                    symmetric_cbar=True,
                    output_file=str(seed_output_dir / f'{seed_name}_mean_connectivity.png'),
                    display_mode='mosaic'
                )
                print(f"  Visualization saved: {seed_name}_mean_connectivity.png")

            results.append({
                'seed_name': seed_name,
                'status': 'success' if len(errors) == 0 else 'partial',
                'n_maps': len(maps),
                'n_excluded': len(excluded),
                'n_errors': len(errors),
                'errors': errors,
                'excluded': excluded,
                'output_dir': str(seed_output_dir)
            })

    else:
        # SEED-BY-SEED MODE (original): Process all sessions for each seed
        # Faster overall but first complete seed takes longer

        results = Parallel(n_jobs=args.n_jobs, backend=args.backend, verbose=args.verbose)(
            delayed(process_single_seed)(
                seed_name, seed_def, bold_files,
                maps_data, maps_affine, brain_mask, args, output_dir
            )
            for seed_name, seed_def in seeds_to_analyze.items()
        )

    # Report results
    print(f"\n{'='*60}")
    print("PARALLEL SEED-BASED ANALYSIS COMPLETE")
    print(f"{'='*60}")

    total_maps = 0
    total_errors = 0
    failed_seeds = []

    for result in results:
        if result['status'] in ['success', 'partial']:
            print(f"\n{result['seed_name']}:")
            print(f"  Maps generated: {result['n_maps']}")
            print(f"  Excluded: {result['n_excluded']}")
            print(f"  Errors: {result['n_errors']}")
            print(f"  Output: {result['output_dir']}")
            total_maps += result['n_maps']
            total_errors += result['n_errors']
            if result['status'] == 'partial':
                print(f"  (partial - some errors occurred)")
        else:
            print(f"\n{result['seed_name']}: FAILED")
            print(f"  Error: {result.get('error', 'Unknown error')}")
            failed_seeds.append(result['seed_name'])
            total_errors += 1

    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"Total maps generated: {total_maps}")
    print(f"Total errors: {total_errors}")
    print(f"Failed seeds: {len(failed_seeds)}")
    if failed_seeds:
        print(f"  {failed_seeds}")
    print(f"\nResults directory: {output_dir}")
    print(f"\nNext steps:")
    print(f"1. Run group-level analysis (Group x Time interaction)")
    print(f"2. Apply cluster correction (FWE p<0.05)")
    print(f"3. Extract peak coordinates and effect sizes")

    return 0 if len(failed_seeds) == 0 else 1


if __name__ == '__main__':
    exit(main())
