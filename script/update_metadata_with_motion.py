#!/usr/bin/env python3
"""
Update metadata file with motion QC info from seed connectivity output.

This script reads the individual_maps.csv file from seed-based connectivity
output and merges the mean_fd values into the main metadata file.

Usage:
    python update_metadata_with_motion.py \
        --metadata derivatives/connectivity-difumo256/participants_all24.csv \
        --seed-csv derivatives/connectivity-difumo256/subject-level/seed_based/dlpfc_l/individual_maps.csv \
        --output derivatives/connectivity-difumo256/participants_all24_with_motion.csv
"""

import argparse
import pandas as pd
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Update metadata with motion QC from seed connectivity output"
    )
    parser.add_argument('--metadata', required=True,
                        help='Input metadata CSV file')
    parser.add_argument('--seed-csv', required=True,
                        help='individual_maps.csv from seed connectivity output')
    parser.add_argument('--output', required=True,
                        help='Output metadata CSV file with motion info')

    args = parser.parse_args()

    # Load metadata
    print(f"Loading metadata from {args.metadata}...")
    metadata = pd.read_csv(args.metadata)
    print(f"  Loaded {len(metadata)} sessions")

    # Load seed motion data
    print(f"\nLoading motion data from {args.seed_csv}...")
    seed_data = pd.read_csv(args.seed_csv)
    print(f"  Loaded {len(seed_data)} sessions")

    # Merge on subject and session
    print("\nMerging motion data into metadata...")
    metadata_updated = metadata.merge(
        seed_data[['subject', 'session', 'mean_fd', 'n_scrubbed', 'scrub_pct']],
        on=['subject', 'session'],
        how='left',
        suffixes=('', '_seed')
    )

    # Use seed motion data if metadata mean_fd is empty
    if 'mean_fd_seed' in metadata_updated.columns:
        metadata_updated['mean_fd'] = metadata_updated['mean_fd_seed'].fillna(
            metadata_updated['mean_fd']
        )
        metadata_updated = metadata_updated.drop('mean_fd_seed', axis=1)

    # Save
    metadata_updated.to_csv(args.output, index=False)
    print(f"\nSaved updated metadata to {args.output}")
    print(f"  Total sessions: {len(metadata_updated)}")
    print(f"  Sessions with motion data: {metadata_updated['mean_fd'].notna().sum()}")

    # Show motion summary
    if 'mean_fd' in metadata_updated.columns:
        print(f"\nMotion QC summary:")
        print(f"  Mean FD: {metadata_updated['mean_fd'].mean():.3f} ± {metadata_updated['mean_fd'].std():.3f} mm")
        print(f"  Range: {metadata_updated['mean_fd'].min():.3f} - {metadata_updated['mean_fd'].max():.3f} mm")

        if 'scrub_pct' in metadata_updated.columns:
            print(f"  Mean scrubbed: {metadata_updated['scrub_pct'].mean():.1f}%")


if __name__ == '__main__':
    main()
