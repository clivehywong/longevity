"""XCP-D output discovery utility.

Discovers outputs produced by XCP-D under::

    <bids_root>/derivatives/preprocessing/xcpd/<pipeline>/sub-XX/ses-YY/func/

Supported pipelines: fc, fc_gsr, ec.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pandas as pd

KNOWN_ATLASES = ["4S256Parcels", "4S456Parcels", "Glasser", "Gordon", "Tian"]
KNOWN_PIPELINES = ["fc", "fc_gsr", "ec"]

XCPD_SPACE = "MNI152NLin6Asym"


def _first_match(directory: Path, pattern: str) -> Optional[Path]:
    """Return the first file matching *pattern* in *directory*, or None."""
    matches = sorted(directory.glob(pattern))
    return matches[0] if matches else None


def _atlas_dict(func_dir: Path, stat: str, suffix: str) -> dict[str, Path]:
    """Build atlas -> Path dict for a given stat/suffix combination."""
    result: dict[str, Path] = {}
    for atlas in KNOWN_ATLASES:
        p = _first_match(
            func_dir,
            f"*_space-{XCPD_SPACE}_atlas-{atlas}_stat-{stat}_{suffix}.tsv",
        )
        if p is not None:
            result[atlas] = p
    return result


@dataclass
class XcpdOutputs:
    """All discovered XCP-D outputs for a single (subject, session, pipeline)."""

    subject: str
    session: str
    pipeline: str
    func_dir: Path
    figures_dir: Path

    alff_map: Optional[Path]
    reho_map: Optional[Path]
    denoised_bold: Optional[Path]
    denoised_smoothed_bold: Optional[Path]

    motion_tsv: Optional[Path]
    outliers_tsv: Optional[Path]
    design_tsv: Optional[Path]

    # atlas-keyed dicts
    alff_parcel: dict[str, Path] = field(default_factory=dict)
    reho_parcel: dict[str, Path] = field(default_factory=dict)
    coverage_parcel: dict[str, Path] = field(default_factory=dict)
    mean_timeseries: dict[str, Path] = field(default_factory=dict)
    pearson_relmat: dict[str, Path] = field(default_factory=dict)

    def has_local_measures(self) -> bool:
        """Return True if both alff_map and reho_map exist."""
        return self.alff_map is not None and self.reho_map is not None

    def list_atlases(self) -> list[str]:
        """Return sorted list of atlases for which mean_timeseries is available."""
        return sorted(self.mean_timeseries.keys())

    def parcel_labels(self, atlas: str) -> list[str]:
        """Return parcel labels by parsing the TSV header for *atlas*.

        Raises KeyError if the atlas is not available.
        """
        tsv = self.mean_timeseries.get(atlas)
        if tsv is None:
            raise KeyError(f"Atlas '{atlas}' not found in mean_timeseries for "
                           f"{self.subject}/{self.session}/{self.pipeline}")
        with tsv.open() as fh:
            header = fh.readline().rstrip("\n")
        return header.split("\t")


class XcpdDiscovery:
    """Discover XCP-D outputs under a BIDS project root."""

    def __init__(self, bids_root: Path, pipeline: str = "fc") -> None:
        self.bids_root = Path(bids_root)
        self.default_pipeline = pipeline
        self._xcpd_root = self.bids_root / "derivatives" / "preprocessing" / "xcpd"

    # ------------------------------------------------------------------
    # Listing helpers
    # ------------------------------------------------------------------

    def list_pipelines(self) -> list[str]:
        """Return pipeline names that exist on disk."""
        if not self._xcpd_root.exists():
            return []
        return sorted(
            d.name
            for d in self._xcpd_root.iterdir()
            if d.is_dir() and d.name in KNOWN_PIPELINES
        )

    def list_subjects(self, pipeline: str | None = None) -> list[str]:
        """Return subject IDs available in *pipeline*."""
        pl = pipeline or self.default_pipeline
        pl_dir = self._xcpd_root / pl
        if not pl_dir.exists():
            return []
        return sorted(
            d.name
            for d in pl_dir.iterdir()
            if d.is_dir() and d.name.startswith("sub-")
        )

    def list_sessions(self, subject: str, pipeline: str | None = None) -> list[str]:
        """Return session IDs available for *subject* in *pipeline*."""
        pl = pipeline or self.default_pipeline
        sub_dir = self._xcpd_root / pl / subject
        if not sub_dir.exists():
            return []
        return sorted(
            d.name
            for d in sub_dir.iterdir()
            if d.is_dir() and d.name.startswith("ses-")
        )

    # ------------------------------------------------------------------
    # Core discovery
    # ------------------------------------------------------------------

    def get(
        self,
        subject: str,
        session: str,
        pipeline: str | None = None,
    ) -> XcpdOutputs:
        """Discover all XCP-D outputs for *(subject, session, pipeline)*.

        Returns an :class:`XcpdOutputs` even if the directory does not exist;
        all optional fields will be ``None`` in that case.
        """
        pl = pipeline or self.default_pipeline
        ses_dir = self._xcpd_root / pl / subject / session
        func_dir = ses_dir / "func"
        figures_dir = ses_dir / "figures"

        def _find(pattern: str) -> Optional[Path]:
            if not func_dir.exists():
                return None
            return _first_match(func_dir, pattern)

        def _atlas_d(stat: str, suffix: str) -> dict[str, Path]:
            if not func_dir.exists():
                return {}
            return _atlas_dict(func_dir, stat, suffix)

        return XcpdOutputs(
            subject=subject,
            session=session,
            pipeline=pl,
            func_dir=func_dir,
            figures_dir=figures_dir,
            alff_map=_find(f"*_space-{XCPD_SPACE}_res-2_stat-alff_boldmap.nii.gz"),
            reho_map=_find(f"*_space-{XCPD_SPACE}_res-2_stat-reho_boldmap.nii.gz"),
            denoised_bold=_find(
                f"*_space-{XCPD_SPACE}_res-2_desc-denoised_bold.nii.gz"
            ),
            denoised_smoothed_bold=_find(
                f"*_space-{XCPD_SPACE}_res-2_desc-denoisedSmoothed_bold.nii.gz"
            ),
            motion_tsv=_find("*_task-rest_motion.tsv"),
            outliers_tsv=_find("*_task-rest_outliers.tsv"),
            design_tsv=_find("*_task-rest_desc-preproc_design.tsv"),
            alff_parcel=_atlas_d("alff", "bold"),
            reho_parcel=_atlas_d("reho", "bold"),
            coverage_parcel=_atlas_d("coverage", "bold"),
            mean_timeseries=_atlas_d("mean", "timeseries"),
            pearson_relmat=_atlas_d("pearsoncorrelation", "relmat"),
        )

    # ------------------------------------------------------------------
    # Coverage table
    # ------------------------------------------------------------------

    def coverage_table(self, pipeline: str | None = None) -> pd.DataFrame:
        """Return a DataFrame summarising output availability.

        Rows are indexed by (subject, session).
        Columns:

        * ``alff_map`` – bool
        * ``reho_map`` – bool
        * ``denoised`` – bool
        * ``motion_tsv`` – bool
        * ``atlases_present`` – list[str] (atlases with mean_timeseries)
        """
        pl = pipeline or self.default_pipeline
        records = []
        for sub in self.list_subjects(pl):
            for ses in self.list_sessions(sub, pl):
                out = self.get(sub, ses, pl)
                records.append(
                    {
                        "subject": sub,
                        "session": ses,
                        "alff_map": out.alff_map is not None,
                        "reho_map": out.reho_map is not None,
                        "denoised": out.denoised_bold is not None,
                        "motion_tsv": out.motion_tsv is not None,
                        "atlases_present": out.list_atlases(),
                    }
                )
        return pd.DataFrame(records).set_index(["subject", "session"])
