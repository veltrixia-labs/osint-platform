
import sys
import os

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from analysis.skeleton_builder import build_threads_teaser

def audit_examples():
    print("--- THREADS POST AUDIT: CURRENT SYSTEM OUTPUTS ---")
    
    theme = "Strategic Infrastructure Vulnerability"
    event = "Satellite Imagery Reveals New Damage to Transit Nodes"
    url = "https://osint-platform.com/reports/123"
    
    domains = [
        "energy_resource_risk",
        "global_market_intelligence",
        "geopolitics"
    ]
    
    for domain in domains:
        print(f"\n--- DOMAIN: {domain} ---")
        post = build_threads_teaser(event, theme, domain, url)
        print(post)
        print("-" * 40)

if __name__ == "__main__":
    audit_examples()
