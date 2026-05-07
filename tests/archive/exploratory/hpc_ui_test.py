#!/usr/bin/env python3
"""
HPC Selection UI and Re-upload Checkbox Test
Tests Local/HPC radio button selector and re-upload XCP-D checkbox behavior
"""
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

# Test results storage
test_results = {
    "test_name": "HPC Selection & Re-upload Checkbox Testing",
    "timestamp": "",
    "test_cases": [],
    "overall_status": "PENDING"
}

async def navigate_to_submit_seed_connectivity(page):
    """Navigate to Submit Seed Connectivity page"""
    print("[*] Navigating to Submit Seed Connectivity page...")
    
    await page.goto('http://localhost:8520')
    await page.wait_for_load_state('networkidle')
    print("  ✓ Home page loaded")
    
    # Click fMRI Analysis
    try:
        await page.click('text=🧠 fMRI Analysis')
        await page.wait_for_timeout(1000)
        print("  ✓ Clicked fMRI Analysis")
    except Exception as e:
        print(f"  ✗ Failed to click fMRI Analysis: {e}")
        return False
    
    # Click Subject-Level
    try:
        await page.click('text=👤 Subject-Level')
        await page.wait_for_timeout(1000)
        print("  ✓ Clicked Subject-Level")
    except Exception as e:
        print(f"  ✗ Failed to click Subject-Level: {e}")
        return False
    
    # Click on Analysis selectbox and select Submit Seed Connectivity
    try:
        # Wait for the selectbox and click
        selectbox = page.locator('select').first
        await selectbox.click()
        await page.wait_for_timeout(500)
        
        # Select the option by value or label
        options = await page.locator('select option').all()
        for option in options:
            text = await option.inner_text()
            if 'Submit Seed' in text:
                value = await option.get_attribute('value')
                await selectbox.select_option(value=value)
                print(f"  ✓ Selected option: {text}")
                break
        
        await page.wait_for_load_state('networkidle')
        await page.wait_for_timeout(1000)
    except Exception as e:
        print(f"  ✗ Failed to select Submit Seed Connectivity: {e}")
        return False
    
    return True

async def test_local_hpc_visibility(page):
    """Test 1: Local/HPC Radio Visibility"""
    test_case = {
        "id": "test_1",
        "name": "Local/HPC Radio Visibility",
        "status": "RUNNING",
        "details": {}
    }
    
    try:
        print("\n[TEST 1] Local/HPC Radio Visibility")
        
        # Scroll to find the radio button section
        await page.evaluate('() => { const elem = document.body.querySelector("[value*=Local]") || document.body.querySelector("label:has-text(Local)"); if (elem) elem.scrollIntoView({behavior: "smooth", block: "center"}); }')
        await page.wait_for_timeout(1000)
        
        # Find radio buttons
        body_text = await page.inner_text('body')
        
        if 'Local' in body_text and 'HPC' in body_text:
            test_case["details"]["radio_labels_visible"] = True
            print("  ✓ Found 'Local' and 'HPC' text on page")
        else:
            test_case["details"]["radio_labels_visible"] = False
            print("  ✗ Did not find 'Local' and 'HPC' text")
            test_case["status"] = "FAILED"
            return test_case
        
        # Check for radio buttons
        radios = await page.locator('[role="radio"]').all()
        test_case["details"]["radio_buttons_count"] = len(radios)
        print(f"  ✓ Found {len(radios)} radio buttons")
        
        # Take screenshot
        await page.screenshot(path='tmp/test1_radio_visibility.png', full_page=False)
        test_case["details"]["screenshot"] = "test1_radio_visibility.png"
        
        test_case["status"] = "PASSED"
        
    except Exception as e:
        test_case["status"] = "FAILED"
        test_case["details"]["error"] = str(e)
        print(f"  ✗ Test failed: {e}")
    
    return test_case

async def test_local_selected_no_checkbox(page):
    """Test 2: Local Radio Selected — No Re-upload Checkbox"""
    test_case = {
        "id": "test_2",
        "name": "Local Radio Selected — No Re-upload Checkbox",
        "status": "RUNNING",
        "details": {}
    }
    
    try:
        print("\n[TEST 2] Local Radio Selected — No Re-upload Checkbox")
        
        # Find and click Local radio button
        local_radio = page.locator('[role="radio"]:has-text("Local")').first
        await local_radio.click()
        await page.wait_for_timeout(500)
        
        # Check if it's selected
        is_selected = await local_radio.get_attribute('aria-checked')
        test_case["details"]["local_selected"] = is_selected == 'true'
        print(f"  ✓ Local radio selected: {is_selected == 'true'}")
        
        # Check if checkbox is hidden
        body_text = await page.inner_text('body')
        checkbox_visible = 'Re-upload' in body_text
        test_case["details"]["reupload_checkbox_visible"] = checkbox_visible
        
        if not checkbox_visible:
            print("  ✓ Re-upload checkbox is NOT visible (expected)")
            test_case["status"] = "PASSED"
        else:
            print("  ✗ Re-upload checkbox IS visible (unexpected)")
            test_case["status"] = "WARNING"
        
        # Take screenshot
        await page.screenshot(path='tmp/test2_local_no_checkbox.png', full_page=False)
        test_case["details"]["screenshot"] = "test2_local_no_checkbox.png"
        
    except Exception as e:
        test_case["status"] = "FAILED"
        test_case["details"]["error"] = str(e)
        print(f"  ✗ Test failed: {e}")
    
    return test_case

async def test_hpc_selected_checkbox_appears(page):
    """Test 3: HPC Radio Selected — Re-upload Checkbox Appears"""
    test_case = {
        "id": "test_3",
        "name": "HPC Radio Selected — Re-upload Checkbox Appears",
        "status": "RUNNING",
        "details": {}
    }
    
    try:
        print("\n[TEST 3] HPC Radio Selected — Re-upload Checkbox Appears")
        
        # Find and click HPC radio button
        hpc_radio = page.locator('[role="radio"]:has-text("HPC")').first
        await hpc_radio.click()
        await page.wait_for_timeout(500)
        
        # Check if it's selected
        is_selected = await hpc_radio.get_attribute('aria-checked')
        test_case["details"]["hpc_selected"] = is_selected == 'true'
        print(f"  ✓ HPC radio selected: {is_selected == 'true'}")
        
        # Check if checkbox is visible
        body_text = await page.inner_text('body')
        checkbox_visible = 'Re-upload' in body_text
        test_case["details"]["reupload_checkbox_visible"] = checkbox_visible
        
        if checkbox_visible:
            print("  ✓ Re-upload checkbox IS visible (expected)")
            
            # Check if checkbox is unchecked by default
            checkbox = page.locator('[role="checkbox"]').filter(has_text='Re-upload').first
            is_checked = await checkbox.get_attribute('aria-checked')
            test_case["details"]["checkbox_checked_by_default"] = is_checked == 'true'
            print(f"  ✓ Checkbox checked by default: {is_checked == 'true'}")
            
            # Verify label
            checkbox_label = await checkbox.inner_text()
            test_case["details"]["checkbox_label"] = checkbox_label[:100]
            print(f"  ✓ Checkbox label: {checkbox_label[:80]}...")
            
            test_case["status"] = "PASSED"
        else:
            print("  ✗ Re-upload checkbox is NOT visible (unexpected)")
            test_case["status"] = "FAILED"
        
        # Take screenshot
        await page.screenshot(path='tmp/test3_hpc_checkbox_appears.png', full_page=False)
        test_case["details"]["screenshot"] = "test3_hpc_checkbox_appears.png"
        
    except Exception as e:
        test_case["status"] = "FAILED"
        test_case["details"]["error"] = str(e)
        print(f"  ✗ Test failed: {e}")
    
    return test_case

async def test_toggle_local_hpc(page):
    """Test 4: Toggle Between Local & HPC"""
    test_case = {
        "id": "test_4",
        "name": "Toggle Between Local & HPC",
        "status": "RUNNING",
        "details": {}
    }
    
    try:
        print("\n[TEST 4] Toggle Between Local & HPC")
        
        # Start with Local
        local_radio = page.locator('[role="radio"]:has-text("Local")').first
        await local_radio.click()
        await page.wait_for_timeout(300)
        body_text = await page.inner_text('body')
        local_no_checkbox = 'Re-upload' not in body_text
        test_case["details"]["local_no_checkbox"] = local_no_checkbox
        print(f"  ✓ Local: No checkbox visible = {local_no_checkbox}")
        
        # Switch to HPC
        hpc_radio = page.locator('[role="radio"]:has-text("HPC")').first
        await hpc_radio.click()
        await page.wait_for_timeout(300)
        body_text = await page.inner_text('body')
        hpc_checkbox_visible = 'Re-upload' in body_text
        test_case["details"]["hpc_checkbox_visible"] = hpc_checkbox_visible
        print(f"  ✓ HPC: Checkbox visible = {hpc_checkbox_visible}")
        
        # Switch back to Local
        local_radio = page.locator('[role="radio"]:has-text("Local")').first
        await local_radio.click()
        await page.wait_for_timeout(300)
        body_text = await page.inner_text('body')
        local_no_checkbox_again = 'Re-upload' not in body_text
        test_case["details"]["local_no_checkbox_again"] = local_no_checkbox_again
        print(f"  ✓ Local (again): No checkbox visible = {local_no_checkbox_again}")
        
        if local_no_checkbox and hpc_checkbox_visible and local_no_checkbox_again:
            test_case["status"] = "PASSED"
        else:
            test_case["status"] = "FAILED"
        
        # Take final screenshot
        await page.screenshot(path='tmp/test4_toggle_complete.png', full_page=False)
        test_case["details"]["screenshot"] = "test4_toggle_complete.png"
        
    except Exception as e:
        test_case["status"] = "FAILED"
        test_case["details"]["error"] = str(e)
        print(f"  ✗ Test failed: {e}")
    
    return test_case

async def test_checkbox_toggle(page):
    """Test 5: Re-upload Checkbox Toggle"""
    test_case = {
        "id": "test_5",
        "name": "Re-upload Checkbox Toggle",
        "status": "RUNNING",
        "details": {}
    }
    
    try:
        print("\n[TEST 5] Re-upload Checkbox Toggle")
        
        # Make sure HPC is selected
        hpc_radio = page.locator('[role="radio"]:has-text("HPC")').first
        await hpc_radio.click()
        await page.wait_for_timeout(300)
        
        # Find checkbox
        checkbox = page.locator('[role="checkbox"]').filter(has_text='Re-upload').first
        
        # Check initial state
        initial_checked = await checkbox.get_attribute('aria-checked')
        test_case["details"]["initial_state"] = initial_checked
        print(f"  ✓ Initial checkbox state: {initial_checked}")
        
        # Toggle checkbox (click)
        await checkbox.click()
        await page.wait_for_timeout(300)
        after_click = await checkbox.get_attribute('aria-checked')
        test_case["details"]["after_first_click"] = after_click
        print(f"  ✓ After click: {after_click}")
        
        # Toggle again
        await checkbox.click()
        await page.wait_for_timeout(300)
        after_second_click = await checkbox.get_attribute('aria-checked')
        test_case["details"]["after_second_click"] = after_second_click
        print(f"  ✓ After second click: {after_second_click}")
        
        if initial_checked != after_click and after_click != after_second_click:
            test_case["status"] = "PASSED"
            print("  ✓ Checkbox toggle working correctly")
        else:
            test_case["status"] = "WARNING"
            print("  ⚠ Checkbox toggle may not be working")
        
        # Take screenshot
        await page.screenshot(path='tmp/test5_checkbox_toggle.png', full_page=False)
        test_case["details"]["screenshot"] = "test5_checkbox_toggle.png"
        
    except Exception as e:
        test_case["status"] = "FAILED"
        test_case["details"]["error"] = str(e)
        print(f"  ✗ Test failed: {e}")
    
    return test_case

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        
        try:
            # Navigate to page
            if not await navigate_to_submit_seed_connectivity(page):
                print("[!] Failed to navigate to page. Stopping tests.")
                test_results["overall_status"] = "FAILED_TO_NAVIGATE"
                return
            
            # Run tests
            test_results["test_cases"].append(await test_local_hpc_visibility(page))
            test_results["test_cases"].append(await test_local_selected_no_checkbox(page))
            test_results["test_cases"].append(await test_hpc_selected_checkbox_appears(page))
            test_results["test_cases"].append(await test_toggle_local_hpc(page))
            test_results["test_cases"].append(await test_checkbox_toggle(page))
            
            # Calculate overall status
            failed_count = sum(1 for tc in test_results["test_cases"] if tc["status"] == "FAILED")
            warning_count = sum(1 for tc in test_results["test_cases"] if tc["status"] == "WARNING")
            passed_count = sum(1 for tc in test_results["test_cases"] if tc["status"] == "PASSED")
            
            if failed_count > 0:
                test_results["overall_status"] = "FAILED"
            elif warning_count > 0:
                test_results["overall_status"] = "WARNING"
            else:
                test_results["overall_status"] = "PASSED"
            
            print(f"\n[SUMMARY] Passed: {passed_count}, Warning: {warning_count}, Failed: {failed_count}")
            print(f"[OVERALL] {test_results['overall_status']}")
            
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
    
    # Print test results
    print("\n" + "="*80)
    print("TEST RESULTS JSON:")
    print("="*80)
    print(json.dumps(test_results, indent=2))

