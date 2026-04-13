"""
Framewise displacement inspection utilities for the XCP-D gate.
"""

from __future__ import annotations

from math import ceil
from pathlib import Path
from typing import Dict, List
import math

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


def find_confounds_files(fmriprep_dir: Path) -> List[Path]:
    """Return all confounds files beneath the fMRIPrep derivatives root."""
    return sorted(fmriprep_dir.glob("sub-*/ses-*/func/*_desc-confounds_timeseries.tsv"))


def build_fd_summary(fmriprep_dir: Path, output_dir: Path, tr: float = 0.8) -> pd.DataFrame:
    """Compute the per-subject/session FD summary table."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []

    for confounds_file in find_confounds_files(fmriprep_dir):
        try:
            confounds = pd.read_csv(confounds_file, sep="\t")
        except Exception:
            continue

        if "framewise_displacement" not in confounds:
            continue

        fd = confounds["framewise_displacement"].fillna(0.0)
        subject = next(part for part in confounds_file.parts if part.startswith("sub-"))
        session = next(part for part in confounds_file.parts if part.startswith("ses-"))
        total_volumes = int(fd.shape[0])

        rows.append(
            {
                "subject_id": subject,
                "session": session,
                "mean_fd": float(fd.mean()),
                "median_fd": float(fd.median()),
                "peak_fd": float(fd.max()),
                "pct_vols_gt_0.3": float((fd > 0.3).mean() * 100),
                "pct_vols_gt_0.5": float((fd > 0.5).mean() * 100),
                "pct_vols_gt_0.8": float((fd > 0.8).mean() * 100),
                "pct_vols_gt_1.5": float((fd > 1.5).mean() * 100),
                "total_volumes": total_volumes,
                "est_remaining_60s": float((fd <= 0.3).sum() * tr),
                "est_remaining_100s": float((fd <= 0.5).sum() * tr),
                "confounds_file": str(confounds_file),
            }
        )

    summary = pd.DataFrame(rows).sort_values(["subject_id", "session"])
    summary.to_csv(output_dir / "fd_summary.csv", index=False)
    return summary


def generate_fd_plots(
    fmriprep_dir: Path,
    output_dir: Path,
    summary: pd.DataFrame,
) -> Dict[str, Path]:
    """Generate the requested FD plots."""
    output_dir.mkdir(parents=True, exist_ok=True)
    plots: Dict[str, Path] = {}

    if summary.empty:
        return plots

    sns.set_theme(style="whitegrid")

    histogram_path = output_dir / "fd_group_histogram.png"
    fig, ax = plt.subplots(figsize=(10, 6))
    sns.histplot(summary["mean_fd"], bins=20, ax=ax, color="#4c72b0")
    thresholds = [0.3, 0.5, 0.8]
    total = len(summary)
    for threshold, color in zip(thresholds, ["green", "orange", "red"]):
        count = int((summary["mean_fd"] > threshold).sum())
        ax.axvline(threshold, color=color, linestyle="--", linewidth=2)
        ax.text(
            threshold,
            ax.get_ylim()[1] * 0.9,
            f">{threshold:.1f}: {count}/{total} ({100 * count / max(total, 1):.1f}%)",
            rotation=90,
            va="top",
            ha="right",
            color=color,
        )
    ax.set_title("Mean FD distribution across all subject-session runs")
    ax.set_xlabel("Mean FD (mm)")
    fig.tight_layout()
    fig.savefig(histogram_path, dpi=150)
    plt.close(fig)
    plots["fd_group_histogram"] = histogram_path

    boxplot_path = output_dir / "fd_boxplot_by_session.png"
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.boxplot(data=summary, x="session", y="mean_fd", ax=ax)
    ax.set_title("Mean FD by session")
    ax.set_xlabel("Session")
    ax.set_ylabel("Mean FD (mm)")
    fig.tight_layout()
    fig.savefig(boxplot_path, dpi=150)
    plt.close(fig)
    plots["fd_boxplot_by_session"] = boxplot_path

    series_path = output_dir / "fd_timeseries_all_subjects.png"
    confound_paths = [
        Path(path)
        for path in summary["confounds_file"].tolist()
        if Path(path).exists()
    ]
    n_panels = len(confound_paths)
    cols = 4
    rows = ceil(n_panels / cols)
    fig, axes = plt.subplots(rows, cols, figsize=(18, max(4, rows * 3)), squeeze=False)
    axes_flat = axes.flatten()

    summary_index = summary.set_index(["subject_id", "session"])
    for ax in axes_flat[n_panels:]:
        ax.axis("off")

    for ax, confounds_path in zip(axes_flat, confound_paths):
        confounds = pd.read_csv(confounds_path, sep="\t")
        fd = confounds["framewise_displacement"].fillna(0.0)
        subject = next(part for part in confounds_path.parts if part.startswith("sub-"))
        session = next(part for part in confounds_path.parts if part.startswith("ses-"))
        mean_fd = float(summary_index.loc[(subject, session), "mean_fd"])
        color = "red" if mean_fd > 0.5 else "#4c72b0"
        ax.plot(fd.values, color=color, linewidth=1)
        ax.axhline(0.3, color="green", linestyle="--", linewidth=1)
        ax.axhline(0.5, color="orange", linestyle="--", linewidth=1)
        ax.set_title(f"{subject} {session}", fontsize=9)
        ax.set_ylim(0, max(1.5, float(fd.max()) + 0.1))
        ax.set_xticks([])
        ax.set_ylabel("FD", fontsize=8)

    fig.suptitle("Framewise displacement timeseries", fontsize=14)
    fig.tight_layout()
    fig.savefig(series_path, dpi=150)
    plt.close(fig)
    plots["fd_timeseries_all_subjects"] = series_path

    return plots


def fd_risk_color(mean_fd: float) -> str:
    """Return a coarse risk category for UI coloring."""
    if mean_fd <= 0.3:
        return "green"
    if mean_fd <= 0.5:
        return "amber"
    return "red"


def highlight_fd_rows(summary: pd.DataFrame) -> pd.DataFrame:
    """Add a coarse risk label to the summary table."""
    highlighted = summary.copy()
    highlighted["risk"] = highlighted["mean_fd"].map(fd_risk_color)
    return highlighted
