#!/usr/bin/env python3
"""
group_matrix_stats.py — Group statistics over parcel-level connectivity matrices.

Supported methods
-----------------
paired_t_fdr
    Paired t-test per edge, BH-FDR correction across all edges.
    Parametric, fast.  No threshold parameter required.

nbs
    Network-Based Statistic (Zalesky et al. 2010).
    Threshold edge-level t-statistic to build a graph, find connected
    components, permute (sign-flip for paired data) to build null
    distribution of maximum component edge-count; corrected p-value per
    component = fraction of nulls ≥ observed size.

tfnbs
    Threshold-Free NBS (Baggio et al. 2018).
    TFCE-like integral enhancement on the edge-statistic graph;
    permutation-based (max-statistic) FWER correction per edge.

Supported contrasts
-------------------
ses-02_minus_ses-01
    Paired within-subject contrast: X₂ − X₁.

Input discovery
---------------
kind=network
    derivatives/connectivity/{pipeline}/sub-XX/ses-YY/network/
    atlas-{atlas}/sub-XX_ses-YY_atlas-{atlas}_measure-{measure}_relmat[z].tsv

kind=seed
    derivatives/connectivity/{pipeline}/sub-XX/ses-YY/seed/{seed-id}/
    *_atlas-{seed-target-atlas}_measure-{measure}_seed-to-parcel.tsv

Outputs (in --out directory)
----------------------------
tstat.tsv            parcel × parcel (or 1 × N) t-statistic matrix
pcorr.tsv            corrected p-value matrix (same shape)
significant_edges.tsv  long-format: parcel_i, parcel_j, t, p_corr, sig
report.json          method params, N, runtime, RNG seed
report.html          summary + embedded -log10(p) heatmap
components.tsv       [NBS only] component_id, size, p, member_edges

Usage
-----
python script/group_matrix_stats.py \\
    --bids-root /home/clivewong/proj/longevity \\
    --pipeline fc \\
    --kind network \\
    --atlas 4S256Parcels \\
    --measure pearson \\
    --contrast ses-02_minus_ses-01 \\
    --method nbs \\
    --threshold 3.1 \\
    --n-permutations 5000 \\
    --alpha 0.05 \\
    --group-csv /home/clivewong/proj/longevity/group.csv \\
    --out derivatives/connectivity/group/matrix/fc/ses-02_minus_ses-01/4S256Parcels/pearson/nbs/
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Optional

import networkx as nx
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import fdrcorrection

# ---------------------------------------------------------------------------
# Repo path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "script"))
sys.path.insert(0, str(REPO_ROOT / "neuconn_app"))

from connectivity_measures import fisher_z, CORRELATION_TYPE  # noqa: E402
from utils.xcpd_outputs import XcpdDiscovery  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Maps contrast name → (session_a, session_b) so diff = ses_b − ses_a
CONTRAST_PATTERNS: dict[str, tuple[str, str]] = {
    "ses-02_minus_ses-01": ("ses-01", "ses-02"),
}

METHODS = {"paired_t_fdr", "nbs", "tfnbs"}


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_network_matrix(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
    atlas: str,
    measure: str,
) -> Optional[Path]:
    """Return path to network relmat TSV for one (subject, session), or None."""
    z = "z" if measure in CORRELATION_TYPE else ""
    conn_dir = (
        bids_root
        / "derivatives"
        / "connectivity"
        / pipeline
        / subject
        / session
        / "network"
        / f"atlas-{atlas}"
    )
    if not conn_dir.exists():
        return None
    # Exact filename first
    exact = conn_dir / f"{subject}_{session}_atlas-{atlas}_measure-{measure}_relmat{z}.tsv"
    if exact.exists():
        return exact
    # Glob fallback
    matches = sorted(conn_dir.glob(f"*_measure-{measure}_relmat{z}.tsv"))
    return matches[0] if matches else None


def find_seed_matrix(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
    seed_id: str,
    measure: str,
    target_atlas: str,
) -> Optional[Path]:
    """Return path to seed-to-parcel TSV for one (subject, session), or None."""
    seed_dir = (
        bids_root
        / "derivatives"
        / "connectivity"
        / pipeline
        / subject
        / session
        / "seed"
        / seed_id
    )
    if not seed_dir.exists():
        return None
    matches = sorted(seed_dir.glob(f"*_atlas-{target_atlas}_measure-{measure}_seed-to-parcel.tsv"))
    return matches[0] if matches else None


# ---------------------------------------------------------------------------
# Matrix I/O
# ---------------------------------------------------------------------------

def load_matrix(path: Path) -> tuple[np.ndarray, list[str]]:
    """
    Load a TSV connectivity matrix.

    Returns
    -------
    matrix : ndarray, shape (n_rows, n_cols)
    labels : list[str] — column names (parcel labels)
    """
    df = pd.read_csv(path, sep="\t", index_col=0)
    return df.values.astype(np.float64), list(df.columns)


def load_paired_matrices(
    bids_root: Path,
    pipeline: str,
    kind: str,
    atlas: Optional[str],
    seed_id: Optional[str],
    measure: str,
    contrast: str,
    group_csv: Path,
    seed_target_atlas: Optional[str] = None,
) -> tuple[np.ndarray, np.ndarray, list[str], list[str]]:
    """
    Discover and load connectivity matrices for all subjects with both sessions.

    Returns
    -------
    X1 : ndarray, shape (N, n_rows, n_cols)  — session A
    X2 : ndarray, shape (N, n_rows, n_cols)  — session B  (contrast = X2 − X1)
    labels : list[str] — column (parcel) labels
    subjects : list[str] — included subject IDs
    """
    if contrast not in CONTRAST_PATTERNS:
        raise ValueError(
            f"Unknown contrast '{contrast}'. Known: {sorted(CONTRAST_PATTERNS)}"
        )
    ses_a, ses_b = CONTRAST_PATTERNS[contrast]

    gdf = pd.read_csv(group_csv)
    if "subject_id" not in gdf.columns:
        raise ValueError("group.csv must contain a 'subject_id' column")
    all_subjects = sorted(gdf["subject_id"].tolist())

    effective_atlas = seed_target_atlas or atlas

    mats_a: list[np.ndarray] = []
    mats_b: list[np.ndarray] = []
    included: list[str] = []
    labels_ref: Optional[list[str]] = None

    for sub in all_subjects:
        if kind == "network":
            if atlas is None:
                raise ValueError("--atlas is required for kind=network")
            path_a = find_network_matrix(bids_root, pipeline, sub, ses_a, atlas, measure)
            path_b = find_network_matrix(bids_root, pipeline, sub, ses_b, atlas, measure)
        else:  # seed
            if seed_id is None:
                raise ValueError("--seed-id is required for kind=seed")
            if effective_atlas is None:
                raise ValueError("--seed-target-atlas (or --atlas) is required for kind=seed")
            path_a = find_seed_matrix(
                bids_root, pipeline, sub, ses_a, seed_id, measure, effective_atlas
            )
            path_b = find_seed_matrix(
                bids_root, pipeline, sub, ses_b, seed_id, measure, effective_atlas
            )

        if path_a is None or path_b is None:
            continue

        mat_a, labels_a = load_matrix(path_a)
        mat_b, labels_b = load_matrix(path_b)

        if mat_a.shape != mat_b.shape:
            continue

        if labels_ref is None:
            labels_ref = labels_a

        mats_a.append(mat_a)
        mats_b.append(mat_b)
        included.append(sub)

    if not included:
        raise RuntimeError(
            "No subjects with both sessions found.  "
            "Check --pipeline, --kind, --atlas, and connectivity output paths."
        )

    return (
        np.stack(mats_a, axis=0),
        np.stack(mats_b, axis=0),
        labels_ref or [],
        included,
    )


# ---------------------------------------------------------------------------
# Edge extraction utilities
# ---------------------------------------------------------------------------

def upper_tri_indices(n: int) -> tuple[np.ndarray, np.ndarray]:
    """Upper-triangle (row, col) index arrays, excluding diagonal."""
    return np.triu_indices(n, k=1)


def extract_edge_diffs(
    X1: np.ndarray, X2: np.ndarray, kind: str
) -> tuple[np.ndarray, int, bool]:
    """
    Compute per-edge difference matrices.

    For square (network) matrices: extract upper triangle.
    For non-square (seed): flatten all columns.

    Returns
    -------
    diffs    : ndarray, shape (N_subjects, n_edges)
    n_parcels: int — number of columns (parcels)
    is_square: bool
    """
    n_sub, n_rows, n_cols = X1.shape
    diff = X2 - X1  # (N, rows, cols)

    if kind == "network" and n_rows == n_cols:
        ri, ci = upper_tri_indices(n_rows)
        return diff[:, ri, ci], n_rows, True
    else:
        return diff.reshape(n_sub, n_rows * n_cols), n_cols, False


def rebuild_matrix(
    vec: np.ndarray, n_parcels: int, is_square: bool, n_rows: int = 1
) -> np.ndarray:
    """
    Reconstruct a full matrix from an edge vector.

    For square: symmetric NxN.
    For non-square (seed): 1×N_parcels.
    """
    if is_square:
        mat = np.zeros((n_parcels, n_parcels))
        ri, ci = upper_tri_indices(n_parcels)
        mat[ri, ci] = vec
        mat[ci, ri] = vec
        return mat
    else:
        return vec.reshape(n_rows, n_parcels)


# ---------------------------------------------------------------------------
# Core statistics
# ---------------------------------------------------------------------------

def _paired_t(diffs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Paired t-statistic and two-tailed p-value for each edge.

    Parameters
    ----------
    diffs : ndarray, shape (N_subjects, n_edges)

    Returns
    -------
    t : ndarray, shape (n_edges,)
    p : ndarray, shape (n_edges,)
    """
    n = diffs.shape[0]
    mean = diffs.mean(axis=0)
    std = diffs.std(axis=0, ddof=1)
    # Avoid division by zero
    std = np.where(std == 0.0, np.nan, std)
    t = mean / (std / np.sqrt(n))
    p = 2.0 * stats.t.sf(np.abs(t), df=n - 1)
    p = np.where(np.isnan(t), 1.0, p)
    t = np.where(np.isnan(t), 0.0, t)
    return t, p


# ----- Method 1: paired t + BH-FDR ----------------------------------------

def run_paired_t_fdr(
    diffs: np.ndarray,
    alpha: float = 0.05,
) -> dict:
    """
    Paired t-test per edge, BH-FDR correction across edges.

    Returns keys: t, p_uncorr, p_corr, rejected
    """
    t, p = _paired_t(diffs)
    _, p_fdr = fdrcorrection(p, alpha=alpha)
    return {
        "t": t,
        "p_uncorr": p,
        "p_corr": p_fdr,
        "rejected": p_fdr < alpha,
    }


# ----- NBS helpers ----------------------------------------------------------

def _build_component_graph(
    t_abs: np.ndarray,
    threshold: float,
    i_idx: np.ndarray,
    j_idx: np.ndarray,
    n_parcels: int,
) -> list[tuple[list[int], int]]:
    """
    Threshold |t|, build graph, return list of (edge_indices, n_edges) per component.
    """
    above = np.where(t_abs >= threshold)[0]
    if len(above) == 0:
        return []

    G = nx.Graph()
    G.add_nodes_from(range(n_parcels))
    for e in above:
        G.add_edge(i_idx[e], j_idx[e])

    # Precompute (u,v)->edge_index for edges above threshold
    edge_lookup: dict[tuple[int, int], int] = {}
    for e in above:
        edge_lookup[(int(i_idx[e]), int(j_idx[e]))] = e

    components = []
    for comp_nodes in nx.connected_components(G):
        subg = G.subgraph(comp_nodes)
        nx_edges = list(subg.edges())
        if not nx_edges:
            continue
        edge_indices = []
        for u, v in nx_edges:
            key = (min(u, v), max(u, v))
            e = edge_lookup.get(key)
            if e is not None:
                edge_indices.append(e)
        if edge_indices:
            components.append((edge_indices, len(edge_indices)))
    return components


# ----- Method 2: NBS --------------------------------------------------------

def run_nbs(
    diffs: np.ndarray,
    n_parcels: int,
    is_square: bool,
    threshold: float,
    n_permutations: int = 5000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict:
    """
    Network-Based Statistic (Zalesky et al. 2010).

    Permutation strategy: sign-flip paired differences.
    Component size = number of edges (as in the original paper).

    Returns keys: t, p_uncorr, p_corr, rejected, components
    """
    rng = np.random.default_rng(seed)
    n_sub, n_edges = diffs.shape

    t, p_uncorr = _paired_t(diffs)
    t_abs = np.abs(t)

    if is_square:
        i_idx, j_idx = upper_tri_indices(n_parcels)

        def _max_comp_size(t_vec: np.ndarray) -> int:
            comps = _build_component_graph(
                np.abs(t_vec), threshold, i_idx, j_idx, n_parcels
            )
            return max((c[1] for c in comps), default=0)

        obs_components = _build_component_graph(t_abs, threshold, i_idx, j_idx, n_parcels)
    else:
        i_idx = j_idx = np.array([], dtype=int)

        def _max_comp_size(t_vec: np.ndarray) -> int:
            return int(np.sum(np.abs(t_vec) >= threshold))

        above = np.where(t_abs >= threshold)[0]
        obs_components = (
            [(above.tolist(), len(above))] if len(above) > 0 else []
        )

    # Build null distribution of maximum component size
    null_max = np.zeros(n_permutations, dtype=int)
    for perm in range(n_permutations):
        signs = rng.choice(np.array([-1.0, 1.0]), size=n_sub)
        t_perm, _ = _paired_t(diffs * signs[:, np.newaxis])
        null_max[perm] = _max_comp_size(t_perm)

    # Assign p-values and build output records
    p_corr = np.ones(n_edges)
    component_records: list[dict] = []

    for comp_id, (edge_indices, comp_size) in enumerate(obs_components):
        p_comp = float(
            (np.sum(null_max >= comp_size) + 1) / (n_permutations + 1)
        )
        for e in edge_indices:
            p_corr[e] = p_comp

        if is_square:
            member = [(int(i_idx[e]), int(j_idx[e])) for e in edge_indices]
        else:
            member = edge_indices

        component_records.append(
            {
                "component_id": comp_id,
                "size": comp_size,
                "p": p_comp,
                "member_edges": str(member),
            }
        )

    return {
        "t": t,
        "p_uncorr": p_uncorr,
        "p_corr": p_corr,
        "rejected": p_corr < alpha,
        "components": component_records,
    }


# ----- Method 3: TF-NBS -----------------------------------------------------

def run_tfnbs(
    diffs: np.ndarray,
    n_parcels: int,
    is_square: bool,
    threshold: float,
    n_permutations: int = 5000,
    alpha: float = 0.05,
    seed: int = 42,
    E: float = 0.5,
    H: float = 2.0,
    n_thresholds: int = 50,
) -> dict:
    """
    Threshold-Free NBS (Baggio et al. 2018).

    TFCE-like integral enhancement:
        score(e) = ∫_{h ≥ threshold} extent(e, h)^E · h^H dh

    Correction: max-statistic FWER across edges via sign-flip permutations.

    Returns keys: t, p_uncorr, p_corr, rejected
    """
    rng = np.random.default_rng(seed)
    n_sub, n_edges = diffs.shape

    t, p_uncorr = _paired_t(diffs)

    if is_square:
        i_idx, j_idx = upper_tri_indices(n_parcels)
        edge_lookup: dict[tuple[int, int], int] = {
            (int(i_idx[e]), int(j_idx[e])): e for e in range(n_edges)
        }

    def _compute_scores(t_vec: np.ndarray) -> np.ndarray:
        """TF-NBS enhancement score per edge."""
        scores = np.zeros(n_edges)
        t_abs = np.abs(t_vec)
        max_t = float(np.nanmax(t_abs))
        if max_t <= threshold:
            return scores

        h_vals = np.linspace(threshold, max_t, n_thresholds)
        dh = (max_t - threshold) / max(n_thresholds - 1, 1)

        if is_square:
            G = nx.Graph()
            G.add_nodes_from(range(n_parcels))

            for h in h_vals:
                above = np.where(t_abs >= h)[0]
                if len(above) == 0:
                    continue
                G.clear_edges()
                for e in above:
                    G.add_edge(i_idx[e], j_idx[e])
                for comp_nodes in nx.connected_components(G):
                    subg = G.subgraph(comp_nodes)
                    nx_edges = list(subg.edges())
                    extent = len(nx_edges)
                    if extent == 0:
                        continue
                    increment = (extent ** E) * (h ** H) * dh
                    for u, v in nx_edges:
                        key = (min(u, v), max(u, v))
                        e = edge_lookup.get(key)
                        if e is not None:
                            scores[e] += increment
        else:
            for h in h_vals:
                above = np.where(t_abs >= h)[0]
                extent = len(above)
                if extent > 0:
                    scores[above] += (extent ** E) * (h ** H) * dh

        return scores

    obs_scores = _compute_scores(t)

    # Null max-statistic distribution
    null_max = np.zeros(n_permutations)
    for perm in range(n_permutations):
        signs = rng.choice(np.array([-1.0, 1.0]), size=n_sub)
        t_perm, _ = _paired_t(diffs * signs[:, np.newaxis])
        perm_scores = _compute_scores(t_perm)
        null_max[perm] = perm_scores.max() if perm_scores.max() > 0 else 0.0

    # Per-edge FWER p-value
    p_corr = np.ones(n_edges)
    for e in range(n_edges):
        if obs_scores[e] > 0:
            p_corr[e] = float(
                (np.sum(null_max >= obs_scores[e]) + 1) / (n_permutations + 1)
            )

    return {
        "t": t,
        "p_uncorr": p_uncorr,
        "p_corr": p_corr,
        "rejected": p_corr < alpha,
    }


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _make_matrix_df(
    vec: np.ndarray,
    labels: list[str],
    n_parcels: int,
    is_square: bool,
    n_rows_orig: int = 1,
    row_label: str = "seed",
) -> pd.DataFrame:
    """Reconstruct DataFrame from edge vector."""
    if is_square:
        mat = rebuild_matrix(vec, n_parcels, is_square)
        return pd.DataFrame(mat, index=labels, columns=labels)
    else:
        mat = rebuild_matrix(vec, n_parcels, is_square, n_rows=n_rows_orig)
        row_labels = [row_label] * mat.shape[0]
        return pd.DataFrame(mat, index=row_labels, columns=labels)


def _make_significant_edges(
    t_vec: np.ndarray,
    p_corr: np.ndarray,
    labels: list[str],
    n_parcels: int,
    is_square: bool,
    alpha: float,
) -> pd.DataFrame:
    """Build long-format significant edges table."""
    if is_square:
        ri, ci = upper_tri_indices(n_parcels)
        rows = {
            "parcel_i": [labels[r] for r in ri],
            "parcel_j": [labels[c] for c in ci],
            "t": t_vec,
            "p_corr": p_corr,
            "sig": p_corr < alpha,
        }
    else:
        rows = {
            "parcel_i": ["seed"] * len(t_vec),
            "parcel_j": labels[: len(t_vec)],
            "t": t_vec,
            "p_corr": p_corr,
            "sig": p_corr < alpha,
        }
    return pd.DataFrame(rows)


def _make_heatmap_png(p_corr_mat: np.ndarray, title: str) -> bytes:
    """Render -log10(p_corr) heatmap; return PNG bytes."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    data = -np.log10(np.clip(p_corr_mat, 1e-10, 1.0))
    fig, ax = plt.subplots(figsize=(8, 6))
    im = ax.imshow(data, aspect="auto", cmap="hot_r", vmin=0)
    plt.colorbar(im, ax=ax, label="-log₁₀(p_corr)")
    ax.set_title(title)
    ax.set_xlabel("Parcel index")
    ax.set_ylabel("Parcel index")
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def write_outputs(
    out_dir: Path,
    result: dict,
    labels: list[str],
    n_parcels: int,
    is_square: bool,
    method: str,
    report_meta: dict,
    alpha: float,
    n_rows_orig: int = 1,
) -> None:
    """Write all output files to *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)

    t_vec = result["t"]
    p_corr = result["p_corr"]

    # tstat.tsv
    t_df = _make_matrix_df(t_vec, labels, n_parcels, is_square, n_rows_orig)
    t_df.to_csv(out_dir / "tstat.tsv", sep="\t")

    # pcorr.tsv
    p_df = _make_matrix_df(p_corr, labels, n_parcels, is_square, n_rows_orig)
    p_df.to_csv(out_dir / "pcorr.tsv", sep="\t")

    # significant_edges.tsv
    sig_df = _make_significant_edges(
        t_vec, p_corr, labels, n_parcels, is_square, alpha
    )
    sig_df.to_csv(out_dir / "significant_edges.tsv", sep="\t", index=False)

    # components.tsv (NBS only)
    if "components" in result and result["components"]:
        comp_df = pd.DataFrame(result["components"])
        comp_df.to_csv(out_dir / "components.tsv", sep="\t", index=False)

    # report.json
    with open(out_dir / "report.json", "w") as f:
        json.dump(report_meta, f, indent=2, default=str)

    # report.html with embedded heatmap
    n_sig = int(np.sum(p_corr < alpha))
    p_mat = p_df.values.astype(np.float64)
    try:
        png_bytes = _make_heatmap_png(p_mat, f"{method} corrected -log₁₀(p)")
        img_b64 = base64.b64encode(png_bytes).decode()
        img_tag = f'<img src="data:image/png;base64,{img_b64}" alt="heatmap"/>'
    except Exception:
        img_tag = "<p><em>Heatmap unavailable.</em></p>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>Group Matrix Stats — {method}</title>
<style>body{{font-family:sans-serif;max-width:900px;margin:auto;padding:1em}}
table{{border-collapse:collapse}}td,th{{border:1px solid #ccc;padding:4px 8px}}
th{{background:#eee}}</style></head>
<body>
<h1>Group Matrix Statistics</h1>
<h2>Method: {method}</h2>
<table>
{"".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in report_meta.items())}
</table>
<h3>Significant edges: {n_sig}</h3>
<h3>Corrected -log₁₀(p) heatmap</h3>
{img_tag}
</body>
</html>
"""
    (out_dir / "report.html").write_text(html)


# ---------------------------------------------------------------------------
# Public API (importable)
# ---------------------------------------------------------------------------

def run_group_matrix_stats(
    bids_root: Path,
    pipeline: str,
    kind: str,
    atlas: Optional[str],
    seed_id: Optional[str],
    measure: str,
    contrast: str,
    method: str,
    threshold: float,
    n_permutations: int,
    alpha: float,
    group_csv: Path,
    out_dir: Path,
    seed_target_atlas: Optional[str] = None,
    rng_seed: int = 42,
) -> dict:
    """
    End-to-end group matrix statistics pipeline.

    Returns the result dict from the chosen method.
    """
    t0 = time.time()

    # Load data
    X1, X2, labels, subjects = load_paired_matrices(
        bids_root=bids_root,
        pipeline=pipeline,
        kind=kind,
        atlas=atlas,
        seed_id=seed_id,
        measure=measure,
        contrast=contrast,
        group_csv=group_csv,
        seed_target_atlas=seed_target_atlas,
    )

    diffs, n_parcels, is_square = extract_edge_diffs(X1, X2, kind)
    n_rows_orig = X1.shape[1]

    # Run selected method
    kwargs_perm = dict(
        n_permutations=n_permutations,
        alpha=alpha,
        seed=rng_seed,
    )

    if method == "paired_t_fdr":
        result = run_paired_t_fdr(diffs, alpha=alpha)
    elif method == "nbs":
        result = run_nbs(
            diffs, n_parcels, is_square, threshold, **kwargs_perm
        )
    elif method == "tfnbs":
        result = run_tfnbs(
            diffs, n_parcels, is_square, threshold, **kwargs_perm
        )
    else:
        raise ValueError(f"Unknown method '{method}'. Choose from: {sorted(METHODS)}")

    runtime = time.time() - t0

    report_meta = {
        "method": method,
        "contrast": contrast,
        "measure": measure,
        "kind": kind,
        "atlas": atlas,
        "seed_id": seed_id,
        "n_subjects": len(subjects),
        "n_parcels": n_parcels,
        "n_edges": len(result["t"]),
        "n_significant": int(np.sum(result["rejected"])),
        "threshold_t": threshold,
        "n_permutations": n_permutations,
        "alpha": alpha,
        "rng_seed": rng_seed,
        "runtime_s": round(runtime, 2),
        "subjects": subjects,
    }

    write_outputs(
        out_dir=out_dir,
        result=result,
        labels=labels,
        n_parcels=n_parcels,
        is_square=is_square,
        method=method,
        report_meta=report_meta,
        alpha=alpha,
        n_rows_orig=n_rows_orig,
    )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--bids-root", required=True, type=Path, help="Project BIDS root")
    p.add_argument(
        "--pipeline",
        default="fc",
        choices=["fc", "fc_gsr", "ec"],
        help="XCP-D pipeline name",
    )
    p.add_argument(
        "--kind",
        required=True,
        choices=["network", "seed"],
        help="Input matrix type",
    )
    p.add_argument("--atlas", default=None, help="Atlas name (required for kind=network)")
    p.add_argument("--seed-id", default=None, help="Seed identifier (required for kind=seed)")
    p.add_argument(
        "--seed-target-atlas",
        default=None,
        help="Target parcel atlas for seed-to-parcel TSV (defaults to --atlas)",
    )
    p.add_argument("--measure", required=True, help="Connectivity measure (e.g. pearson)")
    p.add_argument(
        "--contrast",
        required=True,
        choices=list(CONTRAST_PATTERNS),
        help="Contrast specification",
    )
    p.add_argument(
        "--method",
        required=True,
        choices=sorted(METHODS),
        help="Statistical method",
    )
    p.add_argument(
        "--threshold",
        type=float,
        default=3.1,
        help="Cluster-forming t-threshold for NBS / TF-NBS",
    )
    p.add_argument(
        "--n-permutations",
        type=int,
        default=5000,
        help="Number of sign-flip permutations",
    )
    p.add_argument("--alpha", type=float, default=0.05, help="Significance level")
    p.add_argument("--group-csv", required=True, type=Path, help="group.csv with subject_id column")
    p.add_argument("--out", required=True, type=Path, help="Output directory")
    p.add_argument("--seed", type=int, default=42, help="RNG seed for permutations")
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = _build_parser().parse_args(argv)

    bids_root = args.bids_root.resolve()
    out_dir = args.out if args.out.is_absolute() else bids_root / args.out

    result = run_group_matrix_stats(
        bids_root=bids_root,
        pipeline=args.pipeline,
        kind=args.kind,
        atlas=args.atlas,
        seed_id=args.seed_id,
        measure=args.measure,
        contrast=args.contrast,
        method=args.method,
        threshold=args.threshold,
        n_permutations=args.n_permutations,
        alpha=args.alpha,
        group_csv=args.group_csv,
        out_dir=out_dir,
        seed_target_atlas=args.seed_target_atlas,
        rng_seed=args.seed,
    )

    n_sig = int(np.sum(result["rejected"]))
    print(f"[group_matrix_stats] method={args.method}  N_sig={n_sig}  out={out_dir}")


if __name__ == "__main__":
    main()
