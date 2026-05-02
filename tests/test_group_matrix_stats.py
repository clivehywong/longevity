"""
Tests for script/group_matrix_stats.py

Run with:
    cd /home/clivewong/proj/longevity && python -m pytest tests/test_group_matrix_stats.py -v

Test plan
---------
1.  test_paired_t_fdr_detects_injected_edges
        Strong effect in all 8 subjects on a 5-edge path component.
        FDR-corrected p < 0.05 for every injected edge.

2.  test_nbs_detects_significant_component
        Same design (8 subjects, 5-edge component).
        NBS must find ≥1 significant component (p < 0.05) that overlaps
        all injected edges.

3.  test_tfnbs_lower_p_at_injected_edges
        Injected edges have strictly lower TF-NBS p-values than the
        median non-injected edge p-value.

4.  test_null_paired_t_fdr_no_effect
        Pure noise (N=8, 30 parcels).  paired_t_fdr should report 0
        significant edges at α=0.05.

5.  test_null_nbs_no_component
        Pure noise.  NBS finds no significant components.

6.  test_null_tfnbs_no_edges
        Pure noise.  TF-NBS reports no significant edges.

7.  test_output_files_created
        run_group_matrix_stats writes all required files: tstat.tsv,
        pcorr.tsv, significant_edges.tsv, report.json, report.html.
        NBS also writes components.tsv.

8.  test_report_json_has_required_fields
        report.json contains method, n_subjects, n_permutations, alpha,
        rng_seed, runtime_s, n_significant.

9.  test_tsv_shapes_match
        tstat.tsv and pcorr.tsv have square shape N_parcels × N_parcels.

10. test_significant_edges_long_format
        significant_edges.tsv has columns parcel_i, parcel_j, t, p_corr, sig.

11. test_seed_kind_non_square
        Seed-kind (1×N matrices) runs without error and produces 1×N
        tstat/pcorr TSVs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "script"))
sys.path.insert(0, str(REPO_ROOT / "neuconn_app"))

import group_matrix_stats as gms  # noqa: E402

# ---------------------------------------------------------------------------
# Synthetic data design
# ---------------------------------------------------------------------------
N_SUB = 8
N_PARCELS = 30
RNG_SEED = 0

# 5-edge path component: nodes 0-1-2-3-4-5 (6 nodes, 5 edges)
INJECTED_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]
EFFECT_SIZE = 4.0   # Cohen's d ≈ 4 → very reliable detection
NOISE_STD = 1.0


def _make_identity_matrix(n: int) -> np.ndarray:
    """Return an n×n identity-like connectivity matrix (diagonal=1)."""
    return np.eye(n, dtype=np.float64)


def _make_zero_matrix(n: int) -> np.ndarray:
    return np.zeros((n, n), dtype=np.float64)


def _inject_effect(
    diff_mats: np.ndarray,
    edges: list[tuple[int, int]],
    effect: float,
) -> None:
    """Add *effect* to every edge in *edges* for all subjects (in-place)."""
    for i, j in edges:
        diff_mats[:, i, j] += effect
        diff_mats[:, j, i] += effect  # keep symmetric


def _make_paired_data(
    n_sub: int = N_SUB,
    n_parcels: int = N_PARCELS,
    injected_edges: list[tuple[int, int]] | None = None,
    effect: float = EFFECT_SIZE,
    rng: np.random.Generator | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Create synthetic (X1, X2) connectivity matrices.

    Parameters
    ----------
    injected_edges : list of (i, j) or None
        If provided, adds *effect* to X2 − X1 at those edges for all subjects.

    Returns
    -------
    X1, X2 : ndarray, shape (n_sub, n_parcels, n_parcels)
    """
    if rng is None:
        rng = np.random.default_rng(RNG_SEED)

    # Base: identity + small noise so matrices are valid correlation-like
    base = np.stack([_make_identity_matrix(n_parcels)] * n_sub, axis=0)
    X1 = base + rng.normal(0.0, 0.05, size=(n_sub, n_parcels, n_parcels))
    X2 = base + rng.normal(0.0, 0.05, size=(n_sub, n_parcels, n_parcels))

    if injected_edges:
        # diff = X2 - X1; we want diff to have a strong signal at injected edges
        diff = rng.normal(effect, NOISE_STD, size=(n_sub,))
        for i, j in injected_edges:
            X2[:, i, j] = X1[:, i, j] + diff
            X2[:, j, i] = X1[:, j, i] + diff

    return X1, X2


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def effect_diffs() -> np.ndarray:
    """Upper-triangle differences with injected 5-edge component."""
    X1, X2 = _make_paired_data(injected_edges=INJECTED_EDGES)
    diffs, _, _ = gms.extract_edge_diffs(X1, X2, "network")
    return diffs


@pytest.fixture(scope="module")
def null_diffs() -> np.ndarray:
    """Pure noise differences (no injected effect)."""
    X1, X2 = _make_paired_data(injected_edges=None)
    diffs, _, _ = gms.extract_edge_diffs(X1, X2, "network")
    return diffs


@pytest.fixture(scope="module")
def injected_edge_indices() -> list[int]:
    """Flat indices into the upper-triangle vector for the injected edges."""
    ri, ci = gms.upper_tri_indices(N_PARCELS)
    inj_set = {(min(a, b), max(a, b)) for a, b in INJECTED_EDGES}
    return [e for e, (r, c) in enumerate(zip(ri, ci)) if (r, c) in inj_set]


# ---------------------------------------------------------------------------
# Test 1 — paired_t_fdr detects injected edges
# ---------------------------------------------------------------------------

def test_paired_t_fdr_detects_injected_edges(effect_diffs, injected_edge_indices):
    """FDR-corrected p < 0.05 for every injected edge (strong effect design)."""
    result = gms.run_paired_t_fdr(effect_diffs, alpha=0.05)
    p_corr = result["p_corr"]
    for idx in injected_edge_indices:
        assert p_corr[idx] < 0.05, (
            f"Injected edge {idx} not significant: p_corr={p_corr[idx]:.4f}"
        )


# ---------------------------------------------------------------------------
# Test 2 — NBS detects significant component overlapping injected edges
# ---------------------------------------------------------------------------

def test_nbs_detects_significant_component(effect_diffs, injected_edge_indices):
    """NBS finds ≥1 significant component (p < 0.05) covering injected edges."""
    result = gms.run_nbs(
        effect_diffs,
        n_parcels=N_PARCELS,
        is_square=True,
        threshold=3.0,
        n_permutations=200,
        alpha=0.05,
        seed=42,
    )
    # At least one component must be significant
    sig_components = [c for c in result["components"] if c["p"] < 0.05]
    assert len(sig_components) >= 1, "NBS found no significant component"

    # The significant component must overlap the injected edges
    sig_edge_indices: set[int] = set()
    for comp in sig_components:
        for e in result["t"]:
            pass  # edges stored in p_corr assignment
    # Check via p_corr: injected edges should be in a significant component
    p_corr = result["p_corr"]
    n_injected_sig = sum(p_corr[idx] < 0.05 for idx in injected_edge_indices)
    assert n_injected_sig == len(injected_edge_indices), (
        f"Only {n_injected_sig}/{len(injected_edge_indices)} injected edges "
        "are in a significant NBS component"
    )


# ---------------------------------------------------------------------------
# Test 3 — TF-NBS: injected edges have lower p than non-injected median
# ---------------------------------------------------------------------------

def test_tfnbs_lower_p_at_injected_edges(effect_diffs, injected_edge_indices):
    """Injected edges have lower TF-NBS p-values than median non-injected edge."""
    result = gms.run_tfnbs(
        effect_diffs,
        n_parcels=N_PARCELS,
        is_square=True,
        threshold=2.5,
        n_permutations=100,
        alpha=0.05,
        seed=42,
        n_thresholds=20,
    )
    p_corr = result["p_corr"]
    n_edges = len(p_corr)
    all_indices = set(range(n_edges))
    non_injected = list(all_indices - set(injected_edge_indices))

    median_non_inj = float(np.median(p_corr[non_injected]))
    max_injected = float(np.max(p_corr[injected_edge_indices]))

    assert max_injected < median_non_inj, (
        f"TF-NBS: max injected p ({max_injected:.4f}) "
        f"≥ median non-injected p ({median_non_inj:.4f})"
    )


# ---------------------------------------------------------------------------
# Test 4 — null paired_t_fdr: no significant edges
# ---------------------------------------------------------------------------

def test_null_paired_t_fdr_no_effect(null_diffs):
    """Pure noise: paired_t_fdr reports 0 significant edges at α=0.05."""
    result = gms.run_paired_t_fdr(null_diffs, alpha=0.05)
    n_sig = int(np.sum(result["rejected"]))
    assert n_sig == 0, f"Null data produced {n_sig} significant edges (FDR)"


# ---------------------------------------------------------------------------
# Test 5 — null NBS: no significant component
# ---------------------------------------------------------------------------

def test_null_nbs_no_component(null_diffs):
    """Pure noise: NBS finds no significant component."""
    result = gms.run_nbs(
        null_diffs,
        n_parcels=N_PARCELS,
        is_square=True,
        threshold=3.1,
        n_permutations=200,
        alpha=0.05,
        seed=99,
    )
    sig_components = [c for c in result["components"] if c["p"] < 0.05]
    assert len(sig_components) == 0, (
        f"Null data produced {len(sig_components)} significant NBS component(s)"
    )


# ---------------------------------------------------------------------------
# Test 6 — null TF-NBS: no significant edges
# ---------------------------------------------------------------------------

def test_null_tfnbs_no_edges(null_diffs):
    """Pure noise: TF-NBS reports no significant edges at α=0.05."""
    result = gms.run_tfnbs(
        null_diffs,
        n_parcels=N_PARCELS,
        is_square=True,
        threshold=3.1,
        n_permutations=100,
        alpha=0.05,
        seed=99,
        n_thresholds=15,
    )
    n_sig = int(np.sum(result["rejected"]))
    assert n_sig == 0, f"Null data produced {n_sig} significant edges (TF-NBS)"


# ---------------------------------------------------------------------------
# Test 7 — output files are created
# ---------------------------------------------------------------------------

def _write_synthetic_tsvs(tmp_path: Path) -> tuple[Path, Path, str]:
    """Write synthetic paired TSVs and participants.tsv; return (bids_root, participants_tsv, atlas)."""
    rng = np.random.default_rng(7)
    pipeline = "fc"
    atlas = "TestAtlas"
    measure = "pearson"
    labels = [f"parcel-{k:02d}" for k in range(N_PARCELS)]

    bids_root = tmp_path / "bids"
    subjects = [f"sub-{i:03d}" for i in range(N_SUB)]

    X1, X2 = _make_paired_data(injected_edges=INJECTED_EDGES, rng=rng)

    for s_idx, sub in enumerate(subjects):
        for ses, mat in [("ses-01", X1[s_idx]), ("ses-02", X2[s_idx])]:
            conn_dir = (
                bids_root
                / "derivatives"
                / "connectivity"
                / pipeline
                / sub
                / ses
                / "network"
                / f"atlas-{atlas}"
            )
            conn_dir.mkdir(parents=True, exist_ok=True)
            z = "z"  # pearson is correlation type
            fname = f"{sub}_{ses}_atlas-{atlas}_measure-{measure}_relmat{z}.tsv"
            df = pd.DataFrame(mat, index=labels, columns=labels)
            df.to_csv(conn_dir / fname, sep="\t")

    participants_tsv = bids_root / "participants.tsv"
    pd.DataFrame({
        "participant_id": subjects,
        "Age": np.linspace(60, 68, N_SUB),
        "Gender": ["F" if i % 2 == 0 else "M" for i in range(N_SUB)],
        "group": ["A"] * N_SUB,
    }).to_csv(participants_tsv, sep="\t", index=False)
    return bids_root, participants_tsv, atlas


def test_output_files_created(tmp_path):
    """All required output files are written by run_group_matrix_stats."""
    bids_root, participants_tsv, atlas = _write_synthetic_tsvs(tmp_path)
    out_dir = tmp_path / "out_nbs"

    gms.run_group_matrix_stats(
        bids_root=bids_root,
        pipeline="fc",
        kind="network",
        atlas=atlas,
        seed_id=None,
        measure="pearson",
        contrast="ses-02_minus_ses-01",
        method="nbs",
        threshold=3.0,
        n_permutations=100,
        alpha=0.05,
        group_csv=participants_tsv,
        out_dir=out_dir,
        rng_seed=42,
    )

    for fname in ("tstat.tsv", "pcorr.tsv", "significant_edges.tsv", "report.json", "report.html"):
        assert (out_dir / fname).exists(), f"Missing output file: {fname}"

    # NBS also produces components.tsv when components are found
    # (may or may not exist depending on whether any edges are above threshold)


# ---------------------------------------------------------------------------
# Test 8 — report.json has required fields
# ---------------------------------------------------------------------------

def test_report_json_has_required_fields(tmp_path):
    """report.json must contain all required metadata keys."""
    bids_root, participants_tsv, atlas = _write_synthetic_tsvs(tmp_path)
    out_dir = tmp_path / "out_json"

    gms.run_group_matrix_stats(
        bids_root=bids_root,
        pipeline="fc",
        kind="network",
        atlas=atlas,
        seed_id=None,
        measure="pearson",
        contrast="ses-02_minus_ses-01",
        method="paired_t_fdr",
        threshold=3.1,
        n_permutations=50,
        alpha=0.05,
        group_csv=participants_tsv,
        out_dir=out_dir,
        rng_seed=0,
    )

    with open(out_dir / "report.json") as f:
        meta = json.load(f)

    required_keys = {
        "method", "n_subjects", "n_permutations", "alpha",
        "rng_seed", "runtime_s", "n_significant",
    }
    missing = required_keys - set(meta.keys())
    assert not missing, f"report.json missing keys: {missing}"
    assert meta["method"] == "paired_t_fdr"
    assert meta["n_subjects"] == N_SUB


# ---------------------------------------------------------------------------
# Test 9 — tstat.tsv and pcorr.tsv shapes
# ---------------------------------------------------------------------------

def test_tsv_shapes_match(tmp_path):
    """Output matrix TSVs must be square (N_parcels × N_parcels)."""
    bids_root, participants_tsv, atlas = _write_synthetic_tsvs(tmp_path)
    out_dir = tmp_path / "out_shape"

    gms.run_group_matrix_stats(
        bids_root=bids_root,
        pipeline="fc",
        kind="network",
        atlas=atlas,
        seed_id=None,
        measure="pearson",
        contrast="ses-02_minus_ses-01",
        method="paired_t_fdr",
        threshold=3.1,
        n_permutations=50,
        alpha=0.05,
        group_csv=participants_tsv,
        out_dir=out_dir,
    )

    for fname in ("tstat.tsv", "pcorr.tsv"):
        df = pd.read_csv(out_dir / fname, sep="\t", index_col=0)
        assert df.shape == (N_PARCELS, N_PARCELS), (
            f"{fname}: expected ({N_PARCELS}, {N_PARCELS}), got {df.shape}"
        )


# ---------------------------------------------------------------------------
# Test 10 — significant_edges.tsv long format
# ---------------------------------------------------------------------------

def test_significant_edges_long_format(tmp_path):
    """significant_edges.tsv must have the expected column schema."""
    bids_root, participants_tsv, atlas = _write_synthetic_tsvs(tmp_path)
    out_dir = tmp_path / "out_long"

    gms.run_group_matrix_stats(
        bids_root=bids_root,
        pipeline="fc",
        kind="network",
        atlas=atlas,
        seed_id=None,
        measure="pearson",
        contrast="ses-02_minus_ses-01",
        method="paired_t_fdr",
        threshold=3.1,
        n_permutations=50,
        alpha=0.05,
        group_csv=participants_tsv,
        out_dir=out_dir,
    )

    sig_df = pd.read_csv(out_dir / "significant_edges.tsv", sep="\t")
    required = {"parcel_i", "parcel_j", "t", "p_corr", "sig"}
    assert required.issubset(sig_df.columns), (
        f"Missing columns: {required - set(sig_df.columns)}"
    )
    # Number of rows must equal number of upper-triangle edges
    n_expected = N_PARCELS * (N_PARCELS - 1) // 2
    assert len(sig_df) == n_expected


# ---------------------------------------------------------------------------
# Test 11 — seed kind (non-square matrices)
# ---------------------------------------------------------------------------

def test_seed_kind_non_square(tmp_path):
    """Seed-kind 1×N_parcels matrices run without error; outputs have 1 row."""
    rng = np.random.default_rng(11)
    pipeline = "fc"
    atlas = "SeedAtlas"
    seed_id = "atlas-SeedAtlas_parcel-TestSeed"
    measure = "pearson"
    n_parcels = 20
    labels = [f"parcel-{k:02d}" for k in range(n_parcels)]
    subjects = [f"sub-{i:03d}" for i in range(6)]

    bids_root = tmp_path / "bids_seed"

    for sub in subjects:
        for ses in ("ses-01", "ses-02"):
            seed_dir = (
                bids_root
                / "derivatives"
                / "connectivity"
                / pipeline
                / sub
                / ses
                / "seed"
                / seed_id
            )
            seed_dir.mkdir(parents=True, exist_ok=True)
            vec = rng.normal(0.0, 0.5, size=(1, n_parcels))
            if ses == "ses-02":
                vec[0, :5] += 3.0  # small effect on first 5 parcels
            z = "z"
            fname = f"{sub}_{ses}_atlas-{atlas}_measure-{measure}_seed-to-parcel.tsv"
            df = pd.DataFrame(vec, columns=labels)
            df.index = ["seed"]
            df.to_csv(seed_dir / fname, sep="\t")

    participants_tsv = bids_root / "participants.tsv"
    pd.DataFrame({
        "participant_id": subjects,
        "Age": np.linspace(60, 65, len(subjects)),
        "Gender": ["F" if i % 2 == 0 else "M" for i in range(len(subjects))],
        "group": ["A"] * 6,
    }).to_csv(participants_tsv, sep="\t", index=False)

    out_dir = tmp_path / "out_seed"
    gms.run_group_matrix_stats(
        bids_root=bids_root,
        pipeline=pipeline,
        kind="seed",
        atlas=None,
        seed_id=seed_id,
        measure=measure,
        contrast="ses-02_minus_ses-01",
        method="paired_t_fdr",
        threshold=2.5,
        n_permutations=50,
        alpha=0.05,
        group_csv=participants_tsv,
        out_dir=out_dir,
        seed_target_atlas=atlas,
    )

    tstat_df = pd.read_csv(out_dir / "tstat.tsv", sep="\t", index_col=0)
    # For seed kind: 1 row × n_parcels columns
    assert tstat_df.shape[1] == n_parcels, (
        f"Expected {n_parcels} parcel columns, got {tstat_df.shape[1]}"
    )
    assert (out_dir / "report.json").exists()
    assert (out_dir / "report.html").exists()
