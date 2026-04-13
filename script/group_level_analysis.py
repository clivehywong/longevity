#!/usr/bin/env python3
"""
Group-Level Statistical Analysis for Longitudinal Walking Intervention Study

Performs voxelwise linear mixed-effects analysis on whole-brain maps:
- fALFF, ReHo, seed-based connectivity maps
- Model: value ~ Group * Time + Age + Sex + MeanFD + (1|Subject)
  (Covariates are dropped if >50% missing)
- Cluster correction via permutation testing with TFCE
- Fallback to uncorrected p < 0.001 + k > 50 voxels if no FWE results
- Cluster table extraction with anatomical labels

Usage:
    python group_level_analysis.py \
        --input-maps results/local_measures/*_fALFF.nii.gz \
        --metadata results/metadata.csv \
        --output results/group_analysis/fALFF \
        --cluster-threshold 0.05

Dependencies:
    pip install nibabel nilearn pandas numpy scipy statsmodels
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
from nilearn.glm.second_level import SecondLevelModel, non_parametric_inference
from nilearn.masking import apply_mask, unmask
from statsmodels.formula.api import mixedlm

warnings.filterwarnings('ignore')


def check_covariates(df):
    """
    Check availability of age/sex covariates and determine formula to use.

    Parameters
    ----------
    df : pd.DataFrame
        Metadata with age and sex columns

    Returns
    -------
    formula : str
        Model formula to use
    included_covariates : list
        List of covariates included in model
    warnings_list : list
        List of warning messages about dropped covariates
    """
    n_obs = len(df)
    warnings_list = []
    included_covariates = []

    # Check age
    if 'age' in df.columns:
        age_missing = df['age'].isna().sum()
        if age_missing < n_obs * 0.5:
            included_covariates.append('age_std')
        else:
            warnings_list.append(
                f"Age missing for {age_missing}/{n_obs} observations (>{50}%). "
                "Dropping age from model."
            )
    else:
        warnings_list.append("Age column not found. Dropping age from model.")

    # Check sex
    if 'sex' in df.columns:
        sex_missing = df['sex'].isna().sum() + (df['sex'] == '').sum() + (df['sex'] == 'U').sum()
        if sex_missing < n_obs * 0.5:
            included_covariates.append('sex_code')
        else:
            warnings_list.append(
                f"Sex missing for {sex_missing}/{n_obs} observations (>{50}%). "
                "Dropping sex from model."
            )
    else:
        warnings_list.append("Sex column not found. Dropping sex from model.")

    # Check mean_fd
    if 'mean_fd' in df.columns:
        fd_missing = df['mean_fd'].isna().sum()
        if fd_missing < n_obs * 0.5:
            included_covariates.append('mean_fd_std')
        else:
            warnings_list.append(
                f"MeanFD missing for {fd_missing}/{n_obs} observations. "
                "Dropping mean_fd from model."
            )
    else:
        warnings_list.append("mean_fd column not found. Dropping mean_fd from model.")

    # Build formula
    base_formula = "value ~ group_code * time"
    if included_covariates:
        base_formula += " + " + " + ".join(included_covariates)

    return base_formula, included_covariates, warnings_list


def load_maps_and_metadata(map_files, metadata_file, group_file=None):
    """
    Load individual subject maps and match with metadata.

    Parameters
    ----------
    map_files : list of str
        Paths to individual NIfTI maps
    metadata_file : str
        Path to metadata CSV/TSV
    group_file : str, optional
        Path to group assignment file (CSV with subject_id, group columns)

    Returns
    -------
    maps_df : pd.DataFrame
        DataFrame with columns: subject, session, group, age, sex, mean_fd, map_file
    """
    # Try to load metadata with automatic separator detection
    try:
        # First try comma separator
        metadata = pd.read_csv(metadata_file)
    except Exception:
        # Fall back to tab separator
        metadata = pd.read_csv(metadata_file, sep='\t')

    # Load group assignments if provided separately
    group_assignments = {}
    if group_file and Path(group_file).exists():
        group_df = pd.read_csv(group_file)
        for _, row in group_df.iterrows():
            group_assignments[row['subject_id']] = row['group']

    # Parse map filenames to extract subject and session
    rows = []
    for map_file in map_files:
        filename = Path(map_file).name
        parts = filename.split('_')

        subject = [p for p in parts if p.startswith('sub-')]
        session = [p for p in parts if p.startswith('ses-')]

        if not subject:
            print(f"Warning: Could not parse subject from {filename}, skipping")
            continue

        subject = subject[0]
        session = session[0] if session else 'ses-01'

        # Match with metadata
        meta_row = metadata[(metadata['subject'] == subject) & (metadata['session'] == session)]

        if len(meta_row) == 0:
            # Try to construct metadata from group file and other sources
            if subject in group_assignments:
                group = group_assignments[subject]
                print(f"Note: Using group from group_file for {subject} {session}")
            else:
                print(f"Warning: No metadata for {subject} {session}, skipping")
                continue

            rows.append({
                'subject': subject,
                'session': session,
                'group': group,
                'age': np.nan,
                'sex': 'U',
                'mean_fd': np.nan,
                'map_file': map_file
            })
        else:
            meta_row = meta_row.iloc[0]
            # Determine group - from metadata or group file
            if 'group' in meta_row:
                group = meta_row['group']
            elif subject in group_assignments:
                group = group_assignments[subject]
            else:
                print(f"Warning: No group assignment for {subject}, skipping")
                continue

            rows.append({
                'subject': subject,
                'session': session,
                'group': group,
                'age': meta_row.get('age', np.nan),
                'sex': meta_row.get('sex', 'U'),  # Unknown if not available
                'mean_fd': meta_row.get('mean_fd', np.nan),
                'map_file': map_file
            })

    maps_df = pd.DataFrame(rows)
    return maps_df


def voxelwise_lme(maps_df, mask_img, output_dir):
    """
    Perform voxelwise linear mixed-effects analysis.

    Model: value ~ Group * Time + [Age] + [Sex] + [MeanFD] + (1|Subject)
    Covariates are included only if available for >50% of observations.

    Parameters
    ----------
    maps_df : pd.DataFrame
        Map files and metadata
    mask_img : Nifti1Image
        Brain mask
    output_dir : Path
        Output directory

    Returns
    -------
    tstat_img : Nifti1Image
        T-statistic map for Group × Time interaction
    model_info : dict
        Information about model fitting (formula used, covariates, warnings)
    """
    print("\nPerforming voxelwise linear mixed-effects analysis...")
    print(f"  N observations: {len(maps_df)}")
    print(f"  N subjects: {maps_df['subject'].nunique()}")

    # Check covariates and get formula
    formula, included_covariates, covariate_warnings = check_covariates(maps_df)

    print(f"\n  Model formula: {formula}")
    if covariate_warnings:
        print("  Covariate warnings:")
        for w in covariate_warnings:
            print(f"    - {w}")

    # Load all maps
    print("\n  Loading maps...")
    map_data_list = []
    for map_file in maps_df['map_file']:
        img = image.load_img(map_file)
        # Resample to mask if needed
        if img.shape != mask_img.shape:
            img = image.resample_to_img(img, mask_img, interpolation='nearest')
        map_data_list.append(apply_mask(img, mask_img))

    map_data = np.array(map_data_list)  # (n_obs, n_voxels)
    n_obs, n_voxels = map_data.shape

    print(f"  Map data shape: {map_data.shape}")

    # Prepare design variables
    df = maps_df.copy()
    df['time'] = df['session'].map({'ses-01': 0, 'ses-02': 1})
    df['group_code'] = df['group'].map({'Control': 0, 'Walking': 1})

    # Handle sex coding
    if 'sex_code' in included_covariates:
        df['sex_code'] = df['sex'].map({'M': 0, 'F': 1, 'U': np.nan})
        # Fill missing with median
        df['sex_code'] = df['sex_code'].fillna(df['sex_code'].median())
    else:
        df['sex_code'] = 0  # Dummy if not used

    # Standardize continuous covariates
    if 'age_std' in included_covariates:
        df['age_std'] = (df['age'] - df['age'].mean()) / df['age'].std()
        df['age_std'] = df['age_std'].fillna(0)  # Fill missing with mean (0 after standardization)
    else:
        df['age_std'] = 0

    if 'mean_fd_std' in included_covariates:
        df['mean_fd_std'] = (df['mean_fd'] - df['mean_fd'].mean()) / df['mean_fd'].std()
        df['mean_fd_std'] = df['mean_fd_std'].fillna(0)
    else:
        df['mean_fd_std'] = 0

    # Run LME for each voxel
    print("  Fitting voxelwise models...")
    tstat_values = np.zeros(n_voxels)
    pval_values = np.ones(n_voxels)

    for v in range(n_voxels):
        if (v + 1) % 10000 == 0:
            print(f"    Progress: {v + 1}/{n_voxels} voxels")

        # Get voxel values
        df['value'] = map_data[:, v]

        # Skip if no variance
        if df['value'].std() < 1e-10:
            continue

        # Fit LME
        try:
            model = mixedlm(
                formula,
                data=df,
                groups=df['subject']
            )
            fit = model.fit(reml=True, method='nm')

            # Extract interaction effect
            tstat_values[v] = fit.tvalues.get('group_code:time', 0.0)
            pval_values[v] = fit.pvalues.get('group_code:time', 1.0)

        except Exception:
            # Model failed, leave as zero
            continue

    # Create T-statistic image
    tstat_img = unmask(tstat_values, mask_img)

    # Save uncorrected T-stat map
    tstat_file = output_dir / 'interaction_tstat_map.nii.gz'
    nib.save(tstat_img, tstat_file)
    print(f"\n  Saved T-statistic map: {tstat_file}")

    # Save uncorrected p-value map
    # Use fill=1.0 so out-of-brain voxels have p=1 (not significant)
    pval_img = unmask(pval_values, mask_img, fill=1.0)
    pval_file = output_dir / 'interaction_pval_map.nii.gz'
    nib.save(pval_img, pval_file)
    print(f"  Saved p-value map: {pval_file}")

    # Model info for report
    model_info = {
        'formula': formula,
        'included_covariates': included_covariates,
        'covariate_warnings': covariate_warnings,
        'n_observations': n_obs,
        'n_subjects': maps_df['subject'].nunique(),
        'n_voxels': n_voxels
    }

    # Save model info
    model_info_file = output_dir / 'model_info.json'
    with open(model_info_file, 'w') as f:
        json.dump(model_info, f, indent=2)
    print(f"  Saved model info: {model_info_file}")

    return tstat_img, model_info


def apply_uncorrected_threshold(tstat_img, pval_img, mask_img, output_dir,
                                  p_threshold=0.001, min_cluster_size=50):
    """
    Apply uncorrected p-value threshold with cluster size filtering.

    Used as fallback when FWE-corrected results are empty.

    Parameters
    ----------
    tstat_img : Nifti1Image
        T-statistic map
    pval_img : Nifti1Image or Path
        P-value map (or path to it)
    mask_img : Nifti1Image
        Brain mask to restrict thresholding to in-brain voxels
    output_dir : Path
        Output directory
    p_threshold : float
        Uncorrected p-value threshold (default: 0.001)
    min_cluster_size : int
        Minimum cluster size in voxels (default: 50)

    Returns
    -------
    thresholded_img : Nifti1Image
        Thresholded map with cluster size filter
    correction_info : dict
        Information about correction applied
    """
    print(f"\n  Applying uncorrected threshold (p < {p_threshold}, k > {min_cluster_size})...")

    # Load p-value map if path
    if isinstance(pval_img, (str, Path)):
        pval_img = image.load_img(pval_img)

    tstat_data = tstat_img.get_fdata()
    pval_data = pval_img.get_fdata()
    mask_data = mask_img.get_fdata().astype(bool)

    # Threshold by p-value, restricted to brain mask
    # This prevents out-of-brain voxels (p=0 or p=1) from being flagged as significant
    sig_mask = (pval_data < p_threshold) & (pval_data > 0) & mask_data

    # Apply cluster size filter
    labeled_data, n_clusters = ndimage_label(sig_mask)

    # Remove small clusters
    cluster_sizes = np.bincount(labeled_data.ravel())
    keep_clusters = np.where(cluster_sizes >= min_cluster_size)[0]

    # Create filtered mask
    filtered_mask = np.isin(labeled_data, keep_clusters)

    # Apply to T-statistics
    thresholded_data = tstat_data * filtered_mask
    thresholded_img = nib.Nifti1Image(thresholded_data, tstat_img.affine, tstat_img.header)

    # Count surviving clusters
    labeled_filtered, n_surviving = ndimage_label(filtered_mask)

    # Save
    thresh_file = output_dir / f'interaction_uncorr_p{str(p_threshold).replace(".", "")}' \
                               f'_k{min_cluster_size}.nii.gz'
    nib.save(thresholded_img, thresh_file)
    print(f"  Saved uncorrected thresholded map: {thresh_file}")
    print(f"  Surviving clusters (k >= {min_cluster_size}): {n_surviving}")

    correction_info = {
        'method': 'uncorrected',
        'p_threshold': p_threshold,
        'min_cluster_size': min_cluster_size,
        'n_clusters_initial': n_clusters,
        'n_clusters_surviving': n_surviving
    }

    return thresholded_img, correction_info


def cluster_correction_nilearn(maps_df, tstat_img, mask_img, output_dir,
                                 threshold=0.05, n_permutations=5000,
                                 use_uncorrected_fallback=True):
    """
    Apply cluster correction using nilearn's non-parametric inference.

    Uses permutation testing with TFCE (threshold-free cluster enhancement).
    Falls back to uncorrected threshold if no FWE-corrected results.

    Parameters
    ----------
    maps_df : pd.DataFrame
        Map files and metadata
    tstat_img : Nifti1Image
        T-statistic map
    mask_img : Nifti1Image
        Brain mask
    output_dir : Path
        Output directory
    threshold : float
        FWE-corrected p-value threshold
    n_permutations : int
        Number of permutations
    use_uncorrected_fallback : bool
        If True, apply uncorrected threshold when FWE results are empty

    Returns
    -------
    thresholded_img : Nifti1Image
        Thresholded map (FWE-corrected or uncorrected fallback)
    correction_info : dict
        Information about correction method used
    """
    print(f"\nApplying cluster correction (permutation testing, n={n_permutations})...")

    # Prepare design matrix for nilearn
    df = maps_df.copy()
    df['time'] = df['session'].map({'ses-01': 0, 'ses-02': 1})
    df['group_code'] = df['group'].map({'Control': 0, 'Walking': 1})
    df['interaction'] = df['group_code'] * df['time']

    # Get formula/covariates info
    _, included_covariates, _ = check_covariates(df)

    # Handle covariates based on what's included
    if 'age_std' in included_covariates:
        df['age_std'] = (df['age'] - df['age'].mean()) / df['age'].std()
        df['age_std'] = df['age_std'].fillna(0)
    else:
        df['age_std'] = 0

    if 'mean_fd_std' in included_covariates:
        df['mean_fd_std'] = (df['mean_fd'] - df['mean_fd'].mean()) / df['mean_fd'].std()
        df['mean_fd_std'] = df['mean_fd_std'].fillna(0)
    else:
        df['mean_fd_std'] = 0

    if 'sex_code' in included_covariates:
        df['sex_code'] = df['sex'].map({'M': 0, 'F': 1, 'U': 0.5})
        df['sex_code'] = df['sex_code'].fillna(0.5)
    else:
        df['sex_code'] = 0

    # Create design matrix with only included covariates
    design_cols = ['interaction', 'group_code', 'time']
    if 'age_std' in included_covariates:
        design_cols.append('age_std')
    if 'sex_code' in included_covariates:
        design_cols.append('sex_code')
    if 'mean_fd_std' in included_covariates:
        design_cols.append('mean_fd_std')

    design_matrix = df[design_cols].copy()
    design_matrix.insert(0, 'intercept', 1)

    # Load second-level images
    second_level_input = list(maps_df['map_file'])

    # Run permutation test
    print("  Running permutation test (this may take time)...")

    fwe_success = False
    try:
        # Use non_parametric_inference for permutation testing
        neg_log_pvals_img = non_parametric_inference(
            second_level_input,
            design_matrix=design_matrix,
            second_level_contrast='interaction',
            mask=mask_img,
            n_perm=n_permutations,
            two_sided_test=True,
            smoothing_fwhm=None,
            n_jobs=1  # Use 1 to avoid multiprocessing issues
        )

        # Convert -log10(p) to p-values
        neg_log_pvals_data = neg_log_pvals_img.get_fdata()
        pvals_data = 10 ** (-neg_log_pvals_data)

        # Threshold at FWE p < threshold
        thresholded_data = tstat_img.get_fdata() * (pvals_data < threshold)
        thresholded_img = nib.Nifti1Image(thresholded_data, tstat_img.affine, tstat_img.header)

        # Check if any significant voxels
        n_sig_voxels = np.sum(thresholded_data != 0)

        # Save FWE-corrected map
        thresh_file = output_dir / f'interaction_fwe_p{int(threshold*100):02d}.nii.gz'
        nib.save(thresholded_img, thresh_file)
        print(f"  Saved FWE thresholded map: {thresh_file}")
        print(f"  Significant voxels (FWE p < {threshold}): {n_sig_voxels}")

        # Save negative log p-values
        neglog_file = output_dir / 'interaction_neglog_pvals.nii.gz'
        nib.save(neg_log_pvals_img, neglog_file)

        if n_sig_voxels > 0:
            fwe_success = True
            correction_info = {
                'method': 'FWE',
                'n_permutations': n_permutations,
                'p_threshold': threshold,
                'n_significant_voxels': int(n_sig_voxels)
            }
        else:
            print("  No significant voxels after FWE correction.")
            fwe_success = False

    except Exception as e:
        print(f"  ERROR in permutation testing: {e}")
        print("  Will try uncorrected fallback...")
        fwe_success = False

    # Apply uncorrected fallback if needed
    if not fwe_success and use_uncorrected_fallback:
        pval_file = output_dir / 'interaction_pval_map.nii.gz'
        if pval_file.exists():
            thresholded_img, correction_info = apply_uncorrected_threshold(
                tstat_img, pval_file, mask_img, output_dir,
                p_threshold=0.001, min_cluster_size=50
            )
        else:
            print("  ERROR: No p-value map available for uncorrected fallback")
            thresholded_img = nib.Nifti1Image(
                np.zeros_like(tstat_img.get_fdata()),
                tstat_img.affine, tstat_img.header
            )
            correction_info = {'method': 'failed', 'error': 'No p-value map'}

    elif not fwe_success:
        # Return empty map if fallback disabled
        thresholded_img = nib.Nifti1Image(
            np.zeros_like(tstat_img.get_fdata()),
            tstat_img.affine, tstat_img.header
        )
        correction_info = {'method': 'FWE', 'n_significant_voxels': 0}

    # Save correction info
    correction_file = output_dir / 'correction_info.json'
    with open(correction_file, 'w') as f:
        json.dump(correction_info, f, indent=2)

    return thresholded_img, correction_info


def extract_cluster_table(thresholded_img, tstat_img, mask_img, output_dir,
                           min_cluster_size=10, correction_info=None):
    """
    Extract cluster table from thresholded statistical map.

    Parameters
    ----------
    thresholded_img : Nifti1Image
        Thresholded T-statistic map
    tstat_img : Nifti1Image
        Unthresholded T-statistic map
    mask_img : Nifti1Image
        Brain mask
    output_dir : Path
        Output directory
    min_cluster_size : int
        Minimum cluster size in voxels
    correction_info : dict, optional
        Information about correction method used

    Returns
    -------
    cluster_df : pd.DataFrame
        Cluster table with peak coordinates and labels
    cluster_masks : dict
        Dictionary mapping cluster_id to binary mask image
    """
    print("\nExtracting cluster table...")

    thresholded_data = thresholded_img.get_fdata()
    tstat_data = tstat_img.get_fdata()
    affine = thresholded_img.affine

    # Find connected components
    labeled_data, n_clusters = ndimage_label(thresholded_data != 0)

    print(f"  Found {n_clusters} clusters")

    # Load Harvard-Oxford atlas for anatomical labels
    try:
        ho_atlas = datasets.fetch_atlas_harvard_oxford('cort-maxprob-thr25-2mm')
        ho_img = image.load_img(ho_atlas.maps)
        ho_labels = ho_atlas.labels

        # Resample to same space as statistical map
        ho_img = image.resample_to_img(ho_img, thresholded_img, interpolation='nearest')
        ho_data = ho_img.get_fdata().astype(int)
    except Exception:
        print("  Warning: Could not load Harvard-Oxford atlas, labels will be empty")
        ho_data = None
        ho_labels = []

    # Extract cluster information
    clusters = []
    cluster_masks = {}

    for cluster_id in range(1, n_clusters + 1):
        cluster_mask = (labeled_data == cluster_id)
        cluster_size = np.sum(cluster_mask)

        if cluster_size < min_cluster_size:
            continue

        # Find peak voxel
        cluster_tstats = np.abs(tstat_data[cluster_mask])
        peak_idx = np.argmax(cluster_tstats)
        peak_coords_voxel = np.argwhere(cluster_mask)[peak_idx]

        # Convert to MNI coordinates
        peak_mni = nib.affines.apply_affine(affine, peak_coords_voxel)

        # Peak T-value
        peak_t = tstat_data[tuple(peak_coords_voxel)]

        # Anatomical label
        if ho_data is not None:
            peak_label_idx = ho_data[tuple(peak_coords_voxel)]
            if 0 < peak_label_idx < len(ho_labels):
                anatomical_label = ho_labels[peak_label_idx]
            else:
                anatomical_label = "Unknown"
        else:
            anatomical_label = "Unknown"

        # Determine direction (positive or negative effect)
        direction = "Walking > Control" if peak_t > 0 else "Control > Walking"

        cluster_entry = {
            'cluster_id': len(clusters) + 1,  # Renumber after size filtering
            'size_voxels': int(cluster_size),
            'size_mm3': int(cluster_size * 8),  # 2mm^3 voxels
            'peak_t': round(peak_t, 3),
            'peak_x': round(peak_mni[0], 1),
            'peak_y': round(peak_mni[1], 1),
            'peak_z': round(peak_mni[2], 1),
            'anatomical_region': anatomical_label,
            'direction': direction
        }

        # Add correction info
        if correction_info:
            cluster_entry['correction_method'] = correction_info.get('method', 'unknown')

        clusters.append(cluster_entry)

        # Save cluster mask
        mask_data = cluster_mask.astype(np.int16)
        cluster_mask_img = nib.Nifti1Image(mask_data, affine, tstat_img.header)
        cluster_masks[cluster_entry['cluster_id']] = cluster_mask_img

    cluster_df = pd.DataFrame(clusters)

    if len(cluster_df) > 0:
        # Sort by absolute peak T-value
        cluster_df = cluster_df.sort_values('peak_t', key=abs, ascending=False).reset_index(drop=True)
        # Re-number cluster IDs
        cluster_df['cluster_id'] = range(1, len(cluster_df) + 1)

        # Save
        cluster_file = output_dir / 'clusters_interaction.csv'
        cluster_df.to_csv(cluster_file, index=False)
        print(f"  Saved cluster table: {cluster_file}")
        print(f"  Clusters (>= {min_cluster_size} voxels): {len(cluster_df)}")

        # Save cluster masks
        mask_dir = output_dir / 'cluster_masks'
        mask_dir.mkdir(exist_ok=True)
        for cid, mask_img in cluster_masks.items():
            mask_file = mask_dir / f'cluster_{cid:02d}_mask.nii.gz'
            nib.save(mask_img, mask_file)

    else:
        print("  No clusters found meeting size threshold")
        cluster_df = pd.DataFrame()

    return cluster_df, cluster_masks


def create_visualization(tstat_img, thresholded_img, output_dir, correction_info=None):
    """
    Create brain slice visualizations.

    Parameters
    ----------
    tstat_img : Nifti1Image
        T-statistic map
    thresholded_img : Nifti1Image
        Thresholded map
    output_dir : Path
        Output directory
    correction_info : dict, optional
        Information about correction method
    """
    print("\nCreating visualizations...")

    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend

    # Determine correction label for title
    if correction_info:
        method = correction_info.get('method', 'unknown')
        if method == 'FWE':
            correction_label = f"FWE p<{correction_info.get('p_threshold', 0.05)}"
        elif method == 'uncorrected':
            p_thresh = correction_info.get('p_threshold', 0.001)
            k_thresh = correction_info.get('min_cluster_size', 50)
            correction_label = f"Uncorrected p<{p_thresh}, k>{k_thresh}"
        else:
            correction_label = "Unknown correction"
    else:
        correction_label = "Thresholded"

    # Plot unthresholded T-stat map
    try:
        fig = plotting.plot_stat_map(
            tstat_img,
            threshold=2.0,
            title='Group × Time Interaction (T-statistic)',
            display_mode='ortho',
            colorbar=True,
            cmap='RdBu_r',
            symmetric_cbar=True,
            output_file=str(output_dir / 'tstat_map_ortho.png')
        )
        print(f"  Saved: tstat_map_ortho.png")
    except Exception as e:
        print(f"  Warning: Could not create tstat ortho plot: {e}")

    # Plot thresholded map
    if np.any(thresholded_img.get_fdata() != 0):
        try:
            fig = plotting.plot_stat_map(
                thresholded_img,
                title=f'Group × Time Interaction ({correction_label})',
                display_mode='ortho',
                colorbar=True,
                cmap='RdBu_r',
                symmetric_cbar=True,
                output_file=str(output_dir / 'thresholded_map_ortho.png')
            )
            print(f"  Saved: thresholded_map_ortho.png")
        except Exception as e:
            print(f"  Warning: Could not create thresholded ortho plot: {e}")

        # Mosaic view
        try:
            fig = plotting.plot_stat_map(
                thresholded_img,
                title=f'Group × Time Interaction ({correction_label})',
                display_mode='mosaic',
                colorbar=True,
                cmap='RdBu_r',
                symmetric_cbar=True,
                output_file=str(output_dir / 'thresholded_map_mosaic.png')
            )
            print(f"  Saved: thresholded_map_mosaic.png")
        except Exception as e:
            print(f"  Warning: Could not create mosaic plot: {e}")

        # Also create glass brain view for HTML report
        try:
            fig = plotting.plot_glass_brain(
                thresholded_img,
                title=f'Group × Time Interaction ({correction_label})',
                colorbar=True,
                cmap='RdBu_r',
                symmetric_cbar=True,
                output_file=str(output_dir / 'thresholded_map_glass.png')
            )
            print(f"  Saved: thresholded_map_glass.png")
        except Exception as e:
            print(f"  Warning: Could not create glass brain plot: {e}")
    else:
        print("  No suprathreshold voxels to visualize")


def main():
    parser = argparse.ArgumentParser(
        description="Group-level voxelwise analysis for longitudinal walking study"
    )
    parser.add_argument('--input-maps', nargs='+', required=True,
                        help='Individual subject maps (NIfTI files)')
    parser.add_argument('--metadata', required=True,
                        help='Metadata CSV/TSV with subject, session, group, age, sex, mean_fd')
    parser.add_argument('--group-file',
                        help='Optional group assignments CSV (subject_id, group)')
    parser.add_argument('--output', required=True,
                        help='Output directory')
    parser.add_argument('--mask',
                        help='Brain mask (default: load MNI152 2mm mask)')
    parser.add_argument('--cluster-threshold', type=float, default=0.05,
                        help='FWE-corrected p-value threshold (default: 0.05)')
    parser.add_argument('--n-permutations', type=int, default=5000,
                        help='Number of permutations for cluster correction (default: 5000)')
    parser.add_argument('--min-cluster-size', type=int, default=10,
                        help='Minimum cluster size in voxels (default: 10)')
    parser.add_argument('--no-uncorrected-fallback', action='store_true',
                        help='Disable uncorrected fallback when FWE results are empty')

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("GROUP-LEVEL VOXELWISE ANALYSIS")
    print("=" * 60)

    # Load mask
    if args.mask:
        mask_img = image.load_img(args.mask)
    else:
        print("Loading MNI152 2mm brain mask...")
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

    if len(maps_df) < 10:
        print("ERROR: Need at least 10 observations for group analysis")
        return 1

    # Voxelwise LME
    tstat_img, model_info = voxelwise_lme(maps_df, mask_img, output_dir)

    # Cluster correction
    thresholded_img, correction_info = cluster_correction_nilearn(
        maps_df, tstat_img, mask_img, output_dir,
        threshold=args.cluster_threshold,
        n_permutations=args.n_permutations,
        use_uncorrected_fallback=not args.no_uncorrected_fallback
    )

    # Extract cluster table
    cluster_df, cluster_masks = extract_cluster_table(
        thresholded_img, tstat_img, mask_img, output_dir,
        min_cluster_size=args.min_cluster_size,
        correction_info=correction_info
    )

    # Visualizations
    create_visualization(tstat_img, thresholded_img, output_dir, correction_info)

    print("\n" + "=" * 60)
    print("GROUP-LEVEL ANALYSIS COMPLETE")
    print("=" * 60)
    print(f"Output directory: {output_dir}")
    print(f"Correction method: {correction_info.get('method', 'unknown')}")

    if len(cluster_df) > 0:
        print(f"\nSignificant clusters: {len(cluster_df)}")
        print("\nTop clusters:")
        display_cols = ['cluster_id', 'size_voxels', 'peak_t', 'peak_x', 'peak_y',
                        'peak_z', 'anatomical_region', 'direction']
        print(cluster_df[display_cols].head(5).to_string(index=False))
    else:
        print("\nNo significant clusters found.")

    return 0


if __name__ == '__main__':
    exit(main())
