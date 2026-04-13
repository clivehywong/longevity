"""
General Quality Control Pages

This section provides QC tools organized by BIDS modality:
- Dataset Overview: Scan BIDS directory, show available data
- Anatomical (anat): T1w, T2w QC
- Functional (func): BOLD QC
- Diffusion (dwi): DWI QC
- Field Maps (fmap): AP/PA QC

Each modality has 4 QC tools:
1. Visual Check - Slice montages
2. Papaya Viewer - Interactive NIfTI viewer
3. Dimension Table - Check X/Y/Z/T consistency
4. Mark/Exclude - Move bad scans to bids_excluded/
"""

import streamlit as st

st.title("⚙️ General Quality Control")

st.markdown("""
### Data QC by Modality

Select a modality from the sidebar to begin quality control checks.

Available tools for each modality:
- **Visual Check**: Axial/Coronal/Sagittal slice montages
- **Papaya Viewer**: Interactive 3D NIfTI viewer
- **Dimension Table**: X/Y/Z/T consistency checks
- **Mark/Exclude**: Flag and move bad scans
""")

# Placeholder - full implementation coming
st.info("🚧 This page is under construction. Use the sidebar to navigate to specific QC tools.")
