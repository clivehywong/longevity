"""
Subject Data page — group assignments, demographics, and BIDS conflict detection.

Allows uploading and editing the project's group.csv (or other metadata files)
directly in the UI. Flags subjects present in BIDS but missing from the CSV.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

_GROUP_CSV_COLUMNS = ["subject_id", "group"]


def _locate_group_csv(config: dict) -> Optional[Path]:
    """Return expected path of group.csv, or None if project_root is not configured."""
    project_root_str = (
        config.get("project_root") or config.get("paths", {}).get("project_root", "")
    )
    if not project_root_str:
        return None
    project_root = Path(project_root_str).expanduser()
    if not project_root.is_absolute():
        return None
    return project_root / "group.csv"


def _load_group_csv(csv_path: Path) -> pd.DataFrame:
    if csv_path.exists():
        df = pd.read_csv(csv_path)
        # Normalise column names
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
        if "subject_id" not in df.columns and df.shape[1] >= 1:
            df.columns = _GROUP_CSV_COLUMNS[:df.shape[1]]
        return df
    return pd.DataFrame(columns=_GROUP_CSV_COLUMNS)


def _bids_subjects(config: dict) -> list[str]:
    bids_dir = Path(config.get("paths", {}).get("bids_dir", "")).expanduser()
    if not bids_dir.exists():
        return []
    return sorted(p.name for p in bids_dir.glob("sub-*") if p.is_dir())


def render() -> None:
    st.header("📋 Subject Data")
    st.caption(
        "Manage group assignments and demographics for all subjects. "
        "The table is loaded from `group.csv` in the project root. "
        "Subjects present in BIDS but absent from the table are flagged."
    )

    config = st.session_state.get("config", {})
    csv_path = _locate_group_csv(config)

    # Guard: project_root must be configured before any file I/O is allowed
    if csv_path is None:
        st.error(
            "**Project root not configured.** "
            "Go to **Settings** and set `project_root` before using this page."
        )
        return

    # ── Load or initialise state ─────────────────────────────────────────────
    if "subject_data_df" not in st.session_state or st.button(
        "🔄 Reload from disk", help="Re-read group.csv from disk, discarding unsaved changes"
    ):
        st.session_state.subject_data_df = _load_group_csv(csv_path)

    df: pd.DataFrame = st.session_state.subject_data_df.copy()

    # ── BIDS conflict detection ──────────────────────────────────────────────
    bids_subs = _bids_subjects(config)
    csv_subs = set(df.get("subject_id", pd.Series(dtype=str)).tolist())

    missing_from_csv = [s for s in bids_subs if s not in csv_subs]
    extra_in_csv = [s for s in csv_subs if s and s not in set(bids_subs)]

    if missing_from_csv:
        with st.expander(
            f"⚠️ {len(missing_from_csv)} BIDS subject(s) not in group.csv",
            expanded=True,
        ):
            st.warning(
                "These subjects exist in the BIDS directory but have no group assignment. "
                "Add them to the table below and save."
            )
            st.write(", ".join(missing_from_csv))
            if st.button("➕ Add unlabelled subjects", help="Appends rows with group='' for all missing subjects"):
                new_rows = pd.DataFrame(
                    {"subject_id": missing_from_csv, "group": [""] * len(missing_from_csv)}
                )
                df = pd.concat([df, new_rows], ignore_index=True)
                st.session_state.subject_data_df = df
                st.rerun()

    if extra_in_csv:
        st.info(
            f"ℹ️ {len(extra_in_csv)} subject(s) in group.csv are not present in the BIDS directory: "
            + ", ".join(extra_in_csv)
        )

    # ── Editable table ───────────────────────────────────────────────────────
    st.subheader("Group assignments")

    # Build column config with a constrained group dropdown where possible.
    # subject_id must remain editable when num_rows="dynamic" so users can
    # enter IDs for newly-added rows.  Validation is done at save time.
    groups_seen = sorted(set(df.get("group", pd.Series(dtype=str)).dropna().unique()) - {""})
    col_config: dict = {
        "subject_id": st.column_config.TextColumn(
            "Subject ID",
            help="BIDS subject identifier, e.g. sub-033",
        ),
        "group": st.column_config.SelectboxColumn(
            "Group",
            options=groups_seen or ["Control", "Walking"],
            help="Intervention group for this subject",
        ),
    }
    # Pass-through any extra columns as plain text
    for col in df.columns:
        if col not in col_config:
            col_config[col] = st.column_config.TextColumn(col)

    edited = st.data_editor(
        df,
        column_config=col_config,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        key="subject_data_editor",
    )
    st.session_state.subject_data_df = edited

    # ── Summary metrics ──────────────────────────────────────────────────────
    if not edited.empty and "group" in edited.columns:
        group_counts = edited["group"].value_counts(dropna=False)
        cols = st.columns(len(group_counts) + 1)
        cols[0].metric("Total subjects", len(edited))
        for i, (grp, cnt) in enumerate(group_counts.items(), 1):
            cols[i].metric(str(grp) if grp else "(unlabelled)", cnt)

    # ── CSV upload ───────────────────────────────────────────────────────────
    with st.expander("📂 Upload / Replace CSV", expanded=False):
        st.caption(
            "Upload a CSV with at minimum `subject_id` and `group` columns. "
            "Additional columns (age, sex, etc.) are preserved."
        )
        uploaded = st.file_uploader(
            "Upload group CSV",
            type=["csv"],
            key="group_csv_upload",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            try:
                new_df = pd.read_csv(io.BytesIO(uploaded.read()))
                new_df.columns = [c.strip().lower().replace(" ", "_") for c in new_df.columns]
                st.success(f"Loaded {len(new_df)} rows from `{uploaded.name}`")
                st.dataframe(new_df.head(10), width="stretch", hide_index=True)
                if st.button("✅ Apply uploaded CSV", type="primary"):
                    st.session_state.subject_data_df = new_df
                    st.rerun()
            except Exception as e:
                st.error(f"Could not parse CSV: {e}")

    # ── Save ─────────────────────────────────────────────────────────────────
    st.markdown("---")
    save_col, _ = st.columns([1, 3])
    with save_col:
        if st.button("💾 Save to group.csv", type="primary", width="stretch"):
            final = st.session_state.subject_data_df
            # Validate subject_id uniqueness before writing
            dup_ids = final["subject_id"].dropna().duplicated()
            if dup_ids.any():
                st.error(
                    f"Duplicate subject IDs detected: "
                    f"{', '.join(final['subject_id'][dup_ids].unique())}. "
                    "Fix before saving."
                )
            else:
                try:
                    final.to_csv(csv_path, index=False)
                    st.success(f"Saved {len(final)} rows to `{csv_path}`")
                except Exception as e:
                    st.error(f"Could not save: {e}")

    st.caption(f"File: `{csv_path}`")
