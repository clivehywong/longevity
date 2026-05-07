"""Shared seed visualisation utilities.

Provides:
  - cli_token_to_seed_dir_name  — canonical CLI token → filesystem dir name
  - make_seed_preview_png       — nilearn plot_roi PNG for a seed token
"""

from __future__ import annotations

import io
import re
from pathlib import Path


# ---------------------------------------------------------------------------
# Token → directory-name conversion
# ---------------------------------------------------------------------------

def cli_token_to_seed_dir_name(token: str) -> str:
    """Convert a CLI seed token to the on-disk directory name.

    Must produce the same string as
    ``script/compute_seed_connectivity_xcpd.py::_seed_output_id()``.

    Examples
    --------
    >>> cli_token_to_seed_dir_name("sphere:-46,16,32,r=6,name=dlpfc_l")
    'sphere--46_16_32_r6'
    >>> cli_token_to_seed_dir_name("atlas-4S256Parcels:RH_Cont_Par_1")
    'atlas-4S256Parcels_parcel-RH_Cont_Par_1'
    """
    if token.startswith("sphere:"):
        m = re.match(r"sphere:([-\d.]+),([-\d.]+),([-\d.]+),r=([\d.]+)", token)
        if m:
            x, y, z, r = (float(m.group(i)) for i in range(1, 5))
            xi = int(x) if x == int(x) else x
            yi = int(y) if y == int(y) else y
            zi = int(z) if z == int(z) else z
            ri = int(r) if r == int(r) else r
            return f"sphere-{xi}_{yi}_{zi}_r{ri}"

    if token.startswith("atlas-"):
        m = re.match(r"atlas-([^:]+):(.+)$", token)
        if m:
            return f"atlas-{m.group(1)}_parcel-{m.group(2)}"

    if token.startswith("nifti:"):
        name_m = re.search(r",name=(.+)$", token)
        name = name_m.group(1) if name_m else Path(token[len("nifti:"):].split(",")[0]).stem
        safe = re.sub(r"[^\w-]", "_", name)
        return f"custom-{safe}"

    # Bare path or unknown — sanitise
    return re.sub(r"[^\w.-]", "_", token)


# ---------------------------------------------------------------------------
# Seed preview PNG
# ---------------------------------------------------------------------------

def make_seed_preview_png(token: str, bids_root_str: str) -> bytes | None:
    """Return a PNG (bytes) showing the seed ROI overlaid on the MNI template.

    Handles three token types:
      - ``sphere:x,y,z,r=radius,name=...``
      - ``atlas-{Atlas}:{ParcelLabel}``
      - ``nifti:/path/to/roi.nii.gz[,name=...]`` or bare file path

    Returns ``None`` if the ROI cannot be resolved (unsupported atlas, missing
    file, bad token) — callers should display a graceful warning instead of
    raising.
    """
    import nibabel as nib  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415
    import matplotlib  # noqa: PLC0415
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415
    from nilearn import plotting  # noqa: PLC0415
    from nilearn.datasets import load_mni152_template  # noqa: PLC0415

    bg = load_mni152_template(resolution=2)
    roi_img = None
    cut_coords: tuple[float, float, float] = (0.0, 0.0, 0.0)
    title = token

    # ── Sphere ────────────────────────────────────────────────────────────
    if token.startswith("sphere:"):
        m = re.match(r"sphere:([-\d.]+),([-\d.]+),([-\d.]+),r=([\d.]+)", token)
        if not m:
            return None
        cx, cy, cz = float(m.group(1)), float(m.group(2)), float(m.group(3))
        radius = float(m.group(4))
        cut_coords = (cx, cy, cz)

        affine = bg.affine
        shape = bg.shape[:3]
        i_idx, j_idx, k_idx = np.indices(shape)
        vox = np.stack(
            [i_idx.ravel(), j_idx.ravel(), k_idx.ravel(), np.ones(i_idx.size)], axis=0
        )
        mm = (affine @ vox)[:3, :]
        center = np.array([cx, cy, cz])[:, np.newaxis]
        mask_data = (np.sqrt(((mm - center) ** 2).sum(axis=0)) <= radius).astype(np.int16)
        roi_img = nib.Nifti1Image(mask_data.reshape(shape), affine)

        name_m = re.search(r",name=(.+)$", token)
        label = name_m.group(1) if name_m else f"({cx}, {cy}, {cz})"
        title = f"{label}   [{cx}, {cy}, {cz}]  r={radius} mm"

    # ── Atlas parcel ──────────────────────────────────────────────────────
    elif token.startswith("atlas-"):
        m = re.match(r"atlas-([^:]+):(.+)$", token)
        if not m:
            return None
        atlas_name, parcel_label = m.group(1), m.group(2)

        atlas_img = None
        label_int: int | None = None

        # Try project xcpd_project_atlases first
        atlas_dir = (
            Path(bids_root_str)
            / "atlases"
            / "xcpd_project_atlases"
            / "tpl-MNI152NLin2009cAsym"
        )
        local_dseg = next(iter(atlas_dir.glob(f"*atlas-{atlas_name}*_dseg.nii.gz")), None)
        if local_dseg:
            tsv_path = local_dseg.with_suffix("").with_suffix(".tsv")
            if tsv_path.exists():
                with open(tsv_path) as fh:
                    next(fh)
                    for line in fh:
                        parts = line.rstrip("\n").split("\t")
                        if len(parts) >= 2 and parts[1] == parcel_label:
                            label_int = int(parts[0])
                            break
                if label_int is not None:
                    atlas_img = nib.load(local_dseg)

        # Fallback: nilearn Schaefer for 4S*Parcels
        if atlas_img is None and re.match(r"4S(\d+)Parcels", atlas_name):
            n_rois_m = re.match(r"4S(\d+)Parcels", atlas_name)
            n_rois_raw = int(n_rois_m.group(1))
            schaefer_map = {
                256: 200, 356: 300, 456: 400, 556: 500, 656: 600,
                756: 700, 856: 800, 956: 900, 1056: 1000,
            }
            n_schaefer = schaefer_map.get(n_rois_raw, 200)
            try:
                from nilearn.datasets import fetch_atlas_schaefer_2018  # noqa: PLC0415
                sch = fetch_atlas_schaefer_2018(
                    n_rois=n_schaefer, yeo_networks=7, resolution_mm=2
                )
                sch_img = nib.load(sch.maps)
                sch_labels = list(sch.labels)
                target = parcel_label
                for prefix in ("7Networks_", "17Networks_", ""):
                    candidate = prefix + target
                    if candidate in sch_labels:
                        label_int = sch_labels.index(candidate)
                        atlas_img = sch_img
                        break
            except Exception:
                pass

        if atlas_img is None or label_int is None:
            return None

        atlas_data = np.round(atlas_img.get_fdata()).astype(np.int32)
        mask_data = (atlas_data == label_int).astype(np.int16)
        roi_img = nib.Nifti1Image(mask_data, atlas_img.affine)

        vox_coords = np.argwhere(mask_data > 0)
        if len(vox_coords) > 0:
            from nibabel.affines import apply_affine  # noqa: PLC0415
            centroid_vox = vox_coords.mean(axis=0)
            cx, cy, cz = apply_affine(atlas_img.affine, centroid_vox)
            cut_coords = (float(cx), float(cy), float(cz))
        title = f"{atlas_name}  ·  {parcel_label}"

    # ── Custom NIfTI / bare path ──────────────────────────────────────────
    else:
        nifti_path = token
        if token.startswith("nifti:"):
            nifti_path = token[len("nifti:"):].split(",name=")[0]
        if not Path(nifti_path).exists():
            return None
        roi_img = nib.load(nifti_path)
        title = Path(nifti_path).name

    if roi_img is None:
        return None

    fig = plt.figure(figsize=(10, 3), facecolor="black")
    try:
        plotting.plot_roi(
            roi_img,
            bg_img=bg,
            cut_coords=cut_coords,
            display_mode="ortho",
            figure=fig,
            title=title,
            cmap="autumn",
            alpha=0.85,
            colorbar=False,
        )
    except Exception:
        plt.close(fig)
        return None

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=100, bbox_inches="tight", facecolor="black")
    plt.close(fig)
    buf.seek(0)
    return buf.read()
