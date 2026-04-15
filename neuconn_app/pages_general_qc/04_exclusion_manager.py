"""
Exclusion Manager

Review QC-failed images and move them to bids_excluded/.

Two-step process:
1. Visual Check marks images as Fail
2. Exclusion Manager reviews and moves them

Implementation: Phase 2 ✅
"""

import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.qc_database import load_qc_database
from utils.bids import (move_to_excluded, restore_from_excluded,
                        load_exclusion_manifest, save_exclusion_manifest)


# ── Modality → BIDS subdirectory mapping ────────────────────────────────────
_FUNCTIONAL_MODALITIES = {"bold", "cbv", "phase"}
_DWI_MODALITIES = {"dwi"}
_FMAP_MODALITIES = {"epi", "fieldmap", "phasediff", "phase1", "phase2",
                    "magnitude", "magnitude1", "magnitude2"}


def _resolve_file_path(bids_dir: Path, scan: dict):
    """
    Return (file_path, file_pattern) with the correct BIDS subdirectory
    and correctly-prefixed filename stem.

    QC key formats stored by visual check pages:
      Anat:  sub-033_ses-01_run-01_T1w   → run field = "run-01"
      fMRI:  sub-066_ses-02_rest_bold     → run field = "rest" (bare task name)
    """
    subject = scan['subject']
    session = scan['session']
    run_raw = scan['run']
    modality = scan['modality']

    # 1. Determine BIDS subdirectory from modality
    if modality in _FUNCTIONAL_MODALITIES:
        subdir = "func"
    elif modality in _DWI_MODALITIES:
        subdir = "dwi"
    elif modality in _FMAP_MODALITIES:
        subdir = "fmap"
    else:
        subdir = "anat"

    # 2. Fix the run/task field for functional scans
    #    A bare task name (e.g. "rest") needs "task-" prepended.
    #    Already-prefixed values (e.g. "task-rest", "run-01") are left alone.
    if subdir == "func" and not any(run_raw.startswith(p)
                                    for p in ("task-", "run-", "dir-", "echo-")):
        run_in_filename = f"task-{run_raw}"
    else:
        run_in_filename = run_raw

    file_pattern = f"{subject}_{session}_{run_in_filename}_{modality}"
    file_path = bids_dir / subject / session / subdir / f"{file_pattern}.nii.gz"
    return file_path, file_pattern


def render():
    st.header("🗑️ Exclusion Manager")

    # Get config
    config = st.session_state.get('config', {})
    bids_dir = Path(config.get('paths', {}).get('bids_dir', ''))
    excluded_dir = Path(config.get('paths', {}).get('excluded_dir', ''))

    if not bids_dir or not bids_dir.exists():
        st.warning("⚠️ BIDS directory not configured.")
        return

    if not excluded_dir:
        excluded_dir = bids_dir.parent / "bids_excluded"

    # Load QC database
    qc_db = load_qc_database(bids_dir)

    # Filter for failed scans
    failed_scans = []
    for scan_key, qc_entry in qc_db.items():
        if 'Fail' in qc_entry['status']:
            # Parse key: sub-033_ses-01_run-01_T1w
            parts = scan_key.split('_')
            if len(parts) >= 4:
                failed_scans.append({
                    'key': scan_key,
                    'subject': parts[0],
                    'session': parts[1],
                    'run': parts[2],
                    'modality': parts[3],
                    'reason': qc_entry.get('notes', 'No reason specified'),
                    'timestamp': qc_entry.get('timestamp', 'Unknown')
                })

    # Load exclusion manifest
    exclusion_manifest = load_exclusion_manifest(excluded_dir)
    already_excluded = [entry['file'] for entry in exclusion_manifest]

    # Sidebar stats
    with st.sidebar:
        st.markdown("---")
        st.subheader("Statistics")
        st.metric("Failed (marked)", len(failed_scans))
        st.metric("Already Excluded", len(already_excluded))
        st.metric("Available in BIDS", len(failed_scans))

    # Main panel - two tabs
    tab1, tab2 = st.tabs(["📤 Move to Excluded", "📥 Already Excluded"])

    with tab1:
        st.subheader("Images Marked as Failed")

        if not failed_scans:
            st.info("✅ No images marked as failed. All scans passed QC!")
            return

        st.markdown(f"**{len(failed_scans)} images** marked as failed in QC:")

        # Select scans to exclude
        selected_to_exclude = []

        for scan in failed_scans:
            # Construct file path (handles anat/func/dwi/fmap + task- prefix)
            file_path, file_pattern = _resolve_file_path(bids_dir, scan)

            # Check if file exists (not already moved)
            if not file_path.exists():
                st.caption(f"⚠️ {file_pattern} - Already moved or not found")
                continue

            # Checkbox to select for exclusion
            col1, col2 = st.columns([3, 1])

            with col1:
                selected = st.checkbox(
                    f"**{scan['subject']}** / {scan['session']} / {scan['run']} / {scan['modality']}",
                    key=f"exclude_{file_pattern}",
                    value=True  # Pre-check failed scans
                )

                st.caption(f"Reason: {scan['reason']}")
                st.caption(f"Marked: {scan['timestamp'][:19]}")

            with col2:
                # Preview button
                if st.button("👁️ Preview", key=f"preview_{file_pattern}"):
                    st.session_state.preview_file = str(file_path)

            if selected:
                selected_to_exclude.append({
                    'scan': scan,
                    'file_path': file_path
                })

            st.markdown("---")

        # Bulk action
        if selected_to_exclude:
            st.markdown("---")
            col1, col2, col3 = st.columns([2, 2, 1])

            with col1:
                st.info(f"**{len(selected_to_exclude)}** images selected")

            with col2:
                if st.button("🗑️ Move Selected to Excluded", type="primary", width="stretch"):
                    # Confirm
                    if 'confirm_exclude' not in st.session_state:
                        st.session_state.confirm_exclude = True
                        st.warning("⚠️ Click again to confirm exclusion")
                        st.stop()

                    # Execute exclusion
                    with st.spinner("Moving files..."):
                        success_count = 0
                        errors = []

                        for item in selected_to_exclude:
                            result = move_to_excluded(
                                bids_dir,
                                excluded_dir,
                                item['scan']['subject'],
                                item['scan']['session'],
                                item['file_path'],
                                item['scan']['reason']
                            )

                            if result['status'] == 'success':
                                success_count += 1
                            else:
                                errors.append(result.get('message', 'Unknown error'))

                    st.success(f"✅ Successfully moved {success_count} files to {excluded_dir}")

                    if errors:
                        st.error(f"❌ {len(errors)} errors occurred")
                        for err in errors:
                            st.caption(f"  • {err}")

                    # Clear confirmation state
                    if 'confirm_exclude' in st.session_state:
                        del st.session_state.confirm_exclude

                    st.rerun()

            with col3:
                if st.button("🔄 Refresh"):
                    st.rerun()

    with tab2:
        st.subheader("Already Excluded")

        if not exclusion_manifest:
            st.info("No files have been excluded yet.")
            return

        st.markdown(f"**{len(exclusion_manifest)} files** in exclusion directory:")

        for entry in exclusion_manifest:
            file_path_excluded = excluded_dir / entry['file']

            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"**❌ {entry['file']}**")
                st.caption(f"Reason: {entry.get('reason', 'N/A')}")
                st.caption(f"Excluded: {entry.get('timestamp', 'Unknown')[:19]}")

            with col2:
                if st.button("↩️ Restore", key=f"restore_{entry['file']}"):
                    result = restore_from_excluded(bids_dir, excluded_dir, file_path_excluded)

                    if result['status'] == 'success':
                        st.success(f"✅ Restored to {result['restored']}")
                        st.rerun()
                    else:
                        st.error(f"❌ {result.get('message', 'Failed to restore')}")

            st.markdown("---")


if __name__ == "__main__":
    render()
