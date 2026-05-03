"""Download connectivity analysis results from HPC to local storage.

Uses rsync via SSH (same pattern as HPCWorkflowManager.download_results).
Filters to only the seeds/pipeline submitted in a given ConnectivitySubmission
to avoid downloading unrelated outputs.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional

try:
    from .hpc import HPCConfig
except ImportError:
    from hpc import HPCConfig


# Progress callback type: (label, status_msg, fraction 0–1)
ProgressCallback = Callable[[str, str, float], None]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ssh_opts(cfg: HPCConfig) -> List[str]:
    return ["-e", f"ssh -p {cfg.port} -o StrictHostKeyChecking=no -o BatchMode=yes"]


def _seed_dir_name(seed_token: str) -> str:
    """Convert a CLI seed token to the directory name used on disk.

    Examples:
      "atlas-4S256Parcels-LH_Cont_PFCl_3"  →  "atlas-4S256Parcels_parcel-LH_Cont_PFCl_3"
      "sphere-0_0_0_r6"                     →  "sphere-0_0_0_r6"
    """
    if seed_token.startswith("atlas-"):
        parts = seed_token.split("-", 2)          # ["atlas", "<atlas>", "<parcel>"]
        if len(parts) == 3:
            return f"atlas-{parts[1]}_parcel-{parts[2]}"
    return seed_token


# ---------------------------------------------------------------------------
# Subject-level seed connectivity download
# ---------------------------------------------------------------------------

def download_seed_results(
    submission_id: str,
    pipeline: str,
    seeds: List[str],
    subjects: List[str],
    hpc_config: HPCConfig,
    local_bids_root: Path,
    progress_callback: Optional[ProgressCallback] = None,
) -> Dict[str, bool]:
    """rsync seed connectivity results from HPC → local derivatives/.

    Only the seed directories matching *seeds* are transferred, avoiding
    a bulk download of all seed results on HPC.

    Returns a dict mapping subject_id → download_success.
    """
    local_bids_root = Path(local_bids_root)
    local_dest = local_bids_root / "derivatives" / "connectivity" / pipeline
    local_dest.mkdir(parents=True, exist_ok=True)

    remote_src = (
        f"{hpc_config.user}@{hpc_config.host}:"
        f"{hpc_config.remote_base}/derivatives/connectivity/{pipeline}/"
    )

    # Build per-seed --include patterns so we only pull the requested seeds
    seed_dirs = [_seed_dir_name(t) for t in seeds]
    include_patterns: List[str] = []
    for sd in seed_dirs:
        include_patterns += [
            f"--include=sub-*/",
            f"--include=sub-*/ses-*/",
            f"--include=sub-*/ses-*/seed/",
            f"--include=sub-*/ses-*/seed/{sd}/",
            f"--include=sub-*/ses-*/seed/{sd}/**",
        ]
    # Exclude everything else under seed/ and any other top-level dirs
    include_patterns += [
        "--include=sub-*/ses-*/seed/",   # keep seed dir itself
        "--exclude=sub-*/ses-*/seed/*",  # exclude other seed dirs
        "--exclude=sub-*/ses-*/*/",      # exclude non-seed subdirs
        "--exclude=*",
    ]

    results: Dict[str, bool] = {}
    total = max(len(subjects), 1)

    for idx, sub_id in enumerate(subjects):
        if progress_callback:
            progress_callback(sub_id, "Downloading…", idx / total)

        sub_filter = [f"--include={sub_id}/", f"--filter=+ {sub_id}/**"]
        cmd = (
            ["rsync", "-avz", "--progress"]
            + _ssh_opts(hpc_config)
            + [f"--include={sub_id}/"]
            + [f"--include={sub_id}/ses-*/"]
            + [f"--include={sub_id}/ses-*/seed/"]
        )
        for sd in seed_dirs:
            cmd += [
                f"--include={sub_id}/ses-*/seed/{sd}/",
                f"--include={sub_id}/ses-*/seed/{sd}/**",
            ]
        cmd += [
            f"--exclude={sub_id}/ses-*/seed/*",
            "--exclude=*",
            remote_src,
            str(local_dest) + "/",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3600,
            )
            success = result.returncode == 0
            results[sub_id] = success
            status = "✅ Done" if success else f"❌ rsync error: {result.stderr[:200]}"
        except subprocess.TimeoutExpired:
            results[sub_id] = False
            status = "❌ Timeout"
        except Exception as exc:
            results[sub_id] = False
            status = f"❌ Error: {exc}"

        if progress_callback:
            progress_callback(sub_id, status, (idx + 1) / total)

    return results


# ---------------------------------------------------------------------------
# Group-level results download
# ---------------------------------------------------------------------------

def download_group_results(
    pipeline: str,
    seeds: List[str],
    hpc_config: HPCConfig,
    local_bids_root: Path,
    progress_callback: Optional[ProgressCallback] = None,
) -> bool:
    """rsync group connectivity results from HPC → local derivatives/.

    Transfers derivatives/connectivity/{pipeline}/group/seed/{seed_dir}/ for
    each requested seed.

    Returns True on success.
    """
    local_bids_root = Path(local_bids_root)
    local_dest = local_bids_root / "derivatives" / "connectivity" / pipeline / "group" / "seed"
    local_dest.mkdir(parents=True, exist_ok=True)

    remote_group = (
        f"{hpc_config.user}@{hpc_config.host}:"
        f"{hpc_config.remote_base}/derivatives/connectivity/{pipeline}/group/seed/"
    )

    seed_dirs = [_seed_dir_name(t) for t in seeds]
    total = max(len(seed_dirs), 1)
    all_ok = True

    for idx, sd in enumerate(seed_dirs):
        if progress_callback:
            progress_callback(sd, "Downloading…", idx / total)

        cmd = (
            ["rsync", "-avz", "--progress"]
            + _ssh_opts(hpc_config)
            + [
                f"{remote_group}{sd}/",
                str(local_dest / sd) + "/",
            ]
        )

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=1800,
            )
            success = result.returncode == 0
            if not success:
                all_ok = False
            status = "✅ Done" if success else f"❌ rsync error: {result.stderr[:200]}"
        except subprocess.TimeoutExpired:
            all_ok = False
            status = "❌ Timeout"
        except Exception as exc:
            all_ok = False
            status = f"❌ Error: {exc}"

        if progress_callback:
            progress_callback(sd, status, (idx + 1) / total)

    return all_ok


# ---------------------------------------------------------------------------
# Rsync command preview (for UI display)
# ---------------------------------------------------------------------------

def build_seed_download_command(
    pipeline: str,
    seeds: List[str],
    subjects: List[str],
    hpc_config: HPCConfig,
    local_bids_root: Path,
) -> str:
    """Return a human-readable rsync command string for display."""
    seed_dirs = [_seed_dir_name(t) for t in seeds]
    include_args = " ".join(
        f"--include='{s}/ses-*/seed/{sd}/**'" for s in subjects[:3] for sd in seed_dirs
    )
    ellipsis = " ..." if len(subjects) > 3 else ""
    remote = (
        f"{hpc_config.user}@{hpc_config.host}:"
        f"{hpc_config.remote_base}/derivatives/connectivity/{pipeline}/"
    )
    local = str(local_bids_root / "derivatives" / "connectivity" / pipeline) + "/"
    return (
        f"rsync -avz --progress -e 'ssh -p {hpc_config.port}'\\\n"
        f"  {include_args}{ellipsis}\\\n"
        f"  --exclude='*'\\\n"
        f"  {remote}\\\n"
        f"  {local}"
    )


def build_group_download_command(
    pipeline: str,
    seeds: List[str],
    hpc_config: HPCConfig,
    local_bids_root: Path,
) -> str:
    """Return a human-readable rsync command string for group download display."""
    seed_dirs = [_seed_dir_name(t) for t in seeds]
    remote_base = (
        f"{hpc_config.user}@{hpc_config.host}:"
        f"{hpc_config.remote_base}/derivatives/connectivity/{pipeline}/group/seed/"
    )
    local_base = str(local_bids_root / "derivatives" / "connectivity" / pipeline / "group" / "seed")
    cmds = []
    for sd in seed_dirs:
        cmds.append(
            f"rsync -avz -e 'ssh -p {hpc_config.port}' "
            f"{remote_base}{sd}/ {local_base}/{sd}/"
        )
    return "\n".join(cmds)
