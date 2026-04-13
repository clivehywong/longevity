"""
Visualization Utilities

Montage generation for different imaging modalities.
Now with smart caching integration for faster loading.

Implementation: Phase 2 ✅
Updated: Added image caching support (Phase 3)
"""

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
from pathlib import Path
from typing import Optional

# Import generator functions from qa_image_generator
from utils.qa_image_generator import (
    generate_anat_montage as _generate_anat_montage,
    generate_func_timepoints as _generate_func_timepoints,
    generate_func_quality as _generate_func_quality,
    generate_dwi_montage as _generate_dwi_montage,
    generate_fmap_montage as _generate_fmap_montage
)


def get_cache_if_available(bids_dir: Optional[Path] = None):
    """
    Get image cache if available and BIDS dir is known.

    Returns:
        ImageCache instance or None
    """
    if bids_dir is None:
        return None

    try:
        from utils.image_cache import get_image_cache
        return get_image_cache(bids_dir)
    except Exception:
        return None


def plot_t1w_montage(nifti_path: Path, use_cache: bool = True, bids_dir: Optional[Path] = None) -> Optional[plt.Figure]:
    """
    Generate 7 axial + 7 sagittal slice montage for T1w/T2w.

    Args:
        nifti_path: Path to NIfTI file
        use_cache: Whether to use disk cache (default: True)
        bids_dir: BIDS directory path (required for caching)

    Returns:
        matplotlib Figure or None on error
    """
    cache = get_cache_if_available(bids_dir) if use_cache else None

    if cache is not None:
        try:
            return cache.get_cached_image(nifti_path, 'anat', _generate_anat_montage)
        except Exception as e:
            print(f"Cache error, falling back to direct generation: {e}")

    # Direct generation (no cache)
    return _generate_anat_montage(nifti_path)


# Alias for backwards compatibility
plot_anat_montage = plot_t1w_montage


def plot_functional_timepoints(nifti_path: Path, use_cache: bool = True, bids_dir: Optional[Path] = None) -> Optional[plt.Figure]:
    """
    Generate 3 timepoints x 3 views montage for BOLD.

    Args:
        nifti_path: Path to NIfTI file
        use_cache: Whether to use disk cache (default: True)
        bids_dir: BIDS directory path (required for caching)

    Returns:
        matplotlib Figure or None on error
    """
    cache = get_cache_if_available(bids_dir) if use_cache else None

    if cache is not None:
        try:
            return cache.get_cached_image(nifti_path, 'func_timepoints', _generate_func_timepoints)
        except Exception as e:
            print(f"Cache error, falling back to direct generation: {e}")

    return _generate_func_timepoints(nifti_path)


def plot_functional_quality_maps(nifti_path: Path, use_cache: bool = True, bids_dir: Optional[Path] = None) -> Optional[plt.Figure]:
    """
    Generate Mean, Std, tSNR maps for BOLD quality assessment.

    Args:
        nifti_path: Path to NIfTI file
        use_cache: Whether to use disk cache (default: True)
        bids_dir: BIDS directory path (required for caching)

    Returns:
        matplotlib Figure or None on error
    """
    cache = get_cache_if_available(bids_dir) if use_cache else None

    if cache is not None:
        try:
            return cache.get_cached_image(nifti_path, 'func_quality', _generate_func_quality)
        except Exception as e:
            print(f"Cache error, falling back to direct generation: {e}")

    return _generate_func_quality(nifti_path)


def plot_dwi_montage(nifti_path: Path, use_cache: bool = True, bids_dir: Optional[Path] = None) -> Optional[plt.Figure]:
    """
    Generate DWI montage showing b0 and high-b volumes.

    Args:
        nifti_path: Path to NIfTI file
        use_cache: Whether to use disk cache (default: True)
        bids_dir: BIDS directory path (required for caching)

    Returns:
        matplotlib Figure or None on error
    """
    cache = get_cache_if_available(bids_dir) if use_cache else None

    if cache is not None:
        try:
            return cache.get_cached_image(nifti_path, 'dwi', _generate_dwi_montage)
        except Exception as e:
            print(f"Cache error, falling back to direct generation: {e}")

    return _generate_dwi_montage(nifti_path)


def plot_fmap_comparison(ap_path: Path, pa_path: Path = None, use_cache: bool = True, bids_dir: Optional[Path] = None) -> Optional[plt.Figure]:
    """
    Generate field map montage (AP alone or AP/PA comparison).

    Args:
        ap_path: Path to AP field map NIfTI file
        pa_path: Optional path to PA field map
        use_cache: Whether to use disk cache (default: True)
        bids_dir: BIDS directory path (required for caching)

    Returns:
        matplotlib Figure or None on error
    """
    # Note: Caching for fmap with PA comparison is complex, so we use direct generation
    # for the paired case and cache only single fmap
    if pa_path is not None:
        return _generate_fmap_montage(ap_path, pa_path)

    cache = get_cache_if_available(bids_dir) if use_cache else None

    if cache is not None:
        try:
            return cache.get_cached_image(ap_path, 'fmap', _generate_fmap_montage)
        except Exception as e:
            print(f"Cache error, falling back to direct generation: {e}")

    return _generate_fmap_montage(ap_path)
