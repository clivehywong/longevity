"""Submit seed-based connectivity analyses (XCP-D backend).

Two run targets are supported:

* **Local**  — serial subprocess execution (no parallelism), driven by
  ``utils/local_connectivity_runner.LocalConnectivityRunner``.  Suitable for
  testing the pipeline on the local workstation.
* **HPC**    — submits a SLURM job via ``ConnectivityWorkflowManager`` (legacy
  CLI path through ``hpc_submit_subject_level.py``).  Optionally re-uploads
  cleaned XCP-D inputs first.

Scripts are sourced from ``neuconn_app/scripts/connectivity/`` (symlinks to
``script/``) so the app remains self-contained.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal, NamedTuple

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.config import load_config
from utils.connectivity_workflow import ConnectivityWorkflowManager
from utils.local_connectivity_runner import LocalConnectivityRunner
from utils.seed_catalog import Seed, SeedCatalog
from utils.seed_viz import make_seed_preview_png
from utils.xcpd_outputs import XcpdDiscovery, KNOWN_PIPELINES

# Import MEASURES names from the app-resident scripts directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "connectivity"))
try:
    from connectivity_measures import MEASURES as _MEASURES_REGISTRY
    ALL_MEASURES = list(_MEASURES_REGISTRY.keys())
except Exception:
    ALL_MEASURES = [
        "pearson", "spearman", "partial_correlation",
        "plv", "wpli", "coherence",
        "amplitude_envelope_correlation", "mutual_information",
    ]

STATE_PREFIX = "submit_seed_"

# ---------------------------------------------------------------------------
# Static-file manifest for HPC sync
# ---------------------------------------------------------------------------

# (display_name, local_path_relative_to_project_root, remote_path_relative_to_remote_base)
STATIC_FILE_MANIFEST: list[tuple[str, str, str]] = [
    (
        "Brain mask (HPC)",
        "atlases/MNI152_T1_2mm_brain_mask_dil.nii.gz",
        "atlases/MNI152_T1_2mm_brain_mask_dil.nii.gz",
    ),
    (
        "Compute script (HPC)",
        "script/compute_seed_connectivity_xcpd.py",
        "script/compute_seed_connectivity_xcpd.py",
    ),
    (
        "Connectivity measures (HPC)",
        "script/connectivity_measures.py",
        "script/connectivity_measures.py",
    ),
    (
        "Submit script (HPC)",
        "script/hpc_submit_subject_level.py",
        "script/hpc_submit_subject_level.py",
    ),
    (
        "XCP-D outputs util (HPC)",
        "neuconn_app/utils/xcpd_outputs.py",
        "neuconn_app/utils/xcpd_outputs.py",
    ),
    (
        "Seed catalog util (HPC)",
        "neuconn_app/utils/seed_catalog.py",
        "neuconn_app/utils/seed_catalog.py",
    ),
]

# ---------------------------------------------------------------------------
# Pre-flight check infrastructure
# ---------------------------------------------------------------------------

_PREFLIGHT_ICON: dict[str, str] = {
    "pass": "✅",
    "fail": "❌",
    "warn": "⚠️",
    "skip": "⏭️",
}


class PreflightResult(NamedTuple):
    name: str
    status: str  # "pass" | "fail" | "warn" | "skip"
    detail: str


def _run_local_preflight(
    bids_root: str, pipeline: str, subjects: list[str]
) -> list[PreflightResult]:
    """Checks that don't require an SSH connection."""
    results: list[PreflightResult] = []
    root = Path(bids_root)

    mask_path = root / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz"
    if mask_path.exists():
        results.append(PreflightResult("Brain mask (local)", "pass", str(mask_path)))
    else:
        results.append(PreflightResult(
            "Brain mask (local)", "fail",
            f"Not found: {mask_path}. "
            "Download from FSL or regenerate with fslmaths."
        ))

    script_path = root / "script" / "compute_seed_connectivity_xcpd.py"
    if script_path.exists():
        results.append(PreflightResult("Compute script (local)", "pass", str(script_path)))
    else:
        results.append(PreflightResult(
            "Compute script (local)", "warn",
            f"Not found locally — HPC copy will be used: {script_path}"
        ))

    xcpd_dir = root / "derivatives" / "preprocessing" / "xcpd" / pipeline
    if not xcpd_dir.exists():
        results.append(PreflightResult(
            f"XCP-D outputs ({pipeline})", "fail",
            f"Pipeline directory not found: {xcpd_dir}"
        ))
    else:
        missing = [s for s in subjects if not (xcpd_dir / s).exists()]
        if not missing:
            results.append(PreflightResult(
                f"XCP-D outputs ({pipeline})", "pass",
                f"All {len(subjects)} subject(s) found under {xcpd_dir}"
            ))
        elif len(missing) == len(subjects):
            results.append(PreflightResult(
                f"XCP-D outputs ({pipeline})", "fail",
                f"No subjects found in {xcpd_dir}"
            ))
        else:
            sample = ", ".join(missing[:5]) + ("…" if len(missing) > 5 else "")
            results.append(PreflightResult(
                f"XCP-D outputs ({pipeline})", "warn",
                f"{len(missing)}/{len(subjects)} subjects missing locally: {sample}"
            ))

    return results


def _run_hpc_preflight(
    bids_root: str, pipeline: str, subjects: list[str], config: dict
) -> tuple[list[PreflightResult], list[str]]:
    """HPC-specific checks via SSH.

    Returns (results, missing_xcpd_subjects) where missing_xcpd_subjects is the
    list of subjects that have no atlas timeseries TSV data on HPC.
    """
    results: list[PreflightResult] = []
    missing_xcpd: list[str] = []

    try:
        from utils.hpc import HPCConfig, HPCConnection  # noqa: PLC0415
        hpc_cfg = HPCConfig.from_config(config)
    except Exception as exc:
        return [PreflightResult("HPC config", "fail", f"Could not load HPC config: {exc}")], []

    if not hpc_cfg.host or not hpc_cfg.user:
        return [PreflightResult(
            "HPC config", "fail",
            "host or user not set — check longevity_config.yaml hpc section"
        )], []
    results.append(PreflightResult("HPC config", "pass", f"{hpc_cfg.user}@{hpc_cfg.host}"))

    remote_base = hpc_cfg.remote_base
    if not remote_base:
        return results + [PreflightResult(
            "HPC remote base", "fail",
            "remote_paths.base not configured"
        )], []

    conn = HPCConnection(hpc_cfg)
    try:
        conn.connect()
    except Exception as exc:
        results.append(PreflightResult("SSH connection", "fail", str(exc)))
        return results, []
    results.append(PreflightResult("SSH connection", "pass", f"Connected to {hpc_cfg.host}"))

    file_checks = [(name, f"{remote_base}/{remote_rel}")
                   for name, _local, remote_rel in STATIC_FILE_MANIFEST]
    for name, remote_path in file_checks:
        try:
            stdout, _, rc = conn.execute(
                f"test -f {remote_path} && echo OK", timeout=15
            )
            if rc == 0 and "OK" in stdout:
                results.append(PreflightResult(name, "pass", remote_path))
            else:
                results.append(PreflightResult(name, "fail",
                                               f"Not found on HPC: {remote_path}"))
        except Exception as exc:
            results.append(PreflightResult(name, "fail", str(exc)))

    xcpd_dir = f"{remote_base}/derivatives/preprocessing/xcpd/{pipeline}"
    try:
        stdout, _, rc = conn.execute(
            f"test -d {xcpd_dir} && ls {xcpd_dir} | wc -l", timeout=15
        )
        if rc == 0:
            count = stdout.strip().splitlines()[-1].strip()
            results.append(PreflightResult(
                f"XCP-D outputs ({pipeline}) on HPC", "pass",
                f"{xcpd_dir} ({count} entries)"
            ))
        else:
            results.append(PreflightResult(
                f"XCP-D outputs ({pipeline}) on HPC", "fail",
                f"Directory not found on HPC: {xcpd_dir}"
            ))
    except Exception as exc:
        results.append(PreflightResult(f"XCP-D outputs ({pipeline}) on HPC", "fail", str(exc)))

    # ── Per-subject XCP-D atlas timeseries check ──────────────────────────
    # Run a single batch SSH command that counts TSV files per subject in func/
    # dirs, so we can identify subjects missing data without N round-trips.
    if subjects:
        subs_arg = " ".join(subjects)
        batch_cmd = (
            f"for s in {subs_arg}; do "
            f"  n=$(find {xcpd_dir}/$s -maxdepth 3 -name '*.tsv' -path '*/func/*' "
            f"      2>/dev/null | wc -l); "
            f"  echo $s:$n; "
            f"done"
        )
        try:
            stdout, _, rc = conn.execute(batch_cmd, timeout=60)
            counts: dict[str, int] = {}
            for line in stdout.strip().splitlines():
                line = line.strip()
                if ":" in line:
                    sub, n = line.rsplit(":", 1)
                    try:
                        counts[sub.strip()] = int(n.strip())
                    except ValueError:
                        pass
            missing_xcpd = [s for s in subjects if counts.get(s, 0) == 0]
            has_data = len(subjects) - len(missing_xcpd)
            if not missing_xcpd:
                results.append(PreflightResult(
                    "XCP-D atlas timeseries on HPC",
                    "pass",
                    f"All {has_data} subject(s) have atlas TSV data on HPC"
                ))
            else:
                sample = ", ".join(missing_xcpd[:5]) + ("…" if len(missing_xcpd) > 5 else "")
                results.append(PreflightResult(
                    "XCP-D atlas timeseries on HPC",
                    "warn",
                    f"{len(missing_xcpd)}/{len(subjects)} subjects lack atlas TSVs on HPC: "
                    f"{sample} — upload their XCP-D data before submitting"
                ))
        except Exception as exc:
            results.append(PreflightResult(
                "XCP-D atlas timeseries on HPC", "warn",
                f"Could not check per-subject TSV data: {exc}"
            ))

    try:
        conn.disconnect()
    except Exception:
        pass

    return results, missing_xcpd


# ---------------------------------------------------------------------------
# HPC static-file upload
# ---------------------------------------------------------------------------


class UploadResult(NamedTuple):
    name: str
    status: str   # "ok" | "skip" | "error"
    detail: str


def _upload_static_files_to_hpc(
    project_root: str, config: dict
) -> list[UploadResult]:
    """Upload / overwrite all static analysis files to HPC via SFTP.

    Always overwrites (not just missing) so local edits propagate to HPC.
    Validates all local files exist before connecting.  Returns per-file results.
    """
    from utils.hpc import HPCConfig, HPCConnection  # noqa: PLC0415

    root = Path(project_root)
    results: list[UploadResult] = []

    # ── Validate all local files before connecting ────────────────────────
    for name, local_rel, _ in STATIC_FILE_MANIFEST:
        local = root / local_rel
        if not local.exists():
            results.append(UploadResult(name, "error", f"Local file not found: {local}"))
    if any(r.status == "error" for r in results):
        return results

    hpc_cfg = HPCConfig.from_config(config)
    conn = HPCConnection(hpc_cfg)
    try:
        conn.connect()
        for name, local_rel, remote_rel in STATIC_FILE_MANIFEST:
            local = root / local_rel
            remote = f"{hpc_cfg.remote_base}/{remote_rel}"
            try:
                conn.mkdir_p(str(Path(remote).parent))
                conn.sftp.put(str(local), remote)
                results.append(UploadResult(name, "ok", remote))
            except Exception as exc:
                results.append(UploadResult(name, "error", str(exc)))
    finally:
        try:
            conn.disconnect()
        except Exception:
            pass

    return results


def _upload_xcpd_subjects_to_hpc(
    subjects: list[str], pipeline: str, bids_root: str, config: dict
) -> list[UploadResult]:
    """Rsync XCP-D derivatives for *subjects* from local to HPC.

    Uploads the full ``derivatives/preprocessing/xcpd/<pipeline>/<subject>/``
    tree for each subject that is missing on HPC.  Uses a single rsync process
    per subject so progress is easy to track.
    """
    from utils.hpc import HPCConfig  # noqa: PLC0415

    hpc_cfg = HPCConfig.from_config(config)
    root = Path(bids_root)
    results: list[UploadResult] = []

    ssh_opts = (
        f"ssh -p {hpc_cfg.port}"
        " -o StrictHostKeyChecking=no"
        " -o ServerAliveInterval=60"
        " -o ServerAliveCountMax=10"
    )
    remote_xcpd = (
        f"{hpc_cfg.user}@{hpc_cfg.host}:"
        f"{hpc_cfg.remote_base}/derivatives/preprocessing/xcpd/{pipeline}"
    )

    for subject in subjects:
        local_xcpd = root / "derivatives" / "preprocessing" / "xcpd" / pipeline / subject
        if not local_xcpd.exists():
            results.append(UploadResult(
                subject, "error", f"Local XCP-D directory not found: {local_xcpd}"
            ))
            continue

        cmd = [
            "rsync", "-avz", "--mkpath",
            "-e", ssh_opts,
            f"{local_xcpd}/",
            f"{remote_xcpd}/{subject}/",
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
            if proc.returncode == 0:
                results.append(UploadResult(subject, "ok", f"→ {remote_xcpd}/{subject}/"))
            else:
                results.append(UploadResult(
                    subject, "error",
                    proc.stderr.strip()[:300] or proc.stdout.strip()[:300]
                ))
        except subprocess.TimeoutExpired:
            results.append(UploadResult(subject, "error", "Timeout after 10 min"))
        except Exception as exc:
            results.append(UploadResult(subject, "error", str(exc)))

    return results


def _render_preflight_section(
    bids_root: str,
    pipeline: str,
    subjects: list[str],
    is_local: bool,
    config: dict,
) -> bool:
    """Render the pre-flight checks UI.

    Returns True if all critical checks passed (safe to submit).
    For HPC mode, returns False until at least one preflight has been run and passed.
    """
    st.subheader("🔍 Pre-flight Checks")

    static_check_names = {name for name, _, _ in STATIC_FILE_MANIFEST}

    cached: list[dict] | None = st.session_state.get(f"{STATE_PREFIX}preflight_results")
    cached_pipeline = st.session_state.get(f"{STATE_PREFIX}preflight_pipeline")
    cached_mode = st.session_state.get(f"{STATE_PREFIX}preflight_is_local")

    if cached and (cached_pipeline != pipeline or cached_mode != is_local):
        cached = None
        st.session_state[f"{STATE_PREFIX}preflight_results"] = None
        st.info("Settings changed — please re-run pre-flight checks.")

    def _run_and_store() -> list[dict]:
        raw = _run_local_preflight(bids_root, pipeline, subjects)
        missing_xcpd: list[str] = []
        if not is_local:
            hpc_results, missing_xcpd = _run_hpc_preflight(bids_root, pipeline, subjects, config)
            raw += hpc_results
        result = [{"name": r.name, "status": r.status, "detail": r.detail} for r in raw]
        st.session_state[f"{STATE_PREFIX}preflight_results"] = result
        st.session_state[f"{STATE_PREFIX}preflight_pipeline"] = pipeline
        st.session_state[f"{STATE_PREFIX}preflight_is_local"] = is_local
        st.session_state[f"{STATE_PREFIX}hpc_missing_xcpd"] = missing_xcpd
        return result

    if st.button("Run pre-flight checks", key=f"{STATE_PREFIX}preflight_btn"):
        with st.spinner("Running checks…"):
            cached = _run_and_store()

    if cached is None:
        st.caption("Click **Run pre-flight checks** to verify required files before submitting.")
        # Block HPC submission until checks have been run at least once
        return is_local

    n_fail = sum(1 for r in cached if r["status"] == "fail")
    n_warn = sum(1 for r in cached if r["status"] == "warn")
    n_pass = sum(1 for r in cached if r["status"] == "pass")

    for r in cached:
        icon = _PREFLIGHT_ICON.get(r["status"], "❓")
        st.markdown(f"{icon} **{r['name']}** — {r['detail']}")

    if n_fail == 0:
        warn_note = f", {n_warn} warning(s)" if n_warn else ""
        st.success(f"All critical checks passed ({n_pass} passed{warn_note}).")
    else:
        st.error(f"{n_fail} critical check(s) failed — resolve before submitting.")

    # ── Upload static files section (HPC mode only) ───────────────────────
    if not is_local:
        has_static_failures = any(
            r["status"] == "fail" and r["name"] in static_check_names
            for r in cached
        )
        with st.expander(
            "📤 Upload / sync static files to HPC"
            + (" ← fix required" if has_static_failures else ""),
            expanded=has_static_failures,
        ):
            st.caption(
                "Uploads the brain mask, compute script, connectivity measures, and submit "
                "script from local to HPC. Always overwrites so local edits propagate."
            )
            for name, local_rel, _ in STATIC_FILE_MANIFEST:
                local_path = Path(bids_root) / local_rel
                icon = "✅" if local_path.exists() else "❌"
                st.caption(f"{icon} `{local_rel}`")

            if st.button(
                "Upload static files to HPC",
                key=f"{STATE_PREFIX}upload_static_btn",
                type="primary" if has_static_failures else "secondary",
            ):
                with st.spinner("Uploading static files to HPC…"):
                    upload_results = _upload_static_files_to_hpc(bids_root, config)
                n_ok = sum(1 for r in upload_results if r.status == "ok")
                n_err = sum(1 for r in upload_results if r.status == "error")
                for r in upload_results:
                    if r.status == "ok":
                        st.success(f"✅ {r.name} — uploaded")
                    else:
                        st.error(f"❌ {r.name} — {r.detail}")
                if n_err == 0:
                    st.success(f"All {n_ok} files uploaded. Re-running pre-flight checks…")
                    with st.spinner("Re-checking…"):
                        cached = _run_and_store()
                    st.rerun()
                else:
                    st.error(f"{n_err} file(s) failed to upload — check errors above.")

        # ── Upload missing XCP-D subject data (HPC mode only) ────────────
        missing_xcpd: list[str] = st.session_state.get(f"{STATE_PREFIX}hpc_missing_xcpd", [])
        if missing_xcpd:
            with st.expander(
                f"📤 Upload missing XCP-D data to HPC ({len(missing_xcpd)} subjects) ← required",
                expanded=True,
            ):
                st.caption(
                    "The following subjects have no atlas timeseries TSV data on HPC. "
                    "Upload their local XCP-D derivatives so the SLURM job can process them."
                )
                root = Path(bids_root)
                local_xcpd_base = root / "derivatives" / "preprocessing" / "xcpd" / pipeline
                rows = []
                for sub in missing_xcpd:
                    local_path = local_xcpd_base / sub
                    has_local = local_path.exists() and any(local_path.rglob("*.tsv"))
                    rows.append(
                        f"{'✅' if has_local else '❌'} **{sub}** — "
                        f"{'local data available' if has_local else 'no local XCP-D data either'}"
                    )
                st.markdown("\n\n".join(rows))

                uploadable = [
                    s for s in missing_xcpd
                    if (local_xcpd_base / s).exists()
                    and any((local_xcpd_base / s).rglob("*.tsv"))
                ]
                if not uploadable:
                    st.warning(
                        "None of the missing subjects have local XCP-D data to upload. "
                        "Run XCP-D locally first, then return here."
                    )
                else:
                    if st.button(
                        f"📤 Upload {len(uploadable)} subject(s) to HPC",
                        key=f"{STATE_PREFIX}upload_xcpd_btn",
                        type="primary",
                    ):
                        progress = st.progress(0.0, text="Starting upload…")
                        upload_results = []
                        for i, sub in enumerate(uploadable):
                            progress.progress(
                                i / len(uploadable), text=f"Uploading {sub}…"
                            )
                            res = _upload_xcpd_subjects_to_hpc(
                                [sub], pipeline, bids_root, config
                            )
                            upload_results.extend(res)
                        progress.progress(1.0, text="Done")
                        n_ok = sum(1 for r in upload_results if r.status == "ok")
                        n_err = sum(1 for r in upload_results if r.status == "error")
                        for r in upload_results:
                            if r.status == "ok":
                                st.success(f"✅ {r.name} — {r.detail}")
                            else:
                                st.error(f"❌ {r.name} — {r.detail}")
                        if n_err == 0:
                            st.success(
                                f"Uploaded {n_ok} subject(s). Re-running pre-flight checks…"
                            )
                            with st.spinner("Re-checking…"):
                                cached = _run_and_store()
                            st.rerun()
                        else:
                            st.error(f"{n_err} subject(s) failed — check errors above.")

    return n_fail == 0


@st.cache_data(ttl=60, show_spinner=False)
def _discover_subjects_sessions(bids_root: str, pipeline: str) -> dict[str, list[str]]:
    disc = XcpdDiscovery(Path(bids_root), pipeline=pipeline)
    result: dict[str, list[str]] = {}
    for sub in disc.list_subjects(pipeline):
        sessions = disc.list_sessions(sub, pipeline)
        if sessions:
            result[sub] = sessions
    return result


def _get_config() -> dict:
    return st.session_state.get("config") or load_config()


def _seed_to_cli_token(seed: Seed) -> str:
    """Convert a Seed object to its CLI --seed argument value."""
    if seed.source == "xcpd_atlas_parcel":
        return f"atlas-{seed.atlas}:{seed.parcel_label}"
    if seed.source == "custom_nifti_roi":
        return f"nifti:{seed.nifti_path or seed.id},name={seed.name}"
    if seed.source == "sphere":
        x, y, z = seed.coords_mm or (0, 0, 0)
        r = seed.radius_mm or 6.0
        return f"sphere:{x},{y},{z},r={r},name={seed.name}"
    return seed.id


@st.cache_data(show_spinner=False, ttl=3600)
def _make_seed_preview_png(token: str, bids_root_str: str) -> bytes | None:
    """Cached wrapper around shared make_seed_preview_png utility."""
    return make_seed_preview_png(token, bids_root_str)


def _render_seed_builder(catalog: SeedCatalog | None, bids_root: Path) -> None:
    """Render the seed builder UI and populate session_state seeds list."""
    seeds: list[dict[str, Any]] = st.session_state.get(f"{STATE_PREFIX}seeds", [])

    st.subheader("🌱 Seed Builder")
    source = st.radio(
        "Seed source",
        ["Atlas parcel", "Custom NIfTI ROI", "Sphere from coordinates"],
        horizontal=True,
        key=f"{STATE_PREFIX}source",
    )

    new_seed: Seed | None = None

    if source == "Atlas parcel":
        if catalog is None:
            st.warning("No seed catalog available (XCP-D outputs not found).")
        else:
            atlases = catalog.list_atlases()
            if not atlases:
                st.warning("No atlas parcels discovered.")
            else:
                col_a, col_b = st.columns(2)
                with col_a:
                    atlas = st.selectbox("Atlas", atlases, key=f"{STATE_PREFIX}atlas_sel")
                with col_b:
                    networks = ["(all)"] + catalog.list_networks(atlas)
                    net_sel = st.selectbox("Network filter", networks, key=f"{STATE_PREFIX}net_sel")
                kw: dict[str, Any] = {"atlas": atlas}
                if net_sel != "(all)":
                    kw["network"] = net_sel
                parcel_seeds = catalog.get_seeds(source="xcpd_atlas_parcel", **kw)
                parcel_opts = [f"{s.parcel_label} ({s.id})" for s in parcel_seeds]
                seed_map = {f"{s.parcel_label} ({s.id})": s for s in parcel_seeds}
                chosen = st.multiselect(
                    "Parcels (searchable)", parcel_opts,
                    key=f"{STATE_PREFIX}parcel_multi"
                )
                if chosen and st.button("➕ Add selected parcels", key=f"{STATE_PREFIX}add_parcel"):
                    for label in chosen:
                        s = seed_map[label]
                        token = _seed_to_cli_token(s)
                        if not any(sd["token"] == token for sd in seeds):
                            seeds.append({"name": s.name, "token": token})
                    st.session_state[f"{STATE_PREFIX}seeds"] = seeds
                    st.rerun()

    elif source == "Custom NIfTI ROI":
        nifti_path = st.text_input(
            "NIfTI ROI path", placeholder="/path/to/roi.nii.gz",
            key=f"{STATE_PREFIX}nifti_path"
        )
        roi_name = st.text_input("Name", key=f"{STATE_PREFIX}nifti_name")
        if st.button("➕ Add NIfTI ROI", key=f"{STATE_PREFIX}add_nifti"):
            if nifti_path:
                token = nifti_path
                name = roi_name or Path(nifti_path).stem
                if not any(sd["token"] == token for sd in seeds):
                    seeds.append({"name": name, "token": token})
                st.session_state[f"{STATE_PREFIX}seeds"] = seeds
                st.rerun()
            else:
                st.warning("Please enter a NIfTI path.")

    else:  # Sphere
        c1, c2, c3, c4 = st.columns(4)
        x = c1.number_input("x (mm)", value=0.0, step=1.0, key=f"{STATE_PREFIX}sph_x")
        y = c2.number_input("y (mm)", value=0.0, step=1.0, key=f"{STATE_PREFIX}sph_y")
        z = c3.number_input("z (mm)", value=0.0, step=1.0, key=f"{STATE_PREFIX}sph_z")
        r = c4.number_input("radius (mm)", value=6.0, step=1.0, min_value=1.0, key=f"{STATE_PREFIX}sph_r")
        sph_name = st.text_input("Sphere name", key=f"{STATE_PREFIX}sph_name")
        if st.button("➕ Add sphere", key=f"{STATE_PREFIX}add_sphere"):
            if sph_name:
                s = Seed.sphere(sph_name, x, y, z, r)
                token = _seed_to_cli_token(s)
                if not any(sd["token"] == token for sd in seeds):
                    seeds.append({"name": s.name, "token": token})
                st.session_state[f"{STATE_PREFIX}seeds"] = seeds
                st.rerun()
            else:
                st.warning("Please enter a sphere name.")

    # Show current seed list
    if seeds:
        st.markdown("**Selected seeds:**")
        for i, sd in enumerate(seeds):
            col_l, col_r = st.columns([5, 1])
            col_l.markdown(f"- `{sd['name']}` — `{sd['token']}`")
            if col_r.button("✖", key=f"{STATE_PREFIX}rm_{i}"):
                seeds.pop(i)
                st.session_state[f"{STATE_PREFIX}seeds"] = seeds
                st.rerun()

        # ── Seed preview ───────────────────────────────────────────────────
        with st.expander("🔍 Preview seed on MNI template", expanded=False):
            seed_names = [sd["name"] for sd in seeds]
            sel_name = st.selectbox(
                "Seed to preview",
                seed_names,
                key=f"{STATE_PREFIX}preview_sel",
            )
            token = next(sd["token"] for sd in seeds if sd["name"] == sel_name)
            with st.spinner("Rendering…"):
                png = _make_seed_preview_png(token, str(bids_root))
            if png:
                st.image(png, use_container_width=True)
                st.caption(
                    "Seed ROI (orange) on MNI152 2mm template — orthographic slices "
                    "centred on seed. Click **✖** in the seed list to remove."
                )
            else:
                st.warning(
                    "Could not render preview — atlas dseg file not found locally "
                    "and no nilearn fallback available for this atlas. "
                    "Atlas parcels supported: project atlases and 4S-series (Schaefer-based)."
                )
    else:
        st.info("No seeds added yet.")



# ---------------------------------------------------------------------------
# Status badge mapping (shared across tabs)
# ---------------------------------------------------------------------------

_STATUS_BADGE: dict[str, str] = {
    "submitted": "⏳ Pending",
    "running": "🔄 Running",
    "completed": "✅ Completed",
    "failed": "❌ Failed",
    "cancelled": "🚫 Cancelled",
}


def _make_progress_callback(progress_bar, status_text):
    def callback(label: str, msg: str, frac: float) -> None:
        progress_bar.progress(min(frac, 1.0), text=f"{label}: {msg}")
        status_text.text(msg)
    return callback


def _render_monitor_tab(config: dict, bids_root: Any) -> None:
    """Monitor seed connectivity HPC submissions."""
    manager = ConnectivityWorkflowManager(config)
    all_subs = [s for s in manager.list_submissions() if s.analysis_type == "seed_connectivity"]

    col_refresh, col_filter = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 Refresh All", key="monitor_seed_refresh_all"):
            for sub in all_subs:
                if sub.status not in {"completed", "failed", "cancelled"}:
                    try:
                        manager.refresh_status(sub.submission_id)
                    except Exception:
                        pass
            st.rerun()
    with col_filter:
        filter_val = st.selectbox(
            "Filter by status",
            ["All", "Pending", "Running", "Completed", "Failed"],
            key="monitor_seed_filter",
        )

    if not all_subs:
        st.info("No seed connectivity submissions yet. Submit a job in the ⚙️ Submit tab.")
        return

    filter_map = {
        "Pending": "submitted",
        "Running": "running",
        "Completed": "completed",
        "Failed": "failed",
    }
    filtered = all_subs if filter_val == "All" else [
        s for s in all_subs if s.status == filter_map.get(filter_val, "")
    ]

    if not filtered:
        st.info(f"No submissions with status: {filter_val}")
        return

    for sub in sorted(filtered, key=lambda s: s.submitted_at, reverse=True):
        with st.container(border=True):
            badge = _STATUS_BADGE.get(sub.status, sub.status)
            col1, col2 = st.columns([3, 1])
            with col1:
                st.markdown(f"**Job ID:** `{sub.job_id or '—'}` &nbsp; {badge}")
                st.caption(f"Submitted: {sub.submitted_at} | ID: `{sub.submission_id}`")
                pipeline_opt = sub.options.get("pipeline", "—")
                seeds_opt = sub.options.get("seeds", [])
                seeds_str = ", ".join(str(s) for s in seeds_opt[:3])
                if len(seeds_opt) > 3:
                    seeds_str += f" (+{len(seeds_opt) - 3} more)"
                st.caption(
                    f"Pipeline: `{pipeline_opt}` | Seeds: {seeds_str or '—'} "
                    f"| Subjects: {len(sub.subjects)}"
                )
            with col2:
                if st.button("🔁 Refresh", key=f"refresh_{sub.submission_id}"):
                    try:
                        manager.refresh_status(sub.submission_id)
                    except Exception as exc:
                        st.error(f"Refresh failed: {exc}")
                    st.rerun()
                if sub.status in {"submitted", "running"}:
                    if st.button("🚫 Cancel", key=f"cancel_{sub.submission_id}"):
                        try:
                            manager.cancel(sub.submission_id)
                        except Exception as exc:
                            st.error(f"Cancel failed: {exc}")
                        st.rerun()


def _scan_hpc_connectivity(config: dict, pipeline: str, bids_root: Path) -> dict:
    """SSH to HPC and find connectivity zmaps.

    Actual remote structure:
      {remote_base}/derivatives/connectivity/{pipeline}/sub-{ID}/ses-{N}/seed/{seed_dir}/*_zmap.nii.gz

    Returns dict:
    {
      seed_dir: {
        "remote_subjects": [(sub_id, ses_id, remote_zmap_path), ...],
        "local_missing": [(sub_id, ses_id), ...]   # on HPC but not local
      }
    }
    """
    from utils.hpc import HPCConfig, HPCConnection  # noqa: PLC0415

    hpc_cfg = HPCConfig.from_config(config)
    conn = HPCConnection(hpc_cfg)
    conn.connect()
    try:
        remote_dir = f"{hpc_cfg.remote_base}/derivatives/connectivity/{pipeline}"
        cmd = f"find {remote_dir} -name '*_zmap.nii.gz' -type f 2>/dev/null"
        stdout, _stderr, _exit_code = conn.execute(cmd, timeout=120)
    finally:
        conn.disconnect()

    results: dict = {}
    for line in stdout.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Remote path: …/connectivity/{pipeline}/sub-{ID}/ses-{N}/seed/{seed_dir}/…_zmap.nii.gz
        try:
            parts = Path(line).parts
            conn_idx = parts.index("connectivity")
        except ValueError:
            continue
        # Need at least: connectivity / pipeline / sub-* / ses-* / seed / seed_dir / file
        if len(parts) < conn_idx + 7:
            continue
        path_pipeline = parts[conn_idx + 1]
        if path_pipeline != pipeline:
            continue
        sub_id  = parts[conn_idx + 2]
        ses_id  = parts[conn_idx + 3]
        # parts[conn_idx + 4] == "seed"
        seed_dir = parts[conn_idx + 5]
        if not sub_id.startswith("sub-") or not ses_id.startswith("ses-"):
            continue

        if seed_dir not in results:
            results[seed_dir] = {"remote_subjects": [], "local_missing": []}
        results[seed_dir]["remote_subjects"].append((sub_id, ses_id, line))

        local_ses = (
            bids_root / "derivatives" / "connectivity" / pipeline
            / sub_id / ses_id / "seed" / seed_dir
        )
        if not list(local_ses.glob("*_zmap.nii.gz")):
            results[seed_dir]["local_missing"].append((sub_id, ses_id))

    return results


def _download_seed_scan_results(
    config: dict,
    pipeline: str,
    seed_dir: str,
    bids_root: Path,
    progress: Any,
) -> None:
    """rsync all subjects/sessions for a discovered seed_dir from HPC to local.

    Remote structure: {remote_base}/derivatives/connectivity/{pipeline}/sub-*/ses-*/seed/{seed_dir}/
    Local  structure: {bids_root}/derivatives/connectivity/{pipeline}/sub-*/ses-*/seed/{seed_dir}/
    """
    from utils.hpc import HPCConfig  # noqa: PLC0415

    hpc_cfg = HPCConfig.from_config(config)
    local_dest = bids_root / "derivatives" / "connectivity" / pipeline
    local_dest.mkdir(parents=True, exist_ok=True)

    remote_src = f"{hpc_cfg.user}@{hpc_cfg.host}:{hpc_cfg.remote_base}/derivatives/connectivity/{pipeline}/"
    ssh_opts = f"ssh -p {hpc_cfg.port} -o StrictHostKeyChecking=no -o BatchMode=yes"
    # rsync include/exclude to transfer only the requested seed across all sub-/ses- dirs
    cmd = [
        "rsync", "-az", "--progress",
        "-e", ssh_opts,
        "--include=sub-*/",
        "--include=sub-*/ses-*/",
        "--include=sub-*/ses-*/seed/",
        f"--include=sub-*/ses-*/seed/{seed_dir}/",
        f"--include=sub-*/ses-*/seed/{seed_dir}/**",
        "--exclude=*",
        remote_src,
        str(local_dest) + "/",
    ]

    progress("Downloading…", 0.1)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if result.returncode != 0:
        raise RuntimeError(f"rsync failed: {result.stderr[:500]}")
    progress("Done", 1.0)


def _cleanup_hpc_seed(config: dict, pipeline: str, seed_dir: str) -> None:
    """SSH and remove seed_dir from HPC (all subjects) after confirming results are local."""
    from utils.hpc import HPCConfig, HPCConnection  # noqa: PLC0415

    hpc_cfg = HPCConfig.from_config(config)
    conn = HPCConnection(hpc_cfg)
    conn.connect()
    try:
        remote_base = f"{hpc_cfg.remote_base}/derivatives/connectivity/{pipeline}"
        # Remove seed_dir from every sub-*/ses-* directory
        cmd = (
            f"find {remote_base} -mindepth 3 -maxdepth 3 -type d -name '{seed_dir}' "
            f"| xargs -r rm -rf"
        )
        _stdout, stderr, exit_code = conn.execute(cmd, timeout=120)
        if exit_code != 0:
            raise RuntimeError(f"cleanup failed: {stderr[:300]}")
    finally:
        conn.disconnect()


def _render_download_tab(config: dict, bids_root: Any) -> None:
    """Download completed HPC seed connectivity results."""
    from utils.connectivity_download import (  # noqa: PLC0415
        download_seed_results as _dl_seed,
        build_seed_download_command as _build_seed_dl_cmd,
    )
    from utils.hpc import HPCConfig as _HPCConfig  # noqa: PLC0415

    manager = ConnectivityWorkflowManager(config)
    completed = [
        s for s in manager.list_submissions()
        if s.analysis_type == "seed_connectivity"
        and s.execution_mode == "hpc"
        and s.status == "completed"
    ]

    if not completed:
        st.info("No completed HPC seed jobs to download.")

    for sub in sorted(completed, key=lambda s: s.submitted_at, reverse=True):
        with st.container(border=True):
            pipeline = sub.options.get("pipeline", "fc")
            seeds = sub.options.get("seeds", [])
            seeds_str = ", ".join(str(s) for s in seeds[:3])
            if len(seeds) > 3:
                seeds_str += f" (+{len(seeds) - 3} more)"

            st.markdown(f"**Job ID:** `{sub.job_id or '—'}` ✅ Completed")
            st.caption(
                f"Submitted: {sub.submitted_at} | Pipeline: `{pipeline}` "
                f"| Seeds: {seeds_str or '—'} | Subjects: {len(sub.subjects)}"
            )

            hpc_cfg = None
            try:
                hpc_cfg = _HPCConfig.from_config(config)
                cmd_preview = _build_seed_dl_cmd(
                    pipeline=pipeline,
                    seeds=seeds,
                    subjects=sub.subjects[:5],
                    hpc_config=hpc_cfg,
                    local_bids_root=Path(bids_root),
                )
                with st.expander("📋 Rsync command preview"):
                    st.code(cmd_preview, language="bash")
            except Exception as exc:
                st.warning(f"Could not build command preview: {exc}")

            if st.button("⬇️ Download Results", key=f"download_{sub.submission_id}"):
                if hpc_cfg is None:
                    try:
                        hpc_cfg = _HPCConfig.from_config(config)
                    except Exception as exc:
                        st.error(f"HPC config error: {exc}")
                        return
                st_progress = st.progress(0.0, text="Starting download…")
                st_status = st.empty()
                try:
                    results = _dl_seed(
                        submission_id=sub.submission_id,
                        pipeline=pipeline,
                        seeds=seeds,
                        subjects=sub.subjects,
                        hpc_config=hpc_cfg,
                        local_bids_root=Path(bids_root),
                        progress_callback=_make_progress_callback(st_progress, st_status),
                    )
                    ok = sum(1 for v in results.values() if v)
                    fail = len(results) - ok
                    for sub_id, success in results.items():
                        st.markdown(f"{'✅' if success else '❌'} `{sub_id}`")
                    if fail == 0:
                        st.success(f"✅ Downloaded {ok}/{len(results)} subjects successfully.")
                    else:
                        st.error(f"⚠️ {fail} subject(s) failed. {ok} succeeded.")
                except Exception as exc:
                    st.error(f"Download failed: {exc}")

    # ------------------------------------------------------------------
    # Recovery: scan HPC for undownloaded results
    # ------------------------------------------------------------------
    st.divider()
    with st.expander("🔍 Scan HPC for undownloaded results", expanded=not bool(completed)):
        st.caption(
            "Use this to recover downloads after a page refresh, or to find results "
            "submitted outside of this UI."
        )
        pipeline_scan = st.selectbox(
            "Pipeline to scan", ["fc", "fc_gsr", "ec"],
            key="submit_seed_scan_hpc_pipeline",
        )
        if st.button("🔍 Scan HPC", key="submit_seed_scan_hpc_btn"):
            with st.spinner("Connecting to HPC and scanning…"):
                try:
                    scan_results = _scan_hpc_connectivity(
                        config, pipeline_scan, Path(bids_root)
                    )
                    st.session_state["submit_seed_hpc_scan"] = scan_results
                    st.session_state["submit_seed_hpc_scan_pipeline"] = pipeline_scan
                except Exception as exc:
                    st.error(f"Scan failed: {exc}")

        scan = st.session_state.get("submit_seed_hpc_scan", {})
        scan_pipeline = st.session_state.get("submit_seed_hpc_scan_pipeline", "fc")

        if scan:
            total_remote = sum(len(v["remote_subjects"]) for v in scan.values())
            total_missing = sum(len(v["local_missing"]) for v in scan.values())
            st.success(
                f"Found **{len(scan)} seed(s)**, "
                f"**{total_remote} subject-session result(s)** on HPC, "
                f"**{total_missing}** not yet downloaded locally."
            )

            for seed_dir, info in sorted(scan.items()):
                n_remote = len(info["remote_subjects"])
                n_missing = len(info["local_missing"])
                status_label = "✅ All downloaded" if n_missing == 0 else f"⬇️ {n_missing}/{n_remote} pending"

                with st.container(border=True):
                    col_label, col_dl, col_clean = st.columns([3, 1, 1])
                    with col_label:
                        st.markdown(f"**{seed_dir}**  {status_label}")
                        st.caption(f"{n_remote} result(s) on HPC")

                    with col_dl:
                        if n_missing > 0 and st.button(
                            "⬇️ Download", key=f"submit_seed_scan_dl_{seed_dir}"
                        ):
                            prog = st.progress(0.0, text="Downloading…")
                            try:
                                _download_seed_scan_results(
                                    config, scan_pipeline, seed_dir, Path(bids_root),
                                    lambda msg, frac: prog.progress(frac, text=msg),
                                )
                                st.success(f"✅ Downloaded {seed_dir}")
                                st.session_state.pop("submit_seed_hpc_scan", None)
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Download failed: {exc}")

                    with col_clean:
                        if n_missing == 0 and st.button(
                            "🗑️ Clean HPC", key=f"submit_seed_scan_clean_{seed_dir}",
                            help="Remove from HPC after confirming all results are local",
                        ):
                            try:
                                _cleanup_hpc_seed(config, scan_pipeline, seed_dir)
                                st.success(f"✅ Cleaned {seed_dir} from HPC")
                                st.session_state.pop("submit_seed_hpc_scan", None)
                                st.rerun()
                            except Exception as exc:
                                st.error(f"Cleanup failed: {exc}")


def _render_submit_tab(config: dict, bids_root: Any) -> None:
    # --- Session state defaults ---
    st.session_state.setdefault(f"{STATE_PREFIX}pipeline", "fc")
    st.session_state.setdefault(f"{STATE_PREFIX}subjects", [])
    st.session_state.setdefault(f"{STATE_PREFIX}sessions", [])
    st.session_state.setdefault(f"{STATE_PREFIX}seeds", [])
    st.session_state.setdefault(f"{STATE_PREFIX}measures", ALL_MEASURES)
    st.session_state.setdefault(f"{STATE_PREFIX}bold_variant", "denoisedSmoothed")
    st.session_state.setdefault(f"{STATE_PREFIX}out_root", "derivatives/connectivity")
    st.session_state.setdefault(f"{STATE_PREFIX}last_command", "")

    # --- Pipeline ---
    pipeline = st.selectbox(
        "Pipeline",
        KNOWN_PIPELINES,
        index=KNOWN_PIPELINES.index(st.session_state.get(f"{STATE_PREFIX}pipeline", "fc")),
        key=f"{STATE_PREFIX}pipeline_widget",
    )
    st.session_state[f"{STATE_PREFIX}pipeline"] = pipeline

    # --- Subject / Session scope ---
    with st.spinner("Discovering subjects…"):
        sub_ses = _discover_subjects_sessions(str(bids_root), pipeline)
    all_subjects = list(sub_ses.keys())
    all_sessions = sorted({s for slist in sub_ses.values() for s in slist})

    _stored_subjects = st.session_state.get(f"{STATE_PREFIX}subjects") or all_subjects
    _valid_default_subjects = [s for s in _stored_subjects if s in all_subjects] or all_subjects
    sel_subjects = st.multiselect(
        "Subjects (default: all)",
        options=all_subjects,
        default=_valid_default_subjects,
        key=f"{STATE_PREFIX}subj_widget",
    )
    st.session_state[f"{STATE_PREFIX}subjects"] = sel_subjects

    _stored_sessions = st.session_state.get(f"{STATE_PREFIX}sessions") or all_sessions
    _valid_default_sessions = [s for s in _stored_sessions if s in all_sessions] or all_sessions
    sel_sessions = st.multiselect(
        "Sessions (default: all)",
        options=all_sessions,
        default=_valid_default_sessions,
        key=f"{STATE_PREFIX}ses_widget",
    )
    st.session_state[f"{STATE_PREFIX}sessions"] = sel_sessions

    st.markdown("---")

    # --- Seed builder ---
    catalog: SeedCatalog | None = None
    try:
        catalog = SeedCatalog(Path(bids_root), xcpd_pipeline=pipeline)
    except Exception:
        pass
    _render_seed_builder(catalog, bids_root)

    st.markdown("---")

    # --- Measures ---
    sel_measures = st.multiselect(
        "Measures",
        options=ALL_MEASURES,
        default=st.session_state.get(f"{STATE_PREFIX}measures") or ALL_MEASURES,
        key=f"{STATE_PREFIX}measures_widget",
    )
    st.session_state[f"{STATE_PREFIX}measures"] = sel_measures

    # --- BOLD variant ---
    bold_variant = st.selectbox(
        "BOLD variant",
        ["denoisedSmoothed", "denoised"],
        index=0 if st.session_state.get(f"{STATE_PREFIX}bold_variant", "denoisedSmoothed") == "denoisedSmoothed" else 1,
        key=f"{STATE_PREFIX}bold_widget",
    )
    st.session_state[f"{STATE_PREFIX}bold_variant"] = bold_variant

    # --- Output root ---
    out_root = st.text_input(
        "Output root",
        value=st.session_state.get(f"{STATE_PREFIX}out_root", "derivatives/connectivity"),
        key=f"{STATE_PREFIX}out_root_widget",
    )
    st.session_state[f"{STATE_PREFIX}out_root"] = out_root

    st.markdown("---")

    # --- Run target: Local vs HPC ---
    st.subheader("⚙️ Execution target")
    run_target = st.radio(
        "Run on",
        ["Local (serial, this workstation)", "HPC (SLURM batch)"],
        horizontal=True,
        key=f"{STATE_PREFIX}run_target_widget",
        help=(
            "Local runs the connectivity script serially as a subprocess on this "
            "machine — no parallelism, suitable for testing or small jobs.  HPC "
            "submits a SLURM array job via the configured cluster."
        ),
    )
    is_local = run_target.startswith("Local")
    st.session_state[f"{STATE_PREFIX}run_target"] = "local" if is_local else "hpc"

    # HPC-only: re-upload cleaned XCP-D inputs
    reupload_inputs = False
    if not is_local:
        reupload_inputs = st.checkbox(
            "🔄 Re-upload cleaned XCP-D inputs to HPC before submitting",
            value=False,
            key=f"{STATE_PREFIX}reupload_widget",
            help=(
                "Sync local derivatives/preprocessing/xcpd/<pipeline>/<sub>/ for the "
                "selected subjects to the HPC.  Use this if you have re-run XCP-D "
                "locally and need the cluster to pick up the latest denoised BOLD "
                "and atlas TSVs."
            ),
        )

    # --- Command preview ---
    seeds: list[dict] = st.session_state.get(f"{STATE_PREFIX}seeds", [])
    manager = ConnectivityWorkflowManager(config)

    # Resolve HPC remote path for command construction (used both in preview and actual submit)
    _remote_bids_root: str = str(bids_root)  # default: local path
    _hpc_cfg_preview = None
    if not is_local:
        try:
            from utils.hpc import HPCConfig as _HPCCfg
            _hpc_cfg_preview = _HPCCfg.from_config(config)
            if _hpc_cfg_preview.remote_base:
                _remote_bids_root = _hpc_cfg_preview.remote_base
        except Exception:
            pass

    def _build_cmd(dry_run: bool = False) -> str:
        subjects_for_cmd = sel_subjects or all_subjects
        preview_subs = subjects_for_cmd[:1] if subjects_for_cmd else ["sub-033"]
        opts = {
            "pipeline": pipeline,
            "measures": ",".join(sel_measures) if sel_measures else ",".join(ALL_MEASURES),
            "seeds": [sd["token"] for sd in seeds],
            "bids_root": _remote_bids_root,
            "out_root": out_root,
            "bold_variant": bold_variant,
            "dry_run": dry_run,
        }
        if not is_local and _hpc_cfg_preview is not None:
            opts["partition"] = _hpc_cfg_preview.partition
            opts["conda_env"] = _hpc_cfg_preview.conda_env
            opts["log_dir"] = f"{_remote_bids_root}/logs"
        return manager.build_subject_level_command(
            "seed_connectivity", opts, preview_subs
        )

    if st.button("🔍 Build command preview", key=f"{STATE_PREFIX}preview_btn"):
        try:
            cmd = _build_cmd(dry_run=True)
            # Add note that this will be wrapped in sbatch on HPC
            if not is_local:
                display_cmd = f"# This command will be wrapped in sbatch on HPC:\n{cmd}"
            else:
                display_cmd = cmd
            st.session_state[f"{STATE_PREFIX}last_command"] = display_cmd
        except Exception as exc:
            st.error(f"Command build failed: {exc}")

    if st.session_state.get(f"{STATE_PREFIX}last_command"):
        st.code(st.session_state[f"{STATE_PREFIX}last_command"], language="bash")

    # --- Preflight summary ---
    n_sub = len(sel_subjects or all_subjects)
    n_ses = len(sel_sessions or all_sessions)
    n_seeds = len(seeds)
    n_measures = len(sel_measures or ALL_MEASURES)
    total_jobs = n_sub * n_ses * n_seeds * n_measures

    st.info(
        f"**Preflight:** {n_sub} subjects × {n_ses} sessions × "
        f"{n_seeds} seeds × {n_measures} measures = **{total_jobs} jobs**"
    )
    if total_jobs > 500:
        st.warning("⚠️ Large submission (>500 jobs). Consider narrowing scope.")
    if is_local and total_jobs > 100:
        st.warning(
            "⚠️ Local serial execution will take a long time for this workload. "
            "Consider HPC for large runs."
        )

    st.markdown("---")

    # --- File pre-flight checks ---
    _preflight_ok = _render_preflight_section(
        bids_root=str(bids_root),
        pipeline=pipeline,
        subjects=sel_subjects or all_subjects,
        is_local=is_local,
        config=config,
    )

    st.markdown("---")

    # --- Active local run status (if any) ---
    state_dir = (Path(bids_root) / ".neuconn") if bids_root else Path.home() / ".neuconn"
    runner = LocalConnectivityRunner(state_dir)
    active_run_id = st.session_state.get(f"{STATE_PREFIX}local_run_id")
    if active_run_id:
        rs = runner.load_state(active_run_id)
        if rs:
            done = rs.get("completed", 0) + rs.get("failed", 0)
            total = max(rs.get("total", 1), 1)
            st.markdown(f"**Local run `{active_run_id}` — {rs['status']}**")
            st.progress(done / total, text=f"{done}/{total} — current: {rs.get('current') or '—'}")
            if rs["status"] in {"completed", "failed", "cancelled"}:
                st.success(f"Run finished: completed={rs['completed']}, failed={rs['failed']}")

    # --- Dry-run / Submit ---
    col_dry, col_sub = st.columns(2)
    with col_dry:
        if st.button("🏃 Dry-run", key=f"{STATE_PREFIX}dryrun_btn"):
            if not seeds:
                st.error("Add at least one seed before submitting.")
            else:
                try:
                    cmd = _build_cmd(dry_run=True)
                    st.session_state[f"{STATE_PREFIX}last_command"] = cmd
                    st.success("Dry-run command built (not submitted).")
                    st.code(cmd, language="bash")
                except Exception as exc:
                    st.error(f"Dry-run failed: {exc}")

    with col_sub:
        submit_label = "🖥️ Run locally (serial)" if is_local else "🚀 Submit to HPC"
        if st.button(submit_label, key=f"{STATE_PREFIX}submit_btn", type="primary"):
            if not seeds:
                st.error("Add at least one seed before submitting.")
            elif not is_local and not _preflight_ok:
                pf = st.session_state.get(f"{STATE_PREFIX}preflight_results")
                if pf is None:
                    st.error(
                        "⚠️ Run **pre-flight checks** before submitting to HPC. "
                        "This verifies the brain mask, scripts, and XCP-D data are "
                        "present on the cluster."
                    )
                else:
                    st.error(
                        "❌ Pre-flight checks failed. Fix the issues shown above "
                        "then re-run checks before submitting."
                    )
            elif is_local:
                # ---- LOCAL: serial subprocess loop --------------------- #
                _subjects_sessions = {
                    s: [ss for ss in (sub_ses.get(s, []) or [])
                        if not sel_sessions or ss in sel_sessions]
                    for s in (sel_subjects or all_subjects)
                }
                _subjects_sessions = {k: v for k, v in _subjects_sessions.items() if v}
                items = LocalConnectivityRunner.plan_seed(
                    subjects_sessions=_subjects_sessions,
                    seeds=[sd["token"] for sd in seeds],
                    measures=sel_measures or ALL_MEASURES,
                    bids_root=str(bids_root),
                    out_root=out_root,
                    pipeline=pipeline,
                    bold_variant=bold_variant,
                )
                if not items:
                    st.error("No subjects/sessions selected.")
                else:
                    run_id = runner.start_run("seed_connectivity", items)
                    st.session_state[f"{STATE_PREFIX}local_run_id"] = run_id
                    st.success(f"🟢 Local run started: `{run_id}` ({len(items)} subject-sessions)")
                    st.info(
                        "The UI will block while running.  Each subject-session "
                        "takes ~30–60 s.  Progress is also persisted to "
                        f"`{state_dir}/connectivity_local_runs/{run_id}.json`."
                    )
                    log_box = st.empty()
                    progress_bar = st.progress(0.0, text="Starting…")
                    log_lines: list[str] = []

                    def _on_log(msg: str) -> None:
                        log_lines.append(msg)
                        log_box.code("\n".join(log_lines[-20:]))

                    def _on_progress(done: int, total: int, label: str) -> None:
                        progress_bar.progress(min(done / max(total, 1), 1.0),
                                              text=f"{done}/{total} — {label}")

                    final = runner.run_all(run_id, log_callback=_on_log, progress_callback=_on_progress)
                    if final.get("status") == "completed":
                        st.success(
                            f"✅ Completed: {final['completed']}/{final['total']} "
                            f"({final.get('failed', 0)} failed)"
                        )
                    else:
                        st.error(
                            f"⚠️ Run finished with errors: completed={final.get('completed')}, "
                            f"failed={final.get('failed')}"
                        )
            else:
                # ---- HPC: optional re-upload then submit --------------- #
                try:
                    from utils.hpc import HPCConfig, HPCConnection
                    import subprocess as _sp
                    hpc_cfg = HPCConfig.from_config(config)
                    # _remote_bids_root already computed above (HPC remote path)
                    if reupload_inputs:
                        with st.spinner("Re-uploading cleaned XCP-D inputs to HPC…"):
                            subjects_for_upload = sel_subjects or all_subjects
                            ssh_opts = (
                                f"ssh -p {hpc_cfg.port} -o StrictHostKeyChecking=no"
                            )
                            local_xcpd = (Path(bids_root) / "derivatives"
                                          / "preprocessing" / "xcpd" / pipeline)
                            remote_xcpd = (
                                f"{hpc_cfg.user}@{hpc_cfg.host}:"
                                f"{hpc_cfg.remote_base}/derivatives/preprocessing/xcpd/{pipeline}/"
                            )
                            cmd = ["rsync", "-avz", "--info=progress2", "-e", ssh_opts]
                            for sub in subjects_for_upload:
                                cmd += [f"--include={sub}/", f"--include={sub}/**"]
                            cmd += ["--exclude=*", f"{local_xcpd}/", remote_xcpd]
                            res = _sp.run(cmd, capture_output=True, text=True, timeout=7200)
                            if res.returncode != 0:
                                st.error(f"Re-upload failed: {res.stderr[-500:]}")
                                st.stop()
                            st.success(f"Re-uploaded {len(subjects_for_upload)} subjects.")

                    subjects_for_submit = sel_subjects or all_subjects
                    opts = {
                        "pipeline": pipeline,
                        "measures": ",".join(sel_measures or ALL_MEASURES),
                        "seeds": [sd["token"] for sd in seeds],
                        "bids_root": _remote_bids_root,  # HPC remote path
                        "out_root": out_root,
                        "bold_variant": bold_variant,
                        "log_dir": f"{_remote_bids_root}/logs",  # absolute path on HPC
                        "partition": hpc_cfg.partition,  # use configured partition
                        "conda_env": hpc_cfg.conda_env,  # conda environment for jobs
                    }
                    sub_obj = manager.submit(
                        "seed_connectivity", opts, subjects_for_submit, dry_run=False,
                        execution_mode="hpc",
                    )
                    job_id = sub_obj.job_id if sub_obj else "unknown"
                    if sub_obj and sub_obj.status == "failed":
                        st.error(f"❌ HPC submission failed: {sub_obj.notes or 'unknown error'}")
                    else:
                        st.success(f"✅ HPC job submitted! Job ID: **{job_id}**")
                except Exception as exc:
                    st.error(f"HPC submission failed: {exc}")


def render() -> None:
    st.title("📤 Submit Seed Connectivity")

    config = _get_config()
    bids_root_value = (
        config.get("project_root")
        or config.get("paths", {}).get("project_root")
        or config.get("paths", {}).get("bids_root")
        or config.get("paths", {}).get("bids_dir")
    )
    bids_root = (
        Path(bids_root_value).expanduser()
        if bids_root_value and "${" not in str(bids_root_value)
        else Path(__file__).resolve().parents[2]
    )

    tabs = st.tabs(["⚙️ Submit", "📡 Monitor", "⬇️ Download"])

    with tabs[0]:
        _render_submit_tab(config, bids_root)

    with tabs[1]:
        _render_monitor_tab(config, bids_root)

    with tabs[2]:
        _render_download_tab(config, bids_root)


if __name__ == "__main__":
    render()
