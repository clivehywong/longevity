"""Group cluster analysis utilities: GRF (randomise tstat) and TFCE (corrp) cluster extraction.

Matches the logic of:
  script/fsl/cluster.sh      → run_grf_cluster
  script/fsl/tfce-cluster.sh → run_tfce_cluster
"""

from __future__ import annotations

import functools
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

# Column renames from fsl-cluster tab-separated output to display-friendly names
_COL_RENAMES: dict[str, str] = {
    "Cluster Index": "Cluster",
    "Voxels": "Voxels",
    "P": "p(FWE)",
    "-log10(P)": "-log10p",
    "Z-MAX": "Peak Z",
    "Z-MAX X (mm)": "X(mm)",
    "Z-MAX Y (mm)": "Y(mm)",
    "Z-MAX Z (mm)": "Z(mm)",
    # zthresh output uses MAX (not Z-MAX) — rename to Peak Z for consistency
    "MAX": "Peak Z",
    "MAX X (mm)": "X(mm)",
    "MAX Y (mm)": "Y(mm)",
    "MAX Z (mm)": "Z(mm)",
}


@dataclass
class ClusterResult:
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    cluster_img: dict[str, Path | None] = field(default_factory=dict)
    params: dict = field(default_factory=dict)
    error: str | None = None


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def fsl_available() -> bool:
    """Check if FSL's smoothest is accessible in PATH."""
    return shutil.which("smoothest") is not None


def _run_cmd(cmd: list[str] | str, timeout: int = 120) -> tuple[int, str, str]:
    """Run a shell command; returns (returncode, stdout, stderr)."""
    if isinstance(cmd, str):
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
    else:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr


def _parse_smoothest(stdout: str) -> dict | None:
    """Parse smoothest stdout; extract DLH, RESELS, VOLUME into a dict."""
    data: dict = {}
    for line in stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        key, val = parts[0], parts[1]
        try:
            if key == "DLH":
                data["DLH"] = float(val)
            elif key == "RESELS":
                data["RESELS"] = float(val)
            elif key == "VOLUME":
                data["VOLUME"] = int(val)
        except ValueError:
            pass
    return data if ("DLH" in data and "VOLUME" in data) else None


@functools.lru_cache(maxsize=512)
def query_atlasq_label(x: int, y: int, z: int) -> str:
    """Query atlas label for a single MNI coordinate (coordinate-based, lru_cached)."""
    results = query_atlasq_labels_batch(((x, y, z),))
    return results[0] if results else "Unknown"


def query_atlasq_labels_batch(
    coords: tuple[tuple[int, int, int], ...] | list[tuple[int, int, int]],
) -> list[str]:
    """Coordinate-based fallback: query top label per coord via AAL3v1 + HO Cortical."""
    coords = list(coords)
    if not coords:
        return []

    labels = ["NA"] * len(coords)

    def _coord_batch(atlas: str, idxs: list[int]) -> list[str]:
        args = ["atlasq", "query", atlas, "-s"]
        for i in idxs:
            x, y, z = coords[i]
            args += ["-c", str(x), str(y), str(z)]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=300)
            out = []
            for line in r.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 3:
                    region = re.sub(r"\s+[\d.]+$", "", parts[2]).strip()
                    out.append(region if region else "NA")
                else:
                    out.append("NA")
            while len(out) < len(idxs):
                out.append("NA")
            return out[:len(idxs)]
        except Exception:
            return ["Unknown"] * len(idxs)

    aal = _coord_batch("AAL3v1", list(range(len(coords))))
    for i, lbl in enumerate(aal):
        labels[i] = lbl
    na_idxs = [i for i, lbl in enumerate(labels) if lbl == "NA"]
    if na_idxs:
        ho = _coord_batch("Harvard-Oxford Cortical Structural Atlas", na_idxs)
        for i, lbl in zip(na_idxs, ho):
            labels[i] = lbl if lbl != "NA" else "Unknown"
    return labels


def _find_atlas_space() -> tuple[Path | None, list | None]:
    """Return (atlas_nifti_path, affine) for AAL3v1 at 2mm, or None if not found."""
    import os
    fsldir = os.environ.get("FSLDIR", "/home/clivewong/fsl")
    candidate = Path(fsldir) / "data" / "atlases" / "AAL3" / "AAL3v1.nii.gz"
    if candidate.exists():
        try:
            import nibabel as nib
            img = nib.load(str(candidate))
            return candidate, img.affine
        except Exception:
            pass
    return None, None


def query_atlasq_labels_by_mask(
    cluster_index_path: Path,
    cluster_ids: list[int],
    top_n: int = 3,
) -> list[str]:
    """Query anatomical labels for clusters using mask-based atlasq query.

    For each cluster ID, extracts a binary mask from cluster_index_path, then
    queries AAL3v1 (and HO Cortical fallback for all-NA results) in a single
    batch call. Returns top_n non-NA region names joined by ' / ' for each cluster.

    The cluster image is assumed to be in MNI RAS space (fMRIPrep/XCP-D standard).
    Masks are x-flipped to match the FSL atlas radiological convention before querying.
    """
    import tempfile, shutil
    try:
        import nibabel as nib
        import numpy as np
    except ImportError:
        return ["Unknown"] * len(cluster_ids)

    if not cluster_ids:
        return []

    _, atlas_affine = _find_atlas_space()
    if atlas_affine is None:
        return query_atlasq_labels_batch(
            [(0, 0, 0)] * len(cluster_ids)  # fallback: coordinate at origin
        )

    # Load cluster index
    try:
        ci_img = nib.load(str(cluster_index_path))
        ci_data = np.asanyarray(ci_img.dataobj)
    except Exception:
        return ["Unknown"] * len(cluster_ids)

    tmpdir = tempfile.mkdtemp(prefix="atlasq_masks_")
    mask_paths: list[str] = []
    try:
        for cid in cluster_ids:
            mask_data = (ci_data == cid).astype(np.uint8)
            # x-flip to match FSL atlas radiological convention
            mask_data = mask_data[::-1, :, :]
            mask_img = nib.Nifti1Image(mask_data, atlas_affine)
            p = str(Path(tmpdir) / f"cluster_{cid}.nii.gz")
            nib.save(mask_img, p)
            mask_paths.append(p)

        def _mask_batch(atlas: str, idxs: list[int]) -> list[list[str]]:
            """Run atlasq for selected mask indices; return list of label lists."""
            args = ["atlasq", "query", atlas, "-s"]
            for i in idxs:
                args += ["-m", mask_paths[i]]
            try:
                r = subprocess.run(args, capture_output=True, text=True, timeout=300)
                results = []
                for line in r.stdout.strip().splitlines():
                    parts = line.split("\t")
                    region_labels = []
                    for part in parts[2:]:
                        part = part.strip()
                        if not part:
                            continue
                        name = re.sub(r"\s+[\d.]+$", "", part).strip()
                        if name and name != "NA":
                            region_labels.append(name)
                            if len(region_labels) >= top_n:
                                break
                    results.append(region_labels)
                while len(results) < len(idxs):
                    results.append([])
                return results[:len(idxs)]
            except Exception:
                return [[] for _ in idxs]

        all_idxs = list(range(len(cluster_ids)))

        # Pass 1: AAL3v1 (fast — ~1.3s for 84 masks)
        aal_results = _mask_batch("AAL3v1", all_idxs)

        # Pass 2: HO Cortical fallback for clusters with no AAL3v1 labels
        na_idxs = [i for i, lbls in enumerate(aal_results) if not lbls]
        if na_idxs:
            ho_results = _mask_batch("Harvard-Oxford Cortical Structural Atlas", na_idxs)
            for pos, i in enumerate(na_idxs):
                if ho_results[pos]:
                    aal_results[i] = ho_results[pos]

        return [" / ".join(lbls) if lbls else "Unknown" for lbls in aal_results]

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def parse_cluster_table(txt_path: Path) -> pd.DataFrame:
    """Parse tab-separated fsl-cluster stdout saved to *txt_path* → DataFrame.

    Handles both GRF format (P column meaningful) and TFCE format (P=1).
    """
    text = txt_path.read_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return pd.DataFrame()

    header = lines[0].split("\t")
    data_lines = lines[1:]
    if not data_lines:
        return pd.DataFrame(columns=[_COL_RENAMES.get(h, h) for h in header])

    rows = [ln.split("\t") for ln in data_lines]
    df = pd.DataFrame(rows, columns=header)
    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="ignore")

    return df.rename(columns=_COL_RENAMES)


# ──────────────────────────────────────────────────────────────────────────────
# GRF cluster analysis (matching cluster.sh)
# ──────────────────────────────────────────────────────────────────────────────

def run_grf_cluster(
    tstat_path: Path,
    mask_path: Path,
    out_dir: Path,
    z_thr: float = 2.3,
    p_thr: float = 0.05,
    k: int = 1,
    smoothness: str = "z",
    tail: str = "both",
) -> ClusterResult:
    """Run GRF cluster analysis on a randomise/lmm tstat map.

    smoothness='z'  → smoothest -z <tstat> -m <mask>  (default)
    smoothness='r'  → smoothest -d <dof> -r <res4d> -m <mask>
                      Falls back to 'z' if res4d/dof not found.
    tail: 'both' | 'pos' | 'neg'
    """
    if not fsl_available():
        return ClusterResult(error="FSL not available")

    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Smoothness estimation ──────────────────────────────────────────
    smooth_data: dict | None = None

    if smoothness == "r":
        stats_dir = tstat_path.parent
        res4d_candidates = [stats_dir / "res4d.nii.gz", stats_dir / "res4d"]
        res4d = next((p for p in res4d_candidates if p.exists()), None)
        dof_file = stats_dir / "dof"
        if res4d and dof_file.exists():
            try:
                dof = dof_file.read_text().strip()
                rc, stdout, _ = _run_cmd(
                    f"smoothest -d {dof} -r {res4d} -m {mask_path}"
                )
                if rc == 0:
                    smooth_data = _parse_smoothest(stdout)
            except Exception:
                pass
        if smooth_data is None:
            smoothness = "z"  # fall back gracefully

    if smooth_data is None:
        rc, stdout, stderr = _run_cmd(f"smoothest -z {tstat_path} -m {mask_path}")
        if rc != 0:
            return ClusterResult(error=f"smoothest failed (rc={rc}): {stderr[:400]}")
        smooth_data = _parse_smoothest(stdout)
        if smooth_data is None:
            return ClusterResult(
                error=f"Could not parse smoothest output:\n{stdout[:400]}"
            )

    DLH = smooth_data["DLH"]
    VOLUME = smooth_data["VOLUME"]
    RESELS = smooth_data.get("RESELS")

    # ── Determine tails ───────────────────────────────────────────────
    tails: list[str]
    match tail:
        case "pos":
            tails = ["pos"]
        case "neg":
            tails = ["neg"]
        case _:
            tails = ["pos", "neg"]

    tables: dict[str, pd.DataFrame] = {}
    cluster_imgs: dict[str, Path | None] = {}

    for t in tails:
        pfx = out_dir / f"grf_{t}"
        thresh_file = pfx.parent / f"{pfx.name}_thresh"
        cluster_index = pfx.parent / f"{pfx.name}_cluster_index"
        lmax_file = pfx.parent / f"{pfx.name}_lmax.txt"
        cluster_txt = pfx.parent / f"{pfx.name}_cluster.txt"
        cluster_img = pfx.parent / f"{pfx.name}_cluster_img"

        # Threshold tstat for the requested tail
        if t == "pos":
            fslmaths_cmd = f"fslmaths {tstat_path} -thr {z_thr} {thresh_file}"
        else:
            fslmaths_cmd = (
                f"fslmaths {tstat_path} -mul -1 -thr {z_thr} {thresh_file}"
            )
        rc, _, err = _run_cmd(fslmaths_cmd)
        if rc != 0:
            return ClusterResult(error=f"fslmaths threshold failed ({t}): {err[:400]}")

        # Build fsl-cluster command — all long opts use = (FSL parser requires this)
        cluster_cmd = (
            f"fsl-cluster --in={thresh_file} --thresh={z_thr}"
            f" --othresh={thresh_file} --oindex={cluster_index}"
            f" --olmax={lmax_file} --pthresh={p_thr}"
            f" --dlh={DLH}"
        )
        if RESELS is not None:
            cluster_cmd += f" --resels={RESELS}"
        cluster_cmd += f" --volume={VOLUME} --minextent={k} --mm"

        rc, stdout, stderr = _run_cmd(cluster_cmd, timeout=180)
        cluster_txt.write_text(stdout)
        if rc != 0:
            return ClusterResult(
                error=f"fsl-cluster failed ({t}): {stderr[:400]}"
            )

        # Save masked cluster image (for reference only)
        cluster_index_nii = Path(str(cluster_index) + ".nii.gz")
        if cluster_index_nii.exists():
            _run_cmd(f"fslmaths {thresh_file} -mas {cluster_index} {cluster_img}")
        # Return integer-labeled cluster index (not the float tstat) so that
        # ci_data == cluster_label comparisons work downstream.
        cluster_imgs[t] = cluster_index_nii if cluster_index_nii.exists() else None
        tables[t] = parse_cluster_table(cluster_txt)

    return ClusterResult(
        tables=tables,
        cluster_img=cluster_imgs,
        params={
            "z_thr": z_thr,
            "p_thr": p_thr,
            "k": k,
            "smoothness": smoothness,
            "DLH": DLH,
            "RESELS": RESELS,
            "VOLUME": VOLUME,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# LMM cluster labeling (cN_zthresh.nii.gz — already GRF-corrected)
# ──────────────────────────────────────────────────────────────────────────────

def run_lmm_cluster(
    zthresh_path: Path,
    out_dir: Path,
    min_voxels: int = 50,
) -> ClusterResult:
    """Label clusters in an already GRF-corrected z-stat map (LMM cN_zthresh.nii.gz).

    Uses fsl-cluster just for connected-component labeling and peak extraction.
    No GRF p-value is applied — the input is already corrected.
    """
    import nibabel as nib  # noqa: PLC0415
    import numpy as np  # noqa: PLC0415

    if not fsl_available():
        return ClusterResult(error="FSL not available")
    if not zthresh_path.exists():
        return ClusterResult(error=f"zthresh file not found: {zthresh_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    cluster_index = out_dir / "lmm_cluster_index"
    lmax_file = out_dir / "lmm_lmax.txt"
    cluster_txt = out_dir / "lmm_cluster.txt"

    # Find min nonzero z as threshold (just below the smallest significant value)
    try:
        data = np.asanyarray(nib.load(str(zthresh_path)).dataobj)
        nonzero = data[data > 0]
        z_thr = float(nonzero.min()) - 0.01 if len(nonzero) > 0 else 0.01
    except Exception:
        z_thr = 0.01

    cmd = (
        f"fsl-cluster --in={zthresh_path} --thresh={z_thr:.4f}"
        f" --oindex={cluster_index} --olmax={lmax_file}"
        f" --minextent={min_voxels} --mm"
    )
    rc, stdout, stderr = _run_cmd(cmd, timeout=60)
    cluster_txt.write_text(stdout)

    if rc != 0:
        return ClusterResult(error=f"fsl-cluster failed: {stderr[:400]}")

    cluster_index_nii = Path(str(cluster_index) + ".nii.gz")

    table = parse_cluster_table(cluster_txt)
    # Rename 'MAX' → 'Peak Z' if not already renamed (zthresh output has MAX column)
    if "MAX" in table.columns and "Peak Z" not in table.columns:
        table = table.rename(columns={
            "MAX": "Peak Z",
            "MAX X (mm)": "X(mm)",
            "MAX Y (mm)": "Y(mm)",
            "MAX Z (mm)": "Z(mm)",
        })

    return ClusterResult(
        tables={"pos": table},
        cluster_img={"pos": cluster_index_nii if cluster_index_nii.exists() else None},
        params={"z_thr": z_thr, "min_voxels": min_voxels, "source": "lmm_zthresh"},
    )


# ──────────────────────────────────────────────────────────────────────────────
# TFCE cluster analysis (matching tfce-cluster.sh)
# ──────────────────────────────────────────────────────────────────────────────

def run_tfce_cluster(
    corrp_path: Path,
    tstat_path: Path,
    out_dir: Path,
    corrp_thr: float = 0.95,
    cluster_z_thr: float | None = None,
    k: int = 50,
) -> ClusterResult:
    """Run TFCE cluster analysis on a 1-p corrp map (matching tfce-cluster.sh).

    Works for both randomise TFCE corrp maps and parametric (LMM) corrp maps
    since both are stored as 1-p values (>0.95 → significant at p<0.05).
    """
    if not fsl_available():
        return ClusterResult(error="FSL not available")
    if corrp_path is None or not Path(corrp_path).exists():
        return ClusterResult(error=f"Corrp file not found: {corrp_path}")

    out_dir.mkdir(parents=True, exist_ok=True)

    corrp_mask = out_dir / "corrp_mask"
    tstat_thresh = out_dir / "tstat_thresh"
    cluster_index = out_dir / "cluster_index"
    lmax_file = out_dir / "lmax.txt"
    cluster_size = out_dir / "cluster_size"
    cluster_txt = out_dir / "tstat_cluster.txt"
    cluster_img_path = out_dir / "cluster_img"

    # Apply corrp threshold → binary mask
    rc, _, err = _run_cmd(
        f"fslmaths {corrp_path} -thr {corrp_thr} -bin {corrp_mask}"
    )
    if rc != 0:
        return ClusterResult(error=f"fslmaths corrp threshold failed: {err[:400]}")

    # Early-exit if corrp mask has 0 significant voxels
    corrp_mask_nii = Path(str(corrp_mask) + ".nii.gz")
    if corrp_mask_nii.exists():
        try:
            import nibabel as nib  # noqa: PLC0415
            import numpy as np  # noqa: PLC0415
            mask_data = np.asanyarray(nib.load(str(corrp_mask_nii)).dataobj)
            if mask_data.sum() == 0:
                # Write sentinel so _load_cluster_from_disk recognises "ran, no clusters"
                cluster_txt.write_text(
                    "Cluster Index\tVoxels\tMAX\tMAX X (mm)\tMAX Y (mm)\tMAX Z (mm)\t"
                    "COG X (mm)\tCOG Y (mm)\tCOG Z (mm)\n"
                )
                return ClusterResult(
                    tables={"pos": pd.DataFrame()},
                    cluster_img={"pos": None},
                    params={},
                )
        except Exception:
            pass

    # Mask tstat with surviving corrp voxels
    rc, _, err = _run_cmd(
        f"fslmaths {corrp_mask} -mul {tstat_path} {tstat_thresh}"
    )
    if rc != 0:
        return ClusterResult(error=f"fslmaths tstat masking failed: {err[:400]}")

    # Compute tstat range within significant voxels
    rc, fslstats_out, err = _run_cmd(
        f"fslstats {tstat_thresh} -k {corrp_mask} -R"
    )
    if rc != 0:
        return ClusterResult(error=f"fslstats failed: {err[:400]}")

    try:
        parts = fslstats_out.strip().split()
        tmin = float(parts[0])
        tmax = float(parts[1])
    except (ValueError, IndexError):
        return ClusterResult(
            error=f"Could not parse fslstats output: {fslstats_out!r}"
        )

    if cluster_z_thr is None or cluster_z_thr <= 0.0:
        cluster_z_thr = max(tmin, 0.01)

    # Run fsl-cluster (matching tfce-cluster.sh)
    # Note: no -p flag — requires --volume/--dlh for p-values which we don't need here
    cluster_cmd = (
        f"fsl-cluster --in={tstat_thresh} --thresh={cluster_z_thr}"
        f" --oindex={cluster_index} --olmax={lmax_file}"
        f" --osize={cluster_size} --mm --minextent={k}"
    )
    rc, stdout, stderr = _run_cmd(cluster_cmd, timeout=180)
    cluster_txt.write_text(stdout)
    if rc != 0:
        return ClusterResult(error=f"fsl-cluster failed: {stderr[:400]}")

    # Save masked cluster image (kept for reference but not returned as cluster_img)
    cluster_index_nii = Path(str(cluster_index) + ".nii.gz")
    if cluster_index_nii.exists():
        _run_cmd(f"fslmaths {tstat_thresh} -mas {cluster_index} {cluster_img_path}")

    table = parse_cluster_table(cluster_txt)

    return ClusterResult(
        tables={"pos": table},
        cluster_img={"pos": cluster_index_nii if cluster_index_nii.exists() else None},
        params={
            "corrp_thr": corrp_thr,
            "cluster_z_thr": cluster_z_thr,
            "k": k,
            "tmin": tmin,
            "tmax": tmax,
        },
    )
