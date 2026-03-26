import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
import logging
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from jobs.alert_scoring import calculate_alert_score

async def test_reproduce_crash():
    logging.basicConfig(level=logging.INFO)
    
    # Mock database session
    db = AsyncMock()
    
    # CASE 1: avg_feedback is a Decimal (The production crash case)
    # Mocking the scalar() return value of db.execute(stmt)
    mock_result = MagicMock()
    mock_result.scalar.return_value = Decimal("3.5")
    db.execute.return_value = mock_result
    
    print("Testing with Decimal feedback (Production Crash Case)...")
    try:
        score, breakdown = await calculate_alert_score(
            db, 
            intensity=8.5, 
            spike=2.0, 
            domains=5, 
            trigger_type="test_trigger", 
            target_label="test_label"
        )
        print(f"SUCCESS: Score = {score}")
        print(f"Breakdown: {breakdown}")
    except TypeError as e:
        print(f"FAILED: Caught expected TypeError: {e}")
    except Exception as e:
        print(f"FAILED: Caught unexpected exception: {type(e).__name__}: {e}")

    # CASE 2: Mixed None values
    print("\nTesting with None values...")
    try:
        score, breakdown = await calculate_alert_score(
            db, 
            intensity=None, 
            spike=None, 
            domains=None, 
            trigger_type="test_trigger", 
            target_label="test_label"
        )
        print(f"SUCCESS: Score = {score}")
    except Exception as e:
        print(f"FAILED: Caught exception with None values: {e}")

if __name__ == "__main__":
    asyncio.run(test_reproduce_crash())
