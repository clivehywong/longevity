"""
Subject-Level: Effective Connectivity

Directed (causal) connectivity analyses:

Methods:
1. Regression DCM (Dynamic Causal Modeling):
   - Uses RegressionDynamicCausalModeling.jl (Julia)
   - Auto-install Julia runtime on first use
   - User defines network structure (adjacency matrix)
   - Output: Effective connectivity matrix with confidence intervals

2. MVAR/Granger Causality:
   - Multivariate autoregressive modeling
   - Tests if past values of ROI_i predict ROI_j
   - Library: nitime.analysis.GrangerAnalyzer

3. DTF/PDC (Frequency Domain):
   - Directed Transfer Function
   - Partial Directed Coherence
   - Decomposes causality by frequency band

Execution: Local only (not HPC)
ROI limit: 4-10 regions recommended (computational efficiency)

Implementation: Phase 11
"""

import streamlit as st

def render():
    st.header("🔗 Effective Connectivity")
    st.info("🚧 Implementation coming in Phase 11")

if __name__ == "__main__":
    render()
