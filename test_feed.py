
import asyncio
from src.core.feed import MarketDataFeed
import aiohttp
import json

async def get_active_token_id():
    url = "https://gamma-api.polymarket.com/events?limit=1&closed=false&order=volume24hr&ascending=false"
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            data = await resp.json()
            if data and data[0].get('markets'):
                market = data[0]['markets'][0]
                raw_ids = market.get('clobTokenIds')
                ids = json.loads(raw_ids) if isinstance(raw_ids, str) else raw_ids
                return ids[0] if ids else None
    return None

async def handler(msg):
    if msg.get('event_type') == 'price_change':
        print(f"[PRICE] {msg.get('price')} size={msg.get('size')} side={msg.get('side')}")
    elif msg.get('event_type') == 'book':
        print(f"[BOOK] Update received")

async def main():
    feed = MarketDataFeed()
    
    # Add handler
    feed.add_callback(handler)
    
    # Start feed in background
    feed_task = asyncio.create_task(feed.start())
    
    # Wait for connection (rudimentary)
    await asyncio.sleep(2)
    
    # Get ID
    tid = await get_active_token_id()
    if tid:
        print(f"Subscribing to {tid}")
        feed.subscribe([str(tid)])
    
    try:
        # Run for 30s
        await asyncio.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        await feed.stop()
        await feed_task

if __name__ == "__main__":
    asyncio.run(main())
