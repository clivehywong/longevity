"""Streamlit page for submitting group-level connectivity statistics to HPC."""

from __future__ import annotations

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st


sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.config import load_config
from utils.connectivity_workflow import ConnectivitySubmission, ConnectivityWorkflowManager
from utils.hpc import HPCConfig, HPCConnection
from utils.seed_catalog import load_default_catalog


SESSION_PREFIX = "submit_group_"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_SCRIPT = PROJECT_ROOT / "script" / "hpc_manifest.py"
DEFAULT_FORMULA = "value ~ group * session + age_std + sex_code + fd_std + (1|subject)"
LOCAL_MEASURES = ["fALFF", "ALFF", "ReHo"]
NETWORK_ATLASES = ["DiFuMo256", "Schaefer400", "Schaefer200_Tian"]
NETWORK_GROUPINGS = {
    "None": "none",
    "Yeo7": "yeo7",
    "Yeo17": "yeo17",
}
SOURCE_LABELS = {
    "Local Measures": "local",
    "Seed Connectivity": "seed",
    "Network Connectivity": "network",
}
CORRECTION_LABELS = {
    "GRF (cluster-based)": "grf",
    "TFCE (permutation)": "tfce",
    "FDR": "fdr",
}
MASK_LABELS = {
    "Gray-matter": "gray_matter",
    "Whole-brain": "whole_brain",
    "Custom path": "custom",
}


def _key(name: str) -> str:
    return f"{SESSION_PREFIX}{name}"


@st.cache_data(show_spinner=False)
def _load_cached_config() -> Dict[str, Any]:
    return load_config()


@st.cache_data(show_spinner=False)
def _load_group_csv(path: str, mtime: float) -> pd.DataFrame:  # noqa: ARG001 - mtime invalidates cache
    return pd.read_csv(path)


@st.cache_data(show_spinner=False)
def _load_seed_catalog() -> Dict[str, List[Dict[str, str]]]:
    catalog = load_default_catalog()
    result: Dict[str, List[Dict[str, str]]] = {}
    for atlas in catalog.list_atlases():
        result[atlas] = [
            {
                "id": seed.id,
                "label": seed.label,
                "source": seed.source,
                "networks": ", ".join(seed.networks or ["Unassigned"]),
            }
            for seed in catalog.get_seeds(atlas=atlas)
        ]
    return result


@st.cache_data(show_spinner=False)
def _load_manifest_data(path: str, mtime: float) -> Dict[str, Any]:  # noqa: ARG001 - mtime invalidates cache
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _project_root(config: Dict[str, Any]) -> Path:
    return Path(
        config.get("project_root")
        or config.get("paths", {}).get("project_root")
        or PROJECT_ROOT
    ).expanduser()


def _group_csv_path(config: Dict[str, Any]) -> Path:
    return _project_root(config) / "group.csv"


def _load_group_table(config: Dict[str, Any]) -> Tuple[Optional[pd.DataFrame], Optional[str], Path]:
    group_path = _group_csv_path(config)
    if not group_path.exists():
        return None, f"group.csv not found at `{group_path}`.", group_path
    try:
        return _load_group_csv(str(group_path), group_path.stat().st_mtime), None, group_path
    except Exception as exc:  # pragma: no cover - displayed in UI
        return None, f"Could not read `{group_path}`: {exc}", group_path


def _normalise_subject_id(value: Any) -> str:
    text = str(value).strip()
    return text if text.startswith("sub-") else f"sub-{text}"


def _manifest_candidates(config: Dict[str, Any]) -> List[Path]:
    root = _project_root(config)
    paths = config.get("paths", {})
    candidates = [
        Path(paths.get("subject_level_dir", root / "derivatives" / "subject_level")) / ".manifest.json",
        root / "results" / ".manifest.json",
        root / "derivatives" / "connectivity-difumo256" / "subject-level" / ".manifest.json",
    ]
    unique: List[Path] = []
    for candidate in candidates:
        candidate = candidate.expanduser()
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _load_manifest(config: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[Path], str]:
    for candidate in _manifest_candidates(config):
        if candidate.exists():
            try:
                data = _load_manifest_data(str(candidate), candidate.stat().st_mtime)
                return data, candidate, "Loaded"
            except Exception as exc:
                return {}, candidate, f"Unreadable: {exc}"
    return {}, None, "Missing"


def _load_manifest_manager(manifest_path: Optional[Path]):
    if manifest_path is None or not manifest_path.exists() or not MANIFEST_SCRIPT.exists():
        return None
    try:
        spec = importlib.util.spec_from_file_location("hpc_manifest", MANIFEST_SCRIPT)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.ManifestManager(str(manifest_path))
    except Exception:
        return None


def _hpc_remote_project_dir(config: Dict[str, Any]) -> str:
    remote = config.get("hpc", {}).get("remote_paths", {})
    return remote.get("base", "") or str(_project_root(config))


def _default_subject_job_id(manager: ConnectivityWorkflowManager) -> str:
    for submission in manager.list_submissions():
        if submission.analysis_type != "group_stats" and submission.job_id and submission.job_id != "DRY_RUN":
            return str(submission.job_id)
    return ""


def _render_hpc_status(config: Dict[str, Any]) -> None:
    st.subheader("1. HPC connection status")
    hpc = config.get("hpc", {})
    remote = hpc.get("remote_paths", {})

    cols = st.columns(4)
    cols[0].metric("HPC", "Enabled" if hpc.get("enabled") else "Disabled", border=True)
    cols[1].metric("Host", hpc.get("host") or "not set", border=True)
    cols[2].metric("User", hpc.get("user") or "not set", border=True)
    cols[3].metric("Partition", hpc.get("slurm", {}).get("partition", "shared_cpu"), border=True)
    st.caption(f"Remote project: `{remote.get('base', '') or 'not set'}`")

    if not hpc.get("enabled"):
        st.warning("HPC is disabled in Settings. Dry-runs are still saved locally; submission requires HPC settings.")

    with st.expander("Test SSH connection", expanded=False):
        if st.button("Test connection", key=_key("test_connection")):
            try:
                hpc_cfg = HPCConfig.from_config(config)
                with st.spinner(f"Connecting to {hpc_cfg.host}..."):
                    conn = HPCConnection(hpc_cfg)
                    conn.connect()
                    stdout, stderr, exit_code = conn.execute("hostname && whoami", timeout=20)
                    conn.disconnect()
                if exit_code == 0:
                    st.success(stdout.strip())
                else:
                    st.error(stderr.strip() or "Connection command failed.")
            except Exception as exc:
                st.error(f"Connection failed: {exc}")


def _render_source_filters(seed_catalog: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    st.subheader("2–3. Analysis source and cascading filters")
    source_label = st.radio(
        "Analysis source",
        list(SOURCE_LABELS.keys()),
        horizontal=True,
        key=_key("analysis_source"),
    )
    source = SOURCE_LABELS[source_label]
    options: Dict[str, Any] = {"analysis_source": source, "analysis_source_label": source_label}

    if source == "local":
        measures = st.multiselect(
            "Local measure(s)",
            LOCAL_MEASURES,
            default=["fALFF", "ALFF", "ReHo"],
            key=_key("local_measures"),
        )
        options["measures"] = measures
    elif source == "seed":
        atlases = sorted(seed_catalog.keys()) or NETWORK_ATLASES
        atlas = st.selectbox("Atlas", atlases, key=_key("seed_atlas"))
        seed_rows = seed_catalog.get(atlas, [])
        seed_labels = {f"{row['label']} ({row['id']})": row["id"] for row in seed_rows}
        selected_labels = st.multiselect(
            "Seeds",
            list(seed_labels.keys()),
            default=list(seed_labels.keys())[: min(5, len(seed_labels))],
            key=_key("seed_labels"),
        )
        seeds = [seed_labels[label] for label in selected_labels]
        if seed_rows:
            with st.expander("Seed catalog preview", expanded=False):
                st.dataframe(seed_rows[:50], hide_index=True, width="stretch")
        options.update({"atlas": atlas, "seeds": seeds})
    else:
        atlas = st.selectbox("Atlas", NETWORK_ATLASES, key=_key("network_atlas"))
        grouping_label = st.radio(
            "Network grouping",
            list(NETWORK_GROUPINGS.keys()),
            horizontal=True,
            key=_key("network_grouping_label"),
        )
        options.update({"atlas": atlas, "network_grouping": NETWORK_GROUPINGS[grouping_label]})

    return options


def _render_group_table(config: Dict[str, Any]) -> Tuple[Optional[pd.DataFrame], List[str], bool]:
    st.subheader("4–6. Group definitions and LME model")
    group_df, error, group_path = _load_group_table(config)
    if error or group_df is None:
        st.error(error or "group.csv is unavailable.")
        return None, [], False

    st.caption(f"Loaded `{group_path}`")
    st.dataframe(group_df.head(10), hide_index=True, width="stretch")

    columns = list(group_df.columns)
    subject_col = "subject_id" if "subject_id" in columns else columns[0]
    covariate_options = [col for col in columns if col not in {subject_col, "group"}]
    default_covariates = [col for col in ["age", "age_std", "sex", "sex_code", "fd", "fd_std", "session"] if col in covariate_options]

    formula = st.text_area(
        "Model formula",
        value=DEFAULT_FORMULA,
        key=_key("model_formula"),
        help="Linear mixed-effects formula passed through to the group statistics submission metadata.",
    )
    covariates = st.multiselect(
        "Covariates detected from group.csv",
        covariate_options,
        default=default_covariates,
        key=_key("covariates"),
    )
    st.session_state[_key("model_formula_value")] = formula
    st.session_state[_key("covariates_value")] = covariates
    return group_df, covariates, True


def _render_correction_and_mask() -> Dict[str, Any]:
    st.subheader("7–8. Multiple-comparison correction and mask")
    correction_label = st.radio(
        "Correction method",
        list(CORRECTION_LABELS.keys()),
        horizontal=True,
        key=_key("correction_label"),
    )
    correction_method = CORRECTION_LABELS[correction_label]
    options: Dict[str, Any] = {"correction_method": correction_method}

    if correction_method == "grf":
        col1, col2 = st.columns(2)
        with col1:
            options["cluster_forming_p"] = st.number_input(
                "Cluster-forming threshold (p<)",
                min_value=0.0001,
                max_value=0.05,
                value=0.001,
                step=0.0005,
                format="%.4f",
                key=_key("cluster_forming_p"),
            )
        with col2:
            options["cluster_p"] = st.number_input(
                "Cluster p threshold",
                min_value=0.001,
                max_value=0.20,
                value=0.05,
                step=0.005,
                format="%.3f",
                key=_key("cluster_p"),
            )
    elif correction_method == "tfce":
        options["n_permutations"] = st.selectbox(
            "Number of permutations",
            [1000, 5000, 10000],
            index=1,
            key=_key("n_permutations"),
        )
        if options["n_permutations"] < 5000:
            st.warning("TFCE publication analyses should generally use ≥5000 permutations.")
    else:
        options["q_threshold"] = st.number_input(
            "FDR q threshold",
            min_value=0.001,
            max_value=0.20,
            value=0.05,
            step=0.005,
            format="%.3f",
            key=_key("q_threshold"),
        )

    mask_label = st.radio("Mask", list(MASK_LABELS.keys()), horizontal=True, key=_key("mask_label"))
    options["mask"] = MASK_LABELS[mask_label]
    if options["mask"] == "custom":
        options["custom_mask"] = st.text_input("Custom mask path", key=_key("custom_mask"))
    return options


def _count_manifest_subjects(
    manifest: Dict[str, Any],
    source_options: Dict[str, Any],
    group_subjects: List[str],
    manager: Any = None,
) -> Dict[str, Any]:
    tasks = manifest.get("tasks", {}) if isinstance(manifest, dict) else {}
    expected_subjects = set(group_subjects)

    if source_options["analysis_source"] == "local":
        required_pairs = [("N/A", "N/A")]
    elif source_options["analysis_source"] == "seed":
        required_pairs = [(seed, source_options.get("atlas", "")) for seed in source_options.get("seeds", [])]
    else:
        required_pairs = [("N/A", source_options.get("atlas", ""))]

    if manager is not None and required_pairs:
        manager_counts = [manager.get_completion_rate(seed, atlas) for seed, atlas in required_pairs]
    else:
        manager_counts = []

    subjects_by_pair: Dict[Tuple[str, str], set] = {pair: set() for pair in required_pairs}
    totals_by_pair: Dict[Tuple[str, str], int] = {pair: 0 for pair in required_pairs}
    for task in tasks.values():
        if not isinstance(task, dict):
            continue
        pair = (str(task.get("seed", "")), str(task.get("atlas", "")))
        if pair not in subjects_by_pair:
            continue
        totals_by_pair[pair] += 1
        if task.get("status") == "complete":
            subject = _normalise_subject_id(task.get("subject_id", ""))
            if not expected_subjects or subject in expected_subjects:
                subjects_by_pair[pair].add(subject)

    if not required_pairs:
        complete_subjects: set = set()
    else:
        complete_sets = [subjects_by_pair[pair] for pair in required_pairs]
        complete_subjects = set.intersection(*complete_sets) if complete_sets else set()

    total_available = len(group_subjects)
    completed = len(complete_subjects)
    percent = (completed / total_available * 100) if total_available else 0.0
    return {
        "completed": completed,
        "total": total_available,
        "percent": percent,
        "required_pairs": required_pairs,
        "task_totals": totals_by_pair,
        "manager_counts": manager_counts,
    }


def _badge(label: str, color: str) -> None:
    st.markdown(
        f"<span style='background:{color};color:white;padding:0.25rem 0.6rem;"
        f"border-radius:999px;font-weight:600'>{label}</span>",
        unsafe_allow_html=True,
    )


def _render_manifest_preflight(
    config: Dict[str, Any],
    group_df: Optional[pd.DataFrame],
    source_options: Dict[str, Any],
) -> Dict[str, Any]:
    st.subheader("9–10. Subject inclusion and manifest preflight")
    if group_df is None or group_df.empty:
        st.error("group.csv must be readable before manifest preflight can run.")
        return {"ready": False, "completed": 0, "total": 0, "percent": 0.0, "threshold": 80}

    threshold = st.slider(
        "Min subjects for inclusion (% of group.csv subjects)",
        min_value=50,
        max_value=100,
        value=80,
        step=5,
        key=_key("min_subjects_pct"),
    )

    subject_col = "subject_id" if "subject_id" in group_df.columns else group_df.columns[0]
    group_subjects = sorted({_normalise_subject_id(value) for value in group_df[subject_col].dropna()})
    manifest, manifest_path, manifest_status = _load_manifest(config)
    manifest_manager = _load_manifest_manager(manifest_path)
    counts = _count_manifest_subjects(manifest, source_options, group_subjects, manifest_manager)
    ready = counts["percent"] >= threshold and counts["total"] > 0

    if ready:
        badge_label, badge_color = "GREEN · ready", "#16a34a"
    elif counts["completed"] > 0:
        badge_label, badge_color = "YELLOW · incomplete", "#ca8a04"
    else:
        badge_label, badge_color = "RED · missing", "#dc2626"

    cols = st.columns(4)
    with cols[0]:
        _badge(badge_label, badge_color)
    cols[1].metric("Subjects ready", f"{counts['completed']}/{counts['total']}", border=True)
    cols[2].metric("Completion", f"{counts['percent']:.1f}%", border=True)
    cols[3].metric("Threshold", f"{threshold}%", border=True)

    if manifest_path:
        st.caption(f"Manifest: `{manifest_path}` · Status: {manifest_status} · Validator: `{MANIFEST_SCRIPT}`")
    else:
        st.caption(f"No manifest found. Checked: {', '.join(f'`{p}`' for p in _manifest_candidates(config))}")

    with st.expander("Required upstream outputs", expanded=False):
        rows = []
        for seed, atlas in counts["required_pairs"]:
            rows.append(
                {
                    "seed": seed,
                    "atlas": atlas,
                    "manifest_tasks": counts["task_totals"].get((seed, atlas), 0),
                }
            )
        st.dataframe(rows, hide_index=True, width="stretch")

    return {**counts, "ready": ready, "threshold": threshold, "manifest_path": str(manifest_path or "")}


def _parse_time_hours(time_limit: str) -> float:
    try:
        days = 0
        text = str(time_limit).strip()
        if "-" in text:
            day_text, text = text.split("-", 1)
            days = int(day_text)
        parts = [int(part) for part in text.split(":")]
        if len(parts) == 3:
            hours, minutes, seconds = parts
        elif len(parts) == 2:
            hours, minutes, seconds = 0, parts[0], parts[1]
        else:
            hours, minutes, seconds = parts[0], 0, 0
        return days * 24 + hours + minutes / 60 + seconds / 3600
    except Exception:
        return 0.0


def _render_hpc_resources(config: Dict[str, Any], correction_method: str, manager: ConnectivityWorkflowManager) -> Dict[str, Any]:
    slurm = config.get("hpc", {}).get("slurm", {})
    recommended_time = "12:00:00" if correction_method == "tfce" else "02:00:00"
    min_hours = 12 if correction_method == "tfce" else 2

    with st.expander("11. HPC resources", expanded=False):
        default_job = _default_subject_job_id(manager) or "DRY_RUN"
        subject_job_id = st.text_input(
            "Subject-level dependency job ID",
            value=default_job,
            key=_key("subject_job_id"),
            help="Used as --subject-job-id for afterok dependency chaining. Leave blank only for dry-run inspection.",
        )
        col1, col2, col3 = st.columns(3)
        with col1:
            cpus = st.number_input("CPUs", min_value=1, max_value=64, value=int(slurm.get("default_cpus", 8)), key=_key("cpus"))
        with col2:
            memory = st.text_input("Memory", value=str(slurm.get("default_memory", "32GB")), key=_key("memory"))
        with col3:
            time_limit = st.text_input("Wall time", value=recommended_time, key=_key(f"time_{correction_method}"))

        col4, col5 = st.columns(2)
        with col4:
            partition = st.text_input("Partition", value=str(slurm.get("partition", "shared_cpu")), key=_key("partition"))
        with col5:
            max_parallel = st.number_input("Max parallel jobs", min_value=1, max_value=256, value=10, key=_key("max_parallel"))

    chosen_hours = _parse_time_hours(time_limit)
    if chosen_hours and chosen_hours < min_hours:
        st.warning(f"Recommended wall time for {correction_method.upper()} is ≥{min_hours}h; selected `{time_limit}` may be too low.")

    return {
        "subject_job_id": subject_job_id.strip(),
        "cpus": cpus,
        "memory": memory,
        "time": time_limit,
        "partition": partition,
        "max_parallel": max_parallel,
        "remote_project_dir": _hpc_remote_project_dir(config),
        "project_dir": str(_project_root(config)),
    }


def _build_options(
    config: Dict[str, Any],
    source_options: Dict[str, Any],
    correction_options: Dict[str, Any],
    resource_options: Dict[str, Any],
    covariates: List[str],
    preflight: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        **source_options,
        **correction_options,
        **resource_options,
        "model_formula": st.session_state.get(_key("model_formula_value"), DEFAULT_FORMULA),
        "covariates": covariates,
        "min_subjects_pct": preflight.get("threshold"),
        "manifest_path": preflight.get("manifest_path", ""),
        "group_csv": str(_group_csv_path(config)),
        "output_dir": config.get("paths", {}).get("group_level_dir"),
    }


def _validate(source_options: Dict[str, Any], options: Dict[str, Any], group_ok: bool, preflight: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    if source_options.get("analysis_source") not in SOURCE_LABELS.values():
        errors.append("Choose an analysis source.")
    if source_options.get("analysis_source") == "local" and not source_options.get("measures"):
        errors.append("Select at least one local measure.")
    if source_options.get("analysis_source") == "seed" and not source_options.get("seeds"):
        errors.append("Select at least one seed.")
    if not str(options.get("model_formula", "")).strip():
        errors.append("Model formula cannot be empty.")
    if not group_ok:
        errors.append("group.csv must be readable.")
    if not preflight.get("ready"):
        errors.append("Manifest preflight is below the selected inclusion threshold.")
    if options.get("mask") == "custom" and not options.get("custom_mask"):
        errors.append("Provide a custom mask path or choose a built-in mask.")
    return errors


def _render_actions(
    manager: ConnectivityWorkflowManager,
    options: Dict[str, Any],
    validation_errors: List[str],
    subjects: List[str],
) -> None:
    st.subheader("12. Actions")
    preview_command = manager.build_group_level_command(dict(options))
    st.code(preview_command, language="bash")

    if validation_errors:
        st.error(" ".join(validation_errors))

    col1, col2 = st.columns(2)
    with col1:
        dry_run = st.button("🔍 Dry-run", key=_key("dry_run"), disabled=bool(validation_errors))
    with col2:
        submit = st.button("🚀 Submit", type="primary", key=_key("submit"), disabled=bool(validation_errors))

    if dry_run:
        submission = manager.submit("group_stats", options, subjects=subjects, dry_run=True)
        st.success(f"Dry-run saved with job_id={submission.job_id}.")
        st.code(submission.options.get("command_preview", preview_command), language="bash")

    if submit:
        try:
            with st.spinner("Submitting group-level statistics job array..."):
                submission = manager.submit("group_stats", options, subjects=subjects, dry_run=False)
            if submission.status == "failed":
                st.error(submission.notes or "Submission failed.")
            else:
                st.success(f"Submitted group_stats job: {submission.job_id or 'pending job id'}")
        except Exception as exc:
            st.error(f"Submission failed: {exc}")


def _status_icon(status: str) -> str:
    return {
        "submitted": "🟡",
        "running": "🔵",
        "completed": "🟢",
        "failed": "🔴",
        "cancelled": "⚪",
    }.get(status, "⚪")


def _submission_row(submission: ConnectivitySubmission) -> Dict[str, Any]:
    options = submission.options
    return {
        "submitted_at": submission.submitted_at,
        "status": f"{_status_icon(submission.status)} {submission.status}",
        "job_id": submission.job_id or "",
        "source": options.get("analysis_source_label") or options.get("analysis_source", ""),
        "correction": options.get("correction_method", ""),
        "atlas": options.get("atlas", ""),
        "selections": ", ".join(options.get("measures") or options.get("seeds") or [options.get("network_grouping", "")]),
        "output_dir": submission.output_dir or "",
    }


def _render_monitor(manager: ConnectivityWorkflowManager) -> None:
    st.subheader("13. Submission monitor")
    submissions = [submission for submission in manager.list_submissions() if submission.analysis_type == "group_stats"]

    if st.button("🔄 Refresh group_stats statuses", key=_key("refresh_statuses")):
        for submission in submissions:
            if submission.job_id and submission.job_id != "DRY_RUN" and submission.status in {"submitted", "running"}:
                try:
                    manager.refresh_status(submission.submission_id)
                except Exception as exc:
                    st.warning(f"Could not refresh {submission.job_id}: {exc}")
        submissions = [submission for submission in manager.list_submissions() if submission.analysis_type == "group_stats"]

    if not submissions:
        st.info("No past group_stats submissions yet.")
        return

    st.dataframe([_submission_row(submission) for submission in submissions], hide_index=True, width="stretch")
    with st.expander("Submission details", expanded=False):
        labels = [f"{s.submitted_at} · {s.job_id or 'no job id'} · {s.status}" for s in submissions]
        selected_label = st.selectbox("Select submission", labels, key=_key("monitor_selection"))
        selected = submissions[labels.index(selected_label)]
        st.json(
            {
                "submission_id": selected.submission_id,
                "job_id": selected.job_id,
                "status": selected.status,
                "subjects": selected.subjects,
                "options": selected.options,
                "output_dir": selected.output_dir,
                "notes": selected.notes,
            }
        )


def render():
    st.title("👥 Submit Group-Level Statistics")

    st.session_state.setdefault(_key("last_rendered"), datetime.now().isoformat())
    config = st.session_state.get("config") or _load_cached_config()
    manager = ConnectivityWorkflowManager(config)

    _render_hpc_status(config)
    seed_catalog = _load_seed_catalog()
    source_options = _render_source_filters(seed_catalog)
    group_df, covariates, group_ok = _render_group_table(config)
    correction_options = _render_correction_and_mask()
    preflight = _render_manifest_preflight(config, group_df, source_options)
    resource_options = _render_hpc_resources(config, correction_options["correction_method"], manager)

    options = _build_options(config, source_options, correction_options, resource_options, covariates, preflight)
    validation_errors = _validate(source_options, options, group_ok, preflight)
    subject_col = "subject_id" if group_df is not None and "subject_id" in group_df.columns else None
    subjects = (
        sorted({_normalise_subject_id(value) for value in group_df[subject_col].dropna()})
        if group_df is not None and subject_col
        else []
    )

    _render_actions(manager, options, validation_errors, subjects)
    _render_monitor(manager)
    st.caption(f"Last rendered: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    render()
