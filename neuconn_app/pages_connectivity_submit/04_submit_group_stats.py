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
    """Load seed catalog from XCP-D outputs."""
    try:
        from utils.xcpd_outputs import XcpdDiscovery
        disc = XcpdDiscovery(Path(bids_root), pipeline=pipeline)
        return disc.get_seed_catalog()
    except Exception as e:
        st.warning(f"Could not load seed catalog: {e}")
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


def _render_mixed_design_section(config: dict, bids_root: str) -> None:
    """Render mixed-design TFCE workflow section."""
    
    st.subheader("🧬 Mixed-Design TFCE Analysis")
    
    st.markdown("""
    **Paired pre/post × 2-group mixed ANOVA** for longitudinal intervention studies.
    
    - **Input**: 72 zmaps (36 subjects × 2 sessions, ~20 control, ~16 walking)
    - **Output**: FSL randomise results with TFCE/GRF/FDR correction
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

    seed_input = ""
    seed_source = st.radio(
        "Seed source",
        ["Catalog (from computed subject-level outputs)", "Manual entry"],
        horizontal=True,
        key=f"{STATE_PREFIX}mixed_seed_source",
    )

    if seed_source == "Catalog (from computed subject-level outputs)":
        if catalog is None or not catalog.get_seeds():
            st.warning("⚠️ No seeds in catalog — run subject-level seed connectivity first, or use Manual entry.")
        else:
            computed_seeds = _list_computed_seeds(str(bids_root), pipeline)
            if computed_seeds:
                computed_tokens = {s: cli_token_to_seed_dir_name(s) for s in computed_seeds}
                # Prefer seeds that have been computed for subjects
                catalog_tokens = {
                    f"atlas-{s.atlas}:{s.parcel_label}" if s.source == "xcpd_atlas_parcel"
                    else f"sphere:{','.join(str(int(v) if v == int(v) else v) for v in s.coords_mm or (0,0,0))},r={int(s.radius_mm or 6)},name={s.name}"
                    if s.source == "sphere"
                    else s.id
                    : s
                    for s in catalog.get_seeds()
                }
                # Filter to seeds that have subject-level outputs
                available = [t for t in computed_seeds if t in catalog_tokens or True]
                sel = st.selectbox(
                    "Select seed",
                    computed_seeds,
                    key=f"{STATE_PREFIX}mixed_seed_catalog_sel",
                    format_func=lambda t: _seed_token_display(t),
                )
                seed_input = sel
            else:
                st.info("No subject-level seed outputs found. Showing full catalog.")
                all_seeds = catalog.get_seeds(source="xcpd_atlas_parcel")[:100]
                if all_seeds:
                    opts = {f"atlas-{s.atlas}:{s.parcel_label}": s for s in all_seeds}
                    sel_label = st.selectbox(
                        "Select seed", list(opts.keys()),
                        key=f"{STATE_PREFIX}mixed_seed_catalog_full",
                        format_func=_seed_token_display,
                    )
                    seed_input = sel_label
    else:
        seed_input = st.text_input(
            "Seed token (CLI format: atlas-4S256Parcels:LABEL or sphere:x,y,z,r=6,name=...)",
            value=st.session_state.get(f"{STATE_PREFIX}mixed_seed", ""),
            key=f"{STATE_PREFIX}mixed_seed_manual",
            help="E.g., 'atlas-4S256Parcels:RH_Cont_Par_1' or 'sphere:-46,16,32,r=6,name=dlpfc_l'",
        )

    st.session_state[f"{STATE_PREFIX}mixed_seed"] = seed_input

    # Seed visualizer preview
    if seed_input:
        with st.expander("🔍 Preview seed on MNI template", expanded=False):
            with st.spinner("Rendering seed preview..."):
                png = _cached_seed_preview(seed_input, str(bids_root))
            if png:
                st.image(png, use_container_width=True)
            else:
                st.warning(f"Could not render preview for: `{seed_input}`")
    
    # ===== Section 2: FSL TFCE Parameters =====
    st.markdown("#### ⚙️ Section 2: FSL TFCE Parameters")
    
    col1, col2 = st.columns(2)
    
    with col1:
        n_perm = st.slider(
            "Number of permutations",
            min_value=100,
            max_value=10000,
            value=st.session_state.get(f"{STATE_PREFIX}mixed_n_perm", 5000),
            step=100,
            key=f"{STATE_PREFIX}mixed_n_perm_widget",
        )
        st.session_state[f"{STATE_PREFIX}mixed_n_perm"] = n_perm
    
    with col2:
        correction = st.radio(
            "Correction method",
            ["TFCE", "GRF", "FDR"],
            index=["TFCE", "GRF", "FDR"].index(
                st.session_state.get(f"{STATE_PREFIX}mixed_correction", "TFCE")
            ),
            horizontal=True,
            key=f"{STATE_PREFIX}mixed_correction_widget",
        )
        st.session_state[f"{STATE_PREFIX}mixed_correction"] = correction
    
    mask_input = st.text_input(
        "Custom brain mask (optional; auto-detected if blank)",
        value=st.session_state.get(f"{STATE_PREFIX}mixed_mask", ""),
        key=f"{STATE_PREFIX}mixed_mask_widget",
        help="Leave blank to auto-derive mask from zmaps",
    )
    st.session_state[f"{STATE_PREFIX}mixed_mask"] = mask_input
    
    if n_perm < 1000:
        st.warning("⚠️ <1000 permutations gives unreliable p-values")
    
    # ===== Section 3: Execution Options =====
    st.markdown("#### 🚀 Section 3: Execution Options")
    
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
    
    if execution == "Local":
        use_test_perms = st.checkbox(
            "Use reduced permutations for testing (100 instead of configured)",
            value=st.session_state.get(f"{STATE_PREFIX}mixed_test_mode", False),
            key=f"{STATE_PREFIX}mixed_test_mode_widget",
        )
        st.session_state[f"{STATE_PREFIX}mixed_test_mode"] = use_test_perms
    else:
        st.info("ℹ️ HPC: Will upload design files and submit SLURM job")
    
    # ===== Section 4: Preview & Validation =====
    st.markdown("#### 👁️ Section 4: Preview & Validation")
    
    col_val, col_prev = st.columns([1, 1])
    
    with col_val:
        if st.button("🔍 Validate Zmaps", key=f"{STATE_PREFIX}mixed_validate"):
            if not seed_input:
                st.warning("Select a seed first before validating zmaps.")
            else:
                with st.spinner("Validating zmaps..."):
                    try:
                        canonical_csv = st.session_state.get(
                            f"{STATE_PREFIX}mixed_canonical_csv",
                            _default_participants_path(str(bids_root)),
                        )
                        seed_dir_name = cli_token_to_seed_dir_name(seed_input)

                        validator = SubjectDataValidator(
                            bids_root=str(bids_root),
                            canonical_order_csv=canonical_csv,
                            pipeline=pipeline,
                            measure=measure,
                        )

                        validation_df = validator.validate_all_subjects(seed=seed_dir_name)
                        summary = validator.summarize_validation(validation_df)

                        st.session_state[f"{STATE_PREFIX}mixed_validation_result"] = summary
                        st.session_state[f"{STATE_PREFIX}mixed_zmaps_valid"] = (
                            summary.get("error_count", 0) == 0
                        )

                        if st.session_state[f"{STATE_PREFIX}mixed_zmaps_valid"]:
                            st.success(f"✓ {summary['success_count']} zmaps valid for seed: `{seed_dir_name}`")
                        else:
                            st.error(f"✗ {summary['error_count']} validation errors")
                            if summary.get("error_details"):
                                st.text(summary["error_details"])
                    except Exception as e:
                        st.error(f"Validation failed: {e}")
                        st.session_state[f"{STATE_PREFIX}mixed_zmaps_valid"] = False
    
    with col_prev:
        if st.button("📊 Preview Design", key=f"{STATE_PREFIX}mixed_preview"):
            with st.spinner("Building design preview..."):
                try:
                    canonical_csv = st.session_state.get(
                        f"{STATE_PREFIX}mixed_canonical_csv",
                        _default_participants_path(str(bids_root)),
                    )

                    df = _read_subject_table(canonical_csv)
                    group_values = df["group"].astype(str).str.strip().str.lower()
                    control = sorted(df.loc[group_values == "control", "participant_id"].dropna().unique())
                    walking = sorted(df.loc[group_values == "walking", "participant_id"].dropna().unique())
                    
                    builder = MixedDesignBuilder.from_paired_two_group(control, walking)
                    design_mat, _, _, _ = builder.build()
                    
                    st.info(f"""
                    **Design Matrix:**
                    - Shape: {design_mat.shape}
                    - Rank: {int(np.linalg.matrix_rank(design_mat))}
                    - Subjects: {len(control)} control, {len(walking)} walking
                    - Sessions: 2 (pre/post)
                    """)
                    
                    with st.expander("View sample rows"):
                        st.dataframe(pd.DataFrame(design_mat[:5]))
                    
                except Exception as e:
                    st.error(f"Preview failed: {e}")
    
    # Show validation result if available
    if st.session_state.get(f"{STATE_PREFIX}mixed_validation_result"):
        val_result = st.session_state[f"{STATE_PREFIX}mixed_validation_result"]
        st.metric(
            "Validation Status",
            f"{val_result.get('success_count', 0)}/{val_result.get('total_count', 72)} zmaps",
        )
    
    # ===== Section 5: Submit =====
    st.markdown("#### 📤 Section 5: Submit Analysis")
    
    canonical_csv = st.session_state.get(
        f"{STATE_PREFIX}mixed_canonical_csv",
        _default_participants_path(str(bids_root)),
    )

    # Let the backend resolve the canonical output path (derivatives/connectivity/...)
    seed_dir_name = cli_token_to_seed_dir_name(seed_input) if seed_input else ""
    expected_output = (
        Path(bids_root) / "derivatives" / "connectivity"
        / pipeline / "group" / "seed" / seed_dir_name / f"measure-{measure}"
        if seed_dir_name else None
    )

    col_info, col_submit = st.columns([2, 1])

    with col_info:
        st.info(f"""
        **Execution Settings:**
        - **Location**: {execution}
        - **Seed dir**: `{seed_dir_name or '(none selected)'}`
        - **Output**: `{expected_output or '(select a seed)'}`
        - **N Permutations**: {100 if use_test_perms and execution == "Local" else n_perm}
        - **Correction**: {correction}
        """)

    is_valid = st.session_state.get(f"{STATE_PREFIX}mixed_zmaps_valid", False) and seed_input

    with col_submit:
        if st.button(
            "🚀 Submit",
            key=f"{STATE_PREFIX}mixed_submit",
            type="primary",
            disabled=not is_valid,
        ):
            if not is_valid:
                st.error("Please validate zmaps first and select a seed")
            else:
                with st.spinner("Submitting analysis..."):
                    try:
                        effective_n_perm = 100 if (use_test_perms and execution == "Local") else n_perm

                        if execution == "Local":
                            _submit_mixed_design_local(
                                bids_root,
                                seed_input,
                                pipeline,
                                measure,
                                canonical_csv,
                                effective_n_perm,
                                correction,
                                mask_input or None,
                            )
                        else:
                            _submit_mixed_design_hpc(
                                config,
                                bids_root,
                                seed_input,
                                pipeline,
                                measure,
                                canonical_csv,
                                n_perm,
                                correction,
                                mask_input or None,
                            )
                    except Exception as e:
                        st.error(f"Submission failed: {e}")


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
    cmd = [
        "python", "neuconn_app/scripts/group_mixed_design_stats.py",
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

    st.code(" ".join(cmd), language="bash")

    with st.spinner("Running analysis... (this may take 10+ minutes for full permutations)"):
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)

            if result.returncode == 0:
                st.success("✅ Analysis completed!")
                seed_dir = cli_token_to_seed_dir_name(seed)
                out = (
                    Path(bids_root) / "derivatives" / "connectivity"
                    / pipeline / "group" / "seed" / seed_dir / f"measure-{measure}"
                )
                st.info(f"Results saved to: `{out}`")
            else:
                st.error(f"Analysis failed (exit {result.returncode}):\n```\n{result.stderr[-2000:]}\n```")
        except subprocess.TimeoutExpired:
            st.error("Analysis timed out (>1 hour)")
        except Exception as e:
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
) -> None:
    """Submit mixed-design analysis to HPC (output path resolved by backend)."""
    cmd = [
        "python", "neuconn_app/scripts/group_mixed_design_stats.py",
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

    st.code(" ".join(cmd), language="bash")
    st.info("ℹ️ HPC submission: Create a SLURM job script and upload to HPC. (Full HPC integration coming soon.)")


def render() -> None:
    st.title("📤 Submit Group Statistics")

    config = _get_config()
    bids_root = (
        config.get("paths", {}).get("project_root")
        or config.get("project_root")
        or config.get("paths", {}).get("bids_root")
        or "."
    )
    default_participants_path = _default_participants_path(str(bids_root))

    # --- Session state defaults ---
    st.session_state.setdefault(f"{STATE_PREFIX}template", "Voxel")
    st.session_state.setdefault(f"{STATE_PREFIX}kind", "Voxel")
    st.session_state.setdefault(f"{STATE_PREFIX}pipeline", "fc")
    st.session_state.setdefault(f"{STATE_PREFIX}group_csv", default_participants_path)
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
    # Mixed-design defaults
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_pipeline", "fc")
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_measure", "pearson")
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_seed", "")
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_n_perm", 5000)
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_correction", "TFCE")
    st.session_state.setdefault(f"{STATE_PREFIX}mixed_mask", "")
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
