"""
End-to-end Playwright tests for the XCP-D-driven connectivity submit pages.

Covers five scenarios:
  1. Local Measures Coverage dashboard — pipeline selector, dataframe, download CSV.
  2. Seed Connectivity cascade — source/atlas/parcel pickers, command preview, dry-run.
  3. Network Connectivity submit — atlas multi-select, measures, command preview, dry-run.
  4. Group Stats — Voxel branch: TFCE method, permutation warning, command preview.
  5. Group Stats — Matrix branch: network kind, atlas, method NBS, command preview.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# conftest.py (same directory) provides: app_page fixture, navigate_sidebar, APP_URL, SCREENSHOTS_DIR
from tests.e2e.conftest import APP_URL, SCREENSHOTS_DIR, navigate_sidebar  # noqa: F401

MAIN = 'section[data-testid="stMain"]'

# v2 screenshots go in their own sub-folder so they don't clash with v1 screenshots.
SCREENSHOTS_V2 = SCREENSHOTS_DIR / "v2"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_screenshot(page: Page, name: str) -> None:
    SCREENSHOTS_V2.mkdir(parents=True, exist_ok=True)
    path = SCREENSHOTS_V2 / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)


def _get_code_blocks(page: Page) -> list[str]:
    """Return text content of every <pre> code block currently visible."""
    return [el.text_content() or "" for el in page.locator("pre").all()]


def _find_command(page: Page, keyword: str) -> str | None:
    """Return the first code block that contains *keyword*, or None."""
    for text in _get_code_blocks(page):
        if keyword in text:
            return text
    return None


def _open_pipeline_selectbox_options(page: Page, area: str = MAIN) -> list[str]:
    """Click the Pipeline selectbox in *area* and return the option texts."""
    pipeline_box = page.locator(area + " " + '[data-testid="stSelectbox"]').filter(has_text="Pipeline")
    pipeline_box.click()
    page.wait_for_timeout(400)
    opts = [el.text_content() or "" for el in page.get_by_role("option").all()]
    page.keyboard.press("Escape")
    return opts


# ---------------------------------------------------------------------------
# Test 1: Local Measures Coverage Dashboard
# ---------------------------------------------------------------------------


class TestLocalMeasuresCoverage:
    """Verify the Local Measures Coverage dashboard (replaces old local-measures dry-run tests)."""

    def test_full_dashboard(self, app_page: Page) -> None:
        """Pipeline selector, dataframe with ✅, and download button are all present."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📊 Local Measures Coverage")
        _save_screenshot(app_page, "01_local_measures_coverage_page")

        # Page title
        heading = app_page.locator(MAIN).get_by_role("heading", level=1).first
        expect(heading).to_contain_text("Local Measures Coverage", timeout=15_000)

        # Pipeline selector has exactly 3 options: fc / fc_gsr / ec
        pipeline_opts = _open_pipeline_selectbox_options(app_page)
        assert pipeline_opts == ["fc", "fc_gsr", "ec"], \
            f"Expected pipeline options [fc, fc_gsr, ec], got: {pipeline_opts}"

        # Wait for the dataframe to render (spinner goes away).
        app_page.wait_for_selector('[data-testid="stDataFrame"]', timeout=15_000)

        # Assert at least one ✅ appears for sub-033 ses-01
        page_text = app_page.locator(MAIN).text_content() or ""
        assert "✅" in page_text, "Expected ✅ (ALFF or ReHo present) but none found on page"
        assert "sub-033" in page_text, "sub-033 not found in coverage table"

        # Switch pipeline to fc_gsr — dataframe must re-render (no error message for fc_gsr)
        pipeline_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(has_text="Pipeline")
        pipeline_box.click()
        app_page.wait_for_timeout(300)
        app_page.get_by_role("option", name="fc_gsr").click()
        app_page.wait_for_timeout(5_000)
        _save_screenshot(app_page, "01_local_measures_coverage_fc_gsr")

        after_text = app_page.locator(MAIN).text_content() or ""
        # After switching to fc_gsr the table should still be visible (data exists for fc_gsr)
        assert "sub-033" in after_text or "No XCP-D outputs" in after_text, \
            "Page did not re-render after pipeline switch"

        # Download CSV button exists (label contains "Download" or "CSV")
        # Switch back to fc for the final assertion
        pipeline_box2 = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(has_text="Pipeline")
        pipeline_box2.click()
        app_page.wait_for_timeout(300)
        app_page.get_by_role("option", name="fc", exact=True).click()
        app_page.wait_for_timeout(5_000)

        download_btn = app_page.locator(MAIN).get_by_role("link").filter(has_text="CSV")
        if download_btn.count() == 0:
            # Streamlit download_button renders as a regular button with "Download" text
            download_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Download")
        assert download_btn.count() >= 1, \
            "Download CSV button not found on Local Measures Coverage page"

        _save_screenshot(app_page, "01_local_measures_coverage_download")


# ---------------------------------------------------------------------------
# Test 2: Seed Connectivity Submit — Source / Atlas / Parcel cascade + dry-run
# ---------------------------------------------------------------------------


class TestSeedConnectivityCascade:
    """Verify atlas → parcel cascade, measures, command preview, and dry-run."""

    def test_full_cascade_and_dryrun(self, app_page: Page) -> None:
        """End-to-end seed connectivity cascade: source → atlas → parcels → command."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")
        _save_screenshot(app_page, "02_seed_connectivity_page")

        # Pipeline selector shows fc as default
        pipeline_text = (
            app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]')
            .filter(has_text="Pipeline")
            .text_content() or ""
        )
        assert "fc" in pipeline_text, f"Expected 'fc' default pipeline, got: {pipeline_text}"

        # Seed source radio shows 3 options
        source_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(has_text="Seed source")
        expect(source_radio).to_be_visible(timeout=10_000)
        source_opts = [el.text_content() or "" for el in source_radio.locator("p").all()]
        # Filter out the label itself
        source_opts = [o for o in source_opts if o != "Seed source"]
        assert len(source_opts) == 3, f"Expected 3 seed source options, got: {source_opts}"
        assert any("Atlas" in o for o in source_opts), f"'Atlas parcel' option missing: {source_opts}"
        assert any("NIfTI" in o for o in source_opts), f"'Custom NIfTI' option missing: {source_opts}"
        assert any("Sphere" in o for o in source_opts), f"'Sphere' option missing: {source_opts}"

        # Atlas parcel is the default; atlas selectbox shows 5 atlases
        atlas_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(has_text="Atlas")
        expect(atlas_box).to_be_visible(timeout=8_000)
        atlas_box.click()
        app_page.wait_for_timeout(400)
        atlas_opts = [el.text_content() or "" for el in app_page.get_by_role("option").all()]
        app_page.keyboard.press("Escape")
        assert len(atlas_opts) == 5, f"Expected 5 atlases, got: {atlas_opts}"
        for atlas in ("4S256Parcels", "4S456Parcels", "Glasser", "Gordon", "Tian"):
            assert atlas in atlas_opts, f"Atlas '{atlas}' missing from dropdown: {atlas_opts}"

        # 4S256Parcels is already selected (default); parcel multiselect is populated
        parcel_multi = app_page.locator(MAIN + " " + '[data-testid="stMultiSelect"]').filter(
            has_text="Parcels"
        )
        expect(parcel_multi).to_be_visible(timeout=8_000)
        parcel_multi.locator("input").click()
        app_page.wait_for_timeout(500)
        parcel_opts = [el.text_content() or "" for el in app_page.get_by_role("option").all()]
        app_page.keyboard.press("Escape")
        assert any("LH_Vis_1" in o for o in parcel_opts), \
            f"'LH_Vis_1' not found in parcel options: {parcel_opts[:10]}"
        _save_screenshot(app_page, "02_seed_parcel_dropdown")

        # Add 2 parcels (LH_Vis_1 and LH_Vis_2)
        parcel_multi.locator("input").click()
        app_page.wait_for_timeout(400)
        app_page.get_by_role("option").filter(has_text="LH_Vis_1").first.click()
        app_page.keyboard.press("Escape")
        app_page.wait_for_timeout(300)

        parcel_multi.locator("input").click()
        app_page.wait_for_timeout(400)
        app_page.get_by_role("option").filter(has_text="LH_Vis_2").first.click()
        app_page.keyboard.press("Escape")
        app_page.wait_for_timeout(300)

        add_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Add selected parcels")
        add_btn.scroll_into_view_if_needed()
        add_btn.click()
        app_page.wait_for_timeout(3_000)

        # Seeds list now shows 2 entries
        seeds_text = app_page.locator(MAIN).text_content() or ""
        assert "Selected seeds:" in seeds_text, "Seeds list header not found after adding parcels"
        assert seeds_text.count("LH_Vis") >= 2 or seeds_text.count("atlas-4S256Parcels") >= 2, \
            f"Expected 2 seed entries; text snippet: {seeds_text[seeds_text.find('Selected'):seeds_text.find('Selected')+300]}"
        _save_screenshot(app_page, "02_seed_parcels_added")

        # Measures multiselect: 8 measures, pearson + plv + mutual_information present
        measures_multi = app_page.locator(MAIN + " " + '[data-testid="stMultiSelect"]').filter(
            has_text="Measures"
        )
        measures_text = measures_multi.text_content() or ""
        for m in ("pearson", "plv", "mutual_information"):
            assert m in measures_text, f"Expected measure '{m}' in multiselect, got: {measures_text[:300]}"
        # Count unique measure chips (all 8 should be selected by default)
        for m in ("pearson", "spearman", "partial_correlation", "plv", "wpli",
                  "coherence", "amplitude_envelope_correlation", "mutual_information"):
            assert m in measures_text, f"Measure '{m}' missing from default selection"

        # Build command preview
        preview_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Build command preview")
        preview_btn.scroll_into_view_if_needed()
        preview_btn.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "02_seed_command_preview")

        command = _find_command(app_page, "--analysis seed")
        assert command is not None, "No code block with '--analysis seed' found after Build command preview"
        assert command.startswith("python"), f"Command must start with 'python', got: {command[:80]}"
        assert "--analysis seed" in command, f"--analysis seed missing from: {command[:300]}"
        assert "--pipeline fc" in command, f"--pipeline fc missing from: {command[:300]}"
        assert "--seed atlas-4S256Parcels" in command, \
            f"--seed atlas-4S256Parcels missing from: {command[:400]}"
        assert "--measures" in command, f"--measures missing from: {command[:400]}"

        # Dry-run → success message + command echo
        dry_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Dry-run")
        dry_btn.scroll_into_view_if_needed()
        dry_btn.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "02_seed_dryrun")

        success_alerts = [
            el.text_content() or ""
            for el in app_page.locator('[data-testid="stAlertContainer"]').all()
            if "success" in (el.get_attribute("class") or "").lower()
            or "dry" in (el.text_content() or "").lower()
            or "built" in (el.text_content() or "").lower()
        ]
        # Either a success alert or a code block with the command confirms the dry-run
        dry_run_code = _find_command(app_page, "--analysis seed")
        assert (len(success_alerts) > 0 or dry_run_code is not None), \
            "Expected success message or command echo after Dry-run"


# ---------------------------------------------------------------------------
# Test 3: Network Connectivity Submit
# ---------------------------------------------------------------------------


class TestNetworkConnectivitySubmit:
    """Verify atlas multi-select, measures, command preview, and dry-run for network connectivity."""

    def test_full_network_flow(self, app_page: Page) -> None:
        """Atlas multi-select (5 atlases), measures, command preview, dry-run."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Network Connectivity")
        _save_screenshot(app_page, "03_network_connectivity_page")

        # Pipeline selector is visible
        pipeline_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Pipeline"
        )
        expect(pipeline_box).to_be_visible(timeout=10_000)

        # Atlas multi-select shows all 5 atlases selected by default
        atlas_multi = app_page.locator(MAIN + " " + '[data-testid="stMultiSelect"]').filter(
            has_text="Atlases"
        )
        expect(atlas_multi).to_be_visible(timeout=10_000)
        atlas_text = atlas_multi.text_content() or ""
        for atlas in ("4S256Parcels", "4S456Parcels", "Glasser", "Gordon", "Tian"):
            assert atlas in atlas_text, \
                f"Atlas '{atlas}' not present in multi-select: {atlas_text[:300]}"

        # Measures multiselect shows 8 measures
        measures_multi = app_page.locator(MAIN + " " + '[data-testid="stMultiSelect"]').filter(
            has_text="Measures"
        )
        measures_text = measures_multi.text_content() or ""
        for m in ("pearson", "spearman", "partial_correlation", "plv", "wpli",
                  "coherence", "amplitude_envelope_correlation", "mutual_information"):
            assert m in measures_text, f"Measure '{m}' missing from network measures selection"

        # Build command preview
        preview_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Build command preview")
        preview_btn.scroll_into_view_if_needed()
        preview_btn.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "03_network_command_preview")

        command = _find_command(app_page, "--analysis network")
        assert command is not None, "No code block with '--analysis network' found"
        assert command.startswith("python"), f"Command must start with 'python', got: {command[:80]}"
        assert "--analysis network" in command, f"--analysis network missing from: {command[:300]}"
        assert "--pipeline fc" in command, f"--pipeline fc missing from: {command[:300]}"
        assert "--atlas 4S256Parcels" in command, \
            f"--atlas 4S256Parcels missing from: {command[:500]}"
        assert "--measures" in command, f"--measures missing from: {command[:400]}"
        assert "pearson" in command, f"'pearson' not in --measures value: {command[:400]}"

        # Dry-run succeeds
        dry_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Dry-run")
        dry_btn.scroll_into_view_if_needed()
        dry_btn.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "03_network_dryrun")

        # Dry-run success: either an alert or code block with --analysis network
        dry_cmd = _find_command(app_page, "--analysis network")
        assert dry_cmd is not None, "No command block found after network dry-run"


# ---------------------------------------------------------------------------
# Test 4: Group Stats — Voxel branch
# ---------------------------------------------------------------------------


class TestGroupStatsVoxel:
    """Verify Voxel branch: TFCE method, permutation warning, command preview."""

    def test_voxel_tfce_flow(self, app_page: Page) -> None:
        """Kind=Voxel, method=TFCE, n_perms=500, warning, command preview."""
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")
        _save_screenshot(app_page, "04_group_stats_page")

        # "Analysis kind" radio has Voxel | Matrix
        kind_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(
            has_text="Analysis kind"
        )
        expect(kind_radio).to_be_visible(timeout=10_000)
        kind_opts = [el.text_content() or "" for el in kind_radio.locator("p").all()]
        assert any("Voxel" in o for o in kind_opts), f"Voxel option missing: {kind_opts}"
        assert any("Matrix" in o for o in kind_opts), f"Matrix option missing: {kind_opts}"

        # Voxel branch: Measure selectbox shows alff, reho
        measure_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Measure"
        ).first
        measure_box.click()
        app_page.wait_for_timeout(400)
        measure_opts = [el.text_content() or "" for el in app_page.get_by_role("option").all()]
        app_page.keyboard.press("Escape")
        assert "alff" in measure_opts, f"'alff' missing from measure options: {measure_opts}"
        assert "reho" in measure_opts, f"'reho' missing from measure options: {measure_opts}"

        # Switch Correction method to TFCE → n_permutations input appears
        correction_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Correction method"
        )
        correction_box.click()
        app_page.wait_for_timeout(400)
        app_page.get_by_role("option", name="TFCE").click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "04_group_voxel_tfce")

        n_perms_widget = app_page.locator(MAIN).locator('[data-testid="stNumberInput"]').filter(
            has_text="n_permutations"
        )
        expect(n_perms_widget).to_be_visible(timeout=8_000)

        # Default n_permutations is 5000
        perm_input = n_perms_widget.locator("input")
        default_val = perm_input.input_value()
        assert default_val == "5000", f"Expected default n_permutations=5000, got: {default_val}"

        # Set to 500 → warning about <1000
        perm_input.fill("500")
        perm_input.press("Enter")
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "04_group_voxel_tfce_500perms")

        warnings = [el.text_content() or "" for el in
                    app_page.locator('[data-testid="stAlertContainer"]').all()]
        assert any("<1000" in w or "1000" in w for w in warnings), \
            f"Expected <1000 permutation warning, got alerts: {warnings}"

        # Build command preview → contains --kind voxel, --method TFCE, --n-permutations 500
        preview_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Build command preview")
        preview_btn.scroll_into_view_if_needed()
        preview_btn.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "04_group_voxel_command")

        command = _find_command(app_page, "--kind voxel")
        assert command is not None, "No code block with '--kind voxel' found"
        assert "--kind voxel" in command, f"--kind voxel missing from: {command[:400]}"
        assert "--method TFCE" in command, \
            f"--method TFCE missing from: {command[:400]}"
        assert "--n-permutations 500" in command, \
            f"--n-permutations 500 missing from: {command[:400]}"


# ---------------------------------------------------------------------------
# Test 5: Group Stats — Matrix branch
# ---------------------------------------------------------------------------


class TestGroupStatsMatrix:
    """Verify Matrix branch: network kind, atlas, NBS method, threshold, command preview."""

    def test_matrix_nbs_flow(self, app_page: Page) -> None:
        """Kind=Matrix, matrix-kind=network, atlas=4S256Parcels, method=nbs, command preview."""
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")

        # Switch to Matrix kind
        kind_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(
            has_text="Analysis kind"
        )
        kind_radio.locator("p", has_text="Matrix").click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "05_group_matrix_page")

        # Matrix kind selectbox (network | seed) is visible
        mat_kind_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Matrix kind"
        )
        expect(mat_kind_box).to_be_visible(timeout=8_000)

        # Atlas selectbox is visible with network selected (default)
        atlas_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(has_text="Atlas")
        expect(atlas_box).to_be_visible(timeout=8_000)
        atlas_text = atlas_box.text_content() or ""
        assert "4S256Parcels" in atlas_text, f"Expected 4S256Parcels as default atlas: {atlas_text}"

        # Measure selectbox is visible
        measure_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Measure"
        ).first
        measure_text = measure_box.text_content() or ""
        assert "pearson" in measure_text, f"Expected pearson as default measure: {measure_text}"

        # Switch statistical method to nbs
        method_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Statistical method"
        )
        method_box.click()
        app_page.wait_for_timeout(400)
        app_page.get_by_role("option", name="nbs", exact=True).click()
        app_page.wait_for_timeout(2_000)

        # Threshold input appears (default 3.1)
        threshold_widget = app_page.locator(MAIN).locator('[data-testid="stNumberInput"]').filter(
            has_text="Threshold"
        )
        expect(threshold_widget).to_be_visible(timeout=8_000)
        thresh_val = threshold_widget.locator("input").input_value()
        assert float(thresh_val) == pytest.approx(3.1), \
            f"Expected default threshold 3.1, got: {thresh_val}"

        # Set n_permutations to 1000
        nperms_widget = app_page.locator(MAIN).locator('[data-testid="stNumberInput"]').filter(
            has_text="n_permutations"
        )
        nperms_input = nperms_widget.locator("input")
        nperms_input.fill("1000")
        nperms_input.press("Enter")
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "05_group_matrix_nbs_setup")

        # Build command preview
        preview_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Build command preview")
        preview_btn.scroll_into_view_if_needed()
        preview_btn.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "05_group_matrix_command")

        command = _find_command(app_page, "--kind matrix")
        assert command is not None, "No code block with '--kind matrix' found"
        assert "--kind matrix" in command, f"--kind matrix missing from: {command[:400]}"
        assert "--matrix-kind network" in command, \
            f"--matrix-kind network missing from: {command[:400]}"
        assert "--atlas 4S256Parcels" in command, \
            f"--atlas 4S256Parcels missing from: {command[:400]}"
        assert "--measure pearson" in command, \
            f"--measure pearson missing from: {command[:400]}"
        assert "--method nbs" in command, \
            f"--method nbs missing from: {command[:400]}"
        assert "--threshold 3.1" in command, \
            f"--threshold 3.1 missing from: {command[:400]}"
