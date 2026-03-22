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
    pid = os.getenv("STRIPE_PRICE_ID_PRO")
    if pid:
        print(f"STRIPE_PRICE_ID_PRO: Found (Starts with: {pid[:9]}...)")
    else:
        print("STRIPE_PRICE_ID_PRO: MISSING")
        
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
