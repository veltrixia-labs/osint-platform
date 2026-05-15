"""
Market Data Repository.

Handles idempotent storage and retrieval for market instruments, 
price points, and synchronization logs.
"""

import uuid
import logging
from typing import Optional, List, Dict, Any
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from db.models import MarketDataInstrument, MarketDataPrice, MarketDataFetchLog
from datetime import datetime, date

logger = logging.getLogger(__name__)

class MarketDataRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_instrument(
        self,
        provider: str,
        symbol: str,
        name: str,
        asset_class: str,
        domain_ids: Optional[List[str]] = None,
        quote_currency: Optional[str] = None,
        base_currency: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None
    ) -> MarketDataInstrument:
        """
        Idempotently create or update a market instrument catalog entry.
        """
        stmt = select(MarketDataInstrument).where(
            MarketDataInstrument.provider == provider,
            MarketDataInstrument.symbol == symbol
        )
        result = await self.db.execute(stmt)
        instrument = result.scalar_one_or_none()
        
        if instrument:
            # Update existing
            instrument.name = name
            instrument.asset_class = asset_class
            if domain_ids is not None:
                instrument.domain_ids = domain_ids
            if quote_currency is not None:
                instrument.quote_currency = quote_currency
            if base_currency is not None:
                instrument.base_currency = base_currency
            if metadata_json is not None:
                instrument.metadata_json = metadata_json
            instrument.updated_at = datetime.utcnow()
        else:
            # Create new
            instrument = MarketDataInstrument(
                provider=provider,
                symbol=symbol,
                name=name,
                asset_class=asset_class,
                domain_ids=domain_ids,
                quote_currency=quote_currency,
                base_currency=base_currency,
                metadata_json=metadata_json
            )
            self.db.add(instrument)
            
        await self.db.flush()
        return instrument

    async def upsert_price(
        self,
        instrument_id: uuid.UUID,
        provider: str,
        symbol: str,
        price_date: date,
        interval: str = "daily",
        open_val: Optional[float] = None,
        high_val: Optional[float] = None,
        low_val: Optional[float] = None,
        close_val: Optional[float] = None,
        adjusted_close: Optional[float] = None,
        volume: Optional[float] = None,
        raw_json: Optional[Dict[str, Any]] = None
    ) -> MarketDataPrice:
        """
        Idempotently save or update a market price point.
        """
        stmt = select(MarketDataPrice).where(
            MarketDataPrice.provider == provider,
            MarketDataPrice.symbol == symbol,
            MarketDataPrice.date == price_date,
            MarketDataPrice.interval == interval
        )
        result = await self.db.execute(stmt)
        price = result.scalar_one_or_none()
        
        if price:
            # Update existing observation
            price.instrument_id = instrument_id
            price.open = open_val
            price.high = high_val
            price.low = low_val
            price.close = close_val
            price.adjusted_close = adjusted_close
            price.volume = volume
            price.raw_json = raw_json
            price.fetched_at = datetime.utcnow()
        else:
            # Create new observation
            price = MarketDataPrice(
                instrument_id=instrument_id,
                provider=provider,
                symbol=symbol,
                date=price_date,
                interval=interval,
                open=open_val,
                high=high_val,
                low=low_val,
                close=close_val,
                adjusted_close=adjusted_close,
                volume=volume,
                raw_json=raw_json
            )
            self.db.add(price)
            
        return price

    async def create_fetch_log(self, provider: str, job_name: str) -> MarketDataFetchLog:
        """Create a new fetch log entry with 'running' status."""
        log = MarketDataFetchLog(
            provider=provider,
            job_name=job_name,
            status="running",
            started_at=datetime.utcnow()
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def finish_fetch_log(
        self,
        log: MarketDataFetchLog,
        status: str,
        instruments_requested: int = 0,
        rows_fetched: int = 0,
        rows_saved: int = 0,
        error_message: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None
    ):
        """Finalize a fetch log entry with results and completion status."""
        log.status = status
        log.finished_at = datetime.utcnow()
        log.instruments_requested = instruments_requested
        log.rows_fetched = rows_fetched
        log.rows_saved = rows_saved
        log.error_message = error_message
        if metadata_json:
            log.metadata_json = metadata_json
        await self.db.flush()
