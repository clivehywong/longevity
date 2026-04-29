from pathlib import Path

from neuconn_app.utils.seed_catalog import SeedCatalog, load_default_catalog


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_loading_both_files_succeeds():
    catalog = load_default_catalog()

    assert catalog.get_seeds(source="priority")
    assert catalog.get_seeds(source="custom")


def test_difumo_priority_seed_count():
    catalog = SeedCatalog(REPO_ROOT)

    difumo_priority = catalog.get_seeds(atlas="DiFuMo256", source="priority")

    assert len(difumo_priority) == 17
    assert all("DiFuMo256" in seed.valid_atlases for seed in difumo_priority)


def test_custom_roi_seeds_load():
    catalog = SeedCatalog(REPO_ROOT)

    custom_seeds = catalog.get_seeds(source="custom")

    assert len(custom_seeds) == 6
    assert {seed.atlas for seed in custom_seeds} == {"Schaefer200_Tian"}
    assert catalog.get_seed("custom:sensorimotor_L").label == "Left Sensorimotor (M1/S1)"


def test_nonexistent_atlas_returns_empty_list():
    catalog = SeedCatalog(REPO_ROOT)

    assert catalog.get_seeds(atlas="NonexistentAtlas") == []


def test_group_by_network_for_difumo():
    catalog = SeedCatalog(REPO_ROOT)

    grouped = catalog.group_by_network("DiFuMo256")

    assert "Salience" in grouped
    assert "DefaultMode" in grouped
    assert all(grouped.values())


def test_missing_files_do_not_crash():
    missing_repo_root = REPO_ROOT / "does_not_exist_for_seed_catalog_test"

    catalog = SeedCatalog(missing_repo_root)

    assert catalog.get_seeds() == []
    assert catalog.list_atlases() == []
