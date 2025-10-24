#!/usr/bin/env python3
"""
Telegram Notification System for ngTradingBot
Sends alerts and notifications via Telegram Bot API
"""

import logging
import requests
from typing import Optional, Dict
from datetime import datetime
import os

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Send notifications via Telegram"""

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        """
        Initialize Telegram Notifier

        Args:
            bot_token: Telegram Bot Token (from @BotFather)
            chat_id: Your Telegram Chat ID
        """
        self.bot_token = bot_token or os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = chat_id or os.getenv('TELEGRAM_CHAT_ID')
        self.enabled = bool(self.bot_token and self.chat_id)

        if not self.enabled:
            logger.warning(
                "Telegram notifications DISABLED - Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID"
            )
        else:
            logger.info(f"Telegram notifications ENABLED - Chat ID: {self.chat_id}")

    def send_message(self, message: str, parse_mode: str = 'HTML', silent: bool = False) -> bool:
        """
        Send a message via Telegram

        Args:
            message: Message text (supports HTML formatting)
            parse_mode: 'HTML' or 'Markdown'
            silent: Send silently (no notification sound)

        Returns:
            True if message was sent successfully
        """
        if not self.enabled:
            logger.debug(f"Telegram disabled, would have sent: {message}")
            return False

        try:
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode,
                'disable_notification': silent
            }

            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200:
                logger.debug(f"Telegram message sent successfully")
                return True
            else:
                logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error sending Telegram message: {e}")
            return False

    def send_alert(self, title: str, message: str, level: str = 'WARNING') -> bool:
        """
        Send a formatted alert message

        Args:
            title: Alert title
            message: Alert message
            level: 'INFO', 'WARNING', or 'CRITICAL'

        Returns:
            True if sent successfully
        """
        # Emoji mapping
        emoji_map = {
            'INFO': 'ℹ️',
            'WARNING': '⚠️',
            'CRITICAL': '🚨'
        }

        emoji = emoji_map.get(level, '📢')

        formatted_message = f"""
{emoji} <b>{level}: {title}</b>

{message}

<i>Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</i>
"""

        # Critical alerts should make sound
        silent = (level == 'INFO')

        return self.send_message(formatted_message, silent=silent)

    def send_connection_alert(self, account_number: int, last_heartbeat: datetime,
                             age_seconds: int) -> bool:
        """Send MT5 connection lost alert"""

        age_minutes = age_seconds // 60

        message = f"""
⚠️ <b>MT5 CONNECTION LOST</b>

<b>Account:</b> #{account_number}
<b>Last Heartbeat:</b> {last_heartbeat.strftime('%Y-%m-%d %H:%M:%S')}
<b>Offline for:</b> {age_minutes} minutes

<b>Actions taken:</b>
• Auto-trading paused
• No new trades will be opened
• Existing trades continue to be monitored

<i>Please check MT5 Terminal and EA status!</i>
"""

        return self.send_message(message, silent=False)

    def send_connection_restored(self, account_number: int, offline_duration: int) -> bool:
        """Send MT5 connection restored notification"""

        message = f"""
✅ <b>MT5 CONNECTION RESTORED</b>

<b>Account:</b> #{account_number}
<b>Offline duration:</b> {offline_duration // 60} minutes

<b>Status:</b>
• Connection re-established
• Receiving live data
• Auto-trading resumed

<i>System back to normal operation.</i>
"""

        return self.send_message(message, silent=True)

    def send_trade_alert(self, trade_info: Dict) -> bool:
        """Send trade execution alert"""

        symbol = trade_info.get('symbol')
        direction = trade_info.get('direction', '').upper()
        entry = trade_info.get('entry_price')
        sl = trade_info.get('sl')
        tp = trade_info.get('tp')
        confidence = trade_info.get('confidence', 0)
        volume = trade_info.get('volume', 0)

        # Calculate risk/reward
        if entry and sl and tp:
            risk = abs(float(entry) - float(sl))
            reward = abs(float(tp) - float(entry))
            rr_ratio = reward / risk if risk > 0 else 0
        else:
            rr_ratio = 0

        # ✅ NEW FORMAT: Symbol + Direction FIRST, then compact details
        message = f"""
🔔 <b>{symbol} {direction}</b> | {confidence:.0f}%

Entry: {entry:.5f}
SL: {sl:.5f} | TP: {tp:.5f}"""

        # Add R/R ratio if available
        if rr_ratio > 0:
            message += f"\nR:R 1:{rr_ratio:.1f}"

        # Add volume if available
        if volume:
            message += f" | Vol: {volume}"

        return self.send_message(message, silent=True)

    def send_trade_closed_alert(self, trade_info: Dict, account_balance: float) -> bool:
        """Send trade closed notification with current account balance"""

        ticket = trade_info.get('ticket')
        symbol = trade_info.get('symbol')
        direction = trade_info.get('direction', '').upper()
        volume = trade_info.get('volume', 0)
        open_price = trade_info.get('open_price', 0)
        close_price = trade_info.get('close_price', 0)
        profit = trade_info.get('profit', 0)
        swap = trade_info.get('swap', 0)
        commission = trade_info.get('commission', 0)
        close_reason = trade_info.get('close_reason', 'Unknown')
        duration = trade_info.get('duration', '')

        # Calculate total P&L
        total_pnl = float(profit or 0) + float(swap or 0) + float(commission or 0)

        # Choose emoji based on profit
        if total_pnl > 0:
            pnl_emoji = '✅'
            result_text = 'WIN'
        elif total_pnl < 0:
            pnl_emoji = '❌'
            result_text = 'LOSS'
        else:
            pnl_emoji = '➖'
            result_text = 'BREAKEVEN'

        # Format close reason (compact)
        reason_map = {
            'TP_HIT': 'TP',
            'SL_HIT': 'SL',
            'MANUAL': 'Manual',
            'TRAILING_STOP': 'Trail',
            'TIME_EXIT': 'Time',
            'STRATEGY_INVALID': 'Invalid',
            'EMERGENCY_CLOSE': 'Emergency',
            'PARTIAL_CLOSE': 'Partial'
        }
        close_reason_short = reason_map.get(close_reason, close_reason)

        # ✅ NEW FORMAT: Emoji + Amount FIRST, then details
        message = f"""
{pnl_emoji} <b>€{total_pnl:+.2f}</b> | {symbol} {direction}

#{ticket} | {close_reason_short}{f' | {duration}' if duration else ''}
Entry: {open_price:.5f} → Exit: {close_price:.5f}

💰 Balance: €{account_balance:.2f}
"""

        # Add detailed breakdown only for significant trades (|P&L| > 1 EUR)
        if abs(total_pnl) > 1.0:
            message += f"\n<i>P: €{profit:.2f} | S: €{swap:.2f} | C: €{commission:.2f}</i>"

        # Don't silence if it's a loss (so you notice)
        silent = (total_pnl >= 0)

        return self.send_message(message, silent=silent)

    def send_daily_summary(self, stats: Dict) -> bool:
        """Send daily performance summary"""

        trades_today = stats.get('trades_today', 0)
        profit_today = stats.get('profit_today', 0)
        win_rate = stats.get('win_rate', 0)
        wins = stats.get('wins', 0)
        losses = stats.get('losses', 0)

        # Choose emoji based on profit
        if profit_today > 0:
            profit_emoji = '✅'
        elif profit_today < 0:
            profit_emoji = '❌'
        else:
            profit_emoji = '➖'

        # ✅ NEW FORMAT: Profit FIRST, then compact stats
        message = f"""
📊 <b>Daily Summary</b> | {datetime.now().strftime('%d.%m.%Y')}

{profit_emoji} <b>€{profit_today:+.2f}</b>

{trades_today} Trades | {win_rate:.0f}% WR ({wins}W/{losses}L)
"""

        return self.send_message(message, silent=True)

    def test_connection(self) -> bool:
        """Test Telegram connection"""

        if not self.enabled:
            logger.error("Telegram not configured")
            return False

        message = """
🤖 <b>ngTradingBot - Test Message</b>

Telegram notifications are working!

<i>This is a test message from your trading bot.</i>
"""

        return self.send_message(message)


# Singleton instance
_notifier_instance = None


def get_telegram_notifier() -> TelegramNotifier:
    """Get or create Telegram notifier singleton"""
    global _notifier_instance

    if _notifier_instance is None:
        _notifier_instance = TelegramNotifier()

    return _notifier_instance


if __name__ == '__main__':
    # Test script
    print("Testing Telegram Notifier...")

    # You can set these via environment variables or pass them directly
    # bot_token = "YOUR_BOT_TOKEN"
    # chat_id = "YOUR_CHAT_ID"

    notifier = get_telegram_notifier()

    if notifier.test_connection():
        print("✅ Test message sent successfully!")
    else:
        print("❌ Failed to send test message. Check your credentials.")
