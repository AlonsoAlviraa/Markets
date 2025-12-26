"""
Atomic Arbitrage Scanner for Polymarket

Monitors all markets for the condition:
    Cost(YES) + Cost(NO) != $1.00

When the sum deviates from $1.00, there's an arbitrage opportunity:
- Sum < $1.00: Buy both YES and NO, merge for guaranteed profit
- Sum > $1.00: Split USDC into YES+NO, sell both for guaranteed profit
"""

import asyncio
import aiohttp
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from dataclasses import dataclass


@dataclass
class ArbitrageOpportunity:
    market_id: str
    market_title: str
    yes_price: float
    no_price: float
    sum_price: float
    deviation: float  # How far from $1.00
    direction: str    # "BUY_MERGE" or "SPLIT_SELL"
    estimated_profit_pct: float
    yes_token_id: str
    no_token_id: str
    timestamp: datetime


class AtomicArbitrageScanner:
    """
    Scans Polymarket for atomic arbitrage opportunities.
    
    An atomic arbitrage exists when:
    - YES + NO < $1.00 (buy both, merge to get $1.00)
    - YES + NO > $1.00 (split $1.00, sell both)
    
    Polymarket fee: 2% on profits
    """
    
    POLYMARKET_FEE = 0.02  # 2% fee on winnings
    MIN_DEVIATION_THRESHOLD = 0.005  # 0.5% minimum deviation to be interesting
    MIN_PROFIT_THRESHOLD = 0.002     # 0.2% minimum profit after fees
    
    def __init__(self):
        self.gamma_url = "https://gamma-api.polymarket.com/events"
        self.clob_url = "https://clob.polymarket.com"
        self.opportunities: List[ArbitrageOpportunity] = []
        
    async def fetch_all_markets(self) -> List[Dict]:
        """Fetch all active markets from Polymarket"""
        all_events = []
        
        params = {
            "closed": "false",
            "limit": 100,
            "offset": 0,
            "order": "volume24hr",
            "ascending": "false"
        }
        
        async with aiohttp.ClientSession() as session:
            for offset in range(0, 500, 100):
                params["offset"] = offset
                try:
                    async with session.get(self.gamma_url, params=params, timeout=15) as response:
                        if response.status != 200:
                            break
                        data = await response.json()
                        if not data:
                            break
                        all_events.extend(data)
                except Exception as e:
                    print(f"Error fetching markets: {e}")
                    break
        
        return all_events
    
    async def get_market_prices(self, session: aiohttp.ClientSession, 
                                 yes_token_id: str, no_token_id: str) -> Tuple[Optional[float], Optional[float], Optional[float], Optional[float]]:
        """
        Get best BID and ASK prices for YES and NO tokens.
        Returns: (yes_bid, yes_ask, no_bid, no_ask)
        """
        yes_bid = yes_ask = no_bid = no_ask = None
        
        # Helper to fetch one book
        async def fetch_book(token_id):
            try:
                url = f"{self.clob_url}/book?token_id={token_id}"
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        return await response.json()
            except:
                return None
        
        # Fetch both concurrently
        yes_book, no_book = await asyncio.gather(
            fetch_book(yes_token_id),
            fetch_book(no_token_id)
        )
        
        if yes_book:
            bids = yes_book.get("bids", [])
            asks = yes_book.get("asks", [])
            if bids: yes_bid = float(bids[0]["price"])
            if asks: yes_ask = float(asks[0]["price"])
            
        if no_book:
            bids = no_book.get("bids", [])
            asks = no_book.get("asks", [])
            if bids: no_bid = float(bids[0]["price"])
            if asks: no_ask = float(asks[0]["price"])
            
        return yes_bid, yes_ask, no_bid, no_ask
    
    def calculate_profit(self, entry_cost: float, exit_value: float) -> float:
        """
        Calculate profit percentage based on entry cost and exit value.
        Fee is 2% on net winnings (Profit).
        """
        gross_profit = exit_value - entry_cost
        if gross_profit <= 0: return 0.0
        
        fee = gross_profit * self.POLYMARKET_FEE
        net_profit = gross_profit - fee
        
        return (net_profit / entry_cost) * 100
    
    async def scan_for_opportunities(self) -> List[ArbitrageOpportunity]:
        """
        Main scanning function. Checks all markets for atomic arbitrage.
        """
        print(f"\n{'='*60}")
        print(f"[ATOMIC ARBITRAGE SCANNER]")
        print(f"   Threshold: {self.MIN_DEVIATION_THRESHOLD*100:.1f}% deviation")
        print(f"   Min Profit: {self.MIN_PROFIT_THRESHOLD*100:.2f}% after fees")
        print(f"{'='*60}\n")
        
        start_time = datetime.now()
        opportunities = []
        markets_checked = 0
        
        events = await self.fetch_all_markets()
        print(f"Fetched {len(events)} events")
        
        total_markets = sum(len(e.get("markets", [])) for e in events)
        print(f"Total markets to check: {total_markets}")
        
        async with aiohttp.ClientSession() as session:
            tasks = []
            sem = asyncio.Semaphore(20)  # Concurrency limit
            
            async def process_market(market, event):
                async with sem:
                    # Get token IDs
                    token_ids_raw = market.get("clobTokenIds", None)
                    if not token_ids_raw: return
                    
                    # Parse token IDs
                    import json
                    if isinstance(token_ids_raw, str):
                        try:
                            token_ids = json.loads(token_ids_raw)
                        except:
                            return
                    else:
                        token_ids = token_ids_raw
                    
                    if not token_ids or len(token_ids) != 2: return
                    
                    yes_token_id = str(token_ids[0])
                    no_token_id = str(token_ids[1])
                    
                    if yes_token_id.startswith("0x"): yes_token_id = str(int(yes_token_id, 16))
                    if no_token_id.startswith("0x"): no_token_id = str(int(no_token_id, 16))
                    
                    # Get prices
                    yes_bid, yes_ask, no_bid, no_ask = await self.get_market_prices(
                        session, yes_token_id, no_token_id
                    )
                    
                    # Check Case 1: BUY MERGE
                    if yes_ask is not None and no_ask is not None:
                        buy_cost = yes_ask + no_ask
                        if buy_cost < (1.0 - self.MIN_DEVIATION_THRESHOLD):
                            profit_pct = self.calculate_profit(entry_cost=buy_cost, exit_value=1.0)
                            if profit_pct >= self.MIN_PROFIT_THRESHOLD * 100:
                                self.log_opportunity(market, event, "BUY_MERGE", yes_ask, no_ask, buy_cost, profit_pct, yes_token_id, no_token_id)

                    # Check Case 2: SPLIT SELL
                    if yes_bid is not None and no_bid is not None:
                        sell_revenue = yes_bid + no_bid
                        if sell_revenue > (1.0 + self.MIN_DEVIATION_THRESHOLD):
                            profit_pct = self.calculate_profit(entry_cost=1.0, exit_value=sell_revenue)
                            if profit_pct >= self.MIN_PROFIT_THRESHOLD * 100:
                                self.log_opportunity(market, event, "SPLIT_SELL", yes_bid, no_bid, sell_revenue, profit_pct, yes_token_id, no_token_id)
            
            # Create tasks
            for event in events:
                markets = event.get("markets", [])
                for market in markets:
                    tasks.append(process_market(market, event))
            
            print(f"Processing {len(tasks)} markets concurrently...")
            await asyncio.gather(*tasks)
    
    def log_opportunity(self, market, event, direction, p1, p2, sum_price, profit_pct, t1, t2):
        deviation = sum_price - 1.0
        opp = ArbitrageOpportunity(
            market_id=market.get("id", ""),
            market_title=event.get("title", "Unknown")[:50],
            yes_price=p1,
            no_price=p2,
            sum_price=sum_price,
            deviation=deviation,
            direction=direction,
            estimated_profit_pct=profit_pct,
            yes_token_id=t1,
            no_token_id=t2,
            timestamp=datetime.now()
        )
        # Monkey patch or update dataclass later, for now just attach it
        opp.condition_id = market.get("conditionId")
        self.opportunities.append(opp)
        
        arrow = ">>>" if direction == "SPLIT_SELL" else "<<<"
        print(f"\n{arrow} OPPORTUNITY FOUND!")
        print(f"   Market: {opp.market_title}")
        print(f"   YES: ${p1:.4f} | NO: ${p2:.4f}")
        print(f"   Sum: ${sum_price:.4f} ({deviation:+.4f})")
        print(f"   Direction: {direction}")
        print(f"   Est. Profit: {profit_pct:.2f}%")
        
        elapsed = (datetime.now() - start_time).total_seconds()
        print(f"\n[OK] Scan complete in {elapsed:.1f}s")
        print(f"   Markets checked: {markets_checked}")
        print(f"   Opportunities found: {len(opportunities)}")
        
        self.opportunities = opportunities
        return opportunities


async def main():
    scanner = AtomicArbitrageScanner()
    opps = await scanner.scan_for_opportunities()
    
    if opps:
        print("\n" + "="*60)
        print("📋 SUMMARY OF OPPORTUNITIES")
        print("="*60)
        for opp in sorted(opps, key=lambda x: -x.estimated_profit_pct):
            print(f"\n{opp.market_title}")
            print(f"  {opp.direction}: {opp.estimated_profit_pct:.2f}% profit")
            print(f"  YES=${opp.yes_price:.4f} + NO=${opp.no_price:.4f} = ${opp.sum_price:.4f}")
    else:
        print("\n[X] No atomic arbitrage opportunities found at this time.")


if __name__ == "__main__":
    asyncio.run(main())
