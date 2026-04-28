# Connectivity Analysis Pages

Interactive Streamlit pages for neuroimaging connectivity analysis.

## 02_Seed_Connectivity.py

**Seed-based connectivity analysis with multi-atlas/seed selection, brain map viewer, and group statistics.**

A comprehensive tool for exploring functional connectivity from seed regions to the whole brain.

### Features

- **🌳 Multi-Atlas Support**: DiFuMo256, Schaefer400, combined Schaefer+Tian
- **🧠 Seed Selection**: Motor, cognitive, and subcortical seeds from roi_config.json
- **👤 Subject-Level Analysis**:
  - Individual seed-to-voxel correlation z-maps
  - Interactive Papaya viewer with 3-plane display
  - Real-time coordinate tracking
  - Threshold and colormap controls
  - NIfTI export
- **🌍 Group-Level Analysis**:
  - Statistical cluster summaries with anatomical labels
  - Effect sizes and p-value distributions
  - Multiple comparison correction visualization
  - CSV/JSON export of results
  - Download group-level maps
- **📊 Display Options**:
  - Adjustable z-value thresholds
  - 4 colormaps (Hot, Cool, Spectrum, Jet, Gray)
  - Overlay transparency control
  - Custom viewer height

### Data Requirements

**Subject-Level:**
- Connectivity z-maps (NIfTI): `results/seed_based/<seed>/<atlas>/<subject>_ses-<session>_zmap.nii.gz`

**Group-Level:**
- Statistics CSV: `results/group_analysis/seed_<seed>_<atlas>_clusters.csv`
- Group maps: `results/group_analysis/group_seed_<seed>_<atlas>_zmap.nii.gz`

### Configuration

Seeds are defined in `roi_config.json` with `"use_as_seed": true`:

```json
{
  "rois": [
    {
      "id": "dlpfc_L",
      "label": "Left DLPFC",
      "type": "mni_sphere",
      "mni_coords": [-44, 36, 20],
      "radius_mm": 6,
      "use_as_seed": true
    }
  ]
}
```

### Running Connectivity Analysis

Generate required maps and statistics:

```bash
# Subject and group-level connectivity
bash script/master_full_connectivity_workflow.sh

# Or test on subset
bash script/master_full_connectivity_workflow.sh --test
```

This generates:
- Subject-level z-maps in `results/seed_based/`
- Group-level statistics in `results/group_analysis/`
- HTML connectivity report

---

## Network Connectivity Analysis Page

Interactive visualization and analysis of whole-brain functional connectivity using DiFuMo 256 ROIs.

### Features

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
