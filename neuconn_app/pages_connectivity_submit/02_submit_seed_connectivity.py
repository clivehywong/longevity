"""Submit seed-based connectivity analyses to HPC.

This Streamlit page provides the subject/session controls, cascading atlas-to-seed
selection, preflight checks, and submission actions for subject-level seed-based
connectivity jobs.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import streamlit as st

# Support dynamic import from the custom NeuConn page loader.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.config import load_config
from utils.connectivity_workflow import ConnectivitySubmission, ConnectivityWorkflowManager
from utils.hpc import HPCConfig, HPCConnection
from utils.seed_catalog import Seed, SeedCatalog, load_default_catalog


SOURCE_LABELS = {
    "priority": "✨ Priority seeds",
    "custom": "🎨 Custom seeds",
    "atlas_parcel": "🗺️ Atlas parcels",
}
SOURCE_ORDER = {"priority": 0, "custom": 1, "atlas_parcel": 2}
STATE_PREFIX = "submit_seed_"


@st.cache_data(show_spinner=False)
def _load_config_cached() -> Dict[str, Any]:
    """Load default app configuration when the app has not injected one."""
    return load_config()


@st.cache_resource(show_spinner=False)
def _load_catalog_cached() -> SeedCatalog:
    """Load the merged priority/custom/atlas seed catalog once per app process."""
    return load_default_catalog()


@st.cache_data(show_spinner=False)
def _scan_bids_subject_sessions(bids_dir: str) -> Dict[str, List[str]]:
    """Return subject IDs without ``sub-`` and available sessions without ``ses-``."""
    bids_path = Path(str(bids_dir)).expanduser()
    if not bids_path.exists():
        return {}

    subject_sessions: Dict[str, List[str]] = {}
    for subject_dir in sorted(bids_path.glob("sub-*")):
        if not subject_dir.is_dir():
            continue
        subject_id = subject_dir.name.removeprefix("sub-")
        sessions = sorted(
            session_dir.name.removeprefix("ses-")
            for session_dir in subject_dir.glob("ses-*")
            if session_dir.is_dir()
        )
        if sessions:
            subject_sessions[subject_id] = sessions
    return subject_sessions


@st.cache_data(show_spinner=False)
def _xcpd_preflight(
    selected_subjects: Tuple[str, ...],
    selected_sessions: Tuple[str, ...],
    xcpd_dirs: Tuple[str, ...],
) -> Dict[str, Any]:
    """Check whether selected subjects have XCP-D outputs available locally."""
    valid_subjects: List[str] = []
    missing_subjects: List[str] = []
    session_details: Dict[str, List[str]] = {}
    normalized_sessions = tuple(_with_prefix(session, "ses-") for session in selected_sessions)

    for subject in selected_subjects:
        sub_label = _with_prefix(subject, "sub-")
        valid_sessions: List[str] = []
        for session in normalized_sessions:
            if _has_xcpd_input(sub_label, session, xcpd_dirs):
                valid_sessions.append(session.removeprefix("ses-"))
        if valid_sessions:
            valid_subjects.append(subject)
            session_details[subject] = valid_sessions
        else:
            missing_subjects.append(subject)

    total = len(selected_subjects)
    valid = len(valid_subjects)
    pct = (valid / total * 100.0) if total else 0.0
    return {
        "total": total,
        "valid": valid,
        "pct": pct,
        "valid_subjects": valid_subjects,
        "missing_subjects": missing_subjects,
        "session_details": session_details,
    }


def _has_xcpd_input(subject: str, session: str, xcpd_dirs: Sequence[str]) -> bool:
    suffixes = (
        "*desc-denoised_bold.nii.gz",
        "*desc-denoised_bold.dtseries.nii",
        "*timeseries.tsv",
        "*timeseries.csv",
    )
    for raw_dir in xcpd_dirs:
        if not raw_dir:
            continue
        base = Path(str(raw_dir)).expanduser()
        if not base.exists():
            continue
        search_roots = [base / subject / session, base / subject, base]
        for root in search_roots:
            if not root.exists():
                continue
            for suffix in suffixes:
                pattern = f"**/{subject}_{session}_{suffix}"
                if any(root.glob(pattern)):
                    return True
    return False


def _with_prefix(value: str, prefix: str) -> str:
    value = str(value)
    return value if value.startswith(prefix) else f"{prefix}{value}"


def _init_state() -> None:
    st.session_state.setdefault(f"{STATE_PREFIX}selected_seed_ids", set())
    st.session_state.setdefault(f"{STATE_PREFIX}previous_atlas", None)
    st.session_state.setdefault(f"{STATE_PREFIX}last_command", "")


def _coerce_selected_seed_set() -> Set[str]:
    selected = st.session_state.get(f"{STATE_PREFIX}selected_seed_ids", set())
    if isinstance(selected, set):
        return selected
    selected_set = set(selected or [])
    st.session_state[f"{STATE_PREFIX}selected_seed_ids"] = selected_set
    return selected_set


def _clear_seed_widget_state() -> None:
    for key in list(st.session_state.keys()):
        if str(key).startswith(f"{STATE_PREFIX}seedcheck_"):
            del st.session_state[key]


def _sync_seed_checkboxes(seed_ids: Iterable[str], checked: bool) -> None:
    selected = _coerce_selected_seed_set()
    for seed_id in seed_ids:
        widget_key = _seed_checkbox_key(seed_id)
        st.session_state[widget_key] = checked
        if checked:
            selected.add(seed_id)
        else:
            selected.discard(seed_id)
    st.session_state[f"{STATE_PREFIX}selected_seed_ids"] = selected


def _seed_checkbox_key(seed_id: str) -> str:
    safe_id = seed_id.replace(" ", "_").replace(":", "__").replace("/", "_")
    return f"{STATE_PREFIX}seedcheck_{safe_id}"


def _get_config() -> Dict[str, Any]:
    return st.session_state.get("config") or _load_config_cached()


def _render_hpc_status(config: Dict[str, Any]) -> None:
    st.subheader("1. HPC connection status")
    hpc = config.get("hpc", {})
    enabled = bool(hpc.get("enabled", False))
    hpc_cfg = HPCConfig.from_config(config)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("HPC", "Enabled" if enabled else "Disabled")
    col2.metric("Host", hpc_cfg.host or "Not set")
    col3.metric("User", hpc_cfg.user or "Not set")
    col4.metric("Partition", hpc_cfg.partition or "Not set")

    remote_paths = hpc.get("remote_paths", {})
    with st.expander("Connection settings", expanded=not enabled):
        c1, c2 = st.columns(2)
        with c1:
            st.text_input("Host", value=hpc_cfg.host, disabled=True, key=f"{STATE_PREFIX}host_display")
            st.text_input("User", value=hpc_cfg.user, disabled=True, key=f"{STATE_PREFIX}user_display")
        with c2:
            st.text_input("Remote base", value=remote_paths.get("base", ""), disabled=True, key=f"{STATE_PREFIX}remote_base_display")
            st.text_input("XCP-D image", value=hpc.get("singularity_images", {}).get("xcp_d", ""), disabled=True, key=f"{STATE_PREFIX}xcpd_image_display")

        if not enabled:
            st.warning("HPC is disabled in Settings. Dry-runs are still available.")
        elif st.button("Test HPC connection", key=f"{STATE_PREFIX}test_connection"):
            try:
                with st.spinner(f"Connecting to {hpc_cfg.host}..."):
                    conn = HPCConnection(hpc_cfg)
                    conn.connect()
                    stdout, stderr, exit_code = conn.execute("hostname && whoami", timeout=20)
                    conn.disconnect()
                if exit_code == 0:
                    st.success(stdout.strip() or "Connection successful")
                else:
                    st.error(stderr.strip() or "Connection command failed")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")


def _render_subject_selection(config: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    st.subheader("2. Subject/session selection")
    bids_dir = config.get("paths", {}).get("bids_dir", "")
    subject_sessions = _scan_bids_subject_sessions(bids_dir)
    if not subject_sessions:
        st.error(f"No BIDS subjects found in `{bids_dir}`.")
        return [], []

    all_subjects = sorted(subject_sessions.keys())
    longitudinal_subjects = [
        subject for subject, sessions in subject_sessions.items() if {"01", "02"}.issubset(set(sessions))
    ]
    all_sessions = sorted({session for sessions in subject_sessions.values() for session in sessions})

    c1, c2, c3 = st.columns(3)
    with c1:
        use_all = st.checkbox("All subjects", value=True, key=f"{STATE_PREFIX}all_subjects")
    with c2:
        longitudinal_only = st.checkbox(
            "Longitudinal only", value=False, key=f"{STATE_PREFIX}longitudinal_only"
        )
    with c3:
        st.metric("Available", len(longitudinal_subjects if longitudinal_only else all_subjects))

    selectable_subjects = longitudinal_subjects if longitudinal_only else all_subjects
    if use_all:
        selected_subjects = selectable_subjects
        st.info(f"Selected all {len(selected_subjects)} subject(s).")
    else:
        default_subjects = selectable_subjects[: min(4, len(selectable_subjects))]
        selected_subjects = st.multiselect(
            "Subjects",
            options=selectable_subjects,
            default=default_subjects,
            format_func=lambda subject: f"sub-{subject}",
            key=f"{STATE_PREFIX}subjects",
        )

    selected_sessions = st.multiselect(
        "Sessions",
        options=all_sessions,
        default=all_sessions,
        format_func=lambda session: f"ses-{session}",
        key=f"{STATE_PREFIX}sessions",
        help="Submitted through --sessions as a comma-separated list.",
    )

    return list(selected_subjects), list(selected_sessions)


def _render_seed_selector(catalog: SeedCatalog) -> Tuple[Optional[str], List[Seed]]:
    st.subheader("3–4. Atlas and seed selection")
    atlases = catalog.list_atlases()
    if not atlases:
        st.error("No atlases found in the seed catalog.")
        return None, []

    previous_atlas = st.session_state.get(f"{STATE_PREFIX}previous_atlas")
    default_index = atlases.index(previous_atlas) if previous_atlas in atlases else 0
    selected_atlas = st.radio(
        "Atlas",
        options=atlases,
        index=default_index,
        key=f"{STATE_PREFIX}atlas",
        horizontal=True,
        help="Changing the atlas refreshes the seed list below.",
    )

    seeds = catalog.get_seeds(atlas=selected_atlas)
    seed_ids_for_atlas = {seed.id for seed in seeds}
    if selected_atlas != previous_atlas:
        st.session_state[f"{STATE_PREFIX}selected_seed_ids"] = set()
        st.session_state[f"{STATE_PREFIX}previous_atlas"] = selected_atlas
        _clear_seed_widget_state()
    else:
        selected_ids = _coerce_selected_seed_set()
        stale_ids = selected_ids - seed_ids_for_atlas
        if stale_ids:
            st.session_state[f"{STATE_PREFIX}selected_seed_ids"] = selected_ids - stale_ids

    if not seeds:
        st.warning(f"No seeds are available for atlas `{selected_atlas}`.")
        return selected_atlas, []

    priority_ids = [seed.id for seed in seeds if seed.source == "priority"]
    network_groups = catalog.group_by_network(selected_atlas)
    network_names = list(network_groups.keys())

    c1, c2, c3 = st.columns([1, 2, 1])
    with c1:
        if st.button("Select all priority", key=f"{STATE_PREFIX}select_priority", disabled=not priority_ids):
            _sync_seed_checkboxes(priority_ids, True)
    with c2:
        selected_network = st.selectbox(
            "Select all in network…",
            options=network_names,
            key=f"{STATE_PREFIX}network_select",
            label_visibility="collapsed",
        )
        if st.button("Select network", key=f"{STATE_PREFIX}select_network"):
            _sync_seed_checkboxes([seed.id for seed in network_groups.get(selected_network, [])], True)
    with c3:
        if st.button("Clear", key=f"{STATE_PREFIX}clear_seeds"):
            _sync_seed_checkboxes(seed_ids_for_atlas, False)
            st.session_state[f"{STATE_PREFIX}selected_seed_ids"] = set()

    selected_ids = _coerce_selected_seed_set()
    rendered_ids: Set[str] = set()
    for network, network_seeds in network_groups.items():
        visible_seeds = [seed for seed in network_seeds if seed.id not in rendered_ids]
        if not visible_seeds:
            continue
        with st.expander(f"{network} ({len(visible_seeds)})", expanded=network == network_names[0]):
            for source, source_seeds in _group_seeds_by_source(visible_seeds).items():
                st.markdown(f"**{SOURCE_LABELS.get(source, source.title())}**")
                for seed in source_seeds:
                    rendered_ids.add(seed.id)
                    widget_key = _seed_checkbox_key(seed.id)
                    if widget_key not in st.session_state:
                        st.session_state[widget_key] = seed.id in selected_ids
                    checked = st.checkbox(
                        _format_seed_label(seed),
                        key=widget_key,
                        help=seed.description or seed.id,
                    )
                    if checked:
                        selected_ids.add(seed.id)
                    else:
                        selected_ids.discard(seed.id)
    st.session_state[f"{STATE_PREFIX}selected_seed_ids"] = selected_ids

    st.caption(f"{len(selected_ids)} of {len(seeds)} seed(s) selected for `{selected_atlas}`.")
    return selected_atlas, [seed for seed in seeds if seed.id in selected_ids]


def _group_seeds_by_source(seeds: Sequence[Seed]) -> Dict[str, List[Seed]]:
    grouped: Dict[str, List[Seed]] = {}
    for seed in sorted(seeds, key=lambda s: (SOURCE_ORDER.get(s.source, 99), s.label.lower())):
        grouped.setdefault(seed.source, []).append(seed)
    return grouped


def _format_seed_label(seed: Seed) -> str:
    coords = _coords_text(seed)
    radius = f", r={seed.radius_mm:g}mm" if seed.radius_mm is not None else ""
    parcel = f", parcel={seed.parcel_index}" if seed.parcel_index is not None else ""
    return f"{seed.label} ({coords}{radius}{parcel})"


def _coords_text(seed: Seed) -> str:
    if seed.coordinates_mni:
        return ", ".join(f"{coord:g}" for coord in seed.coordinates_mni)
    if seed.parcel_index is not None:
        return f"parcel {seed.parcel_index}"
    return "atlas-native"


def _render_selected_seed_summary(selected_seeds: Sequence[Seed]) -> None:
    st.subheader("Selected seed summary")
    if not selected_seeds:
        st.info("Select at least one seed to preview coordinates and radius.")
        return

    rows = [
        {
            "ID": seed.id,
            "Label": seed.label,
            "Source": SOURCE_LABELS.get(seed.source, seed.source),
            "Network": ", ".join(seed.networks or ["Unassigned"]),
            "Coordinates / Parcel": _coords_text(seed),
            "Radius (mm)": seed.radius_mm if seed.radius_mm is not None else "—",
        }
        for seed in selected_seeds
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_analysis_options(config: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, bool]]:
    st.subheader("5–8. Analysis options")
    c1, c2, c3 = st.columns(3)
    with c1:
        confound_strategy = st.selectbox(
            "Confound strategy",
            options=["36P", "36P+spike", "aCompCor", "AROMA"],
            index=0,
            key=f"{STATE_PREFIX}confound_strategy",
        )
    with c2:
        high_pass = st.number_input(
            "High-pass (Hz)",
            min_value=0.0,
            max_value=0.5,
            value=0.01,
            step=0.005,
            format="%.3f",
            key=f"{STATE_PREFIX}high_pass",
        )
    with c3:
        low_pass = st.number_input(
            "Low-pass (Hz)",
            min_value=0.0,
            max_value=0.5,
            value=0.10,
            step=0.005,
            format="%.3f",
            key=f"{STATE_PREFIX}low_pass",
        )

    smoothing_fwhm = st.selectbox(
        "Smoothing FWHM (mm)",
        options=[0, 4, 6, 8],
        index=2,
        key=f"{STATE_PREFIX}smoothing_fwhm",
    )

    st.markdown("**Output measures**")
    o1, o2, o3 = st.columns(3)
    with o1:
        output_z_map = st.checkbox("z-map (Fisher)", value=True, key=f"{STATE_PREFIX}output_z_map")
    with o2:
        output_r_map = st.checkbox("r-map", value=True, key=f"{STATE_PREFIX}output_r_map")
    with o3:
        output_timeseries = st.checkbox(
            "Extracted timeseries", value=True, key=f"{STATE_PREFIX}output_timeseries"
        )

    slurm = config.get("hpc", {}).get("slurm", {})
    with st.expander("9. HPC resources", expanded=False):
        r1, r2, r3 = st.columns(3)
        with r1:
            time_limit = st.text_input(
                "Wall time",
                value=str(slurm.get("xcpd_time") or slurm.get("default_time", "12:00:00")),
                key=f"{STATE_PREFIX}time",
            )
        with r2:
            memory = st.text_input(
                "Memory",
                value=str(slurm.get("xcpd_memory") or slurm.get("default_memory", "64GB")),
                key=f"{STATE_PREFIX}memory",
            )
        with r3:
            cpus = st.number_input(
                "CPUs",
                min_value=1,
                max_value=int(slurm.get("xcpd_max_cpus", 32) or 32),
                value=int(slurm.get("xcpd_cpus") or slurm.get("default_cpus", 8) or 8),
                key=f"{STATE_PREFIX}cpus",
            )
        r4, r5 = st.columns(2)
        with r4:
            partition = st.text_input(
                "Partition",
                value=str(slurm.get("partition", "shared_cpu")),
                key=f"{STATE_PREFIX}partition",
            )
        with r5:
            max_parallel = st.number_input(
                "Max parallel",
                min_value=1,
                max_value=100,
                value=int(slurm.get("max_concurrent_jobs", 4) or 4),
                key=f"{STATE_PREFIX}max_parallel",
            )

    options = {
        "confound_strategy": confound_strategy,
        "high_pass": high_pass,
        "low_pass": low_pass,
        "smoothing_fwhm": smoothing_fwhm,
        "time": time_limit,
        "memory": memory,
        "cpus": int(cpus),
        "partition": partition,
        "max_parallel": int(max_parallel),
    }
    outputs = {
        "z_map": output_z_map,
        "r_map": output_r_map,
        "timeseries": output_timeseries,
    }
    return options, outputs


def _render_preflight(config: Dict[str, Any], selected_subjects: Sequence[str], selected_sessions: Sequence[str]) -> None:
    st.subheader("10. Manifest preflight")
    paths = config.get("paths", {})
    xcpd_dirs = tuple(
        str(paths.get(key, ""))
        for key in ("xcpd_fc_dir", "xcpd_fc_gsr_dir", "xcpd_dir")
        if paths.get(key)
    )
    result = _xcpd_preflight(tuple(selected_subjects), tuple(selected_sessions), xcpd_dirs)
    total = result["total"]
    valid = result["valid"]
    pct = result["pct"]

    col1, col2 = st.columns([1, 3])
    with col1:
        st.metric("Valid XCP-D inputs", f"{valid}/{total}", f"{pct:.0f}%")
    with col2:
        st.progress(pct / 100.0 if total else 0.0, text=f"{pct:.1f}% selected subjects ready")

    if total and valid == total:
        st.success("✅ All selected subjects have local XCP-D inputs for at least one selected session.")
    elif valid:
        st.warning(
            f"⚠️ {total - valid} selected subject(s) do not have detected local XCP-D inputs. "
            "Submission is still allowed in case inputs exist on HPC."
        )
    else:
        st.error("No local XCP-D inputs detected for the current selection. Verify XCP-D outputs or remote paths.")

    with st.expander("Preflight details"):
        st.write("Scanned directories:")
        for path in xcpd_dirs:
            st.code(path, language=None)
        missing = result.get("missing_subjects", [])
        if missing:
            st.caption("Missing local XCP-D inputs: " + ", ".join(f"sub-{s}" for s in missing[:50]))


def _build_submit_options(
    config: Dict[str, Any],
    atlas: str,
    selected_seeds: Sequence[Seed],
    selected_sessions: Sequence[str],
    analysis_options: Dict[str, Any],
    outputs: Dict[str, bool],
) -> Dict[str, Any]:
    hpc_cfg = HPCConfig.from_config(config)
    remote_base = hpc_cfg.remote_base
    paths = config.get("paths", {})
    project_root = paths.get("project_root") or config.get("project_root") or str(Path(__file__).resolve().parents[2])
    output_dir = paths.get("subject_level_fc_dir") or paths.get("subject_level_dir") or paths.get("derivatives_dir")

    options = dict(analysis_options)
    options.update(
        {
            "atlas": atlas,
            "seeds": [seed.id for seed in selected_seeds],
            "sessions": [_with_prefix(session, "ses-") for session in selected_sessions],
            "output_measures": [name for name, enabled in outputs.items() if enabled],
            "output_z_map": outputs["z_map"],
            "output_r_map": outputs["r_map"],
            "output_timeseries": outputs["timeseries"],
            "remote_project_dir": remote_base or project_root,
            "project_root": remote_base or project_root,
            "config": f"{remote_base}/.github/connectivity_config.yaml" if remote_base else ".github/connectivity_config.yaml",
            "log_dir": f"{remote_base}/logs" if remote_base else "logs",
            "output_dir": f"{remote_base}/results" if remote_base else output_dir,
        }
    )
    return options


def _validate_submission(
    subjects: Sequence[str], atlas: Optional[str], selected_seeds: Sequence[Seed], outputs: Dict[str, bool]
) -> List[str]:
    errors: List[str] = []
    if not subjects:
        errors.append("Select at least one subject.")
    if not atlas:
        errors.append("Choose an atlas.")
    if not selected_seeds:
        errors.append("Select at least one seed.")
    if not any(outputs.values()):
        errors.append("Select at least one output measure.")
    return errors


def _render_actions(
    manager: ConnectivityWorkflowManager,
    options: Dict[str, Any],
    subjects: Sequence[str],
    errors: Sequence[str],
) -> None:
    st.subheader("11. Submit")
    if errors:
        for error in errors:
            st.error(error)

    c1, c2 = st.columns(2)
    with c1:
        dry_run = st.button(
            "🔍 Dry-run (preview SLURM)",
            disabled=bool(errors),
            key=f"{STATE_PREFIX}dry_run",
            use_container_width=True,
        )
    with c2:
        submit = st.button(
            "🚀 Submit",
            disabled=bool(errors),
            key=f"{STATE_PREFIX}submit",
            type="primary",
            use_container_width=True,
        )

    if dry_run:
        try:
            submission = manager.submit(
                analysis_type="seed_connectivity",
                options=options,
                subjects=list(subjects),
                dry_run=True,
            )
            command = submission.options.get("command_preview", "")
            st.session_state[f"{STATE_PREFIX}last_command"] = command
            st.success(f"Dry-run recorded: {submission.submission_id}")
            st.code(command, language="bash")
        except Exception as exc:
            st.error(f"Dry-run failed: {exc}")

    if submit:
        try:
            with st.spinner("Submitting seed-based connectivity job..."):
                submission = manager.submit(
                    analysis_type="seed_connectivity",
                    options=options,
                    subjects=list(subjects),
                    dry_run=False,
                )
            if submission.status == "failed":
                st.error(submission.notes or "Submission failed.")
            else:
                st.success(f"Submitted job {submission.job_id or '(job ID pending)'}")
        except Exception as exc:
            st.error(f"Submission failed: {exc}")

    last_command = st.session_state.get(f"{STATE_PREFIX}last_command")
    if last_command and not dry_run:
        with st.expander("Last dry-run command", expanded=False):
            st.code(last_command, language="bash")


def _render_submission_monitor(manager: ConnectivityWorkflowManager) -> None:
    st.subheader("12. Submission monitor")
    submissions = [
        submission
        for submission in manager.list_submissions()
        if submission.analysis_type == "seed_connectivity"
    ]
    if not submissions:
        st.info("No seed_connectivity submissions yet.")
        return

    rows = [_submission_row(submission) for submission in submissions]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    with st.expander("Submission details"):
        for submission in submissions[:10]:
            st.markdown(f"**{submission.submission_id}** · `{submission.status}` · job `{submission.job_id or 'N/A'}`")
            st.json(asdict(submission), expanded=False)


def _submission_row(submission: ConnectivitySubmission) -> Dict[str, Any]:
    options = submission.options or {}
    return {
        "Submitted": submission.submitted_at,
        "Job ID": submission.job_id or "—",
        "Status": submission.status,
        "Subjects": len(submission.subjects),
        "Atlas": options.get("atlas", "—"),
        "Seeds": len(options.get("seeds", []) or []),
        "Outputs": ", ".join(options.get("output_measures", []) or []),
        "Output dir": submission.output_dir or "—",
    }


def render():
    st.title("🎯 Submit Seed-Based Connectivity Analysis")
    _init_state()

    config = _get_config()
    manager = ConnectivityWorkflowManager(config)
    catalog = _load_catalog_cached()

    _render_hpc_status(config)
    st.divider()

    selected_subjects, selected_sessions = _render_subject_selection(config)
    st.divider()

    selected_atlas, selected_seeds = _render_seed_selector(catalog)
    _render_selected_seed_summary(selected_seeds)
    st.divider()

    analysis_options, outputs = _render_analysis_options(config)
    st.divider()

    _render_preflight(config, selected_subjects, selected_sessions)
    st.divider()

    submit_options = (
        _build_submit_options(config, selected_atlas, selected_seeds, selected_sessions, analysis_options, outputs)
        if selected_atlas
        else {}
    )
    errors = _validate_submission(selected_subjects, selected_atlas, selected_seeds, outputs)
    _render_actions(manager, submit_options, selected_subjects, errors)
    st.divider()

    _render_submission_monitor(manager)


if __name__ == "__main__":
    render()
