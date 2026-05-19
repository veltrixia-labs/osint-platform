import os
from dotenv import load_dotenv

load_dotenv()

def verify():
    print("--- Stripe Environment Audit ---")
    
    # 1. Secret Key
    sk = os.getenv("STRIPE_SECRET_KEY")
    if sk:
        print(f"STRIPE_SECRET_KEY: Found (Starts with: {sk[:7]}...)")
    else:
        print("STRIPE_SECRET_KEY: MISSING")
        
    # 2. Price ID
    for key in (
        "STRIPE_PRICE_ID_PRO_MONTHLY",
        "STRIPE_PRICE_ID_PRO_ANNUAL",
        "STRIPE_PRICE_ID_EXPERTS_MONTHLY",
        "STRIPE_PRICE_ID_EXPERTS_ANNUAL",
    ):
        pid = os.getenv(key)
        if pid:
            print(f"{key}: Found ({pid[:12]}...)")
        else:
            print(f"{key}: MISSING")
        
    # 3. Domain URL
    domain = os.getenv("DOMAIN_URL")
    print(f"DOMAIN_URL: {domain or 'MISSING'}")
    
    # 4. Webhook Secret
    wh = os.getenv("STRIPE_WEBHOOK_SECRET")
    if wh:
        print(f"STRIPE_WEBHOOK_SECRET: Found (Starts with: {wh[:6]}...)")
    else:
        print("STRIPE_WEBHOOK_SECRET: Not configured (Optional for confirm-session flow)")
        
    print("-" * 30)

if __name__ == "__main__":
    verify()
