"""
Functional (BOLD) Visual Check - All Images Per Subject

Shows ALL functional images for one subject:
- Both timepoint sampling (3x3) AND quality maps (mean/std/tSNR)
- All sessions
- QC controls

Implementation: Phase 2 ✅
Updated: Added smart disk caching (Phase 3)
"""

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.visualization import plot_functional_timepoints, plot_functional_quality_maps
from utils.qc_database import (load_qc_database, save_qc_database,
                                get_qc_status, set_qc_status, get_qc_summary)


def render():
    st.header("🎯 Functional Visual Check - All Images")

    config = st.session_state.get('config', {})
    bids_dir = Path(config.get('paths', {}).get('bids_dir', ''))

    if not bids_dir or not bids_dir.exists():
        st.warning("⚠️ BIDS directory not configured.")
        return

    subjects = sorted([d.name for d in bids_dir.iterdir()
                      if d.is_dir() and d.name.startswith('sub-')])

    if not subjects:
        st.warning("No subjects found.")
        return

    qc_db = load_qc_database(bids_dir)

    # Sidebar
    with st.sidebar:
        st.markdown("---")
        st.subheader("Subject Selection")

        if 'func_subject_idx' not in st.session_state:
            st.session_state.func_subject_idx = 0

        # Navigation buttons FIRST (before selectbox)
        st.markdown("**Quick Navigation:**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("◀ Previous", key="prev_func_subj", use_container_width=True):
                if st.session_state.func_subject_idx > 0:
                    st.session_state.func_subject_idx -= 1
                    st.rerun()
        with col2:
            if st.button("Next ▶", key="next_func_subj", use_container_width=True):
                if st.session_state.func_subject_idx < len(subjects) - 1:
                    st.session_state.func_subject_idx += 1
                    st.rerun()

        st.markdown("---")

        # Subject selector AFTER buttons
        subject_idx = st.selectbox(
            "Subject:",
            range(len(subjects)),
            format_func=lambda i: f"{subjects[i]} ({i+1}/{len(subjects)})",
            index=st.session_state.func_subject_idx,
            key="func_subject_selector"
        )

        # Sync state and get subject
        st.session_state.func_subject_idx = subject_idx
        subject = subjects[subject_idx]

        # QC Summary
        st.markdown("---")
        summary = get_qc_summary(qc_db)
        st.caption(f"✅ {summary['pass']} | ⚠️ {summary['review']} | ❌ {summary['fail']}")

    # Main panel
    st.subheader(f"Subject: {subject}")

    subject_dir = bids_dir / subject
    sessions = sorted([d.name for d in subject_dir.iterdir()
                      if d.is_dir() and d.name.startswith('ses-')])

    if not sessions:
        st.warning("No sessions found")
        return

    # Display all functional images
    for session in sessions:
        st.markdown(f"### 📅 {session}")

        func_dir = subject_dir / session / "func"

        if not func_dir.exists():
            st.caption(f"No func/ directory")
            continue

        bold_files = sorted(func_dir.glob(f"{subject}_{session}_*_bold.nii.gz"))

        if not bold_files:
            st.caption("No BOLD files found")
            continue

        for file_path in bold_files:
            # Extract task
            task = 'rest'
            for part in file_path.stem.split('_'):
                if part.startswith('task-'):
                    task = part.replace('task-', '')
                    break

            # Get QC status
            current_qc = get_qc_status(qc_db, subject, session, task, 'bold')

            qc_badge = "⚪"
            if current_qc:
                status = current_qc['status']
                if 'Pass' in status:
                    qc_badge = "✅"
                elif 'Review' in status:
                    qc_badge = "⚠️"
                elif 'Fail' in status:
                    qc_badge = "❌"

            st.markdown(f"**{qc_badge} task-{task}** - `{file_path.name}`")

            # Show BOTH timepoints and quality maps
            col1, col2 = st.columns(2)

            with col1:
                st.markdown("**Timepoint Sampling (10%, 50%, 90%)**")
                fig_time = plot_functional_timepoints(file_path, bids_dir=bids_dir)
                if fig_time:
                    st.pyplot(fig_time)
                else:
                    st.error("Failed to load")

            with col2:
                st.markdown("**Quality Maps (Mean, Std, tSNR)**")
                fig_quality = plot_functional_quality_maps(file_path, bids_dir=bids_dir)
                if fig_quality:
                    st.pyplot(fig_quality)
                else:
                    st.error("Failed to compute")

            # QC controls
            with st.expander(f"⚙️ QC Controls - {session} task-{task}"):
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
                    key=f"qc_{subject}_{session}_{task}_bold"
                )

                st.caption("ℹ️ *Use Exclusion Manager to move failed images*")

                notes = st.text_area(
                    "Notes:",
                    value=default_notes,
                    key=f"notes_{subject}_{session}_{task}_bold"
                )

                if st.button("💾 Save", key=f"save_{subject}_{session}_{task}_bold"):
                    qc_db = set_qc_status(qc_db, subject, session, task, 'bold', qc_status, notes)
                    save_qc_database(bids_dir, qc_db)
                    st.success("✅ Saved!")
                    st.rerun()

            st.markdown("---")


if __name__ == "__main__":
    render()
