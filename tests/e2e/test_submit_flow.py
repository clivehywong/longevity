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


def _set_selectbox_option(page: Page, label: str, option: str, area: str = MAIN) -> None:
    """Set a Streamlit selectbox by visible label and option text."""
    box = page.locator(area + " " + '[data-testid="stSelectbox"]').filter(has_text=label)
    expect(box).to_be_visible(timeout=10_000)
    box.click()
    page.wait_for_timeout(400)
    opt = page.get_by_role("option", name=option, exact=True)
    expect(opt).to_be_visible(timeout=10_000)
    opt.click()
    page.wait_for_timeout(800)


def _set_single_multiselect(page: Page, label: str, value: str, area: str = MAIN) -> None:
    """Clear a Streamlit multiselect and choose a single value."""
    box = page.locator(area + " " + '[data-testid="stMultiSelect"]').filter(has_text=label)
    expect(box).to_be_visible(timeout=10_000)

    clear_btn = box.get_by_role("button", name="Clear all")
    if clear_btn.count():
        clear_btn.click()
        page.wait_for_timeout(500)

    input_box = box.locator("input")
    input_box.click()
    input_box.fill(value)
    page.wait_for_timeout(800)

    option = page.get_by_role("option", name=value, exact=True)
    expect(option).to_be_visible(timeout=10_000)
    option.click()
    page.wait_for_timeout(800)


def _fill_number_input(page: Page, label: str, value: int | float) -> None:
    """Fill a Streamlit number input by label text."""
    widget = page.locator(MAIN + " " + '[data-testid="stNumberInput"]').filter(has_text=label)
    expect(widget).to_be_visible(timeout=10_000)
    input_box = widget.locator("input")
    input_box.click()
    input_box.press("Control+a")
    input_box.fill(str(value))
    input_box.press("Tab")
    page.wait_for_timeout(300)


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

        # "Choose analysis type:" selectbox has Voxel / Matrix / MixedDesign options
        analysis_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Choose analysis type"
        )
        expect(analysis_box).to_be_visible(timeout=10_000)
        analysis_box.click()
        app_page.wait_for_timeout(400)
        analysis_opts = [el.text_content() or "" for el in app_page.get_by_role("option").all()]
        app_page.keyboard.press("Escape")
        assert any("Voxel" in o for o in analysis_opts), f"Voxel option missing: {analysis_opts}"
        assert any("Matrix" in o for o in analysis_opts), f"Matrix option missing: {analysis_opts}"

        # Select "Voxel-level Group Stats" (default) explicitly
        analysis_box.click()
        app_page.wait_for_timeout(300)
        app_page.get_by_role("option").filter(has_text="Voxel-level").first.click()
        app_page.wait_for_timeout(2_000)

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

        # Switch to Matrix kind via "Choose analysis type:" selectbox
        analysis_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Choose analysis type"
        )
        expect(analysis_box).to_be_visible(timeout=10_000)
        analysis_box.click()
        app_page.wait_for_timeout(300)
        app_page.get_by_role("option").filter(has_text="Matrix-level").first.click()
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


# ---------------------------------------------------------------------------
# Test 6: Seed Connectivity — Pre-flight checks
# ---------------------------------------------------------------------------


class TestSeedConnectivityPreflight:
    """Verify the pre-flight check section for seed connectivity submission."""

    def test_local_preflight_passes(self, app_page: Page) -> None:
        """Local mode: brain mask and XCP-D outputs should be found (✅)."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        # Switch to Local execution mode
        run_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(
            has_text="Run on"
        )
        expect(run_radio).to_be_visible(timeout=10_000)
        run_radio.locator("p").filter(has_text="Local").click()
        app_page.wait_for_timeout(1_500)
        _save_screenshot(app_page, "06a_preflight_local_mode")

        # Pre-flight subheader present
        preflight_heading = app_page.locator(MAIN).get_by_role(
            "heading", level=3
        ).filter(has_text="Pre-flight")
        expect(preflight_heading).to_be_visible(timeout=10_000)

        # "Run pre-flight checks" button present
        preflight_btn = app_page.locator(MAIN).get_by_role("button").filter(
            has_text="pre-flight"
        )
        expect(preflight_btn).to_be_visible(timeout=8_000)

        preflight_btn.scroll_into_view_if_needed()
        preflight_btn.click()
        app_page.wait_for_timeout(8_000)  # Local I/O checks finish quickly
        _save_screenshot(app_page, "06b_preflight_local_results")

        page_text = app_page.locator(MAIN).text_content() or ""

        # Brain mask check must appear
        assert "Brain mask" in page_text, (
            f"'Brain mask' not found in pre-flight results. Page: {page_text[:600]}"
        )
        # XCP-D check must appear
        assert "XCP-D" in page_text, (
            f"'XCP-D' not found in pre-flight results. Page: {page_text[:600]}"
        )
        # At least one green tick (brain mask exists locally)
        assert "✅" in page_text, (
            f"Expected ✅ for brain mask but none found. Page: {page_text[:600]}"
        )

    def test_hpc_preflight_section_and_results(self, app_page: Page) -> None:
        """HPC mode: pre-flight section is visible; clicking it renders check results."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        # Switch to HPC mode
        run_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(
            has_text="Run on"
        )
        expect(run_radio).to_be_visible(timeout=10_000)
        run_radio.locator("p").filter(has_text="HPC").click()
        app_page.wait_for_timeout(1_500)
        _save_screenshot(app_page, "07a_preflight_hpc_mode")

        # Pre-flight subheader present in HPC mode too
        preflight_heading = app_page.locator(MAIN).get_by_role(
            "heading", level=3
        ).filter(has_text="Pre-flight")
        expect(preflight_heading).to_be_visible(timeout=10_000)

        preflight_btn = app_page.locator(MAIN).get_by_role("button").filter(
            has_text="pre-flight"
        )
        expect(preflight_btn).to_be_visible(timeout=8_000)

        preflight_btn.scroll_into_view_if_needed()
        preflight_btn.click()
        # Allow time for SSH attempt (may succeed or fail gracefully)
        app_page.wait_for_timeout(15_000)
        _save_screenshot(app_page, "07b_preflight_hpc_results")

        page_text = app_page.locator(MAIN).text_content() or ""

        # Results rendered: at least one status icon present
        has_icon = any(icon in page_text for icon in ["✅", "❌", "⚠️"])
        assert has_icon, (
            f"Expected pre-flight result icons (✅/❌/⚠️) after HPC check. "
            f"Page snippet: {page_text[:800]}"
        )

        # HPC config check must appear regardless of connectivity
        assert "HPC" in page_text, (
            f"Expected HPC-related check names but got: {page_text[:600]}"
        )

    def test_preflight_invalidates_on_pipeline_change(self, app_page: Page) -> None:
        """Cached pre-flight results are cleared when pipeline changes."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        # Run local pre-flight on default pipeline (fc)
        run_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(
            has_text="Run on"
        )
        expect(run_radio).to_be_visible(timeout=10_000)
        run_radio.locator("p").filter(has_text="Local").click()
        app_page.wait_for_timeout(1_000)

        preflight_btn = app_page.locator(MAIN).get_by_role("button").filter(
            has_text="pre-flight"
        )
        preflight_btn.scroll_into_view_if_needed()
        preflight_btn.click()
        app_page.wait_for_timeout(8_000)
        _save_screenshot(app_page, "08a_preflight_fc_ran")

        page_text_fc = app_page.locator(MAIN).text_content() or ""
        assert "✅" in page_text_fc, "Expected ✅ after local pre-flight with fc pipeline"

        # Switch pipeline to fc_gsr → cached results should be invalidated
        pipeline_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Pipeline"
        )
        pipeline_box.click()
        app_page.wait_for_timeout(400)
        app_page.get_by_role("option", name="fc_gsr").click()
        app_page.wait_for_timeout(3_000)
        _save_screenshot(app_page, "08b_preflight_pipeline_changed")

        page_text_after = app_page.locator(MAIN).text_content() or ""
        # Either the invalidation notice or the "click to run" caption appears
        assert (
            "Settings changed" in page_text_after
            or "Click" in page_text_after
            or "Run pre-flight" in page_text_after
        ), (
            f"Expected pre-flight cache invalidation notice after pipeline change. "
            f"Page: {page_text_after[:600]}"
        )


# ---------------------------------------------------------------------------
# Test 7: Full pipeline — local submit → viewer → quality metrics
# ---------------------------------------------------------------------------

TEST_SUBJECT = "sub-033"
TEST_SESSION = "ses-01"
TEST_SEED_NAME = "E2E_DLPFC"
TEST_SEED_COORDS = (-46, 16, 32)
TEST_SEED_RADIUS = 6
TEST_SEED_ID = "sphere--46_16_32_r6"
TEST_VIEWER_SUBJECT = TEST_SUBJECT.replace("sub-", "")
TEST_VIEWER_SESSION = TEST_SESSION.replace("ses-", "")


class TestSeedFullPipeline:
    """Viewer smoke test plus full local submit → view pipeline test."""

    def test_viewer_shows_existing_zmap(self, app_page: Page) -> None:
        """Fast smoke test: existing sphere zmap is discoverable and viewable."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="🎯 Seed Connectivity Viewer")
        _save_screenshot(app_page, "09a_viewer_existing_open")

        _set_selectbox_option(app_page, "Pipeline", "fc")
        _set_selectbox_option(app_page, "Subject", TEST_VIEWER_SUBJECT)
        _set_selectbox_option(app_page, "Session", TEST_VIEWER_SESSION)
        app_page.wait_for_timeout(1_500)
        _save_screenshot(app_page, "09b_viewer_existing_selected")

        seed_selector = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Seed"
        )
        expect(seed_selector).to_be_visible(timeout=10_000)
        seed_text = seed_selector.text_content() or ""
        page_text = app_page.locator(MAIN).text_content() or ""
        assert (
            "DLPFC" in seed_text
            or "sphere" in seed_text.lower()
            or TEST_SEED_ID in page_text
        ), f"Expected computed sphere seed in selector. Got: {seed_text}"

        vox_tab = app_page.locator(MAIN).locator('[data-testid="stTab"]').filter(
            has_text="Voxel z-map"
        )
        vox_tab.click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "09c_viewer_existing_voxel")

        papaya_frame = app_page.locator('[data-testid="stIFrame"]').first
        expect(papaya_frame).to_be_visible(timeout=15_000)

        qm_expander = app_page.locator(MAIN).locator('[data-testid="stExpander"]').filter(
            has_text="Quality metrics"
        )
        expect(qm_expander).to_be_visible(timeout=8_000)
        qm_expander.locator("summary").click()
        expect(qm_expander.get_by_text("Brain mask applied", exact=False)).to_be_visible(timeout=5_000)
        expect(qm_expander.get_by_text("Mean z", exact=False)).to_be_visible(timeout=5_000)
        expect(qm_expander.get_by_text("Std z", exact=False)).to_be_visible(timeout=5_000)
        _save_screenshot(app_page, "09d_viewer_existing_quality")

    def test_submit_wait_and_view(self, app_page: Page) -> None:  # noqa: C901
        """Full E2E: sphere seed, local submit sub-033/ses-01, view zmap + QA panel."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")
        _save_screenshot(app_page, "09e_submit_page_open")

        _set_single_multiselect(app_page, "Subjects (default: all)", TEST_SUBJECT)
        _set_single_multiselect(app_page, "Sessions (default: all)", TEST_SESSION)

        seed_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(
            has_text="Seed source"
        )
        seed_radio.locator("p").filter(has_text="Sphere from coordinates").click()
        app_page.wait_for_timeout(1_000)

        sphere_name = app_page.locator(MAIN + " " + '[data-testid="stTextInput"]').filter(
            has_text="Sphere name"
        )
        expect(sphere_name).to_be_visible(timeout=10_000)
        sphere_name.locator("input").fill(TEST_SEED_NAME)
        _fill_number_input(app_page, "x (mm)", TEST_SEED_COORDS[0])
        _fill_number_input(app_page, "y (mm)", TEST_SEED_COORDS[1])
        _fill_number_input(app_page, "z (mm)", TEST_SEED_COORDS[2])
        _fill_number_input(app_page, "radius (mm)", TEST_SEED_RADIUS)

        add_sphere_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Add sphere")
        add_sphere_btn.scroll_into_view_if_needed()
        add_sphere_btn.click()
        app_page.wait_for_timeout(1_000)
        _save_screenshot(app_page, "09f_seed_added")

        seed_list_text = app_page.locator(MAIN).text_content() or ""
        assert TEST_SEED_NAME in seed_list_text, (
            f"Expected seed '{TEST_SEED_NAME}' in seed list. Page snippet: {seed_list_text[:600]}"
        )

        _set_single_multiselect(app_page, "Measures", "pearson")

        run_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(
            has_text="Run on"
        )
        run_radio.locator("p").filter(has_text="Local").click()
        app_page.wait_for_timeout(1_000)

        preflight_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="pre-flight")
        preflight_btn.scroll_into_view_if_needed()
        preflight_btn.click()
        expect(app_page.locator(MAIN)).to_contain_text("All critical checks passed", timeout=20_000)
        _save_screenshot(app_page, "09g_preflight_done")

        submit_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Run locally")
        submit_btn.scroll_into_view_if_needed()
        _save_screenshot(app_page, "09h_before_submit")
        submit_btn.click()
        expect(app_page.locator(MAIN)).to_contain_text("Completed", timeout=180_000)
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "09i_after_submit")

        navigate_sidebar(app_page, stage="Subject-Level", analysis="🎯 Seed Connectivity Viewer")
        app_page.wait_for_timeout(3_000)
        _save_screenshot(app_page, "09j_viewer_page_open")

        _set_selectbox_option(app_page, "Pipeline", "fc")
        _set_selectbox_option(app_page, "Subject", TEST_VIEWER_SUBJECT)
        _set_selectbox_option(app_page, "Session", TEST_VIEWER_SESSION)
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "09k_viewer_subject_selected")

        seed_selector = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Seed"
        )
        expect(seed_selector).to_be_visible(timeout=10_000)
        seed_text = seed_selector.text_content() or ""
        page_text = app_page.locator(MAIN).text_content() or ""
        assert (
            TEST_SEED_NAME in seed_text
            or "DLPFC" in seed_text
            or TEST_SEED_ID in page_text
        ), f"Expected computed sphere seed in selector. Got: {seed_text}"
        _save_screenshot(app_page, "09l_seed_selected")

        vox_tab = app_page.locator(MAIN).locator('[data-testid="stTab"]').filter(
            has_text="Voxel z-map"
        )
        vox_tab.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "09m_voxel_tab")

        papaya_frame = app_page.locator('[data-testid="stIFrame"]').first
        expect(papaya_frame).to_be_visible(timeout=15_000)

        qm_expander = app_page.locator(MAIN).locator('[data-testid="stExpander"]').filter(
            has_text="Quality metrics"
        )
        expect(qm_expander).to_be_visible(timeout=8_000)
        qm_expander.locator("summary").click()
        expect(qm_expander.get_by_text("Brain mask applied", exact=False)).to_be_visible(timeout=5_000)
        expect(qm_expander.get_by_text("Mean z", exact=False)).to_be_visible(timeout=5_000)
        expect(qm_expander.get_by_text("Std z", exact=False)).to_be_visible(timeout=5_000)
        _save_screenshot(app_page, "09n_quality_metrics_open")
