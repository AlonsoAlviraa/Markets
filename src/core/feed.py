
import asyncio
import json
import logging
import websockets
from typing import List, Callable, Dict, Any, Optional

logger = logging.getLogger(__name__)

class MarketDataFeed:
    """
    Real-time Market Data Feed for Polymarket.
    Manages WebSocket connection, subscriptions, and message dispatch.
    """
    
    def __init__(self, endpoint: str = "wss://ws-subscriptions-clob.polymarket.com/ws/market"):
        self.endpoint = endpoint
        self.websocket = None
        self.running = False
        self.subscriptions: List[str] = []
        self.callbacks: List[Callable[[Dict], None]] = []
        self.lock = asyncio.Lock()
        
    async def start(self):
        """Start the feed connection loop"""
        self.running = True
        while self.running:
            try:
                print(f"[CONN] Connecting to {self.endpoint}...")
                async with websockets.connect(self.endpoint) as ws:
                    self.websocket = ws
                    print("[OK] WebSocket Connected")
                    
                    # Resubscribe if needed
                    await self._send_subscription()
                    
                    # Message Loop
                    while self.running:
                        try:
                            msg_raw = await asyncio.wait_for(ws.recv(), timeout=20)
                            msg = json.loads(msg_raw)
                            
                            # Dispatch
                            await self._dispatch(msg)
                            
                        except asyncio.TimeoutError:
                            # Send Ping or just continue? 
                            # If timeout, we might want to reconnect if it happens too often.
                            # For now, just continue (maybe send ping?)
                           try:
                               await ws.ping()
                           except:
                               break # Connection likely dead
                        
            except Exception as e:
                print(f"[ERR] WebSocket Error: {e}")
                print("[RETRY] Reconnecting in 5s...")
                await asyncio.sleep(5)
            finally:
                self.websocket = None

    async def stop(self):
        """Stop the feed"""
        self.running = False
        if self.websocket:
            await self.websocket.close()

    def subscribe(self, token_ids: List[str]):
        """Subscribe to a list of token IDs"""
        # Add filtering for uniqueness
        new_ids = [tid for tid in token_ids if tid not in self.subscriptions]
        if not new_ids: return
        
        self.subscriptions.extend(new_ids)
        
        # If active, send immediately
        if self.websocket:
            asyncio.create_task(self._send_subscription())

    async def _send_subscription(self):
        """Send subscription message for all tracked tokens"""
        if not self.websocket or not self.subscriptions: return
        
        # Batch? Poly WS allows list of asset_ids.
        # Check limits (maybe 100 per message?)
        # For now, send one big batch or split if huge.
        
        msg = {
            "assets_ids": self.subscriptions,
            "type": "market"
        }
        try:
            await self.websocket.send(json.dumps(msg))
            print(f"[SUB] Subscribed to {len(self.subscriptions)} assets")
        except Exception as e:
            print(f"[ERR] Sub failed: {e}")

    def add_callback(self, callback: Callable[[Dict], Any]):
        """Register a function to process updates"""
        self.callbacks.append(callback)

    async def _dispatch(self, msg: Any):
        """Send message to all callbacks"""
        # If list, iterate
        if isinstance(msg, list):
            for m in msg:
                for cb in self.callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(m)
                        else:
                            cb(m)
                    except Exception as e:
                        print(f"Callback error: {e}")
        else:
             for cb in self.callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(msg)
                    else:
                        cb(msg)
                except Exception as e:
                    print(f"Callback error: {e}")
