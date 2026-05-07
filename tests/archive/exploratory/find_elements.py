import asyncio
from playwright.async_api import async_playwright

async def find_controls():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        await page.goto('http://localhost:8520')
        await page.wait_for_load_state('networkidle')
        
        # Check if "Execution target" is visible
        exec_target_text = await page.locator('text=Execution target').first
        if await exec_target_text.count() > 0:
            print("✓ Found 'Execution target' heading")
            # Scroll it into view
            await exec_target_text.scroll_into_view_if_needed()
            print("✓ Scrolled into view")
        
        # Find Local and HPC text
        body_text = await page.inner_text('body')
        if 'Local' in body_text:
            print("✓ Found 'Local' text")
        if 'HPC' in body_text:
            print("✓ Found 'HPC' text")
        if 'Re-upload' in body_text:
            print("✓ Found 'Re-upload' text")
        
        # Take a screenshot
        await page.screenshot(path='tmp/execution_target.png', full_page=False)
        print("✓ Screenshot saved to tmp/execution_target.png")
        
        await browser.close()

asyncio.run(find_controls())
