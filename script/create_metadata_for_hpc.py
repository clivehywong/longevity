#!/usr/bin/env python3
"""
Create Metadata File for Group-Level Analysis

Generates participants_updated.tsv with:
- Subject and session IDs from actual z-map files
- Group assignments from group.csv
- Mean FD from fMRIPrep confounds (if available)
- Age and sex placeholders (to be filled manually)

Usage:
    python script/create_metadata_for_hpc.py

Output:
    derivatives/connectivity-difumo256-hpc/participants_updated.tsv
"""

import pandas as pd
from pathlib import Path
import sys

def main():
    print("=" * 60)
    print("CREATING METADATA FOR GROUP-LEVEL ANALYSIS")
    print("=" * 60)
    print()

    # Paths
    project_dir = Path('.')
    group_file = project_dir / 'group.csv'
    subject_level_dir = project_dir / 'derivatives/connectivity-difumo256-hpc/subject-level/seed_based/motor_cortex'
    fmriprep_dir = project_dir / 'fmriprep'
    output_file = project_dir / 'derivatives/connectivity-difumo256-hpc/participants_updated.tsv'

    # Load group assignments
    if not group_file.exists():
        print(f"ERROR: Group file not found: {group_file}")
        return 1

    group_df = pd.read_csv(group_file)
    group_map = dict(zip(group_df['subject_id'], group_df['group']))
    print(f"Loaded group assignments for {len(group_map)} subjects")
    print()

    # Find all subjects with z-maps
    if not subject_level_dir.exists():
        print(f"ERROR: Subject-level directory not found: {subject_level_dir}")
        return 1

    zmap_files = sorted(subject_level_dir.glob('*_zmap.nii.gz'))
    print(f"Found {len(zmap_files)} z-maps")

    if len(zmap_files) == 0:
        print("ERROR: No z-map files found")
        return 1

    # Extract metadata
    rows = []
    for zmap_file in zmap_files:
        parts = zmap_file.stem.split('_')
        subject = parts[0]
        session = parts[1]

        # Get group
        group = group_map.get(subject, 'Unknown')
        if group == 'Unknown':
            print(f"WARNING: No group assignment for {subject}")

        # Try to get mean_fd from fMRIPrep confounds
        confounds_file = fmriprep_dir / subject / session / 'func' / f'{subject}_{session}_task-rest_desc-confounds_timeseries.tsv'
        mean_fd = None

        if confounds_file.exists():
            try:
                conf_df = pd.read_csv(confounds_file, sep='\t')
                if 'framewise_displacement' in conf_df.columns:
                    mean_fd = conf_df['framewise_displacement'].mean()
            except Exception as e:
                print(f"WARNING: Could not read confounds for {subject} {session}: {e}")

        rows.append({
            'subject': subject,
            'session': session,
            'group': group,
            'age': '',
            'sex': '',
            'mean_fd': mean_fd if mean_fd is not None else ''
        })

    # Create DataFrame
    metadata_df = pd.DataFrame(rows)
    metadata_df = metadata_df.sort_values(['subject', 'session'])

    # Save
    output_file.parent.mkdir(parents=True, exist_ok=True)
    metadata_df.to_csv(output_file, index=False)

    print()
    print("=" * 60)
    print("METADATA FILE CREATED")
    print("=" * 60)
    print(f"Output: {output_file}")
    print()
    print(f"Total observations: {len(metadata_df)}")
    print(f"Subjects: {metadata_df['subject'].nunique()}")
    print()
    print("Group breakdown:")
    print(metadata_df['group'].value_counts().to_string())
    print()
    print("Mean FD availability:")
    fd_available = metadata_df['mean_fd'].notna().sum()
    print(f"  With FD: {fd_available}/{len(metadata_df)}")
    print(f"  Missing FD: {len(metadata_df) - fd_available}/{len(metadata_df)}")
    print()
    print("Age/Sex status:")
    print("  Age: Empty (fill manually if needed)")
    print("  Sex: Empty (fill manually if needed)")
    print()
    print("First 5 rows:")
    print(metadata_df.head().to_string(index=False))
    print()
    print("=" * 60)
    print()
    print("NOTE: Age and sex are left blank. The analysis will automatically")
    print("      drop these covariates since >50% are missing.")
    print()
    print("      If you want to include age/sex in the model, manually fill")
    print(f"      them in {output_file} before running the analysis.")
    print()
    print("=" * 60)

    return 0


if __name__ == '__main__':
    exit(main())
