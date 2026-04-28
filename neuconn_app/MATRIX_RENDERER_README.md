# Correlation Matrix Visualization Component

Interactive, publication-ready visualization of correlation matrices for functional connectivity analysis.

## Quick Start

### Basic Usage

```python
import numpy as np
from utils.matrix_renderer import plot_correlation_heatmap

# Your correlation matrix (N×N)
corr_matrix = np.random.randn(10, 10)
corr_matrix = (corr_matrix + corr_matrix.T) / 2
np.fill_diagonal(corr_matrix, 1.0)

# Create heatmap
fig = plot_correlation_heatmap(corr_matrix, threshold=0.3)
fig.show()
```

### In Streamlit

```python
from utils.matrix_renderer import render_correlation_matrix_streamlit

# Load your data
corr_matrix, roi_labels = load_data()

# Render full interactive interface
render_correlation_matrix_streamlit(
    corr_matrix,
    roi_labels=roi_labels,
    subject_id="066",
    session="01"
)
```

## Features

- 🔥 **Interactive Heatmap** - Hover, zoom, pan with plotly
- 🕸️ **Network Graph** - Multiple layout algorithms (spring, circular, kamada_kawai)
- 🎨 **Colormap Selection** - RdBu, coolwarm, viridis, icefire
- 📊 **Threshold Filtering** - Hide weak correlations
- 📈 **Hierarchical Clustering** - Organize ROIs by similarity
- 💾 **Export** - Save as PNG, SVG, or HTML
- 🚀 **Large Matrix Support** - Handles 256×256 DiFuMo matrices
- 🔗 **Network Aggregation** - Group into 7 Yeo networks

## API

### Core Functions

| Function | Purpose |
|----------|---------|
| `plot_correlation_heatmap()` | Interactive heatmap visualization |
| `plot_network_graph()` | Network graph with customizable layouts |
| `plot_network_and_heatmap_side_by_side()` | Combined heatmap + graph view |
| `render_correlation_matrix_streamlit()` | Full Streamlit UI with controls |
| `load_correlation_matrix()` | Load TSV/CSV correlation matrices |
| `aggregate_to_networks()` | Group ROIs into network-level summary |
| `validate_correlation_matrix()` | Check matrix validity |

See `neuconn_app/docs/MATRIX_RENDERER_GUIDE.md` for full documentation.

## File Structure

```
neuconn_app/
├── utils/
│   └── matrix_renderer.py          # Core visualization component
├── tests/
│   └── test_matrix_renderer.py     # 22 unit tests (all passing)
├── pages/
│   └── 05_matrix_demo.py           # Interactive demo page
└── docs/
    └── MATRIX_RENDERER_GUIDE.md    # User guide & tutorials
```

## Testing

Run the full test suite:

```bash
cd neuconn_app
pytest tests/test_matrix_renderer.py -v
```

All 22 tests pass:
- Matrix validation (4 tests)
- File loading (2 tests)
- Hierarchical clustering (1 test)
- Heatmap generation (5 tests)
- Network graph generation (4 tests)
- Side-by-side visualization (1 test)
- Network aggregation (1 test)
- Edge cases (3 tests)
- Integration test (1 test)

## Demo

Launch the Streamlit demo page:

```bash
cd neuconn_app
streamlit run pages/05_matrix_demo.py
```

Three demo modes:
1. **Load Real Data** - From project derivatives
2. **Generate Test Data** - Custom random matrices
3. **Side-by-Side Comparison** - Heatmap + network graph

## Performance

| Matrix Size | Time |
|------------|------|
| 5×5 | <0.1 sec |
| 50×50 | 0.3 sec |
| 256×256 | 1-2 sec |

## Data Format

Accepts:
- NumPy arrays (N×N float)
- CSV files with ROI labels
- TSV files with ROI labels
- HDF5 matrices

### Requirements

- Square matrix (N×N)
- Symmetric (or directed connectivity)
- Diagonal ≈ 1.0 (or auto-handled)
- Range typically [-1, 1]

## Installation

Dependencies already in `neuconn_app/requirements.txt`:

```bash
pip install plotly networkx numpy pandas scipy
```

Optional for export:
```bash
pip install kaleido  # For PNG/SVG export
```

## Usage Examples

### Example 1: Load from TSV and visualize

```python
from utils.matrix_renderer import load_correlation_matrix, render_correlation_matrix_streamlit

corr_matrix, roi_labels = load_correlation_matrix("connectivity.tsv")
render_correlation_matrix_streamlit(corr_matrix, roi_labels=roi_labels)
```

### Example 2: Network aggregation (256 ROIs → 7 networks)

```python
from utils.matrix_renderer import aggregate_to_networks

agg_matrix, networks = aggregate_to_networks(corr_matrix_256, roi_labels_256)
# Result: 7×7 matrix (Visual, Somatomotor, Dorsal Attention, etc.)
```

### Example 3: Multiple colormaps

```python
for colormap in ["RdBu", "coolwarm", "viridis"]:
    fig = plot_correlation_heatmap(corr_matrix, colormap=colormap)
    fig.show()
```

### Example 4: Different network layouts

```python
for layout in ["spring", "circular", "kamada_kawai"]:
    fig = plot_network_graph(corr_matrix, layout_type=layout)
    fig.show()
```

## Troubleshooting

### Matrix appears empty/gray
→ Threshold too high. Lower slider to 0.1-0.2.

### Network has too many edges
→ Increase threshold to 0.4-0.5 for cleaner view.

### Export not working
→ Install kaleido: `pip install kaleido`

See `MATRIX_RENDERER_GUIDE.md` for more troubleshooting.

## Integration Points

Use in any Streamlit page:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.matrix_renderer import render_correlation_matrix_streamlit

# In your page's render() function
render_correlation_matrix_streamlit(corr_matrix, roi_labels=roi_labels)
```

## References

- **Demo:** `pages/05_matrix_demo.py` - Live examples
- **Tests:** `tests/test_matrix_renderer.py` - Usage patterns
- **Guide:** `docs/MATRIX_RENDERER_GUIDE.md` - Complete documentation
- **Source:** `utils/matrix_renderer.py` - Implementation (500 lines, well-documented)

## Contributing

To extend:

1. Add new layout algorithm to `plot_network_graph()`
2. Add colormap to the `colorscale_map` dictionary
3. Add sorting method to `plot_correlation_heatmap()`
4. Add tests to `tests/test_matrix_renderer.py`

## License

Part of the longevity neuroimaging project.
