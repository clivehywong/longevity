#!/usr/bin/env python3
"""
Compare seed-based connectivity z-maps from local and HPC runs.
For overlapping maps, check numerical similarity.
"""

import nibabel as nib
import numpy as np
from pathlib import Path
import pandas as pd

def compare_zmaps(local_dir, hpc_dir, output_csv=None):
    """
    Compare z-maps from local and HPC runs.

    Parameters:
    -----------
    local_dir : str or Path
        Directory with local z-maps
    hpc_dir : str or Path
        Directory with HPC z-maps
    output_csv : str, optional
        Path to save comparison results

    Returns:
    --------
    DataFrame with comparison results
    """
    local_dir = Path(local_dir)
    hpc_dir = Path(hpc_dir)

    # Find all local z-maps
    local_maps = sorted(local_dir.glob('*/*_zmap.nii.gz'))

    print(f"Found {len(local_maps)} local z-maps")

    results = []
    missing_in_hpc = []

    for local_path in local_maps:
        # Construct corresponding HPC path
        seed_name = local_path.parent.name
        zmap_name = local_path.name
        hpc_path = hpc_dir / seed_name / zmap_name

        if not hpc_path.exists():
            missing_in_hpc.append(str(local_path.relative_to(local_dir)))
            continue

        # Load both maps
        local_img = nib.load(local_path)
        hpc_img = nib.load(hpc_path)

        local_data = local_img.get_fdata()
        hpc_data = hpc_img.get_fdata()

        # Compute comparison metrics
        diff = local_data - hpc_data
        abs_diff = np.abs(diff)

        # Correlation
        mask = ~(np.isnan(local_data) | np.isnan(hpc_data))
        if mask.sum() > 0:
            correlation = np.corrcoef(
                local_data[mask].flatten(),
                hpc_data[mask].flatten()
            )[0, 1]
        else:
            correlation = np.nan

        results.append({
            'seed': seed_name,
            'file': zmap_name,
            'max_abs_diff': np.nanmax(abs_diff),
            'mean_abs_diff': np.nanmean(abs_diff),
            'median_abs_diff': np.nanmedian(abs_diff),
            'std_diff': np.nanstd(diff),
            'correlation': correlation,
            'local_mean': np.nanmean(local_data),
            'hpc_mean': np.nanmean(hpc_data),
            'local_std': np.nanstd(local_data),
            'hpc_std': np.nanstd(hpc_data)
        })

    # Create DataFrame
    df = pd.DataFrame(results)

    # Print summary
    print(f"\n{'='*70}")
    print("COMPARISON SUMMARY")
    print(f"{'='*70}")
    print(f"\nCompared {len(df)} z-maps")

    if missing_in_hpc:
        print(f"\n⚠️  Missing in HPC: {len(missing_in_hpc)}")
        for m in missing_in_hpc[:5]:
            print(f"    - {m}")
        if len(missing_in_hpc) > 5:
            print(f"    ... and {len(missing_in_hpc) - 5} more")

    print(f"\n{'Metric':<20} {'Mean':<12} {'Median':<12} {'Max':<12}")
    print(f"{'-'*60}")
    print(f"{'Max abs diff':<20} {df['max_abs_diff'].mean():<12.6f} "
          f"{df['max_abs_diff'].median():<12.6f} {df['max_abs_diff'].max():<12.6f}")
    print(f"{'Mean abs diff':<20} {df['mean_abs_diff'].mean():<12.6f} "
          f"{df['mean_abs_diff'].median():<12.6f} {df['mean_abs_diff'].max():<12.6f}")
    print(f"{'Correlation':<20} {df['correlation'].mean():<12.6f} "
          f"{df['correlation'].median():<12.6f} {df['correlation'].min():<12.6f}")

    print(f"\n{'Seed':<25} {'N maps':<8} {'Mean corr':<12} {'Mean abs diff':<15}")
    print(f"{'-'*65}")
    for seed in df['seed'].unique():
        seed_df = df[df['seed'] == seed]
        print(f"{seed:<25} {len(seed_df):<8} "
              f"{seed_df['correlation'].mean():<12.6f} "
              f"{seed_df['mean_abs_diff'].mean():<15.6f}")

    # Check for mismatches
    threshold = 1e-3  # 0.001 difference threshold
    mismatches = df[df['max_abs_diff'] > threshold]

    if len(mismatches) > 0:
        print(f"\n⚠️  {len(mismatches)} maps with max difference > {threshold}")
        print(f"\nTop 5 largest differences:")
        top_diffs = df.nlargest(5, 'max_abs_diff')[['seed', 'file', 'max_abs_diff', 'correlation']]
        print(top_diffs.to_string(index=False))
    else:
        print(f"\n✅ All maps match within threshold ({threshold})")

    # Save to CSV
    if output_csv:
        df.to_csv(output_csv, index=False)
        print(f"\n💾 Results saved to: {output_csv}")

    return df

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Compare local and HPC z-maps')
    parser.add_argument('--local', default='derivatives/connectivity-difumo256/subject-level/seed_based',
                        help='Local z-maps directory')
    parser.add_argument('--hpc', default='derivatives/connectivity-difumo256-hpc/subject-level/seed_based',
                        help='HPC z-maps directory')
    parser.add_argument('--output', default='logs/zmap_comparison.csv',
                        help='Output CSV file')

    args = parser.parse_args()

    compare_zmaps(args.local, args.hpc, args.output)
