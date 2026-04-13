"""
Field Map Visual Check - All Images Per Subject

Shows AP/PA field maps side-by-side for comparison.
Implementation: Phase 2 ✅
"""

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.visualization import plot_fmap_comparison
from utils.qc_database import (load_qc_database, save_qc_database,
                                get_qc_status, set_qc_status, get_qc_summary)


def render():
    st.header("🗺️ Field Map Visual Check")

    config = st.session_state.get('config', {})
    bids_dir = Path(config.get('paths', {}).get('bids_dir', ''))

    if not bids_dir or not bids_dir.exists():
        st.warning("⚠️ BIDS directory not configured.")
        return

    subjects = sorted([d.name for d in bids_dir.iterdir()
                      if d.is_dir() and d.name.startswith('sub-')])

    qc_db = load_qc_database(bids_dir)

    # Sidebar
    with st.sidebar:
        st.markdown("---")
        st.subheader("Subject Selection")

        if 'fmap_subject_idx' not in st.session_state:
            st.session_state.fmap_subject_idx = 0

        # Navigation buttons FIRST (before selectbox)
        st.markdown("**Quick Navigation:**")
        col1, col2 = st.columns(2)
        with col1:
            if st.button("◀ Previous", key="prev_fmap_subj", use_container_width=True):
                if st.session_state.fmap_subject_idx > 0:
                    st.session_state.fmap_subject_idx -= 1
                    st.rerun()
        with col2:
            if st.button("Next ▶", key="next_fmap_subj", use_container_width=True):
                if st.session_state.fmap_subject_idx < len(subjects) - 1:
                    st.session_state.fmap_subject_idx += 1
                    st.rerun()

        st.markdown("---")

        # Subject selector AFTER buttons
        subject_idx = st.selectbox(
            "Subject:",
            range(len(subjects)),
            format_func=lambda i: f"{subjects[i]} ({i+1}/{len(subjects)})",
            index=st.session_state.fmap_subject_idx,
            key="fmap_subject_selector"
        )

        st.session_state.fmap_subject_idx = subject_idx
        subject = subjects[subject_idx]

        # QC Summary
        st.markdown("---")
        summary = get_qc_summary(qc_db)
        st.caption(f"✅ {summary['pass']} | ⚠️ {summary['review']} | ❌ {summary['fail']}")

    st.subheader(f"Subject: {subject}")

    subject_dir = bids_dir / subject
    sessions = sorted([d.name for d in subject_dir.iterdir()
                      if d.is_dir() and d.name.startswith('ses-')])

    for session in sessions:
        st.markdown(f"### 📅 {session}")
        fmap_dir = subject_dir / session / "fmap"

        if not fmap_dir.exists():
            st.caption("No fmap/ directory")
            continue

        # Find AP and PA pairs
        ap_files = sorted(fmap_dir.glob(f"{subject}_{session}_*_dir-AP_*.nii.gz"))
        pa_files = sorted(fmap_dir.glob(f"{subject}_{session}_*_dir-PA_*.nii.gz"))

        st.caption(f"Found: {len(ap_files)} AP, {len(pa_files)} PA")

        for ap_file in ap_files:
            # Try to find matching PA
            pa_file = None
            ap_base = ap_file.stem.replace('_dir-AP_', '_dir-PA_')
            for pf in pa_files:
                if ap_base in pf.stem:
                    pa_file = pf
                    break

            # Extract acq/run identifier
            run = 'single'
            for part in ap_file.stem.split('_'):
                if part.startswith('run-') or part.startswith('acq-'):
                    run = part
                    break

            # Get QC status
            current_qc = get_qc_status(qc_db, subject, session, run, 'fmap')
            qc_badge = "⚪"
            if current_qc:
                status = current_qc['status']
                if 'Pass' in status:
                    qc_badge = "✅"
                elif 'Review' in status:
                    qc_badge = "⚠️"
                elif 'Fail' in status:
                    qc_badge = "❌"

            st.markdown(f"**{qc_badge} {ap_file.name}**")
            if pa_file:
                st.caption(f"Paired with: {pa_file.name}")

            with st.spinner("Loading field maps..."):
                fig = plot_fmap_comparison(ap_file, pa_file, bids_dir=bids_dir)

            if fig:
                st.pyplot(fig)

                # QC controls
                with st.expander(f"⚙️ QC Controls - {session} {run}"):
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
                        key=f"qc_{subject}_{session}_{run}_fmap"
                    )

                    st.caption("ℹ️ *Use Exclusion Manager to move failed images*")

                    notes = st.text_area(
                        "Notes:",
                        value=default_notes,
                        key=f"notes_{subject}_{session}_{run}_fmap"
                    )

                    if st.button("💾 Save", key=f"save_{subject}_{session}_{run}_fmap"):
                        qc_db = set_qc_status(qc_db, subject, session, run, 'fmap', qc_status, notes)
                        save_qc_database(bids_dir, qc_db)
                        st.success("✅ Saved!")
                        st.rerun()
            else:
                st.error("Failed to load")

            st.markdown("---")


if __name__ == "__main__":
    render()
