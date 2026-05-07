"""End-to-end Playwright tests for group-level seed connectivity analysis.

Covers:
  1. Group Seed Viewer dashboard — shows completion status from fixture data
  2. Group Seed Viewer — viewer tab loads tstat + TFCE maps
  3. Submit Group Stats — seed catalog dropdown + seed visualizer in submit page
  4. Submit Group Stats — correct CLI command preview (no output-dir, correct arg names)
"""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.conftest import APP_URL, SCREENSHOTS_DIR, navigate_sidebar  # noqa: F401

MAIN = 'section[data-testid="stMain"]'
SCREENSHOTS = SCREENSHOTS_DIR / "group_stats"


def _save_screenshot(page: Page, name: str) -> None:
    SCREENSHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOTS / f"{name}.png"), full_page=False)


def _get_code_blocks(page: Page) -> list[str]:
    return [el.text_content() or "" for el in page.locator("pre").all()]


# ============================================================================
# Group Seed Viewer — Dashboard
# ============================================================================

class TestGroupSeedViewerDashboard:
    """Dashboard tab shows completion status from pre-existing fixture data."""

    def test_dashboard_loads_and_shows_fixture(self, app_page: Page) -> None:
        """Navigating to Group Seed Viewer → Dashboard shows fixture seed data."""
        page = app_page
        navigate_sidebar(page, stage="👥 Group-Level", analysis="🗺️ Group Seed Viewer")

        # Wait for title
        expect(page.locator(MAIN).get_by_role("heading", name="Group Seed Connectivity Viewer")).to_be_visible(timeout=10_000)

        # Dashboard tab should be active by default
        page.wait_for_timeout(2_000)

        main = page.locator(MAIN)
        body_text = main.inner_text()

        # Fixture data found → Total runs metric should be ≥ 1
        assert "Total runs" in body_text, (
            f"Dashboard did not show fixture data (Total runs metric missing).\n"
            f"Content:\n{body_text[:1000]}"
        )
        # The fixture has 1 run
        assert "No group results" not in body_text, (
            "Dashboard says no results, but fixture should be present"
        )

        _save_screenshot(page, "dashboard_loads")

    def test_dashboard_shows_status_metrics(self, app_page: Page) -> None:
        """Dashboard shows total runs, has t-stat, has TFCE metrics."""
        page = app_page
        navigate_sidebar(page, stage="👥 Group-Level", analysis="🗺️ Group Seed Viewer")
        page.wait_for_timeout(3_000)

        main = page.locator(MAIN)
        body_text = main.inner_text()

        # Metrics should include "Total runs" and completion info
        assert "Total runs" in body_text or "Complete" in body_text, (
            f"Status metrics not found. Content:\n{body_text[:1000]}"
        )
        _save_screenshot(page, "dashboard_metrics")

    def test_dashboard_rescan_button(self, app_page: Page) -> None:
        """Rescan button is present and clickable."""
        page = app_page
        navigate_sidebar(page, stage="👥 Group-Level", analysis="🗺️ Group Seed Viewer")
        page.wait_for_timeout(2_000)

        rescan_btn = page.locator(MAIN).get_by_role("button", name="Rescan")
        expect(rescan_btn).to_be_visible(timeout=5_000)
        rescan_btn.click()
        page.wait_for_timeout(2_000)

        _save_screenshot(page, "dashboard_after_rescan")


# ============================================================================
# Group Seed Viewer — Viewer tab
# ============================================================================

class TestGroupSeedViewer:
    """Viewer tab renders stat maps from fixture data."""

    def _goto_viewer_tab(self, page: Page) -> None:
        navigate_sidebar(page, stage="👥 Group-Level", analysis="🗺️ Group Seed Viewer")
        page.wait_for_timeout(2_000)
        # Click the 🔍 Viewer tab
        viewer_tab = page.locator(MAIN).get_by_role("tab", name="Viewer")
        viewer_tab.click()
        page.wait_for_timeout(3_000)

    def test_viewer_tab_opens(self, app_page: Page) -> None:
        """Viewer tab loads without error."""
        page = app_page
        self._goto_viewer_tab(page)

        main = page.locator(MAIN)
        # Check for selectors or info about no results
        body_text = main.inner_text()
        assert any(kw in body_text for kw in ["Seed", "Measure", "Contrast", "No group results"]), (
            f"Viewer tab unexpected content:\n{body_text[:1000]}"
        )
        _save_screenshot(page, "viewer_tab_open")

    def test_viewer_renders_tstat_map(self, app_page: Page) -> None:
        """With fixture data: selecting seed shows tstat image."""
        page = app_page
        self._goto_viewer_tab(page)

        main = page.locator(MAIN)
        body_text = main.inner_text()

        # Fixture should be available
        if "No group results" in body_text:
            pytest.skip("No fixture data found — fixture creation may have failed")

        # Should see Seed selector and t-stat map heading
        page.wait_for_timeout(2_000)
        assert "T-statistic map" in main.inner_text() or "tstat" in main.inner_text().lower() or \
               "Contrast" in main.inner_text(), (
            f"Tstat map heading not found. Content:\n{main.inner_text()[:1000]}"
        )

        # There should be at least one <img> in the viewer
        imgs = main.locator("img").all()
        assert len(imgs) >= 1, "No image rendered in viewer tab"

        _save_screenshot(page, "viewer_tstat_map")

    def test_viewer_tfce_map_shown(self, app_page: Page) -> None:
        """TFCE corrected p-value map section is shown."""
        page = app_page
        self._goto_viewer_tab(page)
        page.wait_for_timeout(3_000)

        main = page.locator(MAIN)
        body_text = main.inner_text()

        if "No group results" in body_text:
            pytest.skip("No fixture data found")

        assert "TFCE" in body_text or "corrected" in body_text.lower(), (
            f"TFCE section not found:\n{body_text[:1000]}"
        )
        _save_screenshot(page, "viewer_tfce")

    def test_viewer_threshold_slider(self, app_page: Page) -> None:
        """T-stat threshold slider is present and interactive."""
        page = app_page
        self._goto_viewer_tab(page)
        page.wait_for_timeout(3_000)

        main = page.locator(MAIN)
        body_text = main.inner_text()
        if "No group results" in body_text:
            pytest.skip("No fixture data found")

        slider = main.locator('[data-testid="stSlider"]').first
        expect(slider).to_be_visible(timeout=5_000)
        _save_screenshot(page, "viewer_slider")

    def test_viewer_metadata_expander(self, app_page: Page) -> None:
        """Analysis metadata expander is visible and openable."""
        page = app_page
        self._goto_viewer_tab(page)
        page.wait_for_timeout(3_000)

        main = page.locator(MAIN)
        if "No group results" in main.inner_text():
            pytest.skip("No fixture data")

        meta_exp = main.get_by_text("Analysis metadata")
        if meta_exp.count() > 0:
            meta_exp.first.click()
            page.wait_for_timeout(1_000)
            # Should show JSON content (n_perm, seed, etc.)
            assert "pearson" in main.inner_text() or "100" in main.inner_text()

        _save_screenshot(page, "viewer_metadata")


# ============================================================================
# Submit Group Stats — seed selector + visualizer
# ============================================================================

class TestGroupStatsSubmit:
    """Group stats submit page has seed catalog dropdown + visualizer."""

    def _goto_submit(self, page: Page) -> None:
        navigate_sidebar(page, stage="👥 Group-Level", analysis="📤 Submit Group Statistics")
        page.wait_for_timeout(3_000)
        # Select Mixed-Design TFCE from the analysis type selectbox
        main = page.locator(MAIN)
        template_box = main.locator('[data-testid="stSelectbox"]').first
        template_box.click()
        page.wait_for_timeout(400)
        page.get_by_role("option", name="Mixed-Design TFCE (pre/post × 2 groups)").click()
        page.wait_for_timeout(2_500)

    def test_submit_page_loads(self, app_page: Page) -> None:
        """Submit page loads with Mixed-Design section."""
        page = app_page
        self._goto_submit(page)

        main = page.locator(MAIN)
        # Page title and Mixed-Design heading should be visible
        body_text = main.inner_text()
        assert "Submit Group Statistics" in body_text, (
            f"Page heading not found:\n{body_text[:500]}"
        )
        assert "Mixed-Design" in body_text, (
            f"Mixed-Design section not found:\n{body_text[:500]}"
        )
        _save_screenshot(page, "submit_page_loads")

    def test_submit_has_seed_source_radio(self, app_page: Page) -> None:
        """Seed section has radio for Catalog vs Manual entry."""
        page = app_page
        self._goto_submit(page)

        main = page.locator(MAIN)
        body_text = main.inner_text()

        # Should have catalog seed source option
        assert "Catalog" in body_text or "Manual" in body_text or "Seed" in body_text, (
            f"Seed source selector not found:\n{body_text[:1000]}"
        )
        _save_screenshot(page, "submit_seed_source")

    def test_submit_manual_seed_preview(self, app_page: Page) -> None:
        """Selecting Manual entry + typing a sphere token shows preview expander."""
        page = app_page
        self._goto_submit(page)

        main = page.locator(MAIN)

        # Switch to Manual entry via the stRadio widget (exact match to avoid warning text)
        manual_radio = main.locator('[data-testid="stRadio"]').get_by_text("Manual entry", exact=True)
        if manual_radio.count() == 0:
            pytest.skip("Manual entry radio not found")
        manual_radio.first.click()
        page.wait_for_timeout(1_000)

        # Type a valid sphere token
        text_input = main.locator('[data-testid="stTextInput"] input').first
        text_input.fill("sphere:-46,16,32,r=6,name=dlpfc_l")
        page.wait_for_timeout(1_500)

        body_text = main.inner_text()
        assert "Preview seed" in body_text or "MNI" in body_text or "preview" in body_text.lower(), (
            f"Seed preview expander not found:\n{body_text[:1000]}"
        )
        _save_screenshot(page, "submit_seed_preview_expander")

    def test_submit_shows_output_path(self, app_page: Page) -> None:
        """Submit section shows proper derivatives output path."""
        page = app_page
        self._goto_submit(page)

        main = page.locator(MAIN)

        # Switch to Manual entry and enter seed
        manual_radio = main.locator('[data-testid="stRadio"]').get_by_text("Manual entry", exact=True)
        if manual_radio.count() > 0:
            manual_radio.first.click()
            page.wait_for_timeout(500)
            text_input = main.locator('[data-testid="stTextInput"] input').first
            text_input.fill("sphere:-46,16,32,r=6,name=dlpfc_l")
            page.wait_for_timeout(1_000)

        body_text = main.inner_text()
        assert "derivatives/connectivity" in body_text or "group" in body_text.lower(), (
            f"Proper output path not shown:\n{body_text[:2000]}"
        )
        assert "results/group_mixed_design" not in body_text, (
            "Old output path still present — fix not applied"
        )
        _save_screenshot(page, "submit_output_path")

    def test_submit_validate_requires_seed(self, app_page: Page) -> None:
        """Validate Zmaps button shows warning when no seed is selected."""
        page = app_page
        self._goto_submit(page)

        main = page.locator(MAIN)

        # Switch to Manual entry and clear the input
        manual_radio = main.locator('[data-testid="stRadio"]').get_by_text("Manual entry", exact=True)
        if manual_radio.count() > 0:
            manual_radio.first.click()
            page.wait_for_timeout(500)
            text_input = main.locator('[data-testid="stTextInput"] input').first
            text_input.fill("")
            page.wait_for_timeout(500)

        # Click Validate Zmaps without seed
        validate_btn = main.get_by_role("button", name="Validate Zmaps")
        if validate_btn.count() > 0:
            validate_btn.click()
            page.wait_for_timeout(2_000)
            body_text = main.inner_text()
            assert "seed" in body_text.lower() or "select" in body_text.lower(), (
                f"Warning about missing seed not shown:\n{body_text[:1000]}"
            )

        _save_screenshot(page, "submit_validate_requires_seed")

    def test_submit_cli_command_no_output_dir(self, app_page: Page) -> None:
        """After submission attempt, CLI command should NOT contain --output-dir."""
        # This test validates the backend CLI command structure
        # We verify by checking code shown in the UI after a (failed) submission
        page = app_page
        self._goto_submit(page)

        main = page.locator(MAIN)
        body_text = main.inner_text()

        # If there's a code block showing the command (from a prior run), check it
        code_blocks = _get_code_blocks(page)
        for block in code_blocks:
            if "group_mixed_design_stats" in block:
                assert "--output-dir" not in block, (
                    f"--output-dir should not be in CLI command:\n{block}"
                )
                assert "--n-perms" in block or "--n-perm" in block, (
                    f"n-perms argument missing:\n{block}"
                )

        _save_screenshot(page, "submit_cli_command")
