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
from utils.pipeline_state import load_pipeline_state


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
    render_pipeline_gate_summary(st.session_state.config)

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
        ["📊 Dataset Overview", "📋 Subject Data", "🧠 Anatomical", "🎯 Functional",
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

    elif modality == "📋 Subject Data":
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "subject_data",
            Path(__file__).parent / "pages_general_qc" / "08_subject_data.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.render()

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
    config = st.session_state.get("config", {})
    state = load_pipeline_state(config) if config else {}

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
            [
                "📊 fMRI Dashboard",
                "fMRIPrep Submit",
                "fMRIPrep QC Reports",
                "XCP-D Pipeline",
                "XCP-D QC Reports",
                "FSL FIX",
                "fMRIPost-AROMA",
                "Denoising Comparison",
            ]
        )

        if tool == "📊 fMRI Dashboard":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "fmri_dashboard",
                Path(__file__).parent / "pages_fmri" / "preprocessing" / "00_fmri_dashboard.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        elif tool == "fMRIPrep Submit":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "hpc_submit",
                Path(__file__).parent / "pages_fmri" / "preprocessing" / "01_hpc_submit.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        elif tool == "fMRIPrep QC Reports":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "fmriprep_qc_reports",
                Path(__file__).parent / "pages_fmri" / "preprocessing" / "02_qc_reports.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        elif tool == "XCP-D Pipeline":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "xcpd_pipeline",
                Path(__file__).parent / "pages_fmri" / "preprocessing" / "06_xcpd_pipeline.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        elif tool == "XCP-D QC Reports":
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "xcpd_qc_reports",
                Path(__file__).parent / "pages_fmri" / "preprocessing" / "07_xcpd_qc_reports.py"
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.render()
        else:
            st.title(f"🔧 fMRI Preprocessing - {tool}")
            st.info("🚧 Implementation coming in future phases")

    elif stage == "👤 Subject-Level":
        qc_approved = bool(state.get("approvals", {}).get("qc_gate", {}).get("approved"))
        if not qc_approved:
            st.warning("Subject-level analysis is locked until the Post-XCP-D QC gate is approved.")

        # Level 3: Analysis type
        analysis = st.sidebar.selectbox(
            "Analysis:",
            ["Local Measures", "Seed Connectivity", "Effective Connectivity"]
        )

        import importlib.util

        if analysis == "Local Measures":
            page_path = Path(__file__).parent / "pages_fmri" / "subject_level" / "01_local_measures.py"
            module_name = "fmri_subject_local_measures"
        elif analysis == "Seed Connectivity":
            page_path = Path(__file__).parent / "pages_fmri" / "subject_level" / "02_seed_connectivity.py"
            module_name = "fmri_subject_seed_connectivity"
        else:
            page_path = Path(__file__).parent / "pages_fmri" / "subject_level" / "03_effective_connectivity.py"
            module_name = "fmri_subject_effective_connectivity"

        spec = importlib.util.spec_from_file_location(module_name, page_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.render()

    elif stage == "👥 Group-Level":
        qc_approved = bool(state.get("approvals", {}).get("qc_gate", {}).get("approved"))
        subject_ready = state.get("steps", {}).get("subject_level", {}).get("status") == "completed"
        if not qc_approved:
            st.warning("Group-level analysis is locked until the Post-XCP-D QC gate is approved.")
            return
        if not subject_ready:
            st.warning("Group-level analysis is locked until subject-level outputs are generated.")
            return

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


def render_pipeline_gate_summary(config):
    """Show compact fMRI and dMRI pipeline gate state in the sidebar."""
    if not config:
        return

    state = load_pipeline_state(config)
    fd_gate = state.get("approvals", {}).get("fd_gate", {}).get("approved")
    qc_gate = state.get("approvals", {}).get("qc_gate", {}).get("approved")
    subject_status = state.get("steps", {}).get("subject_level", {}).get("status", "not_started")

    # Probe dMRI preprocessing dirs for basic gate indicators
    paths = config.get("paths", {})
    qsiprep_dir = paths.get("qsiprep_dir", "")
    dmri_ready = bool(qsiprep_dir and Path(qsiprep_dir).exists())

    st.sidebar.markdown("**fMRI gates**")
    st.sidebar.caption(f"{'🟢' if fd_gate else '🟠'} FD approval")
    st.sidebar.caption(f"{'🟢' if qc_gate else '🟠'} XCP-D QC approval")
    st.sidebar.caption(f"{'🟢' if subject_status == 'completed' else '⚪'} Subject-level outputs")

    st.sidebar.markdown("**dMRI gates**")
    st.sidebar.caption(f"{'🟢' if dmri_ready else '⚪'} QSIPrep outputs")
    st.sidebar.caption("⚪ Tractography QC")
    st.sidebar.markdown("---")


if __name__ == "__main__":
    main()
