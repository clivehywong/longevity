"""
Group-Level Statistics Demo Page

Demonstrates the group_stats_ui component for interactive exploration
of group-level analysis results including:
- Method selection (GRF/TFCE/FDR)
- Dynamic thresholding
- Cluster table with anatomy
- Statistical summaries
- Export capabilities

Implementation: Phase 10
"""

import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.group_stats_ui import render_group_stats_ui


def render():
    """Main render function for group statistics page."""
    
    st.set_page_config(layout="wide", page_title="Group Statistics")
    
    st.title("📊 Group-Level Statistics Explorer")
    
    st.markdown("""
    Interactive exploration of group-level connectivity analysis results.
    
    **Features:**
    - 🎯 Correction method selection (GRF, TFCE, FDR)
    - 📈 Dynamic threshold controls
    - 🧠 Cluster table with anatomical labels
    - 📊 Statistical summaries and distributions
    - 📥 Export to CSV and text reports
    - 🔄 Method comparison (coming soon)
    """)
    
    st.markdown("---")
    
    # Sidebar for directory selection
    with st.sidebar:
        st.header("⚙️ Analysis Selection")
        
        analysis_type = st.selectbox(
            "Analysis Type:",
            options=['seed_based', 'local_measures', 'network_connectivity'],
            key='analysis_type_select'
        )
        
        # Default directories based on analysis type
        default_dirs = {
            'seed_based': '/home/clivewong/proj/longevity/derivatives/connectivity-difumo256/group-level/seed_based/dlpfc_l',
            'local_measures': '/home/clivewong/proj/longevity/results/group_analysis/local_measures',
            'network_connectivity': '/home/clivewong/proj/longevity/results/group_analysis/network_connectivity'
        }
        
        # Allow custom directory
        use_custom = st.checkbox("Use custom directory", value=False)
        
        if use_custom:
            results_dir = st.text_input(
                "Results directory:",
                value=default_dirs.get(analysis_type, ''),
                key='custom_results_dir'
            )
        else:
            results_dir = default_dirs.get(analysis_type, '')
            st.info(f"Using default: `{results_dir}`")
    
    # Main content
    if results_dir:
        render_group_stats_ui(
            group_results_dir=results_dir,
            analysis_type=analysis_type,
            title=f"Group-Level Statistics - {analysis_type.replace('_', ' ').title()}"
        )
    else:
        st.error("Please provide a valid results directory path.")


if __name__ == "__main__":
    render()
