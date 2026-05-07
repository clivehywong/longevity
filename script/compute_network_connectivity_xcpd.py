"""
compute_network_connectivity_xcpd.py — Subject-level network/parcel connectivity
backend driven by XCP-D mean parcel timeseries.

For each (atlas, measure):
  1. Load mean timeseries TSV → ndarray (n_t, n_parcels) + column labels
  2. Compute connectivity matrix via connectivity_measures.compute()
  3. Apply Fisher-Z for CORRELATION_TYPE measures (file suffix ``_z``)
  4. Save as TSV with parcel labels in header and index column
  5. Save JSON meta per atlas

For Pearson, also loads XCP-D's own pearson_relmat and logs sanity-check stats.

Output layout::

    derivatives/connectivity/{pipeline}/sub-XX/ses-YY/network/atlas-{atlas}/
    ├── sub-XX_ses-YY_atlas-X_measure-pearson_relmat-z.tsv
    ├── sub-XX_ses-YY_atlas-X_measure-plv_relmat.tsv
    └── sub-XX_ses-YY_atlas-X_meta.json

Usage::

    python script/compute_network_connectivity_xcpd.py \\
        --bids-root /home/clivewong/proj/longevity \\
        --subject sub-033 --session ses-01 \\
        --pipeline fc \\
        --atlas 4S256Parcels --atlas 4S456Parcels \\
        --measures pearson,spearman,partial_correlation,plv,wpli,coherence,\\
amplitude_envelope_correlation,mutual_information \\
        --out-root derivatives/connectivity \\
        --tr 0.8 [--force]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Allow imports from script/ and neuconn_app/ regardless of CWD
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_SCRIPT_DIR))
sys.path.insert(0, str(_REPO_ROOT))

import connectivity_measures as cm
from neuconn_app.utils.xcpd_outputs import XcpdDiscovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("network_connectivity_xcpd")


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

def load_timeseries(tsv_path: Path) -> tuple[np.ndarray, list[str]]:
    """Load a mean-timeseries TSV produced by XCP-D.

    Returns
    -------
    ts : ndarray, shape (n_timepoints, n_parcels)
    labels : list[str], length n_parcels
    """
    df = pd.read_csv(tsv_path, sep="\t", header=0)
    labels = list(df.columns)
    ts = df.to_numpy(dtype=np.float64)
    return ts, labels


def load_relmat(tsv_path: Path) -> tuple[np.ndarray, list[str]]:
    """Load an XCP-D pearson relmat TSV (first column is 'Node' index).

    Returns
    -------
    mat : ndarray, shape (n_parcels, n_parcels)
    labels : list[str], length n_parcels (the row/column labels)
    """
    df = pd.read_csv(tsv_path, sep="\t", index_col=0)
    labels = list(df.index)
    mat = df.to_numpy(dtype=np.float64)
    return mat, labels


def save_relmat_tsv(out_path: Path, mat: np.ndarray, labels: list[str]) -> None:
    """Save a connectivity matrix as a labelled TSV (index + header)."""
    df = pd.DataFrame(mat, index=labels, columns=labels)
    df.index.name = "Node"
    df.to_csv(out_path, sep="\t", float_format="%.10f")


def _measure_suffix(measure: str, fisher_z_applied: bool) -> str:
    """Return filename token: ``relmat-z`` or ``relmat``."""
    return "relmat-z" if fisher_z_applied else "relmat"


def _out_filename(subject: str, session: str, atlas: str, measure: str, suffix: str) -> str:
    return f"{subject}_{session}_atlas-{atlas}_measure-{measure}_{suffix}.tsv"


# ---------------------------------------------------------------------------
# Per-atlas processing
# ---------------------------------------------------------------------------

def process_atlas(
    *,
    subject: str,
    session: str,
    pipeline: str,
    atlas: str,
    measures: list[str],
    ts_path: Path,
    relmat_path: Optional[Path],
    out_dir: Path,
    tr: float,
    force: bool,
) -> dict:
    """Compute all measures for one atlas and save outputs.

    Returns a meta dict (written later to JSON).
    """
    t0 = time.time()
    fs = 1.0 / tr

    ts, labels = load_timeseries(ts_path)
    n_timepoints, n_parcels = ts.shape
    log.info(
        "%s/%s atlas=%s: loaded timeseries (%d timepoints, %d parcels)",
        subject, session, atlas, n_timepoints, n_parcels,
    )

    # Load XCP-D reference Pearson relmat (may be None)
    xcpd_pearson: Optional[np.ndarray] = None
    if relmat_path is not None and relmat_path.exists():
        xcpd_pearson, _ = load_relmat(relmat_path)

    fisher_z_applied: list[str] = []
    sanity_check: dict = {}

    for measure in measures:
        fisher_applied = measure in cm.CORRELATION_TYPE
        suffix = _measure_suffix(measure, fisher_applied)
        fname = _out_filename(subject, session, atlas, measure, suffix)
        out_path = out_dir / fname

        if out_path.exists() and not force:
            log.info("  [skip] %s (already exists)", fname)
            continue

        log.info("  [compute] %s ...", measure)
        M = cm.compute(measure, ts, fs=fs)

        # Sanity check for Pearson before Fisher-Z
        if measure == "pearson" and xcpd_pearson is not None:
            diff = np.abs(M - xcpd_pearson)
            mean_diff = float(np.mean(diff))
            max_diff = float(np.max(diff))
            sanity_check["xcpd_pearson_mean_abs_diff"] = mean_diff
            sanity_check["xcpd_pearson_max_abs_diff"] = max_diff
            log.info(
                "  [sanity] Pearson vs XCP-D: mean_abs_diff=%.2e  max_abs_diff=%.2e",
                mean_diff, max_diff,
            )

        if fisher_applied:
            M = cm.fisher_z(M)
            fisher_z_applied.append(measure)

        save_relmat_tsv(out_path, M, labels)
        log.info("  [saved] %s", out_path.name)

    runtime = time.time() - t0

    meta = {
        "subject": subject,
        "session": session,
        "pipeline": pipeline,
        "atlas": atlas,
        "n_parcels": n_parcels,
        "n_timepoints": n_timepoints,
        "tr_seconds": tr,
        "measures": measures,
        "fisher_z_applied": fisher_z_applied,
        "sanity_check_vs_xcpd_pearson": sanity_check,
        "runtime_seconds": round(runtime, 3),
        "software": {
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": sys.version.split()[0],
        },
    }
    return meta


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(
    bids_root: Path,
    subject: str,
    session: str,
    pipeline: str,
    atlases: list[str],
    measures: list[str],
    out_root: Path,
    tr: float,
    force: bool,
) -> None:
    """Top-level driver: iterate over atlases and compute all measures."""
    discovery = XcpdDiscovery(bids_root, pipeline=pipeline)
    outputs = discovery.get(subject, session, pipeline)

    if not outputs.mean_timeseries:
        log.error(
            "No mean_timeseries found for %s/%s/%s under %s",
            subject, session, pipeline, bids_root,
        )
        sys.exit(1)

    # Validate requested atlases
    available = set(outputs.mean_timeseries.keys())
    missing = [a for a in atlases if a not in available]
    if missing:
        log.error(
            "Requested atlas(es) not available for %s/%s/%s: %s",
            subject, session, pipeline, missing,
        )
        log.error("Available atlases: %s", sorted(available))
        sys.exit(1)

    for atlas in atlases:
        out_dir = (
            out_root / pipeline / subject / session / "network" / f"atlas-{atlas}"
        )
        out_dir.mkdir(parents=True, exist_ok=True)

        meta_path = out_dir / f"{subject}_{session}_atlas-{atlas}_meta.json"
        if meta_path.exists() and not force and _all_outputs_exist(
            out_dir, subject, session, atlas, measures
        ):
            log.info(
                "atlas=%s: all outputs exist, skipping (use --force to recompute)",
                atlas,
            )
            continue

        meta = process_atlas(
            subject=subject,
            session=session,
            pipeline=pipeline,
            atlas=atlas,
            measures=measures,
            ts_path=outputs.mean_timeseries[atlas],
            relmat_path=outputs.pearson_relmat.get(atlas),
            out_dir=out_dir,
            tr=tr,
            force=force,
        )

        with meta_path.open("w") as fh:
            json.dump(meta, fh, indent=2)
        log.info("atlas=%s: meta saved → %s", atlas, meta_path.name)


def _all_outputs_exist(
    out_dir: Path,
    subject: str,
    session: str,
    atlas: str,
    measures: list[str],
) -> bool:
    """Return True if every expected output file is already present."""
    for measure in measures:
        fisher_applied = measure in cm.CORRELATION_TYPE
        suffix = _measure_suffix(measure, fisher_applied)
        fname = _out_filename(subject, session, atlas, measure, suffix)
        if not (out_dir / fname).exists():
            return False
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compute network/parcel connectivity from XCP-D mean timeseries.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--bids-root", required=True, type=Path,
                        help="BIDS project root (contains derivatives/preprocessing/xcpd/).")
    parser.add_argument("--subject", required=True,
                        help="Subject ID, e.g. sub-033.")
    parser.add_argument("--session", required=True,
                        help="Session ID, e.g. ses-01.")
    parser.add_argument("--pipeline", default="fc",
                        help="XCP-D pipeline name (fc, fc_gsr, ec).")
    parser.add_argument("--atlas", dest="atlases", action="append", required=True,
                        metavar="ATLAS",
                        help="Atlas name (repeatable). E.g. 4S256Parcels.")
    parser.add_argument(
        "--measures",
        default=",".join(sorted(cm.MEASURES.keys())),
        help="Comma-separated list of connectivity measures to compute.",
    )
    parser.add_argument("--out-root", type=Path, default=Path("derivatives/connectivity"),
                        help="Output root directory.")
    parser.add_argument("--tr", type=float, default=0.8,
                        help="Repetition time in seconds.")
    parser.add_argument("--force", action="store_true",
                        help="Recompute and overwrite existing outputs.")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)
    measures = [m.strip() for m in args.measures.split(",") if m.strip()]

    # Resolve out_root relative to bids_root if it is a relative path
    out_root = (
        args.out_root if args.out_root.is_absolute()
        else args.bids_root / args.out_root
    )

    run(
        bids_root=args.bids_root,
        subject=args.subject,
        session=args.session,
        pipeline=args.pipeline,
        atlases=args.atlases,
        measures=measures,
        out_root=out_root,
        tr=args.tr,
        force=args.force,
    )


if __name__ == "__main__":
    main()
