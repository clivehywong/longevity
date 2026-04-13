# NeuConn - Neuroimaging Connectivity Suite

A comprehensive Streamlit application for neuroimaging quality control, preprocessing, and connectivity analysis.

## Features

### 🔍 Data QC (All Modalities)
- **Dataset Overview**: Scan BIDS directory, show available data
- **Visual Check**: Slice montages (axial/coronal/sagittal)
- **Papaya Viewer**: Interactive NIfTI viewer
- **Dimension Table**: X/Y/Z/T consistency checks
- **Exclusion Manager**: Mark and move bad scans

### 🧠 fMRI Analysis Pipeline
**Preprocessing:**
- HPC submission (fMRIPrep) with space-efficient workflow
- QC reports and summary tables
- Denoising (FSL FIX, ICA-AROMA, comparison)

**Subject-Level:**
- Local measures (fALFF, ALFF, ReHo, VMHC)
- Seed-based connectivity (seed-to-voxel, ROI-to-ROI)
- Effective connectivity (Regression DCM, MVAR/Granger)

**Group-Level:**
- Voxelwise statistics (LME, ANCOVA)
- ROI-level statistics
- Graph theory metrics
- Interactive visualization

### 🔗 dMRI Analysis Pipeline
**Preprocessing:**
- QSIPrep (preprocessing)
- QSIRecon (reconstruction, tractography)

**Subject-Level:**
- Diffusion metrics (FA, MD, RD, AD)
- Tractography visualization
- Structural connectivity matrices

**Group-Level:**
- TBSS (tract-based spatial statistics)
- Network analysis
- Multimodal comparison (fMRI vs dMRI)

### 🔄 Comparison Tool
- Compare preprocessing methods
- Compare QC thresholds
- Compare statistical models

### ⚙️ Pipeline Builder
- Chain analyses into automated workflows
- Save/load pipeline templates

## Installation

```bash
# Create conda environment
conda create -n neuconn python=3.11
conda activate neuconn

# Install dependencies
cd neuconn_app
pip install -r requirements.txt

# Optional: Install Julia for Regression DCM
# (App can auto-install on first use)
conda install julia -c conda-forge
```

## Quick Start

```bash
# Run the app
streamlit run app.py

# First time:
# 1. Go to Settings page
# 2. Set BIDS directory path
# 3. Configure HPC settings (if using HPC)
# 4. Go to Data QC → Dataset Overview to scan your data
```

## Configuration

Configuration is stored in YAML format at `~/neuconn_projects/<project_name>.yaml`.

Edit via:
- Settings page in the app (recommended)
- Manually edit YAML file

See `config/default_config.yaml` for all available options.

## Project Structure

```
neuconn_app/
├── app.py                    # Main entry point
├── pages/                    # Top-level navigation pages
├── pages_general_qc/         # Data QC tools
├── pages_fmri/              # fMRI analysis pages
├── pages_dmri/              # dMRI analysis pages
├── utils/                   # Core utilities
├── components/              # Reusable UI components
├── config/                  # Configuration files
├── templates/               # SLURM job templates
└── static/                  # Static assets (Papaya.js)
```

## Development Status

- ✅ Phase 1: Foundation and scaffolding (IN PROGRESS)
- 🚧 Phase 2: Core QC tools
- 🚧 Phase 3: HPC integration
- 🚧 Phase 4-12: Advanced features

See blueprint at `../.claude/plans/moonlit-yawning-curry.md` for complete roadmap.

## Requirements

- Python 3.11+
- 8GB+ RAM (16GB recommended for local processing)
- For HPC: SSH access to SLURM cluster
- For Regression DCM: Julia 1.10+

## License

MIT License (or specify your license)

## Contact

[Your contact information]
