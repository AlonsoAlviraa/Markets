import asyncio
import aiohttp
import json
import websockets
from config import POLY_HOST

async def get_active_token_id():
    """Fetch one active token ID from Gamma API"""
    url = "https://gamma-api.polymarket.com/events?limit=1&closed=false&order=volume24hr&ascending=false"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            if data and data[0].get('markets'):
                market = data[0]['markets'][0]
                # clobTokenIds is usually a JSON string
                raw_ids = market.get('clobTokenIds')
                if isinstance(raw_ids, str):
                    ids = json.loads(raw_ids)
                else:
                    ids = raw_ids
                return ids[0] if ids else None
    return None

async def main():
    print("Testing WebSocket connection...")
    
    token_id = await get_active_token_id()
    if not token_id:
        print("[X] Could not find active token ID")
        return

    print(f"Using Token ID: {token_id}")
    
    # Polymarket WS Endpoint
    ws_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    
    async with websockets.connect(ws_url) as websocket:
        print("[OK] Connected to WS.")
        
        # Subscribe to market (L2 or price)
        msg = {
            "assets_ids": [str(token_id)], 
            "type": "market"
        }
        
        await websocket.send(json.dumps(msg))
        print(f"Sent subscription for {token_id}")
        
        print("Waiting for messages (Press Ctrl+C to stop)...")
        try:
            while True:
                response = await asyncio.wait_for(websocket.recv(), timeout=20)
                data = json.loads(response)
                # Print simplified update
                if isinstance(data, list):
                    for update in data:
                        if update.get('event_type') == 'price_change':
                            print(f"[PRICE] Price Update: {update.get('price')} (Side: {update.get('side')})")
                        elif update.get('event_type') == 'book':
                            print("[BOOK] Book Snapshot/Update received")
                        else:
                            print(f"[MSG] Msg: {data}")
                else:
                    print(f"[MSG] Msg: {data}")
                    
        except asyncio.TimeoutError:
            print("[WARN] No messages received for 20s. Market might be quiet.")

if __name__ == "__main__":
    asyncio.run(main())
