#!/usr/bin/env python3
"""
Functional Connectivity Visualization
Creates heatmaps and network visualizations for FC matrices.
"""

import os
import json
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

# Configuration
PROJECT_ROOT = Path(__file__).parent.parent
RESULTS_DIR = PROJECT_ROOT / "results" / "connectivity"
VIS_DIR = RESULTS_DIR / "visualizations"

VIS_DIR.mkdir(exist_ok=True)

# Set style
plt.style.use("seaborn-v0_8-darkgrid")
sns.set_palette("husl")


def create_connectome_heatmap(matrix, roi_labels, title, output_file, vmin=-1, vmax=1):
    """Create and save FC heatmap."""
    fig, ax = plt.subplots(figsize=(14, 12))

    sns.heatmap(
        matrix,
        cmap="coolwarm",
        center=0,
        vmin=vmin,
        vmax=vmax,
        square=True,
        cbar_kws={"label": "Correlation"},
        ax=ax,
        xticklabels=False,
        yticklabels=False,
    )

    ax.set_title(title, fontsize=16, fontweight="bold", pad=20)
    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"✓ Saved: {output_file.name}")


def create_degree_distribution(degree_list, roi_labels, title, output_file):
    """Create degree centrality distribution plot."""
    # Remove NaN values
    degree_list = degree_list[~np.isnan(degree_list)]
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # Histogram
    ax1.hist(degree_list, bins=20, edgecolor="black", alpha=0.7)
    ax1.set_xlabel("Degree Centrality", fontsize=11)
    ax1.set_ylabel("Frequency", fontsize=11)
    ax1.set_title(f"{title}\nDegree Distribution", fontsize=12, fontweight="bold")
    ax1.axvline(np.mean(degree_list), color="r", linestyle="--", label=f"Mean: {np.mean(degree_list):.3f}")
    ax1.legend()

    # Top hubs (sorted)
    top_n = 20
    top_idx = np.argsort(degree_list)[-top_n:]
    top_rois = [roi_labels[i] for i in top_idx]
    top_values = [degree_list[i] for i in top_idx]

    ax2.barh(range(len(top_rois)), top_values, color="steelblue", edgecolor="black")
    ax2.set_yticks(range(len(top_rois)))
    ax2.set_yticklabels(top_rois, fontsize=9)
    ax2.set_xlabel("Degree Centrality", fontsize=11)
    ax2.set_title(f"Top {top_n} Hub Regions", fontsize=12, fontweight="bold")
    ax2.invert_yaxis()

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"✓ Saved: {output_file.name}")


def create_subject_comparison(subjects_data, output_file):
    """Create comparison plot across subjects."""
    fig, axes = plt.subplots(2, 2, figsize=(14, 12))
    axes = axes.ravel()

    for idx, (subj, data) in enumerate(subjects_data.items()):
        # Plot mean FC strength by atlas region type
        matrix = data["matrix"]
        mean_conn = np.abs(matrix).mean(axis=1)
        # Remove NaN values
        mean_conn = mean_conn[~np.isnan(mean_conn)]

        if len(mean_conn) > 0:
            axes[idx].hist(mean_conn, bins=15, edgecolor="black", alpha=0.7, color="steelblue")
            axes[idx].set_title(f"{subj}\nMean Connection Strength", fontsize=12, fontweight="bold")
            axes[idx].set_xlabel("Mean |Correlation|", fontsize=10)
            axes[idx].set_ylabel("Frequency", fontsize=10)
            axes[idx].axvline(np.mean(mean_conn), color="r", linestyle="--", linewidth=2, label="Mean")
            axes[idx].legend()
        else:
            axes[idx].text(0.5, 0.5, "No valid data", ha="center", va="center")
            axes[idx].set_title(f"{subj}\n(No data)", fontsize=12, fontweight="bold")

    plt.tight_layout()
    plt.savefig(output_file, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"✓ Saved: {output_file.name}")


def main():
    """Generate all visualizations."""
    print("=" * 70)
    print("GENERATING CONNECTIVITY VISUALIZATIONS")
    print("=" * 70)
    print()

    # Load group connectome
    group_file = RESULTS_DIR / "group_connectome.csv"
    if not group_file.exists():
        print("❌ group_connectome.csv not found. Run FC analysis first.")
        return

    group_matrix = pd.read_csv(group_file, index_col=0).values
    roi_labels = list(pd.read_csv(group_file, index_col=0).index)

    print(f"📊 Loaded group connectome: {group_matrix.shape}")

    # 1. Group connectome heatmap
    print("\n📈 Creating group connectome heatmap...")
    create_connectome_heatmap(
        group_matrix,
        roi_labels,
        "Group Functional Connectome\n(Average across 3 subjects, 6 sessions)",
        VIS_DIR / "group_connectome_heatmap.png",
    )

    # 2. Group degree distribution
    print("📈 Creating degree distribution plot...")
    group_degree = np.abs(group_matrix).mean(axis=1)
    # Remove any NaN values
    group_degree = group_degree[~np.isnan(group_degree)]
    create_degree_distribution(
        group_degree,
        roi_labels,
        "Group-Level Analysis",
        VIS_DIR / "degree_distribution_group.png",
    )

    # 3. Individual subject connectomes
    print("\n📈 Creating individual subject connectomes...")
    subjects = ["sub-066", "sub-068", "sub-072"]
    for subject in subjects:
        for session in ["ses-01", "ses-02"]:
            fc_file = RESULTS_DIR / "subject_fc_matrices" / f"{subject}_{session}_fc_pearson.csv"
            if fc_file.exists():
                matrix = pd.read_csv(fc_file, index_col=0).values
                create_connectome_heatmap(
                    matrix,
                    roi_labels,
                    f"{subject} / {session} Functional Connectome",
                    VIS_DIR / f"{subject}_{session}_connectome_heatmap.png",
                )

    # 4. Subject comparison
    print("\n📈 Creating subject comparison plot...")
    subjects_data = {}
    for subject in subjects:
        # Average across sessions for this subject
        matrices = []
        for session in ["ses-01", "ses-02"]:
            fc_file = RESULTS_DIR / "subject_fc_matrices" / f"{subject}_{session}_fc_pearson.csv"
            if fc_file.exists():
                matrices.append(pd.read_csv(fc_file, index_col=0).values)
        if matrices:
            subjects_data[subject] = {"matrix": np.mean(matrices, axis=0)}

    create_subject_comparison(subjects_data, VIS_DIR / "subject_comparison.png")

    # Print summary
    print("\n" + "=" * 70)
    print("✅ VISUALIZATION COMPLETE")
    print("=" * 70)
    print(f"📁 Visualizations saved to: {VIS_DIR}")
    if len(group_degree) > 0:
        hub_idx = np.argmax(group_degree)
        print(f"📊 Hub regions identified: {roi_labels[hub_idx]}")
        print(f"🧠 Mean degree centrality: {group_degree.mean():.3f} ± {group_degree.std():.3f}")
    print()


if __name__ == "__main__":
    main()
