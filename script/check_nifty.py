#!/usr/bin/env python3
"""
Check NIfTI file integrity with enhanced validation.

Checks for:
1. File readability and corruption
2. File size (minimum threshold)
3. Header validation (affine matrix, voxel dimensions)
4. Data range checks (NaN, Inf, all-zeros)
5. Basic intensity statistics (min, max, mean, std)

Usage:
    python check_nifty.py [bids_directory] [min_size_kb]
"""

import nibabel as nib
import numpy as np
from pathlib import Path
import sys
import json
from datetime import datetime

def format_size(bytes_size):
    """Convert bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} TB"


def validate_nifti_header(img):
    """
    Validate NIfTI header for common issues.

    Returns:
        tuple: (list of issues, dict of header info)
    """
    issues = []
    header = img.header
    affine = img.affine

    header_info = {
        'shape': list(img.shape),
        'voxel_dims': list(header.get_zooms()),
        'data_dtype': str(header.get_data_dtype()),
    }

    # Check for NaN/Inf in affine matrix
    if np.any(np.isnan(affine)):
        issues.append('Affine matrix contains NaN values')
    if np.any(np.isinf(affine)):
        issues.append('Affine matrix contains Inf values')

    # Check for zero or negative voxel dimensions
    zooms = header.get_zooms()
    if any(z <= 0 for z in zooms[:3]):  # First 3 are spatial
        issues.append(f'Invalid voxel dimensions: {zooms[:3]}')

    # Check for extremely large or small voxels (likely units issue)
    spatial_zooms = zooms[:3]
    if any(z > 50 for z in spatial_zooms):
        issues.append(f'Unusually large voxel size: {spatial_zooms} (check units)')
    if any(z < 0.1 for z in spatial_zooms):
        issues.append(f'Unusually small voxel size: {spatial_zooms} (check units)')

    # Check for zero determinant (non-invertible transform)
    det = np.linalg.det(affine[:3, :3])
    if abs(det) < 1e-10:
        issues.append('Affine matrix has near-zero determinant (non-invertible)')

    return issues, header_info


def validate_nifti_data(img, sample_size=None):
    """
    Validate NIfTI data for common issues.

    Args:
        img: nibabel image object
        sample_size: If set, only load a subset of data (for large 4D files)

    Returns:
        tuple: (list of issues, dict of statistics)
    """
    issues = []

    try:
        # For 4D data, only load first volume if sample_size specified
        if len(img.shape) == 4 and sample_size and img.shape[3] > sample_size:
            data = img.dataobj[..., :sample_size]
        else:
            data = img.get_fdata()
    except Exception as e:
        return [f'Failed to load data: {e}'], {}

    # Basic statistics
    stats = {
        'min': float(np.nanmin(data)),
        'max': float(np.nanmax(data)),
        'mean': float(np.nanmean(data)),
        'std': float(np.nanstd(data)),
    }

    # Check for all-zero data
    if np.all(data == 0):
        issues.append('All-zero data (empty image)')

    # Check for NaN values
    nan_count = np.sum(np.isnan(data))
    if nan_count > 0:
        issues.append(f'Contains {nan_count} NaN values ({100*nan_count/data.size:.2f}%)')
        stats['nan_count'] = int(nan_count)

    # Check for Inf values
    inf_count = np.sum(np.isinf(data))
    if inf_count > 0:
        issues.append(f'Contains {inf_count} Inf values')
        stats['inf_count'] = int(inf_count)

    # Check for suspiciously uniform data (potential noise-only image)
    if stats['std'] > 0:
        cv = stats['std'] / abs(stats['mean']) if stats['mean'] != 0 else float('inf')
        stats['coefficient_of_variation'] = float(cv)

        # Very high CV with low mean can indicate noise
        if cv > 10 and stats['mean'] < 100:
            issues.append(f'Possible noise-only image (high CV={cv:.2f}, low mean={stats["mean"]:.2f})')

    # Check for suspicious value ranges
    if stats['max'] == stats['min'] and stats['min'] != 0:
        issues.append(f'Constant value image: all voxels = {stats["min"]}')

    return issues, stats

def check_nifti_files(bids_dir, min_size_kb=10, validate_data=True):
    """
    Check NIfTI files for integrity and data quality issues.

    Args:
        bids_dir: Path to BIDS directory
        min_size_kb: Minimum file size threshold in KB
        validate_data: Whether to perform data validation (slower)
    """
    bids_path = Path(bids_dir)

    # Find all NIfTI files
    nifti_files = list(bids_path.rglob("*.nii")) + list(bids_path.rglob("*.nii.gz"))

    total = len(nifti_files)
    readable = 0
    corrupted = []
    too_small = []
    header_issues = []
    data_issues = []
    all_stats = {}

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_file = f"nifti_check_{timestamp}.log"

    print(f"Checking {total} NIfTI files in: {bids_dir}")
    print(f"Minimum file size: {min_size_kb} KB")
    print(f"Data validation: {'enabled' if validate_data else 'disabled'}\n")

    with open(log_file, 'w') as log:
        log.write(f"NIfTI File Check - {datetime.now()}\n")
        log.write(f"Directory: {bids_dir}\n")
        log.write(f"Minimum size: {min_size_kb} KB\n")
        log.write(f"Data validation: {validate_data}\n\n")

        for i, nifti_file in enumerate(nifti_files, 1):
            file_size = nifti_file.stat().st_size
            file_size_kb = file_size / 1024
            size_str = format_size(file_size)
            rel_path = str(nifti_file.relative_to(bids_path)) if bids_path in nifti_file.parents else str(nifti_file)

            msg = f"[{i}/{total}] Checking: {rel_path}\n  Size: {size_str}"
            print(msg)
            log.write(msg + "\n")

            # Check file size
            if file_size_kb < min_size_kb:
                msg = f"  X TOO SMALL (< {min_size_kb} KB)"
                print(msg)
                log.write(msg + "\n\n")
                too_small.append((rel_path, size_str))
                continue

            # Check readability and header
            try:
                img = nib.load(str(nifti_file))
                shape = img.shape

                # Validate header
                h_issues, h_info = validate_nifti_header(img)
                if h_issues:
                    header_issues.append((rel_path, h_issues))
                    for issue in h_issues:
                        msg = f"  ! HEADER: {issue}"
                        print(msg)
                        log.write(msg + "\n")

                # Validate data if requested
                if validate_data:
                    # Sample first 10 volumes for 4D data to speed up
                    d_issues, stats = validate_nifti_data(img, sample_size=10)
                    if d_issues:
                        data_issues.append((rel_path, d_issues))
                        for issue in d_issues:
                            msg = f"  ! DATA: {issue}"
                            print(msg)
                            log.write(msg + "\n")

                    all_stats[rel_path] = {
                        'shape': list(shape),
                        'header': h_info,
                        'stats': stats
                    }

                if not h_issues and not (validate_data and d_issues):
                    msg = f"  OK (Shape: {shape})"
                else:
                    msg = f"  Shape: {shape}"
                print(msg)
                log.write(msg + "\n\n")
                readable += 1

            except Exception as e:
                msg = f"  X CORRUPTED: {e}"
                print(msg)
                log.write(msg + "\n\n")
                corrupted.append((rel_path, size_str, str(e)))

        # Summary
        summary = "\n" + "="*60 + "\n"
        summary += "Summary:\n"
        summary += f"Total files: {total}\n"
        summary += f"Readable: {readable}\n"
        summary += f"Too small: {len(too_small)}\n"
        summary += f"Corrupted: {len(corrupted)}\n"
        summary += f"Header issues: {len(header_issues)}\n"
        summary += f"Data issues: {len(data_issues)}\n"
        summary += "="*60 + "\n"

        print(summary)
        log.write(summary)

    # Save errors if any
    total_errors = len(corrupted) + len(too_small) + len(header_issues) + len(data_issues)
    if total_errors > 0:
        error_file = f"nifti_errors_{timestamp}.txt"
        with open(error_file, 'w') as f:
            if too_small:
                f.write("TOO SMALL FILES:\n")
                f.write("-" * 60 + "\n")
                for file, size in too_small:
                    f.write(f"{file} (Size: {size})\n")
                f.write("\n")

            if corrupted:
                f.write("CORRUPTED FILES:\n")
                f.write("-" * 60 + "\n")
                for file, size, error in corrupted:
                    f.write(f"{file} (Size: {size})\n")
                    f.write(f"  Error: {error}\n\n")

            if header_issues:
                f.write("HEADER ISSUES:\n")
                f.write("-" * 60 + "\n")
                for file, issues in header_issues:
                    f.write(f"{file}\n")
                    for issue in issues:
                        f.write(f"  - {issue}\n")
                    f.write("\n")

            if data_issues:
                f.write("DATA ISSUES:\n")
                f.write("-" * 60 + "\n")
                for file, issues in data_issues:
                    f.write(f"{file}\n")
                    for issue in issues:
                        f.write(f"  - {issue}\n")
                    f.write("\n")

        print(f"\nX Found {total_errors} problematic file(s).")
        print(f"Error list saved to: {error_file}")
        print(f"Full log saved to: {log_file}")

        # Save stats as JSON
        if validate_data and all_stats:
            stats_file = f"nifti_stats_{timestamp}.json"
            with open(stats_file, 'w') as f:
                json.dump(all_stats, f, indent=2)
            print(f"Statistics saved to: {stats_file}")

        return 1
    else:
        print("\n All NIfTI files are readable and valid!")
        print(f"Full log saved to: {log_file}")

        # Save stats as JSON
        if validate_data and all_stats:
            stats_file = f"nifti_stats_{timestamp}.json"
            with open(stats_file, 'w') as f:
                json.dump(all_stats, f, indent=2)
            print(f"Statistics saved to: {stats_file}")

        return 0

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description='Check NIfTI file integrity with enhanced validation.'
    )
    parser.add_argument('bids_dir', nargs='?', default='/home/clivewong/proj/longevity/bids',
                        help='Path to BIDS directory')
    parser.add_argument('min_size', nargs='?', type=int, default=10,
                        help='Minimum file size in KB (default: 10)')
    parser.add_argument('--no-data-check', action='store_true',
                        help='Skip data validation (faster, header-only check)')

    args = parser.parse_args()

    sys.exit(check_nifti_files(args.bids_dir, args.min_size, validate_data=not args.no_data_check))
