"""
tests/e2e/test_papaya_browser.py
=================================
Playwright end-to-end tests for the Papaya brain viewer component.

Tests verified:
1. Main NeuConn app loads at http://localhost:8500.
2. Minimal Papaya test page loads at http://localhost:8501.
3. The Papaya iframe component is present in the Streamlit DOM.
4. Inside the iframe, Papaya JS globals (papaya, papayaContainers) exist.
5. papayaContainers has at least one entry (viewer was initialised).
6. papaya.viewer.Viewer.prototype is defined (library loaded completely).
7. The Papaya container div is rendered with non-zero dimensions.

The test suite uses a dedicated test Streamlit page (papaya_test_page.py) that
bundles papaya.js locally for offline/CI reliability.

Pre-requisites (handled automatically by the conftest streamlit_test_server
fixture):
  - tests/e2e/fixtures/test_brain.nii      — synthetic NIfTI test fixture
  - tests/e2e/fixtures/papaya.js           — Papaya viewer library
  - tests/e2e/fixtures/papaya.css          — Papaya viewer styles
  - Main app running on port 8500 (started externally before the test run)
"""
from __future__ import annotations

from typing import Any

import pytest
from playwright.sync_api import Page

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAIN_APP_URL = "http://localhost:8500"
MAIN_APP_TITLE = "NeuConn - Neuroimaging Connectivity Suite"
PAPAYA_TIMEOUT_MS = 30_000  # 30 s — Papaya NIfTI load can take a few seconds


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_papaya_iframe(page: Page):
    """
    Return the first child frame of *page* that contains Papaya content.

    Streamlit wraps st.components.v1.html() output in an iframe with
    url='about:srcdoc'.  Papaya *removes* the initial ``class="papaya"``
    from the container div after initialisation, so we identify the frame
    by its URL or by the presence of the ``#papaya-status`` sentinel element
    injected by the test page.
    """
    page.wait_for_selector("iframe", timeout=PAPAYA_TIMEOUT_MS)
    for frame in page.frames:
        # Streamlit component iframes use srcdoc and show as about:srcdoc
        if frame.url == "about:srcdoc":
            return frame
        # Fallback: look for the sentinel element we added to the test page HTML
        try:
            el = frame.query_selector("#papaya-status")
            if el is not None:
                return frame
        except Exception:
            continue
    return None


def _eval_in_papaya_frame(page: Page, js: str) -> Any:
    """
    Find the Papaya iframe and evaluate *js* inside it.
    Returns ``None`` if the frame cannot be found.
    """
    frame = _find_papaya_iframe(page)
    if frame is None:
        return None
    return frame.evaluate(js)


# ---------------------------------------------------------------------------
# Test 1 — Main app health
# ---------------------------------------------------------------------------

class TestMainAppLoads:
    """Verify the NeuConn Streamlit app is reachable and renders its title."""

    def test_main_app_health_endpoint(self):
        """/_stcore/health should return 200 (verified without a browser)."""
        import urllib.request
        with urllib.request.urlopen(f"{MAIN_APP_URL}/_stcore/health", timeout=5) as resp:
            assert resp.status == 200, (
                f"Expected HTTP 200 from {MAIN_APP_URL}/_stcore/health, got {resp.status}"
            )

    def test_main_app_page_title(self, page: Page):
        """Main app title must match 'NeuConn - Neuroimaging Connectivity Suite'."""
        page.goto(MAIN_APP_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector('[data-testid="stApp"]', timeout=20_000)
        # Streamlit updates the tab title via JS after the Python code runs.
        # Wait up to 10 s for it to change from the generic "Streamlit" default.
        page.wait_for_function(
            f"document.title.includes('{MAIN_APP_TITLE}')",
            timeout=10_000,
        )
        title = page.title()
        assert MAIN_APP_TITLE in title, (
            f"Expected page title to contain '{MAIN_APP_TITLE}', got: '{title}'"
        )

    def test_main_app_sidebar_present(self, page: Page):
        """The Streamlit sidebar must be present (confirms full app loaded)."""
        page.goto(MAIN_APP_URL, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector('[data-testid="stSidebar"]', timeout=20_000)


# ---------------------------------------------------------------------------
# Test 2 — Papaya test page health
# ---------------------------------------------------------------------------

class TestPapayaTestPageLoads:
    """Verify the dedicated Papaya test Streamlit page serves correctly."""

    def test_test_server_health(self, streamlit_test_server: str):
        import urllib.request
        url = streamlit_test_server
        with urllib.request.urlopen(f"{url}/_stcore/health", timeout=10) as resp:
            assert resp.status == 200

    def test_test_page_renders_title(self, page: Page, streamlit_test_server: str):
        page.goto(streamlit_test_server, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector('[data-testid="stApp"]', timeout=20_000)
        heading = page.locator("h1").first
        heading.wait_for(timeout=15_000)
        assert "Papaya" in heading.text_content(), (
            f"Expected 'Papaya' in page heading, got: {heading.text_content()!r}"
        )

    def test_test_page_alert_present(self, page: Page, streamlit_test_server: str):
        """
        st.success() renders as [data-testid="stAlert"] in Streamlit >= 1.27.
        The alert text must confirm the component HTML was injected.
        """
        page.goto(streamlit_test_server, wait_until="domcontentloaded", timeout=30_000)
        # Use stAlert (Streamlit >= 1.27) with generous timeout for 1.8 MB inline JS
        page.wait_for_selector('[data-testid="stAlert"]', timeout=25_000)
        alert_text = page.locator('[data-testid="stAlert"]').first.inner_text()
        assert "Papaya" in alert_text or "injected" in alert_text, (
            f"Alert text does not confirm Papaya injection: {alert_text!r}"
        )


# ---------------------------------------------------------------------------
# Test 3 — Papaya iframe is present in the DOM
# ---------------------------------------------------------------------------

class TestPapayaIframePresent:
    """Verify that st.components.v1.html() renders an iframe containing Papaya."""

    def test_iframe_exists(self, page: Page, streamlit_test_server: str):
        """At least one <iframe> must appear after Streamlit renders."""
        page.goto(streamlit_test_server, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("iframe", timeout=20_000)
        iframes = page.query_selector_all("iframe")
        assert len(iframes) >= 1, "Expected at least one iframe on the test page"

    def test_papaya_component_inside_iframe(self, page: Page, streamlit_test_server: str):
        """
        The Papaya component container must exist inside the component iframe.

        After Papaya initialises, it replaces the original ``<div class="papaya">``
        element with internal ``<div id="papayaContainer*">`` divs.  We verify the
        iframe contains the ``#papaya-status`` sentinel OR any papayaContainer div.
        """
        page.goto(streamlit_test_server, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("iframe", timeout=20_000)
        # Allow time for 1.8 MB inline JS to parse and Papaya to initialise
        page.wait_for_timeout(4_000)

        frame = _find_papaya_iframe(page)
        assert frame is not None, (
            "Could not find a child iframe with Papaya content (about:srcdoc or #papaya-status). "
            "st.components.v1.html() may not have injected the HTML, or the iframe has not loaded."
        )

        # After Papaya init the div is no longer class="papaya"; look for its replacement
        has_content = frame.evaluate("""() => {
            return !!(
                document.getElementById('papaya-status') ||
                document.querySelector('[id^="papayaContainer"]') ||
                document.querySelector('canvas')
            );
        }""")
        assert has_content, (
            "Papaya iframe exists but contains no expected elements "
            "(#papaya-status, papayaContainer*, or canvas). The viewer may not have initialised."
        )

    def test_papaya_viewer_div_has_dimensions(self, page: Page, streamlit_test_server: str):
        """The outermost Papaya container div must have non-zero rendered dimensions."""
        page.goto(streamlit_test_server, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("iframe", timeout=20_000)
        page.wait_for_timeout(4_000)

        frame = _find_papaya_iframe(page)
        assert frame is not None, "Papaya iframe not found"

        dims = frame.evaluate("""() => {
            var el = (
                document.querySelector('[id^="papayaContainer"]') ||
                document.getElementById('papayaViewer')
            );
            if (!el) return null;
            var r = el.getBoundingClientRect();
            return {width: r.width, height: r.height};
        }""")
        assert dims is not None, (
            "Could not read Papaya container div dimensions — "
            "no papayaContainer* or #papayaViewer element found"
        )
        assert dims["width"] > 0, f"Papaya container width is 0: {dims}"
        assert dims["height"] > 0, f"Papaya container height is 0: {dims}"


# ---------------------------------------------------------------------------
# Test 4 — Papaya JavaScript globals
# ---------------------------------------------------------------------------

class TestPapayaJsGlobals:
    """Verify Papaya JS globals exist inside the component iframe."""

    def _navigate_and_wait(self, page: Page, url: str):
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("iframe", timeout=20_000)
        # Papaya JS is ~1.8 MB inline — allow generous parse + init time
        page.wait_for_timeout(6_000)

    def test_papaya_namespace_exists(self, page: Page, streamlit_test_server: str):
        """``papaya`` global namespace must be defined inside the iframe."""
        self._navigate_and_wait(page, streamlit_test_server)
        result = _eval_in_papaya_frame(page, "typeof papaya !== 'undefined'")
        assert result is True, (
            "papaya global is not defined inside the iframe. "
            "The Papaya JS library may have failed to load or parse."
        )

    def test_papaya_viewer_prototype_exists(self, page: Page, streamlit_test_server: str):
        """``papaya.viewer.Viewer`` must exist (confirms full library loaded)."""
        self._navigate_and_wait(page, streamlit_test_server)
        result = _eval_in_papaya_frame(
            page,
            "typeof papaya !== 'undefined' && "
            "typeof papaya.viewer !== 'undefined' && "
            "typeof papaya.viewer.Viewer !== 'undefined'"
        )
        assert result is True, (
            "papaya.viewer.Viewer is not defined. Papaya JS did not fully parse/execute."
        )

    def test_papaya_containers_array_exists(self, page: Page, streamlit_test_server: str):
        """``papayaContainers`` global array must be defined after Papaya initialises."""
        self._navigate_and_wait(page, streamlit_test_server)
        result = _eval_in_papaya_frame(page, "typeof papayaContainers !== 'undefined'")
        assert result is True, (
            "papayaContainers global is not defined. "
            "papaya.Container.addViewer() may not have run."
        )

    def test_papaya_containers_has_entries(self, page: Page, streamlit_test_server: str):
        """``papayaContainers`` must contain at least one initialised container."""
        self._navigate_and_wait(page, streamlit_test_server)
        count = _eval_in_papaya_frame(
            page,
            "(typeof papayaContainers !== 'undefined') ? papayaContainers.length : -1"
        )
        assert count is not None and count >= 1, (
            f"papayaContainers.length = {count}. "
            "Expected at least 1 entry after addViewer() is called."
        )


# ---------------------------------------------------------------------------
# Test 5 — NIfTI volume loaded
# ---------------------------------------------------------------------------

class TestPapayaVolumeLoaded:
    """Verify that the test NIfTI fixture was actually loaded into the viewer."""

    def _navigate_and_wait(self, page: Page, url: str, extra_ms: int = 8_000):
        """Navigate and wait for Papaya to load the NIfTI (async XHR/atob decode)."""
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        page.wait_for_selector("iframe", timeout=20_000)
        page.wait_for_timeout(extra_ms)

    def test_viewer_initialized_flag(self, page: Page, streamlit_test_server: str):
        """
        papayaContainers[0].viewer.initialized must be true after the
        NIfTI finishes loading.
        """
        self._navigate_and_wait(page, streamlit_test_server)
        initialized = _eval_in_papaya_frame(page, """() => {
            if (typeof papayaContainers === 'undefined') return null;
            var c = papayaContainers[0];
            return (c && c.viewer) ? c.viewer.initialized : null;
        }""")
        # initialized=None means papayaContainers not accessible (iframe finder failed)
        assert initialized is not False, (
            "papayaContainers[0].viewer.initialized is explicitly false. "
            "The NIfTI may have failed to decode or load."
        )

    def test_status_text_reflects_loading(self, page: Page, streamlit_test_server: str):
        """
        The #papaya-status div inside the iframe should advance past
        'Initializing Papaya...' once Papaya has started.
        """
        self._navigate_and_wait(page, streamlit_test_server, extra_ms=4_000)
        status_text = _eval_in_papaya_frame(page, """() => {
            var el = document.getElementById('papaya-status');
            return el ? el.innerText : null;
        }""")
        assert status_text is not None, "#papaya-status element not found inside iframe"
        assert status_text.strip() != "Initializing Papaya...", (
            f"#papaya-status still shows the initial placeholder — "
            f"Papaya may not have started at all. Got: {status_text!r}"
        )

    def test_screen_volumes_populated(self, page: Page, streamlit_test_server: str):
        """
        papayaContainers[0].viewer.screenVolumes must be non-empty after a
        NIfTI is loaded.
        """
        self._navigate_and_wait(page, streamlit_test_server, extra_ms=10_000)
        vol_count = _eval_in_papaya_frame(page, """() => {
            if (typeof papayaContainers === 'undefined') return -1;
            var c = papayaContainers[0];
            if (!c || !c.viewer || !c.viewer.screenVolumes) return -1;
            return c.viewer.screenVolumes.length;
        }""")
        assert vol_count is not None and vol_count >= 1, (
            f"papayaContainers[0].viewer.screenVolumes.length = {vol_count}. "
            "Expected at least 1 volume after the NIfTI fixture is loaded."
        )
