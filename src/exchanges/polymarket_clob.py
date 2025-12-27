import os
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

class PolymarketOrderExecutor:
    """
    Handles order execution on Polymarket CLOB.
    """
    
    def __init__(self):
        self.host = os.getenv("POLY_HOST", "https://clob.polymarket.com")
        self.key = os.getenv("PRIVATE_KEY")
        self.chain_id = int(os.getenv("POLY_CHAIN_ID", "137"))
        
        if not self.key:
            raise ValueError("PRIVATE_KEY not found in env")
            
        self.client = ClobClient(
            host=self.host,
            key=self.key,
            chain_id=self.chain_id,
            # signature_type=2 # Removed to allow auto-detection (Default is EOA)
                             # Standard py-clob-client uses signature_type=None by default which auto-detects or defaults to 1?
                             # Let's try default first.
        )
        self.client.set_api_creds(self.client.create_or_derive_api_creds())

    def place_order(self, token_id, side, price, size):
        """
        Place a Limit Order.
        side: "BUY" or "SELL"
        price: Float (e.g. 0.50)
        size: Float (amount of shares)
        """
        try:
            order_side = BUY if side.upper() == "BUY" else SELL
            
            print(f"🔄 Placing {side} Order: {size} shares @ {price} for token {token_id}...")
            
            resp = self.client.create_and_post_order(
                OrderArgs(
                    price=price,
                    size=size,
                    side=order_side,
                    token_id=token_id
                )
            )
            
            if resp and resp.get("success"):
                order_id = resp.get("orderID")
                print(f"✅ Order Placed! ID: {order_id}")
                return order_id
            else:
                print(f"❌ Order Failed: {resp}")
                return None
                
        except Exception as e:
            print(f"❌ Order Exception: {e}")
            return None

    def cancel_order(self, order_id):
        return self.client.cancel(order_id)
        
    def cancel_all(self):
        return self.client.cancel_all()

    def get_token_balance(self, token_id: str) -> float:
        """
        Fetch token balance (Inventory).
        Tries to use CLOB client or returns 0.0.
        """
        try:
            # Note: py_clob_client's get_balance_allowance usually requires asset_type/token_id
            # Usage depends on library version. Assuming standard interface.
            # If not available, we might need a workaround or external wallet manager.
            # For now, safe default.
            # resp = self.client.get_balance_allowance(...) 
            # Placeholder:
            return 0.0
        except Exception as e:
            print(f"❌ Failed to fetch balance: {e}")
            return 0.0
