"""Submit seed-based connectivity analyses (XCP-D backend).

Uses ConnectivityWorkflowManager.build_subject_level_command() with
--analysis seed, --pipeline, --measures, and repeatable --seed flags.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.config import load_config
from utils.connectivity_workflow import ConnectivityWorkflowManager
from utils.seed_catalog import Seed, SeedCatalog
from utils.xcpd_outputs import XcpdDiscovery, KNOWN_PIPELINES

# Import MEASURES names from script directory
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

STATE_PREFIX = "submit_seed_"


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
        return f"atlas-{seed.atlas}_parcel-{seed.parcel_label}"
    if seed.source == "custom_nifti_roi":
        return str(seed.nifti_path or seed.id)
    if seed.source == "sphere":
        x, y, z = seed.coords_mm or (0, 0, 0)
        r = seed.radius_mm or 6.0
        return f"sphere:{seed.name}:{x},{y},{z}:{r}"
    return seed.id


def _render_seed_builder(catalog: SeedCatalog | None) -> None:
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
    else:
        st.info("No seeds added yet.")


def render() -> None:
    st.title("📤 Submit Seed Connectivity")

    # --- Session state defaults ---
    st.session_state.setdefault(f"{STATE_PREFIX}pipeline", "fc")
    st.session_state.setdefault(f"{STATE_PREFIX}subjects", [])
    st.session_state.setdefault(f"{STATE_PREFIX}sessions", [])
    st.session_state.setdefault(f"{STATE_PREFIX}seeds", [])
    st.session_state.setdefault(f"{STATE_PREFIX}measures", ALL_MEASURES)
    st.session_state.setdefault(f"{STATE_PREFIX}bold_variant", "denoisedSmoothed")
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

    # --- Seed builder ---
    catalog: SeedCatalog | None = None
    try:
        catalog = SeedCatalog(Path(bids_root), xcpd_pipeline=pipeline)
    except Exception:
        pass
    _render_seed_builder(catalog)

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

    # --- Command preview ---
    seeds: list[dict] = st.session_state.get(f"{STATE_PREFIX}seeds", [])
    manager = ConnectivityWorkflowManager(config)

    def _build_cmd(dry_run: bool = False) -> str:
        subjects_for_cmd = sel_subjects or all_subjects
        preview_subs = subjects_for_cmd[:1] if subjects_for_cmd else ["sub-033"]
        opts = {
            "pipeline": pipeline,
            "measures": ",".join(sel_measures) if sel_measures else ",".join(ALL_MEASURES),
            "seeds": [sd["token"] for sd in seeds],
            "bids_root": str(bids_root),
            "out_root": out_root,
            "bold_variant": bold_variant,
            "dry_run": dry_run,
        }
        return manager.build_subject_level_command(
            "seed_connectivity", opts, preview_subs
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
    n_seeds = len(seeds)
    n_measures = len(sel_measures or ALL_MEASURES)
    total_jobs = n_sub * n_ses * n_seeds * n_measures

    st.info(
        f"**Preflight:** {n_sub} subjects × {n_ses} sessions × "
        f"{n_seeds} seeds × {n_measures} measures = **{total_jobs} jobs**"
    )
    if total_jobs > 500:
        st.warning("⚠️ Large submission (>500 jobs). Consider narrowing scope.")

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
        if st.button("🚀 Submit", key=f"{STATE_PREFIX}submit_btn", type="primary"):
            if not seeds:
                st.error("Add at least one seed before submitting.")
            else:
                try:
                    subjects_for_submit = sel_subjects or all_subjects
                    opts = {
                        "pipeline": pipeline,
                        "measures": ",".join(sel_measures or ALL_MEASURES),
                        "seeds": [sd["token"] for sd in seeds],
                        "bids_root": str(bids_root),
                        "out_root": out_root,
                        "bold_variant": bold_variant,
                    }
                    sub_obj = manager.submit(
                        "seed_connectivity", opts, subjects_for_submit, dry_run=False
                    )
                    job_id = sub_obj.job_id if sub_obj else "unknown"
                    st.success(f"✅ Submitted! Job ID: **{job_id}**")
                    if st.button("📡 Track on HPC monitor", key=f"{STATE_PREFIX}track_btn"):
                        st.session_state["hpc_monitor_job_id"] = job_id
                except Exception as exc:
                    st.error(f"Submission failed: {exc}")
