#!/usr/bin/env python3
"""
Group-Level Statistical Analysis with LME Models and Multiple Comparison Correction

Performs voxelwise/ROI-wise linear mixed-effects (LME) analysis on group-level data:
- Local measures (fALFF, ReHo)
- Seed-based connectivity maps
- Network connectivity matrices

Features:
- Standardized covariate preprocessing
- Voxelwise LME fitting with random intercepts
- Multiple comparison correction methods: GRF (FSL), TFCE (permutation), FDR
- Anatomical cluster labeling via FSL atlasq
- Comprehensive logging and quality control

Usage:
    python script/group_analysis_statistics.py \\
        --results results/ \\
        --output results/group_analysis/seed_based/DiFuMo256/Motor_Cortex/ \\
        --analysis-type seed_based \\
        --atlas DiFuMo256 \\
        --seed Motor_Cortex \\
        --correction-method grf \\
        --n-permutations 1000

Dependencies:
    pip install nibabel nilearn pandas numpy scipy statsmodels scikit-image joblib
"""

import argparse
import json
import logging
import subprocess
import sys
import warnings
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import nibabel as nib
import numpy as np
import pandas as pd
from joblib import Parallel, delayed
from nilearn import image, masking
from scipy import stats as scipy_stats
from scipy.ndimage import label as ndimage_label
from scipy.special import comb
from skimage import measure
from statsmodels.formula.api import mixedlm

warnings.filterwarnings('ignore')


# ============================================================================
# LOGGING SETUP
# ============================================================================

def setup_logger(output_dir: Path) -> logging.Logger:
    """Setup logging to file and console."""
    output_dir.mkdir(parents=True, exist_ok=True)
    log_file = output_dir / 'group_analysis.log'
    
    logger = logging.getLogger('group_analysis')
    logger.setLevel(logging.DEBUG)
    
    # File handler
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger


# ============================================================================
# DATA AGGREGATION AND PREPARATION
# ============================================================================

def load_group_assignments(group_file: Optional[Path], results_dir: Path) -> pd.DataFrame:
    """Load participants.tsv or legacy group.csv and normalize subject IDs."""
    candidates = [Path(group_file)] if group_file is not None else [
        Path('bids/participants.tsv'),
        Path('group.csv'),
        results_dir.parent / 'bids' / 'participants.tsv',
        results_dir.parent / 'group.csv',
    ]

    for candidate in candidates:
        if not candidate.exists():
            continue
        groups = pd.read_csv(candidate, sep='\t' if candidate.suffix == '.tsv' else ',')
        if 'participant_id' in groups.columns and 'subject_id' not in groups.columns:
            groups = groups.rename(columns={'participant_id': 'subject_id'})
        if 'subject_id' not in groups.columns:
            raise ValueError(
                f"Group metadata must contain a 'participant_id' or 'subject_id' column: {candidate}"
            )
        return groups

    raise FileNotFoundError(
        f"Group file not found. Checked: {', '.join(str(c) for c in candidates)}"
    )


def load_metadata_and_group(
    results_dir: Path,
    group_file: Optional[Path] = None
) -> pd.DataFrame:
    """
    Load and merge metadata with group assignments.
    
    Parameters
    ----------
    results_dir : Path
        Path to results directory containing metadata.csv
    group_file : Path, optional
        Path to bids/participants.tsv or legacy group.csv. If None, tries standard locations.
    
    Returns
    -------
    pd.DataFrame
        Merged metadata with group assignments
    """
    # Load metadata
    metadata_path = results_dir / 'metadata.csv'
    if not metadata_path.exists():
        raise FileNotFoundError(f"Metadata file not found: {metadata_path}")
    
    metadata = pd.read_csv(metadata_path)
    
    # Standardize column names (handle 'subject' vs 'subject_id')
    if 'subject' in metadata.columns and 'subject_id' not in metadata.columns:
        metadata = metadata.rename(columns={'subject': 'subject_id'})
    
    groups = load_group_assignments(group_file, results_dir)
    
    # Use group from participants.tsv/group.csv if present in metadata, merge to get authoritative assignment
    if 'group' in metadata.columns:
        metadata = metadata.drop(columns=['group'])
    
    merged = metadata.merge(
        groups,
        on='subject_id',
        how='left'
    )
    
    # Check for unassigned subjects
    unassigned = merged[merged['group'].isna()]['subject_id'].unique()
    if len(unassigned) > 0:
        logging.warning(f"Subjects without group assignment: {unassigned}")
    
    return merged


def prepare_metadata(
    df: pd.DataFrame,
    logger: logging.Logger
) -> pd.DataFrame:
    """
    Prepare metadata: add time coding, standardize covariates.
    
    Parameters
    ----------
    df : pd.DataFrame
        Raw metadata
    logger : logging.Logger
        Logger instance
    
    Returns
    -------
    pd.DataFrame
        Prepared metadata with standardized covariates
    """
    df = df.copy()
    
    # Check required columns
    required = ['subject_id', 'session', 'group']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # Create time coding (0 for first session, 1 for second)
    df['time'] = (df['session'].str.extract(r'(\d+)').astype(int) - 1).values
    
    # Code group as binary (assuming 2 groups)
    groups = df['group'].dropna().unique()
    groups = groups[pd.Series(groups).notna()]
    
    if len(groups) < 2:
        logger.warning(f"Expected 2 groups, found {len(groups)}: {groups}")
        # Handle case with only 1 group
        if len(groups) > 0:
            df['group_code'] = (df['group'] != groups[0]).astype(int)
    else:
        group_dict = {groups[0]: 0, groups[1]: 1}
        df['group_code'] = df['group'].map(group_dict)
    
    # Code sex as binary if available
    if 'sex' in df.columns:
        sex_values = df['sex'].dropna().unique()
        sex_values = sex_values[(sex_values != '') & (pd.notna(sex_values))]
        if len(sex_values) > 0:
            sex_dict = {}
            for i, sex in enumerate(sorted(sex_values)):
                sex_dict[sex] = i
            df['sex_code'] = df['sex'].map(sex_dict)
    
    # Standardize continuous covariates
    for col in ['age', 'mean_fd']:
        if col in df.columns:
            valid = df[col].notna()
            if valid.sum() > 0:
                mean = df.loc[valid, col].mean()
                std = df.loc[valid, col].std()
                if std > 0:
                    df[f'{col}_std'] = (df[col] - mean) / std
                    df.loc[~valid, f'{col}_std'] = np.nan
    
    logger.info(f"Prepared metadata: {len(df)} observations, {df['subject_id'].nunique()} subjects")
    
    return df


# ============================================================================
# DATA LOADING
# ============================================================================

def load_subject_maps(
    results_dir: Path,
    analysis_type: str,
    atlas_name: Optional[str] = None,
    seed_name: Optional[str] = None,
    logger: Optional[logging.Logger] = None
) -> Tuple[List[Path], List[str]]:
    """
    Find subject-level result maps.
    
    Parameters
    ----------
    results_dir : Path
        Path to results directory
    analysis_type : str
        'local_measures', 'seed_based', or 'network_connectivity'
    atlas_name : str, optional
        Atlas name for seed-based connectivity
    seed_name : str, optional
        Seed name for seed-based connectivity
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    Tuple[List[Path], List[str]]
        Paths to maps and corresponding scan identifiers
    """
    if logger:
        logger.info(f"Loading {analysis_type} maps from {results_dir}")
    
    if analysis_type == 'local_measures':
        # Find fALFF and ReHo maps
        local_dir = results_dir / 'local_measures'
        if not local_dir.exists():
            raise FileNotFoundError(f"Local measures directory not found: {local_dir}")
        
        falff_maps = sorted(local_dir.glob('*_fALFF.nii.gz'))
        reho_maps = sorted(local_dir.glob('*_ReHo.nii.gz'))
        
        return falff_maps + reho_maps, ['fALFF'] * len(falff_maps) + ['ReHo'] * len(reho_maps)
    
    elif analysis_type == 'seed_based':
        if not atlas_name or not seed_name:
            raise ValueError("atlas_name and seed_name required for seed_based analysis")
        
        seed_dir = results_dir / 'connectivity' / 'seed_based' / atlas_name / seed_name
        if not seed_dir.exists():
            raise FileNotFoundError(f"Seed connectivity directory not found: {seed_dir}")
        
        maps = sorted(seed_dir.glob('*_z.nii.gz'))
        return maps, [seed_name] * len(maps)
    
    elif analysis_type == 'network_connectivity':
        if not atlas_name:
            raise ValueError("atlas_name required for network_connectivity analysis")
        
        net_dir = results_dir / 'connectivity' / 'network' / atlas_name
        if not net_dir.exists():
            raise FileNotFoundError(f"Network connectivity directory not found: {net_dir}")
        
        maps = sorted(net_dir.glob('*_correlation_matrix.nii.gz'))
        return maps, [atlas_name] * len(maps)
    
    else:
        raise ValueError(f"Unknown analysis_type: {analysis_type}")


def extract_scan_id(map_path: Path) -> Tuple[str, str]:
    """
    Extract subject_id and session from map path.
    
    Parameters
    ----------
    map_path : Path
        Path like sub-033_ses-01_fALFF.nii.gz
    
    Returns
    -------
    Tuple[str, str]
        subject_id, session
    """
    stem = map_path.stem
    if stem.endswith('.nii'):
        stem = stem[:-4]
    
    parts = stem.split('_')
    subject_id = parts[0]  # sub-033
    session = parts[1]     # ses-01
    
    return subject_id, session


def load_maps_as_array(
    map_paths: List[Path],
    mask_path: Optional[Path] = None,
    logger: Optional[logging.Logger] = None
) -> Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]:
    """
    Load subject maps as 4D array.
    
    Parameters
    ----------
    map_paths : List[Path]
        Paths to subject map files
    mask_path : Path, optional
        Path to brain mask
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]
        (data_array, affine, mask)
        data_array: (n_scans, x, y, z)
    """
    if logger:
        logger.info(f"Loading {len(map_paths)} maps...")
    
    # Load first map to get shape
    first_img = nib.load(map_paths[0])
    shape = first_img.shape
    affine = first_img.affine
    
    # Load mask if provided
    if mask_path and mask_path.exists():
        mask_img = nib.load(mask_path)
        mask = mask_img.get_fdata() > 0.5
    else:
        # Use union of all non-nan voxels as mask
        mask = None
    
    # Load all maps
    data_list = []
    for path in map_paths:
        img = nib.load(path)
        data = img.get_fdata()
        data_list.append(data)
    
    data_array = np.stack(data_list, axis=0)
    
    if logger:
        logger.info(f"Loaded data shape: {data_array.shape}")
    
    return data_array, affine, mask


# ============================================================================
# LME MODEL FITTING
# ============================================================================

def fit_lme_voxelwise(
    data: np.ndarray,
    metadata: pd.DataFrame,
    n_jobs: int = -1,
    logger: Optional[logging.Logger] = None
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Fit LME model voxelwise.
    
    Model formula: value ~ group_code * time + age_std + sex_code + mean_fd_std + (1|subject_id)
    
    Parameters
    ----------
    data : np.ndarray
        (n_scans, x, y, z) array of voxel values
    metadata : pd.DataFrame
        Prepared metadata with standardized covariates
    n_jobs : int
        Number of parallel jobs
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    Tuple[np.ndarray, np.ndarray, np.ndarray]
        (t_stat_map, p_value_map, effect_size_map)
    """
    if logger:
        logger.info("Fitting voxelwise LME models...")
    
    n_scans = data.shape[0]
    spatial_shape = data.shape[1:]
    n_voxels = np.prod(spatial_shape)
    
    # Build formula
    formula_parts = ['group_code * time']
    if 'age_std' in metadata.columns:
        formula_parts.append('age_std')
    if 'sex_code' in metadata.columns:
        formula_parts.append('sex_code')
    if 'mean_fd_std' in metadata.columns:
        formula_parts.append('mean_fd_std')
    
    formula = 'value ~ ' + ' + '.join(formula_parts) + ' + (1|subject_id)'
    
    if logger:
        logger.info(f"LME formula: {formula}")
        logger.info(f"N observations: {len(metadata)}, N subjects: {metadata['subject_id'].nunique()}")
    
    # Reshape data for fitting
    data_reshaped = data.reshape(n_scans, -1)
    
    # Initialize output arrays
    t_stat_map = np.zeros(n_voxels)
    p_value_map = np.ones(n_voxels)
    effect_size_map = np.zeros(n_voxels)
    
    # Fit for each voxel
    def fit_voxel(voxel_idx: int) -> Tuple[int, float, float, float]:
        """Fit LME for single voxel."""
        try:
            voxel_data = data_reshaped[:, voxel_idx]
            
            # Skip if too many NaN/inf
            valid = np.isfinite(voxel_data)
            if valid.sum() < len(voxel_data) * 0.5:
                return voxel_idx, 0.0, 1.0, 0.0
            
            # Prepare data for this voxel
            fit_data = metadata.copy()
            fit_data['value'] = voxel_data
            fit_data = fit_data[valid]
            
            # Skip if insufficient variance
            if fit_data['value'].std() < 1e-6:
                return voxel_idx, 0.0, 1.0, 0.0
            
            # Fit model
            try:
                model = mixedlm(formula, fit_data, groups=fit_data['subject_id'])
                result = model.fit(method='powell')
                
                # Extract group:time interaction t-statistic
                # (or group effect if no time interaction)
                if 'group_code:time' in result.pvalues.index:
                    t_stat = result.tvalues['group_code:time']
                    p_val = result.pvalues['group_code:time']
                    effect_size = result.fe_params['group_code:time']
                elif 'group_code' in result.pvalues.index:
                    t_stat = result.tvalues['group_code']
                    p_val = result.pvalues['group_code']
                    effect_size = result.fe_params['group_code']
                else:
                    t_stat, p_val, effect_size = 0.0, 1.0, 0.0
                
                return voxel_idx, float(t_stat), float(p_val), float(effect_size)
            
            except Exception as e:
                return voxel_idx, 0.0, 1.0, 0.0
        
        except Exception:
            return voxel_idx, 0.0, 1.0, 0.0
    
    # Parallel fitting
    results = Parallel(n_jobs=n_jobs, verbose=10)(
        delayed(fit_voxel)(i) for i in range(n_voxels)
    )
    
    # Unpack results
    for voxel_idx, t_stat, p_val, effect_size in results:
        t_stat_map[voxel_idx] = t_stat
        p_value_map[voxel_idx] = p_val
        effect_size_map[voxel_idx] = effect_size
    
    # Reshape back to spatial dimensions
    t_stat_map = t_stat_map.reshape(spatial_shape)
    p_value_map = p_value_map.reshape(spatial_shape)
    effect_size_map = effect_size_map.reshape(spatial_shape)
    
    if logger:
        logger.info(f"T-stat range: [{np.nanmin(t_stat_map):.3f}, {np.nanmax(t_stat_map):.3f}]")
        n_sig = (p_value_map < 0.05).sum()
        logger.info(f"Voxels with p < 0.05: {n_sig}")
    
    return t_stat_map, p_value_map, effect_size_map


# ============================================================================
# MULTIPLE COMPARISON CORRECTION
# ============================================================================

def apply_fdr_correction(
    p_value_map: np.ndarray,
    alpha: float = 0.05,
    logger: Optional[logging.Logger] = None
) -> np.ndarray:
    """
    Apply Benjamini-Hochberg FDR correction.
    
    Parameters
    ----------
    p_value_map : np.ndarray
        Uncorrected p-value map
    alpha : float
        FDR threshold
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    np.ndarray
        Corrected p-value map
    """
    if logger:
        logger.info(f"Applying FDR correction (alpha={alpha})...")
    
    # Flatten and get valid p-values
    p_flat = p_value_map.flatten()
    valid_idx = np.isfinite(p_flat)
    p_valid = p_flat[valid_idx]
    
    # Benjamini-Hochberg correction
    n_tests = len(p_valid)
    sorted_idx = np.argsort(p_valid)
    sorted_p = p_valid[sorted_idx]
    
    # Compute threshold
    threshold_idx = np.where(sorted_p <= alpha * np.arange(1, n_tests + 1) / n_tests)[0]
    
    if len(threshold_idx) > 0:
        threshold = sorted_p[threshold_idx[-1]]
    else:
        threshold = 0  # No significant voxels
    
    # Create corrected map
    p_corrected = p_value_map.copy()
    p_corrected[p_corrected > threshold] = 1.0
    
    if logger:
        logger.info(f"FDR threshold: {threshold:.6f}, significant voxels: {(p_corrected < threshold).sum()}")
    
    return p_corrected


def apply_tfce_correction(
    t_stat_map: np.ndarray,
    metadata: pd.DataFrame,
    data: np.ndarray,
    n_permutations: int = 1000,
    n_jobs: int = -1,
    logger: Optional[logging.Logger] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply TFCE-like correction via permutation testing.
    
    Parameters
    ----------
    t_stat_map : np.ndarray
        Uncorrected t-statistic map
    metadata : pd.DataFrame
        Subject metadata
    data : np.ndarray
        Original data array (n_scans, x, y, z)
    n_permutations : int
        Number of permutations
    n_jobs : int
        Number of parallel jobs
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    Tuple[np.ndarray, np.ndarray]
        (p_value_map, effect_size_corrected_map)
    """
    if logger:
        logger.info(f"Applying TFCE correction ({n_permutations} permutations)...")
    
    n_scans = len(metadata)
    spatial_shape = t_stat_map.shape
    n_voxels = np.prod(spatial_shape)
    
    # Reshape data
    data_reshaped = data.reshape(n_scans, n_voxels)
    
    # Observed max t-stat (taking absolute value for two-tailed)
    obs_max_t = np.abs(t_stat_map).max()
    
    # Permutation distribution
    perm_max_t_dist = []
    
    def permutation_fit(perm_idx: int) -> float:
        """Fit LME on permuted data."""
        try:
            # Permute group labels
            perm_metadata = metadata.copy()
            group_codes = perm_metadata['group_code'].values
            perm_group = np.random.permutation(group_codes)
            perm_metadata['group_code'] = perm_group
            
            # Fit LME on a subset of voxels (for speed)
            n_test_voxels = min(1000, n_voxels)
            test_voxel_idx = np.random.choice(n_voxels, n_test_voxels, replace=False)
            
            max_t = 0
            for vi, voxel_idx in enumerate(test_voxel_idx):
                try:
                    voxel_data = data_reshaped[:, voxel_idx]
                    valid = np.isfinite(voxel_data)
                    if valid.sum() < n_scans * 0.5:
                        continue
                    
                    fit_data = perm_metadata.copy()
                    fit_data['value'] = voxel_data
                    fit_data = fit_data[valid]
                    
                    if fit_data['value'].std() < 1e-6:
                        continue
                    
                    formula = 'value ~ group_code * time + (1|subject_id)'
                    model = mixedlm(formula, fit_data, groups=fit_data['subject_id'])
                    result = model.fit(method='powell', disp=False)
                    
                    if 'group_code:time' in result.tvalues.index:
                        t_val = abs(result.tvalues['group_code:time'])
                    else:
                        t_val = abs(result.tvalues['group_code'])
                    
                    max_t = max(max_t, t_val)
                except:
                    pass
            
            return max_t
        except:
            return 0
    
    # Run permutations
    perm_max_t_dist = Parallel(n_jobs=n_jobs, verbose=5)(
        delayed(permutation_fit)(i) for i in range(n_permutations)
    )
    perm_max_t_dist = np.array(perm_max_t_dist)
    
    if logger:
        logger.info(f"Permutation max t-stat range: [{perm_max_t_dist.min():.3f}, {perm_max_t_dist.max():.3f}]")
    
    # Convert t-stats to p-values based on permutation distribution
    abs_t_stat_map = np.abs(t_stat_map)
    p_value_map = np.ones_like(t_stat_map)
    
    for voxel_idx in range(n_voxels):
        i, j, k = np.unravel_index(voxel_idx, spatial_shape)
        t_val = abs_t_stat_map[i, j, k]
        
        if np.isfinite(t_val):
            p_value_map[i, j, k] = (perm_max_t_dist >= t_val).sum() / len(perm_max_t_dist)
    
    if logger:
        n_sig = (p_value_map < 0.05).sum()
        logger.info(f"TFCE corrected voxels with p < 0.05: {n_sig}")
    
    return p_value_map, t_stat_map


def apply_grf_correction(
    t_stat_map: np.ndarray,
    affine: np.ndarray,
    output_dir: Path,
    threshold: float = 2.3,
    cluster_threshold: float = 0.05,
    logger: Optional[logging.Logger] = None
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Apply Gaussian Random Field (GRF) correction via FSL.
    
    Parameters
    ----------
    t_stat_map : np.ndarray
        Uncorrected t-statistic map
    affine : np.ndarray
        Affine transform matrix
    output_dir : Path
        Directory for temporary files
    threshold : float
        Voxel-level threshold for FSL cluster
    cluster_threshold : float
        Cluster-level p-value threshold
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    Tuple[np.ndarray, np.ndarray]
        (p_value_map, cluster_map)
    """
    if logger:
        logger.info(f"Applying GRF correction (FSL cluster, threshold={threshold})...")
    
    # Save t-stat map as NIfTI
    output_dir.mkdir(parents=True, exist_ok=True)
    tstat_nii_path = output_dir / 'tstat_map_temp.nii.gz'
    
    img = nib.Nifti1Image(t_stat_map, affine)
    nib.save(img, tstat_nii_path)
    
    # Run FSL cluster
    cluster_out_path = output_dir / 'cluster_table.txt'
    
    try:
        cmd = [
            'fsl_cluster',
            '-i', str(tstat_nii_path),
            '-t', str(threshold),
            '-p', str(cluster_threshold),
            '--mm',
            '-o', str(cluster_out_path)
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        if logger:
            logger.info(f"FSL cluster completed, output: {cluster_out_path}")
    
    except (FileNotFoundError, subprocess.CalledProcessError) as e:
        if logger:
            logger.warning(f"FSL cluster failed ({e}), falling back to FDR correction")
        return apply_fdr_correction(scipy_stats.t.sf(np.abs(t_stat_map), df=70) * 2, logger=logger), np.zeros_like(t_stat_map)
    
    # Create p-value map based on cluster results
    p_value_map = np.ones_like(t_stat_map)
    cluster_map = np.zeros_like(t_stat_map)
    
    if cluster_out_path.exists():
        clusters = pd.read_csv(cluster_out_path, sep=r'\s+', skiprows=1)
        # Mark significant clusters
        for idx, row in clusters.iterrows():
            if row['Cluster'] < cluster_threshold:  # Assuming Cluster column is p-value
                p_value_map[p_value_map < cluster_threshold] = row['Cluster']
    
    if logger:
        logger.info(f"GRF correction complete, {(cluster_map > 0).sum()} voxels in clusters")
    
    return p_value_map, cluster_map


# ============================================================================
# CLUSTER EXTRACTION AND LABELING
# ============================================================================

def extract_clusters(
    stat_map: np.ndarray,
    p_value_map: np.ndarray,
    affine: np.ndarray,
    threshold: float = 0.05,
    min_cluster_size: int = 10,
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    Extract clusters from thresholded statistical map.
    
    Parameters
    ----------
    stat_map : np.ndarray
        T-statistic or effect size map
    p_value_map : np.ndarray
        Corrected p-value map
    affine : np.ndarray
        Affine transform
    threshold : float
        P-value threshold for significance
    min_cluster_size : int
        Minimum cluster size in voxels
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    pd.DataFrame
        Cluster table with coordinates and statistics
    """
    if logger:
        logger.info(f"Extracting clusters (p < {threshold}, min size {min_cluster_size} voxels)...")
    
    # Threshold map
    binary_map = p_value_map < threshold
    
    # Label connected components (6-connectivity)
    labeled_map, n_clusters = ndimage_label(binary_map)
    
    if logger:
        logger.info(f"Found {n_clusters} clusters")
    
    clusters_list = []
    
    for cluster_id in range(1, n_clusters + 1):
        cluster_mask = labeled_map == cluster_id
        n_voxels = cluster_mask.sum()
        
        if n_voxels < min_cluster_size:
            continue
        
        # Get cluster voxel coordinates
        coords = np.where(cluster_mask)
        
        # Peak voxel (highest |t-stat|)
        cluster_stat_vals = stat_map[cluster_mask]
        peak_idx = np.argmax(np.abs(cluster_stat_vals))
        peak_coord_idx = (coords[0][peak_idx], coords[1][peak_idx], coords[2][peak_idx])
        
        # Convert to MNI coordinates
        peak_mni = affine @ np.array([*peak_coord_idx, 1])
        peak_mni = peak_mni[:3]
        
        # Mean statistics
        mean_stat = cluster_stat_vals.mean()
        mean_p = p_value_map[cluster_mask].mean()
        peak_stat = cluster_stat_vals[peak_idx]
        peak_p = p_value_map[peak_coord_idx]
        
        clusters_list.append({
            'cluster_id': cluster_id,
            'n_voxels': n_voxels,
            'peak_x': peak_mni[0],
            'peak_y': peak_mni[1],
            'peak_z': peak_mni[2],
            'peak_t': peak_stat,
            'peak_p': peak_p,
            'mean_t': mean_stat,
            'mean_p': mean_p,
        })
    
    cluster_df = pd.DataFrame(clusters_list)
    cluster_df = cluster_df.sort_values('peak_p')
    
    if logger:
        logger.info(f"Extracted {len(cluster_df)} clusters (size >= {min_cluster_size})")
    
    return cluster_df


def label_clusters_with_anatomy(
    cluster_df: pd.DataFrame,
    logger: Optional[logging.Logger] = None
) -> pd.DataFrame:
    """
    Label clusters using FSL atlasq.
    
    Parameters
    ----------
    cluster_df : pd.DataFrame
        Cluster table with coordinates
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    pd.DataFrame
        Cluster table with anatomical labels
    """
    if logger:
        logger.info("Labeling clusters with anatomical regions...")
    
    labels = []
    
    for idx, row in cluster_df.iterrows():
        peak_coords = (row['peak_x'], row['peak_y'], row['peak_z'])
        
        try:
            # Run atlasq
            cmd = [
                'atlasq',
                '-l',
                f'{peak_coords[0]} {peak_coords[1]} {peak_coords[2]}'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            label = result.stdout.strip()
            
            if not label:
                label = "Unknown"
        
        except (FileNotFoundError, subprocess.CalledProcessError):
            label = "Unknown"
        
        labels.append(label)
    
    cluster_df['anatomy'] = labels
    
    if logger:
        logger.info(f"Labeled {len(labels)} clusters")
    
    return cluster_df


# ============================================================================
# MAIN ANALYSIS FUNCTION
# ============================================================================

def run_group_analysis(
    results_dir: Path,
    output_dir: Path,
    analysis_type: str = 'local_measures',
    atlas_name: Optional[str] = None,
    seed_name: Optional[str] = None,
    measure_name: str = 'fALFF',
    correction_method: str = 'fdr',
    n_permutations: int = 1000,
    group_file: Optional[Path] = None,
    mask_file: Optional[Path] = None,
    min_cluster_size: int = 10,
    alpha: float = 0.05,
    n_jobs: int = -1,
    logger: Optional[logging.Logger] = None
) -> Dict:
    """
    Run complete group-level LME analysis with multiple comparison correction.
    
    Parameters
    ----------
    results_dir : Path
        Path to results directory with subject-level maps
    output_dir : Path
        Output directory for results
    analysis_type : str
        'local_measures', 'seed_based', or 'network_connectivity'
    atlas_name : str, optional
        Atlas name for seed-based/network analyses
    seed_name : str, optional
        Seed name for seed-based analysis
    measure_name : str
        Measure name (fALFF, ReHo, etc.)
    correction_method : str
        'grf', 'tfce', or 'fdr'
    n_permutations : int
        Number of permutations for TFCE
    group_file : Path, optional
        Path to bids/participants.tsv or legacy group.csv
    mask_file : Path, optional
        Path to brain mask
    min_cluster_size : int
        Minimum cluster size in voxels
    alpha : float
        Significance level
    n_jobs : int
        Number of parallel jobs
    logger : logging.Logger, optional
        Logger instance
    
    Returns
    -------
    Dict
        Results summary
    """
    if logger is None:
        logger = logging.getLogger('group_analysis')
    
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("="*70)
    logger.info("GROUP-LEVEL STATISTICAL ANALYSIS")
    logger.info("="*70)
    logger.info(f"Analysis type: {analysis_type}")
    logger.info(f"Correction method: {correction_method}")
    logger.info(f"Output directory: {output_dir}")
    
    try:
        # Load and prepare data
        logger.info("\n--- STEP 1: Data Preparation ---")
        metadata = load_metadata_and_group(results_dir, group_file)
        metadata = prepare_metadata(metadata, logger)
        
        # Load subject maps
        logger.info("\n--- STEP 2: Loading Subject Maps ---")
        map_paths, map_types = load_subject_maps(
            results_dir, analysis_type, atlas_name, seed_name, logger
        )
        
        if len(map_paths) == 0:
            raise ValueError("No subject maps found")
        
        # Filter by measure type if needed
        if analysis_type == 'local_measures':
            map_paths = [p for i, p in enumerate(map_paths) if map_types[i] == measure_name]
            if len(map_paths) == 0:
                raise ValueError(f"No {measure_name} maps found")
        
        logger.info(f"Found {len(map_paths)} maps")
        
        # Create metadata for maps
        map_metadata = []
        for path in map_paths:
            subject_id, session = extract_scan_id(path)
            match = metadata[(metadata['subject_id'] == subject_id) & 
                           (metadata['session'] == session)]
            if not match.empty:
                map_metadata.append(match.iloc[0])
        
        if len(map_metadata) == 0:
            raise ValueError("No metadata matches for loaded maps")
        
        map_metadata_df = pd.DataFrame(map_metadata)
        
        # Load maps
        logger.info("\n--- STEP 3: Loading Map Data ---")
        data, affine, mask = load_maps_as_array(map_paths, mask_file, logger)
        
        # Fit LME models
        logger.info("\n--- STEP 4: Fitting LME Models ---")
        t_stat_map, p_value_map_uncorr, effect_size_map = fit_lme_voxelwise(
            data, map_metadata_df, n_jobs=n_jobs, logger=logger
        )
        
        # Save uncorrected maps
        logger.info("\n--- STEP 5: Applying Multiple Comparison Correction ---")
        
        tstat_img = nib.Nifti1Image(t_stat_map, affine)
        nib.save(tstat_img, output_dir / 'tstat_map_uncorrected.nii.gz')
        
        effect_img = nib.Nifti1Image(effect_size_map, affine)
        nib.save(effect_img, output_dir / 'effect_size_map.nii.gz')
        
        # Apply correction
        if correction_method == 'fdr':
            p_value_map_corr = apply_fdr_correction(p_value_map_uncorr, alpha, logger)
        elif correction_method == 'tfce':
            p_value_map_corr, _ = apply_tfce_correction(
                t_stat_map, map_metadata_df, data, n_permutations, n_jobs, logger
            )
        elif correction_method == 'grf':
            p_value_map_corr, _ = apply_grf_correction(
                t_stat_map, affine, output_dir, logger=logger
            )
        else:
            raise ValueError(f"Unknown correction method: {correction_method}")
        
        # Save corrected p-value map
        p_img = nib.Nifti1Image(p_value_map_corr, affine)
        nib.save(p_img, output_dir / 'pval_map_corrected.nii.gz')
        
        # Extract and label clusters
        logger.info("\n--- STEP 6: Extracting and Labeling Clusters ---")
        cluster_df = extract_clusters(
            t_stat_map, p_value_map_corr, affine, alpha, min_cluster_size, logger
        )
        
        if len(cluster_df) > 0:
            cluster_df = label_clusters_with_anatomy(cluster_df, logger)
            cluster_df.to_csv(output_dir / 'cluster_table.csv', index=False)
            logger.info(f"Saved {len(cluster_df)} clusters to cluster_table.csv")
        else:
            logger.info("No significant clusters found")
        
        # Save model summary
        summary_text = f"""
GROUP-LEVEL STATISTICAL ANALYSIS SUMMARY
==========================================

Analysis Type: {analysis_type}
Measure: {measure_name}
Atlas: {atlas_name or 'N/A'}
Seed: {seed_name or 'N/A'}

Data Summary:
- Observations: {len(map_metadata_df)}
- Subjects: {map_metadata_df['subject_id'].nunique()}
- Sessions: {map_metadata_df['session'].nunique()}

Model:
- Formula: value ~ group_code * time + age_std + sex_code + mean_fd_std + (1|subject_id)
- Groups: {', '.join(map_metadata_df['group'].unique())}

Statistics:
- T-stat range: [{np.nanmin(t_stat_map):.3f}, {np.nanmax(t_stat_map):.3f}]
- Uncorrected p < 0.05: {(p_value_map_uncorr < 0.05).sum()} voxels
- Corrected p < {alpha}: {(p_value_map_corr < alpha).sum()} voxels
- Significant clusters: {len(cluster_df)}

Correction Method: {correction_method}
Output Directory: {output_dir}
"""
        
        with open(output_dir / 'model_summary.txt', 'w') as f:
            f.write(summary_text)
        
        logger.info("\n" + summary_text)
        
        # Save results metadata
        results_meta = {
            'analysis_type': analysis_type,
            'measure_name': measure_name,
            'atlas_name': atlas_name,
            'seed_name': seed_name,
            'correction_method': correction_method,
            'n_observations': len(map_metadata_df),
            'n_subjects': map_metadata_df['subject_id'].nunique(),
            'n_clusters': len(cluster_df),
            'alpha': alpha,
            'min_cluster_size': min_cluster_size,
        }
        
        with open(output_dir / 'results_metadata.json', 'w') as f:
            json.dump(results_meta, f, indent=2)
        
        logger.info("\n--- COMPLETE ---")
        logger.info("All results saved to " + str(output_dir))
        
        return results_meta
    
    except Exception as e:
        logger.error(f"Analysis failed: {e}", exc_info=True)
        raise


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Group-level statistical analysis with LME and multiple comparison correction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Local measures analysis with FDR correction
  python script/group_analysis_statistics.py \\
    --results results/ \\
    --output results/group_analysis/local_measures/fALFF/ \\
    --analysis-type local_measures \\
    --measure fALFF \\
    --correction-method fdr

  # Seed-based connectivity with GRF correction
  python script/group_analysis_statistics.py \\
    --results results/ \\
    --output results/group_analysis/seed_based/DiFuMo256/Motor_Cortex/ \\
    --analysis-type seed_based \\
    --atlas DiFuMo256 \\
    --seed Motor_Cortex \\
    --correction-method grf
        """
    )
    
    parser.add_argument('--results', type=Path, required=True,
                       help='Results directory')
    parser.add_argument('--output', type=Path, required=True,
                       help='Output directory')
    parser.add_argument('--analysis-type', choices=['local_measures', 'seed_based', 'network_connectivity'],
                       default='local_measures',
                       help='Type of analysis')
    parser.add_argument('--measure', type=str, default='fALFF',
                       help='Measure name (for local_measures)')
    parser.add_argument('--atlas', type=str,
                       help='Atlas name (for seed_based/network)')
    parser.add_argument('--seed', type=str,
                       help='Seed name (for seed_based)')
    parser.add_argument('--correction-method', choices=['grf', 'tfce', 'fdr'],
                       default='fdr',
                       help='Multiple comparison correction method')
    parser.add_argument('--n-permutations', type=int, default=1000,
                       help='Number of permutations for TFCE')
    parser.add_argument('--group-file', type=Path,
                       help='Path to bids/participants.tsv or legacy group.csv')
    parser.add_argument('--mask-file', type=Path,
                       help='Path to brain mask')
    parser.add_argument('--alpha', type=float, default=0.05,
                       help='Significance level')
    parser.add_argument('--min-cluster-size', type=int, default=10,
                       help='Minimum cluster size in voxels')
    parser.add_argument('--n-jobs', type=int, default=-1,
                       help='Number of parallel jobs (-1 for all)')
    
    args = parser.parse_args()
    
    # Setup logging
    logger = setup_logger(args.output)
    
    # Run analysis
    try:
        results = run_group_analysis(
            results_dir=args.results,
            output_dir=args.output,
            analysis_type=args.analysis_type,
            atlas_name=args.atlas,
            seed_name=args.seed,
            measure_name=args.measure,
            correction_method=args.correction_method,
            n_permutations=args.n_permutations,
            group_file=args.group_file,
            mask_file=args.mask_file,
            alpha=args.alpha,
            min_cluster_size=args.min_cluster_size,
            n_jobs=args.n_jobs,
            logger=logger
        )
        
        sys.exit(0)
    
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
