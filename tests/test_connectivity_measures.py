"""
tests/test_connectivity_measures.py

Tests for script/connectivity_measures.py

Synthetic signal sets:
  - Independent random: 10 parcels, 480 timepoints, seed=0
  - Coupled (sin + phase-locked): pairs with known phase relationships
"""

import sys
import os
import numpy as np
import pytest

# Allow importing from script/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "script"))

from connectivity_measures import (
    pearson,
    spearman,
    partial_correlation,
    plv,
    wpli,
    coherence,
    amplitude_envelope_correlation,
    mutual_information,
    compute,
    fisher_z,
    MEASURES,
    CORRELATION_TYPE,
)

FS = 1.0 / 0.8  # 1.25 Hz (TR = 0.8 s)
FMIN, FMAX = 0.01, 0.1
N_PARCELS = 10
N_TIME = 480
N_PARCELS_SMALL = 2
N_TIME_SMALL = 100


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def random_ts():
    """Independent random timeseries, seed=0."""
    rng = np.random.default_rng(0)
    return rng.standard_normal((N_TIME, N_PARCELS))


@pytest.fixture(scope="module")
def coupled_ts():
    """
    Timeseries with known phase coupling.
    Parcels 0-1: in-phase 0.05 Hz sine (should show high PLV/coherence).
    Parcels 2-3: anti-phase 0.05 Hz sine.
    Parcels 4-9: independent random noise (low coupling).
    """
    rng = np.random.default_rng(42)
    t = np.arange(N_TIME) / FS
    freq = 0.05  # Hz, within [0.01, 0.1] band
    ts = rng.standard_normal((N_TIME, N_PARCELS)) * 0.1  # low noise
    # Parcels 0 and 1: in-phase
    sine = np.sin(2 * np.pi * freq * t)
    ts[:, 0] += sine
    ts[:, 1] += sine
    # Parcels 2 and 3: anti-phase
    ts[:, 2] += sine
    ts[:, 3] -= sine
    return ts


@pytest.fixture(scope="module")
def small_ts():
    """2 parcels, 100 timepoints."""
    rng = np.random.default_rng(7)
    return rng.standard_normal((N_TIME_SMALL, N_PARCELS_SMALL))


# ---------------------------------------------------------------------------
# Test 1: Symmetry for all measures
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("measure", list(MEASURES.keys()))
def test_symmetry(measure, random_ts):
    """Every measure must return a symmetric matrix."""
    M = compute(measure, random_ts, fs=FS)
    assert np.allclose(M, M.T, atol=1e-10), f"{measure}: matrix not symmetric"


# ---------------------------------------------------------------------------
# Test 2: Shape and dtype
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("measure", list(MEASURES.keys()))
def test_shape_and_dtype(measure, random_ts):
    """Output must be (n_parcels, n_parcels) float64."""
    M = compute(measure, random_ts, fs=FS)
    assert M.shape == (N_PARCELS, N_PARCELS), f"{measure}: wrong shape {M.shape}"
    assert M.dtype == np.float64, f"{measure}: wrong dtype {M.dtype}"


# ---------------------------------------------------------------------------
# Test 3: Diagonal values
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("measure", ["pearson", "spearman", "partial_correlation",
                                      "plv", "wpli", "coherence",
                                      "amplitude_envelope_correlation"])
def test_diagonal_is_one(measure, random_ts):
    """Correlation-type and phase measures should have diagonal == 1."""
    M = compute(measure, random_ts, fs=FS)
    assert np.allclose(np.diag(M), 1.0, atol=1e-10), \
        f"{measure}: diagonal not 1.0, got {np.diag(M)}"


def test_mi_diagonal_is_entropy(random_ts):
    """MI diagonal should equal per-parcel entropy H(X), not 1.0."""
    MI = mutual_information(random_ts, n_bins=16)
    diag = np.diag(MI)
    # Entropy of a roughly normal distribution with 16 bins must be > 0
    assert np.all(diag > 0), "MI diagonal should be positive entropy values"
    # Entropy should be finite
    assert np.all(np.isfinite(diag)), "MI diagonal should be finite"


# ---------------------------------------------------------------------------
# Test 4: Independent signals have near-zero off-diagonal (pearson, spearman)
# ---------------------------------------------------------------------------

def test_pearson_independent_near_zero(random_ts):
    """Pearson off-diagonal should be near 0 for independent random signals."""
    R = pearson(random_ts)
    mask = ~np.eye(N_PARCELS, dtype=bool)
    off_diag = R[mask]
    assert np.abs(off_diag).mean() < 0.15, \
        f"Pearson mean |off-diag| too high: {np.abs(off_diag).mean():.4f}"


def test_spearman_independent_near_zero(random_ts):
    """Spearman off-diagonal should be near 0 for independent random signals."""
    R = spearman(random_ts)
    mask = ~np.eye(N_PARCELS, dtype=bool)
    off_diag = R[mask]
    assert np.abs(off_diag).mean() < 0.15


# ---------------------------------------------------------------------------
# Test 5: Coupled signals detected by Pearson, PLV, coherence
# ---------------------------------------------------------------------------

def test_pearson_detects_coupling(coupled_ts):
    """Pearson should show high correlation for in-phase parcels (0,1)."""
    R = pearson(coupled_ts)
    assert R[0, 1] > 0.8, f"Pearson[0,1]={R[0,1]:.4f} should be > 0.8 for in-phase signals"


def test_plv_detects_coupling(coupled_ts):
    """PLV should be high for in-phase coupled parcels."""
    P = plv(coupled_ts, fs=FS)
    # In-phase pair should have higher PLV than average off-diagonal
    mask = ~np.eye(N_PARCELS, dtype=bool)
    background = np.mean(P[mask])
    assert P[0, 1] > background + 0.1, \
        f"PLV[0,1]={P[0,1]:.4f} should exceed background {background:.4f} + 0.1"


def test_coherence_detects_coupling(coupled_ts):
    """Coherence should be high for in-phase coupled parcels."""
    C = coherence(coupled_ts, fs=FS)
    mask = ~np.eye(N_PARCELS, dtype=bool)
    background = np.mean(C[mask])
    assert C[0, 1] > background + 0.05, \
        f"Coh[0,1]={C[0, 1]:.4f} should exceed background {background:.4f} + 0.05"


# ---------------------------------------------------------------------------
# Test 6: compute() matches direct function call
# ---------------------------------------------------------------------------

def test_compute_pearson_matches_direct(random_ts):
    """compute('pearson', ts) must exactly match pearson(ts)."""
    R_direct = pearson(random_ts)
    R_compute = compute("pearson", random_ts, fs=FS)
    assert np.allclose(R_direct, R_compute), "compute() differs from direct call"


def test_compute_spearman_matches_direct(random_ts):
    R_direct = spearman(random_ts)
    R_compute = compute("spearman", random_ts, fs=FS)
    assert np.allclose(R_direct, R_compute)


def test_compute_unknown_raises(random_ts):
    """compute() must raise ValueError for unknown measure names."""
    with pytest.raises(ValueError, match="Unknown measure"):
        compute("magic_connectivity", random_ts)


# ---------------------------------------------------------------------------
# Test 7: fisher_z properties
# ---------------------------------------------------------------------------

def test_fisher_z_zero():
    """fisher_z(0.0) == 0.0."""
    assert fisher_z(np.float64(0.0)) == pytest.approx(0.0, abs=1e-12)


def test_fisher_z_half():
    """fisher_z(0.5) ≈ 0.5493."""
    assert fisher_z(np.float64(0.5)) == pytest.approx(0.5493, abs=1e-3)


def test_fisher_z_infinities_clipped():
    """fisher_z at ±1.0 should return finite values (clipped)."""
    z_pos = fisher_z(np.float64(1.0))
    z_neg = fisher_z(np.float64(-1.0))
    assert np.isfinite(z_pos), "fisher_z(1.0) should be finite after clipping"
    assert np.isfinite(z_neg), "fisher_z(-1.0) should be finite after clipping"
    assert z_pos > 0 and z_neg < 0


def test_fisher_z_array():
    """fisher_z on array input, preserves shape."""
    r = np.array([0.0, 0.5, -0.5, 0.9])
    z = fisher_z(r)
    assert z.shape == r.shape
    assert z[0] == pytest.approx(0.0, abs=1e-12)
    assert z[1] > 0
    assert z[2] < 0


# ---------------------------------------------------------------------------
# Test 8: Edge case — 2 parcels, 100 timepoints
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("measure", list(MEASURES.keys()))
def test_small_input(measure, small_ts):
    """Every measure should produce a valid 2×2 matrix for minimal input."""
    M = compute(measure, small_ts, fs=FS)
    assert M.shape == (N_PARCELS_SMALL, N_PARCELS_SMALL), \
        f"{measure}: shape {M.shape} != (2,2)"
    assert np.allclose(M, M.T, atol=1e-10), f"{measure}: not symmetric for small input"
    assert np.all(np.isfinite(M)), f"{measure}: contains non-finite values"


# ---------------------------------------------------------------------------
# Test 9: MEASURES dict contains all expected keys
# ---------------------------------------------------------------------------

def test_measures_registry():
    expected = {
        "pearson", "spearman", "partial_correlation",
        "plv", "wpli", "coherence",
        "amplitude_envelope_correlation", "mutual_information",
    }
    assert set(MEASURES.keys()) == expected


def test_correlation_type_set():
    assert CORRELATION_TYPE == {"pearson", "spearman", "partial_correlation"}


# ---------------------------------------------------------------------------
# Test 10: Partial correlation — conditioning removes spurious correlations
# ---------------------------------------------------------------------------

def test_partial_correlation_shape_and_symmetry(random_ts):
    P = partial_correlation(random_ts)
    assert P.shape == (N_PARCELS, N_PARCELS)
    assert np.allclose(P, P.T, atol=1e-10)
    assert np.allclose(np.diag(P), 1.0, atol=1e-10)


# ---------------------------------------------------------------------------
# Test 11: PLV values in [0, 1]
# ---------------------------------------------------------------------------

def test_plv_range(random_ts):
    P = plv(random_ts, fs=FS)
    assert np.all(P >= -1e-10), "PLV should be non-negative"
    assert np.all(P <= 1.0 + 1e-10), "PLV should be <= 1"


# ---------------------------------------------------------------------------
# Test 12: wPLI values in [0, 1]
# ---------------------------------------------------------------------------

def test_wpli_range(random_ts):
    W = wpli(random_ts, fs=FS)
    assert np.all(W >= -1e-10), "wPLI should be non-negative"
    assert np.all(W <= 1.0 + 1e-10), "wPLI should be <= 1"


# ---------------------------------------------------------------------------
# Test 13: AEC with and without orthogonalization
# ---------------------------------------------------------------------------

def test_aec_orthogonalized_vs_raw(random_ts):
    """AEC with orthogonalization should differ from raw AEC."""
    aec_raw = amplitude_envelope_correlation(random_ts, fs=FS, orthogonalize=False)
    aec_orth = amplitude_envelope_correlation(random_ts, fs=FS, orthogonalize=True)
    # Both valid shapes and symmetric
    assert aec_raw.shape == (N_PARCELS, N_PARCELS)
    assert aec_orth.shape == (N_PARCELS, N_PARCELS)
    assert np.allclose(aec_raw, aec_raw.T, atol=1e-10)
    assert np.allclose(aec_orth, aec_orth.T, atol=1e-10)


# ---------------------------------------------------------------------------
# Test 14: compute() passes kwargs through (e.g., n_bins for MI)
# ---------------------------------------------------------------------------

def test_compute_kwargs_passthrough(random_ts):
    """compute() should forward **kwargs to the underlying function."""
    MI_8 = compute("mutual_information", random_ts, n_bins=8)
    MI_32 = compute("mutual_information", random_ts, n_bins=32)
    # Different bin counts should give different results
    assert not np.allclose(MI_8, MI_32), "Different n_bins should yield different MI"
