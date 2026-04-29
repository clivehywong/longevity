"""Shared Playwright fixtures for NeuConn Streamlit end-to-end tests."""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest
from playwright.sync_api import Browser, BrowserContext, Page

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
APP_URL = "http://localhost:8500"

# Port for the standalone Papaya test page
PAPAYA_TEST_PORT = 8501
PAPAYA_TEST_PAGE = Path(__file__).parent / "papaya_test_page.py"


def _wait_for_streamlit(url: str, timeout: int = 30) -> bool:
    """Poll the Streamlit health endpoint until it returns 200 or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/_stcore/health", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


@pytest.fixture(scope="session")
def streamlit_test_server():
    """
    Start papaya_test_page.py on PAPAYA_TEST_PORT for the session.

    Yields the base URL (e.g. http://localhost:8501).
    Terminates the server process when the session ends.
    """
    base_url = f"http://localhost:{PAPAYA_TEST_PORT}"
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run",
            str(PAPAYA_TEST_PAGE),
            "--server.port", str(PAPAYA_TEST_PORT),
            "--server.headless", "true",
            "--server.fileWatcherType", "none",
            "--browser.gatherUsageStats", "false",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ready = _wait_for_streamlit(base_url, timeout=30)
        if not ready:
            proc.terminate()
            pytest.fail(
                f"Papaya test server on port {PAPAYA_TEST_PORT} did not start within 30 s"
            )
        yield base_url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict) -> dict:
    """Widen viewport so the Streamlit sidebar and main content are both visible."""
    return {
        **browser_context_args,
        "viewport": {"width": 1400, "height": 900},
    }


@pytest.fixture
def app_page(page: Page) -> Page:
    """Navigate to the NeuConn app and wait for it to become responsive."""
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    page.goto(APP_URL, wait_until="networkidle")
    # Wait for the sidebar heading to confirm the app is loaded.
    page.wait_for_selector('[data-testid="stSidebar"] h1', timeout=15_000)
    return page


def navigate_sidebar(page: Page, *, stage: str | None = None, analysis: str | None = None) -> None:
    """
    Navigate the NeuConn sidebar hierarchy.

    Always starts from the fMRI Analysis category.  Pass *stage* for the
    Pipeline Stage radio and *analysis* for the Analysis selectbox option.
    """
    sidebar = page.locator('[data-testid="stSidebar"]')

    # Category: always switch to fMRI Analysis first.
    fmri_label = sidebar.locator('[data-testid="stRadio"]').filter(has_text="Select Category").locator("p", has_text="fMRI Analysis")
    fmri_label.click()
    page.wait_for_timeout(800)

    if stage:
        stage_label = sidebar.locator('[data-testid="stRadio"]').filter(has_text="Pipeline Stage").locator("p", has_text=stage)
        stage_label.click()
        page.wait_for_timeout(800)

    if analysis:
        selectbox = sidebar.locator('[data-testid="stSelectbox"]')
        selectbox.click()
        page.wait_for_timeout(400)
        page.get_by_role("option", name=analysis).click()
        # Wait for Streamlit to finish its rerun (spinner gone or a known element appears).
        page.wait_for_timeout(3_000)
