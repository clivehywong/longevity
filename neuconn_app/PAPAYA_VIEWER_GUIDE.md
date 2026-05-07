# Papaya Viewer Streamlit Component Guide

## Overview

The **Papaya Viewer** is a Streamlit wrapper around [Papaya.js](https://papaya.readthedocs.io), a pure JavaScript NIfTI viewer that runs entirely in the browser. This component enables interactive brain map visualization with atlas overlays, coordinate display, and export functionality.

**Key Features:**
- 🗺️ Interactive 3-plane viewer (axial, coronal, sagittal)
- 🎨 Multiple colormaps and threshold controls
- 📍 Real-time coordinate display (MNI and voxel)
- 🧠 Multiple atlas overlays with transparency control
- 📥 Export views to PNG
- ⚡ Client-side rendering (no server-side processing)
- 💾 Memory-efficient lazy loading

## Installation

The component is part of the `neuconn_app` and requires:

```bash
# Dependencies are already in requirements.txt
pip install streamlit nibabel numpy
```

## Quick Start

### Basic Usage

```python
from neuconn_app.utils.papaya_wrapper import render_papaya_viewer_streamlit

# Load a brain map
state = render_papaya_viewer_streamlit(
    brain_map_path="path/to/brain.nii.gz",
    title="My Brain Map",
    height=600
)

# Access viewer state
print(state["threshold_min"], state["threshold_max"])
print(state["colormap"])
print(state["overlay_alpha"])
```

### With Atlas Overlay

```python
from neuconn_app.utils.papaya_wrapper import render_papaya_viewer_streamlit

state = render_papaya_viewer_streamlit(
    brain_map_path="mni_template.nii.gz",
    overlays=["atlases/DiFuMo_256_MNI152_2mm.nii.gz"],
    title="Brain + Atlas",
    colormap="Grayscale",
    threshold_range=(0, 100),
    overlay_alpha=0.5,
    height=700
)
```

### Multiple Atlases Comparison

```python
from neuconn_app.utils.papaya_wrapper import render_atlas_comparison

atlases = {
    "DiFuMo 256": "atlases/DiFuMo_256_MNI152_2mm.nii.gz",
    "Schaefer 200": "atlases/schaefer200_7net.nii",
    "AAL": "atlases/aal/AAL3v1_1mm.nii.gz",
}

render_atlas_comparison(
    atlases=atlases,
    brain_template_path="mni_template.nii.gz",
    height=600
)
```

### Discover Available Atlases

```python
from neuconn_app.utils.papaya_wrapper import get_available_atlases

atlases = get_available_atlases()
for name, path in atlases.items():
    print(f"{name}: {path}")
```

## API Reference

### `render_papaya_viewer_streamlit()`

Main function to render the Papaya viewer in Streamlit with interactive controls.

**Signature:**
```python
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
) -> Dict[str, Any]
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `brain_map_path` | str | **required** | Path to primary NIfTI file (local or URL) |
| `title` | str | "Brain Viewer" | Header title |
| `overlays` | List[str] | None | List of overlay paths |
| `colormap` | str | "Hot" | Primary image colormap |
| `threshold_range` | Tuple[float, float] | auto | (min%, max%) percentile range |
| `height` | int | 600 | Viewer height in pixels |
| `key` | str | None | Streamlit session state key |
| `enable_export` | bool | True | Show export button |
| `show_info` | bool | True | Show file info sidebar |

**Returns:**
```python
{
    "threshold_min": float,           # Current minimum threshold (%)
    "threshold_max": float,           # Current maximum threshold (%)
    "colormap": str,                  # Selected colormap
    "overlay_alpha": float,           # Overlay transparency (0-1)
    "exported": bool,                 # Export button clicked
}
```

**Example:**
```python
state = render_papaya_viewer_streamlit(
    brain_map_path="results/connectivity_map.nii.gz",
    overlays=["atlases/difumo256.nii"],
    colormap="Hot",
    threshold_range=(10, 90),
    height=700,
    key="conn_viewer"
)

if state["exported"]:
    st.success("View exported to PNG!")
```

---

### `render_atlas_comparison()`

Render multiple atlases in tabs for side-by-side comparison.

**Signature:**
```python
def render_atlas_comparison(
    atlases: Dict[str, str],
    brain_template_path: Optional[str] = None,
    height: int = 600,
) -> None
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `atlases` | Dict[str, str] | **required** | Mapping of atlas name to file path |
| `brain_template_path` | str | MNI template | Base template to use |
| `height` | int | 600 | Viewer height |

**Example:**
```python
atlases = {
    "DiFuMo 256": "atlases/difumo256.nii",
    "Schaefer 200": "atlases/schaefer200_7net.nii",
}

render_atlas_comparison(atlases, height=700)
```

---

### `get_available_atlases()`

Discover atlases in the project directory.

**Signature:**
```python
def get_available_atlases() -> Dict[str, str]
```

**Returns:**
```python
{
    "DiFuMo 256": "/path/to/difumo256.nii",
    "Schaefer 200": "/path/to/schaefer200_7net.nii",
    "AAL": "/path/to/aal/AAL3v1_1mm.nii.gz",
}
```

**Example:**
```python
available = get_available_atlases()
selected = st.selectbox("Choose atlas", options=available.keys())
atlas_path = available[selected]
```

---

### `load_nifti_as_base64()`

Load NIfTI file and convert to base64 for embedding (cached).

**Signature:**
```python
@st.cache_data
def load_nifti_as_base64(file_path: str) -> str
```

**Parameters:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `file_path` | str | Path to .nii or .nii.gz file |

**Returns:** Base64-encoded file content

**Raises:**
- `FileNotFoundError`: If file doesn't exist
- `ValueError`: If file is not valid NIfTI format

---

### `get_nifti_stats()`

Extract statistics from NIfTI file for auto-scaling (cached).

**Signature:**
```python
@st.cache_data
def get_nifti_stats(file_path: str) -> Dict[str, Any]
```

**Returns:**
```python
{
    "shape": (nx, ny, nz),      # Dimensions
    "min": float,               # Minimum value
    "max": float,               # Maximum value
    "mean": float,              # Mean value
    "p5": float,                # 5th percentile
    "p95": float,               # 95th percentile
    "nonzero_voxels": int,      # Number of non-zero voxels
}
```

---

## File Input Support

The viewer supports multiple file input modes:

### 1. Local File Paths

```python
render_papaya_viewer_streamlit(
    brain_map_path="/path/to/local/brain.nii.gz",
    overlays=["/path/to/atlas.nii.gz"]
)
```

### 2. URLs (HTTP/HTTPS)

```python
render_papaya_viewer_streamlit(
    brain_map_path="https://example.com/brain.nii.gz",
    overlays=["https://example.com/atlas.nii.gz"]
)
```

### 3. Base64 Data URIs

```python
import base64

with open("brain.nii.gz", "rb") as f:
    b64_data = base64.b64encode(f.read()).decode()

render_papaya_viewer_streamlit(
    brain_map_path=f"data:application/octet-stream;base64,{b64_data}"
)
```

### 4. Streamlit File Upload

```python
uploaded = st.file_uploader("Upload NIfTI", type=["nii", "nii.gz"])

if uploaded:
    # File is automatically converted to bytes
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=".nii.gz") as tmp:
        tmp.write(uploaded.getbuffer())
        render_papaya_viewer_streamlit(brain_map_path=tmp.name)
```

---

## Colormaps

Available colormap options:

| Colormap | Best For |
|----------|----------|
| **Hot** | Statistical maps, contrast (default) |
| **Cool** | Functional connectivity |
| **Grayscale** | Structural images |
| **Spectrum** | Rainbow scale for multi-region maps |
| **Red** | Single region overlays |
| **Green** | Positive values only |
| **Blue** | Negative values only |

**Example:**
```python
render_papaya_viewer_streamlit(
    brain_map_path="brain.nii.gz",
    colormap="Spectrum"  # Rainbow colormap
)
```

---

## Threshold Control

Thresholds are specified as percentiles (0-100) of the data distribution:

```python
# Auto-scale based on data distribution
render_papaya_viewer_streamlit(
    brain_map_path="stat_map.nii.gz",
    threshold_range=None  # Auto
)

# Manual percentile thresholding
render_papaya_viewer_streamlit(
    brain_map_path="stat_map.nii.gz",
    threshold_range=(5, 95)  # Exclude bottom 5% and top 5%
)

# Fixed range
render_papaya_viewer_streamlit(
    brain_map_path="stat_map.nii.gz",
    threshold_range=(0, 100)  # Show all
)
```

---

## Overlay Transparency

Control overlay opacity with the overlay_alpha slider (0.0 = transparent, 1.0 = opaque):

```python
render_papaya_viewer_streamlit(
    brain_map_path="mni_template.nii.gz",
    overlays=["atlas.nii.gz"],
    # Default overlay_alpha is 0.5 (50% transparent)
    # User can adjust with slider in sidebar
)
```

The `overlay_alpha` is accessible in the returned state:

```python
state = render_papaya_viewer_streamlit(...)
print(f"Current overlay opacity: {state['overlay_alpha'] * 100}%")
```

---

## Coordinate Display

The viewer displays coordinates in two formats in real-time:

- **MNI coordinates**: Standard neuroimaging space (mm)
- **Voxel coordinates**: Array indices into the NIfTI file

These appear in a fixed box in the top-right corner of the viewer as you move the mouse.

**Note:** Coordinate display is automatic and requires no configuration.

---

## Export Functionality

Users can export the current view as PNG by clicking the "Export to PNG" button in the sidebar.

The exported image captures:
- Current 3-plane view
- Colormap and thresholding
- Atlas overlays
- Current coordinates

**Note:** Export uses the browser's canvas API. The image dimensions match the viewer size.

---

## Performance Considerations

### Caching

The wrapper uses Streamlit's `@st.cache_data` for:
- NIfTI file loading (base64 conversion)
- Statistics calculation
- Large files are only loaded once per session

### File Size Limits

- Recommended: NIfTI files ≤ 100 MB
- Hard limit: Browser memory (typically 500 MB - 2 GB)
- Large files may take longer to convert to base64

### Lazy Loading

Atlases are loaded only when:
1. User selects them in the UI
2. They're explicitly passed to `render_papaya_viewer_streamlit()`

---

## Troubleshooting

### Viewer doesn't load

**Problem:** Blank viewer area or Papaya JS error in console.

**Solutions:**
1. Check browser console (F12) for JavaScript errors
2. Verify NIfTI file format: `python -c "import nibabel as nib; nib.load('file.nii.gz')"`
3. Try with a known-good file (e.g., MNI template URL)

### File not found error

**Problem:** "FileNotFoundError: NIfTI file not found"

**Solutions:**
1. Use absolute paths for local files
2. Verify file exists: `ls -lh /path/to/file.nii.gz`
3. Check file permissions: `stat /path/to/file.nii.gz`

### Overlay not showing

**Problem:** Overlay not visible even with opacity slider set to > 0.

**Solutions:**
1. Check overlay threshold range (may be too low)
2. Verify overlay file is valid: `nibabel-ls overlay.nii.gz`
3. Try increasing overlay opacity to 1.0 for testing
4. Check that primary image and overlay are in same space (MNI)

### Slow performance

**Problem:** Viewer is laggy or unresponsive.

**Solutions:**
1. Reduce viewer height (decreases canvas size)
2. Use lower-resolution atlas
3. Close other browser tabs
4. Try a different browser (Chrome typically fastest)

### Coordinates not updating

**Problem:** Coordinate display shows (0, 0, 0) and doesn't change.

**Solutions:**
1. Move mouse over the viewer (coordinates update on mousemove)
2. Refresh page (Ctrl+R or Cmd+R)
3. Check browser console for JavaScript errors

---

## Advanced Usage

### Custom Streamlit Integration

```python
import streamlit as st
from neuconn_app.utils.papaya_wrapper import render_papaya_viewer_streamlit

st.set_page_config(layout="wide")

# Two-column layout
col1, col2 = st.columns(2)

with col1:
    st.subheader("Connectivity Map")
    state1 = render_papaya_viewer_streamlit(
        brain_map_path="results/connectivity.nii.gz",
        key="conn1"
    )

with col2:
    st.subheader("Functional Atlas")
    state2 = render_papaya_viewer_streamlit(
        brain_map_path="atlases/functional_atlas.nii.gz",
        key="conn2"
    )

# Process states
if st.button("Compare Thresholds"):
    st.write(f"Map 1 threshold: {state1['threshold_min']}-{state1['threshold_max']}%")
    st.write(f"Map 2 threshold: {state2['threshold_min']}-{state2['threshold_max']}%")
```

### Dynamic Atlas Loading

```python
import streamlit as st
from neuconn_app.utils.papaya_wrapper import (
    render_papaya_viewer_streamlit,
    get_available_atlases
)

available = get_available_atlases()
selected = st.selectbox("Atlas:", options=available.keys())

state = render_papaya_viewer_streamlit(
    brain_map_path="mni_template.nii.gz",
    overlays=[available[selected]],
    title=f"Viewing: {selected}",
    key=f"atlas_{selected}"
)
```

### Seed-based Analysis Viewer

```python
import streamlit as st
from neuconn_app.utils.papaya_wrapper import render_papaya_viewer_streamlit

# Assume we have seed coordinates
seed_coords = (0, 10, -10)  # MNI coordinates

st.markdown(f"### Seed-based connectivity from {seed_coords}")

render_papaya_viewer_streamlit(
    brain_map_path="results/seed_connectivity.nii.gz",
    overlays=["atlases/roi_seed.nii.gz"],
    colormap="Hot",
    threshold_range=(10, 90),
    height=700
)
```

---

## Limitations

1. **No multi-file loading**: Main image + overlays only (not arbitrary image stacking)
2. **No 3D rendering**: Displays 2D slices (3-plane orthogonal view)
3. **No statistical overlays**: No p-value masking or multiple comparison correction UI
4. **Client-side only**: Large files (>500 MB) may not work in all browsers
5. **No region annotation**: Click-to-label regions not currently supported

---

## See Also

- [Papaya.js Documentation](https://papaya.readthedocs.io)
- [NIfTI Format Spec](https://nifti.nimh.nih.gov/)
- [Nibabel Documentation](https://nipy.org/nibabel/)
- [Streamlit Components](https://docs.streamlit.io/library/components/custom-components)

---

## Contributing

To extend the Papaya wrapper:

1. Modify `papaya_wrapper.py`
2. Update tests in `test_papaya_wrapper.py`
3. Run tests: `pytest test_papaya_wrapper.py -v`
4. Update this guide if adding new features

---

## License

MIT License - See project LICENSE file

**Author:** NeuConn Development Team

