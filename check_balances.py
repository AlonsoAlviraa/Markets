import os
import sys
from dotenv import load_dotenv

# Force LIVE mode for this check
os.environ["MODE"] = "LIVE"
load_dotenv()

from src.wallet.wallet_manager import WalletManager

def check_all_balances():
    print("="*60)
    print("[INFO] WALLET BALANCE CHECKER")
    print("="*60)
    
    try:
        wm = WalletManager()
        print(f"[-] Address: {wm.address}")
        print("-" * 30)
        
        # Check Polygon
        print("\n[POLY] POLYGON NETWORK:")
        try:
            poly_usdc = wm.get_balance('polygon')
            print(f"   [+] USDC:   ${poly_usdc:.2f}")
        except Exception as e:
            print(f"   [!] USDC Error: {e}")
            
        try:
            poly_gas, _, msg = wm.check_gas_balance(min_gas=0.1)
            # We can't easily get the absolute gas amount from the boolean check method without modifying it,
            # but the message usually contains details.
            print(f"   [+] Gas (POL): {'OK' if poly_gas else 'LOW'} ({msg})")
        except Exception as e:
            print(f"   [!] Gas Check Error: {e}")

        # Check SX Network
        print("\n[SX] SX NETWORK:")
        try:
            sx_usdc = wm.get_balance('sx')
            print(f"   [+] USDC:   ${sx_usdc:.2f}")
        except Exception as e:
            print(f"   [!] USDC Error: {e}")
            
        try:
            _, sx_gas, msg = wm.check_gas_balance(min_gas=0.1)
            print(f"   [+] Gas (SX):  {'OK' if sx_gas else 'LOW'} ({msg})")
        except Exception as e:
            print(f"   ❌ Gas Check Error: {e}")
            
        print("\n" + "="*60)

    except Exception as e:
        print(f"[CRITICAL] ERROR: {e}")
        # import traceback
        # traceback.print_exc()

if __name__ == "__main__":
    check_all_balances()
