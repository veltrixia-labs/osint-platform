
import asyncio
import os
import sys
from typing import List, Dict

# Add parent dir to path for imports
sys.path.append(os.getcwd())

from analysis.scenario_engine import generate_scenarios
from analysis.skeleton_builder import build_substack_skeleton

def test_differentiation():
    print("--- STARTING DOMAIN DIFFERENTIATION VERIFICATION (FIXED) ---")
    
    # Mock Input Data
    themes = ["energy infrastructure disruption", "supply chain bottleneck", "regional tensions"]
    developments = ["Major pipeline incident reported", "Shipping delays in key corridors", "Diplomatic signals intensify"]
    forecasts = [
        {"implication": "energy production volatility", "evidence": "Recent facility alerts", "confidence": "High"},
        {"implication": "supply chain pressure", "evidence": "Transit node data", "confidence": "Medium"}
    ]
    avg_score = 0.7
    sources = ["Source A", "Source B"]
    
    # 1. Generate for Energy Domain
    energy_scenarios = generate_scenarios(avg_score, forecasts, domain="energy_resource_risk")
    energy_skeleton = build_substack_skeleton(
        themes, developments, forecasts, energy_scenarios, sources, domain="energy_resource_risk"
    )
    
    # Extract sections
    energy_exec = energy_skeleton.split("# Executive Summary")[1].split("# Key Actions")[0].strip()
    energy_actions = energy_skeleton.split("# Key Actions")[1].split("# Key Developments")[0].strip()
    
    # 2. Generate for Geopolitics Domain
    geo_scenarios = generate_scenarios(avg_score, forecasts, domain="geopolitics")
    geo_skeleton = build_substack_skeleton(
        themes, developments, forecasts, geo_scenarios, sources, domain="geopolitics"
    )
    
    geo_exec = geo_skeleton.split("# Executive Summary")[1].split("# Key Actions")[0].strip()
    geo_actions = geo_skeleton.split("# Key Actions")[1].split("# Key Developments")[0].strip()
    
    # 3. COMPARE
    print("\n--- COMPARISON RESULTS ---")
    
    # Executive Summary Comparison
    # Print safe versions to avoid encoding crashes
    print(f"Energy Executive: {energy_exec[:80].replace('\u2014', '--')}...")
    print(f"Geo Executive:    {geo_exec[:80].replace('\u2014', '--')}...")
    
    exec_diff = (energy_exec != geo_exec)
    print(f"Executive Summary Differentiates: {'YES' if exec_diff else 'NO'}")
    
    # Actions Comparison
    # Check if the scenarios themselves use different keys
    # Energy should use its own outcomes [price volatility, supply gaps, etc. if it maps to energy]
    # Geopolitics should use [sanctions, route instability, etc.]
    
    # Print first lines safely
    e_act_first = energy_actions.splitlines()[0] if energy_actions.splitlines() else 'None'
    g_act_first = geo_actions.splitlines()[0] if geo_actions.splitlines() else 'None'
    print(f"Energy First Action: {e_act_first.replace('\u2014', '--')}")
    print(f"Geo First Action:    {g_act_first.replace('\u2014', '--')}")
    
    actions_diff = (energy_actions != geo_actions)
    print(f"Key Actions Differentiate: {'YES' if actions_diff else 'NO'}")
    
    # Logical check for success
    if exec_diff and actions_diff:
        print("\n[SUCCESS] Domain differentiation confirmed. Executive and Actions sections are now distinct.")
    else:
        print("\n[FAIL] Differentiation missing or insufficient.")

if __name__ == "__main__":
    test_differentiation()
