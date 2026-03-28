import asyncio
import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import uuid

# Add project root to path
sys.path.append(os.getcwd())

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_alert_dedup_logic():
    print("\n--- Starting Alert Dedup Logic Regression Test ---")
    
    # Mock Database Session
    db = AsyncMock()
    
    # Mock Result Object
    mock_result = MagicMock()
    db.execute.return_value = mock_result
    
    from jobs.alert_manager import AlertManager
    
    # Mock AlertLog model
    mock_alert_log = MagicMock(spec=["severity", "id"])
    mock_alert_log.id = uuid.uuid4()
    mock_alert_log.severity = "watch"
    
    # CASE 1: No previous alert exists (Should NOT be suppressed)
    print("\nCASE 1: No previous alert exists")
    mock_result.scalar_one_or_none.return_value = None
    
    is_suppressed = await AlertManager._is_suppressed(db, "Iran", "global", "pattern_risk", "watch")
    print(f"Is Suppressed? {is_suppressed} (Expect: False)")
    assert is_suppressed is False

    # CASE 2: Same severity exists within 12h (Should BE suppressed)
    print("\nCASE 2: Same severity exists within 12h")
    db.execute.return_value.scalar_one_or_none.return_value = mock_alert_log
    
    is_suppressed = await AlertManager._is_suppressed(db, "Iran", "global", "pattern_risk", "watch")
    print(f"Is Suppressed? {is_suppressed} (Expect: True)")
    assert is_suppressed is True

    # CASE 3: Higher severity arrives (Escalation - Should NOT be suppressed)
    print("\nCASE 3: Higher severity arrives (Watch -> Elevated)")
    is_suppressed = await AlertManager._is_suppressed(db, "Iran", "global", "pattern_risk", "elevated")
    print(f"Is Suppressed? {is_suppressed} (Expect: False)")
    assert is_suppressed is False

    # CASE 4: Lower/Equal severity arrives after existing Elevated (Should BE suppressed)
    mock_alert_log.severity = "elevated"
    print("\nCASE 4: Lower severity (Watch) arrives after Elevated")
    is_suppressed = await AlertManager._is_suppressed(db, "Iran", "global", "pattern_risk", "watch")
    print(f"Is Suppressed? {is_suppressed} (Expect: True)")
    assert is_suppressed is True
    
    print("\nCASE 5: Same severity (Elevated) arrives after Elevated")
    is_suppressed = await AlertManager._is_suppressed(db, "Iran", "global", "pattern_risk", "elevated")
    print(f"Is Suppressed? {is_suppressed} (Expect: True)")
    assert is_suppressed is True

    # CASE 6: Critical Escalation (Elevated -> Critical - Should NOT be suppressed)
    print("\nCASE 6: Critical Escalation (Elevated -> Critical)")
    is_suppressed = await AlertManager._is_suppressed(db, "Iran", "global", "pattern_risk", "critical")
    print(f"Is Suppressed? {is_suppressed} (Expect: False)")
    assert is_suppressed is False

    print("\n--- ALL CASES PASSED ---")

if __name__ == "__main__":
    asyncio.run(test_alert_dedup_logic())
