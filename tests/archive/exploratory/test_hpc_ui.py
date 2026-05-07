import asyncio
import json
from playwright.async_api import async_playwright

async def test_hpc_ui():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # Navigate to the app
        await page.goto('http://localhost:8520')
        await page.wait_for_load_state('networkidle')
        
        # Take initial screenshot
        await page.screenshot(path='test_screenshots/01_home_page.png', full_page=True)
        
        # Step 1: Click fMRI Analysis
        await page.click('text=🧠 fMRI Analysis')
        await page.wait_for_load_state('networkidle')
        await page.screenshot(path='test_screenshots/02_fmri_analysis.png', full_page=True)
        
        # Step 2: Click on "👤 Subject-Level" radio button
        await page.click('text=👤 Subject-Level')
        await page.wait_for_load_state('networkidle')
        await page.screenshot(path='test_screenshots/03_subject_level.png', full_page=True)
        
        # Step 3: Find and click "📤 Submit Seed Connectivity" in the Analysis selectbox
        # First, click on the selectbox
        selectbox_locator = page.locator('select').filter(has_text='Submit Seed Connectivity').first
        
        # Wait for the selectbox and click
        analysis_select = await page.locator('xpath=//select[contains(., "Submit Seed Connectivity") or contains(., "Local Measures")]').first
        if analysis_select:
            await analysis_select.click()
        else:
            # Try finding by text
            await page.click('text=📤 Submit Seed Connectivity')
        
        await page.wait_for_load_state('networkidle')
        await page.screenshot(path='test_screenshots/04_submit_seed_connectivity.png', full_page=True)
        
        print("Navigation screenshots saved")
        
        await browser.close()

asyncio.run(test_hpc_ui())
