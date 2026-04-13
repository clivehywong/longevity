#!/usr/bin/env python3
"""
Create Cluster Barplots for Group-Level Analysis

Extracts mean connectivity values from significant clusters and creates
4-bar plots showing Control Pre/Post and Walking Pre/Post conditions.

Usage:
    python create_cluster_barplots.py \
        --cluster-table results/group_analysis/seed_motor_cortex/clusters_interaction.csv \
        --subject-maps results/seed_based/motor_cortex/*_zmap.nii.gz \
        --metadata results/metadata.csv \
        --output results/group_analysis/seed_motor_cortex/cluster_barplots

Dependencies:
    pip install nibabel nilearn pandas numpy matplotlib seaborn
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import nibabel as nib
import numpy as np
import pandas as pd
import seaborn as sns
from nilearn import image
from nilearn.masking import apply_mask
from scipy import stats
from scipy.ndimage import label as ndimage_label


def load_cluster_masks(cluster_table, thresholded_map, min_cluster_size=10):
    """
    Load or create cluster masks from thresholded map.

    Parameters
    ----------
    cluster_table : pd.DataFrame
        Cluster table from group analysis
    thresholded_map : str or Path
        Path to thresholded statistical map
    min_cluster_size : int
        Minimum cluster size

    Returns
    -------
    cluster_masks : dict
        Dictionary mapping cluster_id to tuple of (mask_data, cluster_info)
    """
    thresh_img = image.load_img(thresholded_map)
    thresh_data = thresh_img.get_fdata()
    affine = thresh_img.affine

    # Label connected components
    labeled_data, n_clusters = ndimage_label(thresh_data != 0)

    # Match clusters to table entries by peak coordinates
    cluster_masks = {}

    for _, row in cluster_table.iterrows():
        cluster_id = row['cluster_id']

        # Find cluster by peak coordinates
        peak_mni = np.array([row['peak_x'], row['peak_y'], row['peak_z']])

        # Convert MNI to voxel coordinates
        from nibabel.affines import apply_affine
        inv_affine = np.linalg.inv(affine)
        peak_voxel = np.round(apply_affine(inv_affine, peak_mni)).astype(int)

        # Get cluster label at peak
        try:
            label_at_peak = labeled_data[tuple(peak_voxel)]
        except IndexError:
            print(f"Warning: Peak for cluster {cluster_id} outside volume, skipping")
            continue

        if label_at_peak == 0:
            print(f"Warning: No cluster at peak for cluster {cluster_id}, skipping")
            continue

        # Create binary mask for this cluster
        mask_data = (labeled_data == label_at_peak).astype(float)

        cluster_info = {
            'cluster_id': cluster_id,
            'size_voxels': int(row['size_voxels']),
            'peak_t': row['peak_t'],
            'peak_mni': peak_mni.tolist(),
            'anatomical_region': row.get('anatomical_region', 'Unknown'),
            'direction': row.get('direction', '')
        }

        cluster_masks[cluster_id] = (mask_data, cluster_info, thresh_img)

    return cluster_masks


def extract_cluster_values(subject_maps, cluster_mask, mask_img, metadata):
    """
    Extract mean values from cluster for each subject/session.

    Parameters
    ----------
    subject_maps : list
        List of paths to subject z-maps
    cluster_mask : ndarray
        Binary cluster mask
    mask_img : Nifti1Image
        Reference image for affine
    metadata : pd.DataFrame
        Metadata with subject, session, group

    Returns
    -------
    values_df : pd.DataFrame
        DataFrame with subject, session, group, value columns
    """
    rows = []

    # Create mask image
    cluster_mask_img = nib.Nifti1Image(cluster_mask, mask_img.affine, mask_img.header)

    for map_file in subject_maps:
        filename = Path(map_file).name
        parts = filename.split('_')

        # Parse subject and session
        subject = [p for p in parts if p.startswith('sub-')]
        session = [p for p in parts if p.startswith('ses-')]

        if not subject:
            continue

        subject = subject[0]
        session = session[0] if session else 'ses-01'

        # Get group from metadata
        meta_row = metadata[(metadata['subject'] == subject) & (metadata['session'] == session)]
        if len(meta_row) == 0:
            continue

        group = meta_row.iloc[0]['group']

        # Load subject map and extract cluster values
        try:
            subj_img = image.load_img(map_file)

            # Resample cluster mask to subject space if needed
            if subj_img.shape != cluster_mask_img.shape:
                resampled_mask = image.resample_to_img(
                    cluster_mask_img, subj_img, interpolation='nearest'
                )
                mask_data = resampled_mask.get_fdata() > 0.5
            else:
                mask_data = cluster_mask > 0.5

            # Extract mean value within cluster
            subj_data = subj_img.get_fdata()
            cluster_values = subj_data[mask_data]
            mean_value = np.nanmean(cluster_values)

            rows.append({
                'subject': subject,
                'session': session,
                'group': group,
                'value': mean_value
            })

        except Exception as e:
            print(f"Warning: Could not extract values for {filename}: {e}")
            continue

    return pd.DataFrame(rows)


def create_barplot(values_df, cluster_info, output_file, seed_name=None):
    """
    Create 4-bar plot for cluster (Control Pre/Post, Walking Pre/Post).

    Parameters
    ----------
    values_df : pd.DataFrame
        Data with group, session, value columns
    cluster_info : dict
        Cluster information
    output_file : str or Path
        Output file path
    seed_name : str, optional
        Name of seed region
    """
    # Prepare data for plotting
    df = values_df.copy()
    df['time'] = df['session'].map({'ses-01': 'Pre', 'ses-02': 'Post'})

    # Compute group means and SEM
    summary = df.groupby(['group', 'time']).agg(
        mean=('value', 'mean'),
        sem=('value', lambda x: stats.sem(x)),
        n=('value', 'count')
    ).reset_index()

    # Set up plot
    fig, ax = plt.subplots(figsize=(8, 6))

    # Define colors
    colors = {
        ('Control', 'Pre'): '#1f77b4',      # Blue
        ('Control', 'Post'): '#6baed6',     # Light blue
        ('Walking', 'Pre'): '#d62728',      # Red
        ('Walking', 'Post'): '#fc9272'      # Light red
    }

    # Create bar positions
    x_positions = [0, 1, 3, 4]
    labels = ['Pre', 'Post', 'Pre', 'Post']

    # Plot bars
    bar_data = []
    for i, (pos, label) in enumerate(zip(x_positions, labels)):
        group = 'Control' if i < 2 else 'Walking'
        time = label

        row = summary[(summary['group'] == group) & (summary['time'] == time)]
        if len(row) > 0:
            mean = row['mean'].values[0]
            sem = row['sem'].values[0]
            color = colors[(group, time)]

            ax.bar(pos, mean, yerr=sem, width=0.8, color=color,
                   edgecolor='black', capsize=5, error_kw={'linewidth': 1.5})
            bar_data.append({'pos': pos, 'mean': mean, 'group': group, 'time': time})

    # Add x-axis labels
    ax.set_xticks([0, 1, 3, 4])
    ax.set_xticklabels(['Pre', 'Post', 'Pre', 'Post'])

    # Add group labels
    ax.text(0.5, ax.get_ylim()[0] - 0.15 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
            'Control', ha='center', fontsize=12, fontweight='bold')
    ax.text(3.5, ax.get_ylim()[0] - 0.15 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
            'Walking', ha='center', fontsize=12, fontweight='bold')

    # Labels and title
    ax.set_ylabel('Mean Fisher Z Connectivity', fontsize=12)

    # Build title
    cluster_id = cluster_info['cluster_id']
    region = cluster_info.get('anatomical_region', 'Unknown')
    peak_mni = cluster_info.get('peak_mni', [0, 0, 0])
    direction = cluster_info.get('direction', '')

    title_parts = []
    if seed_name:
        title_parts.append(f'{seed_name} Seed')
    title_parts.append(f'Cluster {cluster_id}: {region}')
    title_parts.append(f'MNI: ({peak_mni[0]:.0f}, {peak_mni[1]:.0f}, {peak_mni[2]:.0f})')
    if direction:
        title_parts.append(f'[{direction}]')

    ax.set_title('\n'.join(title_parts), fontsize=11)

    # Add significance markers if applicable
    # (Could add statistical test results here)

    # Add legend
    from matplotlib.patches import Patch
    legend_elements = [
        Patch(facecolor='#1f77b4', edgecolor='black', label='Control Pre'),
        Patch(facecolor='#6baed6', edgecolor='black', label='Control Post'),
        Patch(facecolor='#d62728', edgecolor='black', label='Walking Pre'),
        Patch(facecolor='#fc9272', edgecolor='black', label='Walking Post'),
    ]
    ax.legend(handles=legend_elements, loc='upper right', framealpha=0.9)

    # Style
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()

    return summary


def create_roi_barplot(connectivity_df, roi_pair, output_file):
    """
    Create barplot for significant ROI-ROI connection.

    Parameters
    ----------
    connectivity_df : pd.DataFrame
        Connectivity data with subject, session, group, roi_i, roi_j, value
    roi_pair : tuple
        (roi_i_name, roi_j_name)
    output_file : str or Path
        Output file path
    """
    df = connectivity_df.copy()
    df['time'] = df['session'].map({'ses-01': 'Pre', 'ses-02': 'Post'})

    # Compute summary statistics
    summary = df.groupby(['group', 'time']).agg(
        mean=('value', 'mean'),
        sem=('value', lambda x: stats.sem(x)),
        n=('value', 'count')
    ).reset_index()

    # Create plot (same style as cluster barplot)
    fig, ax = plt.subplots(figsize=(8, 6))

    colors = {
        ('Control', 'Pre'): '#1f77b4',
        ('Control', 'Post'): '#6baed6',
        ('Walking', 'Pre'): '#d62728',
        ('Walking', 'Post'): '#fc9272'
    }

    x_positions = [0, 1, 3, 4]
    labels = ['Pre', 'Post', 'Pre', 'Post']

    for i, (pos, label) in enumerate(zip(x_positions, labels)):
        group = 'Control' if i < 2 else 'Walking'
        time = label

        row = summary[(summary['group'] == group) & (summary['time'] == time)]
        if len(row) > 0:
            mean = row['mean'].values[0]
            sem = row['sem'].values[0]
            color = colors[(group, time)]

            ax.bar(pos, mean, yerr=sem, width=0.8, color=color,
                   edgecolor='black', capsize=5, error_kw={'linewidth': 1.5})

    ax.set_xticks([0, 1, 3, 4])
    ax.set_xticklabels(['Pre', 'Post', 'Pre', 'Post'])

    ax.text(0.5, ax.get_ylim()[0] - 0.15 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
            'Control', ha='center', fontsize=12, fontweight='bold')
    ax.text(3.5, ax.get_ylim()[0] - 0.15 * (ax.get_ylim()[1] - ax.get_ylim()[0]),
            'Walking', ha='center', fontsize=12, fontweight='bold')

    ax.set_ylabel('Mean Fisher Z Connectivity', fontsize=12)
    ax.set_title(f'{roi_pair[0]} ↔ {roi_pair[1]}', fontsize=12)

    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches='tight')
    plt.close()


def main():
    parser = argparse.ArgumentParser(
        description="Create cluster barplots for group-level analysis"
    )
    parser.add_argument('--cluster-table', required=True,
                        help='Path to clusters_interaction.csv')
    parser.add_argument('--thresholded-map', required=True,
                        help='Path to thresholded statistical map (nii.gz)')
    parser.add_argument('--subject-maps', nargs='+', required=True,
                        help='Individual subject maps (NIfTI files)')
    parser.add_argument('--metadata', required=True,
                        help='Metadata CSV/TSV with subject, session, group')
    parser.add_argument('--group-file',
                        help='Optional group assignments CSV')
    parser.add_argument('--output', required=True,
                        help='Output directory for barplots')
    parser.add_argument('--seed-name',
                        help='Name of seed region for title')

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("CREATING CLUSTER BARPLOTS")
    print("=" * 60)

    # Load cluster table
    cluster_table = pd.read_csv(args.cluster_table)
    print(f"\nLoaded {len(cluster_table)} clusters")

    if len(cluster_table) == 0:
        print("No clusters to plot. Exiting.")
        return 0

    # Load metadata (auto-detect separator)
    try:
        metadata = pd.read_csv(args.metadata)
    except Exception:
        metadata = pd.read_csv(args.metadata, sep='\t')

    # Supplement with group file if provided
    if args.group_file and Path(args.group_file).exists():
        group_df = pd.read_csv(args.group_file)
        group_map = dict(zip(group_df['subject_id'], group_df['group']))

        # Add group to metadata if missing
        if 'group' not in metadata.columns:
            metadata['group'] = metadata['subject'].map(group_map)
        else:
            # Fill missing groups
            mask = metadata['group'].isna()
            metadata.loc[mask, 'group'] = metadata.loc[mask, 'subject'].map(group_map)

    # Load cluster masks
    cluster_masks = load_cluster_masks(
        cluster_table,
        args.thresholded_map
    )

    print(f"Loaded {len(cluster_masks)} cluster masks")

    # Create barplot for each cluster
    all_summaries = []

    for cluster_id, (mask_data, cluster_info, mask_img) in cluster_masks.items():
        print(f"\nProcessing cluster {cluster_id}: {cluster_info['anatomical_region']}")

        # Extract cluster values for all subjects
        values_df = extract_cluster_values(
            args.subject_maps, mask_data, mask_img, metadata
        )

        if len(values_df) == 0:
            print(f"  Warning: No values extracted for cluster {cluster_id}")
            continue

        print(f"  Extracted values for {len(values_df)} observations")

        # Create barplot
        output_file = output_dir / f'cluster_{cluster_id:02d}_barplot.png'
        summary = create_barplot(
            values_df, cluster_info, output_file, seed_name=args.seed_name
        )

        print(f"  Saved: {output_file}")

        # Store summary
        summary['cluster_id'] = cluster_id
        all_summaries.append(summary)

    # Save combined summary
    if all_summaries:
        combined_summary = pd.concat(all_summaries, ignore_index=True)
        summary_file = output_dir / 'cluster_barplot_summary.csv'
        combined_summary.to_csv(summary_file, index=False)
        print(f"\nSaved summary: {summary_file}")

    print("\n" + "=" * 60)
    print("BARPLOT CREATION COMPLETE")
    print("=" * 60)
    print(f"Output directory: {output_dir}")
    print(f"Barplots created: {len(cluster_masks)}")

    return 0


if __name__ == '__main__':
    exit(main())
