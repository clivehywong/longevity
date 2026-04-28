#!/usr/bin/env python3
"""
Local Measures: fALFF and ReHo for Longitudinal Walking Intervention Study

Computes voxelwise local measures from fMRIPrep preprocessed BOLD data:
- fALFF (fractional Amplitude of Low-Frequency Fluctuations)
- ReHo (Regional Homogeneity via Kendall's W)

Usage (CLI):
    python compute_local_measures.py \
        --fmriprep /path/to/fmriprep \
        --output results/local_measures \
        --measures fALFF ReHo \
        --subjects sub-033 sub-034

Usage (Python):
    from compute_local_measures import compute_local_measures
    
    results = compute_local_measures(
        bold_file='fmriprep/sub-033/ses-01/func/sub-033_ses-01_bold.nii.gz',
        output_dir='results/local_measures/sub-033_ses-01/',
        tr=0.8,
        high_pass=0.01,
        low_pass=0.1
    )

Dependencies:
    pip install nibabel nilearn numpy scipy pandas pyyaml
"""

import argparse
import logging
import sys
import time
import warnings
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import nibabel as nib
import numpy as np
import pandas as pd
from scipy import signal
from scipy.stats import rankdata
from nilearn.masking import apply_mask, unmask
from nilearn.image import clean_img, load_img, math_img

# Add script directory to path for config imports
sys.path.insert(0, str(Path(__file__).parent))

try:
    from config_loader import ConnectivityConfig
except ImportError:
    ConnectivityConfig = None

warnings.filterwarnings('ignore')

# Configure logging
logging.basicConfig(
    format='%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class LocalMeasuresError(Exception):
    """Base exception for local measures computation."""
    pass


class ValidationError(LocalMeasuresError):
    """Raised when validation of input data fails."""
    pass


class ComputationError(LocalMeasuresError):
    """Raised when computation fails."""
    pass


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
    
    Raises
    ------
    ValidationError
        If file cannot be read or required columns are missing
    """
    try:
        df = pd.read_csv(confounds_file, sep='\t')
    except Exception as e:
        raise ValidationError(f"Cannot read confounds file {confounds_file}: {e}")

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
    if not available:
        logger.warning(f"No confound columns found in {confounds_file}")
        confounds = np.zeros((len(df), 1))
    else:
        confounds = df[available].values

    # Fill NaN (first row for derivatives)
    confounds = np.nan_to_num(confounds, nan=0.0)

    return confounds


def validate_bold_data(bold_data: np.ndarray, bold_file: str) -> None:
    """
    Validate BOLD data integrity.
    
    Parameters
    ----------
    bold_data : ndarray
        4D BOLD data (x, y, z, time)
    bold_file : str
        Path to BOLD file (for error messages)
    
    Raises
    ------
    ValidationError
        If data fails validation
    """
    if bold_data.ndim != 4:
        raise ValidationError(
            f"BOLD data has {bold_data.ndim} dimensions, expected 4D"
        )
    
    if np.any(np.isnan(bold_data)):
        raise ValidationError(
            f"BOLD data contains NaN values: {np.sum(np.isnan(bold_data))} voxels affected"
        )
    
    if np.any(np.isinf(bold_data)):
        raise ValidationError(
            f"BOLD data contains Inf values: {np.sum(np.isinf(bold_data))} voxels affected"
        )
    
    if bold_data.std() < 1e-6:
        raise ValidationError(
            "BOLD data has zero variance (no signal)"
        )


def compute_falff(bold_file: str, mask_file: str, confounds_file: str,
                  tr: float = 0.8, low_freq: float = 0.01, high_freq: float = 0.1,
                  confound_strategy: str = 'basic') -> Tuple[nib.Nifti1Image, Dict]:
    """
    Compute fractional Amplitude of Low-Frequency Fluctuations (fALFF).

    fALFF = power in low-frequency band (0.01-0.1 Hz) / power in full frequency range (up to Nyquist)

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
    confound_strategy : str
        'basic' or 'extended' confound regression

    Returns
    -------
    falff_img : Nifti1Image
        Whole-brain fALFF map (values in [0, 1])
    stats : dict
        Computation statistics (mean, std, range, etc.)
    
    Raises
    ------
    ValidationError
        If input data is invalid
    ComputationError
        If computation fails
    """
    logger.info(f"Computing fALFF (band: {low_freq}-{high_freq} Hz, TR={tr}s)...")
    start_time = time.time()

    try:
        # Load confounds
        confounds = load_confounds(confounds_file, strategy=confound_strategy)
        logger.debug(f"Loaded {confounds.shape} confound matrix")

        # Load images
        bold_img = load_img(bold_file)
        mask_img = load_img(mask_file)
        
        logger.debug(f"BOLD shape: {bold_img.shape}, Mask shape: {mask_img.shape}")

        # Validate BOLD data
        bold_data_raw = bold_img.get_fdata()
        validate_bold_data(bold_data_raw, bold_file)

        # Clean image: regress confounds and detrend (no bandpass yet)
        cleaned_img = clean_img(
            bold_img,
            confounds=confounds,
            detrend=True,
            standardize=False,
            t_r=tr,
            mask_img=mask_img
        )
        
        cleaned_data = cleaned_img.get_fdata()
        if np.any(~np.isfinite(cleaned_data)):
            raise ComputationError("Cleaned data contains non-finite values")

        # Extract masked data
        data_2d = apply_mask(cleaned_img, mask_img)  # (n_volumes, n_voxels)
        n_volumes, n_voxels = data_2d.shape
        logger.debug(f"Masked data: {n_volumes} volumes, {n_voxels} voxels")

        # Compute power spectral density for each voxel
        fs = 1.0 / tr  # Sampling frequency
        nyquist = fs / 2.0
        logger.debug(f"Sampling frequency: {fs} Hz, Nyquist: {nyquist:.3f} Hz")

        # Validate frequency parameters
        if low_freq < 0 or high_freq < 0:
            raise ValidationError("Frequency parameters must be non-negative")
        if high_freq >= nyquist:
            raise ValidationError(
                f"High-pass frequency ({high_freq} Hz) must be less than Nyquist ({nyquist:.3f} Hz)"
            )
        if low_freq >= high_freq:
            raise ValidationError(
                f"Low-pass frequency ({low_freq} Hz) must be less than high-pass ({high_freq} Hz)"
            )

        # Use Welch's method for PSD estimation
        nperseg = min(n_volumes, 256)
        freqs, psd = signal.welch(data_2d, fs=fs, nperseg=nperseg, axis=0)
        logger.debug(f"PSD computed: {len(freqs)} frequency bins")

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
        
        logger.debug(f"fALFF: {valid.sum()}/{n_voxels} valid voxels")

        # Validate output
        if not np.all(np.isfinite(falff_values[valid])):
            raise ComputationError("fALFF computation produced non-finite values")

        # Convert back to image
        falff_img = unmask(falff_values, mask_img)
        
        # Compute statistics
        masked_falff = falff_values[valid]
        stats = {
            'n_valid_voxels': int(valid.sum()),
            'mean': float(np.mean(masked_falff)),
            'std': float(np.std(masked_falff)),
            'median': float(np.median(masked_falff)),
            'min': float(np.min(masked_falff)),
            'max': float(np.max(masked_falff)),
            'computation_time_sec': time.time() - start_time
        }
        
        logger.info(f"fALFF complete: mean={stats['mean']:.4f}, std={stats['std']:.4f}, time={stats['computation_time_sec']:.1f}s")

        return falff_img, stats

    except (ValidationError, ComputationError):
        raise
    except Exception as e:
        raise ComputationError(f"fALFF computation failed: {e}")


def compute_reho(bold_file: str, mask_file: str, confounds_file: str,
                 tr: float = 0.8, neighborhood: str = 'faces_edges_corners',
                 low_freq: float = 0.01, high_freq: float = 0.1,
                 confound_strategy: str = 'basic') -> Tuple[nib.Nifti1Image, Dict]:
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
        High-pass filter cutoff (Hz)
    high_freq : float
        Low-pass filter cutoff (Hz)
    confound_strategy : str
        'basic' or 'extended' confound regression

    Returns
    -------
    reho_img : Nifti1Image
        Whole-brain ReHo map (values in [0, 1])
    stats : dict
        Computation statistics (mean, std, range, etc.)
    
    Raises
    ------
    ValidationError
        If input data is invalid
    ComputationError
        If computation fails
    """
    logger.info(f"Computing ReHo (neighborhood={neighborhood})...")
    start_time = time.time()

    try:
        # Load confounds
        confounds = load_confounds(confounds_file, strategy=confound_strategy)
        logger.debug(f"Loaded {confounds.shape} confound matrix")

        # Clean image: regress confounds, detrend, and bandpass filter
        bold_img = load_img(bold_file)
        mask_img = load_img(mask_file)
        
        # Validate BOLD data
        bold_data_raw = bold_img.get_fdata()
        validate_bold_data(bold_data_raw, bold_file)

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
        
        if np.any(~np.isfinite(data_4d)):
            raise ComputationError("Filtered data contains non-finite values")
        
        mask_data = mask_img.get_fdata().astype(bool)
        nx, ny, nz, nt = data_4d.shape
        logger.debug(f"Data shape: {data_4d.shape}, {mask_data.sum()} brain voxels")

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
        
        logger.debug(f"Using {len(offsets)} neighbors")

        # Compute ReHo for each voxel in mask
        reho_data = np.zeros((nx, ny, nz))
        mask_coords = np.argwhere(mask_data)
        total_voxels = len(mask_coords)
        
        logger.info(f"Computing ReHo for {total_voxels} voxels...")

        for idx, (x, y, z) in enumerate(mask_coords):
            if (idx + 1) % max(1, total_voxels // 10) == 0:
                elapsed = time.time() - start_time
                rate = (idx + 1) / elapsed
                eta = (total_voxels - idx) / rate if rate > 0 else 0
                logger.debug(f"  Progress: {idx + 1}/{total_voxels} ({100*idx/total_voxels:.1f}%), ETA: {eta:.1f}s")

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
        
        # Compute statistics
        masked_reho = reho_data[mask_data]
        masked_reho = masked_reho[masked_reho > 0]  # Exclude uncomputed voxels
        
        stats = {
            'n_valid_voxels': int(len(masked_reho)),
            'mean': float(np.mean(masked_reho)) if len(masked_reho) > 0 else 0.0,
            'std': float(np.std(masked_reho)) if len(masked_reho) > 0 else 0.0,
            'median': float(np.median(masked_reho)) if len(masked_reho) > 0 else 0.0,
            'min': float(np.min(masked_reho)) if len(masked_reho) > 0 else 0.0,
            'max': float(np.max(masked_reho)) if len(masked_reho) > 0 else 0.0,
            'computation_time_sec': time.time() - start_time
        }
        
        logger.info(f"ReHo complete: mean={stats['mean']:.4f}, std={stats['std']:.4f}, time={stats['computation_time_sec']:.1f}s")

        return reho_img, stats

    except (ValidationError, ComputationError):
        raise
    except Exception as e:
        raise ComputationError(f"ReHo computation failed: {e}")


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
            logger.warning(f"No mask for {subject} {session}, skipping")
            continue
        if not confounds_file.exists():
            logger.warning(f"No confounds for {subject} {session}, skipping")
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
        description="Compute local measures (fALFF, ReHo) from fMRIPrep preprocessed data",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compute both fALFF and ReHo for all subjects
  python compute_local_measures.py --fmriprep fmriprep/ --output results/local_measures/
  
  # Process specific subjects
  python compute_local_measures.py --fmriprep fmriprep/ --output results/local_measures/ \\
      --subjects sub-033 sub-034
  
  # Only compute fALFF
  python compute_local_measures.py --fmriprep fmriprep/ --output results/local_measures/ \\
      --measures fALFF
        """
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
    parser.add_argument('--log-level', default='INFO',
                        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                        help='Logging level (default: INFO)')
    parser.add_argument('--config', type=str,
                        help='Path to connectivity_config.yaml (auto-discovered if not provided)')

    args = parser.parse_args()
    
    # Configure logging
    logger.setLevel(getattr(logging, args.log_level))

    # Load config if available
    config = None
    if ConnectivityConfig:
        try:
            config = ConnectivityConfig(args.config)
            lm_config = config.get_local_measures()
            if lm_config:
                logger.info("Loaded local_measures configuration from connectivity_config.yaml")
                # Use config values if not overridden on CLI
                if 'fALFF' in lm_config and 'parameters' in lm_config['fALFF']:
                    params = lm_config['fALFF']['parameters']
                    args.low_freq = params.get('low_freq_hz', args.low_freq)
                    args.high_freq = params.get('high_freq_hz', args.high_freq)
                if 'ReHo' in lm_config and 'parameters' in lm_config['ReHo']:
                    args.neighborhood = lm_config['ReHo']['parameters'].get('neighborhood_type', args.neighborhood)
        except Exception as e:
            logger.warning(f"Could not load config: {e}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("=" * 70)
    logger.info("LOCAL MEASURES COMPUTATION")
    logger.info("=" * 70)
    logger.info(f"Measures: {', '.join(args.measures)}")
    logger.info(f"TR: {args.tr}s")
    logger.info(f"Frequency band: {args.low_freq}-{args.high_freq} Hz")
    logger.info(f"ReHo neighborhood: {args.neighborhood}")
    logger.info(f"Output directory: {output_dir}")

    # Find BOLD files
    try:
        file_list = find_bold_files(
            args.fmriprep, space=args.space, res=args.res,
            subjects=args.subjects, sessions=args.sessions
        )
    except Exception as e:
        logger.error(f"Error finding BOLD files: {e}")
        return 1

    logger.info(f"Found {len(file_list)} BOLD files to process")

    if len(file_list) == 0:
        logger.error("No BOLD files found. Check fMRIPrep directory.")
        return 1

    # Summary table
    summary_rows = []
    failed_count = 0

    # Process each file
    for i, finfo in enumerate(file_list):
        subject = finfo['subject']
        session = finfo['session']
        logger.info("")
        logger.info("=" * 70)
        logger.info(f"[{i+1}/{len(file_list)}] {subject} {session}")
        logger.info("=" * 70)

        row = {'subject': subject, 'session': session}

        # Compute fALFF
        if 'fALFF' in args.measures:
            try:
                falff_img, falff_stats = compute_falff(
                    finfo['bold'], finfo['mask'], finfo['confounds'],
                    tr=args.tr, low_freq=args.low_freq, high_freq=args.high_freq
                )
                falff_file = output_dir / f'{subject}_{session}_fALFF.nii.gz'
                nib.save(falff_img, falff_file)
                logger.info(f"Saved: {falff_file.name}")

                # Add stats to row
                row.update({
                    f'fALFF_{k}': v for k, v in falff_stats.items()
                })

            except (ValidationError, ComputationError) as e:
                logger.error(f"fALFF computation failed: {e}")
                row['fALFF_error'] = str(e)
                failed_count += 1
            except Exception as e:
                logger.exception(f"Unexpected error in fALFF: {e}")
                row['fALFF_error'] = str(e)
                failed_count += 1

        # Compute ReHo
        if 'ReHo' in args.measures:
            try:
                reho_img, reho_stats = compute_reho(
                    finfo['bold'], finfo['mask'], finfo['confounds'],
                    tr=args.tr, neighborhood=args.neighborhood,
                    low_freq=args.low_freq, high_freq=args.high_freq
                )
                reho_file = output_dir / f'{subject}_{session}_ReHo.nii.gz'
                nib.save(reho_img, reho_file)
                logger.info(f"Saved: {reho_file.name}")

                # Add stats to row
                row.update({
                    f'ReHo_{k}': v for k, v in reho_stats.items()
                })

            except (ValidationError, ComputationError) as e:
                logger.error(f"ReHo computation failed: {e}")
                row['ReHo_error'] = str(e)
                failed_count += 1
            except Exception as e:
                logger.exception(f"Unexpected error in ReHo: {e}")
                row['ReHo_error'] = str(e)
                failed_count += 1

        summary_rows.append(row)

    # Save summary
    summary_df = pd.DataFrame(summary_rows)
    summary_file = output_dir / 'local_measures_summary.csv'
    summary_df.to_csv(summary_file, index=False)

    logger.info("")
    logger.info("=" * 70)
    logger.info("LOCAL MEASURES COMPLETE")
    logger.info("=" * 70)
    logger.info(f"Processed: {len(file_list)} files")
    logger.info(f"Successful: {len(file_list) - failed_count}")
    logger.info(f"Failed: {failed_count}")
    logger.info(f"Summary: {summary_file}")

    if 'fALFF_mean' in summary_df.columns:
        valid_falff = summary_df['fALFF_mean'].dropna()
        logger.info(f"\nfALFF statistics (n={len(valid_falff)}):")
        logger.info(f"  Mean: {valid_falff.mean():.4f}")
        logger.info(f"  Std: {valid_falff.std():.4f}")
        logger.info(f"  Range: [{valid_falff.min():.4f}, {valid_falff.max():.4f}]")

    if 'ReHo_mean' in summary_df.columns:
        valid_reho = summary_df['ReHo_mean'].dropna()
        logger.info(f"\nReHo statistics (n={len(valid_reho)}):")
        logger.info(f"  Mean: {valid_reho.mean():.4f}")
        logger.info(f"  Std: {valid_reho.std():.4f}")
        logger.info(f"  Range: [{valid_reho.min():.4f}, {valid_reho.max():.4f}]")

    return 0 if failed_count == 0 else 1


if __name__ == '__main__':
    exit(main())
