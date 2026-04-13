"""
Anatomical Visual Check - All Images Per Subject

Shows ALL anatomical images for one subject on a single page:
- All sessions (ses-01, ses-02)
- All runs (run-01, run-02)
- All modalities (T1w, T2w)

This allows efficient QC review of all anatomical data at once.

Implementation: Phase 2 ✅
Updated: Added smart disk caching (Phase 3)
"""

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.visualization import plot_anat_montage
from utils.qc_database import (load_qc_database, save_qc_database,
                                get_qc_status, set_qc_status, get_qc_summary)


def render():
    st.header("🧠 Anatomical Visual Check - All Images")

    # Get config
    config = st.session_state.get('config', {})
    bids_dir = Path(config.get('paths', {}).get('bids_dir', ''))

    if not bids_dir or not bids_dir.exists():
        st.warning("⚠️ BIDS directory not configured or not found.")
        return

    # Get all subjects
    subjects = sorted([d.name for d in bids_dir.iterdir()
                      if d.is_dir() and d.name.startswith('sub-')])

    if not subjects:
        st.warning("No subjects found in BIDS directory.")
        return

    # Load QC database
    qc_db = load_qc_database(bids_dir)

    # Sidebar navigation
    with st.sidebar:
        st.markdown("---")
        st.subheader("Subject Selection")

        # Initialize subject index
        if 'anat_subject_idx' not in st.session_state:
            st.session_state.anat_subject_idx = 0

        # Navigation buttons FIRST (before selectbox to avoid conflicts)
        st.markdown("**Quick Navigation:**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("◀ Previous", key="prev_subj", use_container_width=True):
                if st.session_state.anat_subject_idx > 0:
                    st.session_state.anat_subject_idx -= 1
                    st.rerun()
        with col2:
            if st.button("Next ▶", key="next_subj", use_container_width=True):
                if st.session_state.anat_subject_idx < len(subjects) - 1:
                    st.session_state.anat_subject_idx += 1
                    st.rerun()

        st.markdown("---")

        # Subject selector (below buttons)
        subject_idx = st.selectbox(
            "Subject:",
            range(len(subjects)),
            format_func=lambda i: f"{subjects[i]} ({i+1}/{len(subjects)})",
            index=st.session_state.anat_subject_idx,
            key="subject_selector"
        )

        # Update state if manually changed via selectbox
        st.session_state.anat_subject_idx = subject_idx
        subject = subjects[subject_idx]

        # QC Summary
        st.markdown("---")
        st.markdown("**QC Summary:**")
        summary = get_qc_summary(qc_db)
        st.caption(f"✅ {summary['pass']} | ⚠️ {summary['review']} | ❌ {summary['fail']}")

    # Main panel - show all anatomical images for this subject
    st.subheader(f"Subject: {subject}")

    subject_dir = bids_dir / subject
    sessions = sorted([d.name for d in subject_dir.iterdir()
                      if d.is_dir() and d.name.startswith('ses-')])

    if not sessions:
        st.warning("No sessions found for this subject")
        return

    # Display all anatomical images
    for session in sessions:
        st.markdown(f"### 📅 {session}")

        anat_dir = subject_dir / session / "anat"

        if not anat_dir.exists():
            st.warning(f"Anatomical directory not found: {anat_dir}")
            continue

        # Get all anatomical files (T1w and T2w)
        t1w_files = sorted(anat_dir.glob(f"{subject}_{session}_*T1w.nii.gz"))
        t2w_files = sorted(anat_dir.glob(f"{subject}_{session}_*T2w.nii.gz"))

        anat_files = {
            'T1w': t1w_files,
            'T2w': t2w_files
        }

        # Debug: Show what was found
        st.caption(f"Found in {session}/anat/: T1w={len(t1w_files)}, T2w={len(t2w_files)}")

        for modality, files in anat_files.items():
            if not files:
                st.caption(f"No {modality} files found")
                continue

            st.markdown(f"#### {modality}")

            for file_path in files:
                # Extract run from filename
                parts = file_path.stem.split('_')
                run = None
                for part in parts:
                    if part.startswith('run-'):
                        run = part
                        break

                if not run:
                    run = 'acquisition'  # T2w typically has no run number

                # Get QC status
                current_qc = get_qc_status(qc_db, subject, session, run, modality)

                # Show QC badge
                qc_badge = "⚪"
                if current_qc:
                    status = current_qc['status']
                    if 'Pass' in status:
                        qc_badge = "✅"
                    elif 'Review' in status:
                        qc_badge = "⚠️"
                    elif 'Fail' in status:
                        qc_badge = "❌"

                st.markdown(f"**{qc_badge} {run}** - `{file_path.name}`")

                # Generate and display montage (disk cache via bids_dir)
                fig = plot_anat_montage(file_path, bids_dir=bids_dir)  # Works for both T1w and T2w

                if fig:
                    st.pyplot(fig)

                    # QC controls in expander
                    with st.expander(f"⚙️ QC Controls - {session} {run}"):
                        # Pre-fill
                        default_status_idx = 0
                        default_notes = ""

                        if current_qc:
                            status_text = current_qc['status']
                            if 'Pass' in status_text:
                                default_status_idx = 0
                            elif 'Review' in status_text:
                                default_status_idx = 1
                            elif 'Fail' in status_text:
                                default_status_idx = 2
                            default_notes = current_qc.get('notes', '')

                        qc_status = st.radio(
                            "Mark as:",
                            ["✅ Pass", "⚠️ Review", "❌ Fail"],
                            index=default_status_idx,
                            horizontal=True,
                            key=f"qc_{subject}_{session}_{run}_{modality}"
                        )

                        st.caption("ℹ️ *Marking as Fail saves the status. Use **Exclusion Manager** to move failed images to bids_excluded/*")

                        notes = st.text_area(
                            "Notes:",
                            value=default_notes,
                            key=f"notes_{subject}_{session}_{run}_{modality}"
                        )

                        if st.button("💾 Save", key=f"save_{subject}_{session}_{run}_{modality}"):
                            qc_db = set_qc_status(qc_db, subject, session, run, modality, qc_status, notes)
                            save_qc_database(bids_dir, qc_db)
                            st.success("✅ Saved!")
                            st.rerun()
                else:
                    st.error(f"Failed to load {file_path.name}")

                st.markdown("---")


if __name__ == "__main__":
    render()
