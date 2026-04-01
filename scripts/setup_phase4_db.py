import os
import sys
import uuid
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure we can import from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import get_engine_args, Base
from db.models import Stakeholder, Dependency

def setup_phase4():
    print("--- Phase 4: Database Expansion & Seeding ---")
    
    # Get sync engine
    db_url, connect_args, _ = get_engine_args(use_asyncpg=False)
    engine = create_engine(db_url, connect_args=connect_args)
    
    # 1. Create Tables
    print("Creating tables...")
    Base.metadata.create_all(engine)
    
    # 2. Enable WAL Mode for SQLite
    if "sqlite" in db_url:
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL;"))
            print("WAL Mode enabled.")
            
    # 3. Seed Initial Stakeholders
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Seed Initial Stakeholders
        print("Seeding Initial Stakeholders...")
        
        seeds = [
            # AI & Semiconductors
            {"name": "NVIDIA", "ticker": "NVDA", "sector": "AI/GPU", "country": "USA", "domain": "ai_semi", "description": "Global AI compute leader.", "lat": 37.3871, "lng": -121.9667},
            {"name": "TSMC", "ticker": "TSM", "sector": "Foundry", "country": "Taiwan", "domain": "ai_semi", "description": "Critical node in semiconductor supply chain.", "lat": 24.7736, "lng": 121.0117},
            {"name": "ASML", "ticker": "ASML", "sector": "Lithography", "country": "Netherlands", "domain": "ai_semi", "description": "Sole supplier of EUV machines.", "lat": 51.4231, "lng": 5.4211},
            
            # Global Market
            {"name": "Federal Reserve", "ticker": "^GSPC", "sector": "Central Bank", "country": "USA", "domain": "market", "description": "US Monetary Authority.", "lat": 38.8921, "lng": -77.0460},
            {"name": "BlackRock", "ticker": "BLK", "sector": "Asset Management", "country": "USA", "domain": "market", "description": "Global capital flow proxy.", "lat": 40.7589, "lng": -73.9790},
            {"name": "SWIFT", "ticker": None, "sector": "Financial Network", "country": "Belgium", "domain": "market", "description": "International payments backbone.", "lat": 50.8503, "lng": 4.3517},
            
            # Energy & Resource
            {"name": "OPEC+", "ticker": "CL=F", "sector": "Cartel", "country": "Global", "domain": "energy", "description": "Oil production control body.", "lat": 48.2082, "lng": 16.3738},
            {"name": "Saudi Aramco", "ticker": "ARMCO", "sector": "Oil & Gas", "country": "Saudi Arabia", "domain": "energy", "description": "Worlds largest oil exporter.", "lat": 26.2886, "lng": 50.1140},
            {"name": "CATL", "ticker": "300750.SZ", "sector": "Battery", "country": "China", "domain": "energy", "description": "Global EV battery leader.", "lat": 26.6669, "lng": 119.5333},
            
            # Supply Chain
            {"name": "Maersk", "ticker": "MAERSK-B.CO", "sector": "Shipping", "country": "Denmark", "domain": "supply_chain", "description": "Global container logistics barometer.", "lat": 55.6841, "lng": 12.5925},
            {"name": "FedEx", "ticker": "FDX", "sector": "Logistics", "country": "USA", "domain": "supply_chain", "description": "Global express delivery barometer.", "lat": 35.1495, "lng": -90.0490},
            
            # Defense Technology
            {"name": "Lockheed Martin", "ticker": "LMT", "sector": "Aerospace", "country": "USA", "domain": "defense", "description": "Critical defense contractor.", "lat": 39.0253, "lng": -77.1775},
            {"name": "SpaceX/Starlink", "ticker": None, "sector": "Space/Comms", "country": "USA", "domain": "defense", "description": "Strategic satellite communication.", "lat": 33.9213, "lng": -118.3267},
            
            # Crypto & Geopolitics
            {"name": "Binance", "ticker": "BNB", "sector": "Exchange", "country": "Global", "domain": "crypto", "description": "Central node of liquidity for non-state actors.", "lat": 1.3521, "lng": 103.8198},
            {"name": "Tether", "ticker": "USDT", "sector": "Stablecoin", "country": "Global", "domain": "crypto", "description": "Global shadow liquidity backbone.", "lat": 19.3133, "lng": -81.2546},
            
            # Digital Infrastructure & Cyber (NEW)
            {"name": "Microsoft (Azure)", "ticker": "MSFT", "sector": "Cloud", "country": "USA", "domain": "digital_infra", "description": "Core intelligence and enterprise cloud.", "lat": 47.6740, "lng": -122.1215},
            {"name": "Amazon (AWS)", "ticker": "AMZN", "sector": "Cloud", "country": "USA", "domain": "digital_infra", "description": "Backbone of global digital infrastructure.", "lat": 47.6062, "lng": -122.3321},
            {"name": "Cloudflare", "ticker": "NET", "sector": "Cybersecurity", "country": "USA", "domain": "digital_infra", "description": "Chokepoint for web traffic protection.", "lat": 37.7749, "lng": -122.4194},
            {"name": "Equinix", "ticker": "EQIX", "sector": "Data Centers", "country": "USA", "domain": "digital_infra", "description": "Global physical hub for network peering.", "lat": 37.5255, "lng": -121.9219},
            {"name": "CrowdStrike", "ticker": "CRWD", "sector": "Cybersecurity", "country": "USA", "domain": "digital_infra", "description": "Strategic endpoint security.", "lat": 34.0522, "lng": -118.2437}
        ]
        
        stakeholder_objs = []
        for s in seeds:
            obj = Stakeholder(
                name=s["name"],
                ticker=s["ticker"],
                sector=s["sector"],
                country=s["country"],
                domain=s["domain"],
                description=s["description"],
                location_lat=s["lat"],
                location_lng=s["lng"]
            )
            stakeholder_objs.append(obj)
            
        session.add_all(stakeholder_objs)
        session.commit()
        print(f"Successfully seeded {len(stakeholder_objs)} stakeholders.")
        
        # 4. Seed Critical Dependencies (Cascading Links)
        print("Seeding Initial Dependencies...")
        # Get ID mapping for seeds
        id_map = {s.name: s.id for s in stakeholder_objs}
        
        dep_seeds = [
            # AI & Semi Chain
            {"source": "TSMC", "target": "NVIDIA", "type": "upstream_supply", "weight": 0.85, "beta": 1.2},
            {"source": "ASML", "target": "TSMC", "type": "upstream_supply", "weight": 0.90, "beta": 1.1},
            {"source": "NVIDIA", "target": "Microsoft (Azure)", "type": "compute_infra", "weight": 0.70, "beta": 1.0},
            {"source": "NVIDIA", "target": "Amazon (AWS)", "type": "compute_infra", "weight": 0.65, "beta": 1.0},
            
            # Energy & Supply Chain Ripple
            {"source": "OPEC+", "target": "Saudi Aramco", "type": "policy_governance", "weight": 0.95, "beta": 1.5},
            {"source": "Saudi Aramco", "target": "Maersk", "type": "fuel_cost", "weight": 0.40, "beta": 0.8},
            {"source": "Maersk", "target": "FedEx", "type": "logistics_chain", "weight": 0.30, "beta": 0.7},
            
            # Market & Digital Infra
            {"source": "Federal Reserve", "target": "BlackRock", "type": "monetary_policy", "weight": 0.60, "beta": 1.2},
            {"source": "BlackRock", "target": "Binance", "type": "capital_flow", "weight": 0.20, "beta": 1.5},
            {"source": "Cloudflare", "target": "Microsoft (Azure)", "type": "security_gate", "weight": 0.25, "beta": 0.9},
            {"source": "CrowdStrike", "target": "Equinix", "type": "endpoint_security", "weight": 0.35, "beta": 1.0}
        ]
        
        dependency_objs = []
        for d in dep_seeds:
            if d["source"] in id_map and d["target"] in id_map:
                obj = Dependency(
                    source_id=id_map[d["source"]],
                    target_id=id_map[d["target"]],
                    dependency_type=d["type"],
                    exposure_weight=d["weight"],
                    beta_correlation=d["beta"]
                )
                dependency_objs.append(obj)
        
        session.add_all(dependency_objs)
        session.commit()
        print(f"Successfully seeded {len(dependency_objs)} dependencies.")
        
    except Exception as e:
        session.rollback()
        print(f"Error during seeding: {e}")
        raise e
    finally:
        session.close()

if __name__ == "__main__":
    setup_phase4()
