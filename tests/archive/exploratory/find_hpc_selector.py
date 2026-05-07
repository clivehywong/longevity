import asyncio
from playwright.async_api import async_playwright

async def find_selector():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        # Reuse existing page
        await page.goto('http://localhost:8520')
        
        # Get all body text to search for "Local" and "HPC"
        body_text = await page.inner_text('body')
        
        if 'Local' in body_text and 'HPC' in body_text:
            print("✓ Found Local and HPC text on page")
            
            # Find radio buttons or buttons
            radios = await page.locator('[role="radio"]').all()
            print(f"Found {len(radios)} radio buttons")
            
            # Find all text containing "Local" or "HPC"
            local_elements = await page.locator('text=/Local|HPC/').all()
            print(f"Found {len(local_elements)} elements with Local/HPC")
            
            # Print element details
            for elem in local_elements[:5]:
                try:
                    tag = await elem.evaluate('el => el.tagName')
                    text = await elem.inner_text()
                    print(f"  - {tag}: {text[:50]}")
                except:
                    pass
        else:
            print("✗ Local and HPC not found on page")
            
            # Check what text is visible
            lines = [l.strip() for l in body_text.split('\n') if l.strip()]
            print(f"Total {len(lines)} lines of text")
            print("Last 10 lines:")
            for line in lines[-10:]:
                print(f"  {line[:80]}")
        
        await browser.close()

asyncio.run(find_selector())
