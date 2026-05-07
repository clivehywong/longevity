"""
connectivity_measures.py — Parcel-level functional connectivity measures.

All functions accept a timeseries array of shape (n_timepoints, n_parcels) and
return a symmetric (n_parcels, n_parcels) float64 matrix.

Default sample rate: 1 / 0.8 Hz = 1.25 Hz (TR = 0.8 s, study convention).
"""

from __future__ import annotations

import numpy as np
from scipy import signal
from scipy.stats import spearmanr
from sklearn.covariance import LedoitWolf

_DEFAULT_FS = 1.0 / 0.8  # TR = 0.8 s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bandpass(ts: np.ndarray, fs: float, fmin: float, fmax: float) -> np.ndarray:
    """Zero-phase Butterworth bandpass filter (4th order)."""
    nyq = fs / 2.0
    lo, hi = fmin / nyq, fmax / nyq
    # Clamp to valid range
    lo = max(lo, 1e-6)
    hi = min(hi, 1.0 - 1e-6)
    b, a = signal.butter(4, [lo, hi], btype="bandpass")
    return signal.filtfilt(b, a, ts, axis=0)


def _resolve_fs(fs: float | None) -> float:
    return float(fs) if fs is not None else _DEFAULT_FS


# ---------------------------------------------------------------------------
# 1. Pearson correlation
# ---------------------------------------------------------------------------

def pearson(ts: np.ndarray) -> np.ndarray:
    """
    Pearson product-moment correlation between all parcel pairs.

    Parameters
    ----------
    ts : ndarray, shape (n_timepoints, n_parcels)

    Returns
    -------
    R : ndarray, shape (n_parcels, n_parcels), float64
        Symmetric matrix with diagonal == 1.

    Formula
    -------
    r_ij = cov(i,j) / (std_i * std_j)
    """
    ts = np.asarray(ts, dtype=np.float64)
    # np.corrcoef returns (n_parcels, n_parcels) when rowvar=False is not set
    # by default it treats rows as variables; we transpose
    R = np.corrcoef(ts.T)
    np.fill_diagonal(R, 1.0)
    return R.astype(np.float64)


# ---------------------------------------------------------------------------
# 2. Spearman rank correlation
# ---------------------------------------------------------------------------

def spearman(ts: np.ndarray) -> np.ndarray:
    """
    Spearman rank correlation between all parcel pairs.

    Implemented as Pearson on rank-transformed signals, matching
    scipy.stats.spearmanr.

    Parameters
    ----------
    ts : ndarray, shape (n_timepoints, n_parcels)

    Returns
    -------
    R : ndarray, shape (n_parcels, n_parcels), float64
    """
    ts = np.asarray(ts, dtype=np.float64)
    from scipy.stats import rankdata
    ranked = np.apply_along_axis(rankdata, 0, ts)
    R = np.corrcoef(ranked.T)
    np.fill_diagonal(R, 1.0)
    return R.astype(np.float64)


# ---------------------------------------------------------------------------
# 3. Partial correlation
# ---------------------------------------------------------------------------

def partial_correlation(ts: np.ndarray, regularization: float = 1e-3) -> np.ndarray:
    """
    Partial correlation via precision matrix (inverse covariance).

    Uses Ledoit-Wolf shrinkage estimator for regularized precision; falls back
    to ridge regularization if LedoitWolf fails.

    Parameters
    ----------
    ts : ndarray, shape (n_timepoints, n_parcels)
    regularization : float
        Ridge penalty added to covariance diagonal (fallback only).

    Returns
    -------
    P : ndarray, shape (n_parcels, n_parcels), float64
        Symmetric, diagonal == 1.

    Formula
    -------
    P_ij = -Theta_ij / sqrt(Theta_ii * Theta_jj)
    where Theta = precision matrix (inverse covariance).
    Reference: Marrelec et al. (2006) NeuroImage 30:827-834.
    """
    ts = np.asarray(ts, dtype=np.float64)
    try:
        lw = LedoitWolf().fit(ts)
        precision = lw.precision_
    except Exception:
        C = np.cov(ts.T)
        C += regularization * np.eye(C.shape[0])
        precision = np.linalg.inv(C)

    d = np.sqrt(np.diag(precision))
    P = -precision / np.outer(d, d)
    np.fill_diagonal(P, 1.0)
    # Symmetrize to correct any floating-point asymmetry
    P = (P + P.T) / 2.0
    return P.astype(np.float64)


# ---------------------------------------------------------------------------
# 4. Phase-locking value (PLV)
# ---------------------------------------------------------------------------

def plv(
    ts: np.ndarray,
    fs: float | None = None,
    fmin: float = 0.01,
    fmax: float = 0.1,
) -> np.ndarray:
    """
    Phase-locking value (PLV) between all parcel pairs.

    Computes instantaneous phase via Hilbert transform on band-passed signal,
    then PLV = |mean(exp(i * delta_phi))|.

    Parameters
    ----------
    ts   : ndarray, shape (n_timepoints, n_parcels)
    fs   : float, sample rate in Hz (default 1/0.8 Hz)
    fmin : float, lower band edge in Hz
    fmax : float, upper band edge in Hz

    Returns
    -------
    PLV : ndarray, shape (n_parcels, n_parcels), float64
        Symmetric, diagonal == 1, values in [0, 1].

    Reference
    ---------
    Lachaux et al. (1999) Human Brain Mapping 8:194-208.
    """
    fs = _resolve_fs(fs)
    ts = np.asarray(ts, dtype=np.float64)
    filtered = _bandpass(ts, fs, fmin, fmax)
    analytic = signal.hilbert(filtered, axis=0)
    phase = np.angle(analytic)  # (T, P)

    # Vectorized: phase diff for all pairs at once
    # exp(i * (phase_i - phase_j)) for all i,j
    exp_phase = np.exp(1j * phase)          # (T, P)
    # PLV_ij = |mean_t( exp(i*phi_i) * conj(exp(i*phi_j)) )|
    mean_cross = exp_phase.T @ np.conj(exp_phase) / phase.shape[0]  # (P, P)
    PLV = np.abs(mean_cross)
    np.fill_diagonal(PLV, 1.0)
    PLV = (PLV + PLV.T) / 2.0
    return PLV.astype(np.float64)


# ---------------------------------------------------------------------------
# 5. Weighted phase-lag index (wPLI)
# ---------------------------------------------------------------------------

def wpli(
    ts: np.ndarray,
    fs: float | None = None,
    fmin: float = 0.01,
    fmax: float = 0.1,
) -> np.ndarray:
    """
    Weighted Phase-Lag Index (wPLI) between all parcel pairs.

    wPLI = |E[|Im(C_xy)| * sign(Im(C_xy))]| / E[|Im(C_xy)|]
         = |E[Im(C_xy)]| / E[|Im(C_xy)|]

    where C_xy = x * conj(y) is the cross-spectrum sample at each time point.

    Parameters
    ----------
    ts   : ndarray, shape (n_timepoints, n_parcels)
    fs   : float, sample rate in Hz (default 1/0.8 Hz)
    fmin : float, lower band edge in Hz
    fmax : float, upper band edge in Hz

    Returns
    -------
    W : ndarray, shape (n_parcels, n_parcels), float64
        Symmetric, diagonal == 1, values in [0, 1].

    Reference
    ---------
    Vinck et al. (2011) NeuroImage 55:1548-1565.
    """
    fs = _resolve_fs(fs)
    ts = np.asarray(ts, dtype=np.float64)
    filtered = _bandpass(ts, fs, fmin, fmax)
    analytic = signal.hilbert(filtered, axis=0)  # (T, P)

    # Cross-spectrum: C_ij(t) = a_i(t) * conj(a_j(t))
    # Imag part: (T, P, P) — build without explicit Python loop
    im = np.einsum("ti,tj->tij", analytic.real, analytic.imag) - \
         np.einsum("ti,tj->tij", analytic.imag, analytic.real)
    # im[t,i,j] = Im(a_i * conj(a_j)) = Re(a_i)*Im(a_j) - Im(a_i)*Re(a_j)  (wait, sign)
    # Actually Im(a_i * conj(a_j)) = Im(a_i)*Re(a_j) - Re(a_i)*Im(a_j)  ... let me redo:
    # conj(a_j) = re_j - i*im_j
    # a_i * conj(a_j) = (re_i + i*im_i)(re_j - i*im_j)
    #                  = re_i*re_j + im_i*im_j + i*(im_i*re_j - re_i*im_j)
    # So Im(a_i * conj(a_j)) = im_i*re_j - re_i*im_j
    re = analytic.real  # (T, P)
    im_a = analytic.imag  # (T, P)
    cross_imag = np.einsum("ti,tj->tij", im_a, re) - np.einsum("ti,tj->tij", re, im_a)
    # cross_imag[t,i,j] = im_i * re_j - re_i * im_j

    num = np.abs(np.mean(cross_imag, axis=0))
    den = np.mean(np.abs(cross_imag), axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        W = np.where(den > 0, num / den, 0.0)

    np.fill_diagonal(W, 1.0)
    W = (W + W.T) / 2.0
    return W.astype(np.float64)


# ---------------------------------------------------------------------------
# 6. Magnitude-squared coherence
# ---------------------------------------------------------------------------

def coherence(
    ts: np.ndarray,
    fs: float | None = None,
    fmin: float = 0.01,
    fmax: float = 0.1,
    nperseg: int | None = None,
) -> np.ndarray:
    """
    Magnitude-squared coherence averaged over a frequency band.

    Uses Welch's method (scipy.signal.csd / welch) to estimate cross-spectral
    and auto-spectral densities, then averages coherence over [fmin, fmax].

    Parameters
    ----------
    ts      : ndarray, shape (n_timepoints, n_parcels)
    fs      : float, sample rate in Hz (default 1/0.8 Hz)
    fmin    : float, lower band edge in Hz
    fmax    : float, upper band edge in Hz
    nperseg : int, segment length for Welch (default: T // 4, min 16)

    Returns
    -------
    Coh : ndarray, shape (n_parcels, n_parcels), float64
        Symmetric, diagonal == 1, values in [0, 1].

    Reference
    ---------
    Carter et al. (1973) IEEE Trans. Audio Electroacoust. 21:337-344.
    """
    fs = _resolve_fs(fs)
    ts = np.asarray(ts, dtype=np.float64)
    T, P = ts.shape
    if nperseg is None:
        nperseg = max(16, T // 4)

    # Compute Welch auto-spectra and cross-spectra in O(N^2) pairs
    # For efficiency, compute all auto-spectra first then cross-spectra pairwise
    freqs, _ = signal.welch(ts[:, 0], fs=fs, nperseg=nperseg)
    band_mask = (freqs >= fmin) & (freqs <= fmax)
    if not np.any(band_mask):
        # Fallback: use closest frequency bin
        idx = np.argmin(np.abs(freqs - (fmin + fmax) / 2))
        band_mask[idx] = True

    # Auto-spectra
    Pxx = np.zeros((len(freqs), P))
    for i in range(P):
        _, Pxx[:, i] = signal.welch(ts[:, i], fs=fs, nperseg=nperseg)

    # Cross-spectra and coherence
    Coh = np.zeros((P, P), dtype=np.float64)
    for i in range(P):
        for j in range(i, P):
            if i == j:
                Coh[i, i] = 1.0
                continue
            _, Pxy = signal.csd(ts[:, i], ts[:, j], fs=fs, nperseg=nperseg)
            coh_ij = np.abs(Pxy[band_mask]) ** 2 / (
                Pxx[band_mask, i] * Pxx[band_mask, j] + 1e-30
            )
            val = float(np.mean(coh_ij))
            Coh[i, j] = val
            Coh[j, i] = val

    return Coh.astype(np.float64)


# ---------------------------------------------------------------------------
# 7. Amplitude envelope correlation (AEC)
# ---------------------------------------------------------------------------

def amplitude_envelope_correlation(
    ts: np.ndarray,
    fs: float | None = None,
    fmin: float = 0.01,
    fmax: float = 0.1,
    orthogonalize: bool = True,
) -> np.ndarray:
    """
    Amplitude Envelope Correlation (AEC) with optional leakage correction.

    Computes the Pearson correlation between the amplitude envelopes of the
    analytic (Hilbert) signal after band-passing.

    If orthogonalize=True, uses the symmetric pairwise orthogonalization
    (Hipp 2012): for each pair (i, j) remove the component of signal i that
    is in phase with j, and vice versa, then average the two resulting AECs.

    Parameters
    ----------
    ts           : ndarray, shape (n_timepoints, n_parcels)
    fs           : float, sample rate in Hz (default 1/0.8 Hz)
    fmin         : float, lower band edge in Hz
    fmax         : float, upper band edge in Hz
    orthogonalize: bool, if True apply leakage correction (Hipp et al. 2012)

    Returns
    -------
    AEC : ndarray, shape (n_parcels, n_parcels), float64
        Symmetric, diagonal == 1.

    Reference
    ---------
    Hipp et al. (2012) Nature Neuroscience 15:884-891.
    """
    fs = _resolve_fs(fs)
    ts = np.asarray(ts, dtype=np.float64)
    filtered = _bandpass(ts, fs, fmin, fmax)
    analytic = signal.hilbert(filtered, axis=0)  # (T, P)

    if not orthogonalize:
        env = np.abs(analytic)  # (T, P)
        AEC = np.corrcoef(env.T)
        np.fill_diagonal(AEC, 1.0)
        return AEC.astype(np.float64)

    # Pairwise symmetric orthogonalization (Hipp 2012)
    P = analytic.shape[1]
    AEC = np.zeros((P, P), dtype=np.float64)

    for i in range(P):
        ai = analytic[:, i]
        for j in range(i + 1, P):
            aj = analytic[:, j]

            # Orthogonalize i w.r.t. j: remove projection of i onto j
            ai_orth_j = ai - (np.real(np.vdot(ai, aj)) / np.real(np.vdot(aj, aj))) * aj
            env_i_orth = np.abs(ai_orth_j)
            env_j = np.abs(aj)
            r1 = float(np.corrcoef(env_i_orth, env_j)[0, 1])

            # Orthogonalize j w.r.t. i
            aj_orth_i = aj - (np.real(np.vdot(aj, ai)) / np.real(np.vdot(ai, ai))) * ai
            env_j_orth = np.abs(aj_orth_i)
            env_i = np.abs(ai)
            r2 = float(np.corrcoef(env_i, env_j_orth)[0, 1])

            val = (r1 + r2) / 2.0
            AEC[i, j] = val
            AEC[j, i] = val

    np.fill_diagonal(AEC, 1.0)
    return AEC.astype(np.float64)


# ---------------------------------------------------------------------------
# 8. Mutual information (MI)
# ---------------------------------------------------------------------------

def mutual_information(ts: np.ndarray, n_bins: int = 16) -> np.ndarray:
    """
    Pairwise mutual information via the histogram (binning) method.

    MI(X;Y) = H(X) + H(Y) - H(X,Y)

    Diagonal is set to the individual entropy H(X) of each parcel signal
    (not 1.0), consistent with MI being a generalized measure of dependency.
    This makes the diagonal interpretable: MI(X;X) = H(X).

    Parameters
    ----------
    ts     : ndarray, shape (n_timepoints, n_parcels)
    n_bins : int, number of histogram bins per dimension (default 16)

    Returns
    -------
    MI : ndarray, shape (n_parcels, n_parcels), float64
        Symmetric. Diagonal = H(parcel_i) in nats.
        Off-diagonal = MI in nats.

    Formula
    -------
    MI(X;Y) = sum_{x,y} p(x,y) log(p(x,y) / (p(x)*p(y)))
    """
    ts = np.asarray(ts, dtype=np.float64)
    T, P = ts.shape
    MI = np.zeros((P, P), dtype=np.float64)

    # Precompute marginal entropies
    H = np.zeros(P, dtype=np.float64)
    for i in range(P):
        hist, _ = np.histogram(ts[:, i], bins=n_bins)
        p = hist / hist.sum()
        p = p[p > 0]
        H[i] = -np.sum(p * np.log(p))

    for i in range(P):
        MI[i, i] = H[i]
        for j in range(i + 1, P):
            hist2d, _, _ = np.histogram2d(ts[:, i], ts[:, j], bins=n_bins)
            p2 = hist2d / hist2d.sum()
            # Joint entropy
            pf = p2.ravel()
            pf = pf[pf > 0]
            h_joint = -np.sum(pf * np.log(pf))
            mi_val = H[i] + H[j] - h_joint
            MI[i, j] = mi_val
            MI[j, i] = mi_val

    return MI.astype(np.float64)


# ---------------------------------------------------------------------------
# Registry and convenience
# ---------------------------------------------------------------------------

MEASURES: dict[str, callable] = {
    "pearson": pearson,
    "spearman": spearman,
    "partial_correlation": partial_correlation,
    "plv": plv,
    "wpli": wpli,
    "coherence": coherence,
    "amplitude_envelope_correlation": amplitude_envelope_correlation,
    "mutual_information": mutual_information,
}

CORRELATION_TYPE: set[str] = {"pearson", "spearman", "partial_correlation"}

_FS_MEASURES = {"plv", "wpli", "coherence", "amplitude_envelope_correlation"}


def compute(measure: str, ts: np.ndarray, fs: float | None = None, **kwargs) -> np.ndarray:
    """
    Compute a named connectivity measure.

    Parameters
    ----------
    measure : str
        One of the keys in MEASURES.
    ts      : ndarray, shape (n_timepoints, n_parcels)
    fs      : float or None
        Sample rate in Hz. Passed to measures that require it.
        Defaults to 1/0.8 Hz if not supplied.
    **kwargs
        Additional keyword arguments forwarded to the measure function.

    Returns
    -------
    ndarray, shape (n_parcels, n_parcels), float64
    """
    if measure not in MEASURES:
        raise ValueError(f"Unknown measure '{measure}'. Choose from: {sorted(MEASURES)}")
    fn = MEASURES[measure]
    if measure in _FS_MEASURES:
        return fn(ts, fs=fs, **kwargs)
    return fn(ts, **kwargs)


def fisher_z(r: np.ndarray) -> np.ndarray:
    """
    Fisher Z-transformation: z = arctanh(r).

    Transforms Pearson/Spearman/partial-correlation coefficients to an
    approximately normal distribution. Infinities are clipped to the value
    corresponding to |r| = 1 - 1e-7 (approximately ±8.06).

    Parameters
    ----------
    r : float or ndarray
        Correlation coefficient(s) in [-1, 1].

    Returns
    -------
    z : float or ndarray, same shape as r, float64

    Note
    ----
    fisher_z(0.0) == 0.0
    fisher_z(0.5) ≈ 0.5493
    """
    r = np.asarray(r, dtype=np.float64)
    clip_val = 1.0 - 1e-7
    r_clipped = np.clip(r, -clip_val, clip_val)
    return np.arctanh(r_clipped)
