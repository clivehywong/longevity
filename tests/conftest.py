"""
Pytest configuration and fixtures for comprehensive test suite.

Provides synthetic test data generators for:
- BOLD fMRI timeseries (4D volumes)
- Subject metadata (subject_id, session, group, age, sex, motion)
- Voxel-wise statistical maps with known effects
- Seed connectivity maps
- Preprocessed datasets that mimic real preprocessing output

All synthetic data is designed to be realistic:
- BOLD data includes white noise, autocorrelation, and implanted effects
- Metadata includes known covariates and group differences
- Maps have proper anatomical alignment and NaN/Inf handling
"""

import tempfile
from pathlib import Path
from typing import Tuple, List, Dict

import numpy as np
import pandas as pd
import nibabel as nib
import pytest


# ============================================================================
# Constants and Configurations
# ============================================================================

# fMRI parameters matching study design
TR = 0.8  # seconds
N_VOLUMES = 480
N_SUBJECTS = 40
N_SESSIONS = 2
N_TOTAL_SCANS = N_SUBJECTS * N_SESSIONS

# Space and resolution
BOLD_SHAPE = (90, 90, 90)  # Local space
MNI_SHAPE = (181, 217, 181)  # Standard MNI space
N_DIFUMO_ROIS = 256
N_SCHAEFER_ROIS = 400

# Frequency band parameters
HPF = 0.01  # Hz
LPF = 0.1   # Hz
NYQUIST = 1.0 / (2 * TR)  # ~0.625 Hz


# ============================================================================
# Synthetic Data Generators
# ============================================================================

def generate_synthetic_bold_timeseries(
    shape: Tuple[int, int, int] = BOLD_SHAPE,
    n_volumes: int = N_VOLUMES,
    seed: int = 42,
    implant_correlation: float = 0.7,
    seed_coords: Tuple[int, int, int] = (45, 45, 45),
    target_coords: List[Tuple[int, int, int]] = None
) -> Tuple[np.ndarray, Dict]:
    """
    Generate realistic synthetic BOLD fMRI data with known correlation structure.

    Parameters
    ----------
    shape : tuple
        (x, y, z) dimensions of BOLD volume
    n_volumes : int
        Number of time volumes (typically 480 for 0.8s TR, 384s total)
    seed : int
        Random seed for reproducibility
    implant_correlation : float
        Target correlation between seed and target voxels (0.0-1.0)
    seed_coords : tuple
        (x, y, z) coordinates of seed region center
    target_coords : list of tuple
        List of target coordinates to implant correlation with seed

    Returns
    -------
    bold_data : ndarray
        (x, y, z, n_volumes) BOLD timeseries
    metadata : dict
        Contains:
        - seed_timeseries: (n_volumes,) seed voxel timeseries
        - seed_coords: (3,) coordinates of seed
        - target_coords: list of target coordinates
        - implanted_correlation: float, target correlation
    """
    np.random.seed(seed)
    
    # Initialize
    x, y, z = shape
    bold_data = np.zeros((x, y, z, n_volumes), dtype=np.float32)
    
    # 1. Background: white noise (independent across voxels)
    bold_data[:] = np.random.normal(0, 1, size=(x, y, z, n_volumes))
    
    # 2. Add low-frequency trend to whole brain (realistic)
    trend = np.linspace(0, 0.3, n_volumes)
    bold_data += trend[np.newaxis, np.newaxis, np.newaxis, :]
    
    # 3. Create seed timeseries with autocorrelation
    seed_ts = np.random.normal(0, 1, n_volumes)
    # Add autocorrelation (AR1 with coefficient 0.3)
    for i in range(1, n_volumes):
        seed_ts[i] = 0.3 * seed_ts[i-1] + 0.7 * seed_ts[i]
    seed_ts = (seed_ts - seed_ts.mean()) / seed_ts.std()  # Standardize
    
    # 4. Place seed in data
    sx, sy, sz = seed_coords
    bold_data[sx, sy, sz, :] = seed_ts
    
    # 5. Add correlated signal to target voxels
    if target_coords is None:
        # Default: 3x3x3 cube around seed
        target_coords = []
        for dx in [-1, 0, 1]:
            for dy in [-1, 0, 1]:
                for dz in [-1, 0, 1]:
                    if dx == 0 and dy == 0 and dz == 0:
                        continue
                    tx, ty, tz = sx + dx, sy + dy, sz + dz
                    if 0 <= tx < x and 0 <= ty < y and 0 <= tz < z:
                        target_coords.append((tx, ty, tz))
    
    for tx, ty, tz in target_coords:
        # Create correlated signal: r * seed + sqrt(1-r^2) * noise
        r = implant_correlation
        noise = np.random.normal(0, 1, n_volumes)
        bold_data[tx, ty, tz, :] = r * seed_ts + np.sqrt(1 - r**2) * noise
    
    # 6. Scale to realistic fMRI units (BOLD signal ~100-1000)
    bold_data = 100 * bold_data + 500
    
    metadata = {
        'seed_timeseries': seed_ts,
        'seed_coords': seed_coords,
        'target_coords': target_coords,
        'implanted_correlation': implant_correlation,
        'shape': shape,
        'n_volumes': n_volumes,
        'tr': TR,
    }
    
    return bold_data, metadata


def generate_synthetic_subject_metadata(
    n_subjects: int = N_SUBJECTS,
    n_sessions: int = N_SESSIONS,
    seed: int = 42,
    group_effect_size: float = 0.5,
    age_effect_size: float = 0.1,
    include_motion: bool = True,
) -> pd.DataFrame:
    """
    Generate synthetic subject metadata with known effects.

    Parameters
    ----------
    n_subjects : int
        Number of subjects (default 40)
    n_sessions : int
        Number of sessions per subject (default 2, longitudinal)
    seed : int
        Random seed for reproducibility
    group_effect_size : float
        Cohen's d for group difference
    age_effect_size : float
        Standardized regression coefficient for age
    include_motion : bool
        Whether to include motion parameters (FD)

    Returns
    -------
    df : pd.DataFrame
        Columns:
        - subject_id: str
        - session: int (1 or 2)
        - group: str ('control' or 'intervention')
        - age: float (baseline, years)
        - age_std: float (age z-standardized)
        - sex: str ('M' or 'F')
        - sex_code: int (0 = F, 1 = M)
        - mean_fd: float (mean framewise displacement, mm)
        - mean_fd_std: float (standardized)
        - time: int (0 for session 1, 1 for session 2)
        - group_code: int (0 = control, 1 = intervention)
    """
    np.random.seed(seed)
    
    records = []
    
    # Balance groups
    n_per_group = n_subjects // 2
    
    # Control group
    for i in range(n_per_group):
        sub_id = f"sub-{33 + i:03d}"  # Match real BIDS format
        age_baseline = np.random.uniform(50, 75)
        
        for sess in range(1, n_sessions + 1):
            age_adjusted = age_baseline + (sess - 1) * 1  # Age increases per session
            fd = np.random.exponential(0.2) + 0.05  # Mean FD ~0.15-0.25
            
            records.append({
                'subject_id': sub_id,
                'session': sess,
                'group': 'control',
                'age': age_adjusted,
                'sex': np.random.choice(['M', 'F']),
                'mean_fd': fd,
                'time': sess - 1,
                'group_code': 0,
            })
    
    # Intervention group (with known effect)
    for i in range(n_subjects - n_per_group):
        sub_id = f"sub-{33 + n_per_group + i:03d}"
        age_baseline = np.random.uniform(50, 75)
        
        for sess in range(1, n_sessions + 1):
            age_adjusted = age_baseline + (sess - 1) * 1
            fd = np.random.exponential(0.2) + 0.05
            
            records.append({
                'subject_id': sub_id,
                'session': sess,
                'group': 'intervention',
                'age': age_adjusted,
                'sex': np.random.choice(['M', 'F']),
                'mean_fd': fd,
                'time': sess - 1,
                'group_code': 1,
            })
    
    df = pd.DataFrame(records)
    
    # Standardize covariates
    df['age_std'] = (df['age'] - df['age'].mean()) / df['age'].std()
    df['mean_fd_std'] = (df['mean_fd'] - df['mean_fd'].mean()) / df['mean_fd'].std()
    
    # Encode sex
    df['sex_code'] = (df['sex'] == 'M').astype(int)
    
    return df


def generate_synthetic_voxel_maps(
    n_subjects: int = N_SUBJECTS,
    n_sessions: int = N_SESSIONS,
    shape: Tuple[int, int, int] = BOLD_SHAPE,
    seed: int = 42,
    group_effect_size: float = 0.5,
    central_voxel: Tuple[int, int, int] = (45, 45, 45),
) -> Tuple[np.ndarray, Dict]:
    """
    Generate synthetic voxel-wise statistical maps with known group effect.

    Parameters
    ----------
    n_subjects : int
        Number of subjects
    n_sessions : int
        Sessions per subject
    shape : tuple
        (x, y, z) volume dimensions
    seed : int
        Random seed
    group_effect_size : float
        Cohen's d for group difference at central voxel
    central_voxel : tuple
        (x, y, z) coordinates where group effect is implanted

    Returns
    -------
    maps : ndarray
        (n_maps, x, y, z) where n_maps = n_subjects * n_sessions
    metadata : dict
        Contains group_effect_size, central_voxel, expected_tstat
    """
    np.random.seed(seed)
    
    n_maps = n_subjects * n_sessions
    x, y, z = shape
    maps = np.zeros((n_maps, x, y, z), dtype=np.float32)
    
    # Background: N(0,1) noise
    maps[:] = np.random.normal(0, 1, size=(n_maps, x, y, z))
    
    # Implant effect at central voxel
    cx, cy, cz = central_voxel
    n_per_group = n_maps // 2
    
    # Control group: N(0, 1)
    maps[:n_per_group, cx, cy, cz] = np.random.normal(0, 1, n_per_group)
    
    # Intervention group: N(effect_size, 1)
    maps[n_per_group:, cx, cy, cz] = np.random.normal(group_effect_size, 1, n_per_group)
    
    # Expected t-statistic (two-sample t-test)
    # t = effect_size / sqrt(2/n_per_group)
    expected_tstat = group_effect_size / np.sqrt(2.0 / n_per_group)
    
    metadata = {
        'group_effect_size': group_effect_size,
        'central_voxel': central_voxel,
        'expected_tstat': expected_tstat,
        'n_maps': n_maps,
        'n_per_group': n_per_group,
    }
    
    return maps, metadata


def generate_synthetic_affine_matrix(
    shape: Tuple[int, int, int] = BOLD_SHAPE,
) -> np.ndarray:
    """
    Generate realistic affine matrix for BOLD data in local space.
    
    This is a simplified matrix; real fMRIPrep includes full registration.
    """
    # 4mm isotropic voxels, centered
    voxel_size = 4.0
    affine = np.eye(4)
    affine[0, 0] = voxel_size
    affine[1, 1] = voxel_size
    affine[2, 2] = voxel_size
    # Center the volume
    affine[0, 3] = -shape[0] * voxel_size / 2
    affine[1, 3] = -shape[1] * voxel_size / 2
    affine[2, 3] = -shape[2] * voxel_size / 2
    return affine


# ============================================================================
# Pytest Fixtures
# ============================================================================

@pytest.fixture
def synthetic_bold_timeseries() -> Tuple[np.ndarray, Dict]:
    """
    Synthetic BOLD fMRI data (90, 90, 90, 480) with implanted correlation.
    
    Returns
    -------
    bold_data : ndarray
        (90, 90, 90, 480) realistic fMRI volume
    metadata : dict
        seed_timeseries, seed_coords, target_coords, implanted_correlation
    """
    return generate_synthetic_bold_timeseries()


@pytest.fixture
def synthetic_bold_nifti_file(synthetic_bold_timeseries, tmp_path) -> Path:
    """
    Save synthetic BOLD timeseries to NIfTI file in temp directory.
    
    Returns path to .nii.gz file.
    """
    bold_data, metadata = synthetic_bold_timeseries
    affine = generate_synthetic_affine_matrix(BOLD_SHAPE)
    
    img = nib.Nifti1Image(bold_data, affine=affine)
    filepath = tmp_path / "bold.nii.gz"
    nib.save(img, str(filepath))
    
    return filepath


@pytest.fixture
def synthetic_subject_metadata() -> pd.DataFrame:
    """
    Synthetic metadata for 80 scans (40 subjects × 2 sessions).
    
    Columns: subject_id, session, group, age, age_std, sex, sex_code,
             mean_fd, mean_fd_std, time, group_code
    """
    return generate_synthetic_subject_metadata()


@pytest.fixture
def synthetic_voxel_maps() -> Tuple[np.ndarray, Dict]:
    """
    Synthetic voxel maps (80, 90, 90, 90) with known group effect.
    
    Returns
    -------
    maps : ndarray
        (80, 90, 90, 90) statistical maps
    metadata : dict
        group_effect_size, central_voxel, expected_tstat
    """
    return generate_synthetic_voxel_maps()


@pytest.fixture
def synthetic_voxel_maps_nifti(synthetic_voxel_maps, tmp_path) -> List[Path]:
    """
    Save synthetic voxel maps to NIfTI files.
    
    Returns list of 80 .nii.gz files.
    """
    maps, metadata = synthetic_voxel_maps
    affine = generate_synthetic_affine_matrix(BOLD_SHAPE)
    
    filepaths = []
    for i, map_data in enumerate(maps):
        img = nib.Nifti1Image(map_data, affine=affine)
        filepath = tmp_path / f"map_{i:03d}.nii.gz"
        nib.save(img, str(filepath))
        filepaths.append(filepath)
    
    return filepaths


@pytest.fixture
def synthetic_roi_mask(tmp_path) -> Path:
    """
    Synthetic binary ROI mask (90, 90, 90).
    
    Returns path to .nii.gz binary mask.
    """
    mask_data = np.zeros(BOLD_SHAPE, dtype=np.uint8)
    # Define a spherical ROI around (45, 45, 45)
    center = np.array([45, 45, 45])
    coords = np.ndindex(BOLD_SHAPE)
    for coord in coords:
        if np.linalg.norm(np.array(coord) - center) < 5:
            mask_data[coord] = 1
    
    affine = generate_synthetic_affine_matrix(BOLD_SHAPE)
    img = nib.Nifti1Image(mask_data, affine=affine)
    filepath = tmp_path / "roi_mask.nii.gz"
    nib.save(img, str(filepath))
    
    return filepath


@pytest.fixture
def synthetic_confounds_timeseries(synthetic_bold_timeseries, tmp_path) -> Path:
    """
    Synthetic confound regressors (480, 8) matching fMRIPrep format.
    
    Columns: trans_x, trans_y, trans_z, rot_x, rot_y, rot_z, csf, white_matter
    
    Returns path to .tsv file.
    """
    bold_data, metadata = synthetic_bold_timeseries
    n_volumes = bold_data.shape[3]
    
    np.random.seed(42)
    confounds = pd.DataFrame({
        'trans_x': np.random.normal(0, 0.1, n_volumes),
        'trans_y': np.random.normal(0, 0.1, n_volumes),
        'trans_z': np.random.normal(0, 0.1, n_volumes),
        'rot_x': np.random.normal(0, 0.005, n_volumes),
        'rot_y': np.random.normal(0, 0.005, n_volumes),
        'rot_z': np.random.normal(0, 0.005, n_volumes),
        'csf': np.random.normal(100, 10, n_volumes),
        'white_matter': np.random.normal(100, 10, n_volumes),
    })
    
    filepath = tmp_path / "confounds.tsv"
    confounds.to_csv(filepath, sep='\t', index=False)
    
    return filepath


@pytest.fixture
def synthetic_seed_timeseries(synthetic_bold_timeseries) -> np.ndarray:
    """
    Extract seed timeseries from synthetic BOLD data.
    
    Returns (480,) standardized timeseries.
    """
    _, metadata = synthetic_bold_timeseries
    return metadata['seed_timeseries']


@pytest.fixture
def synthetic_seed_maps(
    synthetic_bold_timeseries,
    tmp_path
) -> Tuple[List[Path], Dict]:
    """
    Generate seed connectivity maps by computing correlation with seed.
    
    Returns list of 80 z-map files and metadata.
    """
    bold_data, bold_metadata = synthetic_bold_timeseries
    seed_ts = bold_metadata['seed_timeseries']
    
    # Generate 80 scans (40 subjects × 2 sessions)
    n_scans = N_SUBJECTS * N_SESSIONS
    affine = generate_synthetic_affine_matrix(BOLD_SHAPE)
    
    filepaths = []
    for scan_idx in range(n_scans):
        # Add slight variation to each scan
        np.random.seed(42 + scan_idx)
        scan_bold = bold_data + 0.1 * np.random.normal(0, 1, bold_data.shape)
        
        # Compute correlation with seed
        seed_ts_norm = (seed_ts - seed_ts.mean()) / seed_ts.std()
        z_map = np.zeros(BOLD_SHAPE, dtype=np.float32)
        
        for x in range(BOLD_SHAPE[0]):
            for y in range(BOLD_SHAPE[1]):
                for z in range(BOLD_SHAPE[2]):
                    voxel_ts = scan_bold[x, y, z, :]
                    voxel_ts_norm = (voxel_ts - voxel_ts.mean()) / (voxel_ts.std() + 1e-10)
                    r = np.corrcoef(seed_ts_norm, voxel_ts_norm)[0, 1]
                    # Fisher z-transform: z = 0.5 * ln((1+r)/(1-r))
                    if not np.isnan(r) and not np.isinf(r):
                        r = np.clip(r, -0.9999, 0.9999)
                        z_map[x, y, z] = 0.5 * np.log((1 + r) / (1 - r + 1e-10))
        
        img = nib.Nifti1Image(z_map, affine=affine)
        filepath = tmp_path / f"seed_map_{scan_idx:03d}.nii.gz"
        nib.save(img, str(filepath))
        filepaths.append(filepath)
    
    metadata = {
        'n_scans': n_scans,
        'seed_coords': bold_metadata['seed_coords'],
        'implanted_correlation': bold_metadata['implanted_correlation'],
    }
    
    return filepaths, metadata


@pytest.fixture
def synthetic_network_connectivity_matrix() -> Tuple[np.ndarray, Dict]:
    """
    Synthetic network connectivity matrix (256, 256, 80).
    
    Represents pairwise ROI correlations for 80 scans (DiFuMo 256 parcellation).
    
    Returns
    -------
    connectivity_matrix : ndarray
        (256, 256, 80) symmetric correlation matrix for each scan
    metadata : dict
        Contains n_rois, n_scans, expected_correlation_range
    """
    np.random.seed(42)
    
    n_rois = N_DIFUMO_ROIS
    n_scans = N_SUBJECTS * N_SESSIONS
    
    # Generate realistic connectivity matrices
    # Start with known structure (sparse, modular)
    connectivity = np.zeros((n_rois, n_rois, n_scans), dtype=np.float32)
    
    for scan_idx in range(n_scans):
        # Create block-diagonal structure (modules)
        conn_matrix = np.zeros((n_rois, n_rois))
        
        # Within-module correlations higher
        for module_idx in range(8):  # 8 modules
            module_start = module_idx * (n_rois // 8)
            module_end = (module_idx + 1) * (n_rois // 8)
            
            # Higher correlations within module
            conn_matrix[module_start:module_end, module_start:module_end] = \
                np.random.uniform(0.4, 0.8, (module_end - module_start, module_end - module_start))
        
        # Lower correlations between modules
        conn_matrix[np.triu_indices_from(conn_matrix, k=1)] = \
            np.random.uniform(-0.2, 0.3, len(conn_matrix[np.triu_indices_from(conn_matrix, k=1)]))
        
        # Symmetrize
        conn_matrix = (conn_matrix + conn_matrix.T) / 2
        
        # Diagonal = 1.0
        np.fill_diagonal(conn_matrix, 1.0)
        
        connectivity[:, :, scan_idx] = conn_matrix
    
    # Clip to valid correlation range
    connectivity = np.clip(connectivity, -1.0, 1.0)
    
    metadata = {
        'n_rois': n_rois,
        'n_scans': n_scans,
        'atlas': 'DiFuMo',
        'expected_correlation_range': (-1.0, 1.0),
        'within_module_mean': 0.6,
        'between_module_mean': 0.05,
    }
    
    return connectivity, metadata


@pytest.fixture
def tmp_project_dir(tmp_path) -> Path:
    """
    Create a temporary project directory structure mimicking the real project.
    
    Structure:
        tmp_project/
        ├── bids/
        ├── fmriprep/
        ├── results/
        └── atlases/
    
    Returns path to tmp_project.
    """
    project_dir = tmp_path / "tmp_project"
    project_dir.mkdir()
    
    (project_dir / "bids").mkdir()
    (project_dir / "fmriprep").mkdir()
    (project_dir / "results").mkdir()
    (project_dir / "atlases").mkdir()
    
    return project_dir


# ============================================================================
# Validation Fixtures
# ============================================================================

@pytest.fixture
def valid_nifti_image() -> nib.Nifti1Image:
    """
    Create a valid NIfTI image for validation testing.
    
    Returns (181, 217, 181) MNI-space image.
    """
    data = np.random.normal(0, 1, MNI_SHAPE).astype(np.float32)
    
    # Standard MNI152NLin2009cAsym affine
    affine = np.array([
        [-4.0, 0.0, 0.0, 90.0],
        [0.0, 4.0, 0.0, -126.0],
        [0.0, 0.0, 4.0, -72.0],
        [0.0, 0.0, 0.0, 1.0]
    ], dtype=np.float32)
    
    return nib.Nifti1Image(data, affine=affine)


@pytest.fixture
def invalid_nifti_image_with_nan() -> nib.Nifti1Image:
    """NIfTI image with NaN values (invalid for statistics)."""
    data = np.random.normal(0, 1, MNI_SHAPE).astype(np.float32)
    data[50:60, 50:60, 50:60] = np.nan
    
    affine = np.eye(4)
    return nib.Nifti1Image(data, affine=affine)


@pytest.fixture
def invalid_nifti_image_with_inf() -> nib.Nifti1Image:
    """NIfTI image with infinite values (invalid for statistics)."""
    data = np.random.normal(0, 1, MNI_SHAPE).astype(np.float32)
    data[50:60, 50:60, 50:60] = np.inf
    
    affine = np.eye(4)
    return nib.Nifti1Image(data, affine=affine)


# ============================================================================
# Shared Test Utilities
# ============================================================================

@pytest.fixture
def stats_seed() -> int:
    """Reproducible seed for statistical tests."""
    return 12345


def assert_valid_timeseries(ts: np.ndarray, name: str = "timeseries") -> None:
    """Assert timeseries has no NaN, Inf, or impossible values."""
    assert ts is not None, f"{name} is None"
    assert ts.ndim >= 1, f"{name} has wrong dimensionality"
    assert not np.isnan(ts).any(), f"{name} contains NaN"
    assert not np.isinf(ts).any(), f"{name} contains Inf"


def assert_valid_correlation(r: float, name: str = "correlation") -> None:
    """Assert correlation is in valid range [-1, 1]."""
    assert not np.isnan(r), f"{name} is NaN"
    assert not np.isinf(r), f"{name} is Inf"
    assert -1.0 <= r <= 1.0, f"{name} outside [-1, 1]: {r}"


def assert_valid_pvalue(p: float, name: str = "p-value") -> None:
    """Assert p-value is in valid range [0, 1]."""
    assert not np.isnan(p), f"{name} is NaN"
    assert not np.isinf(p), f"{name} is Inf"
    assert 0.0 <= p <= 1.0, f"{name} outside [0, 1]: {p}"
