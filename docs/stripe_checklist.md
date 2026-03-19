# Stripe Production Readiness Checklist

Before enabling live Stripe payments, complete all items below in order.
Mark each item ✅ when done.

---

## 1. Environment Separation

| Item | Status |
|---|---|
| `STRIPE_SECRET_KEY` starts with `sk_live_...` in production `.env` | ☐ |
| `STRIPE_SECRET_KEY` starts with `sk_test_...` in all development/staging environments | ☐ |
| `.env` file is **not** committed to version control (confirmed in `.gitignore`) | ☐ |
| Docker Compose secrets (or Kubernetes Secrets) are used to inject keys at runtime | ☐ |

---

## 2. Stripe Dashboard: Price IDs

Replace mock price IDs in `api/payments.py` (`PRICES` dict) with real Stripe Price IDs created in the dashboard.

```python
# api/payments.py
PRICES = {
    "pro": "price_REAL_PRO_ID_HERE",
    "enterprise": "price_REAL_ENTERPRISE_ID_HERE",   # or remove for contact-sales flow
}
```

| Item | Status |
|---|---|
| Pro monthly Price ID created in Stripe Dashboard (live mode) | ☐ |
| Enterprise Price ID created OR `directCheckout: false` confirmed in `subscription.ts` | ☐ |
| Price IDs injected via environment variable (not hardcoded) | ☐ |

---

## 3. Webhook Secret

| Item | Status |
|---|---|
| Stripe Webhook endpoint registered at `https://yourdomain.com/api/payments/webhook` | ☐ |
| `STRIPE_WEBHOOK_SECRET` (`whsec_...`) set in production `.env` | ☐ |
| Webhook events enabled: `checkout.session.completed`, `customer.subscription.deleted`, `customer.subscription.canceled` | ☐ |
| Signature validation tested end-to-end with `stripe listen --forward-to` CLI | ☐ |

---

## 4. Success / Cancel Redirect URLs

Update `DOMAIN_URL` in production `.env` (currently defaults to `http://localhost:8000`):

```env
DOMAIN_URL=https://yourdomain.com
```

Stripe Checkout will redirect to:
- **Success:** `https://yourdomain.com/dashboard?payment=success&session_id={CHECKOUT_SESSION_ID}`
- **Cancel:** `https://yourdomain.com/dashboard?payment=canceled`

| Item | Status |
|---|---|
| `DOMAIN_URL` set to production HTTPS domain | ☐ |
| Success redirect page shows confirmation message to user | ☐ |
| Cancel redirect page shows friendly "no changes made" message | ☐ |

---

## 5. Stripe Customer Portal (for cancel/manage flow)

The current `cancelSubscription()` helper in `api.ts` is a stub. To enable self-serve cancel:

1. Enable **Customer Portal** in Stripe Dashboard → Settings → Billing → Customer Portal
2. Implement `POST /api/payments/portal-session` backend endpoint:

```python
@router.post("/portal-session")
async def create_portal_session(current_user: tuple = Depends(get_current_user_from_access), ...):
    session = stripe.billing_portal.Session.create(
        customer=analyst.stripe_customer_id,
        return_url=f"{DOMAIN_URL}/dashboard"
    )
    return {"url": session.url}
```

3. Update `cancelSubscription()` in `api.ts` to call this endpoint and redirect.

| Item | Status |
|---|---|
| Customer Portal enabled in Stripe Dashboard | ☐ |
| `POST /api/payments/portal-session` implemented | ☐ |
| `cancelSubscription()` in `api.ts` updated to call portal endpoint | ☐ |
| Return URL configured correctly | ☐ |

---

## 6. Security Hardening

| Item | Status |
|---|---|
| Webhook endpoint **only** accepts POST requests | ☐ |
| Stripe signature verification is enforced (no fallback to mock in production) | ☐ |
| Rate limiting applied to `/api/payments/checkout-session` to prevent abuse | ☐ |
| HTTPS enforced for all payment-related redirects | ☐ |

> [!CAUTION]
> Never disable signature verification in production. The mock fallback in `payments.py` (no `STRIPE_SECRET_KEY` check) must be guarded with an environment check before going live.

```python
# Add to api/payments.py webhook handler
if os.getenv("ENV") == "production" and not stripe.api_key:
    raise HTTPException(status_code=503, detail="Payment processing unavailable")
```

---

## 7. Downgrade & Grace Period Verification

| Item | Status |
|---|---|
| Grace period = 3 days confirmed in `api/gating.py` (`GRACE_PERIOD_DAYS`) | ☐ |
| Grace-period banner appears in UI when `expires_at` is within 3 days | ☐ |
| After grace period expires, user is automatically treated as Free tier | ☐ |
| Downgraded user sees FREE badge in sidebar and loses Pro feature access | ☐ |

---

## 8. End-to-End Smoke Test (Staging)

Run against Stripe's test mode before flipping to live keys:

```bash
# 1. Complete a checkout session with Stripe test card 4242424242424242
# 2. Verify DB: analyst.subscription_tier = "pro", stripe_customer_id set

# 3. Trigger webhook manually
stripe trigger checkout.session.completed

# 4. Simulate cancellation
stripe trigger customer.subscription.deleted

# 5. Verify DB: analyst.subscription_tier = "free", expires_at = now
```

| Item | Status |
|---|---|
| Test checkout completes and tier is upgraded | ☐ |
| Cancellation webhook downgrades tier | ☐ |
| Grace period banner visible in UI for near-expiry accounts | ☐ |
| Stripe URL failure in UI shows error message (not crash) | ☐ |
