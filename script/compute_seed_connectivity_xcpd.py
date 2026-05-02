#!/usr/bin/env python3
"""
compute_seed_connectivity_xcpd.py — Subject-level seed-based connectivity.

Driven by XCP-D outputs (atlas mean timeseries TSVs + denoised BOLD volumes).

For each seed, computes:
  * Seed-to-parcel connectivity vectors (all XCP-D atlases × requested measures)
  * Seed-to-voxel Fisher-z map (Pearson only)

The script is idempotent: existing outputs are skipped unless --force is given.

Usage
-----
python script/compute_seed_connectivity_xcpd.py \\
    --bids-root /home/clivewong/proj/longevity \\
    --subject sub-033 --session ses-01 \\
    --pipeline fc \\
    --seed atlas-4S256Parcels:LH_Vis_1 \\
    --seed sphere:0,-52,26,r=6,name=PCC \\
    --seed nifti:/path/to/roi.nii.gz,name=DLPFC \\
    --measures pearson,spearman,partial_correlation,plv,wpli,coherence,amplitude_envelope_correlation,mutual_information \\
    --bold denoisedSmoothed \\
    --out-root derivatives/connectivity \\
    --tr 0.8

Output layout::

    derivatives/connectivity/{pipeline}/{subject}/{session}/seed/{seed_id}/
    ├── {sub}_{ses}_seed-{id}_atlas-4S256Parcels_measure-pearson_seed-to-parcel.tsv
    ├── ...   (one TSV per atlas × measure)
    ├── {sub}_{ses}_seed-{id}_seed-to-voxel_zmap.nii.gz
    └── {sub}_{ses}_seed-{id}_meta.json
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Optional

import nibabel as nib
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Path setup — allow importing sibling modules without an installed package
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "neuconn_app"))
sys.path.insert(0, str(_SCRIPT_DIR))

from utils.xcpd_outputs import XcpdDiscovery, XcpdOutputs  # noqa: E402
from utils.seed_catalog import Seed  # noqa: E402
from connectivity_measures import (  # noqa: E402
    compute,
    fisher_z,
    CORRELATION_TYPE,
    MEASURES,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
_LOG = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed spec parsing
# ---------------------------------------------------------------------------


def _parse_seed_spec(spec: str) -> Seed:
    """Parse a CLI seed specification string into a :class:`Seed` object.

    Supported formats:

    * ``atlas-<name>:<parcel_label>``
    * ``sphere:<x>,<y>,<z>[,r=<mm>][,name=<name>]``
    * ``nifti:<path>[,name=<name>]``
    """
    spec = spec.strip()

    if spec.startswith("atlas-"):
        m = re.match(r"^atlas-([^:]+):(.+)$", spec)
        if not m:
            raise ValueError(
                f"Invalid atlas seed spec: {spec!r}. Expected: atlas-<name>:<parcel>"
            )
        atlas = m.group(1)
        parcel_label = m.group(2)
        return Seed(
            id=f"atlas-{atlas}_parcel-{parcel_label}",
            name=f"{atlas}: {parcel_label}",
            source="xcpd_atlas_parcel",
            atlas=atlas,
            parcel_label=parcel_label,
        )

    if spec.startswith("sphere:"):
        rest = spec[len("sphere:"):]
        parts = [p.strip() for p in rest.split(",")]
        coords: list[float] = []
        radius_mm = 6.0
        name: Optional[str] = None
        for part in parts:
            if "=" in part:
                k, v = part.split("=", 1)
                k = k.strip()
                v = v.strip()
                if k == "r":
                    radius_mm = float(v)
                elif k == "name":
                    name = v
            else:
                coords.append(float(part))
        if len(coords) != 3:
            raise ValueError(
                f"Sphere spec needs exactly 3 coordinates, got {len(coords)}: {spec!r}"
            )
        x, y, z = coords
        if name is None:
            name = f"sphere_{int(x)}_{int(y)}_{int(z)}"
        return Seed.sphere(name, x, y, z, radius_mm)

    if spec.startswith("nifti:"):
        rest = spec[len("nifti:"):]
        # Detect trailing ",name=..." suffix
        name_match = re.search(r",name=([^,]+)$", rest)
        name = None
        if name_match:
            name = name_match.group(1).strip()
            nifti_str = rest[: name_match.start()]
        else:
            nifti_str = rest
        nifti_path = Path(nifti_str.strip())
        roi_name = name or nifti_path.name.replace(".nii.gz", "").replace(".nii", "")
        return Seed(
            id=f"custom_nifti-{roi_name}",
            name=roi_name,
            source="custom_nifti_roi",
            nifti_path=nifti_path,
        )

    raise ValueError(
        f"Unrecognized seed spec: {spec!r}\n"
        "Expected one of:\n"
        "  atlas-<name>:<parcel>\n"
        "  sphere:<x>,<y>,<z>[,r=<mm>][,name=<name>]\n"
        "  nifti:<path>[,name=<name>]"
    )


# ---------------------------------------------------------------------------
# Seed output ID (filesystem-safe label used in directory and file names)
# ---------------------------------------------------------------------------


def _seed_output_id(seed: Seed) -> str:
    """Return a filesystem-safe identifier for *seed* used in output paths."""
    if seed.source == "xcpd_atlas_parcel":
        # e.g. atlas-4S256Parcels_parcel-LH_Vis_1
        return seed.id

    if seed.source == "sphere":
        x, y, z = seed.coords_mm  # type: ignore[misc]
        r = seed.radius_mm
        xi = int(x) if x == int(x) else x
        yi = int(y) if y == int(y) else y
        zi = int(z) if z == int(z) else z
        ri = int(r) if r == int(r) else r
        return f"sphere-{xi}_{yi}_{zi}_r{ri}"

    if seed.source == "custom_nifti_roi":
        safe = re.sub(r"[^\w-]", "_", seed.name)
        return f"custom-{safe}"

    return re.sub(r"[^\w.-]", "_", seed.id)


# ---------------------------------------------------------------------------
# Seed timeseries extraction helpers
# ---------------------------------------------------------------------------


def _extract_sphere_timeseries(
    coords_mm: tuple[float, float, float],
    radius_mm: float,
    bold_data: np.ndarray,
    bold_img: nib.Nifti1Image,
) -> np.ndarray:
    """Mean timeseries of all voxels within *radius_mm* of *coords_mm* (MNI)."""
    X, Y, Z, T = bold_data.shape
    affine = bold_img.affine

    # Build voxel-index grid → MNI coordinates
    ix, iy, iz = np.meshgrid(np.arange(X), np.arange(Y), np.arange(Z), indexing="ij")
    n = X * Y * Z
    vox_hom = np.stack(
        [ix.ravel(), iy.ravel(), iz.ravel(), np.ones(n, dtype=np.float32)], axis=0
    )  # (4, N)
    mni = (affine @ vox_hom)[:3]  # (3, N)

    cx, cy, cz = coords_mm
    dist = np.sqrt((mni[0] - cx) ** 2 + (mni[1] - cy) ** 2 + (mni[2] - cz) ** 2)
    mask = dist <= radius_mm

    if not mask.any():
        raise ValueError(
            f"No voxels found within {radius_mm} mm of MNI {coords_mm}. "
            "Check that the coordinates are inside the BOLD volume."
        )

    bold_flat = bold_data.reshape(n, T)
    return bold_flat[mask].mean(axis=0).astype(np.float64)


def _extract_nifti_roi_timeseries(
    nifti_path: Path,
    bold_data: np.ndarray,
    bold_img: nib.Nifti1Image,
) -> np.ndarray:
    """Resample a custom NIfTI ROI to BOLD space and return mean timeseries."""
    try:
        from nilearn.image import resample_to_img
    except ImportError as exc:
        raise ImportError("nilearn is required for custom NIfTI ROI seeds.") from exc

    roi_img = nib.load(str(nifti_path))
    X, Y, Z, T = bold_data.shape

    # Reference: first BOLD volume (3-D)
    ref_img = nib.Nifti1Image(bold_data[..., 0], bold_img.affine)
    roi_resampled = resample_to_img(roi_img, ref_img, interpolation="nearest")
    mask = roi_resampled.get_fdata(dtype=np.float32) > 0.5

    if not mask.any():
        raise ValueError(
            f"NIfTI ROI {nifti_path} contains no voxels after resampling to BOLD space."
        )

    bold_flat = bold_data.reshape(X * Y * Z, T)
    return bold_flat[mask.ravel()].mean(axis=0).astype(np.float64)


def _extract_seed_timeseries(
    seed: Seed,
    xcpd_out: XcpdOutputs,
    bold_data: Optional[np.ndarray],
    bold_img: Optional[nib.Nifti1Image],
) -> np.ndarray:
    """Dispatch seed timeseries extraction based on seed source."""
    if seed.source == "xcpd_atlas_parcel":
        atlas = seed.atlas
        parcel_label = seed.parcel_label
        tsv_path = xcpd_out.mean_timeseries.get(atlas)  # type: ignore[arg-type]
        if tsv_path is None:
            raise KeyError(
                f"Atlas {atlas!r} not available in XCP-D outputs for "
                f"{xcpd_out.subject}/{xcpd_out.session}/{xcpd_out.pipeline}."
            )
        df = pd.read_csv(tsv_path, sep="\t")
        if parcel_label not in df.columns:
            raise KeyError(
                f"Parcel {parcel_label!r} not found in atlas {atlas!r}. "
                f"Available: {list(df.columns[:5])} ..."
            )
        return df[parcel_label].to_numpy(dtype=np.float64)

    if seed.source == "sphere":
        assert bold_data is not None and bold_img is not None
        return _extract_sphere_timeseries(
            seed.coords_mm,  # type: ignore[arg-type]
            seed.radius_mm,  # type: ignore[arg-type]
            bold_data,
            bold_img,
        )

    if seed.source == "custom_nifti_roi":
        assert bold_data is not None and bold_img is not None
        return _extract_nifti_roi_timeseries(
            seed.nifti_path,  # type: ignore[arg-type]
            bold_data,
            bold_img,
        )

    raise ValueError(f"Unknown seed source: {seed.source!r}")


# ---------------------------------------------------------------------------
# Seed-to-voxel Fisher-z map
# ---------------------------------------------------------------------------


def _compute_seed_to_voxel_zmap(
    seed_ts: np.ndarray,
    bold_data: np.ndarray,
    bold_img: nib.Nifti1Image,
    brain_mask: Optional[np.ndarray] = None,
) -> nib.Nifti1Image:
    """Compute voxel-wise Pearson r with *seed_ts*, Fisher-z transform, return NIfTI.
    
    Parameters
    ----------
    seed_ts : np.ndarray
        Seed timeseries (T,)
    bold_data : np.ndarray
        BOLD data (X, Y, Z, T)
    bold_img : nib.Nifti1Image
        BOLD image for affine
    brain_mask : np.ndarray, optional
        Brain mask (X, Y, Z) boolean array. If provided, only compute
        correlations for voxels within mask (memory-efficient).
        Non-brain voxels will be set to 0 in output.
    
    Returns
    -------
    nib.Nifti1Image
        Fisher-z transformed connectivity map
    """
    X, Y, Z, T = bold_data.shape
    n = X * Y * Z

    bold_flat = bold_data.reshape(n, T).astype(np.float64)

    # Demean seed
    seed_dm = seed_ts - seed_ts.mean()
    seed_norm = np.linalg.norm(seed_dm)

    # Initialize output
    r_values = np.zeros(n, dtype=np.float32)

    # If mask provided, only process masked voxels (memory-efficient)
    if brain_mask is not None:
        mask_1d = brain_mask.ravel()
        mask_indices = np.where(mask_1d)[0]
        n_masked = len(mask_indices)
        
        _LOG.info("    Computing correlations for %d masked voxels (%.1f%% of volume)", 
                  n_masked, 100 * n_masked / n)
        
        # Process in chunks to avoid memory issues
        chunk_size = 50000
        n_chunks = (n_masked + chunk_size - 1) // chunk_size
        
        for i in range(n_chunks):
            start = i * chunk_size
            end = min((i + 1) * chunk_size, n_masked)
            chunk_indices = mask_indices[start:end]
            
            # Get chunk data
            chunk_data = bold_flat[chunk_indices]
            
            # Demean
            chunk_mean = chunk_data.mean(axis=1, keepdims=True)
            chunk_dm = chunk_data - chunk_mean
            chunk_norms = np.linalg.norm(chunk_dm, axis=1)
            
            # Pearson
            num = chunk_dm @ seed_dm
            denom = chunk_norms * seed_norm
            
            with np.errstate(invalid="ignore", divide="ignore"):
                r_chunk = np.where(denom > 0, num / denom, 0.0)
            
            r_values[chunk_indices] = r_chunk
    else:
        # Process all voxels (original behavior, memory-intensive)
        _LOG.info("    Computing correlations for all %d voxels (no mask)", n)
        
        vox_mean = bold_flat.mean(axis=1, keepdims=True)
        voxels_dm = bold_flat - vox_mean
        vox_norms = np.linalg.norm(voxels_dm, axis=1)
        
        num = voxels_dm @ seed_dm
        denom = vox_norms * seed_norm
        
        with np.errstate(invalid="ignore", divide="ignore"):
            r_values = np.where(denom > 0, num / denom, 0.0)

    # Fisher-z transform
    clip_val = 1.0 - 1e-7
    r_clipped = np.clip(r_values, -clip_val, clip_val)
    z = np.arctanh(r_clipped).reshape(X, Y, Z).astype(np.float32)

    return nib.Nifti1Image(z, bold_img.affine)


# ---------------------------------------------------------------------------
# Seed-to-parcel TSV
# ---------------------------------------------------------------------------


def _compute_and_save_seed_to_parcel(
    seed_ts: np.ndarray,
    atlas: str,
    measure: str,
    xcpd_out: XcpdOutputs,
    out_tsv: Path,
    tr: float,
) -> None:
    """Compute seed-to-parcel connectivity vector for one atlas/measure and save."""
    tsv_path = xcpd_out.mean_timeseries[atlas]
    atlas_df = pd.read_csv(tsv_path, sep="\t")
    parcel_labels = list(atlas_df.columns)
    atlas_ts = atlas_df.to_numpy(dtype=np.float64)  # (T, N_parcels)

    # Replace NaN / constant-parcel signal with 0 (coverage gaps → zero connectivity)
    atlas_ts = np.nan_to_num(atlas_ts, nan=0.0)
    seed_ts_clean = np.nan_to_num(seed_ts, nan=0.0)

    # Seed is column 0; parcels are columns 1..N
    combined = np.column_stack([seed_ts_clean, atlas_ts])  # (T, N+1)

    mat = compute(measure, combined, fs=1.0 / tr)  # (N+1, N+1)

    seed_row = mat[0, 1:]  # (N_parcels,) — seed-to-parcel

    # Any remaining NaN (e.g. constant parcels → undefined correlation) → 0
    seed_row = np.nan_to_num(seed_row, nan=0.0)

    if measure in CORRELATION_TYPE:
        seed_row = fisher_z(seed_row)

    result_df = pd.DataFrame([seed_row], columns=parcel_labels)
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    result_df.to_csv(out_tsv, sep="\t", index=False, float_format="%.8f")


# ---------------------------------------------------------------------------
# Meta JSON
# ---------------------------------------------------------------------------


def _write_meta(
    path: Path,
    seed: Seed,
    pipeline: str,
    bold_variant: str,
    tr: float,
    measures: list[str],
    atlases: list[str],
    t0: float,
    subject: Optional[str] = None,
    session: Optional[str] = None,
    brain_mask_path: Optional[str] = None,
    n_brain_voxels: Optional[int] = None,
    n_timepoints: Optional[int] = None,
    zmap_shape: Optional[list] = None,
) -> None:
    """Write a JSON sidecar with provenance and run metadata."""
    import scipy

    try:
        import nilearn
        nilearn_ver = nilearn.__version__
    except Exception:
        nilearn_ver = "unavailable"

    meta: dict = {
        "subject": subject,
        "session": session,
        "seed_spec": {
            "id": seed.id,
            "name": seed.name,
            "source": seed.source,
            "atlas": seed.atlas,
            "parcel_label": seed.parcel_label,
            "coords_mm": list(seed.coords_mm) if seed.coords_mm else None,
            "radius_mm": seed.radius_mm,
            "nifti_path": str(seed.nifti_path) if seed.nifti_path else None,
        },
        "pipeline": pipeline,
        "bold_variant": bold_variant,
        "tr": tr,
        "n_timepoints": n_timepoints,
        "measures": measures,
        "atlas_list": atlases,
        "brain_mask_path": brain_mask_path,
        "n_brain_voxels": n_brain_voxels,
        "zmap_shape": zmap_shape,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "software_versions": {
            "nibabel": nib.__version__,
            "nilearn": nilearn_ver,
            "numpy": np.__version__,
            "scipy": scipy.__version__,
        },
        "runtime_seconds": round(time.time() - t0, 2),
    }
    path.write_text(json.dumps(meta, indent=2))


# ---------------------------------------------------------------------------
# Per-seed orchestration
# ---------------------------------------------------------------------------


def _process_seed(
    seed: Seed,
    xcpd_out: XcpdOutputs,
    bold_path: Optional[Path],
    measures: list[str],
    atlases: list[str],
    out_root: Path,
    subject: str,
    session: str,
    pipeline: str,
    bold_variant: str,
    tr: float,
    force: bool,
    t0: float,
) -> None:
    """Process one seed: extract timeseries, compute all outputs."""
    seed_id = _seed_output_id(seed)
    seed_dir = out_root / pipeline / subject / session / "seed" / seed_id
    seed_dir.mkdir(parents=True, exist_ok=True)

    prefix = f"{subject}_{session}_seed-{seed_id}"

    # Determine which outputs are needed
    tsv_needed: dict[tuple[str, str], Path] = {}
    for atlas in atlases:
        for measure in measures:
            p = seed_dir / f"{prefix}_atlas-{atlas}_measure-{measure}_seed-to-parcel.tsv"
            if force or not p.exists():
                tsv_needed[(atlas, measure)] = p

    zmap_path = seed_dir / f"{prefix}_seed-to-voxel_zmap.nii.gz"
    meta_path = seed_dir / f"{prefix}_meta.json"
    zmap_needed = force or not zmap_path.exists()
    meta_needed = force or not meta_path.exists()

    if not tsv_needed and not zmap_needed and not meta_needed:
        _LOG.info("Skipping %s (all outputs exist; use --force to recompute)", seed_id)
        return

    _LOG.info("Processing seed: %s", seed_id)

    # Decide whether BOLD is needed
    needs_bold = seed.source in ("sphere", "custom_nifti_roi") or zmap_needed

    bold_img: Optional[nib.Nifti1Image] = None
    bold_data: Optional[np.ndarray] = None
    if needs_bold:
        if bold_path is None or not bold_path.exists():
            raise FileNotFoundError(
                f"BOLD file required but not found: {bold_path}. "
                f"Seed source='{seed.source}', bold_variant='{bold_variant}'."
            )
        _LOG.info("  Loading BOLD: %s", bold_path.name)
        bold_img = nib.load(str(bold_path))
        bold_data = bold_img.get_fdata(dtype=np.float32)

    # Extract seed timeseries
    _LOG.info("  Extracting seed timeseries (source=%s)", seed.source)
    seed_ts = _extract_seed_timeseries(seed, xcpd_out, bold_data, bold_img)

    # Seed-to-parcel TSVs
    for (atlas, measure), out_tsv in tsv_needed.items():
        _LOG.info("  Seed-to-parcel: atlas=%s measure=%s", atlas, measure)
        _compute_and_save_seed_to_parcel(seed_ts, atlas, measure, xcpd_out, out_tsv, tr)

    # Seed-to-voxel z-map (Pearson only)
    active_mask_path: Optional[str] = None
    n_brain_voxels: Optional[int] = None
    zmap_shape: Optional[list] = None
    if zmap_needed:
        assert bold_data is not None and bold_img is not None
        _LOG.info("  Seed-to-voxel z-map")
        
        # Load brain mask (dilated MNI 2mm)
        brain_mask = None
        try:
            from pathlib import Path as P
            import os
            
            # Try local atlas directory first
            bids_root_path = P(xcpd_out.bids_root) if hasattr(xcpd_out, 'bids_root') else P.cwd()
            mask_candidates = [
                bids_root_path / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz",
                P(os.environ.get("FSLDIR", "/usr/share/fsl")) / "data" / "standard" / "MNI152_T1_2mm_brain_mask_dil.nii.gz",
            ]
            
            for mask_path in mask_candidates:
                if mask_path.exists():
                    _LOG.info("    Loading brain mask: %s", mask_path.name)
                    mask_img = nib.load(str(mask_path))
                    brain_mask = mask_img.get_fdata() > 0.5
                    
                    # Resample to BOLD space if needed
                    if brain_mask.shape != bold_data.shape[:3]:
                        _LOG.info("    Resampling mask from %s to %s", brain_mask.shape, bold_data.shape[:3])
                        from nilearn.image import resample_to_img
                        ref_img = nib.Nifti1Image(bold_data[..., 0], bold_img.affine)
                        mask_img_resampled = resample_to_img(mask_img, ref_img, interpolation='nearest')
                        brain_mask = mask_img_resampled.get_fdata() > 0.5
                    
                    n_brain_voxels = int(brain_mask.sum())
                    active_mask_path = str(mask_path)
                    _LOG.info("    Brain mask loaded: %d voxels", n_brain_voxels)
                    break
            
            if brain_mask is None:
                _LOG.warning("    No brain mask found - processing all voxels (slower)")
        except Exception as e:
            _LOG.warning("    Could not load brain mask (%s) - processing all voxels", e)
        
        zmap_img = _compute_seed_to_voxel_zmap(seed_ts, bold_data, bold_img, brain_mask)
        nib.save(zmap_img, str(zmap_path))
        zmap_shape = list(zmap_img.shape)

    # Meta JSON
    if meta_needed:
        _write_meta(
            path=meta_path,
            seed=seed,
            pipeline=pipeline,
            bold_variant=bold_variant,
            tr=tr,
            measures=measures,
            atlases=atlases,
            t0=t0,
            subject=subject,
            session=session,
            brain_mask_path=active_mask_path,
            n_brain_voxels=n_brain_voxels,
            n_timepoints=int(seed_ts.shape[0]),
            zmap_shape=zmap_shape,
        )

    _LOG.info("  Done: %s", seed_id)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run(
    bids_root: Path | str,
    subject: str,
    session: str,
    pipeline: str,
    seed_specs: list[str],
    measures: list[str],
    bold_variant: str,
    out_root: Path | str,
    tr: float,
    force: bool = False,
    atlases: Optional[list[str]] = None,
) -> None:
    """Run seed-based connectivity for one subject/session.

    Parameters
    ----------
    bids_root    : Path or str — BIDS project root.
    subject      : str — Subject label (e.g. "sub-033").
    session      : str — Session label (e.g. "ses-01").
    pipeline     : str — XCP-D pipeline (e.g. "fc", "fc_gsr", "ec").
    seed_specs   : list[str] — CLI-style seed specifications.
    measures     : list[str] — Connectivity measures to compute.
    bold_variant : str — "denoised" or "denoisedSmoothed".
    out_root     : Path or str — Root for connectivity outputs.
    tr           : float — Repetition time in seconds.
    force        : bool — Recompute even if outputs exist.
    atlases      : list[str] or None — Atlas subset; None means all available.
    """
    t0 = time.time()
    bids_root = Path(bids_root)
    out_root = Path(out_root)

    # Validate measures
    unknown = [m for m in measures if m not in MEASURES]
    if unknown:
        raise ValueError(
            f"Unknown measure(s): {unknown}. Valid choices: {sorted(MEASURES)}"
        )

    # Discover XCP-D outputs
    disc = XcpdDiscovery(bids_root, pipeline)
    xcpd_out = disc.get(subject, session, pipeline)

    # Resolve BOLD path
    if bold_variant == "denoisedSmoothed":
        bold_path = xcpd_out.denoised_smoothed_bold
    elif bold_variant == "denoised":
        bold_path = xcpd_out.denoised_bold
    else:
        raise ValueError(f"Unknown bold_variant: {bold_variant!r}")

    # Resolve atlases
    available_atlases = xcpd_out.list_atlases()
    if atlases is not None:
        available_atlases = [a for a in available_atlases if a in atlases]
    if not available_atlases:
        raise ValueError(
            f"No atlas timeseries available for {subject}/{session}/{pipeline}. "
            f"Requested: {atlases}"
        )

    # Parse seeds
    seeds = [_parse_seed_spec(s) for s in seed_specs]

    _LOG.info(
        "Subject=%s Session=%s Pipeline=%s  seeds=%d measures=%s atlases=%s",
        subject, session, pipeline, len(seeds), measures, available_atlases,
    )

    for seed in seeds:
        _process_seed(
            seed=seed,
            xcpd_out=xcpd_out,
            bold_path=bold_path,
            measures=measures,
            atlases=available_atlases,
            out_root=out_root,
            subject=subject,
            session=session,
            pipeline=pipeline,
            bold_variant=bold_variant,
            tr=tr,
            force=force,
            t0=t0,
        )

    _LOG.info("Finished in %.1f s", time.time() - t0)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Subject-level seed-based connectivity (XCP-D driven).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--bids-root", required=True, type=Path,
        help="BIDS project root directory."
    )
    p.add_argument("--subject", required=True, help="Subject label (e.g. sub-033).")
    p.add_argument("--session", required=True, help="Session label (e.g. ses-01).")
    p.add_argument(
        "--pipeline", default="fc", choices=["fc", "fc_gsr", "ec"],
        help="XCP-D pipeline (default: fc)."
    )
    p.add_argument(
        "--seed", dest="seeds", action="append", required=True, metavar="SPEC",
        help=(
            "Seed spec (repeatable). Formats: "
            "atlas-<name>:<parcel> | sphere:<x>,<y>,<z>[,r=<mm>][,name=<n>] | "
            "nifti:<path>[,name=<n>]"
        ),
    )
    p.add_argument(
        "--measures", default="pearson",
        help="Comma-separated connectivity measures (default: pearson).",
    )
    p.add_argument(
        "--bold", dest="bold_variant", default="denoisedSmoothed",
        choices=["denoised", "denoisedSmoothed"],
        help="BOLD variant to use (default: denoisedSmoothed).",
    )
    p.add_argument(
        "--out-root", required=True, type=Path,
        help="Root directory for connectivity outputs.",
    )
    p.add_argument("--tr", type=float, default=0.8, help="TR in seconds (default: 0.8).")
    p.add_argument(
        "--force", action="store_true",
        help="Recompute all outputs even if they already exist.",
    )
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)
    measures = [m.strip() for m in args.measures.split(",") if m.strip()]
    run(
        bids_root=args.bids_root,
        subject=args.subject,
        session=args.session,
        pipeline=args.pipeline,
        seed_specs=args.seeds,
        measures=measures,
        bold_variant=args.bold_variant,
        out_root=args.out_root,
        tr=args.tr,
        force=args.force,
    )


if __name__ == "__main__":
    main()
