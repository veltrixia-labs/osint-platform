import os
import sys
import uuid
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from api.payments import stripe_webhook

async def test_stripe_robust_integrity():
    print("--- Stripe Robust Integrity Verification Start ---")
    
    mock_db = AsyncMock()
    # ACM Helper
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=mock_db)
    cm.__aexit__ = AsyncMock(return_value=None)
    mock_db.begin = MagicMock(return_value=cm)
    
    mock_request = MagicMock()
    mock_request.body = AsyncMock(return_value=b'{}')
    mock_request.headers = {'stripe-signature': 'valid'}

    with patch('stripe.Webhook.construct_event') as mock_construct:
        mock_construct.return_value = {'id': 'evt_trace', 'type': 'checkout.session.completed', 'data': {'object': {}}}
        
        # 1. Test case: Constraint Name Match (Primary Detection)
        name_error = IntegrityError("stmt", "params", "UNIQUE constraint failed: uq_stripe_event_id")
        with patch('api.payments._is_event_processed', AsyncMock(return_value=False)):
            with patch('api.payments.StripeEvent', side_effect=name_error):
                resp = await stripe_webhook(mock_request, mock_db)
                assert resp["status"] == "already_processed"
                print("PASS: Already Processed on Constraint Name match")

        # 2. Test case: Fallback String Match (Legacy/Driver-specific)
        fallback_error = IntegrityError("stmt", "params", "duplicate key value violates unique constraint stripe_events_event_id_key")
        with patch('api.payments._is_event_processed', AsyncMock(return_value=False)):
            with patch('api.payments.StripeEvent', side_effect=fallback_error):
                resp = await stripe_webhook(mock_request, mock_db)
                assert resp["status"] == "already_processed"
                print("PASS: Already Processed on Fallback String match")

        # 3. Test case: BLOCKED IntegrityError
        blocked_error = IntegrityError("stmt", "params", "NOT NULL constraint failed: profile.user_id")
        with patch('api.payments._is_event_processed', AsyncMock(return_value=False)):
            with patch('api.payments.StripeEvent', side_effect=blocked_error):
                try:
                    await stripe_webhook(mock_request, mock_db)
                    assert False, "Should have raised 500"
                except HTTPException as e:
                    assert e.status_code == 500
                    print("PASS: 500 Error on unrelated IntegrityError")

    print("\nSUMMARY: STRIPE ROBUST INTEGRITY [SUCCESS]")

if __name__ == "__main__":
    asyncio.run(test_stripe_robust_integrity())
