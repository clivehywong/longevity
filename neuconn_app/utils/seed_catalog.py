"""
Unified seed catalog driven by XCP-D atlas parcels, custom NIfTI ROIs,
and on-demand spheres-from-coordinates.

Sources:
  xcpd_atlas_parcel  — every parcel in each XCP-D atlas discovered from probe-subject TSVs
  custom_nifti_roi   — NIfTI masks listed in neuconn_app/roi_config.json
  sphere             — generated on demand via Seed.sphere() / SeedCatalog.add_sphere()
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seed dataclass
# ---------------------------------------------------------------------------

@dataclass
class Seed:
    id: str
    name: str
    source: Literal["xcpd_atlas_parcel", "custom_nifti_roi", "sphere"]
    atlas: str | None = None
    parcel_index: int | None = None
    parcel_label: str | None = None
    network: str | None = None
    nifti_path: Path | None = None
    coords_mm: tuple[float, float, float] | None = None
    radius_mm: float | None = None

    @staticmethod
    def sphere(name: str, x: float, y: float, z: float, radius_mm: float = 6.0) -> "Seed":
        """Factory for a sphere seed at MNI coordinates."""
        sid = (
            f"sphere-{name.replace(' ', '_')}"
            f"_x{int(x)}_y{int(y)}_z{int(z)}_r{int(radius_mm)}"
        )
        return Seed(
            id=sid,
            name=name,
            source="sphere",
            coords_mm=(float(x), float(y), float(z)),
            radius_mm=float(radius_mm),
        )


# ---------------------------------------------------------------------------
# Network inference helpers
# ---------------------------------------------------------------------------

def _infer_network(atlas: str, label: str) -> str | None:
    """
    Best-effort network name from parcel label.

    4S{N}Parcels: (LH|RH)_<Network>_<n>  →  <Network>
                  <Struct>_Region<n>       →  <Struct>
    Gordon:       {L|R}_{Network}_{n}     →  <Network>
    Tian:         <Structure>-{...}        →  <Structure>  (first dash-segment)
    Glasser:      no network in label     →  None
    """
    if atlas.startswith("4S") and atlas.endswith("Parcels"):
        m = re.match(r"^(?:LH|RH)_([A-Za-z]+[A-Za-z0-9]*)_\d+$", label)
        if m:
            return m.group(1)
        m2 = re.match(r"^([A-Za-z]+)_Region\d+$", label)
        if m2:
            return m2.group(1)
        return None
    if atlas == "Gordon":
        m = re.match(r"^[LR]_([A-Za-z]+)_\d+$", label)
        return m.group(1) if m else None
    if atlas == "Tian":
        parts = label.split("-")
        return parts[0] if parts else None
    # Glasser and unrecognised atlases: no reliable network mapping
    return None


def _read_tsv_columns(tsv_path: Path) -> list[str]:
    """Read the column headers from the first line of a TSV file."""
    try:
        with open(tsv_path, "r") as fh:
            return fh.readline().rstrip("\n").split("\t")
    except Exception as exc:
        LOGGER.warning("Failed to read TSV %s: %s", tsv_path, exc)
        return []


# ---------------------------------------------------------------------------
# SeedCatalog
# ---------------------------------------------------------------------------

class SeedCatalog:
    """Unified catalog of seeds for connectivity analysis."""

    def __init__(
        self,
        bids_root: Path,
        xcpd_pipeline: str = "fc",
        probe_subject: str | None = None,
        probe_session: str | None = None,
    ):
        self.bids_root = Path(bids_root).expanduser().resolve()
        self.xcpd_pipeline = xcpd_pipeline
        self._probe_subject = probe_subject
        self._probe_session = probe_session
        self._seeds: list[Seed] = []
        self._seed_by_id: dict[str, Seed] = {}
        self._load_all_seeds()

    # ------------------------------------------------------------------ #
    # Internal loading
    # ------------------------------------------------------------------ #

    def _load_all_seeds(self) -> None:
        seeds: list[Seed] = []
        seeds.extend(self._load_xcpd_atlas_parcels())
        seeds.extend(self._load_custom_nifti_rois())
        self._seeds = seeds
        self._seed_by_id = {s.id: s for s in seeds}

    def _find_probe_tsv_dir(self) -> Path | None:
        """Locate a func directory that contains atlas timeseries TSVs."""
        xcpd_root = (
            self.bids_root
            / "derivatives"
            / "preprocessing"
            / "xcpd"
            / self.xcpd_pipeline
        )
        if not xcpd_root.exists():
            return None

        # Try xcpd_outputs module (optional dependency created in a parallel branch)
        try:
            from neuconn_app.utils.xcpd_outputs import XcpdDiscovery  # type: ignore[import]

            disc = XcpdDiscovery(xcpd_root)
            tsv_dir = disc.find_timeseries_dir(
                subject=self._probe_subject, session=self._probe_session
            )
            if tsv_dir and tsv_dir.exists():
                return tsv_dir
        except Exception:
            pass

        # Fallback: glob for any subject's timeseries TSVs
        hits = sorted(xcpd_root.glob("**/func/*_atlas-*_stat-mean_timeseries.tsv"))
        if hits:
            return hits[0].parent
        return None

    def _load_xcpd_atlas_parcels(self) -> list[Seed]:
        tsv_dir = self._find_probe_tsv_dir()
        if tsv_dir is None:
            LOGGER.warning("No XCP-D timeseries TSVs found under %s", self.bids_root)
            return []

        seeds: list[Seed] = []
        for tsv_path in sorted(tsv_dir.glob("*_stat-mean_timeseries.tsv")):
            m = re.search(r"_atlas-([^_]+)_stat-mean_timeseries\.tsv$", tsv_path.name)
            if not m:
                continue
            atlas = m.group(1)
            labels = _read_tsv_columns(tsv_path)
            for idx, label in enumerate(labels):
                seed_id = f"atlas-{atlas}_parcel-{label}"
                seeds.append(
                    Seed(
                        id=seed_id,
                        name=f"{atlas}: {label}",
                        source="xcpd_atlas_parcel",
                        atlas=atlas,
                        parcel_index=idx,
                        parcel_label=label,
                        network=_infer_network(atlas, label),
                    )
                )
        return seeds

    def _load_custom_nifti_rois(self) -> list[Seed]:
        """Load NIfTI ROI entries from neuconn_app/roi_config.json."""
        config_path = self.bids_root / "neuconn_app" / "roi_config.json"
        if not config_path.exists():
            return []

        try:
            with open(config_path, "r") as fh:
                roi_config = json.load(fh)
        except Exception as exc:
            LOGGER.warning("Failed to read roi_config.json %s: %s", config_path, exc)
            return []

        seeds: list[Seed] = []
        for roi in roi_config.get("rois") or []:
            nifti_str = roi.get("nifti_path")
            if not nifti_str:
                continue
            nifti_path = Path(nifti_str)
            if not nifti_path.is_absolute():
                nifti_path = self.bids_root / nifti_path
            roi_id = roi.get("id") or nifti_path.stem
            name = roi.get("name") or roi.get("label") or roi_id
            seeds.append(
                Seed(
                    id=f"custom_nifti-{roi_id}",
                    name=name,
                    source="custom_nifti_roi",
                    nifti_path=nifti_path,
                )
            )
        return seeds

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def list_sources(self) -> list[str]:
        """Return all source types present in the catalog."""
        return sorted({s.source for s in self._seeds})

    def list_atlases(self) -> list[str]:
        """Return all atlas names that have at least one parcel seed."""
        return sorted({s.atlas for s in self._seeds if s.atlas})

    def list_networks(self, atlas: str) -> list[str]:
        """Return all inferred network names for the given atlas."""
        return sorted(
            {s.network for s in self._seeds if s.atlas == atlas and s.network is not None}
        )

    def get_seeds(
        self,
        *,
        source: str | None = None,
        atlas: str | None = None,
        network: str | None = None,
        query: str | None = None,
    ) -> list[Seed]:
        """Return seeds, optionally filtered by source / atlas / network / text query."""
        seeds = self._seeds
        if source is not None:
            seeds = [s for s in seeds if s.source == source]
        if atlas is not None:
            seeds = [s for s in seeds if s.atlas == atlas]
        if network is not None:
            seeds = [s for s in seeds if s.network == network]
        if query is not None:
            q = query.lower()
            seeds = [
                s
                for s in seeds
                if q in s.id.lower()
                or q in s.name.lower()
                or (s.parcel_label and q in s.parcel_label.lower())
            ]
        return list(seeds)

    def get_seed(self, seed_id: str) -> Seed:
        """Look up a seed by its stable ID; raises KeyError if not found."""
        try:
            return self._seed_by_id[seed_id]
        except KeyError:
            raise KeyError(f"Seed not found: {seed_id!r}")

    def add_sphere(
        self, name: str, x: float, y: float, z: float, radius_mm: float = 6.0
    ) -> Seed:
        """Create a sphere seed and register it in the catalog."""
        seed = Seed.sphere(name, x, y, z, radius_mm)
        if seed.id not in self._seed_by_id:
            self._seeds.append(seed)
            self._seed_by_id[seed.id] = seed
        return self._seed_by_id[seed.id]

    def group_by_network(self, atlas: str) -> dict[str, list[Seed]]:
        """Return {network_name: [seeds]} for the given atlas (sorted by network name)."""
        grouped: dict[str, list[Seed]] = {}
        for seed in self.get_seeds(atlas=atlas):
            key = seed.network or "unknown"
            grouped.setdefault(key, []).append(seed)
        return dict(sorted(grouped.items()))


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def load_default_catalog() -> SeedCatalog:
    """Load catalog using default project paths (bids_root = repo root)."""
    return SeedCatalog(Path(__file__).resolve().parents[2])


def _print_cli_summary(catalog: SeedCatalog) -> None:
    for atlas in catalog.list_atlases():
        seeds = catalog.get_seeds(atlas=atlas)
        networks = catalog.list_networks(atlas)
        print(f"\n{atlas}  ({len(seeds)} parcels, {len(networks)} networks)")
        print("-" * 60)
        for net in networks[:5]:
            n_seeds = len(catalog.get_seeds(atlas=atlas, network=net))
            print(f"  {net}: {n_seeds} parcels")
        if len(networks) > 5:
            print(f"  ... {len(networks) - 5} more networks")


if __name__ == "__main__":
    _print_cli_summary(load_default_catalog())
