#!/usr/bin/env python3
"""
Session-level Seed-Based Connectivity Analysis Backend

Computes voxelwise seed-to-brain connectivity for multiple seeds and atlases.
Supports both coordinate-based spherical seeds and atlas-based ROI seeds.

Features:
- Loads seed definitions from config
- Extracts seed ROI timeseries (sphere or atlas-based)
- Computes whole-brain seed-to-voxel correlations
- High-pass/low-pass filtering and confound regression
- Fisher z-transform normalization
- Output: Z-scored connectivity maps, statistics, and seed timeseries

Usage:
    python seed_based_connectivity_backend.py \\
        --bold fmriprep/sub-033/ses-01/func/sub-033_ses-01_bold.nii.gz \\
        --confounds fmriprep/sub-033/ses-01/func/sub-033_ses-01_confounds.tsv \\
        --output results/seed_based/DiFuMo256/Motor_Cortex/sub-033_ses-01/ \\
        --atlas DiFuMo256 \\
        --seed Motor_Cortex
"""

import argparse
import json
import logging
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

import nibabel as nib
import numpy as np
import pandas as pd
from scipy import stats
from nilearn import image, masking
from nilearn.maskers import NiftiMasker, NiftiLabelsMasker
from nilearn.signal import clean

warnings.filterwarnings('ignore', category=DeprecationWarning)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SeedConnectivityError(Exception):
    """Custom exception for seed connectivity errors."""
    pass


def load_config(config_path: Optional[str] = None) -> Dict:
    """
    Load connectivity configuration from YAML.
    
    Parameters
    ----------
    config_path : str, optional
        Path to connectivity_config.yaml. If None, searches relative to project root.
    
    Returns
    -------
    dict
        Configuration dictionary with atlases, seeds, preprocessing params, etc.
    """
    import yaml
    
    if config_path is None:
        # Search for config relative to project root
        search_paths = [
            Path.cwd() / ".github" / "connectivity_config.yaml",
            Path.cwd() / "connectivity_config.yaml",
        ]
        
        # Try relative to this script
        script_dir = Path(__file__).parent.parent
        search_paths.insert(0, script_dir / ".github" / "connectivity_config.yaml")
        
        for path in search_paths:
            if path.exists():
                config_path = str(path)
                break
        else:
            raise SeedConnectivityError(
                f"Could not find connectivity_config.yaml. Searched in:\n" +
                "\n".join(str(p) for p in search_paths)
            )
    
    config_path = Path(config_path)
    if not config_path.exists():
        raise SeedConnectivityError(f"Config file not found: {config_path}")
    
    logger.info(f"Loading config from: {config_path}")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    return config


def get_seed_definition(
    config: Dict,
    atlas_name: str,
    seed_name: str
) -> Dict:
    """
    Get seed definition from config with validation.
    
    Parameters
    ----------
    config : dict
        Configuration dictionary
    atlas_name : str
        Name of atlas (e.g., 'DiFuMo256')
    seed_name : str
        Name of seed (e.g., 'Motor_Cortex')
    
    Returns
    -------
    dict
        Seed definition with coordinates, radius, etc.
    
    Raises
    ------
    SeedConnectivityError
        If seed or atlas not found, or invalid combination
    """
    # Validate atlas exists
    if atlas_name not in config.get('atlases', {}):
        available = ', '.join(config.get('atlases', {}).keys())
        raise SeedConnectivityError(
            f"Atlas '{atlas_name}' not found. Available: {available}"
        )
    
    # Validate seed exists
    if seed_name not in config.get('seeds', {}):
        available = ', '.join(config.get('seeds', {}).keys())
        raise SeedConnectivityError(
            f"Seed '{seed_name}' not found. Available: {available}"
        )
    
    seed_def = config['seeds'][seed_name]
    
    # Check if this seed is valid for this atlas
    valid_atlases = seed_def.get('valid_atlases', [])
    if atlas_name not in valid_atlases:
        raise SeedConnectivityError(
            f"Seed '{seed_name}' not valid for atlas '{atlas_name}'. "
            f"Valid atlases: {', '.join(valid_atlases)}"
        )
    
    return seed_def


def create_spherical_mask(
    center_coords: np.ndarray,
    radius_mm: float,
    affine: np.ndarray,
    shape: Tuple[int, int, int]
) -> nib.Nifti1Image:
    """
    Create a binary spherical mask around a center coordinate.
    
    Parameters
    ----------
    center_coords : ndarray
        (3,) center coordinate in MNI space (mm)
    radius_mm : float
        Radius of sphere (mm)
    affine : ndarray
        (4, 4) affine matrix from NIfTI image
    shape : tuple
        (x, y, z) shape of output mask
    
    Returns
    -------
    nib.Nifti1Image
        Binary mask image
    """
    mask_data = np.zeros(shape, dtype=np.uint8)
    
    # Compute voxel coordinates
    affine_inv = np.linalg.inv(affine)
    center_voxel = affine_inv[:3, :3] @ center_coords + affine_inv[:3, 3]
    center_voxel = np.round(center_voxel).astype(int)
    
    # Generate sphere in voxel space
    for x in range(shape[0]):
        for y in range(shape[1]):
            for z in range(shape[2]):
                # Distance in voxel space
                voxel_dist = np.linalg.norm(
                    affine[:3, :3] @ np.array([x - center_voxel[0],
                                                 y - center_voxel[1],
                                                 z - center_voxel[2]])
                )
                if voxel_dist <= radius_mm:
                    mask_data[x, y, z] = 1
    
    mask_img = nib.Nifti1Image(mask_data.astype(np.float32), affine)
    return mask_img


def extract_seed_timeseries(
    bold_file: str,
    confounds_file: str,
    seed_mask: nib.Nifti1Image,
    tr: float = 0.8,
    high_pass: float = 0.01,
    low_pass: float = 0.1,
    smoothing_fwhm: float = 6.0
) -> Tuple[np.ndarray, Dict]:
    """
    Extract mean timeseries from seed region.
    
    Parameters
    ----------
    bold_file : str
        Path to preprocessed BOLD NIfTI file
    confounds_file : str
        Path to confounds TSV file
    seed_mask : nib.Nifti1Image
        Binary mask of seed region
    tr : float
        Repetition time (seconds)
    high_pass : float
        High-pass filter cutoff (Hz)
    low_pass : float
        Low-pass filter cutoff (Hz)
    smoothing_fwhm : float
        Spatial smoothing FWHM (mm)
    
    Returns
    -------
    seed_ts : ndarray
        (n_volumes,) extracted and cleaned seed timeseries
    stats_dict : dict
        Statistics: n_voxels, mean_ts, std_ts
    """
    logger.info(f"Extracting seed timeseries from {bold_file}")
    
    # Load confounds
    try:
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='utf-8')
    except UnicodeDecodeError:
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='latin-1')
    
    # Select confound columns (Friston 24-parameter model)
    confound_cols = [
        'trans_x', 'trans_y', 'trans_z',
        'rot_x', 'rot_y', 'rot_z',
        'trans_x_derivative1', 'trans_y_derivative1', 'trans_z_derivative1',
        'rot_x_derivative1', 'rot_y_derivative1', 'rot_z_derivative1',
        'trans_x_power2', 'trans_y_power2', 'trans_z_power2',
        'rot_x_power2', 'rot_y_power2', 'rot_z_power2',
    ]
    
    # Use available columns
    confound_cols = [c for c in confound_cols if c in confounds.columns]
    
    # Add motion outliers if present
    outlier_cols = [c for c in confounds.columns if 'motion_outlier' in c]
    confound_cols.extend(outlier_cols)
    
    if confound_cols:
        confounds_array = confounds[confound_cols].values
    else:
        confounds_array = None
    
    # Create masker for seed region
    masker = NiftiMasker(
        mask_img=seed_mask,
        smoothing_fwhm=smoothing_fwhm,
        high_pass=high_pass,
        low_pass=low_pass,
        detrend=True,
        standardize=True,
        t_r=tr,
        verbose=0
    )
    
    # Extract timeseries from seed region (2D: n_voxels × n_volumes)
    seed_ts_2d = masker.fit_transform(bold_file, confounds=confounds_array)
    
    logger.info(f"  Seed region has {seed_ts_2d.shape[0]} voxels")
    
    # Average across voxels to get mean seed timeseries
    seed_ts = np.mean(seed_ts_2d, axis=0)
    
    # Verify no NaN/Inf
    if np.any(np.isnan(seed_ts)) or np.any(np.isinf(seed_ts)):
        raise SeedConnectivityError(
            "Seed timeseries contains NaN or Inf values"
        )
    
    if np.allclose(seed_ts, 0):
        raise SeedConnectivityError(
            "Seed timeseries is all zeros (possible mask outside brain)"
        )
    
    stats_dict = {
        'n_voxels': seed_ts_2d.shape[0],
        'mean_ts': float(np.mean(seed_ts)),
        'std_ts': float(np.std(seed_ts)),
        'min_ts': float(np.min(seed_ts)),
        'max_ts': float(np.max(seed_ts)),
    }
    
    return seed_ts, stats_dict


def compute_connectivity_map(
    bold_file: str,
    confounds_file: str,
    seed_ts: np.ndarray,
    brain_mask: nib.Nifti1Image,
    tr: float = 0.8,
    high_pass: float = 0.01,
    low_pass: float = 0.1,
    smoothing_fwhm: float = 6.0
) -> nib.Nifti1Image:
    """
    Compute whole-brain seed-to-voxel connectivity map.
    
    Parameters
    ----------
    bold_file : str
        Path to preprocessed BOLD NIfTI file
    confounds_file : str
        Path to confounds TSV file
    seed_ts : ndarray
        (n_volumes,) seed timeseries
    brain_mask : nib.Nifti1Image
        Brain mask for whole-brain analysis
    tr : float
        Repetition time (seconds)
    high_pass : float
        High-pass filter cutoff (Hz)
    low_pass : float
        Low-pass filter cutoff (Hz)
    smoothing_fwhm : float
        Spatial smoothing FWHM (mm)
    
    Returns
    -------
    nib.Nifti1Image
        Fisher z-transformed connectivity map
    """
    logger.info("Computing whole-brain connectivity map")
    
    # Load confounds
    try:
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='utf-8')
    except UnicodeDecodeError:
        confounds = pd.read_csv(confounds_file, sep='\t', encoding='latin-1')
    
    # Select confound columns
    confound_cols = [
        'trans_x', 'trans_y', 'trans_z',
        'rot_x', 'rot_y', 'rot_z',
        'trans_x_derivative1', 'trans_y_derivative1', 'trans_z_derivative1',
        'rot_x_derivative1', 'rot_y_derivative1', 'rot_z_derivative1',
        'trans_x_power2', 'trans_y_power2', 'trans_z_power2',
        'rot_x_power2', 'rot_y_power2', 'rot_z_power2',
    ]
    confound_cols = [c for c in confound_cols if c in confounds.columns]
    
    # Add motion outliers
    outlier_cols = [c for c in confounds.columns if 'motion_outlier' in c]
    confound_cols.extend(outlier_cols)
    
    if confound_cols:
        confounds_array = confounds[confound_cols].values
    else:
        confounds_array = None
    
    # Create whole-brain masker
    masker = NiftiMasker(
        mask_img=brain_mask,
        smoothing_fwhm=smoothing_fwhm,
        high_pass=high_pass,
        low_pass=low_pass,
        detrend=True,
        standardize=True,
        t_r=tr,
        verbose=0
    )
    
    # Extract whole-brain timeseries (n_voxels × n_volumes)
    brain_ts = masker.fit_transform(bold_file, confounds=confounds_array)
    
    logger.info(f"  Brain mask has {brain_ts.shape[0]} voxels")
    
    # Compute correlations
    n_voxels = brain_ts.shape[0]
    correlations = np.zeros(n_voxels, dtype=np.float32)
    
    logger.info("  Computing voxelwise correlations...")
    for i in range(n_voxels):
        if i % max(1, n_voxels // 10) == 0:
            logger.debug(f"    {i}/{n_voxels}")
        
        voxel_ts = brain_ts[:, i]
        
        # Skip if voxel has no variance
        if np.std(voxel_ts) < 1e-10:
            correlations[i] = np.nan
            continue
        
        # Compute Pearson correlation
        r = np.corrcoef(seed_ts, voxel_ts)[0, 1]
        correlations[i] = r
    
    # Handle NaN correlations
    nan_mask = np.isnan(correlations)
    correlations[nan_mask] = 0
    
    # Fisher z-transform: z = 0.5 * ln((1+r)/(1-r))
    # Clip to avoid log of negative numbers
    correlations = np.clip(correlations, -0.9999, 0.9999)
    z_transform = 0.5 * np.log((1 + correlations) / (1 - correlations + 1e-10))
    
    # Convert back to image
    z_map = masker.inverse_transform(z_transform)
    
    return z_map


def validate_output_path(output_path: Path) -> None:
    """
    Validate output path structure follows config rules.
    
    Parameters
    ----------
    output_path : Path
        Output directory path
    
    Raises
    ------
    SeedConnectivityError
        If path doesn't follow expected structure
    """
    # Expected structure: results/seed_based/{atlas}/{seed}/sub-{id}_ses-{session}/
    parts = output_path.parts
    
    try:
        # Find indices of key components
        seed_idx = parts.index('seed_based')
        assert len(parts) > seed_idx + 3, "Missing path components"
    except (ValueError, AssertionError):
        logger.warning(
            f"Output path doesn't follow expected structure: {output_path}. "
            "Expected: results/seed_based/{{atlas}}/{{seed}}/sub-XXX_ses-YY/"
        )


def compute_seed_connectivity(
    bold_file: str,
    confounds_file: str,
    output_dir: str,
    atlas_name: str = 'DiFuMo256',
    seed_name: str = 'Motor_Cortex',
    config_file: Optional[str] = None,
    tr: float = 0.8,
    high_pass: float = 0.01,
    low_pass: float = 0.1,
    smoothing_fwhm: float = 6.0
) -> Tuple[np.ndarray, Dict]:
    """
    Compute seed connectivity for single subject-session-seed combination.
    
    Main entry point for seed connectivity analysis.
    
    Parameters
    ----------
    bold_file : str
        Path to preprocessed BOLD NIfTI file
    confounds_file : str
        Path to confounds TSV file
    output_dir : str
        Output directory for results
    atlas_name : str
        Name of atlas (e.g., 'DiFuMo256')
    seed_name : str
        Name of seed (e.g., 'Motor_Cortex')
    config_file : str, optional
        Path to connectivity_config.yaml
    tr : float
        Repetition time (seconds)
    high_pass : float
        High-pass filter cutoff (Hz)
    low_pass : float
        Low-pass filter cutoff (Hz)
    smoothing_fwhm : float
        Spatial smoothing FWHM (mm)
    
    Returns
    -------
    z_map_data : ndarray
        3D Z-score connectivity map
    stats_dict : dict
        Summary statistics
    
    Raises
    ------
    SeedConnectivityError
        On validation or processing errors
    """
    logger.info("="*70)
    logger.info(f"SEED CONNECTIVITY ANALYSIS")
    logger.info(f"Atlas: {atlas_name}, Seed: {seed_name}")
    logger.info("="*70)
    
    # Validate inputs
    bold_path = Path(bold_file)
    confounds_path = Path(confounds_file)
    output_path = Path(output_dir)
    
    if not bold_path.exists():
        raise SeedConnectivityError(f"BOLD file not found: {bold_file}")
    if not confounds_path.exists():
        raise SeedConnectivityError(f"Confounds file not found: {confounds_file}")
    
    # Load config
    config = load_config(config_file)
    
    # Get seed definition
    seed_def = get_seed_definition(config, atlas_name, seed_name)
    logger.info(f"Seed: {seed_def['region']}")
    logger.info(f"Description: {seed_def['description']}")
    
    # Load BOLD data to get affine and shape
    logger.info(f"Loading BOLD from: {bold_file}")
    bold_img = nib.load(bold_file)
    bold_data = bold_img.get_fdata()
    affine = bold_img.affine
    shape = bold_data.shape[:3]
    
    logger.info(f"BOLD shape: {shape}, {bold_data.shape[3]} volumes")
    
    # Validate parameters from config
    config_preproc = config.get('preprocessing', {})
    if tr != config_preproc.get('tr_s', tr):
        logger.warning(
            f"TR mismatch: using {tr}s (config has {config_preproc.get('tr_s')})"
        )
    
    # Create seed mask
    logger.info("Creating seed mask...")
    coords_mni = np.array(seed_def['coordinates_mni'])
    radius_mm = seed_def['radius_mm']
    
    seed_mask = create_spherical_mask(coords_mni, radius_mm, affine, shape)
    
    # Load brain mask
    logger.info("Loading brain mask...")
    try:
        from nilearn.datasets import load_mni152_brain_mask
        brain_mask = load_mni152_brain_mask(resolution=2)
        # Resample to BOLD space if needed
        brain_mask = image.resample_to_img(brain_mask, bold_img)
    except Exception as e:
        logger.warning(f"Could not load MNI brain mask: {e}")
        logger.info("Creating brain mask from BOLD data...")
        brain_mask_data = (bold_data.mean(axis=3) > 0).astype(np.float32)
        brain_mask = nib.Nifti1Image(brain_mask_data, affine)
    
    # Extract seed timeseries
    seed_ts, seed_stats = extract_seed_timeseries(
        str(bold_path), str(confounds_path), seed_mask,
        tr=tr, high_pass=high_pass, low_pass=low_pass,
        smoothing_fwhm=smoothing_fwhm
    )
    
    # Compute connectivity map
    z_map = compute_connectivity_map(
        str(bold_path), str(confounds_path), seed_ts, brain_mask,
        tr=tr, high_pass=high_pass, low_pass=low_pass,
        smoothing_fwhm=smoothing_fwhm
    )
    
    # Get z-map data
    z_map_data = z_map.get_fdata()
    
    # Verify z-map
    z_data_finite = z_map_data[np.isfinite(z_map_data)]
    if len(z_data_finite) < 100:
        raise SeedConnectivityError("Too few finite voxels in z-map")
    
    logger.info(f"Z-map statistics:")
    logger.info(f"  Mean: {z_data_finite.mean():.4f}")
    logger.info(f"  Std: {z_data_finite.std():.4f}")
    logger.info(f"  Min: {z_data_finite.min():.4f}")
    logger.info(f"  Max: {z_data_finite.max():.4f}")
    
    # Create output directory
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Save z-map
    z_map_file = output_path / f"{seed_name}_zmap.nii.gz"
    nib.save(z_map, str(z_map_file))
    logger.info(f"Saved z-map: {z_map_file}")
    
    # Save seed mask
    seed_mask_file = output_path / f"{seed_name}_mask.nii.gz"
    nib.save(seed_mask, str(seed_mask_file))
    
    # Save seed timeseries
    seed_ts_file = output_path / f"{seed_name}_timeseries.csv"
    seed_ts_df = pd.DataFrame({'timeseries': seed_ts})
    seed_ts_df.to_csv(seed_ts_file, index=False)
    logger.info(f"Saved seed timeseries: {seed_ts_file}")
    
    # Compile statistics
    stats_dict = {
        'seed_name': seed_name,
        'atlas_name': atlas_name,
        'seed_definition': {
            'region': seed_def['region'],
            'coordinates_mni': coords_mni.tolist(),
            'radius_mm': radius_mm,
        },
        'seed_timeseries_stats': seed_stats,
        'z_map_stats': {
            'mean': float(z_data_finite.mean()),
            'std': float(z_data_finite.std()),
            'min': float(z_data_finite.min()),
            'max': float(z_data_finite.max()),
            'median': float(np.median(z_data_finite)),
        },
        'preprocessing': {
            'tr_s': tr,
            'high_pass_hz': high_pass,
            'low_pass_hz': low_pass,
            'smoothing_fwhm_mm': smoothing_fwhm,
        },
        'files': {
            'z_map': str(z_map_file.relative_to(output_path.parent.parent.parent)),
            'mask': str(seed_mask_file.relative_to(output_path.parent.parent.parent)),
            'timeseries': str(seed_ts_file.relative_to(output_path.parent.parent.parent)),
        }
    }
    
    # Save statistics
    stats_file = output_path / f"{seed_name}_stats.json"
    with open(stats_file, 'w') as f:
        json.dump(stats_dict, f, indent=2)
    logger.info(f"Saved statistics: {stats_file}")
    
    logger.info("="*70)
    logger.info("SEED CONNECTIVITY ANALYSIS COMPLETE")
    logger.info("="*70)
    
    return z_map_data, stats_dict


def main():
    """Command-line interface."""
    parser = argparse.ArgumentParser(
        description="Session-level seed-based connectivity analysis"
    )
    
    parser.add_argument(
        '--bold', type=str, required=True,
        help='Path to preprocessed BOLD NIfTI file'
    )
    parser.add_argument(
        '--confounds', type=str, required=True,
        help='Path to confounds TSV file'
    )
    parser.add_argument(
        '--output', type=str, required=True,
        help='Output directory for results'
    )
    parser.add_argument(
        '--atlas', type=str, default='DiFuMo256',
        help='Atlas name (default: DiFuMo256)'
    )
    parser.add_argument(
        '--seed', type=str, default='Motor_Cortex',
        help='Seed name (default: Motor_Cortex)'
    )
    parser.add_argument(
        '--config', type=str, default=None,
        help='Path to connectivity_config.yaml'
    )
    parser.add_argument(
        '--tr', type=float, default=0.8,
        help='Repetition time in seconds (default: 0.8)'
    )
    parser.add_argument(
        '--high-pass', type=float, default=0.01,
        help='High-pass filter cutoff in Hz (default: 0.01)'
    )
    parser.add_argument(
        '--low-pass', type=float, default=0.1,
        help='Low-pass filter cutoff in Hz (default: 0.1)'
    )
    parser.add_argument(
        '--smoothing', type=float, default=6.0,
        help='Spatial smoothing FWHM in mm (default: 6.0)'
    )
    
    args = parser.parse_args()
    
    try:
        z_map, stats = compute_seed_connectivity(
            bold_file=args.bold,
            confounds_file=args.confounds,
            output_dir=args.output,
            atlas_name=args.atlas,
            seed_name=args.seed,
            config_file=args.config,
            tr=args.tr,
            high_pass=args.high_pass,
            low_pass=args.low_pass,
            smoothing_fwhm=args.smoothing
        )
        
        logger.info(f"\nResults saved to: {args.output}")
        return 0
        
    except SeedConnectivityError as e:
        logger.error(f"Seed connectivity error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    exit(main())
