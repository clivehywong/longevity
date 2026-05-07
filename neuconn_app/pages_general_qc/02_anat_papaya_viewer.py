"""
Example usage of Papaya Viewer in Streamlit

Interactive NIfTI viewer with atlas overlays.
Demonstrates different viewing modes and configurations.

Author: NeuConn
"""

import streamlit as st
import sys
from pathlib import Path

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent.parent / "utils"))

from papaya_wrapper import (
    render_papaya_viewer_streamlit,
    render_atlas_comparison,
    get_available_atlases,
)

# ============================================================================
# Page Configuration
# ============================================================================

def render():
    st.set_page_config(
        page_title="🧠 Papaya Brain Viewer",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    st.header("🔍 Anatomical Papaya Viewer")
    st.markdown(
        """
        Explore neuroimaging data with interactive 3-plane viewing, atlas overlays, and real-time coordinates.
        
        **Features:**
        - 🗺️ **Multiple atlases**: DiFuMo, Schaefer, AAL
        - 🎨 **Interactive controls**: Threshold, colormap, transparency
        - 📍 **Coordinate display**: Real-time MNI and voxel coordinates
        - 📥 **Export views**: Save screenshots as PNG
        """
    )

    # ====================================================================
    # Sidebar Configuration
    # ====================================================================

    with st.sidebar:
        st.markdown("### Configuration")

        # Viewing mode selector
        view_mode = st.radio(
            "View Mode",
            ["Template Only", "Template + Atlas", "Atlas Comparison"],
            help="Choose how to view brain data",
        )

        # Height control
        height = st.slider(
            "Viewer Height (pixels)",
            min_value=400,
            max_value=1000,
            value=600,
            step=50,
            help="Adjust viewer height for your screen",
        )

        st.markdown("---")
        st.markdown("### About")
        st.caption(
            """
            **Papaya.js** is a pure JavaScript NIfTI viewer.
            No server-side processing needed!
            
            [Documentation](https://papaya.readthedocs.io)
            """
        )

    # ====================================================================
    # Main Content
    # ====================================================================

    # MNI template URL (fallback template)
    MNI_TEMPLATE = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz"

    # ====================================================================
    # Mode 1: Template Only
    # ====================================================================

    if view_mode == "Template Only":
        st.markdown("## Standard MNI Template")
        st.caption("FSL's MNI152 T1 brain template (1mm resolution)")

        col1, col2 = st.columns([2, 1])

        with col1:
            state = render_papaya_viewer_streamlit(
                brain_map_path=MNI_TEMPLATE,
                title="MNI152 Template",
                colormap="Grayscale",
                height=height,
                key="mni_template",
                enable_export=True,
            )

        with col2:
            st.markdown("### Viewer State")
            st.json(state)

    # ====================================================================
    # Mode 2: Template + Atlas
    # ====================================================================

    elif view_mode == "Template + Atlas":
        st.markdown("## Template with Atlas Overlay")

        # Atlas selector
        available_atlases = get_available_atlases()

        if available_atlases:
            selected_atlas = st.selectbox(
                "Select Atlas",
                options=list(available_atlases.keys()),
                help="Choose an atlas to overlay on the template",
            )

            atlas_path = available_atlases[selected_atlas]

            st.caption(f"Displaying: **{selected_atlas}** overlay on MNI template")

            state = render_papaya_viewer_streamlit(
                brain_map_path=MNI_TEMPLATE,
                overlays=[atlas_path],
                title=f"{selected_atlas} Overlay",
                colormap="Grayscale",
                threshold_range=(20, 100),
                height=height,
                key=f"atlas_{selected_atlas}",
                enable_export=True,
            )

            st.markdown("### Viewer State")
            st.json(state)

        else:
            st.warning("⚠️ No local atlases found. Please check `/atlases/` directory.")

    # ====================================================================
    # Mode 3: Atlas Comparison
    # ====================================================================

    else:  # Atlas Comparison
        st.markdown("## Multi-Atlas Comparison")
        st.caption("View multiple atlases side-by-side")

        available_atlases = get_available_atlases()

        if len(available_atlases) >= 2:
            # Limit to 3 atlases for performance
            selected_atlases = st.multiselect(
                "Select Atlases (max 3)",
                options=list(available_atlases.keys()),
                default=list(available_atlases.keys())[:2],
                max_selections=3,
            )

            if selected_atlases:
                selected_dict = {name: available_atlases[name] for name in selected_atlases}

                render_atlas_comparison(
                    atlases=selected_dict,
                    brain_template_path=MNI_TEMPLATE,
                    height=height,
                )

        else:
            st.warning("⚠️ Need at least 2 atlases for comparison. Found: " f"{len(available_atlases)}")

    # ====================================================================
    # Footer
    # ====================================================================

    st.markdown("---")
    st.markdown(
        """
        <div style="text-align: center; color: gray; font-size: 12px;">
        <p>
            🧬 NeuConn Viewer | Papaya.js Integration<br>
            For support and documentation, see the app documentation.
        </p>
        </div>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    render()
