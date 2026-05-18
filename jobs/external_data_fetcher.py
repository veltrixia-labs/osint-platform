"""
External Data Fetch Jobs.

Orchestrates the fetching of data from external APIs (FRED, BLS, World Bank)
and ensures they are idempotently saved to the database using the ExternalDataRepository.
"""

import logging
import asyncio
from datetime import datetime, date
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from data_sources import (
    FREDClient,
    BLSClient,
    WorldBankClient,
    ComtradeClient,
    BEAClient,
    CensusClient,
    EStatClient,
    EIAClient,
    ECBClient,
    BCBClient,
    OPECClient,
    ASEANClient,
)
from data_sources.estat_series_catalog import get_all_estat_series
from data_sources.eia_series_catalog import get_all_eia_series
from data_sources.ecb_series_catalog import get_all_ecb_series
from data_sources.bcb_series_catalog import get_all_bcb_series
from data_sources.opec_series_catalog import get_all_opec_series
from data_sources.asean_series_catalog import get_all_asean_series
from data_sources.external_data_repository import ExternalDataRepository
from data_sources.fred_series_catalog import get_all_fred_series
from data_sources.bls_series_catalog import get_all_bls_series
from data_sources.worldbank_indicator_catalog import get_all_indicators
from data_sources.comtrade_catalog import get_all_commodities

logger = logging.getLogger(__name__)

class ExternalDataFetcher:
    """
    Service for syncing external data sources into the platform database.
    """
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ExternalDataRepository(db)

    async def sync_fred(self, series_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Fetch and save FRED data from the catalog.
        If series_ids is provided, only syncs those specific series.
        """
        logger.info(f"Starting FRED sync (targeted={series_ids is not None})...")
        client = FREDClient()
        all_series = get_all_fred_series()
        
        if series_ids:
            series_list = [s for s in all_series if s["series_id"] in series_ids]
        else:
            series_list = all_series
        
        log = await self.repo.create_fetch_log(source="fred", job_name="sync_fred")
        
        rows_fetched = 0
        rows_saved = 0
        
        try:
            for s_info in series_list:
                s_id = s_info["series_id"]
                logger.info(f"Fetching FRED series: {s_id}")
                
                # Fetch data (limit to 50 for initial sync to avoid overloading)
                data = client.get_series_observations(s_id, limit=50)
                observations = data.get("observations", [])
                rows_fetched += len(observations)
                
                # Upsert Master
                series_record = await self.repo.upsert_series(
                    source="fred",
                    series_id=s_id,
                    name=s_info["name"],
                    unit=s_info.get("unit"),
                    frequency=s_info.get("frequency_hint"),
                    category=s_info.get("category"),
                    pro_use=s_info.get("pro_use")
                )
                # Flush to ensure series has an ID for the foreign key
                await self.db.flush()
                
                # Upsert Observations
                for obs in observations:
                    await self.repo.upsert_observation(
                        series=series_record,
                        source="fred",
                        series_id=s_id,
                        date_val=obs["date"],
                        value=obs["value"],
                        raw_json=obs
                    )
                    rows_saved += 1
                
                await self.db.flush()
                
            await self.repo.finish_fetch_log(log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved)
            await self.db.commit()
            logger.info(f"FRED sync completed. Saved {rows_saved} observations.")
            
        except Exception as e:
            logger.error(f"FRED sync failed: {e}")
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(e))
            await self.db.commit()
            
        return {"source": "fred", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_bls(self, series_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Fetch and save BLS PPI data from the catalog.
        If series_ids is provided, only syncs those specific series.
        """
        logger.info(f"Starting BLS sync (targeted={series_ids is not None})...")
        client = BLSClient()
        all_series = get_all_bls_series()
        
        if series_ids:
            target_series = [s for s in all_series if s["series_id"] in series_ids]
        else:
            target_series = all_series
            
        sync_series_ids = [s["series_id"] for s in target_series]
        
        log = await self.repo.create_fetch_log(source="bls", job_name="sync_bls")
        
        rows_fetched = 0
        rows_saved = 0
        
        try:
            # Sync last 2 years of data
            current_year = datetime.now().year
            start_year = current_year - 2
            
            raw_response = client.get_timeseries(series_ids, start_year=start_year, end_year=current_year)
            parsed_data = client.parse_series_data(raw_response)
            
            info_map = {s["series_id"]: s for s in target_series}
            
            for s_id, observations in parsed_data.items():
                s_info = info_map.get(s_id)
                rows_fetched += len(observations)
                
                # Upsert Master
                series_record = await self.repo.upsert_series(
                    source="bls",
                    series_id=s_id,
                    name=s_info["name"],
                    unit=s_info.get("unit"),
                    category=s_info.get("category"),
                    pro_use=s_info.get("pro_use")
                )
                await self.db.flush()
                
                # Upsert Observations
                for obs in observations:
                    # BLS normalization: year=2024, period=M03 -> 2024-03-01
                    try:
                        year = int(obs["year"])
                        period = obs["period"] 
                        if period.startswith("M"):
                            month = int(period[1:])
                            dt = date(year, month, 1)
                        elif period == "M13": # Annual average fallback
                            dt = date(year, 12, 31)
                        else:
                            # Fallback for unexpected periods
                            dt = date(year, 1, 1)
                    except Exception as parse_e:
                        logger.warning(f"Failed to parse BLS period: {obs.get('period')} - {parse_e}")
                        continue
                    
                    await self.repo.upsert_observation(
                        series=series_record,
                        source="bls",
                        series_id=s_id,
                        date_val=dt,
                        value=obs["value"],
                        period_label=period,
                        is_latest=(obs.get("latest") == "true"),
                        raw_json=obs
                    )
                    rows_saved += 1
                
                await self.db.flush()

            await self.repo.finish_fetch_log(log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved)
            await self.db.commit()
            logger.info(f"BLS sync completed. Saved {rows_saved} observations.")

        except Exception as e:
            logger.error(f"BLS sync failed: {e}")
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(e))
            await self.db.commit()

        return {"source": "bls", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_worldbank(self) -> Dict[str, Any]:
        """
        Fetch and save World Bank indicator data from the catalog.
        """
        logger.info("Starting World Bank sync...")
        client = WorldBankClient()
        indicators = get_all_indicators()
        countries = ["US", "JP", "CN", "DE", "GB"]
        
        log = await self.repo.create_fetch_log(source="worldbank", job_name="sync_worldbank")
        
        rows_fetched = 0
        rows_saved = 0
        
        try:
            # Sync last 10 years of annual data
            current_year = datetime.now().year
            start_year = current_year - 10
            
            for ind_info in indicators:
                ind_id = ind_info["indicator_id"]
                logger.info(f"Fetching World Bank indicator: {ind_id}")
                
                observations = client.get_indicator(countries, ind_id, start_year=start_year, end_year=current_year)
                rows_fetched += len(observations)
                
                for obs in observations:
                    country_id = obs.get("country", {}).get("id")
                    if not country_id: continue
                    
                    # Create country-specific series
                    composite_id = f"{ind_id}:{country_id}"
                    country_name = obs.get("country", {}).get("value")
                    
                    # Upsert Master per Country
                    series_record = await self.repo.upsert_series(
                        source="worldbank",
                        series_id=composite_id,
                        name=f"{ind_info['name']} ({country_name})",
                        category=ind_info.get("category"),
                        pro_use=ind_info.get("pro_use"),
                        geography=country_id,
                        metadata_json={"indicator_id": ind_id, "country_id": country_id}
                    )
                    await self.db.flush()
                    
                    # Upsert Observation
                    year_str = obs.get("date")
                    if year_str:
                        dt = date(int(year_str), 1, 1)
                        await self.repo.upsert_observation(
                            series=series_record,
                            source="worldbank",
                            series_id=composite_id,
                            date_val=dt,
                            value=obs.get("value"),
                            period_label=year_str,
                            raw_json=obs
                        )
                        rows_saved += 1
                
                await self.db.flush()

            await self.repo.finish_fetch_log(log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved)
            await self.db.commit()
            logger.info(f"World Bank sync completed. Saved {rows_saved} observations.")

        except Exception as e:
            logger.error(f"World Bank sync failed: {e}")
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(e))
            await self.db.commit()

        return {"source": "worldbank", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_comtrade(self) -> Dict[str, Any]:
        """
        Fetch and save UN Comtrade trade data from the catalog.
        """
        logger.info("Starting Comtrade sync...")
        client = ComtradeClient()
        commodities = get_all_commodities()
        cmd_codes = ",".join([c["commodity_code"] for c in commodities])
        
        reporters = ["392", "842", "156", "276", "826"] # JP, US, CN, DE, GB
        partners = "0" # World
        flows = ["M", "X"] # Imports, Exports
        years = [2023, 2022]
        
        log = await self.repo.create_fetch_log(source="comtrade", job_name="sync_comtrade")
        
        rows_fetched = 0
        rows_saved = 0
        
        try:
            for reporter in reporters:
                for flow in flows:
                    for year in years:
                        logger.info(f"Fetching Comtrade: Reporter={reporter}, Flow={flow}, Year={year}, Cmds={cmd_codes}")
                        
                        data = client.get_trade_data(
                            reporter_code=reporter,
                            partner_code=partners,
                            flow_code=flow,
                            commodity_code=cmd_codes,
                            year=year
                        )
                        
                        if isinstance(data, dict) and data.get("error"):
                            logger.error(f"Comtrade sync error for {reporter}/{flow}/{year}: {data.get('message')}")
                            continue
                            
                        records = data.get("data", [])
                        if not records:
                            logger.info(f"No records found for Comtrade {reporter}/{flow}/{year}")
                            continue
                            
                        rows_fetched += len(records)
                        
                        # Prepare a lookup for commodity names from catalog
                        cmd_name_map = {c["commodity_code"]: c["name"] for c in commodities}
                        reporter_names = {
                            "392": "Japan",
                            "842": "United States",
                            "156": "China",
                            "276": "Germany",
                            "826": "United Kingdom"
                        }
                        
                        for rec in records:
                            c_id = rec.get("cmdCode")
                            r_id = str(rec.get("reporterCode"))
                            p_id = str(rec.get("partnerCode"))
                            
                            # Map Comtrade fields to ExternalTradeFlow with fallbacks
                            await self.repo.upsert_trade_flow(
                                source="comtrade",
                                reporter_id=r_id,
                                reporter_name=rec.get("reporterDesc") or reporter_names.get(r_id, f"Country {r_id}"),
                                partner_id=p_id,
                                partner_name=rec.get("partnerDesc") or ("World" if p_id == "0" else f"Partner {p_id}"),
                                flow_type=rec.get("flowCode"),
                                commodity_id=c_id,
                                commodity_name=rec.get("cmdDesc") or cmd_name_map.get(c_id, f"HS {c_id}"),
                                year=int(rec.get("refYear")),
                                period=str(rec.get("refPeriodId") or rec.get("refYear")),
                                trade_value=float(rec.get("primaryValue") or 0),
                                quantity=float(rec.get("qty") or 0) if rec.get("qty") else None,
                                unit=rec.get("qtyUnitAbbr") or str(rec.get("qtyUnitCode") or ""),
                                raw_json=rec
                            )
                            rows_saved += 1
                        
                        await self.db.flush()
                        # Rate limit respect (UN Comtrade v2 allows 1 request per second for standard users)
                        await asyncio.sleep(1.2) 

            await self.repo.finish_fetch_log(log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved)
            await self.db.commit()
            logger.info(f"Comtrade sync completed. Saved {rows_saved} flows.")

        except Exception as e:
            logger.error(f"Comtrade sync failed: {e}")
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(e))
            await self.db.commit()
            
        return {"source": "comtrade", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_bea_industry_stats(self) -> Dict[str, Any]:
        """
        Fetch and save BEA GDPbyIndustry data.
        """
        logger.info("Starting BEA sync...")
        client = BEAClient()
        
        log = await self.repo.create_fetch_log(source="bea", job_name="sync_bea_industry_stats")
        
        rows_fetched = 0
        rows_saved = 0
        
        try:
            # GDPbyIndustry TableID=1 is "Value Added by Industry"
            # Annual data for 2022-2023
            params = {
                "TableID": "1",
                "Frequency": "A",
                "Year": "2022,2023",
                "Industry": "ALL"
            }
            
            response = client.get_data("GDPbyIndustry", **params)
            
            # Extract data list from BEA nested structure
            results = response.get("BEAAPI", {}).get("Results", [])
            data_list = []
            if isinstance(results, list) and len(results) > 0:
                data_list = results[0].get("Data", [])
            elif isinstance(results, dict):
                data_list = results.get("Data", [])
            
            rows_fetched = len(data_list)
            
            for row in data_list:
                # Normalize numeric value
                val_str = str(row.get("DataValue", "")).replace(",", "")
                try:
                    val = float(val_str)
                except ValueError:
                    val = None
                    
                await self.repo.upsert_industry_stat(
                    source="bea",
                    dataset="GDPbyIndustry",
                    geo_id="US",
                    geo_name="United States",
                    industry_id=str(row.get("Industry")),
                    industry_name=row.get("IndustryDescription"),
                    metric_name=row.get("TableName", "Value Added"),
                    year=int(row.get("Year")) if row.get("Year") else None,
                    period=row.get("Frequency"),
                    value=val,
                    unit=row.get("UnitOfMeasure"),
                    raw_json=row
                )
                rows_saved += 1
            
            await self.db.flush()
            await self.repo.finish_fetch_log(log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved)
            await self.db.commit()
            logger.info(f"BEA sync completed. Saved {rows_saved} stats.")
            
        except Exception as e:
            logger.error(f"BEA sync failed: {e}")
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(e))
            await self.db.commit()
            
        return {"source": "bea", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_census_cbp(self) -> Dict[str, Any]:
        """
        Fetch and save Census County Business Patterns data.
        """
        logger.info("Starting Census CBP sync...")
        client = CensusClient()
        
        log = await self.repo.create_fetch_log(source="census", job_name="sync_census_cbp")
        
        rows_fetched = 0
        rows_saved = 0
        
        try:
            # 2022 CBP at state level for establishments, employment, and payroll
            params = {
                "get": "NAME,ESTAB,EMP,PAYANN",
                "for": "state:*"
            }
            
            raw_data = client.get("2022/cbp", params)
            dicts = client.format_as_dicts(raw_data)
            
            rows_fetched = len(dicts)
            
            # Map Census variables to internal metrics
            metrics = [
                ("ESTAB", "Establishments", "count"),
                ("EMP", "Employees", "count"),
                ("PAYANN", "Annual Payroll", "usd_1000")
            ]
            
            for row in dicts:
                state_code = row.get("state")
                state_name = row.get("NAME")
                
                for m_key, m_name, m_unit in metrics:
                    val_str = row.get(m_key)
                    try:
                        val = float(val_str) if val_str is not None else None
                    except (ValueError, TypeError):
                        val = None
                        
                    await self.repo.upsert_industry_stat(
                        source="census",
                        dataset="CBP",
                        geo_id=state_code,
                        geo_name=state_name,
                        industry_id=None, 
                        industry_name="Total",
                        metric_name=m_key,
                        year=2022,
                        period="A",
                        value=val,
                        unit=m_unit,
                        raw_json=row
                    )
                    rows_saved += 1
                
                await self.db.flush()
                
            await self.repo.finish_fetch_log(log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved)
            await self.db.commit()
            logger.info(f"Census CBP sync completed. Saved {rows_saved} stats.")

        except Exception as e:
            logger.error(f"Census sync failed: {e}")
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(e))
            await self.db.commit()

        return {"source": "census", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_estat_japan_stats(
        self, series_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Fetch and save Japan government statistics from e-Stat (IIP, CPI).
        """
        logger.info("Starting e-Stat Japan stats sync (targeted=%s)...", series_ids is not None)
        try:
            client = EStatClient()
        except ValueError as exc:
            logger.error("e-Stat sync skipped: %s", exc)
            return {"source": "estat", "rows_fetched": 0, "rows_saved": 0, "error": str(exc)}

        all_series = get_all_estat_series()
        if series_ids:
            series_list = [s for s in all_series if s["series_id"] in series_ids]
        else:
            series_list = all_series

        log = await self.repo.create_fetch_log(source="estat", job_name="sync_estat_japan_stats")
        rows_fetched = 0
        rows_saved = 0

        try:
            for index, s_info in enumerate(series_list):
                stats_data_id = s_info["stats_data_id"]
                s_id = s_info["series_id"]
                logger.info("Fetching e-Stat statsDataId: %s", stats_data_id)

                observations = await asyncio.to_thread(
                    client.get_stats_data_observations,
                    stats_data_id,
                    60,
                )
                rows_fetched += len(observations)

                series_record = await self.repo.upsert_series(
                    source="estat",
                    series_id=s_id,
                    name=s_info["name"],
                    unit=s_info.get("unit"),
                    frequency=s_info.get("frequency_hint"),
                    category=s_info.get("category"),
                    pro_use=s_info.get("pro_use"),
                    geography=s_info.get("geography"),
                    metadata_json={"stats_data_id": stats_data_id},
                )
                await self.db.flush()

                for obs in observations:
                    await self.repo.upsert_observation(
                        series=series_record,
                        source="estat",
                        series_id=s_id,
                        date_val=obs["date"],
                        value=obs["value"],
                        period_label=obs.get("period_label"),
                        raw_json=obs.get("raw"),
                    )
                    rows_saved += 1

                await self.db.flush()
                if index < len(series_list) - 1:
                    await asyncio.sleep(2)

            await self.repo.finish_fetch_log(
                log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved
            )
            await self.db.commit()
            logger.info("e-Stat sync completed. Saved %s observations.", rows_saved)

        except Exception as exc:
            logger.error("e-Stat sync failed: %s", exc)
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(exc))
            await self.db.commit()

        return {"source": "estat", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_eia_energy_stats(
        self, series_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Fetch and save U.S. weekly petroleum statistics from EIA API v2.
        """
        logger.info("Starting EIA energy stats sync (targeted=%s)...", series_ids is not None)
        try:
            client = EIAClient()
        except ValueError as exc:
            logger.error("EIA sync skipped: %s", exc)
            return {"source": "eia", "rows_fetched": 0, "rows_saved": 0, "error": str(exc)}

        all_series = get_all_eia_series()
        if series_ids:
            series_list = [s for s in all_series if s["series_id"] in series_ids]
        else:
            series_list = all_series

        log = await self.repo.create_fetch_log(source="eia", job_name="sync_eia_energy_stats")
        rows_fetched = 0
        rows_saved = 0

        try:
            for index, s_info in enumerate(series_list):
                s_id = s_info["series_id"]
                logger.info("Fetching EIA series: %s (%s)", s_id, s_info.get("api_route"))

                observations = await asyncio.to_thread(
                    client.fetch_catalog_observations,
                    api_route=s_info.get("api_route"),
                    legacy_route=s_info.get("legacy_route"),
                    fetch_via=s_info.get("fetch_via", "route"),
                    facets=s_info.get("facets"),
                    v1_series_id=s_info.get("v1_series_id"),
                    frequency=s_info.get("frequency_hint", "weekly"),
                    max_observations=52,
                )
                rows_fetched += len(observations)

                series_record = await self.repo.upsert_series(
                    source="eia",
                    series_id=s_id,
                    name=s_info["name"],
                    unit=s_info.get("unit"),
                    frequency=s_info.get("frequency_hint"),
                    category=s_info.get("category"),
                    pro_use=s_info.get("pro_use"),
                    geography=s_info.get("geography"),
                    metadata_json={
                        "api_route": s_info.get("api_route"),
                        "legacy_route": s_info.get("legacy_route"),
                        "fetch_via": s_info.get("fetch_via"),
                        "v1_series_id": s_info.get("v1_series_id"),
                        "facets": s_info.get("facets"),
                    },
                )
                await self.db.flush()

                for obs in observations:
                    await self.repo.upsert_observation(
                        series=series_record,
                        source="eia",
                        series_id=s_id,
                        date_val=obs["date"],
                        value=obs["value"],
                        period_label=obs.get("period_label"),
                        raw_json=obs.get("raw"),
                    )
                    rows_saved += 1

                await self.db.flush()
                if index < len(series_list) - 1:
                    await asyncio.sleep(2)

            await self.repo.finish_fetch_log(
                log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved
            )
            await self.db.commit()
            logger.info("EIA sync completed. Saved %s observations.", rows_saved)

        except Exception as exc:
            logger.error("EIA sync failed: %s", exc)
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(exc))
            await self.db.commit()

        return {"source": "eia", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_ecb_market_stats(
        self, series_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Fetch and save euro area market statistics from ECB SDMX-JSON API.
        """
        logger.info("Starting ECB market stats sync (targeted=%s)...", series_ids is not None)
        client = ECBClient()

        all_series = get_all_ecb_series()
        if series_ids:
            series_list = [s for s in all_series if s["series_id"] in series_ids]
        else:
            series_list = all_series

        log = await self.repo.create_fetch_log(source="ecb", job_name="sync_ecb_market_stats")
        rows_fetched = 0
        rows_saved = 0

        try:
            for index, s_info in enumerate(series_list):
                series_key = s_info["series_key"]
                s_id = s_info["series_id"]
                logger.info("Fetching ECB series: %s", series_key)

                observations = await asyncio.to_thread(
                    client.fetch_series_observations,
                    series_key,
                    60,
                )
                rows_fetched += len(observations)

                series_record = await self.repo.upsert_series(
                    source="ecb",
                    series_id=s_id,
                    name=s_info["name"],
                    unit=s_info.get("unit"),
                    frequency=s_info.get("frequency_hint"),
                    category=s_info.get("category"),
                    pro_use=s_info.get("pro_use"),
                    geography=s_info.get("geography"),
                    metadata_json={"series_key": series_key},
                )
                await self.db.flush()

                for obs in observations:
                    await self.repo.upsert_observation(
                        series=series_record,
                        source="ecb",
                        series_id=s_id,
                        date_val=obs["date"],
                        value=obs["value"],
                        period_label=obs.get("period_label"),
                        raw_json=obs.get("raw"),
                    )
                    rows_saved += 1

                await self.db.flush()
                if index < len(series_list) - 1:
                    await asyncio.sleep(2)

            await self.repo.finish_fetch_log(
                log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved
            )
            await self.db.commit()
            logger.info("ECB sync completed. Saved %s observations.", rows_saved)

        except Exception as exc:
            logger.error("ECB sync failed: %s", exc)
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(exc))
            await self.db.commit()

        return {"source": "ecb", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_south_america_stats(
        self, series_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Fetch and save Brazil macro series from BCB SGS."""
        logger.info("Starting BCB South America sync (targeted=%s)...", series_ids is not None)
        client = BCBClient()
        all_series = get_all_bcb_series()
        series_list = (
            [s for s in all_series if s["series_id"] in series_ids]
            if series_ids
            else all_series
        )

        log = await self.repo.create_fetch_log(source="bcb", job_name="sync_south_america_stats")
        rows_fetched = 0
        rows_saved = 0

        try:
            for index, s_info in enumerate(series_list):
                s_id = s_info["series_id"]
                sgs_id = s_info["sgs_id"]
                logger.info("Fetching BCB SGS series: %s (%s)", s_id, sgs_id)

                observations = await asyncio.to_thread(
                    lambda sid=sgs_id: client.fetch_series_observations(
                        sid, max_observations=60
                    )
                )
                rows_fetched += len(observations)

                series_record = await self.repo.upsert_series(
                    source="bcb",
                    series_id=s_id,
                    name=s_info["name"],
                    unit=s_info.get("unit"),
                    frequency=s_info.get("frequency_hint"),
                    category=s_info.get("category"),
                    pro_use=s_info.get("pro_use"),
                    geography=s_info.get("geography"),
                    metadata_json={"sgs_id": sgs_id},
                )
                await self.db.flush()

                for obs in observations:
                    await self.repo.upsert_observation(
                        series=series_record,
                        source="bcb",
                        series_id=s_id,
                        date_val=obs["date"],
                        value=obs["value"],
                        period_label=obs.get("period_label"),
                        raw_json=obs.get("raw"),
                    )
                    rows_saved += 1

                await self.db.flush()
                if index < len(series_list) - 1:
                    await asyncio.sleep(1)

            await self.repo.finish_fetch_log(
                log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved
            )
            await self.db.commit()
            logger.info("BCB sync completed. Saved %s observations.", rows_saved)
        except Exception as exc:
            logger.error("BCB sync failed: %s", exc)
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(exc))
            await self.db.commit()

        return {"source": "bcb", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_opec_energy_stats(
        self, series_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Fetch and save OPEC-related production statistics (KAPSARC open data)."""
        logger.info("Starting OPEC energy stats sync (targeted=%s)...", series_ids is not None)
        client = OPECClient()
        all_series = get_all_opec_series()
        series_list = (
            [s for s in all_series if s["series_id"] in series_ids]
            if series_ids
            else all_series
        )

        log = await self.repo.create_fetch_log(source="opec", job_name="sync_opec_energy_stats")
        rows_fetched = 0
        rows_saved = 0

        try:
            for index, s_info in enumerate(series_list):
                s_id = s_info["series_id"]
                logger.info("Fetching OPEC series: %s", s_id)

                observations = await asyncio.to_thread(
                    lambda info=s_info: client.fetch_catalog_observations(
                        kapsarc_dataset=info["kapsarc_dataset"],
                        kapsarc_filter=info.get("kapsarc_filter"),
                        max_observations=60,
                    )
                )
                rows_fetched += len(observations)

                series_record = await self.repo.upsert_series(
                    source="opec",
                    series_id=s_id,
                    name=s_info["name"],
                    unit=s_info.get("unit"),
                    frequency=s_info.get("frequency_hint"),
                    category=s_info.get("category"),
                    pro_use=s_info.get("pro_use"),
                    geography=s_info.get("geography"),
                    metadata_json={
                        "kapsarc_dataset": s_info.get("kapsarc_dataset"),
                        "kapsarc_filter": s_info.get("kapsarc_filter"),
                    },
                )
                await self.db.flush()

                for obs in observations:
                    await self.repo.upsert_observation(
                        series=series_record,
                        source="opec",
                        series_id=s_id,
                        date_val=obs["date"],
                        value=obs["value"],
                        period_label=obs.get("period_label"),
                        raw_json=obs.get("raw"),
                    )
                    rows_saved += 1

                await self.db.flush()
                if index < len(series_list) - 1:
                    await asyncio.sleep(2)

            await self.repo.finish_fetch_log(
                log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved
            )
            await self.db.commit()
            logger.info("OPEC sync completed. Saved %s observations.", rows_saved)
        except Exception as exc:
            logger.error("OPEC sync failed: %s", exc)
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(exc))
            await self.db.commit()

        return {"source": "opec", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_asean_supply_chain_stats(
        self, series_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Fetch and save ASEAN trade and investment indicators."""
        logger.info("Starting ASEAN supply chain sync (targeted=%s)...", series_ids is not None)
        client = ASEANClient()
        all_series = get_all_asean_series()
        series_list = (
            [s for s in all_series if s["series_id"] in series_ids]
            if series_ids
            else all_series
        )

        log = await self.repo.create_fetch_log(
            source="asean", job_name="sync_asean_supply_chain_stats"
        )
        rows_fetched = 0
        rows_saved = 0

        try:
            for index, s_info in enumerate(series_list):
                s_id = s_info["series_id"]
                code = s_info["indicator_code"]
                logger.info("Fetching ASEAN indicator: %s", code)

                observations = await asyncio.to_thread(
                    lambda c=code, info=s_info: client.fetch_indicator_observations(
                        c,
                        aggregate_host_code=info.get("aggregate_host_code", "ASEAN"),
                        max_observations=60,
                    )
                )
                rows_fetched += len(observations)
                if not observations and s_info.get("optional"):
                    logger.warning(
                        "ASEAN optional series %s returned no data (API may be unavailable)",
                        code,
                    )

                series_record = await self.repo.upsert_series(
                    source="asean",
                    series_id=s_id,
                    name=s_info["name"],
                    unit=s_info.get("unit"),
                    frequency=s_info.get("frequency_hint"),
                    category=s_info.get("category"),
                    pro_use=s_info.get("pro_use"),
                    geography=s_info.get("geography"),
                    metadata_json={"indicator_code": code},
                )
                await self.db.flush()

                for obs in observations:
                    await self.repo.upsert_observation(
                        series=series_record,
                        source="asean",
                        series_id=s_id,
                        date_val=obs["date"],
                        value=obs["value"],
                        period_label=obs.get("period_label"),
                        raw_json=obs.get("raw"),
                    )
                    rows_saved += 1

                await self.db.flush()
                if index < len(series_list) - 1:
                    await asyncio.sleep(2)

            await self.repo.finish_fetch_log(
                log, status="success", rows_fetched=rows_fetched, rows_saved=rows_saved
            )
            await self.db.commit()
            logger.info("ASEAN sync completed. Saved %s observations.", rows_saved)
        except Exception as exc:
            logger.error("ASEAN sync failed: %s", exc)
            await self.repo.finish_fetch_log(log, status="failed", error_message=str(exc))
            await self.db.commit()

        return {"source": "asean", "rows_fetched": rows_fetched, "rows_saved": rows_saved}

    async def sync_industry_stats(self) -> Dict[str, Any]:
        """
        Run both BEA and Census industry statistics sync jobs.
        """
        results = {}
        results["bea"] = await self.sync_bea_industry_stats()
        results["census"] = await self.sync_census_cbp()
        return results

    async def sync_all_timeseries(self) -> Dict[str, Any]:
        """
        Run all macro-financial time-series sync jobs.
        """
        results = {}
        results["fred"] = await self.sync_fred()
        results["bls"] = await self.sync_bls()
        results["worldbank"] = await self.sync_worldbank()
        return results
