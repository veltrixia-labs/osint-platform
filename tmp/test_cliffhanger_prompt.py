import asyncio
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from llm.prompts import LLM_POLISH_PROMPT
from llm.client import generate_analysis

async def test_prompt():
    dummy_input = """ENRICHED CLUSTER CONTEXT:
EVENT: Rare Earth Export Restrictions
- Scale: 45 reports from 18 unique sources
- Diversity: 90% agreement across sources
- Timeline: Seen over 24 hours
- Key Entities: PRC Ministry of Commerce, Global EV Manufacturers

TREND ANALYSIS CONTEXT:
TREND: Battery Material Scarcity (risk_pattern)
- Change: 300% shift from baseline
- Evidence: Supported by 4 clusters

DRAFT REPORT:
# Summary of Themes
A significant geopolitical move regarding rare earth materials has been observed.
Multiple sources indicate new export restrictions are imminent.
This will likely affect battery production globally.

# Key Developments
- PRC Ministry of Commerce draft circulated.
- Global EV stocks showing volatility.

# Potential Implications
- Supply chain disruption.
- Price increases.

# Monitoring Points
- Official announcements.
- Stock price movements.

# Scenarios
- Base: Moderate restrictions.
- Worst: Total embargo.

# Sources
- Source A
- Source B
"""
    result = await generate_analysis(LLM_POLISH_PROMPT, dummy_input)
    print("--- GENERATED REPORT ---")
    print(result)

if __name__ == "__main__":
    asyncio.run(test_prompt())
