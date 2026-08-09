"""
Market Data Fetcher Job.

Orchestrates synchronization of market instruments and prices from external APIs
(Alpha Vantage, Frankfurter) into the local database.
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from data_sources.alpha_vantage_client import AlphaVantageClient
from data_sources.frankfurter_client import FrankfurterClient
from data_sources.market_data_repository import MarketDataRepository
from data_sources.market_instrument_catalog import MARKET_INSTRUMENT_DEFINITIONS, get_instruments_for_domain
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

def safe_float(val: Any) -> Optional[float]:
    """Safely convert Alpha Vantage / Frankfurter string values to float."""
    if val is None or val in ("", "."):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

class MarketDataFetcher:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = MarketDataRepository(db)

    async def sync_alpha_vantage_sample(self, domain_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Sync equities, crypto and FX from Alpha Vantage.
        If domain_id is provided, only syncs instruments for that domain.
        Respects free tier rate limits.
        """
        logger.info(f"Starting Alpha Vantage sync (domain={domain_id})...")
        # Open and COMMIT the log row before constructing the client. create_fetch_log
        # only flushes, and a flushed row is discarded when the session unwinds on a
        # raise — so a missing ALPHA_VANTAGE_API_KEY used to leave no row at all, which
        # is indistinguishable from the job never firing. Committing here costs an
        # orphan "running" row on a hard kill; that is a diagnosis, absence is not.
        log = await self.repo.create_fetch_log(provider="alpha_vantage", job_name=f"sync_alpha_vantage_{domain_id or 'sample'}")
        await self.db.commit()

        inst_requested = 0
        rows_fetched = 0
        rows_saved = 0
        error_msg = None

        try:
            # Inside the try: AlphaVantageClient() raises when the key is absent or
            # empty (data_sources/base_client.py:52), and get_instruments_for_domain
            # can raise on a malformed catalog entry.
            client = AlphaVantageClient()

            # Get target instruments from catalog
            if domain_id:
                targets = get_instruments_for_domain(domain_id)
            else:
                # Default fallback for general sync
                default_symbols = ["SPY", "QQQ", "XLE", "SMH", "BTC", "USDJPY"]
                targets = [i for i in MARKET_INSTRUMENT_DEFINITIONS if i["symbol"] in default_symbols]

            for inst_def in targets:
                if inst_def["provider"] != "alpha_vantage":
                    continue
                    
                symbol = inst_def["symbol"]
                asset_class = inst_def["asset_class"]
                
                inst_requested += 1
                if inst_requested > 1:
                    await asyncio.sleep(13.0) # AV Free Tier: 5 req/min, be conservative
                
                res = {}
                if asset_class in ("equity", "index"):
                    res = client.get_daily_equity(symbol)
                    series_key = "Time Series (Daily)"
                elif asset_class == "crypto":
                    res = client.get_daily_crypto(symbol)
                    series_key = "Time Series (Digital Currency Daily)"
                elif asset_class == "fx":
                    # For AV FX, we only get latest for now to save quota
                    base = inst_def.get("base_currency", "USD")
                    quote = inst_def.get("quote_currency", "JPY")
                    res = client.get_exchange_rate(base, quote)
                    series_key = "Realtime Currency Exchange Rate"
                else:
                    continue

                if series_key in res:
                    # Upsert Instrument with full metadata from catalog
                    inst = await self.repo.upsert_instrument(
                        provider="alpha_vantage",
                        symbol=symbol,
                        name=inst_def["name"],
                        asset_class=asset_class,
                        domain_ids=inst_def.get("domain_ids"),
                        base_currency=inst_def.get("base_currency"),
                        quote_currency=inst_def.get("quote_currency")
                    )
                    
                    if asset_class == "fx":
                        vals = res[series_key]
                        refreshed = vals.get("6. Last Refreshed", "")
                        d_str = refreshed.split(" ")[0] if refreshed else datetime.utcnow().strftime("%Y-%m-%d")
                        await self.repo.upsert_price(
                            instrument_id=inst.id,
                            provider="alpha_vantage",
                            symbol=symbol,
                            price_date=datetime.strptime(d_str, "%Y-%m-%d").date(),
                            interval="latest",
                            close_val=safe_float(vals.get("5. Exchange Rate")),
                            raw_json=vals
                        )
                        rows_fetched += 1
                        rows_saved += 1
                    else:
                        series = res[series_key]
                        dates = sorted(series.keys(), reverse=True)
                        sync_dates = dates[:30]
                        rows_fetched += len(sync_dates)
                        
                        for d_str in sync_dates:
                            vals = series[d_str]
                            await self.repo.upsert_price(
                                instrument_id=inst.id,
                                provider="alpha_vantage",
                                symbol=symbol,
                                price_date=datetime.strptime(d_str, "%Y-%m-%d").date(),
                                interval="daily",
                                open_val=safe_float(vals.get("1. open")),
                                high_val=safe_float(vals.get("2. high")),
                                low_val=safe_float(vals.get("3. low")),
                                close_val=safe_float(vals.get("4. close")),
                                volume=safe_float(vals.get("5. volume")),
                                raw_json=vals
                            )
                            rows_saved += 1
                elif "Note" in res:
                    logger.warning(f"Alpha Vantage rate limit hit for {symbol}")
                    error_msg = f"Rate limit hit at {symbol}"
                    break
                elif "Information" in res:
                    logger.warning(f"Alpha Vantage rate/premium limit for {symbol}: {res['Information']}")
                    error_msg = f"Rate/premium limit at {symbol}: {res['Information']}"
                    break
                elif "Error Message" in res:
                    logger.error(f"AV Error for {symbol}: {res['Error Message']}")
                    error_msg = f"AV error at {symbol}: {res['Error Message']}"
                else:
                    logger.warning(f"AV unrecognized response for {symbol}; keys={list(res.keys())}")
                    error_msg = f"Unrecognized AV response at {symbol}; keys={list(res.keys())}"

            # Belt-and-braces: a run that requested instruments but saved zero rows
            # must not record clean success, even for a future unknown response shape.
            if error_msg:
                status = "partial"
            elif inst_requested > 0 and rows_saved == 0:
                status = "partial"
                error_msg = f"Zero rows saved despite {inst_requested} instrument(s) requested"
            else:
                status = "success"
            await self.repo.finish_fetch_log(
                log, status=status, 
                instruments_requested=inst_requested, 
                rows_fetched=rows_fetched, 
                rows_saved=rows_saved,
                error_message=error_msg
            )
            await self.db.commit()
            return {"provider": "alpha_vantage", "status": status, "rows_saved": rows_saved}

            status = "partial" if error_msg else "success"
            await self.repo.finish_fetch_log(
                log, status=status, 
                instruments_requested=inst_requested, 
                rows_fetched=rows_fetched, 
                rows_saved=rows_saved,
                error_message=error_msg
            )
            await self.db.commit()
            return {"provider": "alpha_vantage", "status": status, "rows_saved": rows_saved}

        except Exception as e:
            logger.exception("Alpha Vantage sync unexpected failure")
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(e))
            await self.db.commit()
            return {"provider": "alpha_vantage", "status": "failed", "error": str(e)}

    async def sync_frankfurter_fx_history(self, days: int = 31) -> Dict[str, Any]:
        """
        Sync historical FX reference rates from Frankfurter.
        """
        logger.info(f"Starting Frankfurter history sync (last {days} days)...")
        client = FrankfurterClient()
        log = await self.repo.create_fetch_log(provider="frankfurter", job_name="sync_frankfurter_fx_history")
        
        rows_fetched = 0
        rows_saved = 0
        
        try:
            end_date = datetime.utcnow().date()
            start_date = end_date - timedelta(days=days)
            
            # Use symbols from catalog
            fx_defs = [i for i in MARKET_INSTRUMENT_DEFINITIONS if i["provider"] == "frankfurter"]
            symbols = sorted(list(set([i["quote_currency"] for i in fx_defs if i["base_currency"] == "USD"])))
            
            res = client.get_timeseries(
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                base="USD",
                symbols=symbols
            )
            
            if "rates" in res:
                for d_str, rates in res["rates"].items():
                    price_date = datetime.strptime(d_str, "%Y-%m-%d").date()
                    for q_curr, rate in rates.items():
                        symbol = f"USD{q_curr}"
                        # Find name from catalog or fallback
                        inst_def = next((i for i in fx_defs if i["symbol"] == symbol), None)
                        name = inst_def["name"] if inst_def else f"USD/{q_curr} Reference"
                        
                        inst = await self.repo.upsert_instrument(
                            provider="frankfurter",
                            symbol=symbol,
                            name=name,
                            asset_class="fx",
                            domain_ids=inst_def.get("domain_ids") if inst_def else None,
                            base_currency="USD",
                            quote_currency=q_curr
                        )
                        await self.repo.upsert_price(
                            instrument_id=inst.id,
                            provider="frankfurter",
                            symbol=symbol,
                            price_date=price_date,
                            interval="daily_reference",
                            close_val=safe_float(rate),
                            raw_json={"date": d_str, "base": "USD", "rates": rates}
                        )
                        rows_saved += 1
                        rows_fetched += 1
                
                await self.repo.finish_fetch_log(
                    log, status="success", 
                    instruments_requested=len(symbols), 
                    rows_fetched=rows_fetched, 
                    rows_saved=rows_saved
                )
                await self.db.commit()
                return {"provider": "frankfurter", "status": "success", "rows_saved": rows_saved}
            else:
                raise ValueError("Invalid Frankfurter history response")
                
        except Exception as e:
            logger.exception("Frankfurter history sync failed")
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(e))
            await self.db.commit()
            return {"provider": "frankfurter", "status": "failed", "error": str(e)}

    async def sync_market_data_sample(self, domain_id: Optional[str] = None) -> Dict[str, Any]:
        """Main entry point to sync both Alpha Vantage and Frankfurter (including history)."""
        res_av = await self.sync_alpha_vantage_sample(domain_id=domain_id)
        res_fk = await self.sync_frankfurter_fx_history(days=31)
        return {"alpha_vantage": res_av, "frankfurter": res_fk}
