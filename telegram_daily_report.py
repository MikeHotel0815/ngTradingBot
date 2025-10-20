#!/usr/bin/env python3
"""
Telegram Daily Report for ngTradingBot
Sends comprehensive daily performance report via Telegram

Usage:
    python telegram_daily_report.py
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict
from sqlalchemy import func, and_

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import ScopedSession
from models import Trade, TradingSignal, Command
from telegram_notifier import TelegramNotifier

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TelegramDailyReporter:
    """Generate and send daily performance reports via Telegram"""

    def __init__(self, account_id: int = 1):
        self.account_id = account_id
        self.db = ScopedSession()
        self.notifier = TelegramNotifier()

    def get_24h_stats(self) -> Dict:
        """Get last 24 hours statistics"""
        since = datetime.utcnow() - timedelta(hours=24)

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= since,
            Trade.status == 'closed'
        ).all()

        if not trades:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'total_profit': 0.0,
                'buy_trades': 0,
                'buy_wins': 0,
                'buy_wr': 0.0,
                'buy_profit': 0.0,
                'sell_trades': 0,
                'sell_wins': 0,
                'sell_wr': 0.0,
                'sell_profit': 0.0
            }

        # Overall stats
        wins = [t for t in trades if float(t.profit) > 0]
        losses = [t for t in trades if float(t.profit) < 0]
        total_profit = sum(float(t.profit) for t in trades)
        win_rate = (len(wins) / len(trades)) * 100 if trades else 0.0

        # BUY stats
        buy_trades = [t for t in trades if t.direction.upper() == 'BUY']
        buy_wins = [t for t in buy_trades if float(t.profit) > 0]
        buy_wr = (len(buy_wins) / len(buy_trades)) * 100 if buy_trades else 0.0
        buy_profit = sum(float(t.profit) for t in buy_trades)

        # SELL stats
        sell_trades = [t for t in trades if t.direction.upper() == 'SELL']
        sell_wins = [t for t in sell_trades if float(t.profit) > 0]
        sell_wr = (len(sell_wins) / len(sell_trades)) * 100 if sell_trades else 0.0
        sell_profit = sum(float(t.profit) for t in sell_trades)

        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'total_profit': total_profit,
            'buy_trades': len(buy_trades),
            'buy_wins': len(buy_wins),
            'buy_wr': buy_wr,
            'buy_profit': buy_profit,
            'sell_trades': len(sell_trades),
            'sell_wins': len(sell_wins),
            'sell_wr': sell_wr,
            'sell_profit': sell_profit
        }

    def get_7d_stats(self) -> Dict:
        """Get last 7 days statistics for comparison"""
        since = datetime.utcnow() - timedelta(days=7)

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= since,
            Trade.status == 'closed'
        ).all()

        if not trades:
            return {'total_trades': 0, 'win_rate': 0.0, 'total_profit': 0.0}

        wins = sum(1 for t in trades if float(t.profit) > 0)
        win_rate = (wins / len(trades)) * 100
        total_profit = sum(float(t.profit) for t in trades)

        return {
            'total_trades': len(trades),
            'win_rate': win_rate,
            'total_profit': total_profit
        }

    def get_system_status(self) -> Dict:
        """Get system health status"""
        # Check recent signals (last hour)
        since_1h = datetime.utcnow() - timedelta(hours=1)
        signals = self.db.query(TradingSignal).filter(
            TradingSignal.account_id == self.account_id,
            TradingSignal.created_at >= since_1h
        ).count()

        # Check command success rate (last 50)
        commands = self.db.query(Command).filter(
            Command.account_id == self.account_id
        ).order_by(Command.created_at.desc()).limit(50).all()

        if commands:
            successful = sum(1 for c in commands if c.status == 'executed')
            success_rate = (successful / len(commands)) * 100
        else:
            success_rate = 0.0

        return {
            'signals_1h': signals,
            'command_success_rate': success_rate,
            'commands_checked': len(commands)
        }

    def get_top_symbols(self) -> list:
        """Get top 3 performing symbols (last 7 days)"""
        since = datetime.utcnow() - timedelta(days=7)

        results = self.db.query(
            Trade.symbol,
            func.count(Trade.id).label('count'),
            func.sum(Trade.profit).label('profit')
        ).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= since,
            Trade.status == 'closed'
        ).group_by(Trade.symbol).order_by(
            func.sum(Trade.profit).desc()
        ).limit(3).all()

        return [
            {'symbol': r.symbol, 'count': r.count, 'profit': float(r.profit)}
            for r in results
        ]

    def generate_report(self) -> str:
        """Generate formatted Telegram report"""

        stats_24h = self.get_24h_stats()
        stats_7d = self.get_7d_stats()
        system = self.get_system_status()
        top_symbols = self.get_top_symbols()

        # Build message with HTML formatting
        lines = []
        lines.append("🤖 <b>ngTradingBot Daily Report</b>")
        lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        lines.append("")

        # 24h Performance
        lines.append("📊 <b>Performance (Letzte 24h)</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        if stats_24h['total_trades'] > 0:
            profit_emoji = "🟢" if stats_24h['total_profit'] > 0 else "🔴" if stats_24h['total_profit'] < 0 else "⚪"
            lines.append(f"Trades: <b>{stats_24h['total_trades']}</b> ({stats_24h['wins']}W / {stats_24h['losses']}L)")
            lines.append(f"Win Rate: <b>{stats_24h['win_rate']:.1f}%</b>")
            lines.append(f"Profit: {profit_emoji} <b>€{stats_24h['total_profit']:.2f}</b>")
            lines.append("")

            # BUY vs SELL
            lines.append("🎯 <b>BUY vs SELL</b>")
            lines.append(f"BUY:  {stats_24h['buy_trades']} trades | {stats_24h['buy_wr']:.1f}% WR | €{stats_24h['buy_profit']:.2f}")
            lines.append(f"SELL: {stats_24h['sell_trades']} trades | {stats_24h['sell_wr']:.1f}% WR | €{stats_24h['sell_profit']:.2f}")

            # Gap warning
            gap = stats_24h['sell_wr'] - stats_24h['buy_wr']
            if abs(gap) > 15:
                lines.append("")
                if gap > 0:
                    lines.append(f"⚠️ SELL outperforms BUY by {gap:.1f}%")
                else:
                    lines.append(f"✅ BUY outperforms SELL by {abs(gap):.1f}%")
        else:
            lines.append("Keine Trades in den letzten 24h")

        lines.append("")

        # 7 Days Summary
        lines.append("📈 <b>7-Tage Übersicht</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        if stats_7d['total_trades'] > 0:
            profit_7d_emoji = "🟢" if stats_7d['total_profit'] > 0 else "🔴"
            lines.append(f"Trades: {stats_7d['total_trades']}")
            lines.append(f"Win Rate: {stats_7d['win_rate']:.1f}%")
            lines.append(f"Profit: {profit_7d_emoji} €{stats_7d['total_profit']:.2f}")
        else:
            lines.append("Keine Trades in den letzten 7 Tagen")

        lines.append("")

        # Top Symbols
        if top_symbols:
            lines.append("🏆 <b>Top Symbole (7d)</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for i, sym in enumerate(top_symbols, 1):
                emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                lines.append(f"{emoji} {sym['symbol']}: €{sym['profit']:.2f} ({sym['count']} trades)")
            lines.append("")

        # System Status
        lines.append("⚙️ <b>System Status</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"Signale (1h): {system['signals_1h']}")
        lines.append(f"Command Success: {system['command_success_rate']:.1f}%")

        # Health indicators
        health_items = []

        if system['command_success_rate'] > 90:
            health_items.append("✅ Commands OK")
        elif system['command_success_rate'] > 70:
            health_items.append("⚠️ Commands teilweise fehlerhaft")
        else:
            health_items.append("🔴 Commands oft fehlerhaft")

        if system['signals_1h'] > 0:
            health_items.append("✅ Signals aktiv")
        else:
            health_items.append("⚠️ Keine neuen Signale")

        lines.append("")
        lines.append("\n".join(health_items))

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📱 Automatischer Tagesbericht")

        return "\n".join(lines)

    def send_daily_report(self):
        """Generate and send the daily report"""
        try:
            logger.info("Generating daily Telegram report...")

            report = self.generate_report()

            logger.info("Sending report to Telegram...")
            success = self.notifier.send_message(report, parse_mode='HTML')

            if success:
                logger.info("✅ Daily report sent successfully to Telegram!")
                return True
            else:
                logger.error("❌ Failed to send report to Telegram")
                return False

        except Exception as e:
            logger.error(f"Error generating/sending daily report: {e}", exc_info=True)
            # Send error notification
            self.notifier.send_message(
                f"🔴 <b>Fehler beim Daily Report</b>\n\n{str(e)}",
                parse_mode='HTML'
            )
            return False
        finally:
            self.db.close()


def main():
    """Main entry point"""
    logger.info("Starting Telegram Daily Report...")

    reporter = TelegramDailyReporter(account_id=1)

    if not reporter.notifier.enabled:
        logger.error("Telegram is not configured! Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        sys.exit(1)

    success = reporter.send_daily_report()

    if success:
        logger.info("Daily report completed successfully")
        sys.exit(0)
    else:
        logger.error("Daily report failed")
        sys.exit(1)


if __name__ == '__main__':
    main()
