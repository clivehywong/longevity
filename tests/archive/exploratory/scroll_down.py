import asyncio
from playwright.async_api import async_playwright

async def scroll_and_check():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto('http://localhost:8520')
        await page.wait_for_load_state('networkidle')
        
        # Navigate to Submit Seed Connectivity
        await page.click('text=🧠 fMRI Analysis')
        await page.click('text=👤 Subject-Level')
        await page.wait_for_load_state('networkidle')
        
        # Find and click Submit Seed Connectivity
        dropdown = page.locator('select[aria-label*="Analysis"]').first
        if await dropdown.count() > 0:
            await dropdown.select_option(label='📤 Submit Seed Connectivity')
        else:
            # Try clicking directly on the text
            await page.click('text=Submit Seed Connectivity')
        
        await page.wait_for_load_state('networkidle')
        
        # Scroll down to find Local/HPC selector
        await page.evaluate('() => window.scrollBy(0, 1000)')
        await page.wait_for_timeout(500)
        
        # Check page content for "Local" and "HPC"
        text = await page.inner_text('body')
        
        if 'Local' in text and 'HPC' in text:
            print("Found Local and HPC on page")
            # Look for radio group
            radio_groups = await page.query_selector_all('[role="radiogroup"]')
            print(f"Found {len(radio_groups)} radio groups")
        else:
            print("Local and HPC not found. Scrolling down more...")
            await page.evaluate('() => window.scrollBy(0, 1000)')
            await page.wait_for_timeout(500)
            text = await page.inner_text('body')
            print("Checking again...")
            if 'Local' in text and 'HPC' in text:
                print("Found Local and HPC after scrolling")
            else:
                print("Still not found")
        
        await page.screenshot(path='test_screenshots/submit_page_full.png', full_page=True)
        
        await browser.close()

asyncio.run(scroll_and_check())
