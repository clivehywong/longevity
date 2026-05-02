"""Shared helpers for the connectivity viewer pages.

Provides:
- Pipeline picker widget (persisted via session_state)
- Subject / session pickers driven by XcpdDiscovery
- load_relmat() — load a network relmat TSV → (np.ndarray, list[str])
- load_seed_to_parcel() — load seed-to-parcel TSV → pd.DataFrame
- list_available_seeds() — seeds with outputs under derivatives/connectivity/
- list_available_measures() — measures found for a given atlas/network dir
- Constants: KNOWN_MEASURES, CORRELATION_TYPE, CONNECTIVITY_ROOT
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

KNOWN_MEASURES: list[str] = [
    "pearson",
    "spearman",
    "partial_correlation",
    "plv",
    "wpli",
    "coherence",
    "amplitude_envelope_correlation",
    "mutual_information",
]

CORRELATION_TYPE: frozenset[str] = frozenset(
    {"pearson", "spearman", "partial_correlation"}
)

DEFAULT_PIPELINE = "fc"
KNOWN_PIPELINES: list[str] = ["fc", "fc_gsr", "ec"]

# Root under bids_root for connectivity outputs (relative)
CONNECTIVITY_ROOT = Path("derivatives") / "connectivity"


# ---------------------------------------------------------------------------
# Helpers that do NOT touch Streamlit
# ---------------------------------------------------------------------------


def connectivity_dir(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
) -> Path:
    """Return the per-subject-session connectivity output directory."""
    return bids_root / CONNECTIVITY_ROOT / pipeline / subject / session


def network_dir(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
    atlas: str,
) -> Path:
    """Return the network output directory for the given atlas."""
    return connectivity_dir(bids_root, pipeline, subject, session) / "network" / f"atlas-{atlas}"


def seed_dir(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
    seed_id: str,
) -> Path:
    """Return the seed output directory for the given seed ID."""
    return connectivity_dir(bids_root, pipeline, subject, session) / "seed" / seed_id


def relmat_filename(
    subject: str,
    session: str,
    atlas: str,
    measure: str,
) -> str:
    """Return the expected relmat TSV filename (with -z suffix for correlation measures)."""
    z = "-z" if measure in CORRELATION_TYPE else ""
    return f"{subject}_{session}_atlas-{atlas}_measure-{measure}_relmat{z}.tsv"


def relmat_path(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
    atlas: str,
    measure: str,
) -> Path:
    """Return the full path to the relmat TSV (may not exist)."""
    ndir = network_dir(bids_root, pipeline, subject, session, atlas)
    return ndir / relmat_filename(subject, session, atlas, measure)


@st.cache_data(ttl=60)
def load_relmat(
    bids_root_str: str,
    pipeline: str,
    subject: str,
    session: str,
    atlas: str,
    measure: str,
) -> tuple[Optional[np.ndarray], Optional[list[str]]]:
    """Load a network relmat TSV and return (matrix, labels).

    Returns (None, None) if the file does not exist or cannot be parsed.
    The first column is expected to be a row-index (integer); subsequent
    columns are parcel labels.
    """
    path = relmat_path(
        Path(bids_root_str), pipeline, subject, session, atlas, measure
    )
    if not path.exists():
        return None, None
    try:
        df = pd.read_csv(path, sep="\t", index_col=0)
        labels = list(df.columns)
        mat = df.values.astype(float)
        return mat, labels
    except Exception:
        return None, None


@st.cache_data(ttl=60)
def load_seed_to_parcel(
    bids_root_str: str,
    pipeline: str,
    subject: str,
    session: str,
    seed_id: str,
    atlas: str,
    measure: str,
) -> Optional[pd.DataFrame]:
    """Load seed-to-parcel TSV and return a single-row DataFrame with parcel columns.

    The pattern is:
      {subject}_{session}_seed-{seed_id}_atlas-{atlas}_measure-{measure}_seed-to-parcel.tsv
    or any file matching *_atlas-{atlas}_measure-{measure}_seed-to-parcel.tsv in
    the seed directory.

    Returns None if the file does not exist or cannot be parsed.
    """
    sdir = seed_dir(Path(bids_root_str), pipeline, subject, session, seed_id)
    if not sdir.exists():
        return None
    # Try exact name first
    exact = sdir / (
        f"{subject}_{session}_seed-{seed_id}"
        f"_atlas-{atlas}_measure-{measure}_seed-to-parcel.tsv"
    )
    if exact.exists():
        path = exact
    else:
        matches = sorted(
            sdir.glob(f"*_atlas-{atlas}_measure-{measure}_seed-to-parcel.tsv")
        )
        if not matches:
            return None
        path = matches[0]
    try:
        return pd.read_csv(path, sep="\t")
    except Exception:
        return None


def list_available_seeds(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
) -> list[str]:
    """Return seed IDs that have outputs under derivatives/connectivity/."""
    sdir = connectivity_dir(bids_root, pipeline, subject, session) / "seed"
    if not sdir.exists():
        return []
    return sorted(d.name for d in sdir.iterdir() if d.is_dir())


def list_available_atlases_network(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
) -> list[str]:
    """Return atlas names with network outputs for the given subject/session/pipeline."""
    ndir = connectivity_dir(bids_root, pipeline, subject, session) / "network"
    if not ndir.exists():
        return []
    return sorted(
        d.name.replace("atlas-", "")
        for d in ndir.iterdir()
        if d.is_dir() and d.name.startswith("atlas-")
    )


def list_available_measures(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
    atlas: str,
) -> list[str]:
    """Return measures for which relmat TSVs exist for the given atlas/subject/session."""
    ndir = network_dir(bids_root, pipeline, subject, session, atlas)
    if not ndir.exists():
        return []
    found: list[str] = []
    for measure in KNOWN_MEASURES:
        z = "-z" if measure in CORRELATION_TYPE else ""
        pattern = f"*_measure-{measure}_relmat{z}.tsv"
        if any(ndir.glob(pattern)):
            found.append(measure)
    return found


def list_available_measures_seed(
    bids_root: Path,
    pipeline: str,
    subject: str,
    session: str,
    seed_id: str,
    atlas: str,
) -> list[str]:
    """Return measures for which seed-to-parcel TSVs exist."""
    sdir = seed_dir(bids_root, pipeline, subject, session, seed_id)
    if not sdir.exists():
        return []
    found: list[str] = []
    for measure in KNOWN_MEASURES:
        pattern = f"*_atlas-{atlas}_measure-{measure}_seed-to-parcel.tsv"
        if any(sdir.glob(pattern)):
            found.append(measure)
    return found


# ---------------------------------------------------------------------------
# Streamlit widgets
# ---------------------------------------------------------------------------


def pipeline_picker(page_name: str) -> str:
    """Render pipeline selector; return selected pipeline name.

    State is persisted under session_state key ``viewer_pipeline_<page_name>``.
    """
    key = f"viewer_pipeline_{page_name}"
    if key not in st.session_state:
        st.session_state[key] = DEFAULT_PIPELINE
    pipeline = st.selectbox(
        "Pipeline",
        options=KNOWN_PIPELINES,
        index=KNOWN_PIPELINES.index(st.session_state[key]),
        key=key,
        help="fc = no global signal regression | fc_gsr = with GSR | ec = effective connectivity",
    )
    return pipeline


def subject_session_pickers(
    bids_root: Path,
    pipeline: str,
    page_key: str = "",
) -> tuple[Optional[str], Optional[str]]:
    """Render Subject + Session dropdowns driven by XcpdDiscovery.

    Returns (subject, session) or (None, None) if no data is available.
    """
    try:
        from utils.xcpd_outputs import XcpdDiscovery
    except Exception:
        from neuconn_app.utils.xcpd_outputs import XcpdDiscovery

    discovery = XcpdDiscovery(bids_root, pipeline=pipeline)
    subjects = discovery.list_subjects(pipeline)

    col1, col2 = st.columns(2)
    with col1:
        if not subjects:
            st.warning(f"No preprocessed subjects found for pipeline **{pipeline}**.")
            return None, None
        subject = st.selectbox(
            "Subject",
            options=subjects,
            format_func=lambda x: x.replace("sub-", ""),
            key=f"subject_{page_key}_{pipeline}",
        )

    with col2:
        sessions = discovery.list_sessions(subject, pipeline)
        if not sessions:
            st.warning(f"No sessions found for {subject} in pipeline {pipeline}.")
            return subject, None
        session = st.selectbox(
            "Session",
            options=sessions,
            format_func=lambda x: x.replace("ses-", ""),
            key=f"session_{page_key}_{pipeline}",
        )

    return subject, session
