#!/usr/bin/env python3
"""
Connectivity Analysis for Longitudinal Walking Intervention Study

This script analyzes connectivity from timeseries extracted from CONN preprocessing.
It performs:
- Mixed-effects ANOVA (Group × Time interaction)
- Network-based connectivity analysis (hypothesis-driven)
- FDR correction for multiple comparisons
- Effect size calculations

Study Design:
- Groups: Control (n=15) vs Walking (n=9)
- Time: Pre (ses-01) vs Post (ses-02)
- Design: 2×2 mixed ANOVA with covariates (age, sex, mean FD)
- Primary Atlas: DiFuMo 256 (includes cerebellum)

Usage:
    python python_connectivity_analysis.py \\
        --timeseries timeseries_difumo256.h5 \\
        --metadata metadata.csv \\
        --networks difumo256_network_definitions.json \\
        --output results/connectivity_analysis

Dependencies:
    pip install numpy pandas scipy statsmodels h5py networkx
"""

import argparse
import json
import os
from pathlib import Path

import h5py
import numpy as np
import pandas as pd
from scipy import stats
from scipy.spatial.distance import squareform
from statsmodels.stats.multitest import fdrcorrection
from statsmodels.formula.api import mixedlm
import warnings
warnings.filterwarnings('ignore')


def load_timeseries_hdf5(hdf5_file):
    """
    Load ROI timeseries from HDF5 file.

    Expected structure:
        /subject/session/timeseries (n_volumes × n_rois)

    Returns:
        dict: {(subject, session): timeseries_array}
    """
    print(f"Loading timeseries from: {hdf5_file}")

    timeseries_data = {}

    with h5py.File(hdf5_file, 'r') as f:
        for subject in f.keys():
            for session in f[subject].keys():
                ts = f[subject][session]['timeseries'][:]
                timeseries_data[(subject, session)] = ts

    print(f"  Loaded {len(timeseries_data)} subject-session pairs")

    return timeseries_data


def compute_connectivity_matrix(timeseries, method='pearson'):
    """
    Compute connectivity matrix from timeseries.

    Parameters:
        timeseries: n_volumes × n_rois array
        method: 'pearson', 'partial', or 'covariance'

    Returns:
        n_rois × n_rois connectivity matrix
    """
    n_volumes, n_rois = timeseries.shape

    if method == 'pearson':
        # Pearson correlation
        conn_matrix = np.corrcoef(timeseries.T)

    elif method == 'partial':
        # Partial correlation (control for all other ROIs)
        # Using precision matrix approach
        cov_matrix = np.cov(timeseries.T)
        precision = np.linalg.inv(cov_matrix + 1e-6 * np.eye(n_rois))  # Ridge for stability

        # Convert precision to partial correlation
        diag = np.sqrt(np.diag(precision))
        conn_matrix = -precision / np.outer(diag, diag)
        np.fill_diagonal(conn_matrix, 1.0)

    elif method == 'covariance':
        # Covariance
        conn_matrix = np.cov(timeseries.T)

    else:
        raise ValueError(f"Unknown method: {method}")

    return conn_matrix


def fisher_z_transform(correlation_matrix):
    """Apply Fisher Z-transformation for normality."""
    with np.errstate(divide='ignore', invalid='ignore'):
        z = np.arctanh(correlation_matrix)
        z[np.isinf(z)] = np.nan
    return z


def prepare_data_for_anova(timeseries_data, metadata, network_pairs=None):
    """
    Prepare connectivity data for mixed ANOVA.

    Parameters:
        timeseries_data: dict of (subject, session) -> timeseries
        metadata: DataFrame with columns [subject, session, group, age, sex, mean_fd]
        network_pairs: dict of network pair definitions (optional, for hypothesis-driven)

    Returns:
        DataFrame with columns: [subject, session, group, age, sex, mean_fd, roi_i, roi_j, connectivity_z]
    """
    print("Computing connectivity matrices and preparing ANOVA data...")

    data_rows = []

    for (subject, session), ts in timeseries_data.items():
        # Get subject metadata
        meta_row = metadata[(metadata['subject'] == subject) & (metadata['session'] == session)]
        if len(meta_row) == 0:
            print(f"  Warning: No metadata for {subject} {session}, skipping")
            continue

        meta_row = meta_row.iloc[0]

        # Compute connectivity matrix
        conn_matrix = compute_connectivity_matrix(ts, method='pearson')

        # Fisher Z-transform
        conn_z = fisher_z_transform(conn_matrix)

        # Get upper triangle indices (avoid diagonal and redundant pairs)
        n_rois = conn_matrix.shape[0]
        triu_indices = np.triu_indices(n_rois, k=1)

        # If network pairs specified, filter connections
        if network_pairs is not None:
            # Create mask for network pairs
            mask = np.zeros((n_rois, n_rois), dtype=bool)
            for pair_name, pair_info in network_pairs.items():
                rois_a = pair_info['rois_a']
                rois_b = pair_info['rois_b']
                for i in rois_a:
                    for j in rois_b:
                        if i < j:
                            mask[i, j] = True
                        elif j < i:
                            mask[j, i] = True

            # Apply mask
            indices_i, indices_j = np.where(mask)
        else:
            # All pairwise connections
            indices_i, indices_j = triu_indices

        # Extract connections
        for roi_i, roi_j in zip(indices_i, indices_j):
            data_rows.append({
                'subject': subject,
                'session': session,
                'group': meta_row['group'],
                'age': meta_row['age'],
                'sex': meta_row['sex'],
                'mean_fd': meta_row['mean_fd'],
                'roi_i': roi_i,
                'roi_j': roi_j,
                'connectivity_z': conn_z[roi_i, roi_j]
            })

    df = pd.DataFrame(data_rows)

    print(f"  Prepared {len(df)} connectivity observations")
    print(f"  Subjects: {df['subject'].nunique()}")
    print(f"  ROI pairs: {len(df.groupby(['roi_i', 'roi_j']))}")

    return df


def mixed_anova_group_time(df):
    """
    Perform mixed-effects ANOVA for Group × Time interaction.

    Model: connectivity_z ~ Group * Time + Age + Sex + MeanFD + (1|Subject)

    Parameters:
        df: DataFrame with connectivity data

    Returns:
        DataFrame with results per ROI pair
    """
    print("Running mixed-effects ANOVA (Group × Time)...")

    # Recode variables
    df = df.copy()
    df['time'] = df['session'].map({'ses-01': 0, 'ses-02': 1})  # 0=Pre, 1=Post
    df['group_code'] = df['group'].map({'Control': 0, 'Walking': 1})  # 0=Control, 1=Walking
    df['sex_code'] = df['sex'].map({'M': 0, 'F': 1})  # Example coding

    # Standardize continuous covariates
    df['age_std'] = (df['age'] - df['age'].mean()) / df['age'].std()
    df['mean_fd_std'] = (df['mean_fd'] - df['mean_fd'].mean()) / df['mean_fd'].std()

    # Get unique ROI pairs
    roi_pairs = df.groupby(['roi_i', 'roi_j']).size().reset_index()[['roi_i', 'roi_j']]

    results = []

    for idx, row in roi_pairs.iterrows():
        roi_i, roi_j = row['roi_i'], row['roi_j']

        # Subset data for this ROI pair
        pair_data = df[(df['roi_i'] == roi_i) & (df['roi_j'] == roi_j)].copy()

        # Drop NaN
        pair_data = pair_data.dropna(subset=['connectivity_z', 'age_std', 'mean_fd_std'])

        if len(pair_data) < 10:  # Need sufficient data
            continue

        # Fit mixed-effects model
        try:
            model = mixedlm(
                "connectivity_z ~ group_code * time + age_std + sex_code + mean_fd_std",
                data=pair_data,
                groups=pair_data['subject']
            )
            fit = model.fit(reml=True, method='nm')

            # Extract interaction effect (group_code:time)
            interaction_coef = fit.params.get('group_code:time', np.nan)
            interaction_pval = fit.pvalues.get('group_code:time', np.nan)
            interaction_tstat = fit.tvalues.get('group_code:time', np.nan)

            # Extract main effects
            group_coef = fit.params.get('group_code', np.nan)
            group_pval = fit.pvalues.get('group_code', np.nan)
            time_coef = fit.params.get('time', np.nan)
            time_pval = fit.pvalues.get('time', np.nan)

            results.append({
                'roi_i': roi_i,
                'roi_j': roi_j,
                'interaction_coef': interaction_coef,
                'interaction_tstat': interaction_tstat,
                'interaction_pval': interaction_pval,
                'group_coef': group_coef,
                'group_pval': group_pval,
                'time_coef': time_coef,
                'time_pval': time_pval,
                'n_obs': len(pair_data)
            })

        except Exception as e:
            print(f"    Warning: Model failed for ROI pair ({roi_i}, {roi_j}): {e}")
            continue

        if (idx + 1) % 1000 == 0:
            print(f"    Processed {idx + 1}/{len(roi_pairs)} ROI pairs")

    results_df = pd.DataFrame(results)

    print(f"  Completed {len(results_df)} statistical tests")

    return results_df


def apply_fdr_correction(results_df, alpha=0.05):
    """Apply FDR correction to p-values."""
    print(f"Applying FDR correction (alpha={alpha})...")

    # Interaction effect
    reject_interaction, pvals_corrected_interaction = fdrcorrection(
        results_df['interaction_pval'].values, alpha=alpha
    )
    results_df['interaction_pval_fdr'] = pvals_corrected_interaction
    results_df['interaction_significant_fdr'] = reject_interaction

    # Group effect
    reject_group, pvals_corrected_group = fdrcorrection(
        results_df['group_pval'].values, alpha=alpha
    )
    results_df['group_pval_fdr'] = pvals_corrected_group
    results_df['group_significant_fdr'] = reject_group

    # Time effect
    reject_time, pvals_corrected_time = fdrcorrection(
        results_df['time_pval'].values, alpha=alpha
    )
    results_df['time_pval_fdr'] = pvals_corrected_time
    results_df['time_significant_fdr'] = reject_time

    # Summary
    n_sig_interaction = results_df['interaction_significant_fdr'].sum()
    n_sig_group = results_df['group_significant_fdr'].sum()
    n_sig_time = results_df['time_significant_fdr'].sum()

    print(f"  Significant interactions (FDR q<{alpha}): {n_sig_interaction}/{len(results_df)}")
    print(f"  Significant group effects: {n_sig_group}/{len(results_df)}")
    print(f"  Significant time effects: {n_sig_time}/{len(results_df)}")

    return results_df


def compute_effect_sizes(timeseries_data, metadata, significant_pairs):
    """
    Compute effect sizes (Cohen's d) for significant connections.

    Cohen's d for interaction: (d_Walking - d_Control)
        where d_X = (Post - Pre) / pooled_SD for group X
    """
    print("Computing effect sizes for significant connections...")

    effect_sizes = []

    for idx, row in significant_pairs.iterrows():
        roi_i, roi_j = row['roi_i'], row['roi_j']

        # Extract connectivity values for this pair
        connectivity_values = []

        for (subject, session), ts in timeseries_data.items():
            meta_row = metadata[(metadata['subject'] == subject) & (metadata['session'] == session)]
            if len(meta_row) == 0:
                continue

            meta_row = meta_row.iloc[0]

            # Compute connectivity
            conn_matrix = compute_connectivity_matrix(ts, method='pearson')
            conn_z = fisher_z_transform(conn_matrix)
            conn_value = conn_z[roi_i, roi_j]

            connectivity_values.append({
                'subject': subject,
                'session': session,
                'group': meta_row['group'],
                'connectivity_z': conn_value
            })

        conn_df = pd.DataFrame(connectivity_values)

        # Compute change scores (Post - Pre) for each group
        change_control = []
        change_walking = []

        for subject in conn_df['subject'].unique():
            subj_data = conn_df[conn_df['subject'] == subject]
            if len(subj_data) != 2:  # Need both sessions
                continue

            pre = subj_data[subj_data['session'] == 'ses-01']['connectivity_z'].values[0]
            post = subj_data[subj_data['session'] == 'ses-02']['connectivity_z'].values[0]
            change = post - pre

            group = subj_data.iloc[0]['group']
            if group == 'Control':
                change_control.append(change)
            elif group == 'Walking':
                change_walking.append(change)

        # Compute Cohen's d for interaction
        if len(change_control) > 0 and len(change_walking) > 0:
            mean_control = np.mean(change_control)
            mean_walking = np.mean(change_walking)

            # Pooled standard deviation
            var_control = np.var(change_control, ddof=1)
            var_walking = np.var(change_walking, ddof=1)
            n_control = len(change_control)
            n_walking = len(change_walking)

            pooled_sd = np.sqrt(((n_control - 1) * var_control + (n_walking - 1) * var_walking) /
                                (n_control + n_walking - 2))

            # Cohen's d for interaction (difference of differences)
            cohens_d = (mean_walking - mean_control) / pooled_sd

            effect_sizes.append({
                'roi_i': roi_i,
                'roi_j': roi_j,
                'cohens_d_interaction': cohens_d,
                'mean_change_control': mean_control,
                'mean_change_walking': mean_walking,
                'n_control': n_control,
                'n_walking': n_walking
            })

    effect_df = pd.DataFrame(effect_sizes)

    print(f"  Computed effect sizes for {len(effect_df)} connections")

    return effect_df


def save_results(results_df, effect_df, output_dir, network_definitions=None):
    """Save results to CSV files with ROI labels if available."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load ROI labels if available
    roi_labels = None
    if network_definitions:
        with open(network_definitions, 'r') as f:
            net_defs = json.load(f)
            components = net_defs.get('components', [])
            roi_labels = {comp['index']: comp['name'] for comp in components}

    # Add ROI labels to results
    if roi_labels:
        results_df['roi_i_name'] = results_df['roi_i'].map(roi_labels)
        results_df['roi_j_name'] = results_df['roi_j'].map(roi_labels)

        if not effect_df.empty:
            effect_df['roi_i_name'] = effect_df['roi_i'].map(roi_labels)
            effect_df['roi_j_name'] = effect_df['roi_j'].map(roi_labels)

    # Save full results
    results_file = output_dir / 'connectivity_anova_results.csv'
    results_df.to_csv(results_file, index=False)
    print(f"Saved full results to: {results_file}")

    # Save significant interactions only
    sig_interactions = results_df[results_df['interaction_significant_fdr']].copy()
    sig_interactions = sig_interactions.sort_values('interaction_pval_fdr')
    sig_file = output_dir / 'significant_interactions_fdr.csv'
    sig_interactions.to_csv(sig_file, index=False)
    print(f"Saved significant interactions to: {sig_file}")

    # Save effect sizes
    if not effect_df.empty:
        effect_file = output_dir / 'effect_sizes.csv'
        effect_df.to_csv(effect_file, index=False)
        print(f"Saved effect sizes to: {effect_file}")

    # Print summary
    print("\n" + "="*60)
    print("CONNECTIVITY ANALYSIS SUMMARY")
    print("="*60)
    print(f"Total ROI pairs tested: {len(results_df)}")
    print(f"Significant Group × Time interactions (FDR q<0.05): {len(sig_interactions)}")
    if len(sig_interactions) > 0:
        print(f"  Top interaction (lowest p): {sig_interactions.iloc[0]['roi_i_name']} - {sig_interactions.iloc[0]['roi_j_name']}")
        print(f"    p-value (FDR): {sig_interactions.iloc[0]['interaction_pval_fdr']:.6f}")
        print(f"    Effect (coefficient): {sig_interactions.iloc[0]['interaction_coef']:.4f}")


def prepare_within_network_pairs(network_definitions, network_name):
    """
    Generate all pairwise connections within a network.

    Parameters
    ----------
    network_definitions : dict
        Network definitions with 'networks' key
    network_name : str
        Name of network (e.g., 'SalienceVentralAttention')

    Returns
    -------
    pairs : dict
        Dictionary of pairwise connections: {pair_name: {'rois_a': [i], 'rois_b': [j]}}
    """
    if 'networks' not in network_definitions:
        raise ValueError("network_definitions must contain 'networks' key")

    if network_name not in network_definitions['networks']:
        raise ValueError(f"Network '{network_name}' not found in definitions")

    network_rois = network_definitions['networks'][network_name]

    pairs = {}
    for i, roi_i in enumerate(network_rois):
        for roi_j in network_rois[i+1:]:
            pair_name = f"roi{roi_i}_roi{roi_j}"
            pairs[pair_name] = {'rois_a': [roi_i], 'rois_b': [roi_j]}

    return pairs


def prepare_between_network_pairs(network_definitions, network_a, network_b):
    """
    Generate all cross-network connections.

    Parameters
    ----------
    network_definitions : dict
        Network definitions with 'networks' key
    network_a : str
        First network name
    network_b : str
        Second network name

    Returns
    -------
    pairs : dict
        Dictionary of cross-network connections
    """
    if network_a not in network_definitions['networks']:
        raise ValueError(f"Network '{network_a}' not found")
    if network_b not in network_definitions['networks']:
        raise ValueError(f"Network '{network_b}' not found")

    rois_a = network_definitions['networks'][network_a]
    rois_b = network_definitions['networks'][network_b]

    pairs = {}
    for roi_a in rois_a:
        for roi_b in rois_b:
            if roi_a != roi_b:  # Exclude self-connections
                pair_name = f"roi{roi_a}_roi{roi_b}"
                pairs[pair_name] = {'rois_a': [roi_a], 'rois_b': [roi_b]}

    return pairs


def main():
    parser = argparse.ArgumentParser(
        description="Connectivity analysis for longitudinal walking intervention study"
    )
    parser.add_argument('--timeseries', required=True,
                        help='HDF5 file with ROI timeseries')
    parser.add_argument('--metadata', required=True,
                        help='CSV file with subject metadata (group, age, sex, mean_fd)')
    parser.add_argument('--networks',
                        help='JSON file with network definitions (optional, for hypothesis-driven)')
    parser.add_argument('--output', required=True,
                        help='Output directory for results')
    parser.add_argument('--hypothesis-driven', action='store_true',
                        help='Test only hypothesis-driven network pairs')
    parser.add_argument('--within-network', type=str,
                        help='Test all connections within specified network')
    parser.add_argument('--between-networks', nargs=2, metavar=('NET1', 'NET2'),
                        help='Test all connections between two networks')
    parser.add_argument('--all-within', action='store_true',
                        help='Test within-network connectivity for all networks')
    parser.add_argument('--all-between', action='store_true',
                        help='Test between-network connectivity for all network pairs')
    parser.add_argument('--alpha', type=float, default=0.05,
                        help='FDR alpha level (default: 0.05)')

    args = parser.parse_args()

    # Load data
    timeseries_data = load_timeseries_hdf5(args.timeseries)
    metadata = pd.read_csv(args.metadata)

    # Load network definitions
    network_pairs = None
    net_defs = None

    if args.networks:
        with open(args.networks, 'r') as f:
            net_defs = json.load(f)

    # Determine which network pairs to test
    if args.hypothesis_driven and args.networks:
        network_pairs = net_defs.get('hypothesis_driven_pairs_refined', {})
        print(f"Using hypothesis-driven network pairs: {len(network_pairs)} pairs")

    elif args.within_network and args.networks:
        print(f"Testing within-network connectivity: {args.within_network}")
        network_pairs = prepare_within_network_pairs(net_defs, args.within_network)
        print(f"  Generated {len(network_pairs)} within-network pairs")

    elif args.between_networks and args.networks:
        net1, net2 = args.between_networks
        print(f"Testing between-network connectivity: {net1} ↔ {net2}")
        network_pairs = prepare_between_network_pairs(net_defs, net1, net2)
        print(f"  Generated {len(network_pairs)} between-network pairs")

    elif args.all_within and args.networks:
        print("Testing within-network connectivity for all networks")
        network_pairs = {}
        for network_name in net_defs.get('network_names', net_defs['networks'].keys()):
            pairs = prepare_within_network_pairs(net_defs, network_name)
            print(f"  {network_name}: {len(pairs)} pairs")
            network_pairs.update(pairs)
        print(f"Total within-network pairs: {len(network_pairs)}")

    elif args.all_between and args.networks:
        print("Testing between-network connectivity for all network pairs")
        network_pairs = {}
        network_names = list(net_defs.get('network_names', net_defs['networks'].keys()))
        for i, net_a in enumerate(network_names):
            for net_b in network_names[i+1:]:
                pairs = prepare_between_network_pairs(net_defs, net_a, net_b)
                print(f"  {net_a} ↔ {net_b}: {len(pairs)} pairs")
                network_pairs.update(pairs)
        print(f"Total between-network pairs: {len(network_pairs)}")

    # Prepare data
    df = prepare_data_for_anova(timeseries_data, metadata, network_pairs)

    # Run mixed ANOVA
    results_df = mixed_anova_group_time(df)

    # FDR correction
    results_df = apply_fdr_correction(results_df, alpha=args.alpha)

    # Compute effect sizes for significant connections
    significant_pairs = results_df[results_df['interaction_significant_fdr']]
    if len(significant_pairs) > 0:
        effect_df = compute_effect_sizes(timeseries_data, metadata, significant_pairs)
    else:
        effect_df = pd.DataFrame()
        print("No significant interactions found, skipping effect size computation")

    # Save results
    save_results(results_df, effect_df, args.output, args.networks)

    print("\nConnectivity analysis complete!")


if __name__ == '__main__':
    main()
