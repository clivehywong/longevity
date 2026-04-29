"""Submit group-level statistics (XCP-D backend).

Supports two top-level kinds:
  Voxel  — alff / reho / seed-<id> maps via GRF / TFCE / FDR
  Matrix — network or seed correlation matrices via paired_t_fdr / nbs / tfnbs

Uses ConnectivityWorkflowManager.build_group_level_command().
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.config import load_config
from utils.connectivity_workflow import ConnectivityWorkflowManager
from utils.xcpd_outputs import KNOWN_PIPELINES

STATE_PREFIX = "submit_group_"

_DEFAULT_GROUP_CSV = "/home/clivewong/proj/longevity/group.csv"
_DEFAULT_OUT_ROOT = "derivatives/connectivity/group/"


def _get_config() -> dict:
    return st.session_state.get("config") or load_config()


def _scan_seed_ids(bids_root: str, pipeline: str) -> list[str]:
    """Scan derivatives/connectivity/<pipeline>/sub-*/ses-*/seed/ for seed IDs."""
    base = Path(bids_root) / "derivatives" / "connectivity" / pipeline
    seed_ids: set[str] = set()
    for p in base.glob("sub-*/ses-*/seed/*/"):
        if p.is_dir():
            seed_ids.add(p.name)
    return sorted(seed_ids)


def _read_group_csv_columns(csv_path: str) -> list[str]:
    """Return column names from group.csv for contrast builder."""
    try:
        import pandas as pd
        df = pd.read_csv(csv_path, nrows=0)
        return list(df.columns)
    except Exception:
        return []


def _build_contrast_options(csv_path: str) -> list[str]:
    opts = ["ses-02_minus_ses-01", "group-walking_minus_control"]
    for col in _read_group_csv_columns(csv_path):
        if col not in ("subject", "session", "group"):
            opts.append(f"correlation_{col}")
    return opts


def render() -> None:
    st.title("📤 Submit Group Statistics")

    # --- Session state defaults ---
    st.session_state.setdefault(f"{STATE_PREFIX}kind", "Voxel")
    st.session_state.setdefault(f"{STATE_PREFIX}pipeline", "fc")
    st.session_state.setdefault(f"{STATE_PREFIX}group_csv", _DEFAULT_GROUP_CSV)
    st.session_state.setdefault(f"{STATE_PREFIX}out_root", _DEFAULT_OUT_ROOT)
    # Voxel defaults
    st.session_state.setdefault(f"{STATE_PREFIX}measure", "alff")
    st.session_state.setdefault(f"{STATE_PREFIX}contrast", "ses-02_minus_ses-01")
    st.session_state.setdefault(f"{STATE_PREFIX}method", "GRF")
    st.session_state.setdefault(f"{STATE_PREFIX}n_perms", 5000)
    st.session_state.setdefault(f"{STATE_PREFIX}mask", "")
    # Matrix defaults
    st.session_state.setdefault(f"{STATE_PREFIX}matrix_kind", "network")
    st.session_state.setdefault(f"{STATE_PREFIX}atlas", "")
    st.session_state.setdefault(f"{STATE_PREFIX}seed_id", "")
    st.session_state.setdefault(f"{STATE_PREFIX}matrix_measure", "pearson")
    st.session_state.setdefault(f"{STATE_PREFIX}mat_contrast", "ses-02_minus_ses-01")
    st.session_state.setdefault(f"{STATE_PREFIX}mat_method", "paired_t_fdr")
    st.session_state.setdefault(f"{STATE_PREFIX}threshold", 3.1)
    st.session_state.setdefault(f"{STATE_PREFIX}alpha", 0.05)
    st.session_state.setdefault(f"{STATE_PREFIX}mat_n_perms", 5000)
    st.session_state.setdefault(f"{STATE_PREFIX}last_command", "")

    config = _get_config()
    bids_root = config.get("paths", {}).get("bids_root", "bids")

    # --- Kind ---
    kind = st.radio(
        "Analysis kind",
        ["Voxel", "Matrix"],
        index=0 if st.session_state.get(f"{STATE_PREFIX}kind", "Voxel") == "Voxel" else 1,
        horizontal=True,
        key=f"{STATE_PREFIX}kind_widget",
    )
    st.session_state[f"{STATE_PREFIX}kind"] = kind

    st.markdown("---")

    # --- Common: pipeline + paths ---
    pipeline = st.selectbox(
        "Pipeline",
        KNOWN_PIPELINES,
        index=KNOWN_PIPELINES.index(st.session_state.get(f"{STATE_PREFIX}pipeline", "fc")),
        key=f"{STATE_PREFIX}pipeline_widget",
    )
    st.session_state[f"{STATE_PREFIX}pipeline"] = pipeline

    group_csv = st.text_input(
        "group.csv path",
        value=st.session_state.get(f"{STATE_PREFIX}group_csv", _DEFAULT_GROUP_CSV),
        key=f"{STATE_PREFIX}csv_widget",
    )
    st.session_state[f"{STATE_PREFIX}group_csv"] = group_csv

    out_root = st.text_input(
        "Output root",
        value=st.session_state.get(f"{STATE_PREFIX}out_root", _DEFAULT_OUT_ROOT),
        key=f"{STATE_PREFIX}out_root_widget",
    )
    st.session_state[f"{STATE_PREFIX}out_root"] = out_root

    contrast_opts = _build_contrast_options(group_csv)

    st.markdown("---")

    # ================================================================
    # VOXEL branch
    # ================================================================
    if kind == "Voxel":
        st.subheader("🗺️ Voxel-level settings")

        # Build measure options: alff, reho, + seed-<id>
        seed_ids = _scan_seed_ids(str(bids_root), pipeline)
        measure_opts = ["alff", "reho"] + [f"seed-{sid}" for sid in seed_ids]
        cur_measure = st.session_state.get(f"{STATE_PREFIX}measure", "alff")
        if cur_measure not in measure_opts:
            cur_measure = "alff"

        measure = st.selectbox(
            "Measure",
            measure_opts,
            index=measure_opts.index(cur_measure),
            key=f"{STATE_PREFIX}measure_widget",
        )
        st.session_state[f"{STATE_PREFIX}measure"] = measure

        contrast = st.selectbox(
            "Contrast",
            contrast_opts,
            index=contrast_opts.index(
                st.session_state.get(f"{STATE_PREFIX}contrast", contrast_opts[0])
            ) if st.session_state.get(f"{STATE_PREFIX}contrast") in contrast_opts else 0,
            key=f"{STATE_PREFIX}contrast_widget",
        )
        st.session_state[f"{STATE_PREFIX}contrast"] = contrast

        method = st.selectbox(
            "Correction method",
            ["GRF", "TFCE", "FDR"],
            index=["GRF", "TFCE", "FDR"].index(
                st.session_state.get(f"{STATE_PREFIX}method", "GRF")
            ),
            key=f"{STATE_PREFIX}method_widget",
        )
        st.session_state[f"{STATE_PREFIX}method"] = method

        if method == "TFCE":
            n_perms = st.number_input(
                "n_permutations",
                min_value=100,
                max_value=50000,
                value=st.session_state.get(f"{STATE_PREFIX}n_perms", 5000),
                step=100,
                key=f"{STATE_PREFIX}nperms_widget",
            )
            st.session_state[f"{STATE_PREFIX}n_perms"] = int(n_perms)
            if n_perms < 1000:
                st.warning("⚠️ <1000 permutations gives unreliable p-values.")
        else:
            n_perms = None

        mask = st.text_input(
            "Brain mask path (leave blank for auto-derived)",
            value=st.session_state.get(f"{STATE_PREFIX}mask", ""),
            key=f"{STATE_PREFIX}mask_widget",
        )
        st.session_state[f"{STATE_PREFIX}mask"] = mask
        if not mask:
            st.info("ℹ️ No mask provided — will auto-derive from data (may warn).")

        group_opts: dict[str, Any] = {
            "kind": "voxel",
            "pipeline": pipeline,
            "measure": measure,
            "contrast": contrast,
            "method": method,
            "group_csv": group_csv,
            "out": out_root,
            "bids_root": str(bids_root),
        }
        if mask:
            group_opts["mask"] = mask
        if n_perms is not None:
            group_opts["n_permutations"] = n_perms

    # ================================================================
    # MATRIX branch
    # ================================================================
    else:
        st.subheader("🔢 Matrix-level settings")

        matrix_kind = st.selectbox(
            "Matrix kind",
            ["network", "seed"],
            index=["network", "seed"].index(
                st.session_state.get(f"{STATE_PREFIX}matrix_kind", "network")
            ),
            key=f"{STATE_PREFIX}matkind_widget",
        )
        st.session_state[f"{STATE_PREFIX}matrix_kind"] = matrix_kind

        from utils.xcpd_outputs import KNOWN_ATLASES

        if matrix_kind == "network":
            atlas = st.selectbox(
                "Atlas",
                list(KNOWN_ATLASES),
                index=0,
                key=f"{STATE_PREFIX}atlas_widget",
            )
            st.session_state[f"{STATE_PREFIX}atlas"] = atlas
            seed_id_val = None
        else:
            seed_ids = _scan_seed_ids(str(bids_root), pipeline)
            if seed_ids:
                seed_id_val = st.selectbox(
                    "Seed ID",
                    seed_ids,
                    key=f"{STATE_PREFIX}seedid_widget",
                )
            else:
                seed_id_val = st.text_input(
                    "Seed ID (no outputs found on disk, enter manually)",
                    key=f"{STATE_PREFIX}seedid_manual",
                )
            st.session_state[f"{STATE_PREFIX}seed_id"] = seed_id_val
            atlas = None

        matrix_measure = st.selectbox(
            "Measure",
            ["pearson", "spearman", "partial_correlation", "plv", "wpli",
             "coherence", "amplitude_envelope_correlation", "mutual_information"],
            key=f"{STATE_PREFIX}matmeasure_widget",
        )
        st.session_state[f"{STATE_PREFIX}matrix_measure"] = matrix_measure

        mat_contrast = st.selectbox(
            "Contrast",
            contrast_opts,
            index=contrast_opts.index(
                st.session_state.get(f"{STATE_PREFIX}mat_contrast", contrast_opts[0])
            ) if st.session_state.get(f"{STATE_PREFIX}mat_contrast") in contrast_opts else 0,
            key=f"{STATE_PREFIX}mat_contrast_widget",
        )
        st.session_state[f"{STATE_PREFIX}mat_contrast"] = mat_contrast

        mat_method = st.selectbox(
            "Statistical method",
            ["paired_t_fdr", "nbs", "tfnbs"],
            index=["paired_t_fdr", "nbs", "tfnbs"].index(
                st.session_state.get(f"{STATE_PREFIX}mat_method", "paired_t_fdr")
            ),
            key=f"{STATE_PREFIX}matmethod_widget",
        )
        st.session_state[f"{STATE_PREFIX}mat_method"] = mat_method

        threshold_val: float | None = None
        mat_n_perms = 5000
        if mat_method in ("nbs", "tfnbs"):
            threshold_val = st.number_input(
                "Threshold (t-stat)",
                value=float(st.session_state.get(f"{STATE_PREFIX}threshold", 3.1)),
                step=0.1,
                key=f"{STATE_PREFIX}thresh_widget",
            )
            st.session_state[f"{STATE_PREFIX}threshold"] = threshold_val

        mat_n_perms = st.number_input(
            "n_permutations",
            min_value=100,
            max_value=50000,
            value=st.session_state.get(f"{STATE_PREFIX}mat_n_perms", 5000),
            step=100,
            key=f"{STATE_PREFIX}matperms_widget",
        )
        st.session_state[f"{STATE_PREFIX}mat_n_perms"] = int(mat_n_perms)

        alpha = st.number_input(
            "Alpha",
            value=float(st.session_state.get(f"{STATE_PREFIX}alpha", 0.05)),
            step=0.01,
            min_value=0.001,
            max_value=0.2,
            key=f"{STATE_PREFIX}alpha_widget",
        )
        st.session_state[f"{STATE_PREFIX}alpha"] = alpha

        group_opts = {
            "kind": "matrix",
            "matrix_kind": matrix_kind,
            "pipeline": pipeline,
            "measure": matrix_measure,
            "contrast": mat_contrast,
            "method": mat_method,
            "group_csv": group_csv,
            "out": out_root,
            "bids_root": str(bids_root),
            "n_permutations": int(mat_n_perms),
            "alpha": alpha,
        }
        if atlas:
            group_opts["atlas"] = atlas
        if seed_id_val:
            group_opts["seed_id"] = seed_id_val
        if threshold_val is not None:
            group_opts["threshold"] = threshold_val

    st.markdown("---")

    # --- Manifest preflight ---
    manager = ConnectivityWorkflowManager(config)

    st.subheader("🔎 Manifest preflight")
    if kind == "Voxel":
        input_pattern = (
            Path(str(bids_root))
            / "derivatives" / "connectivity" / pipeline
            / "sub-*" / "ses-*"
            / group_opts.get("measure", "alff")
        )
        matches = list(Path(str(bids_root)).glob(
            f"derivatives/connectivity/{pipeline}/sub-*/ses-*/{group_opts.get('measure', 'alff')}*"
        ))
        if matches:
            st.success(f"Found {len(matches)} matching input files.")
        else:
            st.warning("⚠️ No matching input files found. Verify subject-level outputs exist.")
    else:
        # Count matrix files
        mat_glob = f"derivatives/connectivity/{pipeline}/sub-*/ses-*/{matrix_kind}/**/*.tsv"
        matches = list(Path(str(bids_root)).glob(mat_glob))
        if matches:
            st.success(f"Found {len(matches)} matrix files for '{matrix_kind}'.")
        else:
            st.warning("⚠️ No matrix files found. Verify subject-level outputs exist.")

    # --- Command preview ---
    if st.button("🔍 Build command preview", key=f"{STATE_PREFIX}preview_btn"):
        try:
            cmd = manager.build_group_level_command(group_opts)
            st.session_state[f"{STATE_PREFIX}last_command"] = cmd
        except Exception as exc:
            st.error(f"Command build failed: {exc}")

    if st.session_state.get(f"{STATE_PREFIX}last_command"):
        st.code(st.session_state[f"{STATE_PREFIX}last_command"], language="bash")

    # --- Dry-run / Submit ---
    col_dry, col_sub = st.columns(2)
    with col_dry:
        if st.button("🏃 Dry-run", key=f"{STATE_PREFIX}dryrun_btn"):
            dry_opts = dict(group_opts, dry_run=True)
            try:
                cmd = manager.build_group_level_command(dry_opts)
                st.session_state[f"{STATE_PREFIX}last_command"] = cmd
                st.success("Dry-run command built (not submitted).")
                st.code(cmd, language="bash")
            except Exception as exc:
                st.error(f"Dry-run failed: {exc}")

    with col_sub:
        if st.button("🚀 Submit", key=f"{STATE_PREFIX}submit_btn", type="primary"):
            try:
                sub_obj = manager.submit("group_stats", group_opts, [], dry_run=False)
                job_id = sub_obj.job_id if sub_obj else "unknown"
                st.success(f"✅ Submitted! Job ID: **{job_id}**")
                if st.button("📡 Track on HPC monitor", key=f"{STATE_PREFIX}track_btn"):
                    st.session_state["hpc_monitor_job_id"] = job_id
            except Exception as exc:
                st.error(f"Submission failed: {exc}")
