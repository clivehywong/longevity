"""Submit network connectivity analyses (XCP-D backend).

Uses ConnectivityWorkflowManager.build_subject_level_command() with
--analysis network, --pipeline, --measures, and repeatable --atlas flags.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.config import load_config
from utils.connectivity_workflow import ConnectivityWorkflowManager
from utils.xcpd_outputs import XcpdDiscovery, KNOWN_PIPELINES, KNOWN_ATLASES

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "script"))
try:
    from connectivity_measures import MEASURES as _MEASURES_REGISTRY
    ALL_MEASURES = list(_MEASURES_REGISTRY.keys())
except Exception:
    ALL_MEASURES = [
        "pearson", "spearman", "partial_correlation",
        "plv", "wpli", "coherence",
        "amplitude_envelope_correlation", "mutual_information",
    ]

STATE_PREFIX = "submit_network_"


@st.cache_data(ttl=60, show_spinner=False)
def _discover_subjects_sessions(bids_root: str, pipeline: str) -> dict[str, list[str]]:
    disc = XcpdDiscovery(Path(bids_root), pipeline=pipeline)
    result: dict[str, list[str]] = {}
    for sub in disc.list_subjects(pipeline):
        sessions = disc.list_sessions(sub, pipeline)
        if sessions:
            result[sub] = sessions
    return result


@st.cache_data(ttl=60, show_spinner=False)
def _discover_atlases(bids_root: str, pipeline: str) -> list[str]:
    """Return atlases found in XCP-D outputs for this pipeline."""
    disc = XcpdDiscovery(Path(bids_root), pipeline=pipeline)
    subjects = disc.list_subjects(pipeline)
    for sub in subjects:
        sessions = disc.list_sessions(sub, pipeline)
        for ses in sessions:
            out = disc.get(sub, ses, pipeline)
            atlases = out.list_atlases()
            if atlases:
                return atlases
    return list(KNOWN_ATLASES)


def _get_config() -> dict:
    return st.session_state.get("config") or load_config()


def render() -> None:
    st.title("📤 Submit Network Connectivity")

    # --- Session state defaults ---
    st.session_state.setdefault(f"{STATE_PREFIX}pipeline", "fc")
    st.session_state.setdefault(f"{STATE_PREFIX}subjects", [])
    st.session_state.setdefault(f"{STATE_PREFIX}sessions", [])
    st.session_state.setdefault(f"{STATE_PREFIX}atlases", [])
    st.session_state.setdefault(f"{STATE_PREFIX}measures", ALL_MEASURES)
    st.session_state.setdefault(f"{STATE_PREFIX}out_root", "derivatives/connectivity")
    st.session_state.setdefault(f"{STATE_PREFIX}last_command", "")

    config = _get_config()
    bids_root = config.get("paths", {}).get("bids_root", "bids")

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

    sel_subjects = st.multiselect(
        "Subjects (default: all)",
        options=all_subjects,
        default=st.session_state.get(f"{STATE_PREFIX}subjects") or all_subjects,
        key=f"{STATE_PREFIX}subj_widget",
    )
    st.session_state[f"{STATE_PREFIX}subjects"] = sel_subjects

    sel_sessions = st.multiselect(
        "Sessions (default: all)",
        options=all_sessions,
        default=st.session_state.get(f"{STATE_PREFIX}sessions") or all_sessions,
        key=f"{STATE_PREFIX}ses_widget",
    )
    st.session_state[f"{STATE_PREFIX}sessions"] = sel_sessions

    st.markdown("---")

    # --- Atlas multi-select ---
    with st.spinner("Discovering atlases…"):
        available_atlases = _discover_atlases(str(bids_root), pipeline)

    sel_atlases = st.multiselect(
        "Atlases (default: all discovered)",
        options=available_atlases,
        default=st.session_state.get(f"{STATE_PREFIX}atlases") or available_atlases,
        key=f"{STATE_PREFIX}atlas_widget",
    )
    st.session_state[f"{STATE_PREFIX}atlases"] = sel_atlases

    # --- Measures ---
    sel_measures = st.multiselect(
        "Measures",
        options=ALL_MEASURES,
        default=st.session_state.get(f"{STATE_PREFIX}measures") or ALL_MEASURES,
        key=f"{STATE_PREFIX}measures_widget",
    )
    st.session_state[f"{STATE_PREFIX}measures"] = sel_measures

    # --- Output root ---
    out_root = st.text_input(
        "Output root",
        value=st.session_state.get(f"{STATE_PREFIX}out_root", "derivatives/connectivity"),
        key=f"{STATE_PREFIX}out_root_widget",
    )
    st.session_state[f"{STATE_PREFIX}out_root"] = out_root

    st.markdown("---")

    manager = ConnectivityWorkflowManager(config)

    def _build_cmd(dry_run: bool = False) -> str:
        subjects_for_cmd = sel_subjects or all_subjects
        preview_subs = subjects_for_cmd[:1] if subjects_for_cmd else ["sub-033"]
        opts = {
            "pipeline": pipeline,
            "measures": ",".join(sel_measures or ALL_MEASURES),
            "atlases": sel_atlases or available_atlases,
            "bids_root": str(bids_root),
            "out_root": out_root,
            "dry_run": dry_run,
        }
        return manager.build_subject_level_command(
            "network_connectivity", opts, preview_subs
        )

    if st.button("🔍 Build command preview", key=f"{STATE_PREFIX}preview_btn"):
        try:
            cmd = _build_cmd(dry_run=True)
            st.session_state[f"{STATE_PREFIX}last_command"] = cmd
        except Exception as exc:
            st.error(f"Command build failed: {exc}")

    if st.session_state.get(f"{STATE_PREFIX}last_command"):
        st.code(st.session_state[f"{STATE_PREFIX}last_command"], language="bash")

    # --- Preflight summary ---
    n_sub = len(sel_subjects or all_subjects)
    n_ses = len(sel_sessions or all_sessions)
    n_atlases = len(sel_atlases or available_atlases)
    n_measures = len(sel_measures or ALL_MEASURES)
    total_jobs = n_sub * n_ses * n_atlases * n_measures

    st.info(
        f"**Preflight:** {n_sub} subjects × {n_ses} sessions × "
        f"{n_atlases} atlases × {n_measures} measures = **{total_jobs} jobs**"
    )
    if total_jobs > 500:
        st.warning("⚠️ Large submission (>500 jobs). Consider narrowing scope.")

    # --- Dry-run / Submit ---
    col_dry, col_sub = st.columns(2)
    with col_dry:
        if st.button("🏃 Dry-run", key=f"{STATE_PREFIX}dryrun_btn"):
            if not (sel_atlases or available_atlases):
                st.error("No atlases selected.")
            else:
                try:
                    cmd = _build_cmd(dry_run=True)
                    st.session_state[f"{STATE_PREFIX}last_command"] = cmd
                    st.success("Dry-run command built (not submitted).")
                    st.code(cmd, language="bash")
                except Exception as exc:
                    st.error(f"Dry-run failed: {exc}")

    with col_sub:
        if st.button("🚀 Submit", key=f"{STATE_PREFIX}submit_btn", type="primary"):
            try:
                subjects_for_submit = sel_subjects or all_subjects
                opts = {
                    "pipeline": pipeline,
                    "measures": ",".join(sel_measures or ALL_MEASURES),
                    "atlases": sel_atlases or available_atlases,
                    "bids_root": str(bids_root),
                    "out_root": out_root,
                }
                sub_obj = manager.submit(
                    "network_connectivity", opts, subjects_for_submit, dry_run=False
                )
                job_id = sub_obj.job_id if sub_obj else "unknown"
                st.success(f"✅ Submitted! Job ID: **{job_id}**")
                if st.button("📡 Track on HPC monitor", key=f"{STATE_PREFIX}track_btn"):
                    st.session_state["hpc_monitor_job_id"] = job_id
            except Exception as exc:
                st.error(f"Submission failed: {exc}")
