
import asyncio
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, AsyncMock

# Add parent dir to path for imports
sys.path.append(os.getcwd())

# Mock logic of the selection filter
def normalize_theme_key(text: str) -> str:
    if not text: return ""
    import re
    t = text.lower()
    t = re.sub(r'[^\w\s]', '', t)
    return " ".join(t.split()).strip()

async def should_post_social_mock(avg_score, top_theme, recent_posts):
    norm_theme = normalize_theme_key(top_theme)
    should_post = True
    reason = None

    if avg_score < 0.6:
        should_post = False
        reason = f"Low intensity ({avg_score:.2f})"
    elif not norm_theme or len(norm_theme.split()) < 2 or "summary" in norm_theme or "latest" in norm_theme:
        should_post = False
        reason = f"Generic or weak theme ('{top_theme}')"
    else:
        # Novelty Check
        if norm_theme in recent_posts:
            should_post = False
            reason = f"Recent duplicate theme ('{norm_theme}')"

    return should_post, reason

async def test_selection():
    print("--- STARTING SOCIAL SELECTION VERIFICATION ---")
    
    # Recent Posts Mock (Simulation of ExternalPost history)
    recent_posts = ["iran energy risk", "supply chain breakdown"]
    
    test_cases = [
        {"score": 0.4, "theme": "Major Energy Shift", "expect": False, "desc": "Low Intensity"},
        {"score": 0.8, "theme": "Summary", "expect": False, "desc": "Generic Theme"},
        {"score": 0.8, "theme": "Iran Energy Risk", "expect": False, "desc": "Recent Duplicate (Normalized)"},
        {"score": 0.9, "theme": "Saudi Oil Facility Security", "expect": True, "desc": "High Intensity & Unique"},
        {"score": 0.7, "theme": "Strategic Infrastructure Friction", "expect": True, "desc": "Valid Signal"}
    ]
    
    for tc in test_cases:
        actual, reason = await should_post_social_mock(tc["score"], tc["theme"], recent_posts)
        status = "PASS" if actual == tc["expect"] else "FAIL"
        print(f"[{status}] {tc['desc']} | Theme: {tc['theme']} | Score: {tc['score']} | Result: {actual} | Reason: {reason}")

if __name__ == "__main__":
    asyncio.run(test_selection())
