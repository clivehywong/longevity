"""Submit group-level statistics (XCP-D backend).

Supports three top-level kinds:
  Voxel  — alff / reho / seed-<id> maps via GRF / TFCE / FDR
  Matrix — network or seed correlation matrices via paired_t_fdr / nbs / tfnbs
  Mixed-Design TFCE — Paired pre/post × 2-group mixed ANOVA (longitudinal intervention)

Uses ConnectivityWorkflowManager.build_group_level_command() for Voxel/Matrix.
For Mixed-Design, uses MixedDesignBuilder + SubjectDataValidator + group_mixed_design_stats.py.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from utils.config import load_config
from utils.connectivity_workflow import ConnectivityWorkflowManager
from utils.xcpd_outputs import KNOWN_PIPELINES
from utils.seed_catalog import SeedCatalog, Seed
from utils.seed_viz import make_seed_preview_png, cli_token_to_seed_dir_name
from utils.group_stats_design import MixedDesignBuilder
from utils.group_stats_validation import SubjectDataValidator

STATE_PREFIX = "submit_group_"

_DEFAULT_OUT_ROOT = "derivatives/connectivity/group/"


def _get_config() -> dict:
    return st.session_state.get("config") or load_config()


def _default_participants_path(bids_root: str) -> str:
    participants_tsv = Path(bids_root) / "bids" / "participants.tsv"
    legacy_group_csv = Path(bids_root) / "group.csv"
    return str(
        participants_tsv if participants_tsv.exists() or not legacy_group_csv.exists()
        else legacy_group_csv
    )


def _read_subject_table(csv_path: str) -> Any:
    import pandas as pd

    path = Path(csv_path)
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    df = pd.read_csv(path, sep=sep)

    if "subject_id" in df.columns and "participant_id" not in df.columns:
        df = df.rename(columns={"subject_id": "participant_id"})
    if "subject" in df.columns and "participant_id" not in df.columns:
        df = df.copy()
        df["participant_id"] = df["subject"].apply(_format_participant_id)

    return df


def _format_participant_id(value: Any) -> str:
    subject = str(value).strip()
    if subject.startswith("sub-"):
        return subject
    digits = "".join(ch for ch in subject if ch.isdigit())
    if digits:
        return f"sub-{int(digits):03d}"
    return subject


def _scan_seed_ids(bids_root: str, pipeline: str) -> list[str]:
    """Scan derivatives/connectivity/<pipeline>/sub-*/ses-*/seed/ for seed IDs."""
    base = Path(bids_root) / "derivatives" / "connectivity" / pipeline
    seed_ids: set[str] = set()
    for p in base.glob("sub-*/ses-*/seed/*/"):
        if p.is_dir():
            seed_ids.add(p.name)
    return sorted(seed_ids)


def _read_group_csv_columns(csv_path: str) -> list[str]:
    """Return metadata column names for the contrast builder."""
    try:
        return list(_read_subject_table(csv_path).columns)
    except Exception:
        return []


def _build_contrast_options(csv_path: str) -> list[str]:
    opts = ["ses-02_minus_ses-01", "group-walking_minus_control"]
    for col in _read_group_csv_columns(csv_path):
        if col not in ("subject", "subject_id", "participant_id", "session", "group"):
            opts.append(f"correlation_{col}")
    return opts


def _load_seed_catalog(bids_root: str, pipeline: str) -> SeedCatalog | None:
    """Load seed catalog from local XCP-D outputs."""
    try:
        return SeedCatalog(Path(bids_root), xcpd_pipeline=pipeline)
    except Exception:
        return None


def _list_computed_seeds(bids_root: str, pipeline: str) -> list[str]:
    """List seeds with subject-level outputs as CLI tokens.

    Scans derivatives/connectivity/{pipeline}/sub-*/ses-*/seed/ and converts
    dir names back to CLI tokens using the canonical mapping.
    """
    base = Path(bids_root) / "derivatives" / "connectivity" / pipeline
    seed_dirs: set[str] = set()
    for p in base.glob("sub-*/ses-*/seed/*/"):
        if p.is_dir():
            seed_dirs.add(p.name)
    return sorted(_dir_name_to_cli_token(d) for d in seed_dirs)


def _dir_name_to_cli_token(dir_name: str) -> str:
    """Convert on-disk seed dir name back to CLI token format."""
    import re  # noqa: PLC0415
    # sphere-{x}_{y}_{z}_r{r}  →  sphere:{x},{y},{z},r={r}
    m = re.match(r"sphere-([-\d]+)_([-\d]+)_([-\d]+)_r([\d]+)$", dir_name)
    if m:
        return f"sphere:{m.group(1)},{m.group(2)},{m.group(3)},r={m.group(4)}"
    # atlas-{atlas}_parcel-{label}  →  atlas-{atlas}:{label}
    m = re.match(r"(atlas-[^_]+)_parcel-(.+)$", dir_name)
    if m:
        return f"{m.group(1)}:{m.group(2)}"
    # custom-{name}  →  keep as-is
    return dir_name


def _seed_token_display(token: str) -> str:
    """Human-readable label for a CLI seed token."""
    import re  # noqa: PLC0415
    if token.startswith("sphere:"):
        m = re.match(r"sphere:([-\d.]+),([-\d.]+),([-\d.]+),r=([\d.]+)(?:,name=(.+))?", token)
        if m:
            name = m.group(5) or f"({m.group(1)}, {m.group(2)}, {m.group(3)})"
            return f"🔵 {name}  r={m.group(4)} mm"
    if token.startswith("atlas-"):
        m = re.match(r"atlas-([^:]+):(.+)$", token)
        if m:
            return f"🟠 {m.group(2)}  [{m.group(1)}]"
    return token


@st.cache_data(show_spinner=False, ttl=3600)
def _cached_seed_preview(token: str, bids_root_str: str) -> bytes | None:
    return make_seed_preview_png(token, bids_root_str)


def _seed_to_cli_format(seed_str: str) -> str:
    """Convert seed UI string to CLI format."""
    if ":" in seed_str or seed_str.startswith("nifti:"):
        return seed_str
    return f"atlas-4S256Parcels:{seed_str}"


def _build_subject_selection_df(validation_df: pd.DataFrame, fd_cutoff: float = 0.5) -> pd.DataFrame:
    """Build a subject-level selection DF (one row per subject) from session-level validation.

    A subject is included by default only if:
    - All sessions have a valid zmap (fully complete)
    - max mean FD across sessions does not exceed fd_cutoff (or FD is unknown)
    """
    rows = []
    for subject, grp in validation_df.groupby("subject", sort=False):
        group = grp["group"].iloc[0]
        valid_mask = grp["exists"] & grp["error"].isna()
        n_valid = int(valid_mask.sum())
        n_total = len(grp)
        failure_stages = grp.loc[~valid_mask, "error"].dropna().unique().tolist()
        failure_stage = failure_stages[0] if failure_stages else ""
        if n_valid == n_total:
            status = "✅ complete"
        elif n_valid > 0:
            status = "⚠️ partial"
        else:
            status = "❌ none"
        # FD: max mean-FD across sessions (NaN if not available)
        fd_vals = grp["mean_fd"].dropna() if "mean_fd" in grp.columns else pd.Series(dtype=float)
        max_fd = float(fd_vals.max()) if len(fd_vals) > 0 else float("nan")
        fd_ok = pd.isna(max_fd) or max_fd <= fd_cutoff
        rows.append({
            "include": n_valid == n_total and fd_ok,
            "subject": subject,
            "group": group,
            "complete": f"{n_valid}/{n_total} sessions",
            "max_fd": round(max_fd, 3) if not pd.isna(max_fd) else None,
            "status": status,
            "failure_stage": failure_stage,
        })
    return pd.DataFrame(rows)


def _preview_design(control: list[str], walking: list[str]) -> None:
    """Display design matrix preview for the given subject lists."""
    if not control and not walking:
        st.warning("No subjects selected.")
        return
    if not control:
        st.error("No control subjects selected.")
        return
    if not walking:
        st.error("No walking subjects selected.")
        return
    builder = MixedDesignBuilder.from_paired_two_group(control, walking)
    design_mat, _, _, _ = builder.build()
    st.info(
        f"**Design Matrix:** shape {design_mat.shape}, "
        f"rank {int(np.linalg.matrix_rank(design_mat))}  \n"
        f"Subjects: {len(control)} control, {len(walking)} walking · 2 sessions (pre/post)"
    )
    col_names = (
        ["Time (+1=pre, −1=post)", "Group (+1=ctrl, −1=walk)"]
        + [f"subj_{i + 1}" for i in range(len(control) + len(walking))]
    )
    with st.expander("View sample rows (first 6)"):
        st.dataframe(
            pd.DataFrame(design_mat[:6], columns=col_names[:design_mat.shape[1]]),
            use_container_width=True,
        )


def _write_filtered_canonical_tsv(
    validation_df: pd.DataFrame,
    selection_df: pd.DataFrame,
    seed_dir_name: str,
    bids_root: Any,
) -> str:
    """
    Write a filtered canonical TSV in expanded row_index/subject/session/group format
    for only the selected (included) subjects — both sessions per subject.

    Returns the path to the written TSV.
    """
    import time as _time
    included_subjects = set(selection_df[selection_df["include"]]["subject"].tolist())
    filtered = validation_df[validation_df["subject"].isin(included_subjects)].copy()
    filtered = filtered.sort_values(["group", "subject", "session"]).reset_index(drop=True)
    filtered["row_index"] = range(len(filtered))
    out_cols = ["row_index", "subject", "session", "group"]
    out_df = filtered[out_cols]

    out_dir = Path(bids_root) / "tmp" / "group_stats_subsets"
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_seed = seed_dir_name.replace("/", "_").replace(":", "_")
    tsv_path = out_dir / f"{safe_seed}_{int(_time.time())}.tsv"
    out_df.to_csv(tsv_path, sep="\t", index=False)
    return str(tsv_path)


def _build_group_cmd(
    bids_root: Any,
    seed: str,
    pipeline: str,
    measure: str,
    canonical_csv: str,
    n_perm: int,
    correction: str,
    mask: str | None,
    execution: str,
    hpc_remote_base: str | None = None,
) -> str:
    """Build the analysis command string for preview."""
    effective_bids = hpc_remote_base if execution == "HPC" and hpc_remote_base else str(bids_root)
    effective_csv = (
        canonical_csv.replace(str(bids_root), hpc_remote_base, 1)
        if execution == "HPC" and hpc_remote_base and canonical_csv.startswith(str(bids_root))
        else canonical_csv
    )
    effective_mask = (
        mask.replace(str(bids_root), hpc_remote_base, 1)
        if execution == "HPC" and hpc_remote_base and mask and mask.startswith(str(bids_root))
        else mask
    )

    if correction.upper() == "PARAMETRIC":
        parts = [
            "python ../script/group_lmm_stats.py",
            f"  --bids-root {effective_bids}",
            f"  --seed {seed}",
            f"  --pipeline {pipeline}",
            f"  --measure {measure}",
            f"  --canonical-csv {effective_csv}",
        ]
        if effective_mask:
            parts.append(f"  --mask-path {effective_mask}")
        return " \\\n".join(parts)

    parts = [
        "python neuconn_app/scripts/group_mixed_design_stats.py",
        f"  --bids-root {effective_bids}",
        f"  --seed {seed}",
        f"  --pipeline {pipeline}",
        f"  --measure {measure}",
        f"  --n-perms {n_perm}",
        f"  --correction {correction}",
        f"  --canonical-csv {effective_csv}",
    ]
    if effective_mask:
        parts.append(f"  --mask-path {effective_mask}")
    return " \\\n".join(parts)


def _render_mixed_design_section(config: dict, bids_root: str) -> None:
    """Render mixed-design TFCE workflow section."""
    
    st.subheader("🧬 Mixed-Design TFCE Analysis")
    
    st.markdown("""
    **Paired pre/post × 2-group mixed ANOVA** for longitudinal intervention studies.
    
    - **Input**: 72 zmaps (36 subjects × 2 sessions, ~20 control, ~16 walking)
    - **Output**: FSL randomise results with TFCE / Cluster / FDR correction
    - **Design**: Time effect, group effect, subject intercepts
    """)
    
    # ===== Section 1: Analysis Setup =====
    st.markdown("#### 📋 Section 1: Analysis Setup")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        pipeline = st.selectbox(
            "Pipeline",
            KNOWN_PIPELINES,
            index=KNOWN_PIPELINES.index(
                st.session_state.get(f"{STATE_PREFIX}mixed_pipeline", "fc")
            ),
            key=f"{STATE_PREFIX}mixed_pipeline_widget",
        )
        st.session_state[f"{STATE_PREFIX}mixed_pipeline"] = pipeline
    
    with col2:
        measure = st.selectbox(
            "Measure",
            [
                "pearson", "spearman", "partial_correlation",
                "plv", "wpli", "coherence",
                "amplitude_envelope_correlation", "mutual_information"
            ],
            index=0 if not st.session_state.get(f"{STATE_PREFIX}mixed_measure") else 0,
            key=f"{STATE_PREFIX}mixed_measure_widget",
        )
        st.session_state[f"{STATE_PREFIX}mixed_measure"] = measure
    
    with col3:
        st.write("")  # Spacer

    # ── Seed selection from catalog ────────────────────────────────────────
    st.markdown("**Seed selection**")
    catalog = _load_seed_catalog(str(bids_root), pipeline)

    seed_source = st.radio(
        "Seed source",
        ["Catalog (from computed subject-level outputs)", "Manual entry"],
        horizontal=True,
        key=f"{STATE_PREFIX}mixed_seed_source",
    )

    # Backward-compat migration: mixed_seed (str) → mixed_seeds (list)
    _old_seed = st.session_state.pop(f"{STATE_PREFIX}mixed_seed", None)
    _default_seeds: list[str] = st.session_state.get(
        f"{STATE_PREFIX}mixed_seeds",
        [_old_seed] if _old_seed else [],
    )

    if seed_source == "Catalog (from computed subject-level outputs)":
        if catalog is None or not catalog.get_seeds():
            st.warning("⚠️ No seeds in catalog — run subject-level seed connectivity first, or use Manual entry.")
            seed_inputs: list[str] = []
        else:
            computed_seeds = _list_computed_seeds(str(bids_root), pipeline)
            if computed_seeds:
                valid_defaults = [s for s in _default_seeds if s in computed_seeds]
                seed_inputs = st.multiselect(
                    "Select seeds",
                    computed_seeds,
                    default=valid_defaults,
                    key=f"{STATE_PREFIX}mixed_seeds_catalog_sel",
                    format_func=_seed_token_display,
                )
            else:
                st.info("No subject-level seed outputs found. Showing full catalog.")
                all_seeds = catalog.get_seeds(source="xcpd_atlas_parcel")[:100]
                opts_keys = [
                    f"atlas-{s.atlas}:{s.parcel_label}" if s.source == "xcpd_atlas_parcel" else s.id
                    for s in all_seeds
                ]
                valid_defaults_full = [s for s in _default_seeds if s in opts_keys]
                seed_inputs = st.multiselect(
                    "Select seeds", opts_keys,
                    default=valid_defaults_full,
                    key=f"{STATE_PREFIX}mixed_seeds_catalog_full",
                    format_func=_seed_token_display,
                )
    else:
        _manual_default = "\n".join(_default_seeds)
        manual_str = st.text_area(
            "Seed tokens (one per line, CLI format: atlas-4S256Parcels:LABEL or sphere:x,y,z,r=6,name=...)",
            value=_manual_default,
            key=f"{STATE_PREFIX}mixed_seeds_manual",
            help="E.g., 'atlas-4S256Parcels:RH_Cont_Par_1'",
            height=100,
        )
        seed_inputs = [s.strip() for s in manual_str.splitlines() if s.strip()]

    st.session_state[f"{STATE_PREFIX}mixed_seeds"] = seed_inputs

    # Seed visualizer preview
    if seed_inputs:
        extra = f" (+{len(seed_inputs)-1} more)" if len(seed_inputs) > 1 else ""
        with st.expander(f"🔍 Preview first seed on MNI template{extra}", expanded=False):
            with st.spinner("Rendering seed preview..."):
                png = _cached_seed_preview(seed_inputs[0], str(bids_root))
            if png:
                st.image(png, use_container_width=True)
                if len(seed_inputs) > 1:
                    st.caption(f"Showing: `{seed_inputs[0]}`")
            else:
                st.warning(f"Could not render preview for: `{seed_inputs[0]}`")
    
    # ===== Section 2: FSL TFCE Parameters =====
    st.markdown("#### ⚙️ Section 2: FSL TFCE Parameters")
    
    _CORRECTION_OPTIONS = ["TFCE", "Cluster", "FDR", "Parametric"]
    _CORRECTION_LEGACY = {"GRF": "Cluster"}
    _stored_correction = st.session_state.get(f"{STATE_PREFIX}mixed_correction", "TFCE")
    _stored_correction = _CORRECTION_LEGACY.get(_stored_correction, _stored_correction)
    if _stored_correction not in _CORRECTION_OPTIONS:
        _stored_correction = "TFCE"

    col1, col2 = st.columns(2)

    with col2:
        correction = st.radio(
            "Correction method",
            _CORRECTION_OPTIONS,
            index=_CORRECTION_OPTIONS.index(_stored_correction),
            horizontal=True,
            key=f"{STATE_PREFIX}mixed_correction_widget",
            help=(
                "**TFCE** — threshold-free cluster enhancement (recommended, no cluster-forming threshold)  \n"
                "**Cluster** — non-parametric cluster inference via `randomise -c 2.3` (uses permutations)  \n"
                "**FDR** — permutation voxelwise p-maps + Benjamini-Hochberg FDR correction  \n"
                "**Parametric** — fast voxelwise t-tests (change-score), GRF cluster correction; local only"
            ),
        )
        st.session_state[f"{STATE_PREFIX}mixed_correction"] = correction

    with col1:
        if correction == "Parametric":
            n_perm = 0
            st.info("⚡ Parametric t-tests — no permutations needed. Runs in seconds.", icon="⚡")
        else:
            n_perm = st.slider(
                "Number of permutations",
                min_value=100,
                max_value=10000,
                value=st.session_state.get(f"{STATE_PREFIX}mixed_n_perm", 5000),
                step=100,
                key=f"{STATE_PREFIX}mixed_n_perm_widget",
            )
            st.session_state[f"{STATE_PREFIX}mixed_n_perm"] = n_perm
    
    mask_input = st.text_input(
        "Brain mask",
        value=st.session_state.get(
            f"{STATE_PREFIX}mixed_mask",
            str(Path(bids_root) / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz"),
        ),
        key=f"{STATE_PREFIX}mixed_mask_widget",
        help="Dilated MNI brain mask (AGENTS.md §6). Defaults to project atlases/MNI152_T1_2mm_brain_mask_dil.nii.gz",
    )
    st.session_state[f"{STATE_PREFIX}mixed_mask"] = mask_input
    if not mask_input:
        st.warning("⚠️ No mask provided — scripts will auto-detect, but dilated mask is required.")
    elif not Path(mask_input).exists():
        st.warning(f"⚠️ Mask file not found on this machine: `{mask_input}`")
    
    if correction != "Parametric" and n_perm < 1000:
        st.warning("⚠️ <1000 permutations gives unreliable p-values")

    # ===== Section 3: Execution Options =====
    st.markdown("#### 🚀 Section 3: Execution Options")

    if correction == "Parametric":
        execution = "Local"
        st.info("⚡ **Parametric** correction runs locally only (completes in seconds).")
    else:
        execution = st.radio(
            "Execution location",
            ["Local", "HPC"],
            index=["Local", "HPC"].index(
                st.session_state.get(f"{STATE_PREFIX}mixed_execution", "Local")
            ),
            horizontal=True,
            key=f"{STATE_PREFIX}mixed_execution_widget",
        )
        st.session_state[f"{STATE_PREFIX}mixed_execution"] = execution
    
    use_test_perms = False
    if correction != "Parametric":
        if execution == "Local":
            use_test_perms = st.checkbox(
                "Use reduced permutations for testing (100 instead of configured)",
                value=st.session_state.get(f"{STATE_PREFIX}mixed_test_mode", False),
                key=f"{STATE_PREFIX}mixed_test_mode_widget",
            )
            st.session_state[f"{STATE_PREFIX}mixed_test_mode"] = use_test_perms
        else:
            st.info("ℹ️ HPC: Will upload design files and submit SLURM job")
    
    # ===== Section 4: Validate & Select Subjects =====
    st.markdown("#### 👁️ Section 4: Validate & Select Subjects")

    col_val, col_prev = st.columns([1, 1])

    with col_val:
        if st.button("🔍 Validate Zmaps", key=f"{STATE_PREFIX}mixed_validate"):
            if not seed_inputs:
                st.warning("Select at least one seed first.")
            else:
                with st.spinner("Validating zmaps…"):
                    canonical_csv = st.session_state.get(
                        f"{STATE_PREFIX}mixed_canonical_csv",
                        _default_participants_path(str(bids_root)),
                    )
                    fd_cutoff_cur = st.session_state.get(f"{STATE_PREFIX}mixed_fd_cutoff", 0.5)
                    relaxed_mode = execution == "HPC" or correction == "Parametric"

                    per_seed_results: dict = {}
                    per_seed_dfs: dict = {}
                    ref_validation_df = None
                    ref_summary = None

                    for seed_tok in seed_inputs:
                        try:
                            seed_dir_name = cli_token_to_seed_dir_name(seed_tok)
                            validator = SubjectDataValidator(
                                bids_root=str(bids_root),
                                canonical_order_csv=canonical_csv,
                                pipeline=pipeline,
                                measure=measure,
                            )
                            vdf = validator.validate_all_subjects(seed=seed_dir_name)
                            smry = validator.summarize_validation(vdf)
                            per_seed_results[seed_tok] = smry
                            per_seed_dfs[seed_tok] = vdf
                        except Exception as e:
                            per_seed_results[seed_tok] = {"error": str(e)}

                    # Use first seed as reference
                    first_tok = seed_inputs[0]
                    if first_tok in per_seed_dfs:
                        ref_validation_df = per_seed_dfs[first_tok]
                        ref_summary = per_seed_results[first_tok]
                        sel_df = _build_subject_selection_df(ref_validation_df, fd_cutoff=fd_cutoff_cur)
                        ctx_hash = f"{','.join(seed_inputs)}|{pipeline}|{measure}|{fd_cutoff_cur}"
                        st.session_state[f"{STATE_PREFIX}mixed_validation_result"] = ref_summary
                        st.session_state[f"{STATE_PREFIX}mixed_validation_df"] = ref_validation_df
                        st.session_state[f"{STATE_PREFIX}mixed_selection_df"] = sel_df
                        st.session_state[f"{STATE_PREFIX}mixed_selection_ctx"] = ctx_hash

                        valid_count = ref_summary.get("valid_count", 0)
                        st.session_state[f"{STATE_PREFIX}mixed_zmaps_valid"] = (
                            valid_count > 0 if relaxed_mode else ref_summary.get("error_count", 0) == 0
                        )
                    else:
                        st.session_state[f"{STATE_PREFIX}mixed_zmaps_valid"] = False

                    st.session_state[f"{STATE_PREFIX}mixed_per_seed_val_results"] = per_seed_results
                    st.session_state[f"{STATE_PREFIX}mixed_per_seed_val_dfs"] = per_seed_dfs

    with col_prev:
        if st.button("📊 Preview Design", key=f"{STATE_PREFIX}mixed_preview"):
            sel_df_cur: pd.DataFrame | None = st.session_state.get(f"{STATE_PREFIX}mixed_selection_df")
            if sel_df_cur is None:
                st.warning("Run Validate Zmaps first.")
            else:
                with st.spinner("Building design preview…"):
                    try:
                        included = sel_df_cur[sel_df_cur["include"]]
                        control = sorted(included[included["group"] == "control"]["subject"].tolist())
                        walking = sorted(included[included["group"] == "walking"]["subject"].tolist())
                        _preview_design(control, walking)
                    except Exception as e:
                        st.error(f"Preview failed: {e}")

    # ── Per-seed validation summary table ─────────────────────────────────
    per_seed_val_results: dict = st.session_state.get(f"{STATE_PREFIX}mixed_per_seed_val_results", {})
    if per_seed_val_results:
        rows = []
        for tok, smry in per_seed_val_results.items():
            if "error" in smry:
                rows.append({"Seed": _seed_token_display(tok), "Valid": "—", "Missing": "—", "Total": "—", "Status": f"❌ {smry['error'][:60]}"})
            else:
                v = smry.get("valid_count", 0)
                t = smry.get("total_count", 0)
                rows.append({"Seed": _seed_token_display(tok), "Valid": v, "Missing": t - v, "Total": t,
                             "Status": "✅ all found" if v == t else f"⚠️ {t-v} missing"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── Summary metrics + failure-stage breakdown ──────────────────────────
    if st.session_state.get(f"{STATE_PREFIX}mixed_validation_result"):
        val_result = st.session_state[f"{STATE_PREFIX}mixed_validation_result"]
        c1, c2, c3 = st.columns(3)
        c1.metric("Valid zmaps", val_result.get("valid_count", 0))
        c2.metric("Missing", val_result.get("missing_count", 0))
        c3.metric("Total expected", val_result.get("total_count", 0))

        failure_stages = val_result.get("failure_stages", {})
        if failure_stages:
            from utils.group_stats_validation import SubjectDataValidator as _SDV
            st.markdown("**Missing sessions by failure stage:**")
            stage_order = [_SDV.STAGE_NO_BIDS, _SDV.STAGE_NO_FMRIPREP, _SDV.STAGE_NO_XCPD, _SDV.STAGE_NO_SEEDFC]
            stage_rows = [{"Stage": s, "Sessions": failure_stages[s]} for s in stage_order if s in failure_stages]
            st.dataframe(pd.DataFrame(stage_rows), use_container_width=True, hide_index=True)

    # ── FD cutoff widget ───────────────────────────────────────────────────
    val_df_exists = st.session_state.get(f"{STATE_PREFIX}mixed_validation_df") is not None
    fd_cutoff = st.number_input(
        "Mean FD cutoff (mm) — subjects with max session FD above this are auto-excluded",
        min_value=0.1,
        max_value=2.0,
        value=float(st.session_state.get(f"{STATE_PREFIX}mixed_fd_cutoff", 0.5)),
        step=0.05,
        format="%.2f",
        key=f"{STATE_PREFIX}mixed_fd_cutoff_widget",
        disabled=not val_df_exists,
        help="0.5 mm is a common lenient threshold; 0.2 mm is stricter. Applied when Validate Zmaps is run, or when this value changes.",
    )
    prev_cutoff = st.session_state.get(f"{STATE_PREFIX}mixed_fd_cutoff", 0.5)
    st.session_state[f"{STATE_PREFIX}mixed_fd_cutoff"] = fd_cutoff
    # Rebuild selection when cutoff changes (if validation data exists)
    if val_df_exists and abs(fd_cutoff - prev_cutoff) > 1e-6:
        _vdf = st.session_state[f"{STATE_PREFIX}mixed_validation_df"]
        _new_sel = _build_subject_selection_df(_vdf, fd_cutoff=fd_cutoff)
        st.session_state[f"{STATE_PREFIX}mixed_selection_df"] = _new_sel
        st.session_state[f"{STATE_PREFIX}mixed_selection_ctx"] = (
            f"{','.join(seed_inputs)}|{pipeline}|{measure}|{fd_cutoff}"
        )

    # ── Subject selection editor ───────────────────────────────────────────
    ctx_hash_cur = f"{','.join(seed_inputs)}|{pipeline}|{measure}|{fd_cutoff}"
    if st.session_state.get(f"{STATE_PREFIX}mixed_selection_ctx") != ctx_hash_cur:
        # Params changed — clear stale selection
        st.session_state.pop(f"{STATE_PREFIX}mixed_selection_df", None)
        st.session_state.pop(f"{STATE_PREFIX}mixed_per_seed_val_results", None)
        st.session_state.pop(f"{STATE_PREFIX}mixed_per_seed_val_dfs", None)
        st.session_state.pop(f"{STATE_PREFIX}mixed_zmaps_valid", None)

    sel_df_state: pd.DataFrame | None = st.session_state.get(f"{STATE_PREFIX}mixed_selection_df")
    if sel_df_state is not None:
        # Count auto-excluded by FD
        fd_excluded = int(
            (
                (~sel_df_state["include"])
                & sel_df_state["max_fd"].notna()
                & (sel_df_state["max_fd"] > fd_cutoff)
            ).sum()
        ) if "max_fd" in sel_df_state.columns else 0
        label = "**Subject selection** — toggle *Include* to add/remove subjects:"
        if fd_excluded:
            label += f" _(⚠️ {fd_excluded} auto-excluded by FD cutoff)_"
        st.markdown(label)
        edited_sel = st.data_editor(
            sel_df_state,
            key=f"{STATE_PREFIX}mixed_selection_editor",
            column_config={
                "include": st.column_config.CheckboxColumn("Include", default=True),
                "subject": st.column_config.TextColumn("Subject", disabled=True),
                "group": st.column_config.TextColumn("Group", disabled=True),
                "complete": st.column_config.TextColumn("Sessions", disabled=True),
                "max_fd": st.column_config.NumberColumn(
                    "Max mean FD (mm)",
                    format="%.3f",
                    disabled=True,
                    help="Maximum mean framewise displacement across sessions. Subjects above cutoff are auto-excluded.",
                ),
                "status": st.column_config.TextColumn("Status", disabled=True),
                "failure_stage": st.column_config.TextColumn("Failure reason", disabled=True),
            },
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
        )
        # Persist edits (different key from widget)
        st.session_state[f"{STATE_PREFIX}mixed_selection_df"] = edited_sel

        # Composition summary
        included_rows = edited_sel[edited_sel["include"]]
        n_ctrl = (included_rows["group"] == "control").sum()
        n_walk = (included_rows["group"] == "walking").sum()
        n_total = len(included_rows)
        if n_total == 0:
            st.error("⛔ No subjects selected.")
        elif n_ctrl == 0 or n_walk == 0:
            st.error(f"⛔ Both groups must have subjects. Selected: {n_ctrl} control, {n_walk} walking.")
        elif n_ctrl < 2 or n_walk < 2:
            st.warning(f"⚠️ Fewer than 2 subjects per group ({n_ctrl} ctrl, {n_walk} walk). Results may be unreliable.")
        else:
            st.success(f"✅ {n_total} subjects selected: {n_ctrl} control + {n_walk} walking")

    # ── Per-subject session details ────────────────────────────────────────
    val_df: pd.DataFrame | None = st.session_state.get(f"{STATE_PREFIX}mixed_validation_df")
    if val_df is not None:
        valid_count = st.session_state.get(f"{STATE_PREFIX}mixed_validation_result", {}).get("valid_count", 0)
        total_count = st.session_state.get(f"{STATE_PREFIX}mixed_validation_result", {}).get("total_count", 0)
        with st.expander(f"📋 Per-session details ({valid_count} valid / {total_count} total)"):
            is_valid_row = val_df["exists"] & val_df["error"].isna()
            keep_cols = ["subject", "session", "group", "exists", "error"]
            if "mean_fd" in val_df.columns:
                keep_cols.append("mean_fd")
            display_df = val_df[keep_cols].copy()
            display_df["status"] = is_valid_row.map({True: "✅ valid", False: "❌ missing"})
            if "mean_fd" in display_df.columns:
                display_df["mean_fd"] = display_df["mean_fd"].map(
                    lambda v: f"{v:.3f}" if pd.notna(v) else "—"
                )
            display_df = display_df.rename(columns={"error": "failure reason", "mean_fd": "mean FD (mm)"}).drop(columns=["exists"])
            st.dataframe(
                display_df.style.apply(
                    lambda row: ["background-color: #ffeeba" if "❌" in str(row.get("status", "")) else "" for _ in row],
                    axis=1,
                ),
                use_container_width=True,
                hide_index=True,
            )

    # ===== Section 5: Submit =====
    st.markdown("#### 📤 Section 5: Submit Analysis")

    canonical_csv = st.session_state.get(
        f"{STATE_PREFIX}mixed_canonical_csv",
        _default_participants_path(str(bids_root)),
    )

    seed_input_ref = seed_inputs[0] if seed_inputs else ""
    seed_dir_name = cli_token_to_seed_dir_name(seed_input_ref) if seed_input_ref else ""
    expected_output = (
        Path(bids_root) / "derivatives" / "connectivity"
        / pipeline / "group" / "seed" / seed_dir_name / f"measure-{measure}"
        if seed_dir_name else None
    )

    # ── Script preview ─────────────────────────────────────────────────────
    canonical_csv_preview = st.session_state.get(
        f"{STATE_PREFIX}mixed_canonical_csv",
        _default_participants_path(str(bids_root)),
    )
    _hpc_remote_base = None
    if execution == "HPC":
        try:
            from utils.hpc import HPCConfig as _HPCCfgPrev
            _hpc_remote_base = _HPCCfgPrev.from_config(config).remote_base or None
        except Exception:
            pass
    effective_preview_n_perm = 100 if (use_test_perms and execution == "Local") else n_perm
    if seed_input_ref:
        preview_cmd = _build_group_cmd(
            bids_root=bids_root,
            seed=seed_input_ref,
            pipeline=pipeline,
            measure=measure,
            canonical_csv=canonical_csv_preview,
            n_perm=effective_preview_n_perm,
            correction=correction,
            mask=mask_input or None,
            execution=execution,
            hpc_remote_base=_hpc_remote_base,
        )
        extra_seeds = f" (+{len(seed_inputs)-1} more)" if len(seed_inputs) > 1 else ""
        with st.expander(f"📋 Script preview (first seed{extra_seeds})", expanded=False):
            st.code(preview_cmd, language="bash")
            st.caption(
                f"Output directory: `{expected_output}`  \n"
                + (f"HPC remote base: `{_hpc_remote_base}`" if _hpc_remote_base else "Local execution")
            )

    col_info, col_submit = st.columns([2, 1])

    with col_info:
        sel_df_submit: pd.DataFrame | None = st.session_state.get(f"{STATE_PREFIX}mixed_selection_df")
        n_selected = len(sel_df_submit[sel_df_submit["include"]]) if sel_df_submit is not None else "?"
        perm_display = "N/A (parametric)" if correction == "Parametric" else str(
            100 if use_test_perms and execution == "Local" else n_perm
        )
        if seed_inputs:
            seeds_short = ", ".join(cli_token_to_seed_dir_name(s) for s in seed_inputs[:3])
            if len(seed_inputs) > 3:
                seeds_short += f" … +{len(seed_inputs)-3} more"
            seed_display_line = f"**Seeds ({len(seed_inputs)}):** `{seeds_short}`"
        else:
            seed_display_line = "**Seed:** _(none selected)_"
        st.info(
            f"**Execution:** {execution} · **Correction:** {correction}  \n"
            f"{seed_display_line} · **Subjects:** {n_selected} selected  \n"
            f"**Output:** `{expected_output or '(select a seed)'}`  \n"
            f"**N Permutations:** {perm_display}"
        )

    sel_df_submit = st.session_state.get(f"{STATE_PREFIX}mixed_selection_df")
    has_valid_selection = (
        sel_df_submit is not None
        and len(sel_df_submit[sel_df_submit["include"]]) > 0
        and (sel_df_submit[sel_df_submit["include"]]["group"] == "control").sum() >= 1
        and (sel_df_submit[sel_df_submit["include"]]["group"] == "walking").sum() >= 1
    )
    is_valid = (
        st.session_state.get(f"{STATE_PREFIX}mixed_zmaps_valid", False)
        and len(seed_inputs) > 0
        and has_valid_selection
    )

    with col_submit:
        if st.button(
            "🚀 Submit",
            key=f"{STATE_PREFIX}mixed_submit",
            type="primary",
            disabled=not is_valid,
        ):
            if not is_valid:
                st.error("Validate zmaps, select seeds, and ensure both groups have subjects")
            else:
                effective_n_perm = 100 if (use_test_perms and execution == "Local") else n_perm
                val_df_submit: pd.DataFrame = st.session_state[f"{STATE_PREFIX}mixed_validation_df"]
                with st.spinner(f"Submitting {len(seed_inputs)} seed(s)…"):
                    # Write ONE filtered canonical TSV (same subjects for all seeds)
                    effective_csv = _write_filtered_canonical_tsv(
                        val_df_submit,
                        sel_df_submit,
                        "batch",
                        bids_root,
                    )

                    results = []
                    for i, seed_token in enumerate(seed_inputs):
                        seed_label = _seed_token_display(seed_token)
                        with st.expander(f"[{i+1}/{len(seed_inputs)}] {seed_label}", expanded=True):
                            try:
                                if execution == "Local":
                                    _submit_mixed_design_local(
                                        bids_root,
                                        seed_token,
                                        pipeline,
                                        measure,
                                        effective_csv,
                                        effective_n_perm,
                                        correction,
                                        mask_input or None,
                                    )
                                    results.append((seed_token, "✅"))
                                else:
                                    _submit_mixed_design_hpc(
                                        config,
                                        bids_root,
                                        seed_token,
                                        pipeline,
                                        measure,
                                        effective_csv,
                                        n_perm,
                                        correction,
                                        mask_input or None,
                                        _tsv_already_synced=(i > 0),
                                    )
                                    results.append((seed_token, "✅"))
                            except Exception as e:
                                st.error(f"Failed: {e}")
                                results.append((seed_token, f"❌ {e}"))

                    succeeded = sum(1 for _, s in results if s == "✅")
                    if succeeded == len(seed_inputs):
                        st.success(f"✅ All {len(seed_inputs)} seeds submitted successfully!")
                    else:
                        st.warning(f"⚠️ {succeeded}/{len(seed_inputs)} seeds submitted. See errors above.")


def _submit_mixed_design_local(
    bids_root: str,
    seed: str,
    pipeline: str,
    measure: str,
    canonical_csv: str,
    n_perm: int,
    correction: str,
    mask: str | None = None,
) -> None:
    """Submit mixed-design analysis locally (output path resolved by backend)."""
    # Resolve script paths absolutely from this file's location
    _this_dir = Path(__file__).resolve().parent          # pages_connectivity_submit/
    _app_dir = _this_dir.parent                          # neuconn_app/
    _project_root = _app_dir.parent                      # project root

    seed_dir = cli_token_to_seed_dir_name(seed)
    out_base = (
        Path(bids_root) / "derivatives" / "connectivity"
        / pipeline / "group" / "seed" / seed_dir / f"measure-{measure}"
    )

    if correction.upper() == "PARAMETRIC":
        script = str(_project_root / "script" / "group_lmm_stats.py")
        cmd = [
            "python", script,
            "--bids-root", str(bids_root),
            "--seed", seed,
            "--pipeline", pipeline,
            "--measure", measure,
            "--canonical-csv", canonical_csv,
        ]
        if mask:
            cmd.extend(["--mask-path", mask])
        spinner_msg = "Running parametric analysis… (usually <30 seconds)"
        timeout_s = 300
        out_subdir = out_base / "lmm_outputs"
    else:
        script = str(_app_dir / "scripts" / "group_mixed_design_stats.py")
        cmd = [
            "python", script,
            "--bids-root", str(bids_root),
            "--seed", seed,
            "--pipeline", pipeline,
            "--measure", measure,
            "--n-perms", str(n_perm),
            "--correction", correction,
            "--canonical-csv", canonical_csv,
        ]
        if mask:
            cmd.extend(["--mask", mask])
        spinner_msg = "Running analysis… (this may take 10+ minutes for full permutations)"
        timeout_s = 3600
        out_subdir = out_base / "randomise_outputs"

    st.code(" ".join(cmd), language="bash")

    with st.spinner(spinner_msg):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_s)

            if result.returncode == 0:
                st.success("✅ Analysis completed!")
                st.info(f"Results saved to: `{out_subdir}`")
            else:
                st.error(f"Analysis failed (exit {result.returncode}):\n```\n{result.stderr[-2000:]}\n```")
        except subprocess.TimeoutExpired:
            st.error(f"Analysis timed out (>{timeout_s}s)")
        except Exception as e:
            st.error(f"Execution error: {e}")
            st.error(f"Execution error: {e}")


def _submit_mixed_design_hpc(
    config: dict,
    bids_root: str,
    seed: str,
    pipeline: str,
    measure: str,
    canonical_csv: str,
    n_perm: int,
    correction: str,
    mask: str | None = None,
    _tsv_already_synced: bool = False,
) -> None:
    """Submit mixed-design analysis to HPC via ConnectivityWorkflowManager."""
    from utils.hpc import HPCConfig as _HPCCfg
    hpc_cfg = _HPCCfg.from_config(config)
    remote_bids_root = hpc_cfg.remote_base or str(bids_root)

    # Remap local paths to remote equivalents
    def _remap_path(local_path: str | None) -> str | None:
        if not local_path:
            return None
        lp = str(local_path)
        if lp.startswith(str(bids_root)):
            return lp.replace(str(bids_root), remote_bids_root, 1)
        return lp

    remote_mask = _remap_path(mask)
    remote_canonical_csv = _remap_path(canonical_csv)
    remote_log_dir = f"{remote_bids_root}/logs"

    # Rsync the filtered canonical TSV to HPC (it's in tmp/ which won't exist remotely)
    if not _tsv_already_synced and canonical_csv and Path(canonical_csv).exists():
        remote_tsv_dir = f"{remote_bids_root}/tmp/group_stats_subsets"
        rsync_cmd = [
            "rsync", "-a", "--mkpath",
            canonical_csv,
            "-e", f"ssh -p {hpc_cfg.port or 22}",
            f"{hpc_cfg.user}@{hpc_cfg.host}:{remote_tsv_dir}/",
        ]
        try:
            result = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=30)
            if result.returncode != 0:
                st.warning(f"⚠️ Could not rsync subset TSV to HPC: {result.stderr[:200]}")
        except Exception as _e:
            st.warning(f"⚠️ rsync failed: {_e}")

    manager = ConnectivityWorkflowManager(config)
    opts: dict = {
        "bids_root": remote_bids_root,
        "seed": seed,
        "seeds": [seed],  # list form for download compatibility
        "pipeline": pipeline,
        "measure": measure,
        "n_perm": str(n_perm),
        "correction": correction,
        "canonical_order_csv": remote_canonical_csv or f"{remote_bids_root}/bids/participants.tsv",
        "kind": "mixed_design",
        "log_dir": remote_log_dir,
        "partition": hpc_cfg.partition or "shared_cpu",
        "conda_env": hpc_cfg.conda_env,
    }
    if remote_mask:
        opts["mask_path"] = remote_mask

    with st.spinner("Submitting group analysis to HPC…"):
        try:
            sub_obj = manager.submit(
                "group_stats", opts, [], dry_run=False, execution_mode="hpc"
            )
            job_id = sub_obj.job_id if sub_obj else "unknown"
            if sub_obj and sub_obj.status == "failed":
                st.error(f"❌ HPC submission failed: {sub_obj.notes or 'unknown error'}")
            else:
                st.success(f"✅ Group analysis submitted to HPC! Job ID: **{job_id}**")
                st.info(
                    f"Monitor progress in the 📡 Monitor tab. "
                    f"Download results when the job completes."
                )
        except Exception as exc:
            st.error(f"HPC submission failed: {exc}")


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
    """Monitor group stats HPC submissions."""
    manager = ConnectivityWorkflowManager(config)
    all_subs = [s for s in manager.list_submissions() if s.analysis_type == "group_stats"]

    col_refresh, col_filter = st.columns([1, 3])
    with col_refresh:
        if st.button("🔄 Refresh All", key="monitor_group_refresh_all"):
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
            key="monitor_group_filter",
        )

    if not all_subs:
        st.info("No group stats submissions yet. Submit a job in the ⚙️ Submit tab.")
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
                kind_opt = sub.options.get("kind", "—")
                seeds_opt = sub.options.get("seeds", [])
                seed_id_opt = sub.options.get("seed_id", "")
                seeds_str = ", ".join(str(s) for s in seeds_opt[:3]) if seeds_opt else seed_id_opt
                if len(seeds_opt) > 3:
                    seeds_str += f" (+{len(seeds_opt) - 3} more)"
                st.caption(
                    f"Pipeline: `{pipeline_opt}` | Kind: `{kind_opt}` "
                    f"| Seeds: {seeds_str or '—'}"
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


def _render_download_tab(config: dict, bids_root: Any) -> None:
    """Download completed HPC group stats results."""
    from utils.connectivity_download import (  # noqa: PLC0415
        download_group_results as _dl_group,
        build_group_download_command as _build_group_dl_cmd,
    )
    from utils.hpc import HPCConfig as _HPCConfig  # noqa: PLC0415

    manager = ConnectivityWorkflowManager(config)
    completed = [
        s for s in manager.list_submissions()
        if s.analysis_type == "group_stats"
        and s.execution_mode == "hpc"
        and s.status == "completed"
    ]

    if not completed:
        st.info("No completed HPC group stats jobs to download.")
        return

    for sub in sorted(completed, key=lambda s: s.submitted_at, reverse=True):
        with st.container(border=True):
            pipeline = sub.options.get("pipeline", "fc")
            seeds = sub.options.get("seeds", []) or [sub.options.get("seed", "")] or [sub.options.get("seed_id", "")]
            seeds = [s for s in seeds if s]
            seeds_str = ", ".join(str(s) for s in seeds[:3])
            if len(seeds) > 3:
                seeds_str += f" (+{len(seeds) - 3} more)"

            st.markdown(f"**Job ID:** `{sub.job_id or '—'}` ✅ Completed")
            st.caption(
                f"Submitted: {sub.submitted_at} | Pipeline: `{pipeline}` "
                f"| Kind: `{sub.options.get('kind', '—')}` | Seeds: {seeds_str or '—'}"
            )

            hpc_cfg = None
            try:
                hpc_cfg = _HPCConfig.from_config(config)
                cmd_preview = _build_group_dl_cmd(
                    pipeline=pipeline,
                    seeds=seeds,
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
                    success = _dl_group(
                        pipeline=pipeline,
                        seeds=seeds,
                        hpc_config=hpc_cfg,
                        local_bids_root=Path(bids_root),
                        progress_callback=_make_progress_callback(st_progress, st_status),
                    )
                    if success:
                        st.success("✅ Group results downloaded successfully.")
                    else:
                        st.error("⚠️ Some seeds failed to download. Check progress above.")
                except Exception as exc:
                    st.error(f"Download failed: {exc}")


def _render_submit_tab(config: dict, bids_root: Any) -> None:
    default_participants_path = _default_participants_path(str(bids_root))

    # --- Session state defaults ---
    st.session_state.setdefault(f"{STATE_PREFIX}template", "Voxel")
    st.session_state.setdefault(f"{STATE_PREFIX}kind", "Voxel")
    st.session_state.setdefault(f"{STATE_PREFIX}pipeline", "fc")
    st.session_state.setdefault(f"{STATE_PREFIX}group_csv", default_participants_path)
    st.session_state.setdefault(f"{STATE_PREFIX}out_root", _DEFAULT_OUT_ROOT)
    # Voxel defaults — pre-fill dilated mask (AGENTS.md §6)
    _dilated_mask_path = str(Path(bids_root) / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz")
    st.session_state.setdefault(f"{STATE_PREFIX}measure", "alff")
    st.session_state.setdefault(f"{STATE_PREFIX}contrast", "ses-02_minus_ses-01")
    st.session_state.setdefault(f"{STATE_PREFIX}method", "GRF")
    st.session_state.setdefault(f"{STATE_PREFIX}n_perms", 5000)
    st.session_state.setdefault(f"{STATE_PREFIX}mask", _dilated_mask_path)
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
    # Mixed-design defaults
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_pipeline", "fc")
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_measure", "pearson")
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_seeds", [])
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_n_perm", 5000)
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_correction", "TFCE")
    st.session_state.setdefault(
        f"{STATE_PREFIX}mixed_mask",
        str(Path(bids_root) / "atlases" / "MNI152_T1_2mm_brain_mask_dil.nii.gz"),
    )
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_execution", "Local")
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_test_mode", False)
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_zmaps_valid", False)
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_validation_result", None)
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_canonical_csv", default_participants_path)

    # --- Template Selector ---
    st.markdown("### 📋 Analysis Template")
    template = st.selectbox(
        "Choose analysis type:",
        [
            "Voxel-level Group Stats (existing)",
            "Matrix-level Group Stats (existing)",
            "Mixed-Design TFCE (pre/post × 2 groups)",
        ],
        index=0 if st.session_state.get(f"{STATE_PREFIX}template") == "Voxel" else (
            1 if st.session_state.get(f"{STATE_PREFIX}template") == "Matrix" else 2
        ),
        key=f"{STATE_PREFIX}template_widget",
    )
    
    # Map template to kind
    if "Voxel" in template:
        st.session_state[f"{STATE_PREFIX}template"] = "Voxel"
        kind = "Voxel"
    elif "Matrix" in template:
        st.session_state[f"{STATE_PREFIX}template"] = "Matrix"
        kind = "Matrix"
    else:
        st.session_state[f"{STATE_PREFIX}template"] = "MixedDesign"
        kind = "MixedDesign"
    
    st.markdown("---")

    # ===== Mixed-Design TFCE =====
    if kind == "MixedDesign":
        import numpy as np
        _render_mixed_design_section(config, bids_root)
        return

    # ===== Original Voxel/Matrix workflows =====
    
    # --- Common: pipeline + paths ---
    pipeline = st.selectbox(
        "Pipeline",
        KNOWN_PIPELINES,
        index=KNOWN_PIPELINES.index(st.session_state.get(f"{STATE_PREFIX}pipeline", "fc")),
        key=f"{STATE_PREFIX}pipeline_widget",
    )
    st.session_state[f"{STATE_PREFIX}pipeline"] = pipeline

    group_csv = st.text_input(
        "participants.tsv path",
        value=st.session_state.get(f"{STATE_PREFIX}group_csv", default_participants_path),
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
            "Brain mask path",
            value=st.session_state.get(f"{STATE_PREFIX}mask", _dilated_mask_path),
            key=f"{STATE_PREFIX}mask_widget",
            help="Dilated MNI brain mask (required per AGENTS.md §6). Defaults to project atlases/MNI152_T1_2mm_brain_mask_dil.nii.gz",
        )
        st.session_state[f"{STATE_PREFIX}mask"] = mask
        if not mask:
            st.warning("⚠️ No mask provided — scripts will auto-detect, but dilated mask is strongly recommended.")
        elif not Path(mask).exists():
            st.warning(f"⚠️ Mask file not found on this machine: `{mask}`")

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


def render() -> None:
    st.title("📤 Submit Group Statistics")

    config = _get_config()
    _raw_root = (
        config.get("paths", {}).get("project_root")
        or config.get("project_root")
        or config.get("paths", {}).get("bids_root")
        or "."
    )
    # Fall back to repo root when config contains an unexpanded template variable
    if "${" in str(_raw_root):
        bids_root = str(Path(__file__).resolve().parents[2])
    else:
        bids_root = _raw_root

    tabs = st.tabs(["⚙️ Submit", "📡 Monitor", "⬇️ Download"])

    with tabs[0]:
        _render_submit_tab(config, bids_root)

    with tabs[1]:
        _render_monitor_tab(config, bids_root)

    with tabs[2]:
        _render_download_tab(config, bids_root)


if __name__ == "__main__":
    render()
