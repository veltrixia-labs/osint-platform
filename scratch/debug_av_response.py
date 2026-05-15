import asyncio
import sys
import os
import json
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from data_sources.alpha_vantage_client import AlphaVantageClient

async def debug_av():
    client = AlphaVantageClient()
    symbol = "ITA" # Defense ETF
    print(f"Fetching {symbol}...")
    res = client.get_daily_equity(symbol)
    print(json.dumps(res, indent=2))

if __name__ == "__main__":
    asyncio.run(debug_av())
