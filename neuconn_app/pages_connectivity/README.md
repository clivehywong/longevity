# Network Connectivity Analysis Page

Interactive visualization and analysis of whole-brain functional connectivity using DiFuMo 256 ROIs.

## Features

### Subject-Level Analysis
- **Subject & Session Selection**: Browse available subject-session pairs
- **Correlation Metrics**: Toggle between Pearson and Fisher-z correlations
- **Full Matrix Visualization**:
  - Interactive heatmap with hover details
  - Multiple colormaps (RdBu, coolwarm, viridis, icefire, Spectral)
  - Sorting options: no sort, hierarchical clustering, by-mean connectivity
  - Threshold filtering
- **Network Graph Visualization**:
  - Multiple layout algorithms (spring/force-directed, circular, Kamada-Kawai)
  - Customizable node and edge rendering
  - Interactive navigation

### Network-Level Aggregation
- Aggregate 256×256 full matrix to 7 Yeo networks
- Inter-network correlation matrices and graphs
- Automatic network assignment based on ROI labels

### Within/Between-Network Statistics
- Within-network connectivity mean, std, edge count
- Between-network connectivity statistics
- Threshold-based filtering

### Group-Level Analysis
- Load and visualize group-mean connectivity matrices
- Same visualization tools as subject-level
- Network-level aggregation for group data

### Subject-to-Group Comparison
- Side-by-side subject vs group matrices
- Difference visualization (subject - group)
- Correlation similarity metric

## Data Location

Expects connectivity results in:
```
results/
├── connectivity/
│   ├── subject_fc_matrices/
│   │   ├── sub-XXX_ses-01_fc_pearson.csv
│   │   └── sub-XXX_ses-01_fc_fisherz.csv
│   └── group_connectome.csv
```

## Usage

The page is integrated into the fMRI Analysis → Subject-Level → Network Connectivity menu.

### Quick Start
1. Go to **🧠 fMRI Analysis** → **👤 Subject-Level** → **Network Connectivity**
2. Select a subject-session pair
3. Choose correlation metric (Pearson or Fisher-z)
4. Use sidebar controls to adjust visualization:
   - Correlation threshold
   - Colormap
   - Sorting method (for heatmap)
   - Layout algorithm (for network graph)
   - Node label visibility

### Visualization Controls

**Heatmap Controls**:
- Threshold: Hide correlations with |r| < threshold
- Colormap: Color scheme preference
- Sorting: Reorder rows/columns (clustering, mean connectivity, or no sort)

**Network Graph Controls**:
- Layout: Force-directed physics, circular, or dimension reduction
- Labels: Toggle node label display (useful for large matrices)
- Node size and edge width scale automatically

## Implementation Details

### Key Functions

- `get_subject_session_pairs()`: Discover available data
- `load_subject_matrix()`: Load individual subject matrices
- `load_group_matrix()`: Load group-mean matrices
- `compute_network_stats()`: Calculate within/between-network statistics
- `aggregate_to_networks()`: Aggregate to 7 Yeo networks

### Network Assignment

Network labels are extracted from ROI labels using pattern matching:
- "Vis" → Visual
- "SomMot" → Somatomotor
- "DorsAttn" → Dorsal Attention
- "SalVentAttn" → Salience/Ventral Attention
- "Limbic" → Limbic
- "TempPar" → Temporal Parietal
- "DMN" or "Default" → Default Mode

### Matrix Statistics

For each subject/group:
- Diagonal validation (self-correlation ~1.0)
- Symmetry validation
- Range and distribution summaries
- High-correlation edge statistics

## Dependencies

- `streamlit` - UI framework
- `plotly` - Interactive visualizations
- `networkx` - Graph algorithms
- `numpy`, `pandas` - Data manipulation
- `scipy` - Statistical functions

## Integration

Page is dynamically loaded via `app.py` using `importlib.util`:
```python
from pages_connectivity.network_connectivity import render
```

The page requires:
- `config` in session state (loaded via `st.session_state.config`)
- `config["paths"]["results_dir"]` pointing to connectivity results
