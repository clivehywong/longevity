# Correlation Matrix Visualization - User Guide

This document explains how to use the correlation matrix visualization component in the NeuConn Streamlit app.

## Overview

The correlation matrix visualization component provides interactive, publication-ready visualizations for functional connectivity data. It combines:

1. **Interactive Heatmap** - View correlation strength between all ROI pairs
2. **Network Graph** - Visualize network topology with nodes and edges
3. **Interactive Controls** - Fine-tune visualization parameters in real-time

## Features

### 1. Heatmap Visualization

**What it shows:**
- Square matrix of correlation values (N×N)
- Diagonal always 1.0 (self-correlation)
- Color intensity indicates correlation strength

**Interactions:**
- **Hover**: Display exact correlation value
- **Zoom**: Scroll to zoom in/out
- **Pan**: Click and drag to move around
- **Export**: Download as PNG, SVG, or HTML

**Controls:**

| Control | Options | Description |
|---------|---------|-------------|
| **Threshold** | 0.0 - 1.0 | Hide correlations with \|r\| < threshold (shown in gray) |
| **Colormap** | RdBu, coolwarm, viridis, icefire | Color scheme (diverging or sequential) |
| **Sorting** | None, Hierarchical, By Mean Connectivity | Reorder rows/columns to group similar ROIs |
| **Auto-scale** | On/Off | Scale colors to data range (on) or full [-1,1] range (off) |

### 2. Network Graph Visualization

**What it shows:**
- Nodes represent individual ROIs
- Edges represent significant correlations above threshold
- Edge width: correlation strength
- Edge color: correlation sign (red=positive, blue=negative)

**Layout Algorithms:**

| Layout | Best For |
|--------|----------|
| **Spring** | General visualization, good clustering |
| **Circular** | Comparing symmetric patterns |
| **Kamada-Kawai** | Dense networks, visual clarity |

**Controls:**

| Control | Options | Description |
|---------|---------|-------------|
| **Threshold** | 0.0 - 1.0 | Only show edges with \|r\| > threshold |
| **Layout** | spring, circular, kamada_kawai | Graph layout algorithm |
| **Node Labels** | On/Off | Show ROI names on nodes |

### 3. Statistics Panel

Quick summary statistics:

- **Connections Above Threshold**: Count of edge pairs
- **Mean Correlation**: Average off-diagonal correlation
- **Max Correlation**: Strongest correlation value

## Data Format

### Supported Input Formats

#### TSV (Tab-Separated Values)
```
Node       ROI_1    ROI_2    ROI_3
ROI_1      1.0      0.45     0.23
ROI_2      0.45     1.0      0.67
ROI_3      0.23     0.67     1.0
```

#### CSV (Comma-Separated Values)
```
Node,ROI_1,ROI_2,ROI_3
ROI_1,1.0,0.45,0.23
ROI_2,0.45,1.0,0.67
ROI_3,0.23,0.67,1.0
```

#### NumPy Array (in Python code)
```python
import numpy as np
corr_matrix = np.array([[1.0, 0.45, 0.23],
                        [0.45, 1.0, 0.67],
                        [0.23, 0.67, 1.0]])
```

### Matrix Requirements

- **Square**: N×N dimensions
- **Symmetric**: corr_matrix[i,j] == corr_matrix[j,i]
- **Diagonal**: corr_matrix[i,i] ≈ 1.0
- **Range**: Typically [-1, 1]

## Usage Examples

### Example 1: Basic Heatmap

```python
import numpy as np
from utils.matrix_renderer import plot_correlation_heatmap

# Create sample matrix
corr_matrix = np.random.randn(10, 10)
corr_matrix = (corr_matrix + corr_matrix.T) / 2
np.fill_diagonal(corr_matrix, 1.0)

# Create heatmap
fig = plot_correlation_heatmap(
    corr_matrix,
    title="Correlation Matrix",
    colormap="RdBu",
    threshold=0.2
)
fig.show()
```

### Example 2: Network Graph

```python
from utils.matrix_renderer import plot_network_graph

# Create network visualization
fig = plot_network_graph(
    corr_matrix,
    roi_labels=[f"ROI-{i+1}" for i in range(10)],
    threshold=0.3,
    layout_type="spring"
)
fig.show()
```

### Example 3: Side-by-Side Visualization

```python
from utils.matrix_renderer import plot_network_and_heatmap_side_by_side

# Combined visualization
fig = plot_network_and_heatmap_side_by_side(
    corr_matrix,
    roi_labels=[f"ROI-{i+1}" for i in range(10)],
    threshold=0.2
)
fig.show()
```

### Example 4: Load from File and Visualize

```python
from utils.matrix_renderer import load_correlation_matrix, render_correlation_matrix_streamlit

# Load from TSV
corr_matrix, roi_labels = load_correlation_matrix("connectivity_matrix.tsv")

# Render in Streamlit
render_correlation_matrix_streamlit(
    corr_matrix,
    roi_labels=roi_labels,
    subject_id="066",
    session="01"
)
```

### Example 5: Streamlit Integration

```python
import streamlit as st
from utils.matrix_renderer import render_correlation_matrix_streamlit

st.set_page_config(layout="wide")

# Your data loading code here
corr_matrix, roi_labels = load_data()

# Render visualization
render_correlation_matrix_streamlit(
    corr_matrix,
    roi_labels=roi_labels,
    analysis_type="network_connectivity",
    subject_id="066",
    session="01"
)
```

## Color Schemes

### Diverging Colormaps (Recommended for signed data)

- **RdBu**: Red-Blue diverging (default, best for correlation)
- **coolwarm**: Cool-Warm diverging

### Sequential Colormaps (Better for absolute values)

- **viridis**: Purple-Yellow sequential
- **icefire**: Blue-Red sequential (perceptually uniform)

**Tip:** Use diverging colormaps when correlations can be negative or positive. Use sequential colormaps when displaying |r| or other non-signed metrics.

## Threshold Selection Guide

| Threshold | Use Case | Graph Density |
|-----------|----------|---------------|
| 0.0 - 0.1 | Dense networks, visualization overload | Very high |
| 0.1 - 0.3 | Balanced view, recommended default | Medium-high |
| 0.3 - 0.5 | Strong connections only, simplified view | Low-medium |
| 0.5 - 1.0 | Only very strong correlations | Very low |

**Tip:** Start with threshold=0.2-0.3 for clarity. Lower thresholds reveal more structure but can be cluttered.

## Sorting Methods

### No Sorting
Raw order based on input matrix.

### Hierarchical Clustering
Groups similar ROIs together using Ward linkage. Useful for discovering community structure.

### By Mean Connectivity
Reorders by mean correlation strength. Highlights hub ROIs.

## Network Aggregation

Group ROIs into networks (e.g., 7 Yeo networks) for high-level summaries:

```python
from utils.matrix_renderer import aggregate_to_networks

# Automatically detect Yeo networks from DiFuMo labels
agg_matrix, networks = aggregate_to_networks(corr_matrix_256, roi_labels_256)
# Result: 7×7 matrix for Visual, Somatomotor, Attention, Salience, Limbic, TempPar, DMN

# Or provide custom mapping
custom_mapping = {
    "ROI_A1": "Network_A",
    "ROI_A2": "Network_A",
    "ROI_B1": "Network_B",
    "ROI_B2": "Network_B",
}
agg_matrix, networks = aggregate_to_networks(corr_matrix, roi_labels, custom_mapping)
```

## Troubleshooting

### Issue: Matrix appears all white/gray

**Cause:** Threshold too high or all correlations below threshold.

**Solution:** Lower the threshold slider or check your data range.

### Issue: Network graph has too many edges

**Cause:** Low threshold value.

**Solution:** Increase threshold to 0.3-0.5 for cleaner visualization.

### Issue: Node labels overlap in network graph

**Cause:** Too many nodes or "Show Labels" enabled.

**Solution:** 
- Uncheck "Show Labels" 
- Hover over nodes to see names
- Use smaller matrices for dense labels

### Issue: Heatmap is hard to interpret

**Cause:** Clustering not applied or unsorted data.

**Solution:** Select "Hierarchical Clustering" in sort menu.

### Issue: Export button unavailable

**Cause:** Missing kaleido dependency.

**Solution:** Install kaleido: `pip install kaleido`

## Performance Notes

| Matrix Size | Typical Time |
|------------|--------------|
| 5×5 | <0.1 sec |
| 50×50 | 0.3 sec |
| 256×256 | 1-2 sec |
| 1000×1000 | 5-10 sec |

For large matrices (>500×500):
- Use hierarchical clustering sparingly
- Reduce node labels
- Consider aggregating to network level

## Export Formats

### PNG
- Raster format
- Good for presentations, web
- Size: 800×600 default
- Quality: Optimized for screen

### SVG
- Vector format
- Scalable, publication-ready
- Best for print
- Preserves interactivity in some viewers

### HTML
- Interactive version
- Retains all zoom/pan/hover features
- Shareable, no dependencies needed
- Large file size for big matrices

## API Reference

See `neuconn_app/utils/matrix_renderer.py` for complete function documentation.

### Core Functions

```python
def plot_correlation_heatmap(
    corr_matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None,
    title: str = "Correlation Matrix",
    colormap: str = "RdBu",
    threshold: float = 0.0,
    sort_method: Optional[str] = None,
    figsize: Tuple[int, int] = (800, 800),
    auto_scale: bool = False
) -> go.Figure
```

```python
def plot_network_graph(
    corr_matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None,
    title: str = "Network Graph",
    threshold: float = 0.3,
    node_size: int = 15,
    layout_type: str = "spring",
    figsize: Tuple[int, int] = (800, 800),
    show_labels: bool = True,
    edge_width_scale: float = 5.0
) -> go.Figure
```

```python
def render_correlation_matrix_streamlit(
    corr_matrix: np.ndarray,
    roi_labels: Optional[List[str]] = None,
    analysis_type: str = "network_connectivity",
    subject_id: Optional[str] = None,
    session: Optional[str] = None
)
```

## Integration with Streamlit App Pages

Add to any page in `neuconn_app/pages/`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.matrix_renderer import render_correlation_matrix_streamlit

# In your render() function:
render_correlation_matrix_streamlit(
    corr_matrix,
    roi_labels=roi_labels,
    analysis_type="network_connectivity",
    subject_id=subject_id,
    session=session
)
```

## See Also

- **Demo Page:** `neuconn_app/pages/05_matrix_demo.py` - Try different visualization modes
- **Tests:** `neuconn_app/tests/test_matrix_renderer.py` - See usage examples
- **Source:** `neuconn_app/utils/matrix_renderer.py` - Full implementation details
