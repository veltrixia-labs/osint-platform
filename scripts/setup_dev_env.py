import os
import sys
import shutil
import subprocess
import uuid
import json
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Ensure we can import from project root
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.database import get_engine_args, Base
from db.models import Stakeholder, Dependency, AnalystProfile, AlertLog
from api.auth import get_password_hash

def run_command(cmd, cwd=None):
    print(f"Executing: {cmd}")
    process = subprocess.Popen(cmd, shell=True, cwd=cwd)
    process.communicate()
    if process.returncode != 0:
        print(f"Error executing command: {cmd}")
        # sys.exit(1) # Continue even if npm fails if DB part is needed

def setup_dev_env():
    print("--- OSINT Full-Stack Sync & Setup ---")
    
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    web_dir = os.path.join(base_dir, "web_dashboard")
    dist_dir = os.path.join(web_dir, "dist")

    # 1. Frontend Clean Build
    print("Step 1: Cleaning and Rebuilding Frontend...")
    if os.path.exists(dist_dir):
        shutil.rmtree(dist_dir)
        print("Purged stale dist directory.")
    
    # Run npm install and build
    run_command("npm install", cwd=web_dir)
    run_command("npm run build", cwd=web_dir)

    # 2. Database Initialization & Seeding
    print("\nStep 2: Database Initialization & Expert-Tier Seeding...")
    db_url, connect_args, _ = get_engine_args(use_asyncpg=False)
    engine = create_engine(db_url, connect_args=connect_args)
    
    # Ensure tables exist
    Base.metadata.create_all(engine)
    
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # A. Promote Admin & TestUser
        print("Promoting admin and testuser to ENTERPRISE tier...")
        dev_accounts = [
            ("admin@veltrixia.local", "admin", "admin"),
            ("testuser@veltrixia.local", "testuser", "analyst"),
        ]
        for email, password, role in dev_accounts:
            user = session.query(AnalystProfile).filter_by(email=email).first()
            if user:
                user.subscription_tier = "enterprise"
                user.subscription_expires_at = None
                if role == "admin":
                    user.is_admin = True
                    user.user_role = "admin"
                print(f"Updated {email} to enterprise.")
            else:
                print(f"Creating missing user: {email}")
                new_user = AnalystProfile(
                    email=email,
                    hashed_password=get_password_hash(password),
                    user_role=role,
                    is_admin=(role == "admin"),
                    subscription_tier="enterprise",
                    is_active=True,
                )
                session.add(new_user)

        # B. Seed Stakeholders with Coordinates (for Arcs)
        print("Seeding stakeholders with geo-coordinates...")
        seeds = [
            {"name": "NVIDIA", "lat": 37.3871, "lng": -121.9667},
            {"name": "TSMC", "lat": 24.7736, "lng": 121.0117},
            {"name": "Microsoft (Azure)", "lat": 47.6740, "lng": -122.1215}
        ]
        for s in seeds:
            stk = session.query(Stakeholder).filter_by(name=s["name"]).first()
            if stk:
                stk.location_lat = s["lat"]
                stk.location_lng = s["lng"]
            else:
                stk = Stakeholder(name=s["name"], location_lat=s["lat"], location_lng=s["lng"], domain="ai_semi")
                session.add(stk)

        # C. Master Verification Alert (Curved Arcs)
        print("Generating Master Verification Alert...")
        # Clear old alerts to avoid clutter
        session.execute(text("DELETE FROM alert_logs"))
        
        master_alert = AlertLog(
            id=uuid.uuid4(),
            severity="high",
            target_label="Strategic AI Infrastructure Surge",
            topic="ai_semiconductor_intelligence",
            intensity=9.5,
            trigger_type="cascading_impact",
            triggered_at=datetime.now(timezone.utc),
            location_lat=37.3871, # NVIDIA HQ
            location_lng=-121.9667,
            is_high_fidelity=True,
            metadata_json={
                "cascading_impacts": [
                    {
                        "entity_name": "TSMC",
                        "impact_alpha": 5.2,
                        "reasoning": "Direct semiconductor supply chain boost.",
                        "location_lat": 24.7736,
                        "location_lng": 121.0117
                    },
                    {
                        "entity_name": "Microsoft",
                        "impact_alpha": -1.8,
                        "reasoning": "Increased infrastructure CapEx pressure.",
                        "location_lat": 47.6740,
                        "location_lng": -122.1215
                    }
                ]
            }
        )
        session.add(master_alert)
        session.commit()
        print("Setup Complete. Dashboard is ready for Expert-tier verification.")

    except Exception as e:
        session.rollback()
        print(f"Error during setup: {e}")
    finally:
        session.close()

if __name__ == "__main__":
    setup_dev_env()
