"""
Diffusion (DWI) Visual Check - All Images Per Subject

Shows b0 and high-b volumes for quality assessment.
Implementation: Phase 2 ✅
"""

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.visualization import plot_dwi_montage
from utils.qc_database import (load_qc_database, save_qc_database,
                                get_qc_status, set_qc_status, get_qc_summary)


def render():
    st.header("🔗 Diffusion Visual Check - All Images")

    config = st.session_state.get('config', {})
    bids_dir = Path(config.get('paths', {}).get('bids_dir', ''))

    if not bids_dir or not bids_dir.exists():
        st.warning("⚠️ BIDS directory not configured.")
        return

    subjects = sorted([d.name for d in bids_dir.iterdir()
                      if d.is_dir() and d.name.startswith('sub-')])

    qc_db = load_qc_database(bids_dir)

    # Sidebar navigation (same pattern as functional)
    with st.sidebar:
        st.markdown("---")
        if 'dwi_subject_idx' not in st.session_state:
            st.session_state.dwi_subject_idx = 0

        col1, col2 = st.columns(2)
        with col1:
            if st.button("◀ Previous", key="prev_dwi", use_container_width=True):
                if st.session_state.dwi_subject_idx > 0:
                    st.session_state.dwi_subject_idx -= 1
                    st.rerun()
        with col2:
            if st.button("Next ▶", key="next_dwi", use_container_width=True):
                if st.session_state.dwi_subject_idx < len(subjects) - 1:
                    st.session_state.dwi_subject_idx += 1
                    st.rerun()

        subject = subjects[st.selectbox("Subject:", range(len(subjects)),
                                        format_func=lambda i: subjects[i],
                                        index=st.session_state.dwi_subject_idx)]
        st.session_state.dwi_subject_idx = subjects.index(subject)

    st.subheader(f"Subject: {subject}")

    subject_dir = bids_dir / subject
    sessions = sorted([d.name for d in subject_dir.iterdir()
                      if d.is_dir() and d.name.startswith('ses-')])

    for session in sessions:
        st.markdown(f"### 📅 {session}")
        dwi_dir = subject_dir / session / "dwi"

        if not dwi_dir.exists():
            st.caption("No dwi/ directory")
            continue

        dwi_files = sorted(dwi_dir.glob(f"{subject}_{session}_*_dwi.nii.gz"))

        for file_path in dwi_files:
            run = [p for p in file_path.stem.split('_') if p.startswith('run-')]
            run = run[0] if run else 'single'

            current_qc = get_qc_status(qc_db, subject, session, run, 'dwi')
            qc_badge = "✅" if current_qc and 'Pass' in current_qc['status'] else "⚪"

            st.markdown(f"**{qc_badge} {run}** - `{file_path.name}`")

            with st.spinner("Loading DWI volumes..."):
                fig = plot_dwi_montage(file_path, bids_dir=bids_dir)

            if fig:
                st.pyplot(fig)
            else:
                st.error("Failed to load")

            st.markdown("---")


if __name__ == "__main__":
    render()
