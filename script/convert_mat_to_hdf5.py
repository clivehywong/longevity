#!/usr/bin/env python3
"""
Convert exported MATLAB timeseries to HDF5 format for Python analysis.

Usage:
    python convert_mat_to_hdf5.py /path/to/atlas_all_subjects.mat

This script converts the MAT file exported by export_roi_timeseries.m
to HDF5 format that can be easily loaded in Python with h5py or pandas.

Requirements:
    pip install h5py scipy numpy
"""

import sys
import os
import h5py
import numpy as np
from scipy.io import loadmat

def convert_mat_to_hdf5(mat_file):
    """Convert MATLAB .mat file to HDF5 format."""

    if not os.path.exists(mat_file):
        print(f"Error: File not found: {mat_file}")
        sys.exit(1)

    # Output HDF5 file (same name, different extension)
    h5_file = mat_file.replace('.mat', '.h5')

    print(f"Loading MAT file: {mat_file}")
    try:
        # Load MATLAB file
        mat_data = loadmat(mat_file, squeeze_me=False, struct_as_record=False)

        # Extract the 'all_data' structure
        if 'all_data' not in mat_data:
            print("Error: 'all_data' not found in MAT file")
            sys.exit(1)

        all_data = mat_data['all_data']

        # Handle MATLAB struct array (scipy.io loads as object array)
        if isinstance(all_data, np.ndarray) and all_data.dtype == np.object:
            all_data = all_data[0, 0]  # Extract single struct

    except Exception as e:
        print(f"Error loading MAT file: {e}")
        sys.exit(1)

    print(f"Creating HDF5 file: {h5_file}")

    # Create HDF5 file
    with h5py.File(h5_file, 'w') as h5f:

        # Extract metadata
        atlas_name = str(all_data.atlas_name[0]) if hasattr(all_data, 'atlas_name') else 'unknown'
        h5f.attrs['atlas_name'] = atlas_name

        # Extract subject and session lists
        subjects = [str(s[0]) for s in all_data.subjects.flatten()] if hasattr(all_data, 'subjects') else []
        sessions = [str(s[0]) for s in all_data.sessions.flatten()] if hasattr(all_data, 'sessions') else []

        h5f.attrs['n_subjects'] = len(subjects)
        h5f.attrs['n_sessions'] = len(sessions)

        # Create groups for metadata
        meta_group = h5f.create_group('metadata')

        # Save subject and session lists as datasets
        dt = h5py.string_dtype(encoding='utf-8')
        meta_group.create_dataset('subjects', data=subjects, dtype=dt)
        meta_group.create_dataset('sessions', data=sessions, dtype=dt)

        # Save ROI information
        if hasattr(all_data, 'roi_names'):
            roi_names = [str(r[0]) if len(r) > 0 else f'ROI_{i:03d}'
                         for i, r in enumerate(all_data.roi_names.flatten())]
            meta_group.create_dataset('roi_names', data=roi_names, dtype=dt)

        if hasattr(all_data, 'roi_networks'):
            roi_networks = [str(r[0]) if len(r) > 0 else 'Unknown'
                           for r in all_data.roi_networks.flatten()]
            meta_group.create_dataset('roi_networks', data=roi_networks, dtype=dt)

        if hasattr(all_data, 'roi_coords'):
            h5f.create_dataset('metadata/roi_coords', data=all_data.roi_coords)

        # Create timeseries group
        ts_group = h5f.create_group('timeseries')

        # Save timeseries data
        print(f"Saving timeseries data for {len(subjects)} subjects, {len(sessions)} sessions...")

        timeseries_data = all_data.timeseries if hasattr(all_data, 'timeseries') else None

        if timeseries_data is None:
            print("Warning: No timeseries data found")
        else:
            # Iterate through subjects and sessions
            for subj_idx, subject_id in enumerate(subjects):
                subj_group = ts_group.create_group(subject_id)

                for ses_idx, session_id in enumerate(sessions):
                    try:
                        # Extract timeseries for this subject/session
                        # Handle MATLAB cell array indexing
                        ts = timeseries_data[subj_idx, ses_idx]

                        # Check if data exists
                        if ts is None or (isinstance(ts, np.ndarray) and ts.size == 0):
                            print(f"  Warning: No data for {subject_id} {session_id}")
                            continue

                        # Save as dataset
                        subj_group.create_dataset(session_id, data=ts,
                                                  compression='gzip', compression_opts=4)

                    except Exception as e:
                        print(f"  Error saving {subject_id} {session_id}: {e}")
                        continue

    print(f"\nConversion complete!")
    print(f"HDF5 file saved: {h5_file}")
    print(f"\nTo load in Python:")
    print(f"  import h5py")
    print(f"  with h5py.File('{h5_file}', 'r') as f:")
    print(f"      # List subjects")
    print(f"      subjects = list(f['timeseries'].keys())")
    print(f"      # Load timeseries")
    print(f"      ts = f['timeseries']['sub-033']['ses-01'][:]")
    print(f"      # Load ROI names")
    print(f"      roi_names = f['metadata/roi_names'][:].astype(str)")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python convert_mat_to_hdf5.py <mat_file>")
        print("Example: python convert_mat_to_hdf5.py /path/to/schaefer400_all_subjects.mat")
        sys.exit(1)

    mat_file = sys.argv[1]
    convert_mat_to_hdf5(mat_file)
