import os
import sys
import uuid
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure we can import from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import get_engine_args, Base
from db.models import Stakeholder, Dependency

def seed_stakeholders_v17():
    print("--- Phase 8.8: Strategic Intelligence Asset Seeding ---")
    
    db_url, connect_args, _ = get_engine_args(use_asyncpg=False)
    engine = create_engine(db_url, connect_args=connect_args)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # 1. High-Precision Coordinates & Strategic Roles
        entities = [
            # AI & Semiconductors
            {"name": "Samsung Electronics", "ticker": "005930.KS", "domain": "ai_semi", "lat": 37.0, "lng": 127.05, "desc": "HBM & Foundry leader."},
            {"name": "Intel", "ticker": "INTC", "domain": "ai_semi", "lat": 45.53, "lng": -122.95, "desc": "US Logic backbone."},
            {"name": "Arm Holdings", "ticker": "ARM", "domain": "ai_semi", "lat": 52.17, "lng": 0.17, "desc": "Architecture IP standard."},
            {"name": "Tokyo Electron", "ticker": "8035.T", "domain": "ai_semi", "lat": 35.66, "lng": 139.73, "desc": "Essential semi-equipment pivot."},
            {"name": "NVIDIA", "ticker": "NVDA", "domain": "ai_semi", "lat": 37.3871, "lng": -121.9667, "desc": "AI training hardware lead."},
            {"name": "TSMC", "ticker": "TSM", "domain": "ai_semi", "lat": 24.7736, "lng": 121.0117, "desc": "Global foundry anchor."},
            
            # Energy & Resources
            {"name": "Gazprom", "ticker": "GAZP.ME", "domain": "energy", "lat": 59.93, "lng": 30.36, "desc": "Russian gas bridge."},
            {"name": "Rio Tinto", "ticker": "RIO", "domain": "energy", "lat": -37.81, "lng": 144.96, "desc": "Critical mineral miner."},
            {"name": "Rare Earth (Baotou)", "ticker": None, "domain": "energy", "lat": 40.65, "lng": 109.84, "desc": "Global REE refining hub."},
            {"name": "Bab-el-Mandeb", "ticker": None, "domain": "supply_chain", "lat": 12.6, "lng": 43.34, "desc": "Strait of maritime risk."},
            
            # Market
            {"name": "European Central Bank", "ticker": None, "domain": "market", "lat": 50.11, "lng": 8.68, "desc": "Euro stability pivot."},
            {"name": "JPMorgan Chase", "ticker": "JPM", "domain": "market", "lat": 40.75, "lng": -73.97, "desc": "Global money center bank."},
            {"name": "Goldman Sachs", "ticker": "GS", "domain": "market", "lat": 40.71, "lng": -74.01, "desc": "Institutional sentiment proxy."},
            {"name": "Citadel Securities", "ticker": None, "domain": "market", "lat": 41.87, "lng": -87.63, "desc": "Systemic market maker."},
            {"name": "Federal Reserve", "ticker": None, "domain": "market", "lat": 38.89, "lng": -77.04, "desc": "US Monetary engine."},
            
            # Supply Chain
            {"name": "Panama Canal", "ticker": None, "domain": "supply_chain", "lat": 9.11, "lng": -79.72, "desc": "Trans-American trade link."},
            {"name": "DP World", "ticker": None, "domain": "supply_chain", "lat": 25.04, "lng": 55.05, "desc": "Port operations nexus."},
            {"name": "Maersk", "ticker": "MAERSK-B.CO", "domain": "supply_chain", "lat": 55.68, "lng": 12.59, "desc": "Global shipping benchmark."},
            
            # Defense
            {"name": "Palantir", "ticker": "PLTR", "domain": "defense", "lat": 39.73, "lng": -104.99, "desc": "Intelligence OS lead."},
            {"name": "Northrop Grumman", "ticker": "NOC", "domain": "defense", "lat": 38.88, "lng": -77.22, "desc": "Stealth & Space hardware."},
            {"name": "Andersen AFB (Guam)", "ticker": None, "domain": "defense", "lat": 13.58, "lng": 144.92, "desc": "Pacific bombers hub."},
            
            # Crypto
            {"name": "Coinbase", "ticker": "COIN", "domain": "crypto", "lat": 37.77, "lng": -122.41, "desc": "US Crypto compliance pivot."},
            {"name": "Circle", "ticker": None, "domain": "crypto", "lat": 42.36, "lng": -71.06, "desc": "USDC liquidity pillar."}
        ]
        
        stakeholder_map = {}
        for e in entities:
            stk = session.query(Stakeholder).filter_by(name=e["name"]).first()
            if not stk:
                stk = Stakeholder(
                    name=e["name"],
                    ticker=e["ticker"],
                    domain=e["domain"],
                    location_lat=e["lat"],
                    location_lng=e["lng"],
                    description=e["desc"]
                )
                session.add(stk)
                session.flush()
            else:
                # Update coords for precision
                stk.location_lat = e["lat"]
                stk.location_lng = e["lng"]
                stk.description = e["desc"]
            stakeholder_map[e["name"]] = stk

        # 2. Directed Dependency Mapping (Cascading Logic)
        print("Defining strategic dependencies...")
        dependencies = [
            # Semi Logic: Hardware Stack
            ("Tokyo Electron", "TSMC", "supplier", 0.9),
            ("Arm Holdings", "NVIDIA", "regulator", 0.8), # IP lock
            ("TSMC", "NVIDIA", "supplier", 0.95),
            ("TSMC", "Apple", "supplier", 0.85), # Apple is implicit or should be added
            
            # Maritime Choke Points
            ("Bab-el-Mandeb", "Maersk", "regulator", 0.9), # Physical gatekeeper
            ("Panama Canal", "Maersk", "regulator", 0.7),
            ("Suez Canal", "Maersk", "regulator", 0.85),
            
            # Market Logic
            ("Federal Reserve", "JPMorgan Chase", "regulator", 0.9),
            ("Federal Reserve", "Goldman Sachs", "regulator", 0.8),
            
            # Defense & AI
            ("Palantir", "Northrop Grumman", "supplier", 0.6), # Software integration
            ("NVIDIA", "Palantir", "supplier", 0.75), # Compute dependence
        ]
        
        for src_name, tgt_name, dep_type, weight in dependencies:
            if src_name in stakeholder_map and tgt_name in stakeholder_map:
                src = stakeholder_map[src_name]
                tgt = stakeholder_map[tgt_name]
                
                existing_dep = session.query(Dependency).filter_by(source_id=src.id, target_id=tgt.id).first()
                if not existing_dep:
                    dep = Dependency(
                        source_id=src.id,
                        target_id=tgt.id,
                        dependency_type=dep_type,
                        exposure_weight=weight
                    )
                    session.add(dep)
        
        session.commit()
        print("Phase 8.8 Seeding Complete: 23+ Entities and Strategic Arcs updated.")
        
    except Exception as e:
        session.rollback()
        print(f"Error during seeding: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    seed_stakeholders_v17()
