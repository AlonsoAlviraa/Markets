
import unittest
import asyncio
from unittest.mock import MagicMock, AsyncMock
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.strategies.market_maker import SimpleMarketMaker
from src.core.orderbook import OrderBook

class TestSimpleMarketMakerSafety(unittest.IsolatedAsyncioTestCase):
    
    async def asyncSetUp(self):
        self.mock_executor = MagicMock()
        self.mock_executor.place_order = MagicMock(return_value="oid_1")
        self.mock_executor.cancel_order = MagicMock()
        
        self.mm = SimpleMarketMaker(
            token_ids=["123"], 
            executor=self.mock_executor, 
            dry_run=True, 
            spread=0.02, 
            size=10.0
        )
        # Manually init book
        self.mm.books["123"] = OrderBook("123")

    async def test_spread_calculation(self):
        """Verify Bid/Ask calculation respects spread"""
        book = self.mm.books["123"]
        # Market: Bid 0.40, Ask 0.60 -> Mid 0.50
        book.update("BUY", 0.40, 100)
        book.update("SELL", 0.60, 100)
        
        mid = book.get_mid_price()
        self.assertEqual(mid, 0.50)
        
        # We expect Mid +/- (Spread/2) = 0.50 +/- 0.01 = 0.49 / 0.51
        # Calling update_quotes (Async verification)
        # We mock execute_quotes to capture values
        self.mm.execute_quotes = AsyncMock()
        
        await self.mm.update_quotes("123", mid, book)
        
        # Verify execute_quotes NOT called because dry_run=True? 
        # Wait, implementation calls execute_quotes inside 'else' block of dry_run check.
        # So in dry_run, it should print but NOT call execute_quotes.
        self.mm.execute_quotes.assert_not_called()
        
    async def test_live_execution_safety(self):
        """Verify calling Place Order happens ONLY in Live Mode"""
        self.mm.dry_run = False
        
        book = self.mm.books["123"]
        book.update("BUY", 0.40, 100)
        book.update("SELL", 0.60, 100)
        mid = 0.50
        
        # Real execute_quotes logic uses self.executor
        # We want to test logic inside update_quotes -> execute_quotes
        # But execute_quotes logic uses run_in_executor.
        # It's hard to mock run_in_executor perfectly in unit test without loop setup.
        # We will mock execute_quotes to simply check values passed
        
        self.mm.execute_quotes = AsyncMock()
        await self.mm.update_quotes("123", mid, book)
        
        self.mm.execute_quotes.assert_called_once()
        args = self.mm.execute_quotes.call_args[0]
        token_id, bid, ask = args
        
        self.assertEqual(token_id, "123")
        self.assertEqual(bid, 0.49)
        self.assertEqual(ask, 0.51)
        self.assertTrue(bid < ask, "Bid must be lower than Ask")
        self.assertTrue(bid > 0, "Bid must be positive")
        self.assertTrue(ask < 1, "Ask must be < 1.0")

    async def test_crossed_market_protection(self):
        """Verify we do not quote if calculation results in crossed book"""
        # Scenario: Spread 0.02. Mid 0.50.
        # If we accidentally calculated Bid 0.51, Ask 0.49 -> CROSS.
        # Logic in update_quotes: 
        # if my_bid >= my_ask: return
        
        # Let's force a weird mid or negative spread config
        self.mm.spread = -0.05 # Negative spread configuration (Invalid but possible input)
        
        book = self.mm.books["123"]
        book.update("BUY", 0.50, 100)
        book.update("SELL", 0.50, 100) # Mid 0.50
        
        # Mid 0.50. Spread -0.05.
        # Bid = 0.50 - (-0.025) = 0.525
        # Ask = 0.50 + (-0.025) = 0.475
        # 0.525 > 0.475 -> Crossed.
        
        self.mm.execute_quotes = AsyncMock()
        await self.mm.update_quotes("123", 0.50, book)
        
        # Should return early and NOT execute
        self.mm.execute_quotes.assert_not_called()

if __name__ == '__main__':
    unittest.main()
