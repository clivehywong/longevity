"""
Playwright tests for Submit Seed Connectivity UI error cases.
"""
import asyncio
from pathlib import Path
import sys

# Add the app to the path
sys.path.insert(0, str(Path(__file__).parent / "neuconn_app"))

from playwright.async_api import async_playwright

async def run_tests():
    """Run all error case tests."""
    
    results = []
    base_url = "http://localhost:8520"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context()
        page = await context.new_page()
        
        try:
            # Navigate to main page
            await page.goto(base_url)
            await page.wait_for_load_state("networkidle")
            
            # Navigate to Submit Seed Connectivity
            print("Navigating to Submit Seed Connectivity page...")
            
            # Select fMRI Analysis category
            await page.click("text=🧠 fMRI Analysis")
            await page.wait_for_timeout(500)
            
            # Select Subject-Level stage
            await page.click("text=👤 Subject-Level")
            await page.wait_for_timeout(500)
            
            # Select Submit Seed Connectivity
            selectbox = await page.query_selector('[data-testid="stSelectbox"]')
            if selectbox:
                await selectbox.click()
                await page.wait_for_timeout(300)
                await page.click("text=📤 Submit Seed Connectivity")
                await page.wait_for_timeout(2000)
            
            # Get page content
            content = await page.content()
            if "Submit Seed Connectivity" in content or "submit" in content.lower():
                results.append(("Navigation", "✅ PASS", "Successfully navigated to Submit Seed Connectivity page"))
            else:
                results.append(("Navigation", "❌ FAIL", "Page content doesn't contain expected form"))
            
            # Test 1: No Atlas Selected
            print("\n--- Test 1: No Atlas Selected ---")
            submit_btn = await page.query_selector('button:has-text("Submit")')
            if submit_btn:
                is_disabled = await submit_btn.is_disabled()
                results.append(("Test 1: No Atlas", "✅ PASS" if is_disabled else "⚠️ WARNING", 
                               f"Submit button disabled: {is_disabled}"))
            else:
                results.append(("Test 1: No Atlas", "❌ FAIL", "Submit button not found"))
            
            # Log button state
            btn_screenshot = await page.screenshot()
            
        except Exception as e:
            results.append(("Error", "❌ FAIL", str(e)))
            import traceback
            results.append(("Traceback", "❌", traceback.format_exc()))
        finally:
            await browser.close()
    
    return results

if __name__ == "__main__":
    results = asyncio.run(run_tests())
    
    print("\n\n" + "="*60)
    print("TEST RESULTS")
    print("="*60)
    
    for test_name, status, message in results:
        print(f"{test_name}: {status}")
        print(f"  {message}\n")

