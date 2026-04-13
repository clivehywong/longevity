"""
Dataset Overview - Entry Point for Data QC

Scans BIDS directory and displays:
- Available modalities (anat, func, dwi, fmap)
- Subject counts per modality
- Session counts
- File counts and sizes
- Missing data warnings
- BIDS validation status
- QC Image Cache Status and Pre-generation Controls

This is the first page users see to understand what data exists
before drilling into modality-specific QC tools.

Implementation: Phase 1 ✅
Updated: Added image cache status and pre-generation (Phase 3)
"""

import streamlit as st
import sys
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.bids import scan_bids_directory, detect_acquisition_params
from utils.image_cache import get_image_cache
from utils.qa_image_generator import (
    generate_anat_montage,
    generate_func_timepoints,
    generate_func_quality,
    generate_dwi_montage,
    generate_fmap_montage
)


@st.cache_data(ttl=None, show_spinner="Scanning BIDS directory...")
def cached_scan_bids(bids_dir: str):
    """Cache BIDS scan until manually refreshed."""
    return scan_bids_directory(Path(bids_dir))


@st.cache_data(ttl=None, show_spinner="Detecting acquisition parameters...")
def cached_detect_params(bids_dir: str):
    """Cache parameter detection until manually refreshed."""
    return detect_acquisition_params(Path(bids_dir))


def render():
    st.header("📊 Dataset Overview")

    # Get config
    config = st.session_state.get('config', {})

    bids_dir = config.get('paths', {}).get('bids_dir', '')

    if not bids_dir or bids_dir == '/path/to/bids':
        st.warning("⚠️ BIDS directory not configured. Please go to Settings to set up paths.")
        if st.button("→ Go to Settings"):
            st.session_state.main_category = "⚙️ Settings"
            st.rerun()
        return

    bids_path = Path(bids_dir)

    if not bids_path.exists():
        st.error(f"❌ BIDS directory not found: {bids_dir}")
        return

    # Add refresh button at the top
    col_header1, col_header2 = st.columns([3, 1])
    with col_header1:
        st.markdown(f"**BIDS Directory:** `{bids_dir}`")
    with col_header2:
        if st.button("🔄 Refresh Data", key="refresh_bids"):
            # Clear cache to force re-scan
            cached_scan_bids.clear()
            cached_detect_params.clear()
            st.rerun()

    # Scan BIDS directory (cached)
    bids_info = cached_scan_bids(bids_dir)

    if 'error' in bids_info:
        st.error(bids_info['error'])
        return

    # Display summary
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Subjects", len(bids_info['subjects']))

    with col2:
        st.metric("Total Sessions", len(bids_info['sessions']))

    with col3:
        total_files = sum(m['file_count'] for m in bids_info['modalities'].values())
        st.metric("Total Files", total_files)

    st.markdown("---")

    # Modalities found
    st.subheader("✅ Found Modalities")

    if not bids_info['modalities']:
        st.warning("⚠️ No imaging modalities detected. Check BIDS structure.")
        return

    for modality, info in bids_info['modalities'].items():
        with st.expander(f"📁 **{modality}/** - {info['subject_count']} subjects, {info['file_count']} files"):
            st.write(f"- **Subjects**: {info['subject_count']}")
            st.write(f"- **Sessions**: {info['session_count']}")
            st.write(f"- **Total files**: {info['file_count']}")

            # Show sample subjects
            if 'sample_subjects' in info and info['sample_subjects']:
                st.write("**Sample subjects:**")
                st.caption(", ".join(info['sample_subjects']))

    # Detect acquisition parameters (cached)
    st.markdown("---")
    st.subheader("🔍 Acquisition Parameters")

    acq_params = cached_detect_params(bids_dir)

    if acq_params['tr']:
        st.success(f"✅ **TR detected**: {acq_params['tr']} seconds")
    else:
        st.info("ℹ️ TR not detected. Will need to configure manually.")

    if acq_params['volumes']:
        vol_counts = [v['volumes'] for v in acq_params['volumes']]
        if len(set(vol_counts)) == 1:
            st.success(f"✅ **Volumes**: {vol_counts[0]} (consistent across all functional scans)")
        else:
            st.warning(f"⚠️ **Volumes**: Inconsistent - {set(vol_counts)}")

    if acq_params['inconsistencies']:
        st.warning(f"⚠️ **{len(acq_params['inconsistencies'])} inconsistencies detected:**")
        for issue in acq_params['inconsistencies'][:10]:
            st.text(f"  • {issue}")

    # QC Image Cache Status
    st.markdown("---")
    render_cache_section(bids_path)

    # Navigation
    st.markdown("---")
    st.subheader("Next Steps")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Visual QC"):
            st.info("Navigate to: Data QC -> Anatomical -> Visual Check")

    with col2:
        if st.button("Dimension Check"):
            st.info("Navigate to: Data QC -> (Modality) -> Dimension Table")

    with col3:
        if st.button("Start Preprocessing"):
            st.info("Navigate to: fMRI Analysis -> Preprocessing -> HPC Submit")


def render_cache_section(bids_dir: Path):
    """Render QC Image Cache status and controls."""
    st.subheader("QC Image Cache")

    try:
        cache = get_image_cache(bids_dir)
        stats = cache.get_cache_stats()

        # Cache status overview
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Total Images", stats['total'])
        with col2:
            st.metric("Cached", stats['cached'])
        with col3:
            st.metric("Cache Coverage", f"{stats['percentage']}%")

        # Detailed breakdown
        with st.expander("Cache Details by Type"):
            for img_type, type_stats in stats['by_type'].items():
                if type_stats['total'] > 0:
                    pct = round(100 * type_stats['cached'] / type_stats['total'], 1)
                    st.progress(pct / 100, text=f"{img_type}: {type_stats['cached']}/{type_stats['total']} ({pct}%)")

        # Pre-generation controls
        st.markdown("**Pre-Generate QC Images**")
        st.caption("Generate all QC images in background to speed up visual checks.")

        # Check if generation is running
        if cache.is_generating():
            progress = cache.get_progress()
            pct = progress['completed'] / max(progress['total'], 1)

            st.progress(pct, text=f"Generating: {progress['completed']}/{progress['total']}")

            if progress['current_file']:
                st.caption(f"Current: {progress['current_file']}")

            if st.button("Stop Generation", key="stop_gen"):
                cache.stop_background_generation()
                st.rerun()

            # Show errors if any
            if progress['errors']:
                with st.expander(f"Errors ({len(progress['errors'])})"):
                    for err in progress['errors'][:10]:
                        st.text(err)

            # Auto-refresh to update progress
            time.sleep(1)
            st.rerun()
        else:
            col1, col2, col3 = st.columns(3)

            with col1:
                if st.button("Pre-Generate All", key="gen_all", use_container_width=True):
                    start_background_generation(cache)
                    st.rerun()

            with col2:
                if st.button("Generate Missing Only", key="gen_missing", use_container_width=True):
                    start_background_generation(cache, force=False)
                    st.rerun()

            with col3:
                if st.button("Clear Cache", key="clear_cache", use_container_width=True):
                    cache.clear_cache()
                    st.success("Cache cleared!")
                    st.rerun()

        # Cache location info
        st.caption(f"Cache location: `{cache.cache_dir}`")

    except Exception as e:
        st.warning(f"Could not load cache status: {e}")


def start_background_generation(cache, force: bool = True):
    """Start background image generation."""
    generator_funcs = {
        'anat': generate_anat_montage,
        'func_timepoints': generate_func_timepoints,
        'func_quality': generate_func_quality,
        'dwi': generate_dwi_montage,
        'fmap': generate_fmap_montage
    }
    cache.start_background_generation(generator_funcs, force=force)


if __name__ == "__main__":
    render()
