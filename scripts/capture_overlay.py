import asyncio
from playwright.async_api import async_playwright
import os

async def capture_overlay():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()
        
        # Navigate to app
        await page.goto("http://localhost:5173")
        await page.wait_for_selector("input[type='text']")
        
        # Login
        await page.fill("input[type='text']", "12345")
        await page.fill("input[type='password']", "analyst_password_2026")
        await page.click("button >> text=Login")
        
        # Wait for dashboard
        await page.wait_for_selector("#topic-tabs-container", timeout=10000)
        
        # Click on AI & Semiconductors (Experts only)
        # The tab has key 'ai_semiconductor_intelligence' which is the 5th tab (0-indexed 4 or 5)
        # We'll use the text
        await page.click("div >> text=AI & Semiconductors")
        
        # Wait for overlay
        await page.wait_for_selector(".locked-topic-overlay", timeout=5000)
        
        # Capture screenshot
        screenshot_path = r"C:\Users\Owner\.gemini\antigravity\brain\44ca45c6-3f0c-42b6-b3e4-6e67c573a130\expert_overlay_final_verif.png"
        await page.screenshot(path=screenshot_path)
        print(f"Screenshot saved to {screenshot_path}")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_overlay())
