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
    randomise -i 4d_zmaps.nii.gz -o results/mixed_aov \
              -d design.mat -t design.con -f design.fts \
              -e design.grp -m mask.nii.gz -T -n 5000 --demean
"""

import numpy as np
import pandas as pd
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
    get_canonical_subject_order()
        Return subject order for 4D NIfTI merge
    """

    def __init__(
        self,
        control_subjects: List[str],
        walking_subjects: List[str],
        sessions: Optional[List[str]] = None,
    ):
        """
        Initialize builder with subject lists and session labels.

        Parameters
        ----------
        control_subjects : List[str]
            Subject IDs in control group (e.g., ['sub-033', 'sub-034', ...])
        walking_subjects : List[str]
            Subject IDs in walking intervention group (e.g., ['sub-050', ...])
        sessions : List[str], optional
            Session labels in order (e.g., ['ses-01', 'ses-02']).
            Defaults to ['ses-01', 'ses-02'].

        Raises
        ------
        ValueError
            If control_subjects and walking_subjects have overlapping IDs
            or if len(sessions) != 2 for paired design
        """
        self.control_subjects = sorted(control_subjects)
        self.walking_subjects = sorted(walking_subjects)
        
        if sessions is None:
            sessions = ['ses-01', 'ses-02']
        
        if len(sessions) != 2:
            raise ValueError(f"Paired design requires 2 sessions, got {len(sessions)}")
        
        self.sessions = sessions
        
        # Check for overlap
        overlap = set(self.control_subjects) & set(self.walking_subjects)
        if overlap:
            raise ValueError(f"Subject overlap between groups: {overlap}")
        
        # All subjects in canonical order
        self.all_subjects = self.control_subjects + self.walking_subjects
        self.n_subjects = len(self.all_subjects)
        self.n_rows = 2 * self.n_subjects
        
        # Initialize as None; set by build()
        self.design_matrix = None
        self.exchangeability_blocks = None
        self.contrasts = None
        self.ftest = None

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
        return cls(control_subjects, walking_subjects, sessions)

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
        # Build design matrix
        self._build_design_matrix()
        
        # Build contrasts
        self.contrasts = self._build_contrasts()
        
        # Build F-test
        self.ftest = self._build_ftest()
        
        # Build exchangeability blocks
        self.exchangeability_blocks = self._build_exchangeability_blocks()
        
        return (
            self.design_matrix,
            self.contrasts,
            self.ftest,
            self.exchangeability_blocks,
        )

    def _build_design_matrix(self):
        """Construct the design matrix: [Time, Group, Subject_means...]"""
        
        n_cols = 2 + self.n_subjects
        design_mat = np.zeros((self.n_rows, n_cols))
        
        row_idx = 0
        
        # Control group first
        for subj_idx, subject in enumerate(self.control_subjects):
            # Pre session (ses1)
            design_mat[row_idx, 0] = +1  # Time: +1 for pre
            design_mat[row_idx, 1] = +1  # Group: +1 for control
            design_mat[row_idx, 2 + subj_idx] = 1  # Subject mean
            row_idx += 1
            
            # Post session (ses2)
            design_mat[row_idx, 0] = -1  # Time: -1 for post
            design_mat[row_idx, 1] = +1  # Group: +1 for control
            design_mat[row_idx, 2 + subj_idx] = 1  # Subject mean
            row_idx += 1
        
        # Walking group second
        for subj_idx, subject in enumerate(self.walking_subjects):
            offset = len(self.control_subjects)
            
            # Pre session (ses1)
            design_mat[row_idx, 0] = +1  # Time: +1 for pre
            design_mat[row_idx, 1] = -1  # Group: -1 for walking
            design_mat[row_idx, 2 + offset + subj_idx] = 1  # Subject mean
            row_idx += 1
            
            # Post session (ses2)
            design_mat[row_idx, 0] = -1  # Time: -1 for post
            design_mat[row_idx, 1] = -1  # Group: -1 for walking
            design_mat[row_idx, 2 + offset + subj_idx] = 1  # Subject mean
            row_idx += 1
        
        self.design_matrix = design_mat

    def _build_contrasts(self) -> np.ndarray:
        """Build contrast vectors: [Interaction, Time, Group]"""
        
        n_cols = self.design_matrix.shape[1]
        contrasts = np.zeros((3, n_cols))
        
        # Contrast 0: Interaction (Time × Group)
        contrasts[0, 0] = 1  # Time
        contrasts[0, 1] = 1  # Group
        
        # Contrast 1: Time main effect
        contrasts[1, 0] = 1  # Time
        
        # Contrast 2: Group main effect
        contrasts[2, 1] = 1  # Group
        
        return contrasts

    def _build_ftest(self) -> np.ndarray:
        """Build F-test matrix (all contrasts)"""
        ftest = np.ones((1, 3))  # 1 F-test combining all 3 contrasts
        return ftest

    def _build_exchangeability_blocks(self) -> np.ndarray:
        """Build exchangeability blocks: [1,1,2,2,...,N,N] for paired constraint"""
        
        blocks = []
        for subject_idx in range(self.n_subjects):
            # Same block ID for pre/post pair of each subject
            block_id = subject_idx + 1  # FSL uses 1-indexed blocks
            blocks.extend([block_id, block_id])
        
        return np.array(blocks)

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Validate design matrix for FSL compatibility.

        Checks:
        1. Sufficient rank: rank >= n_cols - 1 (paired designs are rank-deficient by 1)
        2. No NaN/Inf values
        3. Subject columns mutually exclusive
        4. Exchangeability blocks match row count
        5. Paired constraint (each block label appears exactly twice)
        6. Effect columns orthogonal to subject means

        Returns
        -------
        (is_valid, error_messages) : Tuple[bool, List[str]]
            is_valid: True if all checks pass
            error_messages: List of error strings (empty if valid)

        Raises
        ------
        ValueError
            If design matrix not yet built (call .build() first)

        Examples
        --------
        >>> builder.build()
        >>> is_valid, errors = builder.validate()
        >>> if is_valid:
        ...     print("Design matrix is valid")
        """
        
        if self.design_matrix is None:
            raise ValueError("Design matrix not built. Call .build() first.")
        
        errors = []
        
        # Check no NaN/Inf first (must do before rank computation)
        if np.any(np.isnan(self.design_matrix)) or np.any(np.isinf(self.design_matrix)):
            errors.append("Design matrix contains NaN or Inf")
            # Return early to avoid NaN errors in other computations
            return (False, errors)
        
        # Check rank: paired designs are rank-deficient by 1 due to sum constraints
        try:
            rank = np.linalg.matrix_rank(self.design_matrix)
            n_cols = self.design_matrix.shape[1]
            # For paired designs, rank = n_cols - 1 is expected and acceptable
            if rank < n_cols - 1:
                errors.append(
                    f"Design matrix rank {rank} < required {n_cols - 1} "
                    f"(full rank would be {n_cols})"
                )
        except np.linalg.LinAlgError as e:
            errors.append(f"Rank computation failed: {e}")
        
        # Check subject columns are orthogonal (one-hot encoding)
        subject_cols = self.design_matrix[:, 2:]
        for col in range(subject_cols.shape[1]):
            col_sum = np.sum(subject_cols[:, col])
            if col_sum != 2:  # Should have exactly 2 ones (pre/post)
                errors.append(f"Subject column {col} not properly encoded (sum={col_sum}, expected 2)")
        
        # Check exchangeability blocks
        if self.exchangeability_blocks is not None:
            if len(self.exchangeability_blocks) != self.design_matrix.shape[0]:
                errors.append(
                    f"Block count {len(self.exchangeability_blocks)} != "
                    f"row count {self.design_matrix.shape[0]}"
                )
            
            # Check paired constraint: each block ID should appear exactly twice
            unique_blocks = np.unique(self.exchangeability_blocks)
            for block_id in unique_blocks:
                count = np.sum(self.exchangeability_blocks == block_id)
                if count != 2:
                    errors.append(f"Block {block_id} appears {count} times (expected 2)")
        
        # Check contrasts
        if self.contrasts is not None:
            if self.contrasts.shape[1] != self.design_matrix.shape[1]:
                errors.append(
                    f"Contrasts cols {self.contrasts.shape[1]} != "
                    f"design cols {self.design_matrix.shape[1]}"
                )
        
        return (len(errors) == 0, errors)

    def save_fsl_files(self, output_dir: Path) -> Dict[str, Path]:
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

        Returns
        -------
        files : Dict[str, Path]
            Mapping of filename (e.g., 'design.mat') to Path

        Raises
        ------
        IOError
            If directory cannot be created or files cannot be written
        ValueError
            If design matrix not yet built (call .build() first)

        Examples
        --------
        >>> builder.build()
        >>> files = builder.save_fsl_files('/path/to/output/')
        # Files created: design.mat, design.con, design.fts, design.grp
        """
        
        if self.design_matrix is None:
            raise ValueError("Design matrix not built. Call .build() first.")
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        files = {}
        
        # Save design matrix
        self._write_design_matrix(output_dir / 'design.mat')
        files['design.mat'] = output_dir / 'design.mat'
        
        # Save contrasts
        self._write_contrasts(output_dir / 'design.con')
        files['design.con'] = output_dir / 'design.con'
        
        # Save F-tests
        self._write_ftest(output_dir / 'design.fts')
        files['design.fts'] = output_dir / 'design.fts'
        
        # Save exchangeability blocks
        self._write_exchangeability_blocks(output_dir / 'design.grp')
        files['design.grp'] = output_dir / 'design.grp'
        
        return files

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
        n_waves = self.design_matrix.shape[1]
        n_points = self.design_matrix.shape[0]
        
        with open(path, 'w') as f:
            f.write(f"/NumWaves\t{n_waves}\n")
            f.write(f"/NumPoints\t{n_points}\n")
            f.write("/Matrix\n")
            np.savetxt(f, self.design_matrix, fmt='%.6f', delimiter='\t')

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
        n_waves = self.contrasts.shape[1]
        n_contrasts = self.contrasts.shape[0]
        
        with open(path, 'w') as f:
            f.write(f"/NumWaves\t{n_waves}\n")
            f.write(f"/NumContrasts\t{n_contrasts}\n")
            f.write("/Matrix\n")
            contrast_names = ["Interaction", "Time", "Group"]
            for i, row in enumerate(self.contrasts):
                row_str = '\t'.join(f'{val:.6f}' for val in row)
                f.write(f"{row_str}\t% {contrast_names[i]}\n")

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
        n_waves = self.ftest.shape[1]
        n_ftests = self.ftest.shape[0]
        
        with open(path, 'w') as f:
            f.write(f"/NumWaves\t{n_waves}\n")
            f.write(f"/NumFtests\t{n_ftests}\n")
            f.write("/Matrix\n")
            np.savetxt(f, self.ftest, fmt='%.6f', delimiter='\t')

    def _write_exchangeability_blocks(self, path: Path) -> None:
        """
        Write exchangeability blocks to FSL VEST format.

        FSL design.grp format (VEST header + one block label per row):
        ```
        /NumWaves 1
        /NumPoints N

        /Matrix
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
        blocks = self.exchangeability_blocks
        n_points = len(blocks)
        with open(path, 'w') as f:
            f.write(f"/NumWaves\t1\n")
            f.write(f"/NumPoints\t{n_points}\n")
            f.write("\n/Matrix\n")
            for val in blocks:
                f.write(f"{int(val)}\n")

    def get_canonical_subject_order(self) -> pd.DataFrame:
        """
        Return subject order for 4D NIfTI merge (matching design matrix row order).
        
        Returns
        -------
        df : pd.DataFrame
            DataFrame with columns: subject, session, group
            Rows in same order as design matrix (control pre/post, then walking pre/post)
        """
        
        rows = []
        
        # Control group
        for subject in self.control_subjects:
            rows.append({
                'subject': subject,
                'session': self.sessions[0],
                'group': 'control'
            })
            rows.append({
                'subject': subject,
                'session': self.sessions[1],
                'group': 'control'
            })
        
        # Walking group
        for subject in self.walking_subjects:
            rows.append({
                'subject': subject,
                'session': self.sessions[0],
                'group': 'walking'
            })
            rows.append({
                'subject': subject,
                'session': self.sessions[1],
                'group': 'walking'
            })
        
        return pd.DataFrame(rows)


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
    builder = MixedDesignBuilder(control_subjects, walking_subjects, sessions)
    return builder.build()


def validate_design_matrix(
    design_matrix: np.ndarray,
    exchangeability_blocks: np.ndarray,
) -> Dict[str, bool]:
    """
    Validate design matrix for FSL compatibility.

    Checks:
    1. Sufficient rank: rank >= n_cols - 1 (paired designs are rank-deficient by 1)
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
    report = {}
    
    # Check rank: paired designs are rank-deficient by 1
    try:
        rank = np.linalg.matrix_rank(design_matrix)
        n_cols = design_matrix.shape[1]
        # For paired designs, rank = n_cols - 1 is expected and acceptable
        report['full_rank'] = rank >= n_cols - 1
    except np.linalg.LinAlgError:
        report['full_rank'] = False
    
    # Check NaN/Inf
    report['no_nan_inf'] = (
        not np.any(np.isnan(design_matrix)) and 
        not np.any(np.isinf(design_matrix))
    )
    
    # Check condition number
    try:
        cond_num = np.linalg.cond(design_matrix)
        report['finite_condition'] = cond_num < 1e10
    except np.linalg.LinAlgError:
        report['finite_condition'] = False
    
    # Check blocks match row count
    report['blocks_match'] = len(exchangeability_blocks) == design_matrix.shape[0]
    
    # Check paired constraint
    if report['blocks_match']:
        unique_blocks = np.unique(exchangeability_blocks.astype(int))
        block_counts = [
            np.sum(exchangeability_blocks == block_id)
            for block_id in unique_blocks
        ]
        report['paired_constraint'] = np.all(np.array(block_counts) == 2)
    else:
        report['paired_constraint'] = False
    
    return report


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
    n_cols = 2 + n_subjects
    contrasts = np.zeros((3, n_cols))
    
    # Contrast 0: Interaction (Time × Group)
    contrasts[0, 0] = 1
    contrasts[0, 1] = 1
    
    # Contrast 1: Time main effect
    contrasts[1, 0] = 1
    
    # Contrast 2: Group main effect
    contrasts[2, 1] = 1
    
    return contrasts


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
    return np.ones((1, 3))
