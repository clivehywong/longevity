#!/usr/bin/env python3
"""
Check dimensional consistency across subjects and sessions in BIDS data.

Validates:
- Voxel dimensions consistent across subjects/sessions for each modality
- Volume counts consistent for functional runs
- Matrix dimensions consistent for each modality

Usage:
    python dimensional_consistency.py --bids bids/ --output consistency_report.csv
"""

import os
import sys
import csv
import json
import argparse
import numpy as np
import nibabel as nib
from pathlib import Path
from collections import defaultdict


def extract_bids_entities(filepath):
    """Extract BIDS entities from filepath."""
    parts = Path(filepath).parts
    filename = os.path.basename(filepath)

    entities = {}

    # From directory structure
    for part in parts:
        if part.startswith('sub-'):
            entities['subject'] = part
        elif part.startswith('ses-'):
            entities['session'] = part

    # Modality from filename (last part before extension)
    base = filename
    for ext in ['.nii.gz', '.nii']:
        if base.endswith(ext):
            base = base[:-len(ext)]
            break
    entities['modality'] = base.split('_')[-1]

    # Run number if present
    import re
    run_match = re.search(r'run-(\d+)', filename)
    if run_match:
        entities['run'] = run_match.group(1)

    return entities


def get_image_dimensions(nifti_path):
    """
    Get image dimensions from NIfTI file.

    Returns:
        dict: Image dimensions and metadata
    """
    try:
        img = nib.load(str(nifti_path))
        header = img.header

        dims = {
            'shape': list(img.shape),
            'voxel_dims': [round(float(z), 4) for z in header.get_zooms()[:3]],
            'matrix_size': list(img.shape[:3]),
            'num_volumes': img.shape[3] if len(img.shape) == 4 else 1,
            'data_dtype': str(header.get_data_dtype())
        }

        return dims, None

    except Exception as e:
        return None, str(e)


def check_voxel_dimensions(bids_dir, target_modalities=None):
    """
    Check voxel dimensions are consistent across subjects/sessions.

    Args:
        bids_dir: Path to BIDS directory
        target_modalities: List of modalities to check (default: all)

    Returns:
        dict: Deviations from expected dimensions
    """
    bids_path = Path(bids_dir)
    nifti_files = list(bids_path.rglob("*.nii.gz")) + list(bids_path.rglob("*.nii"))

    # Group files by modality
    by_modality = defaultdict(list)
    for f in nifti_files:
        entities = extract_bids_entities(str(f))
        modality = entities.get('modality', 'unknown')
        if target_modalities and modality not in target_modalities:
            continue
        by_modality[modality].append(f)

    deviations = []
    expected_dims = {}

    for modality, files in by_modality.items():
        voxel_dims_list = []

        for f in files:
            dims, error = get_image_dimensions(f)
            if error:
                continue
            voxel_dims_list.append((f, dims['voxel_dims']))

        if not voxel_dims_list:
            continue

        # Find mode (most common voxel dimensions)
        from collections import Counter
        dims_tuples = [tuple(d) for _, d in voxel_dims_list]
        most_common = Counter(dims_tuples).most_common(1)[0][0]
        expected_dims[modality] = list(most_common)

        # Find deviations
        for f, dims in voxel_dims_list:
            if tuple(dims) != most_common:
                entities = extract_bids_entities(str(f))
                deviations.append({
                    'file': str(f.relative_to(bids_path)),
                    'subject': entities.get('subject', ''),
                    'session': entities.get('session', ''),
                    'modality': modality,
                    'issue_type': 'voxel_dimension',
                    'observed': dims,
                    'expected': list(most_common)
                })

    return deviations, expected_dims


def check_volume_counts(bids_dir):
    """
    Verify functional runs have consistent volume counts.

    Args:
        bids_dir: Path to BIDS directory

    Returns:
        list: Volume count deviations
    """
    bids_path = Path(bids_dir)

    # Find functional files
    func_files = []
    for f in bids_path.rglob("*_bold.nii.gz"):
        func_files.append(f)
    for f in bids_path.rglob("*_bold.nii"):
        func_files.append(f)

    deviations = []
    volume_counts = defaultdict(list)

    for f in func_files:
        entities = extract_bids_entities(str(f))
        dims, error = get_image_dimensions(f)
        if error:
            continue

        # Group by task (if present in filename)
        import re
        task_match = re.search(r'task-([a-zA-Z0-9]+)', f.name)
        task = task_match.group(1) if task_match else 'unknown'

        key = (entities.get('modality', 'bold'), task)
        volume_counts[key].append((f, dims['num_volumes']))

    # Find expected volume count (mode) for each task
    for key, counts in volume_counts.items():
        from collections import Counter
        count_values = [c for _, c in counts]
        most_common = Counter(count_values).most_common(1)[0][0]

        for f, count in counts:
            if count != most_common:
                entities = extract_bids_entities(str(f))
                deviations.append({
                    'file': str(f.relative_to(bids_path)),
                    'subject': entities.get('subject', ''),
                    'session': entities.get('session', ''),
                    'modality': key[0],
                    'task': key[1],
                    'issue_type': 'volume_count',
                    'observed': count,
                    'expected': most_common
                })

    return deviations


def check_matrix_dimensions(bids_dir, target_modalities=None):
    """
    Check image matrix size consistency.

    Args:
        bids_dir: Path to BIDS directory
        target_modalities: List of modalities to check

    Returns:
        list: Matrix dimension deviations
    """
    bids_path = Path(bids_dir)
    nifti_files = list(bids_path.rglob("*.nii.gz")) + list(bids_path.rglob("*.nii"))

    # Group files by modality
    by_modality = defaultdict(list)
    for f in nifti_files:
        entities = extract_bids_entities(str(f))
        modality = entities.get('modality', 'unknown')
        if target_modalities and modality not in target_modalities:
            continue
        by_modality[modality].append(f)

    deviations = []

    for modality, files in by_modality.items():
        matrix_dims_list = []

        for f in files:
            dims, error = get_image_dimensions(f)
            if error:
                continue
            matrix_dims_list.append((f, dims['matrix_size']))

        if not matrix_dims_list:
            continue

        # Find mode
        from collections import Counter
        dims_tuples = [tuple(d) for _, d in matrix_dims_list]
        most_common = Counter(dims_tuples).most_common(1)[0][0]

        for f, dims in matrix_dims_list:
            if tuple(dims) != most_common:
                entities = extract_bids_entities(str(f))
                deviations.append({
                    'file': str(f.relative_to(bids_path)),
                    'subject': entities.get('subject', ''),
                    'session': entities.get('session', ''),
                    'modality': modality,
                    'issue_type': 'matrix_dimension',
                    'observed': dims,
                    'expected': list(most_common)
                })

    return deviations


def run_all_checks(bids_dir, output_path):
    """
    Run all dimensional consistency checks.

    Args:
        bids_dir: Path to BIDS directory
        output_path: Path to output CSV file
    """
    print("=" * 60)
    print("Dimensional Consistency Check")
    print("=" * 60)
    print(f"BIDS directory: {bids_dir}\n")

    all_deviations = []

    # Check voxel dimensions
    print("Checking voxel dimensions...")
    voxel_devs, expected_voxels = check_voxel_dimensions(bids_dir)
    all_deviations.extend(voxel_devs)
    print(f"  Found {len(voxel_devs)} voxel dimension inconsistencies")

    # Check volume counts
    print("Checking volume counts...")
    volume_devs = check_volume_counts(bids_dir)
    all_deviations.extend(volume_devs)
    print(f"  Found {len(volume_devs)} volume count inconsistencies")

    # Check matrix dimensions
    print("Checking matrix dimensions...")
    matrix_devs = check_matrix_dimensions(bids_dir)
    all_deviations.extend(matrix_devs)
    print(f"  Found {len(matrix_devs)} matrix dimension inconsistencies")

    # Write CSV output
    if all_deviations:
        with open(output_path, 'w', newline='') as f:
            fieldnames = ['file', 'subject', 'session', 'modality', 'issue_type',
                         'observed', 'expected', 'task']
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for dev in all_deviations:
                # Convert lists to strings for CSV
                dev_copy = dev.copy()
                if isinstance(dev_copy.get('observed'), list):
                    dev_copy['observed'] = str(dev_copy['observed'])
                if isinstance(dev_copy.get('expected'), list):
                    dev_copy['expected'] = str(dev_copy['expected'])
                writer.writerow(dev_copy)

        print(f"\nReport saved to: {output_path}")

    # Print summary
    print("\n" + "=" * 60)
    print("Summary:")
    print(f"  Voxel dimension issues: {len(voxel_devs)}")
    print(f"  Volume count issues: {len(volume_devs)}")
    print(f"  Matrix dimension issues: {len(matrix_devs)}")
    print(f"  Total issues: {len(all_deviations)}")
    print("=" * 60)

    if expected_voxels:
        print("\nExpected voxel dimensions by modality:")
        for mod, dims in expected_voxels.items():
            print(f"  {mod}: {dims}")

    # Also save as JSON for detailed info
    json_path = str(output_path).replace('.csv', '.json')
    with open(json_path, 'w') as f:
        json.dump({
            'deviations': all_deviations,
            'expected_voxel_dims': expected_voxels,
            'summary': {
                'voxel_issues': len(voxel_devs),
                'volume_issues': len(volume_devs),
                'matrix_issues': len(matrix_devs),
                'total': len(all_deviations)
            }
        }, f, indent=2)
    print(f"\nJSON details saved to: {json_path}")

    return all_deviations


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='Check dimensional consistency in BIDS neuroimaging data.'
    )
    parser.add_argument('--bids', required=True,
                        help='Path to BIDS directory')
    parser.add_argument('--output', required=True,
                        help='Path to output CSV file')

    args = parser.parse_args()

    if not os.path.exists(args.bids):
        print(f"Error: BIDS directory not found: {args.bids}")
        sys.exit(1)

    deviations = run_all_checks(args.bids, args.output)
    sys.exit(1 if deviations else 0)
