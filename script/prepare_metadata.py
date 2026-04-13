#!/usr/bin/env python3
"""
Prepare metadata CSV from group assignments and fMRIPrep confounds.

This script creates a comprehensive metadata file for connectivity analysis,
combining group assignments with subject demographics and motion parameters.

Usage:
    python prepare_metadata.py [--fmriprep FMRIPREP_DIR] [--output OUTPUT_FILE]

Output:
    metadata.csv with columns: subject, session, group, age, sex, mean_fd
"""

import argparse
import os
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings('ignore')


def load_group_assignments(group_file):
    """Load group assignments from CSV."""
    df = pd.read_csv(group_file)
    return dict(zip(df['subject_id'], df['group']))


def load_demographics(demographics_file):
    """
    Load demographics from CSV if available.

    Expected columns: subject_id, age, sex
    """
    if demographics_file and Path(demographics_file).exists():
        df = pd.read_csv(demographics_file)
        return df.set_index('subject_id')[['age', 'sex']].to_dict('index')
    return {}


def extract_mean_fd(confounds_file):
    """Extract mean framewise displacement from confounds file."""
    if not Path(confounds_file).exists():
        return None

    df = pd.read_csv(confounds_file, sep='\t')

    if 'framewise_displacement' not in df.columns:
        return None

    # Skip first volume (often NaN for FD)
    fd_values = df['framewise_displacement'].iloc[1:]
    return fd_values.mean()


def create_metadata(fmriprep_dir, group_file, demographics_file=None, output_file=None):
    """
    Create metadata CSV from fMRIPrep outputs and group assignments.

    Parameters
    ----------
    fmriprep_dir : str
        Path to fMRIPrep derivatives directory
    group_file : str
        Path to group.csv with subject_id,group columns
    demographics_file : str, optional
        Path to demographics.csv with subject_id,age,sex columns
    output_file : str, optional
        Output path for metadata.csv

    Returns
    -------
    metadata_df : pd.DataFrame
        Metadata DataFrame
    """

    fmriprep_dir = Path(fmriprep_dir)

    # Load group assignments
    groups = load_group_assignments(group_file)
    print(f"Loaded group assignments for {len(groups)} subjects")

    # Load demographics if available
    demographics = load_demographics(demographics_file)
    if demographics:
        print(f"Loaded demographics for {len(demographics)} subjects")
    else:
        print("No demographics file provided (age, sex will be None)")

    # Find all confounds files
    confounds_pattern = '**/func/*_desc-confounds_timeseries.tsv'
    confounds_files = sorted(fmriprep_dir.glob(confounds_pattern))

    print(f"Found {len(confounds_files)} confounds files")

    # Build metadata
    metadata_rows = []

    for confounds_file in confounds_files:
        # Parse filename
        parts = confounds_file.stem.split('_')
        subject = [p for p in parts if p.startswith('sub-')][0]
        session = [p for p in parts if p.startswith('ses-')][0] if any('ses-' in p for p in parts) else 'ses-01'

        # Skip if not in groups
        if subject not in groups:
            print(f"  Warning: {subject} not in group.csv, skipping")
            continue

        # Get group
        group = groups[subject]

        # Get demographics
        demo = demographics.get(subject, {})
        age = demo.get('age', None)
        sex = demo.get('sex', None)

        # Get mean FD
        mean_fd = extract_mean_fd(confounds_file)

        metadata_rows.append({
            'subject': subject,
            'session': session,
            'group': group,
            'age': age,
            'sex': sex,
            'mean_fd': mean_fd
        })

    # Create DataFrame
    metadata_df = pd.DataFrame(metadata_rows)

    # Sort by subject and session
    metadata_df = metadata_df.sort_values(['subject', 'session']).reset_index(drop=True)

    # Summary statistics
    print("\n" + "="*60)
    print("METADATA SUMMARY")
    print("="*60)
    print(f"Total observations: {len(metadata_df)}")
    print(f"Unique subjects: {metadata_df['subject'].nunique()}")
    print(f"Sessions per subject: {metadata_df.groupby('subject').size().value_counts().to_dict()}")
    print(f"\nGroup distribution:")
    print(metadata_df.groupby('group')['subject'].nunique())

    if metadata_df['mean_fd'].notna().any():
        print(f"\nMean FD statistics:")
        print(f"  Mean: {metadata_df['mean_fd'].mean():.4f} mm")
        print(f"  Median: {metadata_df['mean_fd'].median():.4f} mm")
        print(f"  Range: [{metadata_df['mean_fd'].min():.4f}, {metadata_df['mean_fd'].max():.4f}] mm")
        print(f"  High motion (>0.5mm): {(metadata_df['mean_fd'] > 0.5).sum()} / {len(metadata_df)}")

    # Save
    if output_file:
        output_path = Path(output_file)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_df.to_csv(output_path, index=False)
        print(f"\nMetadata saved: {output_path}")

    return metadata_df


def main():
    parser = argparse.ArgumentParser(
        description="Prepare metadata CSV from group assignments and fMRIPrep outputs"
    )
    parser.add_argument('--fmriprep', type=str,
                        default='/home/clivewong/proj/longevity/fmriprep',
                        help='Path to fMRIPrep derivatives directory')
    parser.add_argument('--group', type=str,
                        default='/home/clivewong/proj/longevity/group.csv',
                        help='Path to group.csv with subject_id,group columns')
    parser.add_argument('--demographics', type=str,
                        help='Path to demographics.csv with subject_id,age,sex columns (optional)')
    parser.add_argument('--output', type=str,
                        default='/home/clivewong/proj/longevity/results/metadata.csv',
                        help='Output path for metadata.csv')

    args = parser.parse_args()

    create_metadata(
        fmriprep_dir=args.fmriprep,
        group_file=args.group,
        demographics_file=args.demographics,
        output_file=args.output
    )


if __name__ == '__main__':
    main()
