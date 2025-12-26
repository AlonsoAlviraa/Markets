import asyncio
import requests
from typing import Optional

class TelegramBot:
    """Simple Telegram bot for notifications"""
    
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    async def send_message(self, text: str) -> bool:
        """Send a message to Telegram using non-blocking aiohttp"""
        url = f"{self.base_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=10) as response:
                    return response.status == 200
        except Exception as e:
            print(f"Failed to send Telegram message: {e}")
            return False
    
    async def send_startup_message(self):
        """Send bot startup notification"""
        await self.send_message("🤖 *Arbitrage Bot Started*\n\nMonitoring for opportunities...")
    
    async def send_arb_alert(self, opportunity: dict, position_size: float = 10.0):
        """Send detailed arbitrage opportunity alert"""
        poly_event = opportunity.get('poly_event', {})
        sx_event = opportunity.get('sx_event', {})
        strategy = opportunity.get('strategy', {})
        
        profit_usd = (opportunity.get('profit_percent', 0) / 100) * position_size
        
        # Format the side (Buy Yes/No)
        poly_side = strategy.get('poly_side', '').replace('_', ' ').upper()
        sx_side = strategy.get('sx_side', '').replace('_', ' ').upper()
        
        # Construct message
        poly_slug = poly_event.get("slug", "")
        poly_link = f"https://polymarket.com/event/{poly_slug}" if poly_slug else "https://polymarket.com"
        
        # SX Bet Link - linking to sport/league if possible, otherwise main
        # Default to main site with instruction
        sx_label = sx_event.get("label", "Unknown")
        sx_sport = sx_event.get("sportId", "sports")
        sx_link = f"https://sx.bet/ (Search: {sx_label})"
        
        message = (
            f"🚨 *ARBITRAGE SIGNAL DETECTED* 🚨\n\n"
            f"🏆 *Event:* {poly_event.get('title', 'Unknown')}\n"
            f"📈 *Profit:* {opportunity.get('profit_percent', 0):.2f}% (~${profit_usd:.2f})\n"
            f"💼 *Bet Size:* ${position_size:.2f} per side\n\n"
            
            f"🔵 *POLYMARKET ACTION:*\n"
            f"• Action: *{poly_side}*\n"
            f"• Price: ${opportunity.get('poly_price', 0):.3f}\n"
            f"• Market: {poly_event.get('title')}\n"
            f"🔗 [OPEN MARKET]({poly_link})\n\n"
            
            f"🟢 *SX BET ACTION:*\n"
            f"• Action: *{sx_side}*\n"
            f"• Price: ${opportunity.get('sx_price', 0):.3f}\n"
            f"• Market: {sx_label}\n"
            f"🔗 {sx_link}\n\n"
            
            f"⚡ *EXECUTE NOW!*"
        )
        await self.send_message(message)
    async def send_atomic_alert(self, opp, position_size: float = 10.0):
        """Send atomic arbitrage (mint/merge) alert"""
        
        # Calculate sums and profits
        profit_usd = (opp.estimated_profit_pct / 100) * position_size
        direction_emoji = "📉" if opp.direction == "BUY_MERGE" else "📈"
        action = "BUY YES + NO" if opp.direction == "BUY_MERGE" else "SPLIT & SELL YES + NO"
        
        message = (
            f"⚛️ *ATOMIC ARBITRAGE SIGNAL* {direction_emoji}\n\n"
            f"🏆 *Market:* {opp.market_title}\n"
            f"💰 *Profit:* {opp.estimated_profit_pct:.2f}% (Est. ${profit_usd:.2f} per ${position_size})\n\n"
            
            f"🛑 *Target Prices:*\n"
            f"• YES: ${opp.yes_price:.4f}\n"
            f"• NO:  ${opp.no_price:.4f}\n"
            f"• sum: ${opp.sum_price:.4f} (Dev: {opp.deviation:+.4f})\n\n"
            
            f"⚡ *ACTION: {action}*\n"
            f"🔗 [OPEN MARKET](https://polymarket.com/market/{opp.market_id})"
        )
        await self.send_message(message)
