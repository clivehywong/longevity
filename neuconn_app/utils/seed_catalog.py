"""
Unified seed catalog for connectivity UI selections.

This module merges the project's priority MNI sphere seeds, custom ROI
definitions, and generic atlas parcel seeds behind a single Streamlit-friendly
API.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


LOGGER = logging.getLogger(__name__)

PRIORITY_CONFIG = Path(".github/connectivity_config.yaml")
ROI_CONFIG = Path("neuconn_app/roi_config.json")

ATLAS_DISPLAY_NAMES = {
    "Schaefer2018_200Parcels_7Networks_Tian_S2": "Schaefer200_Tian",
}


@dataclass
class Seed:
    id: str
    label: str
    source: str
    valid_atlases: List[str]
    coordinates_mni: Optional[List[float]] = None
    radius_mm: Optional[float] = None
    atlas: Optional[str] = None
    parcel_index: Optional[int] = None
    networks: Optional[List[str]] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SeedCatalog:
    """Merged catalog of all seed definitions available to the Streamlit UI."""

    def __init__(self, repo_root: Path):
        self.repo_root = Path(repo_root).expanduser().resolve()
        self._seeds = self._load_all_seeds()
        self._seed_by_id = {seed.id: seed for seed in self._seeds}

    def list_atlases(self) -> List[str]:
        """Return all atlases that have at least one seed."""
        atlases = {atlas for seed in self._seeds for atlas in seed.valid_atlases}
        return sorted(atlases)

    def get_seeds(
        self,
        atlas: Optional[str] = None,
        source: Optional[str] = None,
        network: Optional[str] = None,
    ) -> List[Seed]:
        """Get seeds, optionally filtered by atlas/source/network."""
        seeds = self._seeds
        if atlas is not None:
            seeds = [seed for seed in seeds if atlas in seed.valid_atlases]
        if source is not None:
            seeds = [seed for seed in seeds if seed.source == source]
        if network is not None:
            seeds = [
                seed
                for seed in seeds
                if network in (seed.networks or [])
                or network == _metadata_network(seed.metadata)
            ]
        return list(seeds)

    def get_seed(self, seed_id: str) -> Optional[Seed]:
        """Look up a seed by ID."""
        return self._seed_by_id.get(seed_id)

    def group_by_network(self, atlas: str) -> Dict[str, List[Seed]]:
        """Return {network_name: [seeds]} for an atlas (for grouped multiselect UI)."""
        grouped: Dict[str, List[Seed]] = {}
        for seed in self.get_seeds(atlas=atlas):
            networks = seed.networks or [_metadata_network(seed.metadata)] or ["Unassigned"]
            for network in networks:
                grouped.setdefault(network, []).append(seed)
        return dict(sorted(grouped.items()))

    def _load_all_seeds(self) -> List[Seed]:
        seeds: List[Seed] = []
        priority_config = self._load_priority_config()
        seeds.extend(self._priority_seeds(priority_config))
        seeds.extend(self._custom_roi_seeds())
        seeds.extend(self._atlas_parcel_seeds(priority_config))
        return seeds

    def _load_priority_config(self) -> Dict[str, Any]:
        config_path = self.repo_root / PRIORITY_CONFIG
        if not config_path.exists():
            LOGGER.warning("Priority seed config not found: %s", config_path)
            return {}

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as exc:
            LOGGER.warning("Failed to read priority seed config %s: %s", config_path, exc)
            return {}

    def _priority_seeds(self, config: Dict[str, Any]) -> List[Seed]:
        loaded: List[Seed] = []
        for seed_id, seed_config in (config.get("seeds") or {}).items():
            coordinates = seed_config.get("coordinates_mni")
            loaded.append(
                Seed(
                    id=str(seed_id),
                    label=seed_config.get("region") or str(seed_id).replace("_", " "),
                    source="priority",
                    valid_atlases=list(seed_config.get("valid_atlases") or []),
                    coordinates_mni=_float_list(coordinates) if coordinates else None,
                    radius_mm=_optional_float(seed_config.get("radius_mm")),
                    networks=list(seed_config.get("networks") or []),
                    description=seed_config.get("description"),
                    metadata={
                        key: value
                        for key, value in seed_config.items()
                        if key
                        not in {
                            "region",
                            "description",
                            "coordinates_mni",
                            "radius_mm",
                            "valid_atlases",
                            "networks",
                        }
                    },
                )
            )
        return loaded

    def _custom_roi_seeds(self) -> List[Seed]:
        config_path = self.repo_root / ROI_CONFIG
        if not config_path.exists():
            LOGGER.warning("Custom ROI config not found: %s", config_path)
            return []

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                roi_config = json.load(f)
        except Exception as exc:
            LOGGER.warning("Failed to read custom ROI config %s: %s", config_path, exc)
            return []

        default_atlas = (roi_config.get("atlases") or {}).get("combined")
        loaded: List[Seed] = []
        for roi in roi_config.get("rois") or []:
            if not roi.get("use_as_seed", False):
                continue

            canonical_atlas = roi.get("atlas") or default_atlas
            display_atlas = normalize_atlas_name(canonical_atlas) if canonical_atlas else None
            roi_type = roi.get("type")
            networks = []
            if roi.get("network_filter"):
                networks.append(str(roi["network_filter"]))

            metadata = dict(roi)
            if canonical_atlas:
                metadata["canonical_atlas"] = canonical_atlas
            if display_atlas:
                metadata["display_atlas"] = display_atlas

            loaded.append(
                Seed(
                    id=f"custom:{roi.get('id')}",
                    label=roi.get("label") or str(roi.get("id")),
                    source="custom",
                    valid_atlases=[display_atlas] if display_atlas else [],
                    coordinates_mni=_float_list(roi.get("mni_coords"))
                    if roi.get("mni_coords")
                    else None,
                    radius_mm=_optional_float(roi.get("radius_mm")),
                    atlas=display_atlas,
                    networks=networks or None,
                    description=roi.get("description"),
                    metadata=metadata,
                )
            )
        return loaded

    def _atlas_parcel_seeds(self, config: Dict[str, Any]) -> List[Seed]:
        """Create generic seed entries for atlas-native parcel-index selections."""
        loaded: List[Seed] = []
        schaefer400 = (config.get("atlases") or {}).get("Schaefer400")
        if not schaefer400:
            return loaded

        n_rois = int(schaefer400.get("n_rois") or 0)
        for parcel_index in range(1, n_rois + 1):
            loaded.append(
                Seed(
                    id=f"atlas_parcel:Schaefer400:{parcel_index}",
                    label=f"Schaefer400 Parcel {parcel_index}",
                    source="atlas_parcel",
                    valid_atlases=["Schaefer400"],
                    atlas="Schaefer400",
                    parcel_index=parcel_index,
                    networks=["Atlas parcel"],
                    description="Atlas-native Schaefer400 parcel seed",
                    metadata={"atlas_config": schaefer400},
                )
            )
        return loaded


def normalize_atlas_name(atlas_name: Optional[str]) -> str:
    """Map long atlas identifiers to UI-friendly canonical names."""
    if not atlas_name:
        return ""
    return ATLAS_DISPLAY_NAMES.get(atlas_name, atlas_name)


def load_default_catalog() -> SeedCatalog:
    """Load using the project's standard config paths."""
    return SeedCatalog(Path(__file__).resolve().parents[2])


def _float_list(values: Any) -> List[float]:
    return [float(value) for value in values]


def _optional_float(value: Any) -> Optional[float]:
    return float(value) if value is not None else None


def _metadata_network(metadata: Optional[Dict[str, Any]]) -> str:
    if not metadata:
        return "Unassigned"
    return str(metadata.get("network_filter") or metadata.get("network") or "Unassigned")


def _print_cli_summary(catalog: SeedCatalog) -> None:
    for atlas in catalog.list_atlases():
        print(f"\n{atlas}")
        print("-" * len(atlas))
        by_source: Dict[str, List[Seed]] = {}
        for seed in catalog.get_seeds(atlas=atlas):
            by_source.setdefault(seed.source, []).append(seed)
        for source, seeds in sorted(by_source.items()):
            print(f"  {source}: {len(seeds)} seeds")
            for seed in seeds[:10]:
                network = ", ".join(seed.networks or ["Unassigned"])
                print(f"    - {seed.id}: {seed.label} [{network}]")
            if len(seeds) > 10:
                print(f"    ... {len(seeds) - 10} more")


if __name__ == "__main__":
    _print_cli_summary(load_default_catalog())
