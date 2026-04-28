#!/usr/bin/env python3
"""
Session-Level Network Connectivity Backend for DiFuMo 256 Atlas

Computes within-network and between-network correlations from fMRIPrep preprocessed
resting-state fMRI data using the DiFuMo 256 atlas.

Key Features:
- Extract DiFuMo 256 timeseries from preprocessed BOLD
- Apply confound regression (FD, DVARS, WM, CSF)
- High/low-pass filtering
- Compute within-network and between-network Pearson correlations
- Fisher z-transform for statistical inference
- Output: HDF5 correlation matrices + CSV summary statistics

Usage:
    python compute_network_connectivity.py \\
        --bold fmriprep/sub-033/ses-01/func/sub-033_ses-01_space-MNI152NLin2009cAsym_res-2_bold.nii.gz \\
        --confounds fmriprep/sub-033/ses-01/func/sub-033_ses-01_bold_confounds.tsv \\
        --output results/network_connectivity/sub-033_ses-01/ \\
        --atlas DiFuMo256 \\
        --tr 0.8 \\
        --high-pass 0.01 \\
        --low-pass 0.1 \\
        --smoothing 6.0

Dependencies:
    pip install nibabel nilearn numpy scipy pandas h5py
"""

import argparse
import json
import logging
import sys
import time
import warnings
from pathlib import Path

import h5py
import nibabel as nib
import numpy as np
import pandas as pd
from nilearn import datasets
from nilearn.image import resample_to_img
from nilearn.masking import apply_mask
from nilearn.signal import clean
from scipy.stats import pearsonr, zscore

warnings.filterwarnings('ignore')


# =============================================================================
# LOGGING SETUP
# =============================================================================

def setup_logging(output_dir):
    """Configure logging to file and console."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    log_file = output_dir / "compute_network_connectivity.log"
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    return logging.getLogger(__name__)


# =============================================================================
# ATLAS LOADING
# =============================================================================

def load_difumo_atlas(atlas_path=None):
    """
    Load DiFuMo 256 atlas.
    
    Parameters
    ----------
    atlas_path : str, optional
        Path to local DiFuMo atlas file. If None, downloads from nilearn.
    
    Returns
    -------
    atlas_img : nibabel.Nifti1Image
        4D atlas image (3D spatial coords + 256 components)
    """
    logger = logging.getLogger(__name__)
    
    if atlas_path and Path(atlas_path).exists():
        logger.info(f"Loading DiFuMo atlas from: {atlas_path}")
        atlas_img = nib.load(atlas_path)
    else:
        logger.info("Downloading DiFuMo 256 from nilearn...")
        atlas_data = datasets.fetch_atlas_difumo(dimension=256, resolution_mm=2)
        atlas_img = nib.load(atlas_data.maps)
    
    logger.info(f"  Atlas shape: {atlas_img.shape}")
    return atlas_img


def load_network_definitions(networks_json):
    """
    Load network definitions mapping ROI indices to networks.
    
    Parameters
    ----------
    networks_json : str
        Path to network definitions JSON file
    
    Returns
    -------
    networks : dict
        Maps network name to list of ROI indices
    roi_to_network : dict
        Maps ROI index to network name
    """
    logger = logging.getLogger(__name__)
    
    with open(networks_json, 'r') as f:
        data = json.load(f)
    
    networks = data.get('networks', {})
    logger.info(f"Loaded {len(networks)} networks from {networks_json}")
    
    # Create reverse mapping: ROI index -> network name
    roi_to_network = {}
    for network_name, roi_indices in networks.items():
        for roi_idx in roi_indices:
            roi_to_network[roi_idx] = network_name
    
    return networks, roi_to_network


# =============================================================================
# CONFOUND LOADING
# =============================================================================

def load_confounds(confounds_file, strategy='extended'):
    """
    Load confound regressors from fMRIPrep confounds TSV.
    
    Parameters
    ----------
    confounds_file : str
        Path to *_desc-confounds_timeseries.tsv
    strategy : str
        'basic' = 6 motion + FD + DVARS + CSF + WM
        'extended' = basic + motion derivatives
    
    Returns
    -------
    confounds : ndarray
        Confound regressors (n_volumes x n_confounds)
    confound_names : list
        Names of confound columns
    """
    logger = logging.getLogger(__name__)
    
    logger.info(f"Loading confounds from: {confounds_file}")
    df = pd.read_csv(confounds_file, sep='\t')
    
    # Core motion parameters (6 DoF)
    cols = [
        'trans_x', 'trans_y', 'trans_z',
        'rot_x', 'rot_y', 'rot_z'
    ]
    
    # Add framewise displacement if available
    if 'framewise_displacement' in df.columns:
        cols.append('framewise_displacement')
    elif 'FD' in df.columns:
        cols.append('FD')
    
    # Add DVARS if available
    if 'dvars' in df.columns:
        cols.append('dvars')
    elif 'DVARS' in df.columns:
        cols.append('DVARS')
    
    # Motion derivatives
    if strategy == 'extended':
        deriv_cols = [
            'trans_x_derivative1', 'trans_y_derivative1', 'trans_z_derivative1',
            'rot_x_derivative1', 'rot_y_derivative1', 'rot_z_derivative1'
        ]
        cols.extend([c for c in deriv_cols if c in df.columns])
    
    # CSF and white matter signals
    if 'csf' in df.columns:
        cols.append('csf')
    if 'white_matter' in df.columns:
        cols.append('white_matter')
    
    # Filter to available columns
    available_cols = [c for c in cols if c in df.columns]
    logger.info(f"  Using {len(available_cols)} confound regressors: {available_cols}")
    
    confounds = df[available_cols].values
    
    # Handle NaN (typically first row for derivatives)
    confounds = np.nan_to_num(confounds, nan=0.0)
    
    return confounds, available_cols


# =============================================================================
# TIMESERIES EXTRACTION
# =============================================================================

def extract_timeseries(bold_file, atlas_img, mask_img=None):
    """
    Extract ROI timeseries from BOLD data using atlas.
    
    Parameters
    ----------
    bold_file : str
        Path to preprocessed BOLD 4D NIfTI
    atlas_img : nibabel.Nifti1Image
        Atlas image - can be 3D (component labels) or 4D (probabilistic maps)
    mask_img : nibabel.Nifti1Image, optional
        Brain mask. If None, computes from atlas.
    
    Returns
    -------
    timeseries : ndarray
        ROI timeseries (n_volumes x 256)
    """
    logger = logging.getLogger(__name__)
    
    logger.info(f"Loading BOLD data: {bold_file}")
    bold_img = nib.load(bold_file)
    bold_data = bold_img.get_fdata()
    
    # Validate BOLD dimensions
    if len(bold_data.shape) != 4:
        raise ValueError(f"BOLD must be 4D, got {bold_data.shape}")
    
    logger.info(f"  BOLD shape: {bold_data.shape}")
    n_volumes = bold_data.shape[3]
    
    # Get atlas data
    atlas_data = atlas_img.get_fdata()
    
    # Handle both 3D (label) and 4D (probabilistic) atlases
    if len(atlas_data.shape) == 4:
        logger.info(f"  Atlas shape: {atlas_data.shape} (probabilistic maps)")
        # Atlas is 4D: extract components as separate 3D volumes
        atlas_is_4d = True
    elif len(atlas_data.shape) == 3:
        logger.info(f"  Atlas shape: {atlas_data.shape} (labeled map)")
        atlas_is_4d = False
    else:
        raise ValueError(f"Atlas must be 3D or 4D, got {atlas_data.shape}")
    
    # Resample atlas to BOLD space if necessary
    if atlas_data.shape[:3] != bold_data.shape[:3]:
        logger.info("Resampling atlas to BOLD space...")
        atlas_img = resample_to_img(atlas_img, bold_img)
        atlas_data = atlas_img.get_fdata()
    
    # Extract timeseries for each component
    logger.info("Extracting timeseries from 256 ROIs...")
    
    # Reshape BOLD to (spatial_voxels, timepoints)
    bold_shape = bold_data.shape[:3]
    bold_2d = bold_data.reshape(-1, n_volumes)  # (spatial_voxels, timepoints)
    
    timeseries = np.zeros((n_volumes, 256))
    
    if atlas_is_4d:
        # For 4D probabilistic atlas, use each 3D volume as a weight map
        for roi_idx in range(256):
            weight_map = atlas_data[:, :, :, roi_idx]
            weight_flat = weight_map.ravel()
            
            if weight_flat.sum() == 0:
                logger.warning(f"  ROI {roi_idx}: No voxels found, using zeros")
                timeseries[:, roi_idx] = 0
            else:
                # Weighted average timeseries
                timeseries[:, roi_idx] = (bold_2d * weight_flat[:, np.newaxis]).sum(axis=0) / weight_flat.sum()
    else:
        # For 3D labeled atlas
        atlas_flat = atlas_data.ravel()
        for roi_idx in range(1, 257):  # Component labels are 1-256
            roi_mask_flat = (atlas_flat == roi_idx)
            
            if roi_mask_flat.sum() == 0:
                logger.warning(f"  ROI {roi_idx}: No voxels found, using zeros")
                timeseries[:, roi_idx - 1] = 0
            else:
                # Extract mean timeseries for this ROI
                roi_data = bold_2d[roi_mask_flat, :]  # (n_voxels_in_roi, timepoints)
                timeseries[:, roi_idx - 1] = roi_data.mean(axis=0)
    
    return timeseries


# =============================================================================
# SIGNAL PREPROCESSING
# =============================================================================

def preprocess_timeseries(timeseries, confounds, tr=0.8, high_pass=0.01, low_pass=0.1):
    """
    Clean timeseries: confound regression, filtering, normalization.
    
    Parameters
    ----------
    timeseries : ndarray
        ROI timeseries (n_volumes x n_rois)
    confounds : ndarray
        Confound regressors (n_volumes x n_confounds)
    tr : float
        Repetition time in seconds
    high_pass : float
        High-pass filter cutoff in Hz
    low_pass : float
        Low-pass filter cutoff in Hz
    
    Returns
    -------
    cleaned : ndarray
        Preprocessed timeseries (n_volumes x n_rois)
    """
    logger = logging.getLogger(__name__)
    
    logger.info("Preprocessing timeseries...")
    logger.info(f"  Confound regression: {confounds.shape[1]} regressors")
    logger.info(f"  High-pass filter: {high_pass} Hz")
    logger.info(f"  Low-pass filter: {low_pass} Hz")
    
    # Use nilearn.signal.clean for confound regression and filtering
    cleaned = clean(
        timeseries,
        confounds=confounds,
        detrend=True,
        standardize='zscore_sample',
        t_r=tr,
        high_pass=high_pass,
        low_pass=low_pass
    )
    
    # Additional normalization (zscore)
    cleaned = zscore(cleaned, axis=0)
    
    logger.info(f"  Output shape: {cleaned.shape}")
    logger.info(f"  Mean: {cleaned.mean():.6f}, Std: {cleaned.std():.6f}")
    
    return cleaned


# =============================================================================
# CORRELATION COMPUTATION
# =============================================================================

def compute_correlation_matrix(timeseries, demean=True, normalize=True):
    """
    Compute Pearson correlation matrix between ROIs.
    
    Parameters
    ----------
    timeseries : ndarray
        Preprocessed timeseries (n_volumes x n_rois)
    demean : bool
        Whether to demean before correlation (should be done in preprocessing)
    normalize : bool
        Whether to normalize columns
    
    Returns
    -------
    correlation_matrix : ndarray
        Correlation matrix (256 x 256)
    """
    logger = logging.getLogger(__name__)
    
    logger.info("Computing correlation matrix...")
    
    n_volumes, n_rois = timeseries.shape
    correlation_matrix = np.zeros((n_rois, n_rois))
    
    # Compute pairwise Pearson correlations
    for i in range(n_rois):
        for j in range(i, n_rois):
            # Compute correlation
            r, _ = pearsonr(timeseries[:, i], timeseries[:, j])
            
            # Check for NaN
            if np.isnan(r):
                logger.warning(f"NaN correlation for ROI {i}-{j}, setting to 0")
                r = 0.0
            
            # Ensure value is in [-1, 1]
            r = np.clip(r, -1.0, 1.0)
            
            correlation_matrix[i, j] = r
            correlation_matrix[j, i] = r
    
    logger.info(f"  Correlation matrix shape: {correlation_matrix.shape}")
    logger.info(f"  Min: {correlation_matrix.min():.4f}, Max: {correlation_matrix.max():.4f}")
    logger.info(f"  Mean: {correlation_matrix.mean():.4f}, Std: {correlation_matrix.std():.4f}")
    
    return correlation_matrix


def fisher_z_transform(r):
    """Apply Fisher z-transformation to correlation coefficient."""
    return np.arctanh(np.clip(r, -0.9999, 0.9999))


def compute_network_statistics(correlation_matrix, roi_to_network):
    """
    Compute summary statistics for within- and between-network connectivity.
    
    Parameters
    ----------
    correlation_matrix : ndarray
        Correlation matrix (256 x 256)
    roi_to_network : dict
        Maps ROI index to network name
    
    Returns
    -------
    stats : dict
        Summary statistics including within/between network means
    """
    logger = logging.getLogger(__name__)
    
    logger.info("Computing network statistics...")
    
    # Initialize stats dictionary
    stats = {
        'n_rois': 256,
        'mean_correlation': float(np.mean(correlation_matrix)),
        'std_correlation': float(np.std(correlation_matrix)),
    }
    
    # Get unique networks
    networks = sorted(set(roi_to_network.values()))
    logger.info(f"  Found {len(networks)} networks")
    
    within_network_corrs = []
    between_network_corrs = []
    
    # Within-network correlations
    for network in networks:
        roi_indices = [i for i in roi_to_network.keys() if roi_to_network[i] == network]
        
        if len(roi_indices) < 2:
            continue
        
        # Get correlations between ROIs in same network
        corrs = []
        for i in range(len(roi_indices)):
            for j in range(i + 1, len(roi_indices)):
                idx_i = roi_indices[i]
                idx_j = roi_indices[j]
                corrs.append(correlation_matrix[idx_i, idx_j])
        
        if corrs:
            mean_corr = np.mean(corrs)
            stats[f'within_{network}_mean'] = float(mean_corr)
            stats[f'within_{network}_n_pairs'] = len(corrs)
            within_network_corrs.extend(corrs)
    
    # Between-network correlations
    for i, net1 in enumerate(networks):
        for net2 in networks[i+1:]:
            roi_indices_1 = [idx for idx in roi_to_network.keys() if roi_to_network[idx] == net1]
            roi_indices_2 = [idx for idx in roi_to_network.keys() if roi_to_network[idx] == net2]
            
            # Get correlations between ROIs in different networks
            corrs = []
            for idx_i in roi_indices_1:
                for idx_j in roi_indices_2:
                    corrs.append(correlation_matrix[idx_i, idx_j])
            
            if corrs:
                mean_corr = np.mean(corrs)
                pair_name = f"between_{net1}_{net2}"
                stats[pair_name + '_mean'] = float(mean_corr)
                stats[pair_name + '_n_pairs'] = len(corrs)
                between_network_corrs.extend(corrs)
    
    # Overall statistics
    if within_network_corrs:
        stats['within_network_mean'] = float(np.mean(within_network_corrs))
        stats['within_network_std'] = float(np.std(within_network_corrs))
    
    if between_network_corrs:
        stats['between_network_mean'] = float(np.mean(between_network_corrs))
        stats['between_network_std'] = float(np.std(between_network_corrs))
    
    logger.info(f"  Within-network mean: {stats.get('within_network_mean', 'N/A')}")
    logger.info(f"  Between-network mean: {stats.get('between_network_mean', 'N/A')}")
    
    return stats


# =============================================================================
# OUTPUT SAVING
# =============================================================================

def save_correlation_matrix_hdf5(output_dir, correlation_matrix, timeseries_cleaned):
    """
    Save correlation matrix and cleaned timeseries to HDF5.
    
    Parameters
    ----------
    output_dir : str
        Output directory
    correlation_matrix : ndarray
        Correlation matrix (256 x 256)
    timeseries_cleaned : ndarray
        Cleaned timeseries (n_volumes x 256)
    """
    logger = logging.getLogger(__name__)
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    hdf5_file = output_dir / 'correlation_matrix.h5'
    
    logger.info(f"Saving correlation matrix to: {hdf5_file}")
    
    with h5py.File(hdf5_file, 'w') as f:
        # Store correlation matrix
        f.create_dataset('correlation_matrix', data=correlation_matrix, compression='gzip')
        
        # Store cleaned timeseries for QC
        f.create_dataset('timeseries_cleaned', data=timeseries_cleaned, compression='gzip')
        
        # Store metadata
        f.attrs['n_rois'] = 256
        f.attrs['n_volumes'] = timeseries_cleaned.shape[0]
    
    logger.info(f"  Saved {correlation_matrix.shape} correlation matrix")


def save_network_statistics_csv(output_dir, stats, roi_to_network):
    """
    Save network statistics to CSV.
    
    Parameters
    ----------
    output_dir : str
        Output directory
    stats : dict
        Statistics dictionary
    roi_to_network : dict
        Maps ROI index to network name
    """
    logger = logging.getLogger(__name__)
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    csv_file = output_dir / 'correlation_stats.csv'
    
    logger.info(f"Saving statistics to: {csv_file}")
    
    # Convert stats to DataFrame
    stats_df = pd.DataFrame([stats])
    stats_df.to_csv(csv_file, index=False)
    
    logger.info(f"  Saved statistics for {len(stats)} fields")


def save_network_definitions(output_dir, networks, roi_to_network):
    """
    Save network definitions and ROI mappings to JSON.
    
    Parameters
    ----------
    output_dir : str
        Output directory
    networks : dict
        Network definitions
    roi_to_network : dict
        ROI to network mapping
    """
    logger = logging.getLogger(__name__)
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    json_file = output_dir / 'network_definitions.json'
    
    logger.info(f"Saving network definitions to: {json_file}")
    
    # Convert roi_to_network to have string keys for JSON
    roi_to_network_str = {str(k): v for k, v in roi_to_network.items()}
    
    definitions = {
        'networks': networks,
        'roi_to_network': roi_to_network_str,
        'n_rois': 256
    }
    
    with open(json_file, 'w') as f:
        json.dump(definitions, f, indent=2)
    
    logger.info(f"  Saved {len(networks)} networks")


# =============================================================================
# MAIN FUNCTION
# =============================================================================

def compute_network_connectivity(
    bold_file,
    confounds_file,
    output_dir,
    atlas='DiFuMo256',
    atlas_path=None,
    networks_json=None,
    tr=0.8,
    high_pass=0.01,
    low_pass=0.1,
    smoothing_fwhm=6.0
):
    """
    Compute within/between-network connectivity for single subject-session.
    
    Parameters
    ----------
    bold_file : str
        Path to fMRIPrep preprocessed BOLD 4D NIfTI
    confounds_file : str
        Path to fMRIPrep confounds TSV
    output_dir : str
        Output directory
    atlas : str
        Atlas name ('DiFuMo256')
    atlas_path : str, optional
        Path to local atlas file
    networks_json : str, optional
        Path to network definitions JSON
    tr : float
        Repetition time in seconds
    high_pass : float
        High-pass filter cutoff in Hz
    low_pass : float
        Low-pass filter cutoff in Hz
    smoothing_fwhm : float
        Smoothing kernel FWHM (for future use)
    
    Returns
    -------
    results : dict
        Results dictionary with:
        - 'correlation_matrix': (256, 256) array
        - 'stats': dict of summary statistics
        - 'output_dir': path to outputs
    """
    # Setup logging
    logger = setup_logging(output_dir)
    
    logger.info("=" * 80)
    logger.info("SESSION-LEVEL NETWORK CONNECTIVITY COMPUTATION")
    logger.info("=" * 80)
    logger.info(f"BOLD: {bold_file}")
    logger.info(f"Confounds: {confounds_file}")
    logger.info(f"Output: {output_dir}")
    logger.info(f"Atlas: {atlas}")
    logger.info(f"TR: {tr} s, High-pass: {high_pass} Hz, Low-pass: {low_pass} Hz")
    
    start_time = time.time()
    
    try:
        # Validate inputs
        if not Path(bold_file).exists():
            raise FileNotFoundError(f"BOLD file not found: {bold_file}")
        if not Path(confounds_file).exists():
            raise FileNotFoundError(f"Confounds file not found: {confounds_file}")
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Step 1: Load atlas
        logger.info("\n[1/6] Loading atlas...")
        t0 = time.time()
        atlas_img = load_difumo_atlas(atlas_path)
        logger.info(f"  Time: {time.time() - t0:.2f} s")
        
        # Step 2: Load network definitions
        logger.info("\n[2/6] Loading network definitions...")
        t0 = time.time()
        if networks_json is None:
            networks_json = '/home/clivewong/proj/longevity/atlases/difumo256_network_definitions.json'
        networks, roi_to_network = load_network_definitions(networks_json)
        logger.info(f"  Time: {time.time() - t0:.2f} s")
        
        # Step 3: Load confounds
        logger.info("\n[3/6] Loading confounds...")
        t0 = time.time()
        confounds, confound_names = load_confounds(confounds_file)
        logger.info(f"  Time: {time.time() - t0:.2f} s")
        
        # Step 4: Extract timeseries
        logger.info("\n[4/6] Extracting timeseries...")
        t0 = time.time()
        timeseries = extract_timeseries(bold_file, atlas_img)
        logger.info(f"  Time: {time.time() - t0:.2f} s")
        
        # Step 5: Preprocess timeseries
        logger.info("\n[5/6] Preprocessing timeseries...")
        t0 = time.time()
        timeseries_cleaned = preprocess_timeseries(
            timeseries, confounds,
            tr=tr, high_pass=high_pass, low_pass=low_pass
        )
        logger.info(f"  Time: {time.time() - t0:.2f} s")
        
        # Step 6: Compute correlations
        logger.info("\n[6/6] Computing correlations...")
        t0 = time.time()
        correlation_matrix = compute_correlation_matrix(timeseries_cleaned)
        stats = compute_network_statistics(correlation_matrix, roi_to_network)
        logger.info(f"  Time: {time.time() - t0:.2f} s")
        
        # Save outputs
        logger.info("\nSaving outputs...")
        save_correlation_matrix_hdf5(output_dir, correlation_matrix, timeseries_cleaned)
        save_network_statistics_csv(output_dir, stats, roi_to_network)
        save_network_definitions(output_dir, networks, roi_to_network)
        
        total_time = time.time() - start_time
        logger.info(f"\n{'=' * 80}")
        logger.info(f"COMPLETED SUCCESSFULLY in {total_time:.2f} s")
        logger.info(f"{'=' * 80}")
        
        results = {
            'correlation_matrix': correlation_matrix,
            'stats': stats,
            'output_dir': str(output_dir),
            'timeseries': timeseries_cleaned
        }
        
        return results
    
    except Exception as e:
        logger.error(f"ERROR: {e}", exc_info=True)
        raise


# =============================================================================
# COMMAND-LINE INTERFACE
# =============================================================================

def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description='Compute session-level network connectivity from fMRIPrep outputs'
    )
    
    parser.add_argument(
        '--bold',
        required=True,
        help='Path to fMRIPrep preprocessed BOLD 4D NIfTI'
    )
    parser.add_argument(
        '--confounds',
        required=True,
        help='Path to fMRIPrep confounds TSV'
    )
    parser.add_argument(
        '--output',
        required=True,
        help='Output directory'
    )
    parser.add_argument(
        '--atlas',
        default='DiFuMo256',
        help='Atlas name (default: DiFuMo256)'
    )
    parser.add_argument(
        '--atlas-path',
        default=None,
        help='Path to local atlas file (optional)'
    )
    parser.add_argument(
        '--networks-json',
        default=None,
        help='Path to network definitions JSON (optional)'
    )
    parser.add_argument(
        '--tr',
        type=float,
        default=0.8,
        help='Repetition time in seconds (default: 0.8)'
    )
    parser.add_argument(
        '--high-pass',
        type=float,
        default=0.01,
        help='High-pass filter cutoff in Hz (default: 0.01)'
    )
    parser.add_argument(
        '--low-pass',
        type=float,
        default=0.1,
        help='Low-pass filter cutoff in Hz (default: 0.1)'
    )
    parser.add_argument(
        '--smoothing',
        type=float,
        default=6.0,
        help='Smoothing kernel FWHM in mm (default: 6.0)'
    )
    
    args = parser.parse_args()
    
    # Run computation
    results = compute_network_connectivity(
        bold_file=args.bold,
        confounds_file=args.confounds,
        output_dir=args.output,
        atlas=args.atlas,
        atlas_path=args.atlas_path,
        networks_json=args.networks_json,
        tr=args.tr,
        high_pass=args.high_pass,
        low_pass=args.low_pass,
        smoothing_fwhm=args.smoothing
    )
    
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    print(f"Output directory: {results['output_dir']}")
    print(f"Correlation matrix shape: {results['correlation_matrix'].shape}")
    print(f"Within-network mean: {results['stats'].get('within_network_mean', 'N/A')}")
    print(f"Between-network mean: {results['stats'].get('between_network_mean', 'N/A')}")
    print("=" * 80)


if __name__ == '__main__':
    main()
