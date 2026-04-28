"""
Seed-Based Connectivity Analysis

Interactive page for exploring seed-based connectivity with:
- Multi-atlas seed selection (DiFuMo256, Schaefer400)
- Subject/session selection
- Session-level: Papaya viewer for z-maps
- Group-level: Statistical clusters with anatomical labels
- Export functionality for results

Architecture:
- Subject-level tab: Individual z-maps with Papaya viewer
- Group-level tab: Cluster statistics, effect sizes, CSV export
- Sidebar: Atlas/seed/subject selection, filtering options

Author: NeuConn
"""

from __future__ import annotations

import sys
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np
import streamlit as st
import nibabel as nib
from datetime import datetime

# Add paths
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.bids import scan_bids_directory
from utils.config import load_config
from config import get_project_root, derive_project_paths
from utils.papaya_wrapper import render_papaya_viewer_streamlit, get_nifti_stats

logger = logging.getLogger(__name__)


# ============================================================================
# Data Loading & Caching
# ============================================================================

@st.cache_data
def load_roi_config(project_root: Path) -> Dict:
    """Load ROI configuration with seed definitions."""
    config_path = project_root / "neuconn_app" / "roi_config.json"
    if config_path.exists():
        with open(config_path) as f:
            return json.load(f)
    return {}


@st.cache_data
def get_available_seeds(roi_config: Dict) -> Dict[str, str]:
    """Extract seeds marked for connectivity analysis from ROI config."""
    seeds = {}
    for roi in roi_config.get("rois", []):
        if roi.get("use_as_seed"):
            seeds[roi["id"]] = roi["label"]
    return seeds


@st.cache_data
def get_available_atlases() -> Dict[str, str]:
    """Get available atlases for connectivity analysis."""
    return {
        "DiFuMo256": "DiFuMo 256 regions",
        "Schaefer400": "Schaefer 400 regions",
        "Combined": "Schaefer 200 + Tian subcortex",
    }


@st.cache_data
def find_subject_sessions(project_root: Path) -> Dict[str, List[str]]:
    """Find all available subjects and their sessions."""
    bids_dir = project_root / "bids"
    subject_sessions = {}
    
    if bids_dir.exists():
        for sub_dir in sorted(bids_dir.glob("sub-*")):
            subject = sub_dir.name
            sessions = sorted([
                ses_dir.name.replace("ses-", "")
                for ses_dir in sub_dir.glob("ses-*")
                if ses_dir.is_dir()
            ])
            if sessions:
                subject_sessions[subject] = sessions
    
    return subject_sessions


@st.cache_data
def find_connectivity_maps(
    results_dir: Path,
    atlas: str,
    seed: str,
    subject: Optional[str] = None,
    session: Optional[str] = None,
) -> List[Path]:
    """Find connectivity z-maps for given parameters."""
    if subject and session:
        # Subject-level map
        pattern = f"**/seed_{seed}_*atlas_{atlas}*_zmap*.nii.gz"
        maps = list(results_dir.glob(f"**/seed_based/**/{subject}_ses-{session}_*"))
        return sorted([m for m in maps if m.is_file()])
    else:
        # Group-level map
        pattern = f"**/group_seed_{seed}_*atlas_{atlas}*_zmap*.nii.gz"
        maps = list(results_dir.glob(f"**/group_analysis/**/{pattern}"))
        return sorted([m for m in maps if m.is_file()])


@st.cache_data
def find_group_stats_csv(
    results_dir: Path,
    atlas: str,
    seed: str,
) -> Optional[Path]:
    """Find group-level statistics CSV for given seed+atlas."""
    csv_path = results_dir / "group_analysis" / f"seed_{seed}_{atlas}_clusters.csv"
    if csv_path.exists():
        return csv_path
    
    # Alternative pattern
    for csv in results_dir.glob(f"**/group_analysis/**/*{seed}*{atlas}*clusters.csv"):
        return csv
    
    return None


def load_group_stats(csv_path: Path) -> Optional[pd.DataFrame]:
    """Load and parse group-level statistics."""
    try:
        df = pd.read_csv(csv_path)
        return df
    except Exception as e:
        logger.error(f"Error loading group stats {csv_path}: {e}")
        return None


# ============================================================================
# Sidebar Controls
# ============================================================================

def render_sidebar_controls(
    project_root: Path,
    roi_config: Dict,
) -> Tuple[str, str, str, Optional[str], Optional[str], str, Dict]:
    """Render sidebar controls and return selections."""
    
    with st.sidebar:
        st.header("📋 Analysis Controls")
        
        # Analysis level
        analysis_level = st.radio(
            "Analysis Level",
            ["Subject-Level", "Group-Level"],
            help="View individual or group statistics",
        )
        
        st.divider()
        
        # Atlas selection
        atlases = get_available_atlases()
        atlas = st.selectbox(
            "Select Atlas",
            options=list(atlases.keys()),
            format_func=lambda x: atlases[x],
            help="Choose atlas for seed definition and target space",
        )
        
        # Seed selection
        seeds = get_available_seeds(roi_config)
        if seeds:
            seed = st.selectbox(
                "Select Seed",
                options=list(seeds.keys()),
                format_func=lambda x: f"{x}: {seeds[x]}",
                help="Choose brain region for seed connectivity",
            )
        else:
            st.warning("⚠️ No seeds configured in roi_config.json")
            seed = "N/A"
        
        st.divider()
        
        # Subject/session selection (subject-level only)
        subject, session = None, None
        if analysis_level == "Subject-Level":
            subject_sessions = find_subject_sessions(project_root)
            if subject_sessions:
                subject = st.selectbox(
                    "Select Subject",
                    options=list(subject_sessions.keys()),
                    help="Choose subject for individual analysis",
                )
                
                if subject:
                    session_list = subject_sessions[subject]
                    session = st.selectbox(
                        "Select Session",
                        options=session_list,
                        format_func=lambda x: f"Session {x}",
                        help="Choose session for this subject",
                    )
            else:
                st.info("📁 No subjects found in BIDS directory")
        
        st.divider()
        
        # Display options
        st.markdown("### Display Options")
        
        # Threshold controls
        threshold_percentile = st.slider(
            "Display Threshold (%)",
            min_value=0,
            max_value=99,
            value=50,
            help="Set minimum z-value to display",
        )
        
        colormap = st.selectbox(
            "Colormap",
            ["Hot", "Cool", "Spectrum", "Jet", "Gray"],
            help="Select color scheme for z-map",
        )
        
        overlay_alpha = st.slider(
            "Overlay Transparency",
            min_value=0.0,
            max_value=1.0,
            value=0.7,
            step=0.1,
            help="Transparency of connectivity map overlay",
        )
        
        viewer_height = st.slider(
            "Viewer Height (px)",
            min_value=400,
            max_value=1000,
            value=600,
            step=50,
        )
        
        st.divider()
        
        # Info box
        st.markdown("### About")
        st.caption(
            """
            **Seed-based connectivity** maps show correlation between a seed 
            region and all other voxels in the brain.
            
            **Z-maps** are Fisher z-transformed correlation coefficients.
            Positive values = positive correlation.
            """
        )
        
        options = {
            "threshold_percentile": threshold_percentile,
            "colormap": colormap,
            "overlay_alpha": overlay_alpha,
            "viewer_height": viewer_height,
        }
    
    return analysis_level, atlas, seed, subject, session, analysis_level, options


# ============================================================================
# Subject-Level Display
# ============================================================================

def render_subject_level(
    project_root: Path,
    atlas: str,
    seed: str,
    subject: str,
    session: str,
    options: Dict,
) -> None:
    """Render subject-level connectivity visualization."""
    st.header(f"📊 Subject-Level Connectivity: {seed}")
    
    results_dir = project_root / "results"
    
    # Find connectivity maps
    maps = find_connectivity_maps(results_dir, atlas, seed, subject, session)
    
    if not maps:
        st.warning(
            f"❌ No connectivity maps found for:\n"
            f"- Subject: {subject}\n"
            f"- Session: ses-{session}\n"
            f"- Seed: {seed}\n"
            f"- Atlas: {atlas}"
        )
        st.info(
            "💡 Run the connectivity pipeline first using "
            "`script/master_full_connectivity_workflow.sh`"
        )
        return
    
    # If multiple maps (z-map, p-value, etc.), let user select
    if len(maps) > 1:
        selected_map = st.selectbox(
            "Select Map Type",
            options=maps,
            format_func=lambda x: x.name,
        )
    else:
        selected_map = maps[0]
    
    # Verify map exists
    if not selected_map.exists():
        st.error(f"Map file not found: {selected_map}")
        return
    
    # Get stats for automatic scaling
    try:
        stats = get_nifti_stats(str(selected_map))
        st.info(
            f"📈 **Map Statistics**\n"
            f"- Range: [{stats['min']:.3f}, {stats['max']:.3f}]\n"
            f"- Mean: {stats['mean']:.3f}\n"
            f"- 95th percentile: {stats['p95']:.3f}"
        )
    except Exception as e:
        logger.warning(f"Could not get NIfTI stats: {e}")
    
    # Render Papaya viewer
    st.subheader("🧠 Brain Map Viewer")
    try:
        render_papaya_viewer_streamlit(
            str(selected_map),
            height=options["viewer_height"],
            colormap=options["colormap"],
            threshold_range=(options["threshold_percentile"], 100),
        )
    except Exception as e:
        st.error(f"Error rendering map: {e}")
        logger.exception(e)
    
    # Metadata and export
    st.divider()
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📋 Map Details")
        st.write(f"**Path:** `{selected_map.name}`")
        st.write(f"**Subject:** {subject}")
        st.write(f"**Session:** ses-{session}")
        st.write(f"**Seed:** {seed}")
        st.write(f"**Atlas:** {atlas}")
    
    with col2:
        st.subheader("💾 Export")
        # Download NIfTI
        with open(selected_map, "rb") as f:
            nifti_data = f.read()
        st.download_button(
            label="⬇️ Download NIfTI",
            data=nifti_data,
            file_name=f"{subject}_ses-{session}_{seed}_{atlas}_zmap.nii.gz",
            mime="application/gzip",
        )


# ============================================================================
# Group-Level Display
# ============================================================================

def render_group_level(
    project_root: Path,
    atlas: str,
    seed: str,
    options: Dict,
) -> None:
    """Render group-level statistics and cluster visualization."""
    st.header(f"🌍 Group-Level Analysis: {seed}")
    
    results_dir = project_root / "results"
    
    # Find group stats CSV
    csv_path = find_group_stats_csv(results_dir, atlas, seed)
    
    if not csv_path:
        st.warning(
            f"❌ No group statistics found for:\n"
            f"- Seed: {seed}\n"
            f"- Atlas: {atlas}"
        )
        st.info(
            "💡 Run group-level analysis using:\n"
            "`bash script/master_full_connectivity_workflow.sh`"
        )
        return
    
    # Load statistics
    stats_df = load_group_stats(csv_path)
    if stats_df is None or stats_df.empty:
        st.error(f"Could not load or parse statistics from {csv_path}")
        return
    
    # Tabs for different views
    tab1, tab2, tab3 = st.tabs(["📊 Clusters", "📈 Statistics", "💾 Export"])
    
    with tab1:
        st.subheader("Brain Clusters")
        
        # Display cluster table with key columns
        cluster_cols = [col for col in stats_df.columns if col.lower() in 
                       ["cluster", "voxels", "p_value", "t_stat", "z_stat",
                        "anatomy", "region", "network"]]
        
        if cluster_cols:
            display_df = stats_df[cluster_cols].copy()
        else:
            display_df = stats_df.head(10)
        
        # Format numeric columns
        for col in display_df.select_dtypes(include=[np.number]).columns:
            display_df[col] = display_df[col].apply(lambda x: f"{x:.4f}")
        
        st.dataframe(display_df, use_container_width=True, height=400)
        
        # Summary statistics
        st.subheader("Cluster Summary")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            n_clusters = len(stats_df)
            st.metric("Number of Clusters", n_clusters)
        
        with col2:
            total_voxels = stats_df.get("voxels", pd.Series()).sum()
            st.metric("Total Voxels", int(total_voxels) if not np.isnan(total_voxels) else "N/A")
        
        with col3:
            # Significant clusters (p < 0.05)
            sig_threshold = 0.05
            if "p_value" in stats_df.columns:
                n_sig = (stats_df["p_value"] < sig_threshold).sum()
                st.metric("Significant Clusters (p<0.05)", n_sig)
    
    with tab2:
        st.subheader("Statistical Summary")
        
        # Distribution plots
        col1, col2 = st.columns(2)
        
        with col1:
            if "p_value" in stats_df.columns:
                st.write("**P-value Distribution**")
                st.bar_chart(
                    stats_df["p_value"].value_counts(bins=10, sort=False),
                    use_container_width=True
                )
        
        with col2:
            if "t_stat" in stats_df.columns or "z_stat" in stats_df.columns:
                stat_col = "t_stat" if "t_stat" in stats_df.columns else "z_stat"
                st.write(f"**{stat_col.upper()} Distribution**")
                st.bar_chart(
                    stats_df[stat_col].value_counts(bins=10, sort=False),
                    use_container_width=True
                )
        
        # Detailed statistics
        st.subheader("Descriptive Statistics")
        numeric_cols = stats_df.select_dtypes(include=[np.number]).columns
        summary = stats_df[numeric_cols].describe()
        st.dataframe(summary, use_container_width=True)
    
    with tab3:
        st.subheader("Export Results")
        
        # CSV download
        csv_buffer = stats_df.to_csv(index=False)
        st.download_button(
            label="⬇️ Download CSV",
            data=csv_buffer,
            file_name=f"group_{seed}_{atlas}_clusters_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
        )
        
        # JSON export
        json_buffer = stats_df.to_json(orient="records", indent=2)
        st.download_button(
            label="⬇️ Download JSON",
            data=json_buffer,
            file_name=f"group_{seed}_{atlas}_clusters_{datetime.now().strftime('%Y%m%d')}.json",
            mime="application/json",
        )
        
        # Find and offer group map download
        maps = find_connectivity_maps(results_dir, atlas, seed)
        if maps:
            st.write("**Available Group Maps:**")
            for map_path in maps[:3]:  # Limit to 3 maps
                with open(map_path, "rb") as f:
                    map_data = f.read()
                st.download_button(
                    label=f"⬇️ {map_path.name}",
                    data=map_data,
                    file_name=map_path.name,
                    mime="application/gzip",
                    key=f"download_{map_path.name}"
                )


# ============================================================================
# Main Render Function
# ============================================================================

def render():
    """Main page render function."""
    
    # Page config
    st.set_page_config(
        page_title="Seed-Based Connectivity",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    
    # Header
    st.header("🔗 Seed-Based Connectivity")
    st.markdown(
        """
        Explore functional connectivity from seed regions to the whole brain.
        
        **Features:**
        - 🌳 **Multi-atlas support**: DiFuMo256, Schaefer400, combined
        - 🧠 **Seed selection**: Motor, cognitive, subcortical seeds
        - 👤 **Subject-level**: Individual z-maps with Papaya viewer
        - 🌍 **Group-level**: Statistical clusters, anatomical labels, effect sizes
        - 📊 **Export**: Download results as NIfTI, CSV, or JSON
        """
    )
    
    # Get project configuration
    try:
        project_root = get_project_root()
        roi_config = load_roi_config(project_root)
    except Exception as e:
        st.error(f"❌ Error loading configuration: {e}")
        logger.exception(e)
        return
    
    # Sidebar controls
    try:
        analysis_level, atlas, seed, subject, session, _, options = render_sidebar_controls(
            project_root, roi_config
        )
    except Exception as e:
        st.error(f"❌ Error in sidebar controls: {e}")
        logger.exception(e)
        return
    
    # Main content
    try:
        if analysis_level == "Subject-Level":
            if subject and session:
                render_subject_level(project_root, atlas, seed, subject, session, options)
            else:
                st.info("👈 Select subject and session in sidebar")
        else:
            render_group_level(project_root, atlas, seed, options)
    
    except Exception as e:
        st.error(f"❌ Error rendering page: {e}")
        logger.exception(e)


if __name__ == "__main__":
    render()
