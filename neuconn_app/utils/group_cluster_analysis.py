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
    """Query Harvard-Oxford atlases for anatomical label at MNI coordinate.

    Coordinates are rounded integers for cache efficiency.
    Returns: top region label or "Unknown"
    """
    coord_str = f"{x},{y},{z}"
    labels = []
    for atlas in [
        "Harvard-Oxford Cortical Structural Atlas",
        "Harvard-Oxford Subcortical Structural Atlas",
    ]:
        try:
            rc, out, _ = _run_cmd(
                ["atlasquery", "-a", atlas, "-c", coord_str], timeout=10
            )
            if rc == 0 and out.strip():
                # Parse: "<b>Atlas Name</b><br>42% Region Name, 13% Another Region"
                text = re.sub(r"<[^>]+>", "", out).strip()
                for part in text.split(","):
                    part = part.strip()
                    # Skip zero-percentage entries
                    if part and not re.match(r"^0%", part):
                        labels.append(part.strip())
                        break
        except Exception:
            pass
    return " / ".join(labels) if labels else "Unknown"


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

        # Build fsl-cluster command (matching cluster.sh)
        cluster_cmd = (
            f"fsl-cluster -i {thresh_file} -t {z_thr}"
            f" --othresh={thresh_file} -o {cluster_index}"
            f" --olmax={lmax_file} -p {p_thr}"
            f" -d {DLH}"
        )
        if RESELS is not None:
            cluster_cmd += f" -r {RESELS}"
        cluster_cmd += f" --volume={VOLUME} --minextent={k} --mm"

        rc, stdout, stderr = _run_cmd(cluster_cmd, timeout=180)
        cluster_txt.write_text(stdout)
        if rc != 0:
            return ClusterResult(
                error=f"fsl-cluster failed ({t}): {stderr[:400]}"
            )

        # Save masked cluster image
        cluster_index_nii = Path(str(cluster_index) + ".nii.gz")
        cluster_img_out: Path | None = None
        if cluster_index_nii.exists():
            _run_cmd(f"fslmaths {thresh_file} -mas {cluster_index} {cluster_img}")
            candidate = Path(str(cluster_img) + ".nii.gz")
            if candidate.exists():
                cluster_img_out = candidate
        cluster_imgs[t] = cluster_img_out
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
    min_voxels: int = 1,
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
        f"fsl-cluster -i {zthresh_path} -t {z_thr:.4f}"
        f" -o {cluster_index} --olmax={lmax_file}"
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
    cluster_cmd = (
        f"fsl-cluster -p 1 --in={tstat_thresh} --thresh={cluster_z_thr}"
        f" --oindex={cluster_index} --olmax={lmax_file}"
        f" --osize={cluster_size} --mm --minextent={k}"
    )
    rc, stdout, stderr = _run_cmd(cluster_cmd, timeout=180)
    cluster_txt.write_text(stdout)
    if rc != 0:
        return ClusterResult(error=f"fsl-cluster failed: {stderr[:400]}")

    # Save masked cluster image
    cluster_index_nii = Path(str(cluster_index) + ".nii.gz")
    cluster_img_out: Path | None = None
    if cluster_index_nii.exists():
        _run_cmd(f"fslmaths {tstat_thresh} -mas {cluster_index} {cluster_img_path}")
        candidate = Path(str(cluster_img_path) + ".nii.gz")
        if candidate.exists():
            cluster_img_out = candidate

    table = parse_cluster_table(cluster_txt)

    return ClusterResult(
        tables={"pos": table},
        cluster_img={"pos": cluster_img_out},
        params={
            "corrp_thr": corrp_thr,
            "cluster_z_thr": cluster_z_thr,
            "k": k,
            "tmin": tmin,
            "tmax": tmax,
        },
    )
