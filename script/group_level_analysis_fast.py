#!/usr/bin/env python3
"""
Fast Group-Level Statistical Analysis using Parallelized Voxelwise LME

This is an optimized version that uses joblib for parallel processing
across voxels, dramatically reducing computation time.

Usage:
    python group_level_analysis_fast.py \
        --input-maps results/seed_based/dlpfc_l/*_zmap.nii.gz \
        --metadata results/metadata.csv \
        --output results/group_analysis/dlpfc_l \
        --n-jobs 8

Dependencies:
    pip install nibabel nilearn pandas numpy scipy statsmodels joblib
"""

import argparse
import json
import warnings
from pathlib import Path

import nibabel as nib
import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from scipy.ndimage import label as ndimage_label
from nilearn import datasets, image, plotting
from nilearn.masking import apply_mask, unmask
from statsmodels.formula.api import mixedlm
from joblib import Parallel, delayed
import sys

warnings.filterwarnings('ignore')


def fit_single_voxel(v, voxel_data, df_template, formula):
    """Fit LME for a single voxel - designed for parallel execution."""
    df = df_template.copy()
    df['value'] = voxel_data

    # Skip if no variance
    if df['value'].std() < 1e-10:
        return 0.0, 1.0

    try:
        model = mixedlm(formula, data=df, groups=df['subject'])
        fit = model.fit(reml=True, method='nm', disp=False)
        tstat = fit.tvalues.get('group_code:time', 0.0)
        pval = fit.pvalues.get('group_code:time', 1.0)
        return tstat, pval
    except Exception:
        return 0.0, 1.0


def check_covariates(df):
    """Check availability of covariates and determine formula."""
    formula_parts = ['group_code * time']
    included_covariates = []
    warnings_list = []

    # Check age
    if 'age' in df.columns:
        n_valid = df['age'].notna().sum()
        pct = n_valid / len(df) * 100
        if pct >= 50:
            formula_parts.append('age_std')
            included_covariates.append('age_std')
        else:
            warnings_list.append(f"Age dropped: only {pct:.1f}% available")

    # Check sex
    if 'sex' in df.columns:
        n_valid = df['sex'].notna().sum()
        pct = n_valid / len(df) * 100
        if pct >= 50:
            formula_parts.append('sex_code')
            included_covariates.append('sex_code')
        else:
            warnings_list.append(f"Sex dropped: only {pct:.1f}% available")

    # Check mean_fd
    if 'mean_fd' in df.columns:
        n_valid = df['mean_fd'].notna().sum()
        pct = n_valid / len(df) * 100
        if pct >= 50:
            formula_parts.append('mean_fd_std')
            included_covariates.append('mean_fd_std')
        else:
            warnings_list.append(f"MeanFD dropped: only {pct:.1f}% available")

    formula = 'value ~ ' + ' + '.join(formula_parts)
    return formula, included_covariates, warnings_list


def load_maps_and_metadata(input_maps, metadata_file, group_file=None):
    """Load map files and merge with metadata."""
    # Parse map filenames
    records = []
    for map_file in input_maps:
        fname = Path(map_file).name
        parts = fname.replace('_zmap.nii.gz', '').replace('_fALFF.nii.gz', '').replace('_ReHo.nii.gz', '').split('_')
        subject = [p for p in parts if p.startswith('sub-')][0]
        session = [p for p in parts if p.startswith('ses-')][0]
        records.append({'subject': subject, 'session': session, 'map_file': map_file})

    maps_df = pd.DataFrame(records)

    # Load metadata
    meta = pd.read_csv(metadata_file)
    if 'subject_id' in meta.columns:
        meta = meta.rename(columns={'subject_id': 'subject'})

    # Merge
    df = maps_df.merge(meta, on=['subject', 'session'], how='left')

    # Load group file if provided
    if group_file:
        group_df = pd.read_csv(group_file)
        if 'subject_id' in group_df.columns:
            group_df = group_df.rename(columns={'subject_id': 'subject'})
        df = df.merge(group_df[['subject', 'group']], on='subject', how='left', suffixes=('', '_from_file'))
        if 'group_from_file' in df.columns:
            df['group'] = df['group'].fillna(df['group_from_file'])
            df = df.drop(columns=['group_from_file'])

    return df


def voxelwise_lme_parallel(maps_df, mask_img, output_dir, n_jobs=4):
    """
    Perform parallelized voxelwise linear mixed-effects analysis.

    Model: value ~ Group * Time + [Age] + [Sex] + [MeanFD] + (1|Subject)
    """
    print("\nPerforming PARALLELIZED voxelwise LME analysis...")
    print(f"  N observations: {len(maps_df)}")
    print(f"  N subjects: {maps_df['subject'].nunique()}")
    print(f"  N parallel jobs: {n_jobs}")

    # Check covariates
    formula, included_covariates, covariate_warnings = check_covariates(maps_df)

    print(f"\n  Model formula: {formula}")
    if covariate_warnings:
        print("  Covariate warnings:")
        for w in covariate_warnings:
            print(f"    - {w}")

    # Load all maps
    print("\n  Loading maps...", flush=True)
    map_data_list = []
    for i, map_file in enumerate(maps_df['map_file']):
        img = image.load_img(map_file)
        if img.shape != mask_img.shape:
            img = image.resample_to_img(img, mask_img, interpolation='nearest')
        map_data_list.append(apply_mask(img, mask_img))
        if (i + 1) % 10 == 0:
            print(f"    Loaded {i + 1}/{len(maps_df)} maps", flush=True)

    map_data = np.array(map_data_list)  # (n_obs, n_voxels)
    n_obs, n_voxels = map_data.shape
    print(f"  Map data shape: {map_data.shape}")

    # Prepare design variables template
    df_template = maps_df.copy()
    df_template['time'] = df_template['session'].map({'ses-01': 0, 'ses-02': 1})
    df_template['group_code'] = df_template['group'].map({'Control': 0, 'Walking': 1})

    # Handle covariates
    if 'sex_code' in included_covariates:
        df_template['sex_code'] = df_template['sex'].map({'M': 0, 'F': 1, 'U': np.nan})
        df_template['sex_code'] = df_template['sex_code'].fillna(df_template['sex_code'].median())
    else:
        df_template['sex_code'] = 0

    if 'age_std' in included_covariates:
        df_template['age_std'] = (df_template['age'] - df_template['age'].mean()) / df_template['age'].std()
        df_template['age_std'] = df_template['age_std'].fillna(0)
    else:
        df_template['age_std'] = 0

    if 'mean_fd_std' in included_covariates:
        df_template['mean_fd_std'] = (df_template['mean_fd'] - df_template['mean_fd'].mean()) / df_template['mean_fd'].std()
        df_template['mean_fd_std'] = df_template['mean_fd_std'].fillna(0)
    else:
        df_template['mean_fd_std'] = 0

    # Parallel voxelwise fitting
    print(f"\n  Fitting {n_voxels:,} voxels in parallel (n_jobs={n_jobs})...", flush=True)

    # Process in batches for progress reporting
    batch_size = 10000
    n_batches = (n_voxels + batch_size - 1) // batch_size

    all_results = []
    for batch_idx in range(n_batches):
        start_v = batch_idx * batch_size
        end_v = min((batch_idx + 1) * batch_size, n_voxels)

        results = Parallel(n_jobs=n_jobs, backend='loky')(
            delayed(fit_single_voxel)(v, map_data[:, v], df_template, formula)
            for v in range(start_v, end_v)
        )
        all_results.extend(results)

        print(f"    Batch {batch_idx + 1}/{n_batches}: voxels {start_v}-{end_v} complete", flush=True)

    # Extract results
    tstat_values = np.array([r[0] for r in all_results])
    pval_values = np.array([r[1] for r in all_results])

    # Create images
    tstat_img = unmask(tstat_values, mask_img)
    pval_img = unmask(pval_values, mask_img)

    # Save
    tstat_file = output_dir / 'interaction_tstat_map.nii.gz'
    nib.save(tstat_img, tstat_file)
    print(f"\n  Saved T-statistic map: {tstat_file}")

    pval_file = output_dir / 'interaction_pval_map.nii.gz'
    nib.save(pval_img, pval_file)
    print(f"  Saved p-value map: {pval_file}")

    # Model info
    model_info = {
        'formula': formula,
        'included_covariates': included_covariates,
        'covariate_warnings': covariate_warnings,
        'n_observations': n_obs,
        'n_subjects': maps_df['subject'].nunique(),
        'n_voxels': n_voxels
    }

    model_info_file = output_dir / 'model_info.json'
    with open(model_info_file, 'w') as f:
        json.dump(model_info, f, indent=2)

    return tstat_img, pval_img, model_info


def apply_uncorrected_threshold(tstat_img, pval_img, mask_img, output_dir,
                                  p_threshold=0.001, min_cluster_size=50):
    """Apply uncorrected threshold with cluster size filtering."""
    print(f"\n  Applying uncorrected threshold: p < {p_threshold}, k > {min_cluster_size}")

    tstat_data = tstat_img.get_fdata()
    pval_data = pval_img.get_fdata()
    mask_data = mask_img.get_fdata() > 0

    # Threshold: p < threshold AND within brain mask
    sig_mask = (pval_data < p_threshold) & (pval_data > 0) & mask_data

    # Cluster size filtering
    labeled, n_clusters = ndimage_label(sig_mask)
    filtered_mask = np.zeros_like(sig_mask)

    for i in range(1, n_clusters + 1):
        cluster_size = np.sum(labeled == i)
        if cluster_size >= min_cluster_size:
            filtered_mask[labeled == i] = True

    # Create thresholded image
    thresholded_data = np.where(filtered_mask, tstat_data, 0)
    thresholded_img = nib.Nifti1Image(thresholded_data, tstat_img.affine)

    # Save
    thresh_file = output_dir / f'interaction_uncorr_p{str(p_threshold).replace(".", "")}_k{min_cluster_size}.nii.gz'
    nib.save(thresholded_img, thresh_file)

    n_sig_voxels = np.sum(filtered_mask)
    print(f"    Significant voxels: {n_sig_voxels}")

    return thresholded_img, {
        'method': f'uncorrected_p{p_threshold}_k{min_cluster_size}',
        'p_threshold': p_threshold,
        'min_cluster_size': min_cluster_size,
        'n_significant_voxels': int(n_sig_voxels)
    }


def extract_cluster_table(thresholded_img, tstat_img, mask_img, output_dir, min_cluster_size=10, correction_info=None):
    """Extract cluster table with anatomical labels."""
    from nilearn import datasets

    print("\n  Extracting cluster table...")

    thresh_data = thresholded_img.get_fdata()
    tstat_data = tstat_img.get_fdata()
    affine = thresholded_img.affine

    # Label clusters
    binary_mask = np.abs(thresh_data) > 0
    labeled, n_clusters = ndimage_label(binary_mask)

    if n_clusters == 0:
        print("    No clusters found")
        empty_df = pd.DataFrame(columns=['cluster_id', 'size_voxels', 'size_mm3', 'peak_t',
                                          'peak_x', 'peak_y', 'peak_z', 'anatomical_region', 'direction'])
        empty_df.to_csv(output_dir / 'clusters_interaction.csv', index=False)
        return empty_df, {}

    # Load atlas for anatomical labels
    try:
        atlas = datasets.fetch_atlas_harvard_oxford('cort-maxprob-thr25-2mm', symmetric_split=True)
        atlas_img = nib.load(atlas.maps)
        atlas_data = atlas_img.get_fdata()
        atlas_labels = atlas.labels
    except Exception as e:
        print(f"    Warning: Could not load atlas: {e}")
        atlas_data = None
        atlas_labels = None

    # Extract cluster info
    cluster_records = []
    cluster_masks = {}
    voxel_size = np.abs(np.diag(affine[:3, :3]))
    voxel_volume = np.prod(voxel_size)

    for cluster_id in range(1, n_clusters + 1):
        cluster_mask = labeled == cluster_id
        size_voxels = np.sum(cluster_mask)

        if size_voxels < min_cluster_size:
            continue

        # Get t-values in cluster
        cluster_tstats = tstat_data[cluster_mask]

        # Peak voxel
        peak_idx = np.argmax(np.abs(cluster_tstats))
        peak_t = cluster_tstats[peak_idx]

        # Peak coordinates
        cluster_coords = np.array(np.where(cluster_mask)).T
        peak_voxel = cluster_coords[peak_idx]
        peak_mni = nib.affines.apply_affine(affine, peak_voxel)

        # Anatomical label
        if atlas_data is not None:
            try:
                atlas_idx = int(atlas_data[tuple(peak_voxel)])
                if atlas_idx < len(atlas_labels):
                    region = atlas_labels[atlas_idx]
                else:
                    region = 'Unknown'
            except:
                region = 'Unknown'
        else:
            region = 'N/A'

        cluster_records.append({
            'cluster_id': cluster_id,
            'size_voxels': size_voxels,
            'size_mm3': size_voxels * voxel_volume,
            'peak_t': peak_t,
            'peak_x': peak_mni[0],
            'peak_y': peak_mni[1],
            'peak_z': peak_mni[2],
            'anatomical_region': region,
            'direction': 'Walking > Control (increase)' if peak_t > 0 else 'Control > Walking (decrease)'
        })

        cluster_masks[cluster_id] = cluster_mask

    cluster_df = pd.DataFrame(cluster_records)
    if len(cluster_df) > 0:
        cluster_df = cluster_df.sort_values('size_voxels', ascending=False)

    # Save
    cluster_df.to_csv(output_dir / 'clusters_interaction.csv', index=False)
    print(f"    Found {len(cluster_df)} clusters")

    return cluster_df, cluster_masks


def create_visualization(tstat_img, thresholded_img, output_dir, correction_info):
    """Create brain visualizations."""
    print("\n  Creating visualizations...")

    # T-stat map (unthresholded)
    try:
        plotting.plot_stat_map(
            tstat_img,
            title='Group × Time Interaction (T-statistic)',
            output_file=str(output_dir / 'interaction_tstat_ortho.png'),
            display_mode='ortho',
            colorbar=True
        )
        print("    Saved: interaction_tstat_ortho.png")
    except Exception as e:
        print(f"    Warning: Could not create ortho plot: {e}")

    # Thresholded map
    thresh_data = thresholded_img.get_fdata()
    if np.any(thresh_data != 0):
        try:
            plotting.plot_stat_map(
                thresholded_img,
                title=f'Significant clusters ({correction_info.get("method", "thresholded")})',
                output_file=str(output_dir / 'thresholded_map_ortho.png'),
                display_mode='ortho',
                colorbar=True
            )
            print("    Saved: thresholded_map_ortho.png")
        except Exception as e:
            print(f"    Warning: Could not create thresholded plot: {e}")

        try:
            plotting.plot_glass_brain(
                thresholded_img,
                title=f'Significant clusters ({correction_info.get("method", "thresholded")})',
                output_file=str(output_dir / 'thresholded_map_glass.png'),
                colorbar=True
            )
            print("    Saved: thresholded_map_glass.png")
        except Exception as e:
            print(f"    Warning: Could not create glass brain: {e}")
    else:
        print("    No suprathreshold voxels to visualize")


def main():
    parser = argparse.ArgumentParser(
        description="Fast parallelized group-level voxelwise analysis"
    )
    parser.add_argument('--input-maps', nargs='+', required=True,
                        help='Individual subject maps (NIfTI files)')
    parser.add_argument('--metadata', required=True,
                        help='Metadata CSV with subject, session, group, mean_fd')
    parser.add_argument('--group-file',
                        help='Optional group assignments CSV')
    parser.add_argument('--output', required=True,
                        help='Output directory')
    parser.add_argument('--mask',
                        help='Brain mask (default: MNI152 2mm)')
    parser.add_argument('--cluster-threshold', type=float, default=0.05,
                        help='P-value threshold for clustering (default: 0.05)')
    parser.add_argument('--min-cluster-size', type=int, default=50,
                        help='Minimum cluster size in voxels (default: 50)')
    parser.add_argument('--n-jobs', type=int, default=4,
                        help='Number of parallel jobs (default: 4)')

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("FAST PARALLELIZED GROUP-LEVEL ANALYSIS")
    print("=" * 60)
    print(f"Output: {output_dir}")
    print(f"N parallel jobs: {args.n_jobs}")
    sys.stdout.flush()

    # Load mask
    if args.mask:
        mask_img = image.load_img(args.mask)
    else:
        print("\nLoading MNI152 2mm brain mask...")
        from nilearn.datasets import load_mni152_brain_mask
        mask_img = load_mni152_brain_mask(resolution=2)

    # Load maps and metadata
    maps_df = load_maps_and_metadata(
        args.input_maps,
        args.metadata,
        group_file=args.group_file
    )

    print(f"\nLoaded {len(maps_df)} maps")
    print(f"  Subjects: {maps_df['subject'].nunique()}")
    print(f"  Groups: {maps_df['group'].value_counts().to_dict()}")
    sys.stdout.flush()

    if len(maps_df) < 10:
        print("ERROR: Need at least 10 observations")
        return 1

    # Voxelwise LME (parallelized)
    tstat_img, pval_img, model_info = voxelwise_lme_parallel(
        maps_df, mask_img, output_dir, n_jobs=args.n_jobs
    )

    # Apply uncorrected threshold
    thresholded_img, correction_info = apply_uncorrected_threshold(
        tstat_img, pval_img, mask_img, output_dir,
        p_threshold=0.001,
        min_cluster_size=args.min_cluster_size
    )

    # Extract clusters
    cluster_df, cluster_masks = extract_cluster_table(
        thresholded_img, tstat_img, mask_img, output_dir,
        min_cluster_size=args.min_cluster_size,
        correction_info=correction_info
    )

    # Visualizations
    create_visualization(tstat_img, thresholded_img, output_dir, correction_info)

    print("\n" + "=" * 60)
    print("ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Output: {output_dir}")

    if len(cluster_df) > 0:
        print(f"\nSignificant clusters: {len(cluster_df)}")
        print("\nTop clusters:")
        cols = ['cluster_id', 'size_voxels', 'peak_t', 'peak_x', 'peak_y', 'peak_z', 'anatomical_region']
        print(cluster_df[cols].head(5).to_string(index=False))
    else:
        print("\nNo significant clusters found.")

    return 0


if __name__ == '__main__':
    sys.exit(main())
