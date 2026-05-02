"""
Subject Data page — participants metadata and BIDS conflict detection.

Allows uploading and editing the project's BIDS-standard participants.tsv
metadata directly in the UI, with fallback loading from legacy group.csv.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st

_PRIMARY_COLUMNS = ["participant_id", "Age", "Gender", "group"]
_REQUIRED_COLUMNS = ["participant_id", "group"]
_COLUMN_ALIASES = {
    "participant_id": "participant_id",
    "participantid": "participant_id",
    "subject_id": "participant_id",
    "subject": "participant_id",
    "group": "group",
    "age": "Age",
    "gender": "Gender",
    "sex": "Gender",
}


def _project_root(config: dict) -> Optional[Path]:
    project_root_str = (
        config.get("project_root") or config.get("paths", {}).get("project_root", "")
    )
    if not project_root_str:
        return None
    project_root = Path(project_root_str).expanduser()
    if not project_root.is_absolute():
        return None
    return project_root


def _locate_participants_tsv(config: dict) -> Optional[Path]:
    bids_dir_str = config.get("paths", {}).get("bids_dir", "")
    if bids_dir_str:
        bids_dir = Path(bids_dir_str).expanduser()
        if bids_dir.is_absolute():
            return bids_dir / "participants.tsv"

    project_root = _project_root(config)
    if project_root is None:
        return None
    return project_root / "bids" / "participants.tsv"


def _locate_legacy_group_csv(config: dict) -> Optional[Path]:
    project_root = _project_root(config)
    if project_root is None:
        return None
    return project_root / "group.csv"


def _standardize_metadata_columns(df: pd.DataFrame) -> pd.DataFrame:
    rename_map: dict[str, str] = {}
    for column in df.columns:
        normalized = column.strip().lower().replace(" ", "_")
        rename_map[column] = _COLUMN_ALIASES.get(normalized, column.strip())

    standardized = df.rename(columns=rename_map).copy()
    for column in _REQUIRED_COLUMNS:
        if column not in standardized.columns:
            standardized[column] = ""

    ordered_columns = [
        *[column for column in _PRIMARY_COLUMNS if column in standardized.columns],
        *[column for column in standardized.columns if column not in _PRIMARY_COLUMNS],
    ]
    return standardized.loc[:, ordered_columns]


def _read_table(path: Path) -> pd.DataFrame:
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    return pd.read_csv(path, sep=sep)


def _load_subject_data(participants_path: Path, legacy_csv_path: Optional[Path]) -> tuple[pd.DataFrame, Path]:
    if participants_path.exists():
        return _standardize_metadata_columns(_read_table(participants_path)), participants_path
    if legacy_csv_path and legacy_csv_path.exists():
        return _standardize_metadata_columns(_read_table(legacy_csv_path)), legacy_csv_path
    return pd.DataFrame(columns=_PRIMARY_COLUMNS), participants_path


def _read_uploaded_table(uploaded_name: str, uploaded_bytes: bytes) -> pd.DataFrame:
    sep = "\t" if uploaded_name.lower().endswith(".tsv") else ","
    return pd.read_csv(io.BytesIO(uploaded_bytes), sep=sep)


def _bids_subjects(config: dict) -> list[str]:
    bids_dir = Path(config.get("paths", {}).get("bids_dir", "")).expanduser()
    if not bids_dir.exists():
        return []
    return sorted(p.name for p in bids_dir.glob("sub-*") if p.is_dir())


def render() -> None:
    st.header("📋 Subject Data")
    st.caption(
        "Manage participant metadata for all subjects. "
        "The table is loaded from `bids/participants.tsv`, with fallback to legacy `group.csv`. "
        "Subjects present in BIDS but absent from the table are flagged."
    )

    config = st.session_state.get("config", {})
    participants_path = _locate_participants_tsv(config)
    legacy_csv_path = _locate_legacy_group_csv(config)

    if participants_path is None:
        st.error(
            "**Project root not configured.** "
            "Go to **Settings** and set `project_root` before using this page."
        )
        return

    if "subject_data_df" not in st.session_state or st.button(
        "🔄 Reload from disk",
        help="Re-read participants metadata from disk, discarding unsaved changes",
    ):
        df, loaded_from = _load_subject_data(participants_path, legacy_csv_path)
        st.session_state.subject_data_df = df
        st.session_state.subject_data_loaded_from = str(loaded_from)

    df: pd.DataFrame = _standardize_metadata_columns(st.session_state.subject_data_df.copy())
    st.session_state.subject_data_df = df

    loaded_from = Path(st.session_state.get("subject_data_loaded_from", str(participants_path)))
    if loaded_from != participants_path:
        st.info(
            f"Loaded legacy metadata from `{loaded_from}`. Saving will migrate it to `{participants_path}`."
        )

    bids_subs = _bids_subjects(config)
    table_subs = set(df.get("participant_id", pd.Series(dtype=str)).dropna().tolist())

    missing_from_table = [subject for subject in bids_subs if subject not in table_subs]
    extra_in_table = [subject for subject in table_subs if subject and subject not in set(bids_subs)]

    if missing_from_table:
        with st.expander(
            f"⚠️ {len(missing_from_table)} BIDS subject(s) not in participants.tsv",
            expanded=True,
        ):
            st.warning(
                "These subjects exist in the BIDS directory but have no participant metadata row. "
                "Add them to the table below and save."
            )
            st.write(", ".join(missing_from_table))
            if st.button(
                "➕ Add unlabelled subjects",
                help="Appends rows with group='' for all missing subjects",
            ):
                new_rows = pd.DataFrame(
                    {"participant_id": missing_from_table, "group": [""] * len(missing_from_table)}
                )
                df = pd.concat([df, new_rows], ignore_index=True)
                st.session_state.subject_data_df = _standardize_metadata_columns(df)
                st.rerun()

    if extra_in_table:
        st.info(
            f"ℹ️ {len(extra_in_table)} subject(s) in participants metadata are not present in the BIDS directory: "
            + ", ".join(extra_in_table)
        )

    st.subheader("Participant metadata")

    groups_seen = sorted(set(df.get("group", pd.Series(dtype=str)).dropna().unique()) - {""})
    col_config: dict = {
        "participant_id": st.column_config.TextColumn(
            "Participant ID",
            help="BIDS participant identifier, e.g. sub-033",
        ),
        "Age": st.column_config.TextColumn("Age"),
        "Gender": st.column_config.TextColumn("Gender"),
        "group": st.column_config.SelectboxColumn(
            "Group",
            options=groups_seen or ["Control", "Walking"],
            help="Intervention group for this participant",
        ),
    }
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
    edited = _standardize_metadata_columns(edited)
    st.session_state.subject_data_df = edited

    if not edited.empty and "group" in edited.columns:
        group_counts = edited["group"].value_counts(dropna=False)
        cols = st.columns(len(group_counts) + 1)
        cols[0].metric("Total subjects", len(edited))
        for i, (grp, cnt) in enumerate(group_counts.items(), 1):
            cols[i].metric(str(grp) if grp else "(unlabelled)", cnt)

    with st.expander("📂 Upload / Replace metadata", expanded=False):
        st.caption(
            "Upload a CSV/TSV with at minimum `participant_id` and `group` columns. "
            "Legacy `subject_id` uploads are accepted and converted automatically."
        )
        uploaded = st.file_uploader(
            "Upload participants metadata",
            type=["csv", "tsv"],
            key="participants_metadata_upload",
            label_visibility="collapsed",
        )
        if uploaded is not None:
            try:
                new_df = _standardize_metadata_columns(
                    _read_uploaded_table(uploaded.name, uploaded.read())
                )
                st.success(f"Loaded {len(new_df)} rows from `{uploaded.name}`")
                st.dataframe(new_df.head(10), width="stretch", hide_index=True)
                if st.button("✅ Apply uploaded metadata", type="primary"):
                    st.session_state.subject_data_df = new_df
                    st.rerun()
            except Exception as e:
                st.error(f"Could not parse uploaded file: {e}")

    st.markdown("---")
    save_col, _ = st.columns([1, 3])
    with save_col:
        if st.button("💾 Save to participants.tsv", type="primary", width="stretch"):
            final = _standardize_metadata_columns(st.session_state.subject_data_df)
            participant_ids = final["participant_id"].dropna().astype(str)
            dup_ids = participant_ids.duplicated()
            if dup_ids.any():
                st.error(
                    "Duplicate participant IDs detected: "
                    f"{', '.join(participant_ids[dup_ids].unique())}. Fix before saving."
                )
            else:
                try:
                    participants_path.parent.mkdir(parents=True, exist_ok=True)
                    final.to_csv(participants_path, sep="\t", index=False)
                    st.success(f"Saved {len(final)} rows to `{participants_path}`")
                    st.session_state.subject_data_loaded_from = str(participants_path)
                except Exception as e:
                    st.error(f"Could not save: {e}")

    st.caption(f"Target file: `{participants_path}`")
