from fastapi import APIRouter, HTTPException
from pathlib import Path
import json

router = APIRouter(tags=["backbone"])

BASE_DIR = Path(__file__).resolve().parent.parent.parent
BACKBONE_DIR = BASE_DIR / "data" / "backbone"


@router.get("/backbone/{sector}")
async def get_backbone_sector(sector: str):
    file_map = {
        "energy": "energy_master_stakeholders_v1.json",
        "market": "market_master_stakeholders_v1.json",
        "trade": "trade_master_stakeholders_v1.json",
        "ai": "ai_tech_master_stakeholders_v1.json",
        "crypto": "crypto_master_stakeholders_v1.json",
        "defense": "defense_master_stakeholders_v1.json",
    }

    if sector not in file_map:
        raise HTTPException(status_code=404, detail="Invalid sector")

    file_path = BACKBONE_DIR / file_map[sector]

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return data