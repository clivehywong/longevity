"""
Analysis Comparison Tool

Compare results from different:
- Preprocessing pipelines (fMRIPrep → FIX vs AROMA vs None)
- QC thresholds (Strict vs Moderate vs Lenient)
- Statistical models (Different formulas or covariates)
- Atlases (DiFuMo 256 vs Schaefer 400)

Comparison metrics:
- Spatial correlation between maps
- Mean difference maps
- Effect size impact on group results
- QC-FC correlation (motion artifact sensitivity)

Supports:
- Side-by-side visualization (2-3 analyses)
- Quantitative comparison metrics
- Overlap/consensus analysis
- Export comparison reports
"""

import streamlit as st

st.title("🔄 Analysis Comparison Tool")

st.markdown("""
### Compare Analysis Results

This tool allows you to compare results from different preprocessing methods,
QC thresholds, or statistical models.

**Common comparisons:**
- fMRIPrep only vs FSL FIX vs AROMA denoising
- Strict QC (18 subjects) vs Lenient QC (24 subjects)
- Different seed definitions or atlases
""")

st.info("🚧 Implementation coming in Phase 9.")
