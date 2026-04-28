"""
Papaya Viewer Streamlit Wrapper

Interactive NIfTI viewer component for Streamlit using Papaya.js.
Features:
- Load brain maps (NIfTI format, local/URL)
- Multiple atlas overlays with transparency control
- Interactive controls: threshold, colormap, coordinates
- Export to PNG
- Memory-efficient lazy loading of atlases

Author: NeuConn
License: MIT
"""

import streamlit as st
import base64
import json
import os
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import nibabel as nib
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# File Loading & Caching
# ============================================================================

@st.cache_data
def load_nifti_as_base64(file_path: str) -> str:
    """
    Load NIfTI file and convert to base64 for embedding in HTML.

    Args:
        file_path: Path to .nii or .nii.gz file

    Returns:
        Base64-encoded file content

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is not a valid NIfTI format
    """
    file_path = str(file_path)

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"NIfTI file not found: {file_path}")

    # Validate NIfTI format
    try:
        nib.load(file_path)  # Just verify it can be loaded
    except Exception as e:
        raise ValueError(f"Invalid NIfTI file {file_path}: {e}")

    with open(file_path, "rb") as f:
        file_bytes = f.read()

    b64_str = base64.b64encode(file_bytes).decode("utf-8")
    return b64_str


@st.cache_data
def get_nifti_stats(file_path: str) -> Dict[str, Any]:
    """
    Get statistics about NIfTI file for auto-scaling display range.

    Args:
        file_path: Path to NIfTI file

    Returns:
        Dictionary with shape, min, max, mean, percentiles
    """
    file_path = str(file_path)

    try:
        img = nib.load(file_path)
        data = img.get_fdata()

        # Filter out NaN and inf values for statistics
        valid_data = data[np.isfinite(data)]

        if len(valid_data) == 0:
            return {
                "shape": data.shape,
                "min": 0,
                "max": 1,
                "mean": 0,
                "p5": 0,
                "p95": 1,
            }

        return {
            "shape": data.shape,
            "min": float(np.min(valid_data)),
            "max": float(np.max(valid_data)),
            "mean": float(np.mean(valid_data)),
            "p5": float(np.percentile(valid_data, 5)),
            "p95": float(np.percentile(valid_data, 95)),
            "nonzero_voxels": int(np.count_nonzero(valid_data)),
        }
    except Exception as e:
        logger.error(f"Error getting NIfTI stats for {file_path}: {e}")
        return {
            "shape": (0, 0, 0),
            "min": 0,
            "max": 1,
            "mean": 0,
            "p5": 0,
            "p95": 1,
        }


# ============================================================================
# HTML/JavaScript Generation
# ============================================================================

def _create_papaya_html(
    brain_map_path: str,
    overlays: Optional[List[str]] = None,
    colormap: str = "Hot",
    threshold_range: Tuple[float, float] = (0, 100),
    overlay_alpha: float = 0.5,
    overlay_colormaps: Optional[List[str]] = None,
    height: int = 600,
    container_id: str = "papayaViewer",
) -> str:
    """
    Generate HTML/JavaScript for Papaya viewer.

    Args:
        brain_map_path: Primary brain map (local file or URL)
        overlays: List of overlay file paths (local or base64-encoded)
        colormap: Primary image colormap
        threshold_range: (min, max) threshold percentiles
        overlay_alpha: Transparency for overlay (0-1)
        overlay_colormaps: List of colormaps for each overlay
        height: Viewer height in pixels
        container_id: HTML container ID

    Returns:
        HTML string with embedded JavaScript
    """
    min_thresh, max_thresh = threshold_range

    # Prepare image array for Papaya params
    images = [brain_map_path]
    if overlays:
        images.extend(overlays)

    # Default colormaps for overlays
    if overlay_colormaps is None:
        overlay_colormaps = ["spectrum"] * len(overlays or [])

    # Create params JSON
    params_json = json.dumps([images])

    html = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">

    <div id="{container_id}" class="papaya" style="width: 100%; height: {height}px;"></div>

    <div id="papayaCoords" style="position: fixed; top: 20px; right: 20px; 
        background: rgba(0, 0, 0, 0.7); color: #0f0; padding: 12px; 
        font-family: monospace; border-radius: 5px; z-index: 1000; font-size: 12px;">
        MNI: (0.0, 0.0, 0.0) mm<br>
        Voxel: (0, 0, 0)
    </div>

    <script>
        // Initialize Papaya viewer
        var params = {params_json};
        var viewer = papaya.Container.addViewer("{container_id}", params);

        // Configure display settings after viewer loads
        setTimeout(function() {{
            if (viewer && viewer.viewer) {{
                var screenVolumes = viewer.viewer.screenVolumes;

                // Primary image settings
                if (screenVolumes.length > 0) {{
                    var primary = screenVolumes[0];
                    primary.colorMap = "{colormap}";
                    primary.intensityMin = {min_thresh};
                    primary.intensityMax = {max_thresh};
                }}

                // Overlay settings
                if (screenVolumes.length > 1) {{
                    for (var i = 1; i < screenVolumes.length; i++) {{
                        screenVolumes[i].alpha = {overlay_alpha};
                        // Assign colormap from array
                        var colormaps = {json.dumps(overlay_colormaps)};
                        if (i - 1 < colormaps.length) {{
                            screenVolumes[i].colorMap = colormaps[i - 1];
                        }}
                    }}
                }}

                viewer.viewer.drawViewer(true);
            }}
        }}, 800);

        // Update coordinate display on mouse move
        document.addEventListener("mousemove", function(event) {{
            if (viewer && viewer.viewer && viewer.viewer.currentCoord) {{
                var coords = viewer.viewer.currentCoord;
                var voxel = viewer.viewer.currentVoxel;
                var coordBox = document.getElementById("papayaCoords");
                if (coordBox) {{
                    coordBox.innerHTML =
                        "MNI: (" + coords[0].toFixed(1) + ", " +
                        coords[1].toFixed(1) + ", " +
                        coords[2].toFixed(1) + ") mm<br>" +
                        "Voxel: (" + (voxel ? voxel[0] : 0) + ", " +
                        (voxel ? voxel[1] : 0) + ", " +
                        (voxel ? voxel[2] : 0) + ")";
                }}
            }}
        }});

        // Export function (accessible from Streamlit)
        window.papayaExport = function() {{
            if (viewer && viewer.viewer && viewer.viewer.canvas) {{
                var canvas = viewer.viewer.canvas;
                var link = document.createElement("a");
                link.href = canvas.toDataURL("image/png");
                link.download = "brain_view_" + new Date().getTime() + ".png";
                link.click();
            }}
        }};
    </script>
    """

    return html


# ============================================================================
# Main Component
# ============================================================================

def render_papaya_viewer_streamlit(
    brain_map_path: str,
    title: str = "Brain Viewer",
    overlays: Optional[List[str]] = None,
    colormap: str = "Hot",
    threshold_range: Optional[Tuple[float, float]] = None,
    height: int = 600,
    key: Optional[str] = None,
    enable_export: bool = True,
    show_info: bool = True,
) -> Dict[str, Any]:
    """
    Render Papaya viewer in Streamlit with interactive controls.

    Main function for integrating Papaya viewer into Streamlit apps.

    Args:
        brain_map_path: Path to primary NIfTI file (local or URL, or base64 data URI)
        title: Header title for viewer section
        overlays: List of overlay NIfTI paths or base64 data URIs
        colormap: Colormap for primary image ('Hot', 'Cool', 'Grayscale', 'Spectrum', 'Red', 'Green', 'Blue')
        threshold_range: (min_percentile, max_percentile) for display range, defaults to auto
        height: Viewer height in pixels (default 600)
        key: Streamlit component key for state management
        enable_export: Show export button (default True)
        show_info: Show file information sidebar (default True)

    Returns:
        Dictionary with current viewer state:
        {
            "threshold_min": float,
            "threshold_max": float,
            "colormap": str,
            "overlay_alpha": float,
            "coordinates_mni": [x, y, z],
            "exported": bool
        }

    Example:
        >>> state = render_papaya_viewer_streamlit(
        ...     brain_map_path="derivatives/mni_brain.nii.gz",
        ...     overlays=["atlases/DiFuMo_256_MNI152_2mm.nii.gz"],
        ...     colormap="Hot",
        ...     height=700
        ... )
    """

    # Validate inputs
    if not brain_map_path:
        st.error("brain_map_path is required")
        return {}

    # Header
    st.markdown(f"### {title}")

    # Create container for layout (left: viewer, right: controls)
    col_main, col_sidebar = st.columns([3, 1])

    # ====================================================================
    # LEFT COLUMN: Viewer
    # ====================================================================

    with col_main:
        # Initialize session state for viewer controls
        state_key_prefix = key or "papaya"
        if f"{state_key_prefix}_threshold_min" not in st.session_state:
            st.session_state[f"{state_key_prefix}_threshold_min"] = 0
        if f"{state_key_prefix}_threshold_max" not in st.session_state:
            st.session_state[f"{state_key_prefix}_threshold_max"] = 100
        if f"{state_key_prefix}_colormap" not in st.session_state:
            st.session_state[f"{state_key_prefix}_colormap"] = colormap
        if f"{state_key_prefix}_overlay_alpha" not in st.session_state:
            st.session_state[f"{state_key_prefix}_overlay_alpha"] = 0.5
        if f"{state_key_prefix}_exported" not in st.session_state:
            st.session_state[f"{state_key_prefix}_exported"] = False

        # Load primary brain map
        try:
            if brain_map_path.startswith("data:") or brain_map_path.startswith("http"):
                # Already a data URI or URL
                primary_image = brain_map_path
                stats = None
            else:
                # Local file path
                primary_image = load_nifti_as_base64(brain_map_path)
                stats = get_nifti_stats(brain_map_path)

            # Load overlays
            overlay_images = []
            if overlays:
                for overlay_path in overlays:
                    try:
                        if overlay_path.startswith("data:") or overlay_path.startswith("http"):
                            overlay_images.append(overlay_path)
                        else:
                            overlay_images.append(load_nifti_as_base64(overlay_path))
                    except Exception as e:
                        st.warning(f"Could not load overlay {overlay_path}: {e}")

        except FileNotFoundError as e:
            st.error(f"❌ {e}")
            return {}
        except ValueError as e:
            st.error(f"❌ {e}")
            return {}

        # Prepare threshold range
        if threshold_range:
            min_thresh, max_thresh = threshold_range
        elif stats:
            # Auto-scale based on data
            p5 = stats["p5"]
            p95 = stats["p95"]
            min_thresh = max(0, (p5 - stats["min"]) / (stats["max"] - stats["min"]) * 100)
            max_thresh = min(100, (p95 - stats["min"]) / (stats["max"] - stats["min"]) * 100)
            min_thresh, max_thresh = int(min_thresh), int(max_thresh)
        else:
            min_thresh, max_thresh = 0, 100

        # Get current control values from sidebar
        threshold_min = st.session_state[f"{state_key_prefix}_threshold_min"]
        threshold_max = st.session_state[f"{state_key_prefix}_threshold_max"]
        current_colormap = st.session_state[f"{state_key_prefix}_colormap"]
        overlay_alpha = st.session_state[f"{state_key_prefix}_overlay_alpha"]

        # Generate and render HTML
        overlay_colormaps = ["spectrum"] * len(overlay_images)  # Default colormaps
        html_viewer = _create_papaya_html(
            brain_map_path=f"data:application/octet-stream;base64,{primary_image}"
            if not (brain_map_path.startswith("data:") or brain_map_path.startswith("http"))
            else primary_image,
            overlays=overlay_images,
            colormap=current_colormap,
            threshold_range=(threshold_min, threshold_max),
            overlay_alpha=overlay_alpha,
            overlay_colormaps=overlay_colormaps,
            height=height,
        )

        st.components.v1.html(html_viewer, height=height + 50)

    # ====================================================================
    # RIGHT COLUMN: Controls
    # ====================================================================

    with col_sidebar:
        st.markdown("**⚙️ Controls**")

        # Threshold slider
        st.session_state[f"{state_key_prefix}_threshold_min"] = st.slider(
            "Threshold Min (%)",
            min_value=0,
            max_value=100,
            value=threshold_min,
            step=1,
            key=f"{state_key_prefix}_thresh_min_slider",
        )

        st.session_state[f"{state_key_prefix}_threshold_max"] = st.slider(
            "Threshold Max (%)",
            min_value=0,
            max_value=100,
            value=threshold_max,
            step=1,
            key=f"{state_key_prefix}_thresh_max_slider",
        )

        # Colormap selector
        colormap_options = ["Hot", "Cool", "Grayscale", "Spectrum", "Red", "Green", "Blue"]
        selected_colormap = st.selectbox(
            "Colormap",
            options=colormap_options,
            index=colormap_options.index(current_colormap),
            key=f"{state_key_prefix}_colormap_select",
        )
        st.session_state[f"{state_key_prefix}_colormap"] = selected_colormap

        # Overlay transparency
        if overlay_images:
            st.session_state[f"{state_key_prefix}_overlay_alpha"] = st.slider(
                "Overlay Opacity",
                min_value=0.0,
                max_value=1.0,
                value=overlay_alpha,
                step=0.05,
                key=f"{state_key_prefix}_alpha_slider",
            )

        # Export button
        if enable_export:
            st.markdown("**📥 Export**")
            if st.button(
                "Export to PNG",
                key=f"{state_key_prefix}_export_btn",
                help="Right-click on Papaya viewer to also access native export",
            ):
                st.session_state[f"{state_key_prefix}_exported"] = True
                # Note: Actual export happens via JavaScript in the HTML viewer
                st.info("📸 Click 'Export as PNG' in the viewer to download")

        # File info
        if show_info and stats:
            st.markdown("**ℹ️ File Info**")
            st.caption(f"Shape: {stats['shape']}")
            st.caption(f"Min: {stats['min']:.2f}")
            st.caption(f"Max: {stats['max']:.2f}")
            st.caption(f"Nonzero: {stats['nonzero_voxels']}")

    # Return state
    return {
        "threshold_min": threshold_min,
        "threshold_max": threshold_max,
        "colormap": current_colormap,
        "overlay_alpha": overlay_alpha,
        "exported": st.session_state.get(f"{state_key_prefix}_exported", False),
    }


# ============================================================================
# Convenience Functions
# ============================================================================

def render_atlas_comparison(
    atlases: Dict[str, str],
    brain_template_path: Optional[str] = None,
    height: int = 600,
) -> None:
    """
    Render multiple atlases in tabs for side-by-side comparison.

    Args:
        atlases: Dictionary mapping atlas name to file path
        brain_template_path: Optional template to use as primary image
        height: Viewer height in pixels

    Example:
        >>> atlases = {
        ...     "DiFuMo 256": "atlases/DiFuMo_256_MNI152_2mm.nii.gz",
        ...     "AAL": "atlases/AAL_1mm_MNI152.nii.gz",
        ... }
        >>> render_atlas_comparison(atlases)
    """
    tabs = st.tabs(list(atlases.keys()))

    for tab, (atlas_name, atlas_path) in zip(tabs, atlases.items()):
        with tab:
            render_papaya_viewer_streamlit(
                brain_map_path=brain_template_path
                or "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz",
                overlays=[atlas_path],
                title=atlas_name,
                height=height,
                key=f"atlas_{atlas_name.replace(' ', '_')}",
            )


def get_available_atlases() -> Dict[str, str]:
    """
    Get dictionary of available atlases in project.

    Returns:
        Dictionary mapping atlas name to file path
    """
    atlas_base = Path("/home/clivewong/proj/longevity/atlases")
    atlases = {}

    if atlas_base.exists():
        # DiFuMo
        if (atlas_base / "difumo256.nii").exists():
            atlases["DiFuMo 256"] = str(atlas_base / "difumo256.nii")

        # Schaefer
        schaefer_path = atlas_base / "schaefer200_7net.nii"
        if schaefer_path.exists():
            atlases["Schaefer 200"] = str(schaefer_path)

        # AAL
        aal_dir = atlas_base / "aal"
        if aal_dir.exists():
            aal_files = list(aal_dir.glob("*.nii*"))
            if aal_files:
                atlases["AAL"] = str(aal_files[0])

    return atlases


if __name__ == "__main__":
    # Simple test
    st.set_page_config(layout="wide")
    st.title("Papaya Viewer Test")

    # Test with MNI template
    mni_template = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz"

    st.markdown("## Test 1: Basic Viewer")
    render_papaya_viewer_streamlit(
        brain_map_path=mni_template,
        title="MNI Template",
        height=600,
    )

    st.markdown("## Test 2: With Atlases")
    available = get_available_atlases()
    if available:
        st.markdown("### Atlas Comparison")
        render_atlas_comparison(available, brain_template_path=mni_template)
    else:
        st.info("No local atlases found")
