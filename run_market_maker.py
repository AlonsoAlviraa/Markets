
import asyncio
import aiohttp
import json
from src.strategies.market_maker import SimpleMarketMaker

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

async def main():
    print("Fetching active market...")
    token_id = await get_active_token_id()
    if not token_id:
        print("No token found")
        return
        
    print(f"Target Token: {token_id}")
    
    mm = SimpleMarketMaker(token_ids=[str(token_id)])
    try:
        await mm.start()
    except KeyboardInterrupt:
        print("Stopping...")
        await mm.feed.stop()

if __name__ == "__main__":
    asyncio.run(main())
