"""
test_phase33_gating.py
Phase 33 - Automated Backend Gating Tests
"""

import asyncio
import httpx
import sys

BASE = "http://127.0.0.1:8003"
PASS = 0
FAIL = 0


def ok(label):
    global PASS
    PASS += 1
    print(f"  [OK]  {label}")


def fail(label, detail=""):
    global FAIL
    FAIL += 1
    print(f"  [FAIL]  {label}  -- {detail}")


async def get_token():
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{BASE}/api/auth/login", json={
            "telegram_chat_id": "testuser",
            "password": "password123"
        })
        assert r.status_code == 200, f"Login failed: {r.text}"
        return r.json()["access_token"]


async def run_tests():
    token = await get_token()
    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient() as c:
        # 1. GET /api/system/usage - Free tier limits
        print("\n[1] Usage endpoint - Free tier limits")
        r = await c.get(f"{BASE}/api/system/usage", headers=headers)
        if r.status_code != 200:
            fail("GET /api/system/usage", f"HTTP {r.status_code}")
        else:
            u = r.json()
            if u["tier"] == "free":
                ok("tier == free")
            else:
                fail("tier == free", f"got {u['tier']}")
            if u["alerts"]["limit"] == 5:
                ok("alerts.limit == 5")
            else:
                fail("alerts.limit == 5", f"got {u['alerts']['limit']}")
            if u["keywords"]["limit"] == 3:
                ok("keywords.limit == 3")
            else:
                fail("keywords.limit == 3", f"got {u['keywords']['limit']}")
            if u["reports"]["daily"] is True:
                ok("reports.daily == true")
            else:
                fail("reports.daily == true")
            if u["reports"]["monthly"] is False:
                ok("reports.monthly == false")
            else:
                fail("reports.monthly == false")
            if len(u["topics"]["restricted"]) > 0:
                ok(f"restricted topics present ({len(u['topics']['restricted'])})")
            else:
                fail("restricted topics present", "empty list")

        # 2. Watchlist enforcement - Free tier (limit = 3)
        print("\n[2] Watchlist keyword limit - Free tier")
        me = (await c.get(f"{BASE}/api/auth/me", headers=headers)).json()
        uid = me["id"]

        # 2a. Set exactly 3 keywords -> should succeed
        r = await c.post(
            f"{BASE}/api/analysts/{uid}/watchlist",
            headers={**headers, "Content-Type": "application/json"},
            json={"keywords": ["alpha", "bravo", "charlie"]},
        )
        if r.status_code == 200:
            ok("3 keywords (at limit) -> 200")
        else:
            fail("3 keywords -> 200", f"HTTP {r.status_code}: {r.text}")

        # 2b. Set 4 keywords -> should fail with 403
        r = await c.post(
            f"{BASE}/api/analysts/{uid}/watchlist",
            headers={**headers, "Content-Type": "application/json"},
            json={"keywords": ["alpha", "bravo", "charlie", "delta"]},
        )
        if r.status_code == 403:
            ok("4 keywords (over limit) -> 403")
        else:
            fail("4 keywords -> 403", f"HTTP {r.status_code}: {r.text}")

        # 3. Topic gating - Free tier
        print("\n[3] Topic gating - Free tier")

        # 3a. Allowed topic
        r = await c.get(f"{BASE}/api/alerts?topic=global&limit=5", headers=headers)
        if r.status_code == 200:
            ok("topic=global -> 200")
        else:
            fail("topic=global -> 200", f"HTTP {r.status_code}")

        # 3b. Restricted topic
        r = await c.get(f"{BASE}/api/alerts?topic=energy_resource_risk&limit=5", headers=headers)
        if r.status_code == 403:
            ok("topic=energy_resource_risk -> 403")
        else:
            fail("topic=energy_resource_risk -> 403", f"HTTP {r.status_code}")

        # 4. Upgrade to Pro via mock checkout
        print("\n[4] Mock upgrade to Pro")
        r = await c.get(f"{BASE}/api/payments/checkout-session?tier=pro", headers=headers)
        if r.status_code == 200 and r.json().get("success"):
            ok("mock upgrade -> Pro success")
        else:
            fail("mock upgrade -> Pro", f"HTTP {r.status_code}: {r.text}")

        # Refresh token after tier change
        token_new = await get_token()
        headers = {"Authorization": f"Bearer {token_new}"}

        # 5. Pro tier - limits updated
        print("\n[5] Usage endpoint - Pro tier limits")
        r = await c.get(f"{BASE}/api/system/usage", headers=headers)
        if r.status_code == 200:
            u = r.json()
            if u["tier"] == "pro":
                ok("tier == pro")
            else:
                fail("tier == pro", f"got {u['tier']}")
            if u["alerts"]["limit"] == 100:
                ok("alerts.limit == 100")
            else:
                fail("alerts.limit == 100", f"got {u['alerts']['limit']}")
            if u["keywords"]["limit"] == 20:
                ok("keywords.limit == 20")
            else:
                fail("keywords.limit == 20", f"got {u['keywords']['limit']}")
            if u["reports"]["monthly"] is True:
                ok("reports.monthly == true (Pro)")
            else:
                fail("reports.monthly == true")
            if len(u["topics"]["restricted"]) == 0:
                ok("no restricted topics (Pro)")
            else:
                fail("no restricted topics", f"restricted: {u['topics']['restricted']}")
        else:
            fail("GET /api/system/usage (Pro)", f"HTTP {r.status_code}")

        # 6. Pro bypasses Free limits
        print("\n[6] Pro bypasses Free-tier restrictions")

        # 6a. 4 keywords should now work
        r = await c.post(
            f"{BASE}/api/analysts/{uid}/watchlist",
            headers={**headers, "Content-Type": "application/json"},
            json={"keywords": ["alpha", "bravo", "charlie", "delta"]},
        )
        if r.status_code == 200:
            ok("4 keywords (Pro) -> 200")
        else:
            fail("4 keywords (Pro) -> 200", f"HTTP {r.status_code}: {r.text}")

        # 6b. Specialized topic should now work
        r = await c.get(f"{BASE}/api/alerts?topic=energy_resource_risk&limit=5", headers=headers)
        if r.status_code == 200:
            ok("topic=energy_resource_risk (Pro) -> 200")
        else:
            fail("topic=energy_resource_risk (Pro) -> 200", f"HTTP {r.status_code}")

    # Summary
    print(f"\n{'='*50}")
    print(f"Phase 33 Gating Tests:  {PASS} passed,  {FAIL} failed")
    print(f"{'='*50}")
    if FAIL > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_tests())
