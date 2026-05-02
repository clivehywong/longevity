#!/usr/bin/env python3
"""
Create Metadata File for Group-Level Analysis

Generates participants_updated.tsv with:
- Subject and session IDs from actual z-map files
- Group assignments from bids/participants.tsv (or legacy group.csv)
- Mean FD from fMRIPrep confounds (if available)
- Age and sex from participants.tsv when available

Usage:
    python script/create_metadata_for_hpc.py

Output:
    derivatives/connectivity-difumo256-hpc/participants_updated.tsv
"""

import pandas as pd
from pathlib import Path
import sys


def load_participants_data(project_dir: Path) -> pd.DataFrame:
    """Load BIDS participants.tsv with legacy group.csv fallback."""
    participants_tsv = project_dir / 'bids' / 'participants.tsv'
    legacy_group_csv = project_dir / 'group.csv'

    if participants_tsv.exists():
        df = pd.read_csv(participants_tsv, sep='\t')
    elif legacy_group_csv.exists():
        df = pd.read_csv(legacy_group_csv)
        df.rename(columns={'subject_id': 'participant_id'}, inplace=True)
    else:
        raise FileNotFoundError(
            f"Could not find {participants_tsv} or {legacy_group_csv}"
        )

    return df


def main():
    print("=" * 60)
    print("CREATING METADATA FOR GROUP-LEVEL ANALYSIS")
    print("=" * 60)
    print()

    # Paths
    project_dir = Path('.')
    participants_file = project_dir / 'bids/participants.tsv'
    subject_level_dir = project_dir / 'derivatives/connectivity-difumo256-hpc/subject-level/seed_based/motor_cortex'
    fmriprep_dir = project_dir / 'fmriprep'
    output_file = project_dir / 'derivatives/connectivity-difumo256-hpc/participants_updated.tsv'

    # Load group assignments
    try:
        participants_df = load_participants_data(project_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    participant_map = (
        participants_df
        .rename(columns={'Age': 'age', 'Gender': 'sex'})
        .set_index('participant_id')
        .to_dict('index')
    )
    print(f"Loaded participant data for {len(participant_map)} subjects from {participants_file}")
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

        # Get participant metadata
        participant_info = participant_map.get(subject, {})
        group = participant_info.get('group', 'Unknown')
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
            'age': participant_info.get('age', ''),
            'sex': participant_info.get('sex', ''),
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
    print(f"  Age present: {metadata_df['age'].replace('', pd.NA).notna().sum()}/{len(metadata_df)}")
    print(f"  Sex present: {metadata_df['sex'].replace('', pd.NA).notna().sum()}/{len(metadata_df)}")
    print()
    print("First 5 rows:")
    print(metadata_df.head().to_string(index=False))
    print()
    print("=" * 60)
    print()
    print("NOTE: Age and sex are populated from bids/participants.tsv when available.")
    print("      Missing values can still be filled manually before running analysis.")
    print()
    print(f"      Review {output_file} before running the analysis.")
    print()
    print("=" * 60)

    return 0


if __name__ == '__main__':
    exit(main())
