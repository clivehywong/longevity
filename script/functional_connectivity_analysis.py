#!/usr/bin/env python3
"""
Functional Connectivity (FC) Analysis Pipeline
Computes Pearson correlation matrices from XCP-D denoised timeseries
across 4 subjects with 2 sessions each (8 total sessions).
Uses Schaefer 400 + Tian subcortex atlas (4S256Parcels in XCP-D).
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import nibabel as nib
from scipy.spatial.distance import pdist, squareform

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
XCPD_DIR = PROJECT_ROOT / "derivatives" / "preprocessing" / "xcpd" / "fc"
RESULTS_DIR = PROJECT_ROOT / "results" / "connectivity"
ATLAS_NAME = "4S256Parcels"  # Schaefer 400 + Tian subcortex
SUBJECTS = ["sub-066", "sub-068", "sub-072", "sub-077"]
SESSIONS = ["ses-01", "ses-02"]


def load_timeseries(subject, session):
    """Load preprocessed timeseries from XCP-D FC output."""
    ts_file = (
        XCPD_DIR
        / subject
        / session
        / "func"
        / f"{subject}_{session}_task-rest_space-MNI152NLin6Asym_atlas-{ATLAS_NAME}_stat-mean_timeseries.tsv"
    )

    if not ts_file.exists():
        print(f"❌ Missing: {ts_file}")
        return None

    try:
        # Load TSV timeseries (rows=timepoints, cols=ROIs)
        ts = pd.read_csv(ts_file, sep="\t")
        print(f"✓ {subject}/{session}: Loaded {len(ts)} timepoints × {len(ts.columns)} ROIs")
        return ts
    except Exception as e:
        print(f"❌ Error loading {subject}/{session}: {e}")
        return None


def compute_fc_matrix(timeseries):
    """
    Compute Pearson correlation FC matrix and apply Fisher z-transform.
    
    Args:
        timeseries: pd.DataFrame with shape (timepoints, rois)
    
    Returns:
        fc_matrix: np.ndarray with shape (rois, rois), correlation values
        z_matrix: np.ndarray with shape (rois, rois), Fisher z-transformed values
    """
    # Compute Pearson correlation matrix
    fc_matrix = timeseries.corr().values  # (rois, rois)

    # Apply Fisher z-transform for normality
    # z = 0.5 * ln((1+r)/(1-r)) with clipping to avoid log(0)
    r_clipped = np.clip(fc_matrix, -0.9999, 0.9999)
    z_matrix = 0.5 * np.log((1 + r_clipped) / (1 - r_clipped))

    return fc_matrix, z_matrix


def save_fc_matrices(subject, session, fc_matrix, z_matrix, roi_labels):
    """Save FC matrices to CSV with ROI labels."""
    base_name = f"{subject}_{session}_fc"
    fc_file = RESULTS_DIR / "subject_fc_matrices" / f"{base_name}_pearson.csv"
    z_file = RESULTS_DIR / "subject_fc_matrices" / f"{base_name}_fisherz.csv"

    # Save with ROI labels as index and columns
    fc_df = pd.DataFrame(fc_matrix, index=roi_labels, columns=roi_labels)
    z_df = pd.DataFrame(z_matrix, index=roi_labels, columns=roi_labels)

    fc_df.to_csv(fc_file)
    z_df.to_csv(z_file)

    print(f"  → Saved FC matrices: {fc_file.name}, {z_file.name}")
    return fc_file, z_file


def compute_network_metrics(fc_matrix, roi_labels):
    """
    Compute network-level metrics from FC matrix.
    
    Returns:
        metrics: dict with degree, clustering, etc.
    """
    # Thresholded matrix for network analysis (threshold at 0.3 correlation)
    threshold = 0.3
    thresholded = np.abs(fc_matrix) > threshold

    # Degree centrality (strength): mean absolute correlation per node
    degree = np.abs(fc_matrix).mean(axis=1)

    # Clustering coefficient approximation
    n_rois = len(fc_matrix)
    clustering = np.zeros(n_rois)
    for i in range(n_rois):
        neighbors = np.where(thresholded[i])[0]
        if len(neighbors) < 2:
            clustering[i] = 0
        else:
            subgraph = fc_matrix[np.ix_(neighbors, neighbors)]
            possible_edges = len(neighbors) * (len(neighbors) - 1) / 2
            actual_edges = np.sum(thresholded[np.ix_(neighbors, neighbors)]) / 2
            clustering[i] = actual_edges / possible_edges if possible_edges > 0 else 0

    metrics = {
        "roi_labels": list(roi_labels),
        "degree_centrality": degree.tolist(),
        "clustering_coeff": clustering.tolist(),
        "mean_correlation": float(np.abs(fc_matrix).mean()),
        "threshold_used": threshold,
    }

    return metrics


def generate_group_connectome(all_z_matrices, all_roi_labels):
    """
    Generate group-level connectome by averaging z-transformed FC matrices.
    
    Args:
        all_z_matrices: list of z-transformed FC matrices
        all_roi_labels: ROI labels (same for all subjects)
    
    Returns:
        group_connectome: averaged z-matrix across all subjects/sessions
    """
    # Stack all z-matrices and compute mean
    stacked = np.array(all_z_matrices)
    group_connectome = stacked.mean(axis=0)

    return group_connectome


def create_connectivity_report(results_summary):
    """Generate summary report of FC analysis."""
    report_text = f"""# Functional Connectivity Analysis Report

**Analysis Date**: {datetime.now().isoformat()}
**Atlas**: Schaefer 400 + Tian Subcortex (4S256Parcels)
**Subjects**: {', '.join(SUBJECTS)}
**Sessions**: 2 per subject (8 total)

## Summary

- **Total Sessions Analyzed**: {results_summary['total_sessions']}
- **Total ROIs**: {results_summary['total_rois']}
- **Correlation Type**: Pearson (Fisher z-transformed)
- **Thresholding**: {results_summary['threshold']:.2f} for network metrics

## Results

- **Subject FC Matrices**: Per-session Pearson and z-transformed correlation matrices
- **Group Connectome**: Average functional connectome across all subjects and sessions
- **Network Metrics**: Degree centrality and clustering coefficients per ROI

## Files Generated

```
results/connectivity/
├── subject_fc_matrices/
│   ├── sub-0XX_ses-0X_fc_pearson.csv    (Pearson correlations)
│   └── sub-0XX_ses-0X_fc_fisherz.csv    (Fisher z-transformed)
├── group_connectome.csv                  (Group-level average)
├── network_metrics_group.json            (Network analysis metrics)
└── connectivity_report.md                (This report)
```

## Interpretation

- **Degree Centrality**: Higher values indicate hub regions with strong connectivity to other regions
- **Clustering Coefficient**: Higher values indicate local clustering/small-world organization
- **Z-transformed Values**: Fisher z-transform normalizes correlations for statistical inference

## Next Steps

- Visualize connectivity matrices as heatmaps
- Extract network communities using graph-based methods
- Perform group-level statistical tests on connectivity strength
- Investigate individual differences in connectivity patterns
"""
    return report_text


def main():
    """Run full FC analysis pipeline."""
    print("=" * 70)
    print("FUNCTIONAL CONNECTIVITY ANALYSIS PIPELINE")
    print("=" * 70)
    print()

    # Storage for results
    subject_matrices = {}
    group_z_matrices = []
    group_metrics = []
    all_roi_labels = None

    # Process each subject and session
    for subject in SUBJECTS:
        print(f"\n📊 Processing {subject}")
        subject_matrices[subject] = {}

        for session in SESSIONS:
            # Load timeseries
            ts = load_timeseries(subject, session)
            if ts is None:
                continue

            # Get ROI labels from timeseries columns
            roi_labels = ts.columns.tolist()
            if all_roi_labels is None:
                all_roi_labels = roi_labels

            # Compute FC matrices
            fc_matrix, z_matrix = compute_fc_matrix(ts)

            # Save to disk
            fc_file, z_file = save_fc_matrices(subject, session, fc_matrix, z_matrix, roi_labels)

            # Store for group analysis
            subject_matrices[subject][session] = {
                "fc": fc_matrix,
                "z": z_matrix,
                "roi_labels": roi_labels,
            }
            group_z_matrices.append(z_matrix)

            # Compute network metrics
            metrics = compute_network_metrics(fc_matrix, roi_labels)
            metrics["subject"] = subject
            metrics["session"] = session
            group_metrics.append(metrics)

    # Generate group-level connectome
    if group_z_matrices:
        print(f"\n🧠 Generating group connectome ({len(group_z_matrices)} sessions)")
        group_connectome = generate_group_connectome(group_z_matrices, all_roi_labels)

        # Save group connectome
        group_file = RESULTS_DIR / "group_connectome.csv"
        group_df = pd.DataFrame(group_connectome, index=all_roi_labels, columns=all_roi_labels)
        group_df.to_csv(group_file)
        print(f"✓ Saved group connectome: {group_file.name}")

        # Save group network metrics
        group_degree = np.abs(group_connectome).mean(axis=1)
        metrics_dict = {
            "roi_labels": all_roi_labels,
            "degree_centrality": group_degree.tolist(),
            "n_sessions": len(group_z_matrices),
            "n_subjects": len(SUBJECTS),
        }
        metrics_file = RESULTS_DIR / "network_metrics_group.json"
        with open(metrics_file, "w") as f:
            json.dump(metrics_dict, f, indent=2)
        print(f"✓ Saved group metrics: {metrics_file.name}")

    # Generate report
    report_text = create_connectivity_report(
        {
            "total_sessions": len(group_z_matrices),
            "total_rois": len(all_roi_labels) if all_roi_labels else 0,
            "threshold": 0.3,
        }
    )
    report_file = RESULTS_DIR / "connectivity_report.md"
    with open(report_file, "w") as f:
        f.write(report_text)
    print(f"\n✓ Saved report: {report_file.name}")

    # Print summary
    print("\n" + "=" * 70)
    print("✅ FUNCTIONAL CONNECTIVITY ANALYSIS COMPLETE")
    print("=" * 70)
    print(f"📁 Results saved to: {RESULTS_DIR}")
    print(f"📊 Sessions processed: {len(group_z_matrices)}")
    print(f"🧬 ROIs per session: {len(all_roi_labels) if all_roi_labels else 'N/A'}")
    print()


if __name__ == "__main__":
    main()
