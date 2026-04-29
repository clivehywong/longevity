# Connectivity Analysis Pages (Viewers)

Interactive Streamlit pages for visualizing XCP-D-driven connectivity results.

> **Data source:** All viewer pages read from `derivatives/connectivity/{pipeline}/` rather than the legacy `results/` tree. Use the pipeline selector (fc / fc_gsr / ec) and atlas selector (4S256Parcels, 4S456Parcels, Glasser, Gordon, Tian) on each page.

## 02_Seed_Connectivity.py

**Seed-based connectivity viewer — subject-level z-maps and group statistics.**

### Features

- **🌳 Multi-Atlas Support**: 4S256Parcels, 4S456Parcels, Glasser, Gordon, Tian (XCP-D native)
- **🔀 Pipeline selector**: fc / fc_gsr / ec
- **🎛️ Measure selector**: any of the 8 connectivity measures
- **🧠 Seed Selection**: xcpd_atlas_parcel, custom_nifti_roi, sphere sources
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

### Data location

```
derivatives/connectivity/{fc,fc_gsr,ec}/
  sub-XX/ses-YY/seed/<seed_id>/
    *_atlas-<A>_measure-<M>_seed-to-parcel.tsv
    *_seed-to-voxel_zmap.nii.gz
  group/voxel/...
```

---

## Network Connectivity Page

**Parcel × parcel relmat viewer — subject-level and group-level matrix visualization.**

### Features

### Subject-Level Analysis
- **Subject & Session Selection**: Browse available subject-session pairs
- **Pipeline + Atlas + Measure selectors**: fc/fc_gsr/ec, 5 atlases, 8 measures
- **Full Matrix Visualization**:
  - Interactive heatmap with hover details
  - Multiple colormaps (RdBu, coolwarm, viridis, icefire, Spectral)
  - Sorting options: no sort, hierarchical clustering, by-mean connectivity
  - Threshold filtering
- **Network Graph Visualization**:
  - Multiple layout algorithms
  - Customizable node and edge rendering

### Group-Level Analysis
- Load and visualize group-mean connectivity matrices from `derivatives/connectivity/group/matrix/`
- Network-level aggregation
- Subject-to-group comparison

### Data location

```
derivatives/connectivity/{fc,fc_gsr,ec}/
  sub-XX/ses-YY/network/atlas-<A>/
    *_measure-<M>_relmat.tsv
    *_measure-<M>_relmat-z.tsv
  group/matrix/...
```

## Viewer utilities

`utils/connectivity_viewer.py` provides helpers for loading relmat and zmap files from the new output tree, keyed by `(pipeline, atlas, measure, subject, session)`.
