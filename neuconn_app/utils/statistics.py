"""
Statistical Analysis Utilities

Group-level statistical functions:
- run_mixed_effects(): Linear mixed-effects models (statsmodels)
- run_ancova(): ANCOVA models
- apply_tfce(): Permutation testing with TFCE
- apply_fdr_correction(): Benjamini-Hochberg FDR
- extract_clusters(): Find significant clusters with labels

Reused from script/group_level_analysis.py

Implementation: Phase 8
"""

import numpy as np
import pandas as pd
from typing import Dict, List


def run_mixed_effects(data: np.ndarray, metadata: pd.DataFrame, formula: str) -> Dict:
    """
    Run linear mixed-effects model voxelwise or connection-wise.

    Args:
        data: N_subjects × N_voxels or N_connections array
        metadata: DataFrame with subject_id, group, time, covariates
        formula: statsmodels formula string

    Returns:
        dict with t_stat, p_value arrays
    """
    # TODO: Port from script/group_level_analysis.py
    pass
