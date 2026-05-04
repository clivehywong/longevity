# Skill: Papaya Viewer Integration

Build interactive brain map visualizations in Streamlit with Papaya.js for NIfTI files and atlas overlays.

## Introduction

**Papaya.js** is a pure JavaScript NIfTI viewer that runs entirely in the browser without server-side processing. It's ideal for:

- **Interactive exploration** of volumetric neuroimaging data (fMRI, structural MRI)
- **Multi-atlas visualization** with transparency controls and cross-hair coordinate display
- **Real-time atlas switching** and thresholding without recomputing
- **Web-based sharing** of brain maps without requiring specialized software

When to use Papaya vs static maps:
- Use Papaya for **interactive**, exploratory visualizations (QC dashboards, atlas exploration)
- Use static plots (matplotlib, plotly) for **publication figures** (more control, consistent styling)
- Papaya excels for **clinician-friendly interfaces** and **atlas comparison tools**

---

## ⚠️ Critical API Gotchas (Lessons from Production)

These are hard-won lessons from production use. Violating any of these causes **silent failures**.

### 1. Use `encodedImages` — the ONLY reliable loading method over SSH tunnels

Papaya's default URL loading (`params["images"]`) requires browser HTTP requests. Over SSH tunnels `127.0.0.1` on the server ≠ `127.0.0.1` in the browser, so any local file server is unreachable (`ERR_CONNECTION_RESET`). The only solution is to embed base64 NIfTI data directly in the HTML:

```javascript
// Declare base64 data as JS variables — raw base64 only, NO data URI prefix
var mni_bg = "H4sI...==";
var alff_ov = "H4sI...==";

var params = [];
// encodedImages: array of JS variable NAME strings (not the data values)
params["encodedImages"] = ["mni_bg", "alff_ov"];
// Per-image options keyed by the same variable names
params["mni_bg"]  = { lut: "Grayscale" };
params["alff_ov"] = { lut: "Overlay (Positives)", alpha: 0.7, minPercent: 0.2, maxPercent: 1.0 };
```

In Python (papaya_wrapper.py):
```python
import base64

with open(nifti_path, "rb") as fh:
    b64 = base64.b64encode(fh.read()).decode("ascii")  # no prefix!
```

### 2. NEVER set `params["images"]` when using `encodedImages`

Papaya's `loadNextImage` checks `params.images` **first**. If it exists (even as `[]`), `params.encodedImages` is **never reached** — silent failure, black viewer.

```javascript
// ❌ WRONG — params.images silently swallows all other loading methods
params["images"] = [];
params["encodedImages"] = ["mni_bg"];  // ignored!

// ✅ CORRECT — only one mechanism, never both
params["encodedImages"] = ["mni_bg"];
```

### 3. `minPercent`/`maxPercent` are FRACTIONS (0–1), NOT percentages

Papaya computes display range as:
```javascript
screenMin = imageMax * minPercent;   // expects 0.0–1.0
screenMax = imageMax * maxPercent;
```

Passing `maxPercent: 100` inflates `screenMax` by 100×, squashing the entire colormap to the bottom 1% — everything appears as the minimum LUT color regardless of slider position.

```javascript
// ❌ WRONG — passing percent integers
params["alff_ov"] = { minPercent: 20, maxPercent: 100 };  // screenMax = imageMax * 100!

// ✅ CORRECT — pass fractions
params["alff_ov"] = { minPercent: 0.2, maxPercent: 1.0 };
```

In Python, convert actual threshold values to fractions before passing to Papaya:
```python
"minPercent": threshold_min_value / image_max,   # actual value ÷ imageMax → fraction
"maxPercent": threshold_max_value / image_max,
```

### 4. Do NOT call `addViewer()` explicitly

Papaya auto-initializes from a `.papaya` div with `data-params="params"`. Calling `addViewer()` creates a duplicate blank viewer.

```html
<!-- ✅ CORRECT: div attribute triggers auto-init -->
<div class="papaya" data-params="params"></div>
<script>
  var params = [];
  params["encodedImages"] = ["nii_0"];
  // No addViewer() needed!
</script>
```

### 5. Bidirectional maps (z-scores, t-stats): load the file twice with complementary LUTs

`"Overlay (Positives)"` is transparent for negative values; `"Overlay (Negatives)"` is transparent for positive values. Load the **same file twice** with both LUTs to show the full range:

```javascript
var stat_pos = "H4sI...==";  // same base64 data
var stat_neg = "H4sI...==";  // duplicated as a separate JS variable

var params = [];
params["encodedImages"] = ["stat_pos", "stat_neg"];
params["stat_pos"] = { lut: "Overlay (Positives)", minPercent: 0.17, maxPercent: 1.0 };
params["stat_neg"] = { lut: "Overlay (Negatives)", minPercent: 0.17, maxPercent: 1.0 };
```

In Python with `papaya_wrapper.py` for bidirectional mode, pass the same overlay path twice and use `overlay_colormaps=["Overlay (Positives)", "Overlay (Negatives)"]`:
- Positive threshold: `minPercent = pos_threshold / imageMax`
- Negative threshold: `minPercent = abs(neg_threshold) / abs(imageMin)`

---

## Setup & Installation

### CDN vs Local Setup

**CDN (Recommended for Streamlit)** — No build step, works immediately:
```html
<!-- Papaya JS library -->
<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
<!-- Papaya CSS -->
<link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
```

**Local Setup** — Download Papaya release from [GitHub](https://github.com/rii-mango/Papaya):
```bash
# In neuconn_app/static/
wget https://github.com/rii-mango/Papaya/releases/download/v1.4.13/papaya.js
wget https://github.com/rii-mango/Papaya/releases/download/v1.4.13/papaya.css
```

Then reference in HTML:
```html
<script src="static/papaya.js"></script>
<link rel="stylesheet" href="static/papaya.css">
```

### JavaScript Dependencies

Papaya requires minimal dependencies; it's self-contained. Optional:
- **nifti.js** (already bundled in Papaya) for NIfTI parsing
- **JSZip** (bundled) for compressed `.nii.gz` files

### Browser Compatibility

Papaya supports modern browsers (Chrome, Firefox, Safari, Edge). Requires:
- ES5+ JavaScript support
- WebGL for 3D rendering (optional; 2D viewer works without)
- Local file access for file:// URLs (use CORS proxy for remote files)

---

## Basic Usage

### Loading NIfTI Files

#### 1. From Local Path (Streamlit File Upload)
```python
# neuconn_app/pages_general_qc/interactive_viewer.py
import streamlit as st
import base64

uploaded_file = st.file_uploader("Upload NIfTI file", type=["nii", "nii.gz"])

if uploaded_file:
    # Convert to base64 for embedding in HTML
    file_bytes = uploaded_file.read()
    b64_nifti = base64.b64encode(file_bytes).decode()
    
    # Pass to Papaya viewer
    papaya_html = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papaya-container" style="width: 100%; height: 600px;">
        <div id="papayaViewer" class="papaya" data-nifti="data:application/octet-stream;base64,{b64_nifti}"></div>
    </div>
    
    <script>
        var params = [[ "data:application/octet-stream;base64,{b64_nifti}" ]];
        papaya.Container.addViewer("papayaViewer", params);
    </script>
    """
    st.components.v1.html(papaya_html, height=650)
```

#### 2. From Remote URL
```javascript
// Load directly from server URL
var params = [[
    "https://example.com/path/to/image.nii.gz"
]];
papaya.Container.addViewer("papayaViewer", params);
```

#### 3. From ArrayBuffer (Advanced)
```python
# Convert numpy array to NIfTI ArrayBuffer in Streamlit
import nibabel as nib
import numpy as np
import base64

# Create or load NIfTI
data = np.random.randn(64, 64, 64)
nifti_img = nib.Nifti1Image(data, affine=np.eye(4))

# Save to bytes and base64 encode
nib.save(nifti_img, "/tmp/temp.nii.gz")
with open("/tmp/temp.nii.gz", "rb") as f:
    b64_data = base64.b64encode(f.read()).decode()
```

### Setting Up Viewer Container

Minimal HTML structure:
```html
<!-- Container div with unique ID -->
<div id="papayaViewer" class="papaya" style="width: 100%; height: 600px;"></div>

<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
<script>
    var params = [[
        "https://example.com/brain.nii.gz"  // Primary image
    ]];
    
    var viewer = papaya.Container.addViewer("papayaViewer", params);
    // viewer is now accessible for configuration
</script>
```

### Basic Configuration Options

```javascript
var params = {
    // Viewer settings
    viewer: {
        kioskMode: false,              // Hide controls
        expandable: true,               // Allow fullscreen
        orthancURL: undefined,          // Orthanc server (if used)
        showControls: true,             // Show UI controls
        allowScroll: true,              // Mouse scroll zoom
        alpha: 1.0,                     // Overall transparency
    },
    // Image settings
    images: ["image.nii.gz"],           // Primary image(s)
    overlays: [],                       // Overlay images
    // Display options
    defaultLayout: "horizontal",        // orthogonal layout
    colormaps: ["grayscale"],           // Colormap selection
    intensityMin: 0,                    // Display range minimum
    intensityMax: 100                   // Display range maximum
};

var viewer = papaya.Container.addViewer("papayaViewer", params);
```

---

## Atlas Overlays

### Adding Talairach Atlas

Talairach is a probabilistic atlas suited for group-level coordinate reporting. Load as overlay:

```python
# neuconn_app/pages_atlas/talairach_viewer.py
import streamlit as st

html_talairach = """
<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
<link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">

<div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>

<script>
    var params = [[
        "https://www.nitrc.org/frs/download.php/12287/Talairach_T1_512x512x512.nii.gz",  // Primary
        "https://www.nitrc.org/frs/download.php/12286/Talairach_Labels_512x512x512.nii.gz" // Overlay
    ]];
    
    papaya.Container.addViewer("papayaViewer", params);
</script>
"""

st.components.v1.html(html_talairach, height=750)
```

### Adding AAL Atlas

AAL (Automated Anatomical Labeling) provides 116 brain regions. Recommended for seed-based connectivity:

```python
# neuconn_app/pages_atlas/aal_viewer.py
import streamlit as st
import os

# Path to AAL atlas in project (assume stored in atlases/)
aal_path = "/home/clivewong/proj/longevity/atlases/AAL_1mm_MNI152.nii.gz"

# Convert to base64 for embedding
import base64
with open(aal_path, "rb") as f:
    aal_b64 = base64.b64encode(f.read()).decode()

html_aal = f"""
<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
<link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">

<div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>

<script>
    // Standard MNI template as primary
    var mniTemplate = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz";
    
    var params = [[
        mniTemplate,
        "data:application/octet-stream;base64,{aal_b64}"  // AAL overlay
    ]];
    
    var viewer = papaya.Container.addViewer("papayaViewer", params);
</script>
"""

st.components.v1.html(html_aal, height=750)
```

### Adding Custom Atlases (DiFuMo 256)

DiFuMo (Dictionaries of Functional Modes) provides data-driven parcellations. Load from project atlases/:

```python
# neuconn_app/pages_atlas/difumo_viewer.py
import streamlit as st
import base64
from pathlib import Path

# Path to DiFuMo 256 in project
difumo_path = Path("/home/clivewong/proj/longevity/atlases/DiFuMo_256_MNI152_2mm.nii.gz")

if difumo_path.exists():
    with open(difumo_path, "rb") as f:
        difumo_b64 = base64.b64encode(f.read()).decode()
    
    html_difumo = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>
    
    <script>
        var mniTemplate = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz";
        
        var params = [[
            mniTemplate,
            "data:application/octet-stream;base64,{difumo_b64}"  // DiFuMo overlay
        ]];
        
        var viewer = papaya.Container.addViewer("papayaViewer", params);
    </script>
    """
    
    st.components.v1.html(html_difumo, height=750)
else:
    st.error(f"DiFuMo atlas not found: {difumo_path}")
```

### Alpha/Transparency Controls

Control overlay transparency with interactive Streamlit slider:

```python
# neuconn_app/pages_atlas/atlas_transparency.py
import streamlit as st
import base64

# Load atlas
atlas_path = "/home/clivewong/proj/longevity/atlases/DiFuMo_256_MNI152_2mm.nii.gz"
with open(atlas_path, "rb") as f:
    atlas_b64 = base64.b64encode(f.read()).decode()

# Streamlit slider for transparency
alpha = st.slider("Atlas Transparency", 0.0, 1.0, 0.5, step=0.1)

html_viewer = f"""
<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
<link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">

<div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>

<script>
    var mniTemplate = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz";
    
    var params = [[
        mniTemplate,
        "data:application/octet-stream;base64,{atlas_b64}"
    ]];
    
    var viewer = papaya.Container.addViewer("papayaViewer", params);
    
    // Set overlay alpha after loading
    setTimeout(function() {{
        if (viewer && viewer.viewer && viewer.viewer.screenVolumes.length > 1) {{
            var overlay = viewer.viewer.screenVolumes[1];
            overlay.alpha = {alpha};
        }}
    }}, 500);  // Wait for viewer to initialize
</script>
"""

st.components.v1.html(html_viewer, height=750)
```

### Colormap Selection

Apply different colormaps to overlays:

```javascript
// Available colormaps: "grayscale", "hotmetal", "spectrum", "red", "green", "blue", "jet", "actc"
var viewer = papaya.Container.addViewer("papayaViewer", params);

// Change colormap for second image (overlay)
setTimeout(function() {
    if (viewer.viewer.screenVolumes.length > 1) {
        viewer.viewer.screenVolumes[1].colorMap = "spectrum";  // Spectrum colormap
        viewer.viewer.drawViewer(true);
    }
}, 500);
```

---

## Interactive Controls

### Threshold Slider Implementation

Add a Streamlit-integrated threshold slider for dynamic atlas visualization:

```python
# neuconn_app/pages_atlas/interactive_threshold.py
import streamlit as st
import base64
import json

st.title("Interactive Atlas Threshold")

# Threshold control
threshold = st.slider("Voxel Threshold (%)", 0, 100, 50)

# Load atlas
atlas_path = "/home/clivewong/proj/longevity/atlases/DiFuMo_256_MNI152_2mm.nii.gz"
with open(atlas_path, "rb") as f:
    atlas_b64 = base64.b64encode(f.read()).decode()

html_threshold = f"""
<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
<link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">

<div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>

<div id="coordinateDisplay" style="position: absolute; top: 10px; right: 10px; 
    background: rgba(0,0,0,0.7); color: white; padding: 10px; border-radius: 5px;">
    Coordinates: (0, 0, 0)
</div>

<script>
    var mniTemplate = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz";
    
    var params = [[
        mniTemplate,
        "data:application/octet-stream;base64,{atlas_b64}"
    ]];
    
    var viewer = papaya.Container.addViewer("papayaViewer", params);
    
    // Set threshold after loading
    setTimeout(function() {{
        if (viewer.viewer.screenVolumes.length > 1) {{
            var overlay = viewer.viewer.screenVolumes[1];
            overlay.intensityMin = {threshold};
            viewer.viewer.drawViewer(true);
        }}
    }}, 500);
</script>
"""

st.components.v1.html(html_threshold, height=750)
```

### Coordinate Display

Show current cursor coordinates in real-time:

```python
# Embedded in Papaya HTML with JavaScript coordinate tracking
html_coords = """
<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
<link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">

<div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>

<div id="coordBox" style="position: fixed; top: 10px; right: 10px; 
    background: rgba(0,0,0,0.7); color: #0f0; padding: 10px; font-family: monospace; 
    border-radius: 5px; z-index: 1000;">
    MNI: (0.0, 0.0, 0.0) mm
</div>

<script>
    var params = [["https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz"]];
    var viewer = papaya.Container.addViewer("papayaViewer", params);
    
    // Update coordinates on mouse move
    document.addEventListener("mousemove", function(event) {
        if (viewer.viewer) {
            var coords = viewer.viewer.currentCoord;
            if (coords) {
                document.getElementById("coordBox").innerHTML = 
                    "MNI: (" + coords[0].toFixed(1) + ", " + 
                    coords[1].toFixed(1) + ", " + 
                    coords[2].toFixed(1) + ") mm";
            }
        }
    });
</script>
"""
```

### Multi-Atlas Switching

Tab-based interface for comparing multiple atlases:

```python
# neuconn_app/pages_atlas/multi_atlas_compare.py
import streamlit as st
import base64

st.title("Multi-Atlas Comparison")

# Tabs for different atlases
tab_aal, tab_difumo, tab_talairach = st.tabs(["AAL", "DiFuMo 256", "Talairach"])

# Load atlases
atlas_files = {
    "aal": "/home/clivewong/proj/longevity/atlases/AAL_1mm_MNI152.nii.gz",
    "difumo": "/home/clivewong/proj/longevity/atlases/DiFuMo_256_MNI152_2mm.nii.gz",
}

def load_atlas_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

with tab_aal:
    aal_b64 = load_atlas_b64(atlas_files["aal"])
    html_aal = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    <div id="aal" class="papaya" style="width: 100%; height: 600px;"></div>
    <script>
        papaya.Container.addViewer("aal", [[
            "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz",
            "data:application/octet-stream;base64,{aal_b64}"
        ]]);
    </script>
    """
    st.components.v1.html(html_aal, height=650)

with tab_difumo:
    difumo_b64 = load_atlas_b64(atlas_files["difumo"])
    html_difumo = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    <div id="difumo" class="papaya" style="width: 100%; height: 600px;"></div>
    <script>
        papaya.Container.addViewer("difumo", [[
            "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz",
            "data:application/octet-stream;base64,{difumo_b64}"
        ]]);
    </script>
    """
    st.components.v1.html(html_difumo, height=650)

with tab_talairach:
    html_talairach = """
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    <div id="talairach" class="papaya" style="width: 100%; height: 600px;"></div>
    <script>
        papaya.Container.addViewer("talairach", [[
            "https://www.nitrc.org/frs/download.php/12287/Talairach_T1_512x512x512.nii.gz",
            "https://www.nitrc.org/frs/download.php/12286/Talairach_Labels_512x512x512.nii.gz"
        ]]);
    </script>
    """
    st.components.v1.html(html_talairach, height=650)
```

### Exporting Views as Images

Capture viewer canvas and download as PNG:

```python
# neuconn_app/utils/papaya_export.py
import streamlit as st
import base64

def export_papaya_view():
    """Export Papaya viewer canvas as image."""
    
    html_export = """
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papayaViewer" class="papaya" style="width: 100%; height: 600px;"></div>
    
    <button id="exportBtn" style="margin-top: 10px; padding: 10px 20px; cursor: pointer;">
        Export as PNG
    </button>
    
    <script>
        var params = [["https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz"]];
        var viewer = papaya.Container.addViewer("papayaViewer", params);
        
        document.getElementById("exportBtn").addEventListener("click", function() {
            var canvas = viewer.viewer.canvas;
            if (canvas) {
                var link = document.createElement("a");
                link.href = canvas.toDataURL("image/png");
                link.download = "brain_view_" + new Date().getTime() + ".png";
                link.click();
            }
        });
    </script>
    """
    
    return html_export

# Usage in Streamlit
st.components.v1.html(export_papaya_view(), height=650)
```

---

## Streamlit Integration

### Using st.components.v1.html()

Embed Papaya directly in Streamlit layout with automatic reruns handling:

```python
# neuconn_app/pages_general_qc/viewer_basic.py
import streamlit as st
import base64

st.set_page_config(layout="wide")
st.title("Brain Viewer")

# File uploader
uploaded_file = st.file_uploader("Upload NIfTI", type=["nii", "nii.gz"])

if uploaded_file:
    file_bytes = uploaded_file.read()
    b64_data = base64.b64encode(file_bytes).decode()
    
    html = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>
    
    <script>
        papaya.Container.addViewer("papayaViewer", [[
            "data:application/octet-stream;base64,{b64_data}"
        ]]);
    </script>
    """
    
    st.components.v1.html(html, height=750)
else:
    st.info("Upload a NIfTI file to begin")
```

### State Management Across Reruns

Use `st.session_state` to preserve viewer state and configuration:

```python
# neuconn_app/pages_general_qc/stateful_viewer.py
import streamlit as st
import base64

# Initialize session state
if "viewer_alpha" not in st.session_state:
    st.session_state.viewer_alpha = 0.5
if "viewer_threshold" not in st.session_state:
    st.session_state.viewer_threshold = 50
if "current_atlas" not in st.session_state:
    st.session_state.current_atlas = "difumo"

st.title("Persistent Viewer State")

# Control sidebar
with st.sidebar:
    st.session_state.viewer_alpha = st.slider("Alpha", 0.0, 1.0, st.session_state.viewer_alpha)
    st.session_state.viewer_threshold = st.slider("Threshold", 0, 100, st.session_state.viewer_threshold)
    st.session_state.current_atlas = st.selectbox("Atlas", 
        ["aal", "difumo", "talairach"], 
        index=["aal", "difumo", "talairach"].index(st.session_state.current_atlas))

# Load selected atlas
atlas_paths = {
    "aal": "/home/clivewong/proj/longevity/atlases/AAL_1mm_MNI152.nii.gz",
    "difumo": "/home/clivewong/proj/longevity/atlases/DiFuMo_256_MNI152_2mm.nii.gz",
}

atlas_path = atlas_paths.get(st.session_state.current_atlas)
if atlas_path:
    with open(atlas_path, "rb") as f:
        atlas_b64 = base64.b64encode(f.read()).decode()

    html = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>
    
    <script>
        var mniTemplate = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz";
        var params = [[mniTemplate, "data:application/octet-stream;base64,{atlas_b64}"]];
        
        var viewer = papaya.Container.addViewer("papayaViewer", params);
        
        setTimeout(function() {{
            if (viewer.viewer.screenVolumes.length > 1) {{
                viewer.viewer.screenVolumes[1].alpha = {st.session_state.viewer_alpha};
                viewer.viewer.screenVolumes[1].intensityMin = {st.session_state.viewer_threshold};
                viewer.viewer.drawViewer(true);
            }}
        }}, 500);
    </script>
    """
    
    st.components.v1.html(html, height=750)
```

### Passing Data from Python to JavaScript

Serialize Python objects to JSON and pass to JavaScript:

```python
# neuconn_app/utils/papaya_config.py
import json
import streamlit as st

def create_papaya_config(nifti_path, atlas_path, seed_coords=None, threshold=50):
    """Create Papaya configuration from Python objects."""
    
    config = {
        "images": [nifti_path],
        "overlays": [atlas_path],
        "intensityMin": threshold,
        "intensityMax": 100,
        "alpha": 0.6,
    }
    
    if seed_coords:
        config["seedCoordinates"] = seed_coords  # [x, y, z] in MNI space
    
    return config

def render_papaya_with_config(config, height=700):
    """Render Papaya viewer with Python config."""
    
    config_json = json.dumps(config)
    
    html = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papayaViewer" class="papaya" style="width: 100%; height: {height}px;"></div>
    
    <script>
        var config = {config_json};
        var viewer = papaya.Container.addViewer("papayaViewer", [config.images]);
        
        // Store config on window for later reference
        window.papayaConfig = config;
    </script>
    """
    
    st.components.v1.html(html, height=height + 50)

# Usage
config = create_papaya_config(
    "mni_template.nii.gz",
    "aal_atlas.nii.gz",
    seed_coords=[0, 0, 0],
    threshold=30
)
render_papaya_with_config(config)
```

---

## Code Examples

### Single NIfTI Viewer

Minimal viewer for exploring a single NIfTI file:

```python
# neuconn_app/pages_fmri/single_nifti_viewer.py
import streamlit as st
import base64

st.set_page_config(layout="wide")
st.title("Single NIfTI Viewer")

# Sidebar for file selection
nifti_file = st.sidebar.file_uploader("Select NIfTI file", type=["nii", "nii.gz"])

if nifti_file:
    # Convert to base64
    file_bytes = nifti_file.read()
    b64_nifti = base64.b64encode(file_bytes).decode()
    
    # Viewer parameters
    col1, col2 = st.columns([3, 1])
    with col2:
        intensity_min = st.slider("Intensity Min", 0, 100, 0)
        intensity_max = st.slider("Intensity Max", 0, 100, 100)
    
    # HTML viewer
    html = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>
    
    <script>
        var params = {{"images": ["data:application/octet-stream;base64,{b64_nifti}"], 
                      "intensityMin": {intensity_min},
                      "intensityMax": {intensity_max}}};
        papaya.Container.addViewer("papayaViewer", [params.images]);
    </script>
    """
    
    with col1:
        st.components.v1.html(html, height=750)
else:
    st.info("Upload a NIfTI file to explore")
```

### NIfTI with Atlas Overlay

Viewer combining subject data with atlas registration:

```python
# neuconn_app/pages_fmri/atlas_overlay_viewer.py
import streamlit as st
import base64
from pathlib import Path

st.set_page_config(layout="wide")
st.title("Atlas Overlay Viewer")

# Load subject NIfTI
subject_nifti = st.file_uploader("Upload subject NIfTI", type=["nii", "nii.gz"])

# Select atlas
atlas_choice = st.selectbox("Choose Atlas", ["AAL", "DiFuMo 256"])

# Atlas mapping
atlases = {
    "AAL": "/home/clivewong/proj/longevity/atlases/AAL_1mm_MNI152.nii.gz",
    "DiFuMo 256": "/home/clivewong/proj/longevity/atlases/DiFuMo_256_MNI152_2mm.nii.gz",
}

atlas_path = atlases[atlas_choice]

if subject_nifti and Path(atlas_path).exists():
    # Convert to base64
    subject_b64 = base64.b64encode(subject_nifti.read()).decode()
    with open(atlas_path, "rb") as f:
        atlas_b64 = base64.b64encode(f.read()).decode()
    
    # Controls
    col1, col2 = st.columns(2)
    with col1:
        atlas_alpha = st.slider("Atlas Transparency", 0.0, 1.0, 0.6)
    with col2:
        atlas_threshold = st.slider("Atlas Threshold (%)", 0, 100, 50)
    
    html = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>
    
    <script>
        var params = [[
            "data:application/octet-stream;base64,{subject_b64}",
            "data:application/octet-stream;base64,{atlas_b64}"
        ]];
        
        var viewer = papaya.Container.addViewer("papayaViewer", params);
        
        setTimeout(function() {{
            if (viewer.viewer && viewer.viewer.screenVolumes.length > 1) {{
                viewer.viewer.screenVolumes[1].alpha = {atlas_alpha};
                viewer.viewer.screenVolumes[1].intensityMin = {atlas_threshold};
                viewer.viewer.drawViewer(true);
            }}
        }}, 500);
    </script>
    """
    
    st.components.v1.html(html, height=750)
else:
    st.error("Atlas file not found or subject NIfTI not uploaded")
```

### Interactive Multi-Atlas Comparison

Side-by-side comparison with synchronized crosshairs:

```python
# neuconn_app/pages_atlas/multi_atlas_compare_advanced.py
import streamlit as st
import base64
from pathlib import Path

st.set_page_config(layout="wide")
st.title("Multi-Atlas Comparison (Synchronized)")

# Template
mni_template = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz"

# Load atlases
atlases = {
    "AAL": "/home/clivewong/proj/longevity/atlases/AAL_1mm_MNI152.nii.gz",
    "DiFuMo 256": "/home/clivewong/proj/longevity/atlases/DiFuMo_256_MNI152_2mm.nii.gz",
}

# Display side-by-side
col1, col2 = st.columns(2)

with col1:
    st.subheader("AAL Atlas")
    with open(atlases["AAL"], "rb") as f:
        aal_b64 = base64.b64encode(f.read()).decode()
    
    html_aal = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    <div id="aal" class="papaya" style="width: 100%; height: 600px;"></div>
    <script>
        papaya.Container.addViewer("aal", [[
            "{mni_template}",
            "data:application/octet-stream;base64,{aal_b64}"
        ]]);
    </script>
    """
    st.components.v1.html(html_aal, height=650)

with col2:
    st.subheader("DiFuMo 256 Atlas")
    with open(atlases["DiFuMo 256"], "rb") as f:
        difumo_b64 = base64.b64encode(f.read()).decode()
    
    html_difumo = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    <div id="difumo" class="papaya" style="width: 100%; height: 600px;"></div>
    <script>
        papaya.Container.addViewer("difumo", [[
            "{mni_template}",
            "data:application/octet-stream;base64,{difumo_b64}"
        ]]);
    </script>
    """
    st.components.v1.html(html_difumo, height=650)
```

### Export to Canvas/Image

Capture and download viewer snapshots:

```python
# neuconn_app/pages_general_qc/export_viewer_image.py
import streamlit as st
import base64

st.title("Viewer Export")

# File upload
uploaded_nifti = st.file_uploader("Upload NIfTI", type=["nii", "nii.gz"])

if uploaded_nifti:
    nifti_b64 = base64.b64encode(uploaded_nifti.read()).decode()
    
    html_export = f"""
    <script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
    <link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">
    
    <div id="papayaViewer" class="papaya" style="width: 100%; height: 600px;"></div>
    
    <div style="margin-top: 10px;">
        <button id="captureBtn" style="padding: 10px 20px; background-color: #4CAF50; 
            color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px;">
            📸 Capture Screenshot
        </button>
        <a id="downloadLink" style="margin-left: 10px; padding: 10px 20px; 
            background-color: #2196F3; color: white; border-radius: 4px; text-decoration: none;">
            Download
        </a>
    </div>
    
    <script>
        var viewer = papaya.Container.addViewer("papayaViewer", [[
            "data:application/octet-stream;base64,{nifti_b64}"
        ]]);
        
        document.getElementById("captureBtn").addEventListener("click", function() {{
            var canvas = viewer.viewer.canvas;
            var imageData = canvas.toDataURL("image/png");
            document.getElementById("downloadLink").href = imageData;
            document.getElementById("downloadLink").download = 
                "brain_" + new Date().getTime() + ".png";
            document.getElementById("downloadLink").click();
        }});
    </script>
    """
    
    st.components.v1.html(html_export, height=700)
```

---

## Performance Tips

### Handling Large Files

Compress NIfTI files before embedding to reduce data transfer:

```python
# neuconn_app/utils/papaya_performance.py
import nibabel as nib
import gzip
import shutil
import base64

def compress_nifti(nifti_path, output_path=None):
    """Compress NIfTI to .nii.gz if not already compressed."""
    if nifti_path.endswith(".nii.gz"):
        return nifti_path
    
    if output_path is None:
        output_path = nifti_path.replace(".nii", ".nii.gz")
    
    with open(nifti_path, "rb") as f_in:
        with gzip.open(output_path, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    
    return output_path

def load_nifti_as_b64(nifti_path, compress=True):
    """Load NIfTI and return base64-encoded bytes."""
    if compress and not nifti_path.endswith(".nii.gz"):
        nifti_path = compress_nifti(nifti_path)
    
    with open(nifti_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

# Usage
nifti_b64 = load_nifti_as_b64("large_file.nii")
```

For **very large datasets** (>100MB), use remote URL loading instead of base64 embedding:

```python
# Store atlas files on server, reference by URL
mni_template = "https://server.example.com/MNI152_T1_1mm_brain.nii.gz"
aal_atlas = "https://server.example.com/AAL_1mm_MNI152.nii.gz"

# Reference in Papaya instead of embedding
params = [[mni_template, aal_atlas]]
```

### Caching Strategies

Cache loaded atlases in `st.cache_resource` to avoid re-loading on every rerun:

```python
# neuconn_app/utils/papaya_cache.py
import streamlit as st
import base64

@st.cache_resource
def load_atlas_cached(atlas_path):
    """Load and cache atlas as base64."""
    with open(atlas_path, "rb") as f:
        return base64.b64encode(f.read()).decode()

@st.cache_resource
def load_template_cached():
    """Cache MNI template (download if needed)."""
    import requests
    template_url = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz"
    response = requests.get(template_url)
    return base64.b64encode(response.content).decode()

# Usage
aal_b64 = load_atlas_cached("/home/clivewong/proj/longevity/atlases/AAL_1mm_MNI152.nii.gz")
template_b64 = load_template_cached()  # Only fetched once per session

html = f"""
<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>
<div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>
<script>
    papaya.Container.addViewer("papayaViewer", [[
        "data:application/octet-stream;base64,{template_b64}",
        "data:application/octet-stream;base64,{aal_b64}"
    ]]);
</script>
"""
st.components.v1.html(html, height=750)
```

### Lazy Loading Atlases

Load atlases on-demand instead of at app startup:

```python
# neuconn_app/pages_atlas/lazy_load_atlases.py
import streamlit as st
import base64

st.title("Lazy-Loaded Atlas Explorer")

# Sidebar toggle to select atlas
show_atlas = st.sidebar.checkbox("Show Atlas Overlay")
atlas_choice = st.sidebar.selectbox("Atlas", ["AAL", "DiFuMo 256"]) if show_atlas else None

atlases = {
    "AAL": "/home/clivewong/proj/longevity/atlases/AAL_1mm_MNI152.nii.gz",
    "DiFuMo 256": "/home/clivewong/proj/longevity/atlases/DiFuMo_256_MNI152_2mm.nii.gz",
}

html_parts = [
    '<script src="https://papaya.readthedocs.io/viewer/papaya.js"></script>',
    '<link rel="stylesheet" href="https://papaya.readthedocs.io/viewer/papaya.css">',
    '<div id="papayaViewer" class="papaya" style="width: 100%; height: 700px;"></div>',
    '<script>',
]

template = "https://www.nitrc.org/frs/download.php/11342/MNI152_T1_1mm_brain.nii.gz"

if show_atlas and atlas_choice:
    # Load atlas only if user checked the box
    atlas_path = atlases[atlas_choice]
    with open(atlas_path, "rb") as f:
        atlas_b64 = base64.b64encode(f.read()).decode()
    
    html_parts.append(f"""
    var params = [["{template}", "data:application/octet-stream;base64,{atlas_b64}"]];
    """)
else:
    html_parts.append(f"""
    var params = [["{template}"]];
    """)

html_parts.extend([
    'papaya.Container.addViewer("papayaViewer", params);',
    '</script>'
])

html = '\n'.join(html_parts)
st.components.v1.html(html, height=750)
```

---

## References

- **Papaya.js GitHub**: https://github.com/rii-mango/Papaya
- **Papaya Documentation**: https://papaya.readthedocs.io/
- **Papaya API**: https://papaya.readthedocs.io/viewer/lib-papaya.html
- **NITRC Atlas Repository**: https://www.nitrc.org/
- **NIfTI Format**: https://nifti.nimh.nih.gov/

---

**Last Updated**: 2025  
**Applicable to**: Streamlit >=1.28, modern browsers (Chrome, Firefox, Safari, Edge)
