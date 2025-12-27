
import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from src.strategies.copy_bot import CopyBot
from src.strategies.spy_network import PolygonSpy

def test_spy_parsing():
    async def run_test():
        # Mock Callback
        callback = AsyncMock()
        spy = PolygonSpy(["0xWhale"], callback)
        
        # Simulate PolygonScan TX Response for a BUY (Incoming Token)
        mock_tx = {
            "tokenID": "12345",
            "tokenName": "Trump YES",
            "tokenValue": "1000",
            "to": "0xwhale",
            "from": "0xExchange",
            "hash": "0x123",
            "blockNumber": "100"
        }
        
        spy._process_tx("0xWhale", mock_tx)
        
        # Verify Callback (process_tx is sync but calls async callback)
        # Actually _process_tx fires create_task. We need to yield control.
        await asyncio.sleep(0.01)
        
        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event['side'] == "BUY"
        assert event['amount'] == 1000.0
        assert event['token_id'] == "12345"
        
    asyncio.run(run_test())

def test_copy_bot_integration():
    async def run_test():
        executor = AsyncMock()
        with patch("src.strategies.copy_bot.send_telegram_alert") as mock_tg:
            bot = CopyBot(["0xWhale"], executor)
            bot.active = True
            
            # Simulate Trade Event
            trade = {
                "wallet": "0xWhale",
                "type": "trade",
                "side": "BUY",
                "token_id": "12345", 
                "amount": 100.0,
                "tx_hash": "0xabc"
            }
            
            await bot.on_trade_event(trade)
            
            # Verify Alert Sent
            mock_tg.assert_called_once()
            assert "WHALE ALERT" in mock_tg.call_args[0][0]
            
    asyncio.run(run_test())

def test_whale_hunter_integration():
    async def run_test():
        # Mock API Response
        mock_data = [
            {"proxyWallet": "0xAlpha", "pnl": "100000", "vol": "50000", "userName": "AlphaGod"},
            {"proxyWallet": "0xBeta", "pnl": "500", "vol": "100", "userName": "SmallFry"}
        ]
        
        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json.return_value = mock_data
            mock_get.return_value.__aenter__.return_value = mock_resp
            
            # Init CopyBot (which inits Hunter)
            executor = AsyncMock()
            bot = CopyBot(["0xConfig"], executor)
            
            # Manually trigger refresh
            await bot.refresh_targets()
            
            # Assert 0xAlpha added (High PnL), 0xBeta ignored (Low PnL default > 5000)
            assert "0xAlpha" in bot.target_wallets
            assert "0xconfig" in [t.lower() for t in bot.target_wallets] # Original kept
            
    asyncio.run(run_test())
