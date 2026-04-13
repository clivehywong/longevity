#!/usr/bin/env python3
"""
Convert extracted TSV timeseries to HDF5 format.

The extract_timeseries.py script outputs TSV files, but python_connectivity_analysis.py
expects HDF5 format. This script performs the conversion.

Usage:
    python convert_tsv_to_hdf5.py --timeseries-dir TIMESERIES_DIR --output OUTPUT_H5 --atlas ATLAS_NAME

Output HDF5 structure:
    /subject/session/timeseries  [n_volumes × n_rois]

Example:
    python convert_tsv_to_hdf5.py \
        --timeseries-dir timeseries/difumo256 \
        --output results/timeseries_difumo256.h5 \
        --atlas difumo256
"""

import argparse
import warnings
from pathlib import Path

import h5py
import numpy as np
import pandas as pd

warnings.filterwarnings('ignore')


def convert_timeseries_to_hdf5(timeseries_dir, output_h5, atlas_name, verbose=True):
    """
    Convert TSV timeseries files to HDF5 format.

    Parameters
    ----------
    timeseries_dir : str or Path
        Directory containing *_timeseries.tsv files
    output_h5 : str or Path
        Output HDF5 file path
    atlas_name : str
        Name of atlas (stored as metadata)
    verbose : bool
        Print progress information

    Returns
    -------
    n_files : int
        Number of timeseries files converted
    """

    ts_dir = Path(timeseries_dir)
    output_h5 = Path(output_h5)

    # Create output directory
    output_h5.parent.mkdir(parents=True, exist_ok=True)

    # Find all timeseries files
    ts_files = sorted(ts_dir.glob('*_timeseries.tsv'))

    if len(ts_files) == 0:
        print(f"ERROR: No timeseries files found in {ts_dir}")
        print(f"Expected pattern: *_timeseries.tsv")
        return 0

    if verbose:
        print(f"Found {len(ts_files)} timeseries files")
        print(f"Output: {output_h5}")

    # Create HDF5 file
    with h5py.File(output_h5, 'w') as f:
        # Store atlas metadata
        f.attrs['atlas_name'] = atlas_name
        f.attrs['n_files'] = len(ts_files)

        for i, ts_file in enumerate(ts_files, 1):
            # Parse filename: sub-XXX_ses-XX_task-rest_atlas-NAME_timeseries.tsv
            parts = ts_file.stem.split('_')
            subject = [p for p in parts if p.startswith('sub-')][0]
            session = [p for p in parts if p.startswith('ses-')][0] if any('ses-' in p for p in parts) else 'ses-01'

            # Load timeseries
            ts_data = pd.read_csv(ts_file, sep='\t')

            # Convert to numpy array (n_volumes × n_rois)
            ts_array = ts_data.values

            # Create HDF5 structure: /subject/session/timeseries
            if subject not in f:
                f.create_group(subject)

            subj_group = f[subject]

            # Store timeseries with compression
            dataset_path = f'{session}/timeseries'
            subj_group.create_dataset(
                dataset_path,
                data=ts_array,
                compression='gzip',
                compression_opts=4
            )

            # Store metadata
            subj_group[session].attrs['shape'] = ts_array.shape
            subj_group[session].attrs['n_volumes'] = ts_array.shape[0]
            subj_group[session].attrs['n_rois'] = ts_array.shape[1]
            subj_group[session].attrs['roi_labels'] = list(ts_data.columns)

            if verbose:
                print(f"  [{i:2d}/{len(ts_files)}] {subject}/{session}: {ts_array.shape[0]} volumes × {ts_array.shape[1]} ROIs")

    if verbose:
        print(f"\n✓ HDF5 saved: {output_h5}")
        print(f"  Total size: {output_h5.stat().st_size / 1024**2:.1f} MB")

    return len(ts_files)


def verify_hdf5(h5_file, verbose=True):
    """
    Verify HDF5 file structure and contents.

    Parameters
    ----------
    h5_file : str or Path
        HDF5 file to verify
    verbose : bool
        Print verification details

    Returns
    -------
    is_valid : bool
        Whether file structure is valid
    """

    h5_file = Path(h5_file)

    if not h5_file.exists():
        print(f"ERROR: File not found: {h5_file}")
        return False

    try:
        with h5py.File(h5_file, 'r') as f:
            atlas_name = f.attrs.get('atlas_name', 'unknown')
            n_files = f.attrs.get('n_files', 0)

            subjects = list(f.keys())
            n_subjects = len(subjects)

            # Count sessions
            total_sessions = 0
            for subject in subjects:
                sessions = list(f[subject].keys())
                total_sessions += len(sessions)

            if verbose:
                print(f"\n{'='*60}")
                print(f"HDF5 VERIFICATION: {h5_file.name}")
                print(f"{'='*60}")
                print(f"Atlas: {atlas_name}")
                print(f"Files converted: {n_files}")
                print(f"Subjects: {n_subjects}")
                print(f"Total sessions: {total_sessions}")

                # Sample a few entries
                print(f"\nSample entries:")
                for subject in subjects[:3]:
                    for session in f[subject].keys():
                        ts_shape = f[subject][session]['timeseries'].shape
                        print(f"  {subject}/{session}: {ts_shape[0]} volumes × {ts_shape[1]} ROIs")

                if n_subjects > 3:
                    print(f"  ... ({n_subjects - 3} more subjects)")

        return True

    except Exception as e:
        print(f"ERROR verifying HDF5: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert TSV timeseries to HDF5 format for connectivity analysis"
    )
    parser.add_argument('--timeseries-dir', type=str, required=True,
                        help='Directory containing *_timeseries.tsv files')
    parser.add_argument('--output', type=str, required=True,
                        help='Output HDF5 file path')
    parser.add_argument('--atlas', type=str, required=True,
                        help='Atlas name (e.g., difumo256, schaefer400_7net)')
    parser.add_argument('--verify', action='store_true',
                        help='Verify HDF5 file after creation')
    parser.add_argument('--quiet', action='store_true',
                        help='Suppress progress messages')

    args = parser.parse_args()

    verbose = not args.quiet

    # Convert
    n_files = convert_timeseries_to_hdf5(
        timeseries_dir=args.timeseries_dir,
        output_h5=args.output,
        atlas_name=args.atlas,
        verbose=verbose
    )

    if n_files == 0:
        print("\nERROR: No files converted. Check timeseries directory.")
        return 1

    # Verify if requested
    if args.verify:
        is_valid = verify_hdf5(args.output, verbose=verbose)
        if not is_valid:
            print("\nERROR: HDF5 verification failed")
            return 1

    if verbose:
        print("\n✓ Conversion complete!")

    return 0


if __name__ == '__main__':
    exit(main())
