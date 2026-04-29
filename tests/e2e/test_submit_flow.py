"""
End-to-end Playwright tests for the connectivity analysis submit flow.

Covers three sub-tests:
  1. Local Measures dry-run  — verifies form presence and SLURM command preview.
  2. Seed Connectivity cascade — verifies atlas → seed cascade and dry-run command.
  3. Group Statistics method switch — verifies TFCE options and command preview.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

# conftest.py (same directory) provides: app_page fixture, navigate_sidebar, APP_URL, SCREENSHOTS_DIR
from tests.e2e.conftest import APP_URL, SCREENSHOTS_DIR, navigate_sidebar  # noqa: F401

MAIN = 'section[data-testid="stMain"]'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _save_screenshot(page: Page, name: str) -> None:
    path = SCREENSHOTS_DIR / f"{name}.png"
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


def _seed_caption(page: Page) -> str:
    """Return the caption that reports the seed selection count."""
    captions = [el.text_content() or "" for el in page.locator('[data-testid="stCaptionContainer"]').all()]
    for cap in captions:
        if "seed(s) selected" in cap:
            return cap
    return ""


# ---------------------------------------------------------------------------
# Test 1: Local Measures Submit — Dry Run
# ---------------------------------------------------------------------------


class TestLocalMeasuresDryRun:
    """Verify the Submit Local Measures page and its dry-run output."""

    def test_navigate_to_page(self, app_page: Page) -> None:
        """Page title appears after navigating the sidebar hierarchy."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Local Measures")
        _save_screenshot(app_page, "01_local_measures_page")
        # Assert the h1 heading in the main area.
        heading = app_page.locator(MAIN).get_by_role("heading", level=1).first
        expect(heading).to_contain_text("Submit Local Measures Analysis", timeout=10_000)

    def test_form_fields_present(self, app_page: Page) -> None:
        """Required form controls are rendered on the submit page."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Local Measures")

        # Subject multiselect
        assert app_page.locator('[data-testid="stMultiSelect"]').count() >= 1, \
            "Subject/session multiselect not found"

        # Bandpass frequency number inputs (High-pass / Low-pass)
        number_inputs = app_page.locator('[data-testid="stNumberInput"]')
        assert number_inputs.count() >= 2, "Bandpass number inputs not found"

        # Smoothing FWHM selectbox
        selectboxes = app_page.locator(MAIN + ' [data-testid="stSelectbox"]')
        assert selectboxes.count() >= 1, "Smoothing selectbox not found"

        # Output measure checkboxes (fALFF, ALFF, ReHo)
        for label in ("fALFF", "ALFF", "ReHo"):
            checkbox = app_page.locator('[data-testid="stCheckbox"]').filter(has_text=label)
            assert checkbox.count() >= 1, f"{label} checkbox not found"

        # HPC resources expander
        expander = app_page.locator('[data-testid="stExpander"]').filter(has_text="HPC resources")
        assert expander.count() >= 1, "HPC resources expander not found"

        # Dry-run and Submit buttons
        assert app_page.get_by_role("button").filter(has_text="Dry-run").count() >= 1, \
            "Dry-run button not found"

    def test_dry_run_produces_command(self, app_page: Page) -> None:
        """Clicking Dry-run renders a SLURM command preview code block."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Local Measures")

        dry_btn = app_page.get_by_role("button").filter(has_text="Dry-run").first
        dry_btn.scroll_into_view_if_needed()
        _save_screenshot(app_page, "01_local_measures_before_dryrun")

        dry_btn.click()
        # Wait for the code block containing the script name to appear.
        app_page.wait_for_selector("pre:has-text('hpc_submit_subject_level.py')", timeout=12_000)
        _save_screenshot(app_page, "01_local_measures_after_dryrun")

        command = _find_command(app_page, "hpc_submit_subject_level.py")
        assert command is not None, "No code block with 'hpc_submit_subject_level.py' found after dry-run"
        assert "python" in command, "Command must start with 'python'"
        assert "--analysis-type local_measures" in command, \
            f"Expected '--analysis-type local_measures' in command, got:\n{command}"


# ---------------------------------------------------------------------------
# Test 2: Seed Connectivity Submit — Cascading Atlas → Seed
# ---------------------------------------------------------------------------


class TestSeedConnectivityCascade:
    """Verify the atlas → seed cascade and dry-run for seed connectivity."""

    def test_atlas_options_present(self, app_page: Page) -> None:
        """Atlas radio group shows at least DiFuMo256 and Schaefer400."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")
        _save_screenshot(app_page, "02_seed_connectivity_page")

        atlas_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Atlas")
        expect(atlas_radio).to_be_visible(timeout=10_000)

        option_labels = [el.text_content() for el in atlas_radio.locator("label").all()]
        assert "DiFuMo256" in option_labels, f"DiFuMo256 not in atlas options: {option_labels}"
        assert "Schaefer400" in option_labels, f"Schaefer400 not in atlas options: {option_labels}"

    def test_priority_seeds_present_for_difumo(self, app_page: Page) -> None:
        """DiFuMo256 atlas shows priority seeds including Anterior_Insula and dACC."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        # DiFuMo256 is the default atlas; priority seeds should be visible (first expander is open).
        # The seed checkboxes include the seed label in their text.
        page_text = app_page.locator(MAIN).text_content() or ""
        assert "Anterior_Insula" in page_text or "Anterior Insula" in page_text, \
            "Priority seed 'Anterior_Insula' not found on DiFuMo256 page"
        assert "dACC" in page_text, "Priority seed 'dACC' not found on DiFuMo256 page"

    def test_cascade_atlas_clears_seeds(self, app_page: Page) -> None:
        """Switching atlas resets the seed selection (cascade works)."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        # Select all priority seeds for DiFuMo256.
        priority_btn = app_page.get_by_role("button").filter(has_text="Select all priority").first
        priority_btn.scroll_into_view_if_needed()
        priority_btn.click()
        app_page.wait_for_timeout(2_000)

        caption_before = _seed_caption(app_page)
        assert "0 of" not in caption_before, \
            f"Expected >0 seeds selected after 'Select all priority', got: {caption_before}"
        _save_screenshot(app_page, "02_difumo256_seeds_selected")

        # Switch atlas to Schaefer400 — seeds should reset.
        atlas_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Atlas")
        atlas_radio.locator("label", has_text="Schaefer400").click()
        app_page.wait_for_timeout(2_500)

        caption_after = _seed_caption(app_page)
        _save_screenshot(app_page, "02_schaefer400_after_atlas_switch")
        assert "0 of" in caption_after, \
            f"Expected seed list to reset to 0 after atlas switch; got: '{caption_after}'"
        assert "Schaefer400" in caption_after, \
            f"Caption should reference Schaefer400 after switch; got: '{caption_after}'"

    def test_dry_run_command_includes_atlas_and_seeds(self, app_page: Page) -> None:
        """Dry-run preview includes --atlas Schaefer400 and --seeds after cascade."""
        navigate_sidebar(app_page, stage="Subject-Level", analysis="📤 Submit Seed Connectivity")

        # Select Schaefer400 atlas.
        atlas_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Atlas")
        atlas_radio.locator("label", has_text="Schaefer400").click()
        app_page.wait_for_timeout(2_000)

        # Select seeds via the "Select all priority" shortcut.
        priority_btn = app_page.get_by_role("button").filter(has_text="Select all priority").first
        priority_btn.scroll_into_view_if_needed()
        priority_btn.click()
        app_page.wait_for_timeout(2_000)

        # The dry-run button should now be enabled.
        dry_btn = app_page.get_by_role("button").filter(has_text="Dry-run").first
        dry_btn.scroll_into_view_if_needed()
        _save_screenshot(app_page, "02_schaefer400_before_dryrun")
        dry_btn.click()

        app_page.wait_for_selector("pre:has-text('--atlas Schaefer400')", timeout=12_000)
        _save_screenshot(app_page, "02_schaefer400_after_dryrun")

        command = _find_command(app_page, "--atlas Schaefer400")
        assert command is not None, "No code block with '--atlas Schaefer400' found after dry-run"
        assert "--seeds" in command, f"Expected '--seeds' in command, got:\n{command[:400]}"


# ---------------------------------------------------------------------------
# Test 3: Group Stats Submit — Method Switch
# ---------------------------------------------------------------------------


class TestGroupStatMethodSwitch:
    """Verify correction-method switching and TFCE options in Group Statistics."""

    def test_navigate_to_page(self, app_page: Page) -> None:
        """Group Statistics page title loads under Group-Level stage."""
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")
        _save_screenshot(app_page, "03_group_stats_page")
        heading = app_page.locator(MAIN).get_by_role("heading", level=1).first
        expect(heading).to_contain_text("Submit Group-Level Statistics", timeout=10_000)

    def test_seed_connectivity_source_shows_atlas_cascade(self, app_page: Page) -> None:
        """Selecting 'Seed Connectivity' source reveals the Atlas selectbox."""
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")

        source_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Analysis source")
        source_radio.locator("label", has_text="Seed Connectivity").click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "03_group_stats_seed_source")

        atlas_box = app_page.locator(MAIN + ' [data-testid="stSelectbox"]').filter(has_text="Atlas")
        expect(atlas_box).to_be_visible(timeout=5_000)

    def test_tfce_shows_permutation_selector(self, app_page: Page) -> None:
        """Switching to TFCE correction reveals the permutation count selectbox."""
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")

        # Switch to Seed Connectivity source first.
        source_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Analysis source")
        source_radio.locator("label", has_text="Seed Connectivity").click()
        app_page.wait_for_timeout(2_000)

        # Switch correction method to TFCE.
        correction_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Correction method")
        correction_radio.locator("label", has_text="TFCE").click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "03_group_stats_tfce_selected")

        # Permutation count selectbox must appear.
        perm_box = app_page.locator('[data-testid="stSelectbox"]').filter(has_text="permutations")
        expect(perm_box).to_be_visible(timeout=5_000)

    def test_tfce_low_permutation_warning(self, app_page: Page) -> None:
        """Selecting 1000 permutations for TFCE triggers a wall-time warning."""
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")

        # Set up: Seed Connectivity source + TFCE correction.
        source_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Analysis source")
        source_radio.locator("label", has_text="Seed Connectivity").click()
        app_page.wait_for_timeout(1_500)

        correction_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Correction method")
        correction_radio.locator("label", has_text="TFCE").click()
        app_page.wait_for_timeout(1_500)

        # Open the permutation selectbox and choose 1000.
        perm_box = app_page.locator('[data-testid="stSelectbox"]').filter(has_text="permutations")
        perm_box.click()
        app_page.wait_for_timeout(400)
        # Use exact=True to avoid matching "10000" when selecting "1000"
        app_page.get_by_role("option", name="1000", exact=True).click()
        app_page.wait_for_timeout(2_000)
        _save_screenshot(app_page, "03_group_stats_1000_perms")

        # Warning about low permutation count should appear.
        warnings = app_page.locator('[data-testid="stAlertContainer"]')
        warning_texts = [w.text_content() or "" for w in warnings.all()]
        perm_warning = any("permutation" in t.lower() or "5000" in t for t in warning_texts)
        assert perm_warning, \
            f"Expected a permutation-count warning for 1000 perms, found alerts: {warning_texts}"

    def test_command_preview_includes_tfce_flags(self, app_page: Page) -> None:
        """
        The always-visible command preview block includes --correction-method tfce
        and --n-permutations after switching to TFCE.

        Note: the Dry-run button is intentionally disabled when the subject-level
        manifest is absent (expected pre-submission validation).  The preview
        command block renders unconditionally above the disabled button, so this
        test asserts on that block rather than requiring dry-run to be enabled.
        """
        navigate_sidebar(app_page, stage="Group-Level", analysis="📤 Submit Group Statistics")

        # Switch source → Seed Connectivity.
        source_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Analysis source")
        source_radio.locator("label", has_text="Seed Connectivity").click()
        app_page.wait_for_timeout(1_500)

        # Switch correction → TFCE.
        correction_radio = app_page.locator('[data-testid="stRadio"]').filter(has_text="Correction method")
        correction_radio.locator("label", has_text="TFCE").click()
        app_page.wait_for_timeout(2_000)

        # Try to click Dry-run if it is enabled; ignore if disabled.
        dry_btn = app_page.get_by_role("button").filter(has_text="Dry-run").first
        dry_btn.scroll_into_view_if_needed()
        if not dry_btn.is_disabled():
            dry_btn.click()
            app_page.wait_for_timeout(3_000)

        _save_screenshot(app_page, "03_group_stats_tfce_command")

        # The preview command is always rendered by _render_actions before the buttons.
        app_page.wait_for_selector("pre:has-text('--correction-method tfce')", timeout=10_000)
        command = _find_command(app_page, "--correction-method tfce")
        assert command is not None, \
            "No code block with '--correction-method tfce' found in preview"
        assert "--n-permutations" in command, \
            f"Expected '--n-permutations' in TFCE command, got:\n{command[:500]}"
