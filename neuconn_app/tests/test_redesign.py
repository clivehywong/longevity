"""
Playwright smoke tests for workflow-redesign-v2 features.

Run with:
    cd neuconn_app && python tests/test_redesign.py

Assumes the Streamlit app is already running on APP_URL (default http://localhost:8502).
Screen size: 1920x1080 per project standard.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright, Page, expect
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)

APP_URL = "http://localhost:8501"
VIEWPORT = {"width": 1920, "height": 1080}
SCREENSHOT_DIR = Path(__file__).parent.parent.parent / "test_screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

PASS = "✅ PASS"
FAIL = "❌ FAIL"


def screenshot(page: Page, name: str) -> None:
    path = SCREENSHOT_DIR / f"redesign_{name}.png"
    page.screenshot(path=str(path))
    print(f"   📸  {path.name}")


def nav_to_main(page: Page) -> None:
    page.goto(APP_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)


def scroll_to_bottom(page: Page) -> None:
    page.evaluate("""
        const el = document.querySelector('[data-testid="stMainBlockContainer"]');
        if (el) el.scrollTop = el.scrollHeight;
    """)
    page.wait_for_timeout(500)


def click_sidebar_radio(page: Page, label: str) -> None:
    """Click a sidebar radio button by its visible label text."""
    page.locator(f'[data-testid="stSidebar"] label').filter(has_text=label).first.click()
    page.wait_for_timeout(1500)


def click_sidebar_selectbox_option(page: Page, option_text: str) -> None:
    """Open the sidebar selectbox and pick an option."""
    # Click the selectbox to open it
    page.locator('[data-testid="stSidebar"] [data-baseweb="select"]').first.click()
    page.wait_for_timeout(500)
    page.locator(f'[role="option"]').filter(has_text=option_text).first.click()
    page.wait_for_timeout(1500)


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

results: list[tuple[str, str, str]] = []


def test(name: str, ok: bool, detail: str = "") -> None:
    status = PASS if ok else FAIL
    results.append((name, status, detail))
    print(f"  {status}  {name}" + (f" — {detail}" if detail else ""))


def run_settings_hpc_port(page: Page) -> None:
    print("\n[1] Settings → HPC tab — Port field")
    nav_to_main(page)

    # Navigate to Settings
    click_sidebar_radio(page, "⚙️ Settings")
    page.wait_for_timeout(1000)

    # Click HPC Connection Settings tab
    tabs = page.locator('[data-baseweb="tab"]')
    for i in range(tabs.count()):
        if "HPC" in (tabs.nth(i).inner_text() or ""):
            tabs.nth(i).click()
            break
    page.wait_for_timeout(1000)
    screenshot(page, "01_settings_hpc")

    # Check the label "Port" is present in the HPC section
    port_label = page.get_by_text("Port", exact=False)
    test("'Port' label visible in HPC settings", port_label.count() > 0)

    # Port spinbutton should exist and show a valid port number
    port_inputs = page.locator('input[type="number"]')
    test("HPC Port spinbutton present", port_inputs.count() > 0)
    if port_inputs.count() > 0:
        val = port_inputs.first.input_value()
        test("Port value is a valid integer", val.isdigit(), f"value={val}")


def run_pipeline_gates_split(page: Page) -> None:
    print("\n[2] Main page — Pipeline gates split into fMRI / dMRI")
    nav_to_main(page)
    screenshot(page, "02_main_pipeline_gates")

    fmri_gate = page.get_by_text("fMRI", exact=False).first
    test("'fMRI' gate label visible on main page", fmri_gate.count() > 0)

    dmri_gate = page.get_by_text("dMRI", exact=False)
    test("'dMRI' gate label visible on main page", dmri_gate.count() > 0)


def run_subject_data_page(page: Page) -> None:
    print("\n[3] Subject Data page")
    nav_to_main(page)

    # Data QC modality in sidebar
    click_sidebar_radio(page, "🔍 Data QC")
    page.wait_for_timeout(1000)

    # Look for Subject Data in any sub-selector
    subj_option = page.locator('[data-testid="stSidebar"]').get_by_text("Subject Data", exact=False)
    if subj_option.count() > 0:
        subj_option.first.click()
        page.wait_for_timeout(2000)
    else:
        # Try selectbox
        click_sidebar_selectbox_option(page, "Subject Data")

    screenshot(page, "03_subject_data")

    # Should show a dataframe with subject data
    df = page.locator('[data-testid="stDataFrame"]')
    test("Subject Data table visible", df.count() > 0)

    # Should show group column
    group_text = page.get_by_text("group", exact=False).first
    test("'group' column visible in Subject Data table", group_text.count() > 0)

    # Save button should be visible (may be greyed out until edit)
    save_btn = page.get_by_role("button").filter(has_text="Save")
    test("Save button present on Subject Data page", save_btn.count() > 0)

    # Upload section — scroll down first; Streamlit uses stFileUploaderDropzone (not stFileUploadDropzone)
    scroll_to_bottom(page)
    page.wait_for_timeout(500)
    upload = page.locator('[data-testid="stFileUploaderDropzone"]')
    test("CSV upload widget present", upload.count() > 0)


def run_fmri_dashboard(page: Page) -> None:
    print("\n[4] fMRI Dashboard")
    nav_to_main(page)

    click_sidebar_radio(page, "🧠 fMRI")
    page.wait_for_timeout(1000)

    # Try to navigate to fMRI Dashboard
    preprocessing_selector = page.locator('[data-testid="stSidebar"] [data-baseweb="select"]')
    if preprocessing_selector.count() > 0:
        preprocessing_selector.first.click()
        page.wait_for_timeout(500)
        dashboard_opt = page.locator('[role="option"]').filter(has_text="Dashboard")
        if dashboard_opt.count() > 0:
            dashboard_opt.first.click()
        else:
            # Try without "Dashboard" — look for first option
            page.locator('[role="option"]').first.click()
        page.wait_for_timeout(2000)

    screenshot(page, "04_fmri_dashboard")

    # Should show participant table
    df = page.locator('[data-testid="stDataFrame"]')
    test("fMRI Dashboard table visible", df.count() > 0)

    # Rescan button
    rescan = page.get_by_role("button").filter(has_text="Rescan")
    test("Rescan button present on fMRI Dashboard", rescan.count() > 0)

    # fMRIPrep column header
    fmriprep_text = page.get_by_text("fMRIPrep", exact=False)
    test("'fMRIPrep' column present in dashboard", fmriprep_text.count() > 0)


def run_xcpd_pipeline(page: Page) -> None:
    print("\n[5] XCP-D Pipeline — tooltips, renamed heading, subject status")
    nav_to_main(page)

    click_sidebar_radio(page, "🧠 fMRI")
    page.wait_for_timeout(1000)

    # Navigate to XCP-D Pipeline
    preprocessing_selector = page.locator('[data-testid="stSidebar"] [data-baseweb="select"]')
    if preprocessing_selector.count() > 0:
        preprocessing_selector.first.click()
        page.wait_for_timeout(500)
        xcpd_opt = page.locator('[role="option"]').filter(has_text="XCP-D")
        if xcpd_opt.count() > 0:
            xcpd_opt.first.click()
        page.wait_for_timeout(2000)

    screenshot(page, "05_xcpd_pipeline")

    # "Pipeline Progress" heading should be gone
    old_heading = page.get_by_text("Pipeline Progress", exact=True)
    test("Old heading 'Pipeline Progress' NOT present", old_heading.count() == 0)

    # "fMRI Pipeline Status" subheader was also removed — should not appear
    pipeline_status = page.get_by_text("fMRI Pipeline Status", exact=True)
    test("'fMRI Pipeline Status' subheader NOT present (removed)", pipeline_status.count() == 0)

    # Click XCP-D Runs tab to see auto-select buttons
    xcpd_runs_tab = page.get_by_role("tab", name="XCP-D Runs")
    if xcpd_runs_tab.count() > 0:
        xcpd_runs_tab.click()
        page.wait_for_timeout(2000)

    # Auto-select incomplete buttons should be present
    fc_incomplete_btn = page.get_by_role("button").filter(has_text="FC incomplete")
    test("'FC incomplete' auto-select button present", fc_incomplete_btn.count() > 0)

    ec_incomplete_btn = page.get_by_role("button").filter(has_text="EC incomplete")
    test("'EC incomplete' auto-select button present", ec_incomplete_btn.count() > 0)

    reset_btn = page.get_by_role("button").filter(has_text="Reset")
    test("'Reset' button present", reset_btn.count() > 0)

    # Tooltip icons (ⓘ) present on controls — need XCP-D Runs tab to be active
    tooltip_icons = page.locator('[data-testid="stTooltipIcon"]')
    test("Tooltip icons present on XCP-D controls", tooltip_icons.count() >= 3,
         f"found {tooltip_icons.count()} icons")

    # Subject Completion Status expander — scroll to it via JS, then click its summary
    page.evaluate("""
        const allExpanders = document.querySelectorAll('[data-testid="stExpander"]');
        for (const exp of allExpanders) {
            if (exp.textContent?.includes('Subject Completion Status')) {
                exp.scrollIntoView({ behavior: 'instant', block: 'center' });
                break;
            }
        }
    """)
    page.wait_for_timeout(500)

    # Check the expander exists by looking for its text
    status_text = page.get_by_text("Subject Completion Status", exact=False)
    test("'Subject Completion Status' expander present", status_text.count() > 0)

    # Open the expander via JS click on its summary element
    page.evaluate("""
        const allExpanders = document.querySelectorAll('[data-testid="stExpander"]');
        for (const exp of allExpanders) {
            if (exp.textContent?.includes('Subject Completion Status')) {
                const details = exp.querySelector('details');
                if (details && !details.open) {
                    const summary = details.querySelector('summary');
                    if (summary) summary.click();
                }
                break;
            }
        }
    """)
    page.wait_for_timeout(1500)
    screenshot(page, "06_xcpd_subject_status")

    # Should show FC / FC+GSR / EC tabs inside expander
    fc_tab = page.get_by_role("tab").filter(has_text="FC")
    test("FC tab visible in Subject Completion Status", fc_tab.count() > 0)


def run_node_tooltip(page: Page) -> None:
    print("\n[6] Node progress bar tooltip")
    # Navigate to XCP-D Pipeline and switch to XCP-D Runs tab
    nav_to_main(page)
    click_sidebar_radio(page, "🧠 fMRI")
    page.wait_for_timeout(1000)

    preprocessing_selector = page.locator('[data-testid="stSidebar"] [data-baseweb="select"]')
    if preprocessing_selector.count() > 0:
        preprocessing_selector.first.click()
        page.wait_for_timeout(500)
        xcpd_opt = page.locator('[role="option"]').filter(has_text="XCP-D")
        if xcpd_opt.count() > 0:
            xcpd_opt.first.click()
        page.wait_for_timeout(2000)

    # Switch to XCP-D Runs tab where the node progress bar appears
    xcpd_runs_tab = page.get_by_role("tab", name="XCP-D Runs")
    if xcpd_runs_tab.count() > 0:
        xcpd_runs_tab.click()
        page.wait_for_timeout(1500)

    # Node tooltip text is rendered inline below each Re-run button
    node_text = page.get_by_text("each node is one processing step", exact=False)
    test("Node tooltip text visible on progress bar", node_text.count() > 0)


def run_fmriprep_select_incomplete(page: Page) -> None:
    print("\n[7] fMRIPrep Submit — 'Select incomplete' option")
    nav_to_main(page)

    click_sidebar_radio(page, "🧠 fMRI")
    page.wait_for_timeout(1000)

    preprocessing_selector = page.locator('[data-testid="stSidebar"] [data-baseweb="select"]')
    if preprocessing_selector.count() > 0:
        preprocessing_selector.first.click()
        page.wait_for_timeout(500)
        submit_opt = page.locator('[role="option"]').filter(has_text="fMRIPrep Submit")
        if submit_opt.count() > 0:
            submit_opt.first.click()
        page.wait_for_timeout(2000)

    screenshot(page, "07_fmriprep_submit")

    incomplete_radio = page.get_by_text("Select incomplete", exact=True)
    test("'Select incomplete' radio option visible in fMRIPrep Submit", incomplete_radio.count() > 0)


def run_fmriprep_report_viewer(page: Page) -> None:
    print("\n[8] fMRIPrep QC Reports — inline HTML viewer")
    nav_to_main(page)

    click_sidebar_radio(page, "🧠 fMRI")
    page.wait_for_timeout(1000)

    preprocessing_selector = page.locator('[data-testid="stSidebar"] [data-baseweb="select"]')
    if preprocessing_selector.count() > 0:
        preprocessing_selector.first.click()
        page.wait_for_timeout(500)
        reports_opt = page.locator('[role="option"]').filter(has_text="fMRIPrep QC Reports")
        if reports_opt.count() > 0:
            reports_opt.first.click()
        page.wait_for_timeout(3000)

    screenshot(page, "08_fmriprep_reports")

    # Reports found heading
    reports_found = page.get_by_text("report", exact=False).filter(has_text="Found")
    test("Reports-found message visible in fMRIPrep viewer", reports_found.count() > 0)

    # Prev/Next buttons
    prev_btn = page.get_by_role("button").filter(has_text="Prev")
    next_btn = page.get_by_role("button").filter(has_text="Next")
    test("Prev navigation button present", prev_btn.count() > 0)
    test("Next navigation button present", next_btn.count() > 0)

    # Embedded iframe (HTML component)
    iframe = page.locator('iframe')
    test("Embedded report iframe present", iframe.count() > 0)


def run_xcpd_report_viewer(page: Page) -> None:
    print("\n[9] XCP-D QC Reports — two tabs + HTML report viewer")
    nav_to_main(page)

    click_sidebar_radio(page, "🧠 fMRI")
    page.wait_for_timeout(1000)

    preprocessing_selector = page.locator('[data-testid="stSidebar"] [data-baseweb="select"]')
    if preprocessing_selector.count() > 0:
        preprocessing_selector.first.click()
        page.wait_for_timeout(500)
        xcpdqc_opt = page.locator('[role="option"]').filter(has_text="XCP-D QC Reports")
        if xcpdqc_opt.count() > 0:
            xcpdqc_opt.first.click()
        page.wait_for_timeout(3000)

    screenshot(page, "09_xcpd_qc_reports")

    # Two tabs: QC Metrics and HTML Reports
    qc_metrics_tab = page.get_by_role("tab", name="QC Metrics")
    test("'QC Metrics' tab visible", qc_metrics_tab.count() > 0)

    html_reports_tab = page.get_by_role("tab", name="HTML Reports")
    test("'HTML Reports' tab visible", html_reports_tab.count() > 0)

    # Switch to HTML Reports tab
    if html_reports_tab.count() > 0:
        html_reports_tab.click()
        page.wait_for_timeout(2000)
    screenshot(page, "09b_xcpd_html_reports")

    # FC / FC+GSR / EC pipeline sub-tabs
    fc_tab = page.get_by_role("tab", name="FC")
    test("FC sub-tab visible in XCP-D HTML Reports", fc_tab.count() > 0)

    # Prev / Next navigation
    prev_btn = page.get_by_role("button").filter(has_text="Prev")
    test("Prev navigation button in XCP-D report viewer", prev_btn.count() > 0)

    # Should show sessions found
    sessions_text = page.get_by_text("sessions found", exact=False)
    test("Sessions-found message visible in XCP-D HTML viewer", sessions_text.count() > 0)


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

def main() -> None:
    print(f"NeuConn Workflow Redesign v2 — Playwright Smoke Tests")
    print(f"App URL  : {APP_URL}")
    print(f"Viewport : {VIEWPORT['width']}x{VIEWPORT['height']}")
    print(f"Screenshots → {SCREENSHOT_DIR}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(viewport=VIEWPORT)
        page = ctx.new_page()

        run_settings_hpc_port(page)
        run_pipeline_gates_split(page)
        run_subject_data_page(page)
        run_fmri_dashboard(page)
        run_xcpd_pipeline(page)
        run_node_tooltip(page)
        run_fmriprep_select_incomplete(page)
        run_fmriprep_report_viewer(page)
        run_xcpd_report_viewer(page)

        ctx.close()
        browser.close()

    print("\n" + "=" * 60)
    total = len(results)
    passed = sum(1 for _, s, _ in results if s == PASS)
    failed = total - passed
    print(f"Results: {passed}/{total} passed  ({failed} failed)")
    print("=" * 60)
    if failed:
        print("\nFailed tests:")
        for name, status, detail in results:
            if status == FAIL:
                print(f"  {FAIL}  {name}" + (f" — {detail}" if detail else ""))
        sys.exit(1)
    else:
        print("All tests passed!")


if __name__ == "__main__":
    main()
