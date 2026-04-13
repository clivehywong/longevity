"""
NeuConn - Neuroimaging Connectivity Suite
==========================================

A comprehensive Streamlit app for neuroimaging QC, preprocessing, and connectivity analysis.

Features:
- Multi-modality QC (anat, func, dwi, fmap)
- HPC preprocessing (fMRIPrep, QSIPrep, QSIRecon)
- Denoising (FSL FIX, ICA-AROMA)
- Connectivity analysis (local measures, seed-based, effective, graph theory)
- Group-level statistics (LME, ANCOVA, permutation tests)
- Comparison tools
- Pipeline automation

Usage:
    streamlit run app.py

Configuration:
    Edit config via Settings page or edit YAML directly in ~/neuconn_projects/
"""

import streamlit as st
from pathlib import Path
import sys

# Add utils to path
sys.path.insert(0, str(Path(__file__).parent))

from utils.config import load_config


# Page configuration
st.set_page_config(
    page_title="NeuConn - Neuroimaging Connectivity Suite",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded"
)


def main():
    """Main application entry point with hierarchical navigation."""

    # Initialize session state
    if 'config' not in st.session_state:
        try:
            # Try to load longevity project config
            longevity_config = Path.home() / "neuconn_projects" / "longevity.yaml"
            if longevity_config.exists():
                st.session_state.config = load_config(str(longevity_config))
            else:
                st.session_state.config = load_config()
        except Exception as e:
            st.error(f"Error loading config: {e}")
            st.session_state.config = {'paths': {}, 'project': {'name': 'Error'}}

    # Sidebar navigation
    st.sidebar.title("🧠 NeuConn")
    st.sidebar.markdown("Neuroimaging Connectivity Suite")
    st.sidebar.markdown("---")

    # Debug: Show config status
    st.sidebar.caption(f"📁 Project: {st.session_state.config.get('project', {}).get('name', 'Unknown')}")

    # Level 1: Main category
    category = st.sidebar.radio(
        "Select Category:",
        ["🔍 Data QC", "🧠 fMRI Analysis", "🔗 dMRI Analysis",
         "🔄 Comparison", "⚙️ Pipeline Builder", "⚙️ Settings"],
        key="main_category"
    )

    # Route based on category
    if category == "🔍 Data QC":
        render_data_qc()

    elif category == "🧠 fMRI Analysis":
        render_fmri_analysis()

    elif category == "🔗 dMRI Analysis":
        render_dmri_analysis()

    elif category == "🔄 Comparison":
        st.title("🔄 Comparison Tool")
        st.info("🚧 Implementation coming in Phase 9")

    elif category == "⚙️ Pipeline Builder":
        st.title("⚙️ Pipeline Builder")
        st.info("🚧 Implementation coming in Phase 10")

    elif category == "⚙️ Settings":
        render_settings()


def render_data_qc():
    """Render Data QC pages with modality-based organization."""

    # Level 2: Modality selection
    modality = st.sidebar.radio(
        "Select Modality:",
        ["📊 Dataset Overview", "🧠 Anatomical", "🎯 Functional",
         "🔗 Diffusion", "🗺️ Field Maps"],
        key="qc_modality"
    )

    if modality == "📊 Dataset Overview":
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "dataset_overview",
                Path(__file__).parent / "pages_general_qc" / "00_dataset_overview.py"
            )
            module = importlib.util.module_from_spec(spec)
            sys.modules['dataset_overview'] = module  # Register module
            spec.loader.exec_module(module)
            module.render()
        except Exception as e:
            st.error(f"❌ Error loading Dataset Overview: {e}")
            import traceback
            st.code(traceback.format_exc())

            # Fallback: show basic info
            st.write("Debug: Trying direct import...")
            st.write(f"App dir: {Path(__file__).parent}")
            st.write(f"Page path: {Path(__file__).parent / 'pages_general_qc' / '00_dataset_overview.py'}")
            st.write(f"Exists: {(Path(__file__).parent / 'pages_general_qc' / '00_dataset_overview.py').exists()}")

    elif modality == "🧠 Anatomical":
        # Level 3: QC tool
        tool = st.sidebar.selectbox(
            "QC Tool:",
            ["Visual Check", "Papaya Viewer", "Dimension Table", "Mark/Exclude"]
        )

        if tool == "Visual Check":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "anat_visual_check",
                Path(__file__).parent / "pages_general_qc" / "01_anat_visual_check.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        elif tool == "Papaya Viewer":
            st.info("🚧 Papaya Viewer coming in Phase 4")
        elif tool == "Dimension Table":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "dimension_table",
                Path(__file__).parent / "pages_general_qc" / "03_dimension_table.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        elif tool == "Mark/Exclude":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "exclusion_manager",
                Path(__file__).parent / "pages_general_qc" / "04_exclusion_manager.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()

    elif modality == "🎯 Functional":
        tool = st.sidebar.selectbox("QC Tool:", ["Visual Check", "Papaya Viewer", "Dimension Table", "Mark/Exclude"])

        if tool == "Visual Check":
            import importlib.util
            spec = importlib.util.spec_from_file_location("func_visual_check",
                Path(__file__).parent / "pages_general_qc" / "05_func_visual_check.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        elif tool == "Dimension Table":
            import importlib.util
            spec = importlib.util.spec_from_file_location("dimension_table",
                Path(__file__).parent / "pages_general_qc" / "03_dimension_table.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        elif tool == "Mark/Exclude":
            import importlib.util
            spec = importlib.util.spec_from_file_location("exclusion_manager",
                Path(__file__).parent / "pages_general_qc" / "04_exclusion_manager.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        else:
            st.info("🚧 Coming soon")

    elif modality == "🔗 Diffusion":
        tool = st.sidebar.selectbox("QC Tool:", ["Visual Check", "Papaya Viewer", "Dimension Table", "Mark/Exclude"])

        if tool == "Visual Check":
            import importlib.util
            spec = importlib.util.spec_from_file_location("dwi_visual_check",
                Path(__file__).parent / "pages_general_qc" / "06_dwi_visual_check.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        else:
            st.info("🚧 Coming soon")

    elif modality == "🗺️ Field Maps":
        tool = st.sidebar.selectbox("QC Tool:", ["Visual Check", "Papaya Viewer", "Dimension Table"])

        if tool == "Visual Check":
            import importlib.util
            spec = importlib.util.spec_from_file_location("fmap_visual_check",
                Path(__file__).parent / "pages_general_qc" / "07_fmap_visual_check.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        else:
            st.info("🚧 Coming soon")


def render_fmri_analysis():
    """Render fMRI analysis pages."""

    # Level 2: Pipeline stage
    stage = st.sidebar.radio(
        "Pipeline Stage:",
        ["🔧 Preprocessing", "👤 Subject-Level", "👥 Group-Level"],
        key="fmri_stage"
    )

    if stage == "🔧 Preprocessing":
        # Level 3: Preprocessing tool
        tool = st.sidebar.selectbox(
            "Preprocessing:",
            ["HPC Submit", "QC Reports", "FSL FIX", "fMRIPost-AROMA", "Denoising Comparison"]
        )

        if tool == "HPC Submit":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "hpc_submit",
                Path(__file__).parent / "pages_fmri" / "preprocessing" / "01_hpc_submit.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        else:
            st.title(f"🔧 fMRI Preprocessing - {tool}")
            st.info("🚧 Implementation coming in future phases")

    elif stage == "👤 Subject-Level":
        # Level 3: Analysis type
        analysis = st.sidebar.selectbox(
            "Analysis:",
            ["Local Measures", "Seed Connectivity", "Effective Connectivity"]
        )

        # All subject-level pages are stubs
        st.title(f"👤 fMRI Subject-Level - {analysis}")
        st.info("🚧 Implementation coming in Phases 7-11")

    elif stage == "👥 Group-Level":
        # Level 3: Analysis type
        analysis = st.sidebar.selectbox(
            "Analysis:",
            ["Voxelwise", "ROI Analysis", "Graph Theory", "Visualization"]
        )

        # All group-level pages are stubs
        st.title(f"👥 fMRI Group-Level - {analysis}")
        st.info("🚧 Implementation coming in Phases 8-11")


def render_dmri_analysis():
    """Render dMRI analysis pages."""

    # Similar structure to fMRI
    stage = st.sidebar.radio(
        "Pipeline Stage:",
        ["🔧 Preprocessing", "👤 Subject-Level", "👥 Group-Level"],
        key="dmri_stage"
    )

    st.info("🚧 dMRI pages coming in Phase 12")


def render_settings():
    """Render Settings page for configuration editing."""
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "settings_page",
            Path(__file__).parent / "pages_settings" / "settings_page.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.render()
    except Exception as e:
        st.error(f"Error loading Settings page: {e}")
        import traceback
        st.code(traceback.format_exc())


if __name__ == "__main__":
    main()
