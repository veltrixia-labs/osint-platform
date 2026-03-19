import sys
import os
sys.path.append(os.getcwd())

from analysis.skeleton_builder import build_threads_teaser

# Sample data
test_cases = [
    {
        "title": "Iran threatens to close Strait of Hormuz amid naval tensions",
        "theme": "Shipping Risk",
        "category": "geopolitics"
    },
    {
        "title": "US Navy deployments in South China Sea increase",
        "theme": "Naval Pressure",
        "category": "geopolitics"
    },
    {
        "title": "Microsoft warns of new zero-day vulnerability in infrastructure",
        "theme": "Attribution Risk",
        "category": "cyber"
    },
    {
        "title": "Fed signals potential rate pressure following inflation data",
        "theme": "Liquidity Strain",
        "category": "economy"
    }
]

print("--- Testing Phase 14 Risk Headlines ---")
for i, case in enumerate(test_cases):
    teaser = build_threads_teaser(
        case["title"],
        case["theme"],
        case["category"],
        "https://substack.com/test"
    )
    print(f"\n[Test Case {i+1} - {case['category']}]")
    print(teaser.split('\n')[0]) # Only print L1 for clarity
