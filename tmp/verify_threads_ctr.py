
import sys
import os

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from analysis.skeleton_builder import build_threads_teaser

def verify_ctr_optimization():
    print("--- THREADS CTR OPTIMIZATION VERIFICATION (V2) ---")
    
    theme = "Strategic Infrastructure Vulnerability"
    event = "Satellite Imagery Reveals New Damage to Transit Nodes"
    url = "https://osint-platform.com/reports/123"
    
    # Testing all differentiated domains
    domains = [
        "energy_resource_risk",
        "global_market_intelligence",
        "geopolitics",
        "supply_chain_intelligence"
    ]
    
    domain_outputs = {d: [] for d in domains}
    events = [
        "Satellite Imagery Reveals New Damage to Transit Nodes",
        "Ground Reports Confirm Disruption at Key Hubs",
        "Logistics Data Indicates Sustained Flow Reduction"
    ]
    
    for domain in domains:
        print(f"\n--- AUDIT: {domain} ---")
        for i, ev in enumerate(events):
            post = build_threads_teaser(ev, theme, domain, url)
            domain_outputs[domain].append(post)
            
            if i == 0: # Print only first run for brevity
                print(post.replace('\u2014', '--'))
        print("-" * 20)

    # 1. Variety check
    print("\n--- ROTATION VARIETY CHECK ---")
    for d, posts in domain_outputs.items():
        unique_posts = len(set(posts))
        print(f"{d}: {unique_posts}/{len(posts)} unique templates used.")

    # 2. Consequence Sharpness check
    # Check for core keywords from rewritten WHY_IT_MATTERS_TEMPLATES
    sharpened_keywords = [
        "sanctions exposure", 
        "pricing volatility", 
        "production stability", 
        "refinery output stability",
        "regional security posture"
    ]
    
    all_text = "\n".join(["\n".join(ps) for ps in domain_outputs.values()])
    found_keywords = [k for k in sharpened_keywords if k in all_text]
    
    print(f"\nConsequence Sharpness Check: Found keywords {found_keywords}")
    success = len(found_keywords) >= 4
    
    if success:
        print("[SUCCESS] Sharpened consequence framing is active cross-domain.")
    else:
        print("[FAIL] Missing sharpened framing for some domains.")

if __name__ == "__main__":
    verify_ctr_optimization()
