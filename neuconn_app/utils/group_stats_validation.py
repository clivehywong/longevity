"""
Subject Data Validator for Group Statistics

This module validates 72 zmaps (36 subjects × 2 sessions) for mixed-design
group statistics. It ensures all zmaps are present, have correct shape/dtype,
and are free of NaN artifacts before group-level analysis.

**Key Features:**
1. Load canonical subject order from CSV
2. Validate individual zmap files
3. Batch validation of all 72 zmaps
4. Generate summary statistics and error reports
5. Comprehensive logging for diagnostics

**Expected Zmap Location:**
  derivatives/connectivity/fc/{subject}/{session}/seed/
    atlas-{atlas}/[seed-dir]/{subject}_{session}_seed-*_zmap.nii.gz

**Usage Example:**
```python
from neuconn_app.utils.group_stats_validation import SubjectDataValidator

validator = SubjectDataValidator(
    bids_root="/path/to/longevity",
    canonical_order_csv="/path/to/canonical_subject_order.csv"
)

# Validate all 72 zmaps
validation_df = validator.validate_all_subjects()
summary = validator.summarize_validation(validation_df)

# Get validated zmaps in canonical order
if summary['error_count'] == 0:
    zmaps = validator.get_canonical_zmaps_list()
```

**Classes:**
  SubjectDataValidator - Main validation class

**Functions:**
  None (all methods are on SubjectDataValidator)
"""

import numpy as np
import pandas as pd
import nibabel as nib
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import logging
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


def _read_subject_table(path: Path) -> pd.DataFrame:
    sep = "\t" if path.suffix.lower() == ".tsv" else ","
    return pd.read_csv(path, sep=sep)


def _format_participant_id(value: Any) -> str:
    subject = str(value).strip()
    if subject.startswith("sub-"):
        return subject
    digits = "".join(ch for ch in subject if ch.isdigit())
    if digits:
        return f"sub-{int(digits):03d}"
    return subject


def _format_session_id(value: Any) -> str:
    session = str(value).strip()
    if session.startswith("ses-"):
        return session
    digits = "".join(ch for ch in session if ch.isdigit())
    if digits:
        return f"ses-{int(digits):02d}"
    return session


def _to_canonical_order(df: pd.DataFrame) -> pd.DataFrame:
    canonical = df.copy()
    if "subject_id" in canonical.columns and "participant_id" not in canonical.columns:
        canonical = canonical.rename(columns={"subject_id": "participant_id"})

    required_cols = {"row_index", "subject", "session", "group"}
    if required_cols.issubset(canonical.columns):
        canonical["subject"] = canonical["subject"].apply(_format_participant_id)
        canonical["session"] = canonical["session"].apply(_format_session_id)
        canonical["group"] = canonical["group"].astype(str).str.strip().str.lower()
        return canonical

    if not {"participant_id", "group"}.issubset(canonical.columns):
        raise ValueError(
            "Canonical order file must contain either row_index/subject/session/group "
            "or participant_id/group columns."
        )

    rows = []
    for participant_id, group in canonical[["participant_id", "group"]].dropna(subset=["participant_id"]).itertuples(index=False):
        subject = _format_participant_id(participant_id)
        normalized_group = str(group).strip().lower()
        for session in ("ses-01", "ses-02"):
            rows.append(
                {
                    "row_index": len(rows),
                    "subject": subject,
                    "session": session,
                    "group": normalized_group,
                }
            )

    return pd.DataFrame(rows, columns=["row_index", "subject", "session", "group"])


@dataclass
class ValidationResult:
    """Immutable result of validating a single zmap."""
    exists: bool
    shape: Optional[Tuple[int, ...]] = None
    dtype: Optional[str] = None
    has_nan: bool = False
    mean: Optional[float] = None
    std: Optional[float] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for DataFrame storage."""
        return asdict(self)


class SubjectDataValidator:
    """
    Validates 72 zmaps (36 subjects × 2 sessions) for group statistics.

    This validator ensures all zmaps are present, have correct shape and dtype,
    and are free of NaN artifacts. It maintains canonical subject order from
    the input CSV and provides detailed error reporting.

    Attributes
    ----------
    bids_root : Path
        Project root directory
    canonical_order_csv : Path
        Path to canonical subject order CSV
    canonical_order : pd.DataFrame
        Loaded canonical order with columns: row_index, subject, session, group
    pipeline : str
        Connectivity pipeline (default 'fc')
    atlas : str
        Atlas used (default '4S256Parcels')
    measure : str
        Connectivity measure (default 'pearson')

    Methods
    -------
    validate_subject_file(subject, session, seed, pipeline, measure)
        Validate a single zmap file
    validate_all_subjects()
        Batch validate all 72 zmaps
    get_canonical_zmaps_list()
        Get zmap paths in canonical order
    summarize_validation(df)
        Generate summary statistics from validation results
    """

    def __init__(
        self,
        bids_root: str,
        canonical_order_csv: str,
        pipeline: str = "fc",
        atlas: str = "4S256Parcels",
        measure: str = "pearson",
    ):
        """
        Initialize validator with project paths.

        Parameters
        ----------
        bids_root : str
            Project root directory
        canonical_order_csv : str
            Path to canonical subject order CSV
        pipeline : str, optional
            Connectivity pipeline (default 'fc')
        atlas : str, optional
            Atlas used (default '4S256Parcels')
        measure : str, optional
            Connectivity measure (default 'pearson')

        Raises
        ------
        FileNotFoundError
            If canonical_order_csv does not exist
        ValueError
            If canonical_order_csv has invalid structure
        """
        self.bids_root = Path(bids_root)
        self.canonical_order_csv = Path(canonical_order_csv)
        self.pipeline = pipeline
        self.atlas = atlas
        self.measure = measure

        if not self.canonical_order_csv.exists():
            raise FileNotFoundError(
                f"Canonical order CSV not found: {self.canonical_order_csv}"
            )

        # Load canonical order
        self.canonical_order = self._load_canonical_order()

        logger.info(
            f"Initialized SubjectDataValidator with {len(self.canonical_order)} rows"
        )

    def _load_canonical_order(self) -> pd.DataFrame:
        """
        Load canonical subject order from CSV.

        Expected columns: row_index, subject, session, group

        Returns
        -------
        pd.DataFrame
            Canonical order with 72 rows

        Raises
        ------
        ValueError
            If CSV structure is invalid
        """
        try:
            df = _to_canonical_order(_read_subject_table(self.canonical_order_csv))
        except Exception as e:
            raise ValueError(
                f"Failed to read canonical_order_csv: {e}"
            ) from e

        required_cols = ["row_index", "subject", "session", "group"]
        missing_cols = set(required_cols) - set(df.columns)
        if missing_cols:
            raise ValueError(
                f"Canonical order CSV missing columns: {missing_cols}. "
                f"Has: {list(df.columns)}"
            )

        if len(df) == 0:
            raise ValueError("Canonical order CSV has no rows")

        logger.info(
            f"Loaded canonical order: {len(df)} subjects/sessions, "
            f"groups: {df['group'].unique()}"
        )

        return df

    def _find_zmap_file(
        self,
        subject: str,
        session: str,
        seed: Optional[str] = None,
    ) -> Optional[Path]:
        """
        Find zmap file for subject/session.

        If seed is not provided, finds any seed zmap (first match).

        Parameters
        ----------
        subject : str
            Subject ID (e.g., 'sub-033')
        session : str
            Session ID (e.g., 'ses-01')
        seed : str, optional
            Seed name filter. If None, returns first seed found.

        Returns
        -------
        Path or None
            Path to zmap file, or None if not found
        """
        subject_label = _format_participant_id(subject)
        session_label = _format_session_id(session)
        
        seed_dir = (
            self.bids_root
            / "derivatives" / "connectivity" / self.pipeline
            / subject_label / session_label / "seed"
        )

        if not seed_dir.exists():
            return None

        # Search for zmap files
        zmap_files = list(seed_dir.rglob("*_seed-to-voxel_zmap.nii.gz"))

        if not zmap_files:
            return None

        if seed is None:
            # Return first zmap
            return zmap_files[0]

        # Filter by seed name
        for zmap in zmap_files:
            if seed in str(zmap):
                return zmap

        return None

    # Failure stage labels (ordered from most upstream to most downstream)
    STAGE_NO_BIDS = "No BIDS session data"
    STAGE_NO_FMRIPREP = "fMRIPrep not complete"
    STAGE_NO_XCPD = "XCP-D not complete"
    STAGE_NO_SEEDFC = "Seed FC not computed"

    def _get_mean_fd(self, subject: str, session: str, pipeline: Optional[str] = None) -> Optional[float]:
        """
        Return mean framewise displacement (mm) for a subject/session from XCP-D motion TSV.

        Returns None if the motion TSV is not found (e.g. XCP-D not run).
        """
        pl = pipeline or self.pipeline
        xcpd_func = (
            self.bids_root / "derivatives" / "preprocessing"
            / "xcpd" / pl / subject / session / "func"
        )
        motion_files = list(xcpd_func.glob("*_motion.tsv")) if xcpd_func.exists() else []
        if not motion_files:
            return None
        try:
            df = pd.read_csv(motion_files[0], sep="\t")
            if "framewise_displacement" in df.columns:
                return float(df["framewise_displacement"].mean())
        except Exception:
            pass
        return None

    def _trace_error_chain(self, subject: str, session: str, pipeline: Optional[str] = None) -> str:
        """
        Trace why a zmap is missing by checking each upstream step.

        Returns a human-readable stage label from most upstream failure.
        """
        pl = pipeline or self.pipeline

        # Step 1: BIDS session func directory
        bids_func = self.bids_root / "bids" / subject / session / "func"
        if not bids_func.exists() or not any(bids_func.glob("*_bold.nii.gz")):
            return self.STAGE_NO_BIDS

        # Step 2: fMRIPrep output for this session
        fmriprep_func = (
            self.bids_root / "derivatives" / "preprocessing"
            / "fmriprep" / subject / session / "func"
        )
        if not fmriprep_func.exists() or not any(fmriprep_func.iterdir()):
            return self.STAGE_NO_FMRIPREP

        # Step 3: XCP-D atlas timeseries TSVs for this session/pipeline
        xcpd_func = (
            self.bids_root / "derivatives" / "preprocessing"
            / "xcpd" / pl / subject / session / "func"
        )
        if not xcpd_func.exists() or not any(xcpd_func.glob("*_timeseries.tsv")):
            return self.STAGE_NO_XCPD

        return self.STAGE_NO_SEEDFC

    def validate_subject_file(
        self,
        subject: str,
        session: str,
        seed: Optional[str] = None,
        pipeline: Optional[str] = None,
        measure: Optional[str] = None,
    ) -> ValidationResult:
        """
        Validate a single zmap file.

        Checks:
        - File exists
        - Shape matches expected (91, 109, 91)
        - Dtype is float64 or similar
        - No NaN values
        - Mean/std are reasonable

        Parameters
        ----------
        subject : str
            Subject ID (e.g., 'sub-033')
        session : str
            Session ID (e.g., 'ses-01')
        seed : str, optional
            Seed name filter
        pipeline : str, optional
            Override instance pipeline
        measure : str, optional
            Connectivity measure (for logging)

        Returns
        -------
        ValidationResult
            Result object with validation status and data properties
        """
        pipeline = pipeline or self.pipeline
        measure = measure or self.measure

        try:
            zmap_path = self._find_zmap_file(subject, session, seed)

            if zmap_path is None:
                return ValidationResult(
                    exists=False,
                    error=self._trace_error_chain(subject, session, pipeline),
                )

            if not zmap_path.exists():
                return ValidationResult(
                    exists=False,
                    error=f"Zmap file does not exist: {zmap_path}",
                )

            # Load nifti
            try:
                img = nib.load(str(zmap_path))
            except Exception as e:
                return ValidationResult(
                    exists=True,
                    error=f"Failed to load nifti: {e}",
                )

            data = img.get_fdata()

            # Check shape
            expected_shape = (91, 109, 91)
            if data.shape != expected_shape:
                return ValidationResult(
                    exists=True,
                    shape=data.shape,
                    error=f"Shape mismatch: expected {expected_shape}, got {data.shape}",
                )

            # Check dtype
            dtype_str = str(data.dtype)
            if not (data.dtype == np.float64 or data.dtype == np.float32):
                return ValidationResult(
                    exists=True,
                    shape=data.shape,
                    dtype=dtype_str,
                    error=f"Unexpected dtype: {dtype_str}",
                )

            # Check for NaN
            has_nan = np.isnan(data).any()
            nan_count = np.isnan(data).sum() if has_nan else 0
            if has_nan:
                return ValidationResult(
                    exists=True,
                    shape=data.shape,
                    dtype=dtype_str,
                    has_nan=True,
                    error=f"Contains {nan_count} NaN values",
                )

            # Compute statistics
            mean_val = float(np.mean(data))
            std_val = float(np.std(data))

            logger.debug(
                f"Validated {subject} {session}: shape={data.shape}, "
                f"mean={mean_val:.4f}, std={std_val:.4f}"
            )

            return ValidationResult(
                exists=True,
                shape=data.shape,
                dtype=dtype_str,
                has_nan=False,
                mean=mean_val,
                std=std_val,
            )

        except Exception as e:
            logger.exception(f"Unexpected error validating {subject} {session}")
            return ValidationResult(
                exists=False,
                error=f"Unexpected error: {str(e)[:100]}",
            )

    def validate_all_subjects(
        self,
        seed: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Batch validate all 72 zmaps in canonical order.

        Parameters
        ----------
        seed : str, optional
            Seed name filter

        Returns
        -------
        pd.DataFrame
            Validation results with columns:
            - row_index: Position in canonical order
            - subject: Subject ID
            - session: Session ID
            - group: Group assignment
            - exists: File existence
            - shape: Data shape
            - dtype: Data type
            - has_nan: Whether contains NaN
            - mean: Data mean
            - std: Data std
            - error: Error message if any
        """
        results = []

        logger.info(
            f"Starting batch validation of {len(self.canonical_order)} zmaps"
        )

        for _, row in self.canonical_order.iterrows():
            subject = row["subject"]
            session = row["session"]

            # Validate
            validation = self.validate_subject_file(
                subject=subject,
                session=session,
                seed=seed,
            )

            # Build result row
            result_row = {
                "row_index": int(row["row_index"]),
                "subject": subject,
                "session": session,
                "group": row["group"],
            }
            result_row.update(validation.to_dict())
            result_row["mean_fd"] = self._get_mean_fd(subject, session)
            results.append(result_row)

        df = pd.DataFrame(results)

        logger.info(
            f"Completed batch validation: "
            f"{(~df['error'].isna()).sum()} errors, "
            f"{df['exists'].sum()} valid files"
        )

        return df

    def validate_alff_reho(self, stat: str) -> pd.DataFrame:
        """Validate ALFF/ReHo voxelwise maps from XCP-D outputs.

        Maps are at:
          derivatives/preprocessing/xcpd/{pipeline}/sub-{id}/ses-{session}/func/
            sub-{id}_{session}_task-rest_space-MNI152NLin6Asym_res-2_stat-{stat}_boldmap.nii.gz

        Parameters
        ----------
        stat : str
            Either "alff" or "reho"

        Returns
        -------
        pd.DataFrame
            Validation results with same columns as validate_all_subjects()
        """
        rows = []
        for _, row in self.canonical_order.iterrows():
            subject = row["subject"]
            session = row["session"]
            group = row["group"]

            func_dir = (
                self.bids_root / "derivatives" / "preprocessing" / "xcpd"
                / self.pipeline / subject / session / "func"
            )
            pattern = f"*_space-MNI152NLin6Asym_res-2_stat-{stat}_boldmap.nii.gz"
            maps = list(func_dir.glob(pattern)) if func_dir.exists() else []
            exists = len(maps) > 0
            map_path = str(maps[0]) if maps else None
            mean_fd = self._get_mean_fd(subject, session)

            rows.append({
                "row_index": int(row["row_index"]),
                "subject": subject,
                "session": session,
                "group": group,
                "exists": exists,
                "map_path": map_path,
                "error": None if exists else f"No {stat} map in {func_dir}",
                "mean_fd": mean_fd,
                "failure_stage": None if exists else self.STAGE_NO_XCPD,
            })
        return pd.DataFrame(rows)

    def get_canonical_zmaps_list(
        self,
        validation_df: Optional[pd.DataFrame] = None,
        seed: Optional[str] = None,
    ) -> List[str]:
        """
        Get list of zmap file paths in canonical order.

        If validation_df is provided, only includes files marked as valid.

        Parameters
        ----------
        validation_df : pd.DataFrame, optional
            Validation results from validate_all_subjects()
        seed : str, optional
            Seed name filter

        Returns
        -------
        List[str]
            List of zmap file paths in canonical order

        Raises
        ------
        RuntimeError
            If any required zmap is missing (when validation_df provided)
        """
        zmaps = []

        for _, row in self.canonical_order.iterrows():
            subject = row["subject"]
            session = row["session"]

            # If validation_df provided, check if valid
            if validation_df is not None:
                match = validation_df[
                    (validation_df["subject"] == subject)
                    & (validation_df["session"] == session)
                ]

                if len(match) == 0:
                    raise RuntimeError(
                        f"Subject {subject} {session} not in validation results"
                    )

                if not match.iloc[0]["exists"] or match.iloc[0]["error"] is not None:
                    raise RuntimeError(
                        f"Cannot get zmap for invalid subject {subject} {session}: "
                        f"{match.iloc[0]['error']}"
                    )

            # Find zmap file
            zmap_path = self._find_zmap_file(subject, session, seed)
            if zmap_path is None:
                raise RuntimeError(
                    f"Zmap not found for {subject} {session}"
                )

            zmaps.append(str(zmap_path))

        logger.info(f"Built canonical zmap list: {len(zmaps)} files")

        return zmaps

    def summarize_validation(
        self,
        df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """
        Generate summary statistics from validation results.

        Parameters
        ----------
        df : pd.DataFrame
            Validation results from validate_all_subjects()

        Returns
        -------
        Dict[str, Any]
            Summary with keys:
            - total_count: Total subjects validated
            - valid_count: Valid zmaps
            - missing_count: Missing files
            - error_count: Files with errors
            - error_summary: Dict of error types → counts
            - mean_stats: Dict with mean/std of data means
            - group_summary: Dict with per-group stats

        Examples
        --------
        >>> summary = validator.summarize_validation(df)
        >>> print(f"Valid: {summary['valid_count']}/{summary['total_count']}")
        >>> if summary['error_count'] > 0:
        ...     print(f"Errors: {summary['error_summary']}")
        """
        # Count valid/invalid
        valid = df[df["exists"] & df["error"].isna()]
        invalid = df[~(df["exists"] & df["error"].isna())]

        # Failure stage counts (from error column, now contains trace labels for missing files)
        stage_labels = [
            SubjectDataValidator.STAGE_NO_BIDS,
            SubjectDataValidator.STAGE_NO_FMRIPREP,
            SubjectDataValidator.STAGE_NO_XCPD,
            SubjectDataValidator.STAGE_NO_SEEDFC,
        ]
        failure_stages = {
            label: int((df["error"] == label).sum())
            for label in stage_labels
            if (df["error"] == label).sum() > 0
        }

        # Other errors (NaN, shape mismatch, etc.)
        other_errors = {}
        for _, row in invalid.iterrows():
            err = row["error"]
            if err and err not in stage_labels:
                other_errors[err] = other_errors.get(err, 0) + 1

        # Mean statistics (only from valid files; skipped for ALFF/ReHo which lack mean/std cols)
        mean_stats = {}
        if len(valid) > 0 and "mean" in valid.columns and "std" in valid.columns:
            mean_stats = {
                "mean_of_means": float(valid["mean"].mean()),
                "std_of_means": float(valid["mean"].std()),
                "mean_of_stds": float(valid["std"].mean()),
                "min_mean": float(valid["mean"].min()),
                "max_mean": float(valid["mean"].max()),
            }

        # Per-group summary
        group_summary = {}
        for group in df["group"].unique():
            group_data = df[df["group"] == group]
            group_valid = group_data[
                group_data["exists"] & group_data["error"].isna()
            ]
            group_summary[group] = {
                "total": len(group_data),
                "valid": len(group_valid),
                "invalid": len(group_data) - len(group_valid),
            }

        summary = {
            "total_count": len(df),
            "valid_count": len(valid),
            "missing_count": len(invalid),
            "error_count": len(invalid),
            "failure_stages": failure_stages,
            "other_errors": other_errors,
            "mean_stats": mean_stats,
            "group_summary": group_summary,
        }

        logger.info(
            f"Validation summary: {summary['valid_count']}/{summary['total_count']} valid, "
            f"{summary['error_count']} errors"
        )

        return summary
