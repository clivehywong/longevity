"""
Mixed-Design TFCE Group Statistics Design Builder

This module implements FSL-compatible design matrix construction for paired
pre/post × 2-group mixed ANOVA designs, used in longitudinal intervention
neuroimaging studies (e.g., Longevity study: walking intervention vs. control).

The design matrix structure has been validated with FSL randomise on 4-subject
toy data. See `/home/clivewong/proj/longevity/tmp/phase0_design_reference.md`
for detailed design specification and validation results.

**Key Design Principles:**
1. Time effect: +1 for pre-intervention, -1 for post-intervention (within-subject)
2. Group effect: +1 for control, -1 for walking intervention (between-subject)
3. Subject intercepts: Orthogonal random effects (one column per subject)
4. Exchangeability blocks: Enforce paired within-subject constraint [1,1,2,2,...]

**Typical Workflow:**
```python
from neuconn_app.utils.group_stats_design import MixedDesignBuilder

builder = MixedDesignBuilder.from_paired_two_group(
    control_subjects=['sub-033', 'sub-034', ...],
    walking_subjects=['sub-050', 'sub-051', ...],
    sessions=['ses-01', 'ses-02']
)

design_mat, contrasts, ftest, blocks = builder.build()

# Validate design matrix
builder.validate()

# Save FSL design files
builder.save_fsl_files('/path/to/output/')
```

**Classes:**
  MixedDesignBuilder - Factory for paired two-group mixed ANOVA designs

**Functions:**
  build_paired_two_group_design - Construct design matrix from subject lists
  validate_design_matrix - Check rank, orthogonality, and validity
  contrasts_paired_two_group - Generate standard contrasts
  ftest_paired_two_group - Generate F-test definition

**FSL Integration:**
  randomise command template:
    randomise -i 4d_zmaps.nii.gz -o results/mixed_aov \\
              -d design.mat -t design.con -f design.fts \\
              -e design.grp -m mask.nii.gz -T -n 5000 --demean
"""

import numpy as np
from pathlib import Path
from typing import List, Tuple, Dict, Optional
import logging

logger = logging.getLogger(__name__)


class MixedDesignBuilder:
    """
    Builder class for paired pre/post × 2-group mixed ANOVA FSL designs.

    This class encapsulates the design matrix construction, validation, and
    FSL file generation for mixed-design group statistics.

    Attributes
    ----------
    control_subjects : List[str]
        Subject IDs in control group
    walking_subjects : List[str]
        Subject IDs in walking intervention group
    sessions : List[str]
        Session labels, in order (e.g., ['ses-01', 'ses-02'])
    design_matrix : np.ndarray, optional
        Constructed design matrix (N_rows, N_cols)
    exchangeability_blocks : np.ndarray, optional
        Exchangeability block labels for paired constraint
    contrasts : np.ndarray, optional
        Contrast definitions (N_contrasts, N_cols)
    ftest : np.ndarray, optional
        F-test definition (N_ftests, N_contrasts)

    Methods
    -------
    from_paired_two_group(control_subjects, walking_subjects, sessions)
        Factory constructor for paired two-group design
    build()
        Construct design matrix, contrasts, and blocks
    validate()
        Validate design matrix for rank, orthogonality, and FSL compatibility
    save_fsl_files(output_dir)
        Save design, contrasts, f-tests, and groups to FSL format
    """

    def __init__(
        self,
        control_subjects: List[str],
        walking_subjects: List[str],
        sessions: List[str],
    ):
        """
        Initialize builder with subject lists and session labels.

        Parameters
        ----------
        control_subjects : List[str]
            Subject IDs in control group (e.g., ['sub-033', 'sub-034', ...])
        walking_subjects : List[str]
            Subject IDs in walking intervention group (e.g., ['sub-050', ...])
        sessions : List[str]
            Session labels in order (e.g., ['ses-01', 'ses-02'])

        Raises
        ------
        ValueError
            If control_subjects and walking_subjects have overlapping IDs
            or if len(sessions) != 2 for paired design
        """

    @classmethod
    def from_paired_two_group(
        cls,
        control_subjects: List[str],
        walking_subjects: List[str],
        sessions: Optional[List[str]] = None,
    ) -> "MixedDesignBuilder":
        """
        Factory constructor for paired two-group mixed ANOVA design.

        Parameters
        ----------
        control_subjects : List[str]
            Subject IDs in control group, should be sorted
        walking_subjects : List[str]
            Subject IDs in walking intervention group, should be sorted
        sessions : List[str], optional
            Session labels in order. Defaults to ['ses-01', 'ses-02'].

        Returns
        -------
        MixedDesignBuilder
            Initialized builder instance ready for .build()

        Examples
        --------
        >>> builder = MixedDesignBuilder.from_paired_two_group(
        ...     control_subjects=['sub-033', 'sub-034'],
        ...     walking_subjects=['sub-050', 'sub-051']
        ... )
        >>> design_mat, contrasts, ftest, blocks = builder.build()
        """

    def build(self) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """
        Construct design matrix, contrasts, F-tests, and exchangeability blocks.

        This method implements the paired pre/post × 2-group mixed ANOVA design:

        **Design Matrix Structure:**
        - Rows: 2 * N_subjects (one per session per subject)
        - Columns:
          - Col 0: Time effect (+1 pre, -1 post)
          - Col 1: Group effect (+1 control, -1 walking)
          - Cols 2+: Subject intercepts (one per subject, mutually exclusive)

        **Exchangeability Blocks:**
        - [1, 1, 2, 2, 3, 3, ..., N, N] for paired within-subject constraint

        **Contrasts:**
        - Row 0: Interaction [1, 1, 0, 0, ..., 0]
        - Row 1: Time main [1, 0, 0, 0, ..., 0]
        - Row 2: Group main [0, 1, 0, 0, ..., 0]

        **F-test:**
        - Combined ANOVA: [1, 1, 1] (all three contrasts)

        Returns
        -------
        design_matrix : np.ndarray, shape (2*N, 2+N)
            FSL-compatible design matrix
        contrasts : np.ndarray, shape (3, 2+N)
            Three contrasts (interaction, time, group)
        ftest : np.ndarray, shape (1, 3)
            F-test combining all contrasts
        exchangeability_blocks : np.ndarray, shape (2*N,)
            1-indexed block labels for paired constraint

        Raises
        ------
        ValueError
            If design matrix is rank-deficient or invalid
        """

    def validate(self) -> Dict[str, bool]:
        """
        Validate design matrix for FSL compatibility.

        Checks:
        1. Full rank: rank(design_matrix) == n_cols
        2. No NaN/Inf values
        3. Subject columns mutually exclusive
        4. Exchangeability blocks match row count
        5. Paired constraint (each block label appears exactly twice)
        6. Effect columns orthogonal to subject means

        Returns
        -------
        validation_report : Dict[str, bool]
            Dictionary with keys: full_rank, no_nan_inf, subject_exclusive,
            blocks_match, paired_constraint, effects_orthogonal
            All values should be True for valid design.

        Raises
        ------
        ValueError
            If any validation check fails (can be caught and reported)

        Examples
        --------
        >>> builder.build()
        >>> report = builder.validate()
        >>> all(report.values())  # True if all checks pass
        """

    def save_fsl_files(self, output_dir: Path) -> None:
        """
        Save design matrix, contrasts, F-tests, and groups to FSL format.

        Generates four files:
        - design.mat: Design matrix (ASCII, FSL format)
        - design.con: Contrast definitions (ASCII, FSL format)
        - design.fts: F-test definitions (ASCII, FSL format)
        - design.grp: Exchangeability blocks (ASCII, FSL format)

        Parameters
        ----------
        output_dir : Path or str
            Directory to save FSL files. Created if doesn't exist.

        Raises
        ------
        IOError
            If directory cannot be created or files cannot be written
        ValueError
            If design matrix not yet built (call .build() first)

        Examples
        --------
        >>> builder.build()
        >>> builder.save_fsl_files('/path/to/output/')
        # Files created: design.mat, design.con, design.fts, design.grp
        """

    def _write_design_matrix(self, path: Path) -> None:
        """
        Write design matrix to FSL format (ASCII).

        FSL design.mat format:
        ```
        /NumWaves N_cols
        /NumPoints N_rows

        /Matrix
        col0_val0  col1_val0  ...
        col0_val1  col1_val1  ...
        ...
        ```

        Parameters
        ----------
        path : Path
            Output file path for design.mat
        """

    def _write_contrasts(self, path: Path) -> None:
        """
        Write contrasts to FSL format (ASCII).

        FSL design.con format:
        ```
        /NumWaves N_cols
        /NumContrasts N_contrasts

        /Matrix
        col0  col1  col2  ...  % Contrast 1 comment
        col0  col1  col2  ...  % Contrast 2 comment
        ...
        ```

        Parameters
        ----------
        path : Path
            Output file path for design.con
        """

    def _write_ftest(self, path: Path) -> None:
        """
        Write F-tests to FSL format (ASCII).

        FSL design.fts format:
        ```
        /NumWaves N_contrasts
        /NumFtests N_ftests

        /Matrix
        contrast0_weight  contrast1_weight  ...  % F-test 1
        ...
        ```

        Parameters
        ----------
        path : Path
            Output file path for design.fts
        """

    def _write_exchangeability_blocks(self, path: Path) -> None:
        """
        Write exchangeability blocks to FSL format (ASCII).

        FSL design.grp format (one block label per row):
        ```
        1
        1
        2
        2
        3
        3
        ...
        ```

        Parameters
        ----------
        path : Path
            Output file path for design.grp
        """


def build_paired_two_group_design(
    control_subjects: List[str],
    walking_subjects: List[str],
    sessions: Optional[List[str]] = None,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Construct paired pre/post × 2-group mixed ANOVA design matrix.

    Convenience function wrapping MixedDesignBuilder for simple use cases.

    Parameters
    ----------
    control_subjects : List[str]
        Subject IDs in control group
    walking_subjects : List[str]
        Subject IDs in walking intervention group
    sessions : List[str], optional
        Session labels. Defaults to ['ses-01', 'ses-02'].

    Returns
    -------
    design_matrix : np.ndarray, shape (2*N, 2+N)
        FSL-compatible design matrix
    contrasts : np.ndarray, shape (3, 2+N)
        Three contrasts (interaction, time, group)
    ftest : np.ndarray, shape (1, 3)
        F-test combining all contrasts
    exchangeability_blocks : np.ndarray, shape (2*N,)
        1-indexed block labels for paired constraint

    Examples
    --------
    >>> design_mat, contrasts, ftest, blocks = build_paired_two_group_design(
    ...     control_subjects=['sub-033', 'sub-034'],
    ...     walking_subjects=['sub-050', 'sub-051']
    ... )
    >>> design_mat.shape
    (8, 6)  # 4 subjects * 2 sessions = 8 rows; 2 effects + 4 subject intercepts = 6 cols
    """


def validate_design_matrix(
    design_matrix: np.ndarray,
    exchangeability_blocks: np.ndarray,
) -> Dict[str, bool]:
    """
    Validate design matrix for FSL compatibility.

    Checks:
    1. Full rank (no collinearity)
    2. No NaN or Inf values
    3. Finite condition number (< 1e10)
    4. Exchangeability blocks match row count
    5. Paired constraint (each block appears exactly twice)

    Parameters
    ----------
    design_matrix : np.ndarray, shape (N_rows, N_cols)
        Design matrix to validate
    exchangeability_blocks : np.ndarray, shape (N_rows,)
        Block labels (1-indexed)

    Returns
    -------
    validation_report : Dict[str, bool]
        Dictionary with validation results. All values should be True.

    Raises
    ------
    ValueError
        If design matrix is rank-deficient or invalid
    """


def contrasts_paired_two_group(n_subjects: int) -> np.ndarray:
    """
    Generate standard contrasts for paired two-group design.

    **Contrasts:**
    1. Interaction: Time × Group interaction (tests group-specific time effects)
    2. Time: Main effect of time (tests overall pre→post change)
    3. Group: Main effect of group (tests baseline group difference)

    Parameters
    ----------
    n_subjects : int
        Number of subjects (used to pad subject intercept columns)

    Returns
    -------
    contrasts : np.ndarray, shape (3, 2 + n_subjects)
        Three contrast rows (interaction, time, group)

    Examples
    --------
    >>> contrasts = contrasts_paired_two_group(n_subjects=36)
    >>> contrasts.shape
    (3, 38)  # 3 contrasts, 2 effects + 36 subject intercepts
    """


def ftest_paired_two_group() -> np.ndarray:
    """
    Generate F-test definition for paired two-group design.

    The F-test combines all three contrasts (interaction, time, group)
    for an exploratory ANOVA-like omnibus test.

    Returns
    -------
    ftest : np.ndarray, shape (1, 3)
        Single F-test row combining all three contrasts

    Examples
    --------
    >>> ftest = ftest_paired_two_group()
    >>> ftest
    array([[1, 1, 1]])
    """
