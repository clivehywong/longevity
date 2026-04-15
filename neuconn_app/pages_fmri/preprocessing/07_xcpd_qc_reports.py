"""
Dedicated XCP-D QC reports page.
"""

from __future__ import annotations

from pathlib import Path
import sys

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from utils.pipeline_state import load_pipeline_state
from utils.xcpd_qc import render_xcpd_qc_reports


def render() -> None:
    config = st.session_state.get("config", {})
    if not config:
        st.error("Configuration not loaded.")
        return

    state = load_pipeline_state(config)
    render_xcpd_qc_reports(config, state, title="📊 XCP-D QC Reports")


if __name__ == "__main__":
    render()
