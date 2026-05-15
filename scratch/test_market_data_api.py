"""
Test script for Market Data APIs (Alpha Vantage and Frankfurter).

Verifies connectivity and sample data retrieval for:
1. Equities/ETFs (Alpha Vantage)
2. Forex (Alpha Vantage and Frankfurter)
3. Cryptocurrency (Alpha Vantage)
"""

import asyncio
import os
import json
import logging
import sys
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from data_sources.alpha_vantage_client import AlphaVantageClient
from data_sources.frankfurter_client import FrankfurterClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def run_test():
    av_client = AlphaVantageClient()
    fk_client = FrankfurterClient()
    
    sample_results = {
        "alpha_vantage": {},
        "frankfurter": {}
    }

    print("=" * 60)
    print("MARKET DATA API CONNECTIVITY TEST")
    print("=" * 60)

    # 1. Alpha Vantage - Equity (Daily)
    symbols = ["SPY", "QQQ", "XLE", "SMH"]
    print(f"\n[1] Testing Alpha Vantage Equity (Daily) for {symbols}...")
    for symbol in symbols:
        try:
            # Respect AV free tier (5 requests per minute)
            if symbol != symbols[0]:
                await asyncio.sleep(12.5) 
            data = av_client.get_daily_equity(symbol)
            # Just keep metadata and first few days to keep sample small
            if "Time Series (Daily)" in data:
                dates = sorted(data["Time Series (Daily)"].keys(), reverse=True)[:3]
                subset = {d: data["Time Series (Daily)"][d] for d in dates}
                sample_results["alpha_vantage"][f"equity_{symbol}"] = {
                    "metadata": data.get("Meta Data"),
                    "series_subset": subset
                }
                print(f"  Successfully fetched {symbol}")
            else:
                print(f"  Warning: No time series data for {symbol}. Response: {list(data.keys())}")
        except Exception as e:
            print(f"  Error fetching {symbol}: {e}")

    # 2. Alpha Vantage - Crypto (Daily)
    print("\n[2] Testing Alpha Vantage Crypto (Daily) for BTC...")
    try:
        await asyncio.sleep(12.5)
        crypto_data = av_client.get_daily_crypto("BTC")
        if "Time Series (Digital Currency Daily)" in crypto_data:
            dates = sorted(crypto_data["Time Series (Digital Currency Daily)"].keys(), reverse=True)[:3]
            subset = {d: crypto_data["Time Series (Digital Currency Daily)"][d] for d in dates}
            sample_results["alpha_vantage"]["crypto_BTC"] = {
                "metadata": crypto_data.get("Meta Data"),
                "series_subset": subset
            }
            print("  Successfully fetched BTC")
        else:
            print(f"  Warning: No crypto data for BTC. Response: {list(crypto_data.keys())}")
    except Exception as e:
        print(f"  Error fetching BTC: {e}")

    # 3. Alpha Vantage - FX Exchange Rate
    print("\n[3] Testing Alpha Vantage FX Exchange Rate (USD/JPY)...")
    try:
        await asyncio.sleep(12.5)
        fx_data = av_client.get_exchange_rate("USD", "JPY")
        sample_results["alpha_vantage"]["fx_USDJPY"] = fx_data
        print("  Successfully fetched USD/JPY rate")
    except Exception as e:
        print(f"  Error fetching USD/JPY: {e}")

    # 4. Frankfurter - Latest Rates
    print("\n[4] Testing Frankfurter Latest Rates (Base=USD)...")
    try:
        symbols = ["JPY", "EUR", "GBP", "CAD", "NOK", "BRL", "CNY", "KRW", "SGD"]
        fk_data = fk_client.get_latest(base="USD", symbols=symbols)
        sample_results["frankfurter"]["latest"] = fk_data
        print(f"  Successfully fetched latest rates for {len(symbols)} symbols")
    except Exception as e:
        print(f"  Error fetching Frankfurter: {e}")

    # Save to scratch
    output_path = "scratch/market_data_sample.json"
    with open(output_path, "w") as f:
        json.dump(sample_results, f, indent=2)
    
    print("\n" + "=" * 60)
    print(f"Test completed. Sample saved to {output_path}")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(run_test())
