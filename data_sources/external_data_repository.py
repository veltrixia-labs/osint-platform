"""
External Data Repository.

Provides a unified interface for idempotently saving data from various 
external sources (FRED, BLS, World Bank, Comtrade, BEA, Census) into the database.
Supports Upsert (Update-or-Insert) logic to prevent duplicate records.
"""

import logging
from datetime import datetime, date
from typing import Dict, Any, Optional, Union
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from data_sources.base_client import redact_credentials
from db.models import (
    ExternalDataSeries, 
    ExternalObservation, 
    ExternalTradeFlow, 
    ExternalIndustryStat, 
    ExternalDataFetchLog
)

logger = logging.getLogger(__name__)

class ExternalDataRepository:
    """
    Repository for managing persistence of external data.
    Ensures data consistency and provides idempotent saving methods.
    """
    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_series(
        self,
        source: str,
        series_id: str,
        name: str,
        unit: Optional[str] = None,
        frequency: Optional[str] = None,
        category: Optional[str] = None,
        pro_use: Optional[str] = None,
        geography: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None
    ) -> ExternalDataSeries:
        """
        Upsert a series master record.
        Unique on (source, series_id).
        """
        stmt = select(ExternalDataSeries).where(
            ExternalDataSeries.source == source,
            ExternalDataSeries.series_id == series_id
        )
        result = await self.db.execute(stmt)
        series = result.scalar_one_or_none()

        if series:
            series.name = name
            series.unit = unit
            series.frequency = frequency
            series.category = category
            series.pro_use = pro_use
            series.geography = geography
            series.metadata_json = metadata_json
            series.updated_at = func.now()
        else:
            series = ExternalDataSeries(
                source=source,
                series_id=series_id,
                name=name,
                unit=unit,
                frequency=frequency,
                category=category,
                pro_use=pro_use,
                geography=geography,
                metadata_json=metadata_json
            )
            self.db.add(series)
        
        return series

    async def upsert_observation(
        self,
        series: ExternalDataSeries,
        source: str,
        series_id: str,
        date_val: Union[date, datetime, str],
        value: Optional[Union[float, str]],
        period_label: Optional[str] = None,
        is_latest: bool = False,
        raw_json: Optional[Dict[str, Any]] = None
    ) -> ExternalObservation:
        """
        Upsert a time-series observation.
        Unique on (source, series_id, date, period_label).
        """
        # Normalize date
        if isinstance(date_val, str):
            try:
                dt = datetime.fromisoformat(date_val.replace("Z", "+00:00")).date()
            except ValueError:
                # Basic fallback if parsing fails (caller should provide clean dates)
                logger.warning(f"Failed to parse date string: {date_val}")
                dt = date_val
        elif isinstance(date_val, datetime):
            dt = date_val.date()
        else:
            dt = date_val

        # Normalize value
        final_value = None
        if value is not None:
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned not in (".", "", "null", "None"):
                    try:
                        final_value = float(cleaned)
                    except ValueError:
                        final_value = None
            else:
                try:
                    final_value = float(value)
                except (ValueError, TypeError):
                    final_value = None

        stmt = select(ExternalObservation).where(
            ExternalObservation.source == source,
            ExternalObservation.series_id == series_id,
            ExternalObservation.date == dt,
            ExternalObservation.period_label == period_label
        )
        result = await self.db.execute(stmt)
        obs = result.scalar_one_or_none()

        if obs:
            obs.value = final_value
            obs.is_latest = is_latest
            obs.raw_json = raw_json
            obs.fetched_at = func.now()
        else:
            obs = ExternalObservation(
                series_ref_id=series.id,
                source=source,
                series_id=series_id,
                date=dt,
                value=final_value,
                period_label=period_label,
                is_latest=is_latest,
                raw_json=raw_json
            )
            self.db.add(obs)
            
        return obs

    async def upsert_trade_flow(
        self,
        source: str,
        reporter_id: str,
        reporter_name: Optional[str],
        partner_id: str,
        partner_name: Optional[str],
        flow_type: str,
        commodity_id: str,
        commodity_name: Optional[str],
        year: int,
        period: Optional[str],
        trade_value: Optional[float],
        quantity: Optional[float] = None,
        unit: Optional[str] = None,
        raw_json: Optional[Dict[str, Any]] = None
    ) -> ExternalTradeFlow:
        """
        Upsert a trade flow record.
        Unique on (source, reporter, partner, flow, commodity, year, period).
        """
        stmt = select(ExternalTradeFlow).where(
            ExternalTradeFlow.source == source,
            ExternalTradeFlow.reporter_id == reporter_id,
            ExternalTradeFlow.partner_id == partner_id,
            ExternalTradeFlow.flow_type == flow_type,
            ExternalTradeFlow.commodity_id == commodity_id,
            ExternalTradeFlow.year == year,
            ExternalTradeFlow.period == period
        )
        result = await self.db.execute(stmt)
        flow = result.scalar_one_or_none()

        if flow:
            flow.reporter_name = reporter_name
            flow.partner_name = partner_name
            flow.commodity_name = commodity_name
            flow.trade_value = trade_value
            flow.quantity = quantity
            flow.unit = unit
            flow.raw_json = raw_json
            flow.fetched_at = func.now()
        else:
            flow = ExternalTradeFlow(
                source=source,
                reporter_id=reporter_id,
                reporter_name=reporter_name,
                partner_id=partner_id,
                partner_name=partner_name,
                flow_type=flow_type,
                commodity_id=commodity_id,
                commodity_name=commodity_name,
                year=year,
                period=period,
                trade_value=trade_value,
                quantity=quantity,
                unit=unit,
                raw_json=raw_json
            )
            self.db.add(flow)
            
        return flow

    async def upsert_industry_stat(
        self,
        source: str,
        dataset: Optional[str],
        geo_id: Optional[str],
        geo_name: Optional[str],
        industry_id: Optional[str],
        industry_name: Optional[str],
        metric_name: str,
        year: Optional[int],
        period: Optional[str],
        value: Optional[float],
        unit: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None,
        raw_json: Optional[Dict[str, Any]] = None
    ) -> ExternalIndustryStat:
        """
        Upsert an industry or business statistic.
        Unique on (source, dataset, geo, industry, metric, year, period).
        """
        stmt = select(ExternalIndustryStat).where(
            ExternalIndustryStat.source == source,
            ExternalIndustryStat.dataset == dataset,
            ExternalIndustryStat.geo_id == geo_id,
            ExternalIndustryStat.industry_id == industry_id,
            ExternalIndustryStat.metric_name == metric_name,
            ExternalIndustryStat.year == year,
            ExternalIndustryStat.period == period
        )
        result = await self.db.execute(stmt)
        stat = result.scalar_one_or_none()

        if stat:
            stat.geo_name = geo_name
            stat.industry_name = industry_name
            stat.value = value
            stat.unit = unit
            stat.metadata_json = metadata_json
            stat.raw_json = raw_json
            stat.fetched_at = func.now()
        else:
            stat = ExternalIndustryStat(
                source=source,
                dataset=dataset,
                geo_id=geo_id,
                geo_name=geo_name,
                industry_id=industry_id,
                industry_name=industry_name,
                metric_name=metric_name,
                year=year,
                period=period,
                value=value,
                unit=unit,
                metadata_json=metadata_json,
                raw_json=raw_json
            )
            self.db.add(stat)
            
        return stat

    async def create_fetch_log(
        self,
        source: str,
        job_name: str,
        metadata_json: Optional[Dict[str, Any]] = None
    ) -> ExternalDataFetchLog:
        """Create a new fetch log entry and flush to get ID."""
        log = ExternalDataFetchLog(
            source=source,
            job_name=job_name,
            status="running",
            metadata_json=metadata_json
        )
        self.db.add(log)
        await self.db.flush() 
        return log

    async def finish_fetch_log(
        self,
        log: ExternalDataFetchLog,
        status: str,
        rows_fetched: int = 0,
        rows_saved: int = 0,
        error_message: Optional[str] = None,
        metadata_json: Optional[Dict[str, Any]] = None
    ):
        """Finalize a fetch log entry with statistics and status."""
        log.status = status
        log.rows_fetched = rows_fetched
        log.rows_saved = rows_saved
        # Redact at the setter, not at the ~12 call sites that pass str(e): BEA and
        # Alpha Vantage have no local exception handler, so a raise_for_status message
        # carrying the full URL — and with it the api_key/UserID query parameter —
        # reaches this column directly. Doing it here means a future caller cannot
        # bypass it. `is not None` matters: an unredacted None must stay NULL, not
        # become the empty string. Locally-composed messages carry no query string,
        # so this is a verified no-op for them.
        log.error_message = (
            redact_credentials(error_message) if error_message is not None else None
        )
        log.finished_at = func.now()
        if metadata_json:
            if log.metadata_json:
                log.metadata_json.update(metadata_json)
            else:
                log.metadata_json = metadata_json
