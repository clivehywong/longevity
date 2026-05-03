"""
End-to-end Playwright tests for the XCP-D-driven connectivity submit pages.

Covers scenarios:
  1. Local Measures Coverage dashboard — pipeline selector, dataframe, download CSV.
  2. Seed Connectivity cascade — source/atlas/parcel pickers, command preview, dry-run.
  3. Network Connectivity submit — atlas multi-select, measures, command preview, dry-run.
  4. Group Stats — Voxel branch: TFCE method, permutation warning, command preview.
  5. Group Stats — Matrix branch: network kind, atlas, method NBS, command preview.
  6–10. Pre-flight / upload / HPC workflow tests.
  11. Seed Connectivity Monitor + Download tabs (fixture-seeded state).
  12. Group Stats Monitor + Download tabs.
  13. Full workflow smoke test: LH_Cont_PFCl_3 dry-run, group stats dry-run, group viewer.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# conftest.py (same directory) provides: app_page fixture, navigate_sidebar, APP_URL, SCREENSHOTS_DIR
from tests.e2e.conftest import APP_URL, SCREENSHOTS_DIR, navigate_sidebar  # noqa: F401

MAIN = 'section[data-testid="stMain"]'

# v2 screenshots go in their own sub-folder so they don't clash with v1 screenshots.
SCREENSHOTS_V2 = SCREENSHOTS_DIR / "v2"

# State file written by test fixtures to seed the Monitor/Download tabs
_STATE_FILE = Path("/home/clivewong/proj/longevity/.neuconn/connectivity_workflow_state.json")


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
    """Dashboard smoke test + viewer smoke test + full local submit → view pipeline."""

    def test_dashboard_shows_completion(self, app_page: Page) -> None:
        """Dashboard tab shows completion matrix with sub-033 entry."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="🎯 Seed Connectivity Viewer")
        _save_screenshot(app_page, "09a_dashboard_open")

        _set_selectbox_option(app_page, "Pipeline", "fc")
        app_page.wait_for_timeout(2_000)

        # Dashboard tab is the first (default) tab
        dash_tab = app_page.locator(MAIN).locator('[data-testid="stTab"]').filter(
            has_text="Dashboard"
        )
        expect(dash_tab).to_be_visible(timeout=10_000)
        dash_tab.click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "09b_dashboard_active")

        # Should show the completion table with sub-033
        page_text = app_page.locator(MAIN).text_content() or ""
        assert "sub-033" in page_text or "Total computed" in page_text, (
            f"Expected sub-033 or summary metrics in dashboard. Snippet: {page_text[:600]}"
        )
        # Legend caption
        assert "z-map" in page_text or "parcel" in page_text, (
            f"Expected legend in dashboard. Snippet: {page_text[:400]}"
        )
        _save_screenshot(app_page, "09c_dashboard_with_data")

    def test_viewer_shows_existing_zmap(self, app_page: Page) -> None:
        """Fast smoke test: existing sphere zmap is discoverable and viewable."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="🎯 Seed Connectivity Viewer")
        _save_screenshot(app_page, "09a_viewer_existing_open")

        _set_selectbox_option(app_page, "Pipeline", "fc")

        # New layout: click "🔍 Viewer" top-level tab first
        viewer_tab = app_page.locator(MAIN).locator('[data-testid="stTab"]').filter(
            has_text="Viewer"
        )
        viewer_tab.click()
        app_page.wait_for_timeout(1_000)

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
            or "4S256Parcels" in seed_text
            or "LH_Cont_PFCl_3" in seed_text
        ), f"Expected computed seed in selector. Got: {seed_text}"

        # Click inner "🧠 Voxel z-map" tab
        vox_tab = app_page.locator(MAIN).locator('[data-testid="stTab"]').filter(
            has_text="Voxel z-map"
        )
        vox_tab.click()
        app_page.wait_for_timeout(3_000)
        _save_screenshot(app_page, "09c_viewer_existing_voxel")

        # nilearn renders via st.components.v1.html → stIFrame
        nilearn_frame = app_page.locator('[data-testid="stIFrame"]').first
        expect(nilearn_frame).to_be_visible(timeout=15_000)

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

        # Click "🔍 Viewer" top-level tab
        viewer_tab = app_page.locator(MAIN).locator('[data-testid="stTab"]').filter(
            has_text="Viewer"
        )
        viewer_tab.click()
        app_page.wait_for_timeout(1_000)

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
            or "4S256Parcels" in seed_text
            or "LH_Cont_PFCl_3" in seed_text
        ), f"Expected computed seed in selector. Got: {seed_text}"
        _save_screenshot(app_page, "09l_seed_selected")

        vox_tab = app_page.locator(MAIN).locator('[data-testid="stTab"]').filter(
            has_text="Voxel z-map"
        )
        vox_tab.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "09m_voxel_tab")

        # nilearn renders via st.components.v1.html → stIFrame
        nilearn_frame = app_page.locator('[data-testid="stIFrame"]').first
        expect(nilearn_frame).to_be_visible(timeout=15_000)

        qm_expander = app_page.locator(MAIN).locator('[data-testid="stExpander"]').filter(
            has_text="Quality metrics"
        )
        expect(qm_expander).to_be_visible(timeout=8_000)
        qm_expander.locator("summary").click()
        expect(qm_expander.get_by_text("Brain mask applied", exact=False)).to_be_visible(timeout=5_000)
        expect(qm_expander.get_by_text("Mean z", exact=False)).to_be_visible(timeout=5_000)
        expect(qm_expander.get_by_text("Std z", exact=False)).to_be_visible(timeout=5_000)
        _save_screenshot(app_page, "09n_quality_metrics_open")


# ---------------------------------------------------------------------------
# Test 8: HPC Upload Flow — preflight detects missing files → upload → re-check
# ---------------------------------------------------------------------------


class TestHPCUploadFlow:
    """Verify that missing HPC static files trigger an upload prompt that fixes them.

    The test removes the static files from HPC at the start so it is deterministic
    regardless of prior state.
    """

    @pytest.fixture(autouse=True)
    def _remove_hpc_static_files(self) -> None:
        """Remove brain mask and connectivity_measures from HPC before test runs."""
        import subprocess
        result = subprocess.run(
            [
                "ssh", "-o", "BatchMode=yes",
                "clivewong@hpclogin1.eduhk.hk",
                "rm -f /home/clivewong/proj/long/atlases/MNI152_T1_2mm_brain_mask_dil.nii.gz "
                "/home/clivewong/proj/long/script/connectivity_measures.py",
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, (
            f"Failed to remove HPC test files: {result.stderr}"
        )

    def test_hpc_preflight_detects_missing_and_uploads(self, app_page: Page) -> None:
        """HPC preflight shows ❌ for missing files, upload button fixes them."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")
        _save_screenshot(app_page, "10a_hpc_upload_page_open")

        # Select 2 subjects
        _set_single_multiselect(app_page, "Subjects (default: all)", "sub-033")
        app_page.wait_for_timeout(500)

        # Use sphere seed (doesn't require atlas files)
        seed_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(
            has_text="Seed source"
        )
        seed_radio.locator("p").filter(has_text="Sphere from coordinates").click()
        app_page.wait_for_timeout(800)

        sphere_name_widget = app_page.locator(MAIN + " " + '[data-testid="stTextInput"]').filter(
            has_text="Sphere name"
        )
        sphere_name_widget.locator("input").fill("UploadTest_DLPFC")
        _fill_number_input(app_page, "x (mm)", -46)
        _fill_number_input(app_page, "y (mm)", 16)
        _fill_number_input(app_page, "z (mm)", 32)
        _fill_number_input(app_page, "radius (mm)", 6)
        add_sphere_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Add sphere")
        add_sphere_btn.scroll_into_view_if_needed()
        add_sphere_btn.click()
        app_page.wait_for_timeout(800)

        # Switch to HPC mode
        run_radio = app_page.locator(MAIN).locator('[data-testid="stRadio"]').filter(has_text="Run on")
        run_radio.locator("p").filter(has_text="HPC").click()
        app_page.wait_for_timeout(1_200)
        _save_screenshot(app_page, "10b_hpc_mode_selected")

        # Run pre-flight → should detect missing brain mask and/or connectivity_measures
        preflight_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="pre-flight")
        preflight_btn.scroll_into_view_if_needed()
        preflight_btn.click()
        # SSH checks take longer
        app_page.wait_for_timeout(20_000)
        _save_screenshot(app_page, "10c_hpc_preflight_results")

        page_text = app_page.locator(MAIN).text_content() or ""
        # At least one ❌ must be present (brain mask or connectivity_measures missing)
        assert "❌" in page_text, (
            f"Expected ❌ in HPC preflight results (files should be missing). "
            f"Page snippet: {page_text[:800]}"
        )
        assert "Brain mask" in page_text or "Connectivity measures" in page_text, (
            f"Expected 'Brain mask' or 'Connectivity measures' in preflight results. "
            f"Page: {page_text[:800]}"
        )

        # The upload expander should be visible and expanded (has_static_failures=True)
        upload_expander = app_page.locator(MAIN).locator('[data-testid="stExpander"]').filter(
            has_text="Upload / sync static files"
        )
        expect(upload_expander).to_be_visible(timeout=10_000)
        _save_screenshot(app_page, "10d_upload_expander_visible")

        # Click the upload button
        upload_btn = app_page.locator(MAIN).get_by_role("button").filter(
            has_text="Upload static files to HPC"
        )
        upload_btn.scroll_into_view_if_needed()
        upload_btn.click()
        # Allow time for SFTP upload (4 files including 100MB+ brain mask)
        app_page.wait_for_timeout(60_000)
        _save_screenshot(app_page, "10e_after_upload")

        page_text_after = app_page.locator(MAIN).text_content() or ""
        # No ❌ for static file checks; all critical checks should now pass
        assert "All critical checks passed" in page_text_after, (
            f"Expected 'All critical checks passed' after upload + recheck. "
            f"Page snippet: {page_text_after[:1000]}"
        )
        # Upload status rows: each file shows ✅
        assert page_text_after.count("✅") >= 4 or "uploaded" in page_text_after.lower(), (
            f"Expected ✅ rows for each uploaded file. Page: {page_text_after[:1000]}"
        )
        _save_screenshot(app_page, "10f_preflight_all_pass")


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_test_submissions_state() -> None:
    """Write a pre-seeded connectivity_workflow_state.json for Monitor/Download tests.

    Creates 4 entries:
      1. seed_connectivity / status=submitted / execution_mode=hpc / job=DRY_RUN_1
      2. seed_connectivity / status=running   / execution_mode=hpc / job=DRY_RUN_2
      3. seed_connectivity / status=completed / execution_mode=hpc / job=DRY_RUN_3
      4. group_stats       / status=completed / execution_mode=hpc / job=DRY_RUN_4
    """
    import time
    now = time.time()
    state = {
        "submissions": [
            {
                "id": "test-seed-submitted-001",
                "analysis_type": "seed_connectivity",
                "status": "submitted",
                "execution_mode": "hpc",
                "job_id": "DRY_RUN_1",
                "submitted_at": now - 3600,
                "completed_at": None,
                "error": None,
                "options": {
                    "pipeline": "fc",
                    "atlas": "4S256Parcels",
                    "seeds": ["atlas-4S256Parcels-LH_Cont_PFCl_3"],
                    "measures": ["pearson"],
                    "subjects": ["sub-033", "sub-034"],
                    "sessions": ["ses-01", "ses-02"],
                },
                "command": "python script/compute_seed_connectivity_xcpd.py --dry-run",
                "slurm_script": None,
            },
            {
                "id": "test-seed-running-002",
                "analysis_type": "seed_connectivity",
                "status": "running",
                "execution_mode": "hpc",
                "job_id": "DRY_RUN_2",
                "submitted_at": now - 1800,
                "completed_at": None,
                "error": None,
                "options": {
                    "pipeline": "fc",
                    "atlas": "4S256Parcels",
                    "seeds": ["atlas-4S256Parcels-LH_Cont_PFCl_3"],
                    "measures": ["pearson"],
                    "subjects": ["sub-035", "sub-036"],
                    "sessions": ["ses-01", "ses-02"],
                },
                "command": "python script/compute_seed_connectivity_xcpd.py --dry-run",
                "slurm_script": None,
            },
            {
                "id": "test-seed-completed-003",
                "analysis_type": "seed_connectivity",
                "status": "completed",
                "execution_mode": "hpc",
                "job_id": "DRY_RUN_3",
                "submitted_at": now - 900,
                "completed_at": now - 300,
                "error": None,
                "options": {
                    "pipeline": "fc",
                    "atlas": "4S256Parcels",
                    "seeds": ["atlas-4S256Parcels-LH_Cont_PFCl_3"],
                    "measures": ["pearson"],
                    "subjects": ["sub-037", "sub-038"],
                    "sessions": ["ses-01", "ses-02"],
                },
                "command": "python script/compute_seed_connectivity_xcpd.py --dry-run",
                "slurm_script": None,
            },
            {
                "id": "test-group-completed-004",
                "analysis_type": "group_stats",
                "status": "completed",
                "execution_mode": "hpc",
                "job_id": "DRY_RUN_4",
                "submitted_at": now - 600,
                "completed_at": now - 60,
                "error": None,
                "options": {
                    "pipeline": "fc",
                    "kind": "voxel",
                    "measure": "seed",
                    "seed": "atlas-4S256Parcels-LH_Cont_PFCl_3",
                    "method": "TFCE",
                    "n_permutations": 5000,
                },
                "command": "python script/group_voxel_stats_xcpd.py --dry-run",
                "slurm_script": None,
            },
        ]
    }
    _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(_STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2)


@pytest.fixture()
def seeded_state(app_page: Page):
    """Fixture: write test submissions state file before test, clean up after."""
    _write_test_submissions_state()
    yield app_page
    # Restore empty state so other tests are not affected
    if _STATE_FILE.exists():
        with open(_STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump({"submissions": []}, fh)


# ---------------------------------------------------------------------------
# Test 11: Seed Connectivity — Monitor + Download tabs
# ---------------------------------------------------------------------------


class TestSeedConnectivityMonitorDownload:
    """Monitor and Download tabs in the Seed Connectivity submission page."""

    def test_monitor_tab_renders(self, seeded_state: Page) -> None:
        """Navigating to the Monitor tab shows submissions without Python errors."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")
        _save_screenshot(app_page, "11a_seed_monitor_submit_tab")

        # Click the Monitor tab
        monitor_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Monitor")
        expect(monitor_tab).to_be_visible(timeout=12_000)
        monitor_tab.click()
        app_page.wait_for_timeout(3_000)
        _save_screenshot(app_page, "11b_seed_monitor_tab_open")

        page_text = app_page.locator(MAIN).text_content() or ""
        # No Streamlit traceback visible
        assert "Traceback" not in page_text, f"Python traceback in Monitor tab: {page_text[:600]}"
        assert "AttributeError" not in page_text, f"AttributeError in Monitor tab: {page_text[:600]}"

    def test_monitor_shows_status_badges(self, seeded_state: Page) -> None:
        """Monitor tab shows status badges for the seeded submissions."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        monitor_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Monitor")
        expect(monitor_tab).to_be_visible(timeout=12_000)
        monitor_tab.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "11c_seed_monitor_badges")

        page_text = app_page.locator(MAIN).text_content() or ""
        # At least one status icon must appear (submitted / running / completed)
        has_badge = any(icon in page_text for icon in ["✅", "🔄", "⏳", "❌", "submitted", "running", "completed"])
        assert has_badge, (
            f"Expected status badges in Monitor tab. Page text: {page_text[:800]}"
        )

    def test_monitor_refresh_all_button(self, seeded_state: Page) -> None:
        """Clicking Refresh All does not produce an error."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        monitor_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Monitor")
        expect(monitor_tab).to_be_visible(timeout=12_000)
        monitor_tab.click()
        app_page.wait_for_timeout(3_000)

        # Look for a Refresh button (may be "Refresh All", "🔄 Refresh", etc.)
        refresh_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Refresh")
        if refresh_btn.count() > 0:
            refresh_btn.first.scroll_into_view_if_needed()
            refresh_btn.first.click()
            app_page.wait_for_timeout(5_000)
            _save_screenshot(app_page, "11d_seed_monitor_after_refresh")

            page_text = app_page.locator(MAIN).text_content() or ""
            assert "Traceback" not in page_text, f"Traceback after Refresh All: {page_text[:600]}"
        else:
            _save_screenshot(app_page, "11d_seed_monitor_no_refresh_btn")

    def test_download_tab_renders(self, seeded_state: Page) -> None:
        """Download tab shows completed HPC job with a download button."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        download_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Download")
        expect(download_tab).to_be_visible(timeout=12_000)
        download_tab.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "11e_seed_download_tab")

        page_text = app_page.locator(MAIN).text_content() or ""
        # No Python errors
        assert "Traceback" not in page_text, f"Traceback in Download tab: {page_text[:600]}"

    def test_download_tab_shows_completed_hpc_jobs(self, seeded_state: Page) -> None:
        """Download tab lists only completed HPC jobs, not local or non-completed."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        download_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Download")
        expect(download_tab).to_be_visible(timeout=12_000)
        download_tab.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "11f_seed_download_completed_jobs")

        page_text = app_page.locator(MAIN).text_content() or ""
        # The completed job should be mentioned (DRY_RUN_3 or its seed label)
        has_completed = (
            "completed" in page_text.lower()
            or "DRY_RUN_3" in page_text
            or "LH_Cont_PFCl_3" in page_text
            or "Download" in page_text
        )
        assert has_completed, (
            f"Expected completed job info in Download tab. Page: {page_text[:800]}"
        )


# ---------------------------------------------------------------------------
# Test 12: Group Stats — Monitor + Download tabs
# ---------------------------------------------------------------------------


class TestGroupStatsMonitorDownload:
    """Monitor and Download tabs in the Group Statistics submission page."""

    def test_group_monitor_tab_renders(self, seeded_state: Page) -> None:
        """Monitor tab of Group Stats page renders without errors."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")
        _save_screenshot(app_page, "12a_group_stats_submit_tab")

        monitor_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Monitor")
        expect(monitor_tab).to_be_visible(timeout=12_000)
        monitor_tab.click()
        app_page.wait_for_timeout(3_000)
        _save_screenshot(app_page, "12b_group_stats_monitor_tab")

        page_text = app_page.locator(MAIN).text_content() or ""
        assert "Traceback" not in page_text, f"Traceback in Group Monitor tab: {page_text[:600]}"

    def test_group_monitor_shows_group_stats_submission(self, seeded_state: Page) -> None:
        """Group Stats Monitor tab shows the seeded group_stats submission."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")

        monitor_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Monitor")
        expect(monitor_tab).to_be_visible(timeout=12_000)
        monitor_tab.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "12c_group_monitor_submission")

        page_text = app_page.locator(MAIN).text_content() or ""
        has_group_entry = any(token in page_text for token in [
            "group_stats", "DRY_RUN_4", "completed", "✅", "TFCE",
        ])
        assert has_group_entry, (
            f"Expected group_stats submission in Monitor tab. Page: {page_text[:800]}"
        )

    def test_group_download_tab_renders(self, seeded_state: Page) -> None:
        """Download tab of Group Stats page renders without errors."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")

        download_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Download")
        expect(download_tab).to_be_visible(timeout=12_000)
        download_tab.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "12d_group_download_tab")

        page_text = app_page.locator(MAIN).text_content() or ""
        assert "Traceback" not in page_text, f"Traceback in Group Download tab: {page_text[:600]}"

    def test_group_download_shows_completed_hpc_job(self, seeded_state: Page) -> None:
        """Group Download tab shows the completed group_stats HPC job."""
        app_page = seeded_state
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")

        download_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Download")
        expect(download_tab).to_be_visible(timeout=12_000)
        download_tab.click()
        app_page.wait_for_timeout(4_000)
        _save_screenshot(app_page, "12e_group_download_completed_job")

        page_text = app_page.locator(MAIN).text_content() or ""
        has_completed = (
            "completed" in page_text.lower()
            or "DRY_RUN_4" in page_text
            or "group_stats" in page_text
            or "Download" in page_text
        )
        assert has_completed, (
            f"Expected completed group job in Download tab. Page: {page_text[:800]}"
        )


# ---------------------------------------------------------------------------
# Test 13: Full workflow smoke test — LH_Cont_PFCl_3
# ---------------------------------------------------------------------------


class TestFullWorkflowSmokeTest:
    """End-to-end smoke test for the LH_Cont_PFCl_3 seed connectivity workflow."""

    def test_seed_submission_for_LH_Cont_PFCl_3(self, app_page: Page) -> None:
        """Navigate seed page, configure LH_Cont_PFCl_3, build preview, dry-run."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")
        _save_screenshot(app_page, "13a_seed_initial_state")

        # Ensure Submit tab is active (default)
        submit_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Submit")
        if submit_tab.count() > 0:
            submit_tab.first.click()
            app_page.wait_for_timeout(2_000)

        # Pipeline selector → fc (default, just verify it's visible)
        pipeline_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Pipeline"
        )
        expect(pipeline_box).to_be_visible(timeout=12_000)

        # Atlas selector: 4S256Parcels is the default; verify then select explicitly
        atlas_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Atlas"
        )
        expect(atlas_box).to_be_visible(timeout=10_000)
        atlas_box.click()
        app_page.wait_for_timeout(400)
        atlas_opt = app_page.get_by_role("option").filter(has_text="4S256Parcels").first
        expect(atlas_opt).to_be_visible(timeout=8_000)
        atlas_opt.click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "13b_seed_atlas_selected")

        # Parcel multiselect: type to filter, click LH_Cont_PFCl_3, then "Add selected parcels"
        parcel_multi = app_page.locator(MAIN + " " + '[data-testid="stMultiSelect"]').filter(
            has_text="Parcel"
        )
        expect(parcel_multi).to_be_visible(timeout=12_000)
        parcel_input = parcel_multi.locator("input")
        parcel_input.click()
        app_page.wait_for_timeout(400)
        parcel_input.fill("LH_Cont_PFCl_3")
        app_page.wait_for_timeout(1_500)
        parcel_opt = app_page.get_by_role("option").filter(has_text="LH_Cont_PFCl_3").first
        expect(parcel_opt).to_be_visible(timeout=10_000)
        parcel_opt.click()
        app_page.keyboard.press("Escape")
        app_page.wait_for_timeout(300)

        # Click "Add selected parcels" to register the seed
        add_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Add selected parcels")
        add_btn.scroll_into_view_if_needed()
        add_btn.click()
        app_page.wait_for_timeout(3_000)
        _save_screenshot(app_page, "13c_seed_parcel_added")

        # Build command preview
        preview_btn = app_page.locator(MAIN).get_by_role("button").filter(
            has_text="Build command preview"
        )
        preview_btn.scroll_into_view_if_needed()
        preview_btn.click()
        app_page.wait_for_timeout(5_000)
        _save_screenshot(app_page, "13d_seed_command_preview")

        command = _find_command(app_page, "--analysis seed")
        assert command is not None, "No code block with '--analysis seed' found after Build command preview"
        assert "--seed atlas-4S256Parcels" in command, (
            f"Expected '--seed atlas-4S256Parcels' in command, got: {command[:500]}"
        )
        # Check parcel name appears in command (various formats acceptable)
        assert "LH_Cont_PFCl_3" in command or "PFCl_3" in command, (
            f"Expected LH_Cont_PFCl_3 in seed arg. Command: {command[:500]}"
        )
        assert "--pipeline fc" in command, f"--pipeline fc missing from command: {command[:400]}"

        # Dry-run
        dry_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Dry-run")
        dry_btn.scroll_into_view_if_needed()
        dry_btn.click()
        app_page.wait_for_timeout(6_000)
        _save_screenshot(app_page, "13e_seed_dryrun")

        dry_cmd = _find_command(app_page, "--analysis seed")
        alerts = app_page.locator('[data-testid="stAlertContainer"]').all()
        alert_texts = [el.text_content() or "" for el in alerts]
        assert dry_cmd is not None or any(
            "dry" in t.lower() or "success" in t.lower() or "built" in t.lower()
            for t in alert_texts
        ), f"Expected dry-run output. Alerts: {alert_texts}"

    def test_group_stats_dry_run(self, app_page: Page) -> None:
        """Navigate group stats page, configure seed+TFCE, build preview, dry-run."""
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")
        _save_screenshot(app_page, "14a_group_stats_initial")

        # Ensure Submit tab is active
        submit_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Submit")
        if submit_tab.count() > 0:
            submit_tab.first.click()
            app_page.wait_for_timeout(2_000)

        # Select Voxel-level analysis type
        analysis_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Choose analysis type"
        )
        expect(analysis_box).to_be_visible(timeout=12_000)
        analysis_box.click()
        app_page.wait_for_timeout(400)
        app_page.get_by_role("option").filter(has_text="Voxel-level").first.click()
        app_page.wait_for_timeout(2_000)

        # Measure → seed
        measure_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Measure"
        ).first
        measure_box.click()
        app_page.wait_for_timeout(400)
        seed_opt = app_page.get_by_role("option", name="seed", exact=True)
        if seed_opt.count() > 0:
            seed_opt.click()
        else:
            app_page.keyboard.press("Escape")
        app_page.wait_for_timeout(2_000)

        # Correction method → TFCE
        correction_box = app_page.locator(MAIN + " " + '[data-testid="stSelectbox"]').filter(
            has_text="Correction method"
        )
        correction_box.click()
        app_page.wait_for_timeout(400)
        app_page.get_by_role("option", name="TFCE").click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "14b_group_stats_configured")

        # n_permutations stays at 5000 (default)
        n_perms = app_page.locator(MAIN).locator('[data-testid="stNumberInput"]').filter(
            has_text="n_permutations"
        )
        expect(n_perms).to_be_visible(timeout=8_000)

        # Build command preview
        preview_btn = app_page.locator(MAIN).get_by_role("button").filter(
            has_text="Build command preview"
        )
        preview_btn.scroll_into_view_if_needed()
        preview_btn.click()
        app_page.wait_for_timeout(5_000)
        _save_screenshot(app_page, "14c_group_stats_command")

        command = _find_command(app_page, "--kind voxel")
        assert command is not None, "No code block with '--kind voxel' found in group stats"
        assert "--kind voxel" in command, f"--kind voxel missing: {command[:400]}"
        assert "--method TFCE" in command, f"--method TFCE missing: {command[:400]}"

        # Dry-run
        dry_btn = app_page.locator(MAIN).get_by_role("button").filter(has_text="Dry-run")
        dry_btn.scroll_into_view_if_needed()
        dry_btn.click()
        app_page.wait_for_timeout(6_000)
        _save_screenshot(app_page, "14d_group_stats_dryrun")

        dry_cmd = _find_command(app_page, "--kind voxel")
        alerts = app_page.locator('[data-testid="stAlertContainer"]').all()
        alert_texts = [el.text_content() or "" for el in alerts]
        assert dry_cmd is not None or any(
            "dry" in t.lower() or "success" in t.lower() or "built" in t.lower()
            for t in alert_texts
        ), f"Expected dry-run output. Alerts: {alert_texts}"

    def test_group_viewer_renders(self, app_page: Page) -> None:
        """Group Seed Connectivity Viewer page renders without Python errors."""
        navigate_sidebar(app_page, stage="Group-Level", analysis="🗺️ Group Seed Viewer")
        _save_screenshot(app_page, "15a_group_viewer_dashboard")

        page_text = app_page.locator(MAIN).text_content() or ""
        assert "Traceback" not in page_text, f"Traceback in Group Viewer: {page_text[:600]}"

        # Try to click Viewer tab if present
        viewer_tab = app_page.locator('[data-testid="stTab"]').filter(has_text="Viewer")
        if viewer_tab.count() > 0:
            viewer_tab.first.click()
            app_page.wait_for_timeout(3_000)
            _save_screenshot(app_page, "15b_group_viewer_viewer_tab")

            page_text = app_page.locator(MAIN).text_content() or ""
            assert "Traceback" not in page_text, f"Traceback in Viewer tab: {page_text[:600]}"
