#!/usr/bin/env python3
"""
Telegram Dashboard Reporter
Sends lightweight and full dashboard reports via Telegram
"""

import sys
import os
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.dashboard_core import DashboardCore
from monitoring.dashboard_config import get_config
from telegram_notifier import get_telegram_notifier

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class TelegramDashboardReporter:
    """Generate and send dashboard reports via Telegram"""

    def __init__(self, account_id: Optional[int] = None):
        self.config = get_config()
        self.account_id = account_id or self.config.DEFAULT_ACCOUNT_ID
        self.dashboard = DashboardCore(account_id=self.account_id)
        self.telegram = get_telegram_notifier()

    def format_pnl_emoji(self, pnl: float) -> str:
        """Get emoji for P&L"""
        if pnl > 0:
            return "🟢"
        elif pnl < 0:
            return "🔴"
        else:
            return "⚪"

    def format_status_emoji(self, status: str) -> str:
        """Get emoji for status"""
        status_lower = status.lower()
        if status_lower == 'active':
            return "🟢"
        elif status_lower == 'shadow_trade':
            return "🔬"
        elif status_lower == 'paused':
            return "⏸️"
        else:
            return "❓"

    def generate_lightweight_report(self) -> str:
        """Generate lightweight report (Sections 1, 3, 7, 8)

        Returns:
            Formatted Telegram message
        """
        # Fetch data
        trading = self.dashboard.get_realtime_trading_overview()
        risk = self.dashboard.get_risk_management_status()
        health = self.dashboard.get_system_health()
        perf = self.dashboard.get_performance_analytics(hours=24)

        lines = []
        lines.append("🤖 <b>ngTradingBot Quick Report</b>")
        lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        lines.append("")

        # Section 1: Trading Overview (Compact)
        lines.append("📊 <b>Trading Status</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        total = trading.get('total', {})
        lines.append(f"Open Positions: <b>{total.get('open_positions', 0)}</b>")
        today_pnl = total.get('today_pnl', 0)
        pnl_emoji = self.format_pnl_emoji(today_pnl)
        lines.append(f"Today P&L: {pnl_emoji} <b>€{today_pnl:+.2f}</b>")
        lines.append(f"Win Rate: <b>{total.get('win_rate', 0):.1f}%</b>")
        lines.append(f"Signals: {total.get('total_signals', 0)}")
        lines.append("")

        # Top 3 symbols by P&L
        symbols = trading.get('symbols', [])
        symbols_sorted = sorted(symbols, key=lambda x: x['today_pnl'], reverse=True)[:3]
        if symbols_sorted:
            lines.append("🏆 <b>Top Performers:</b>")
            for i, sym in enumerate(symbols_sorted, 1):
                emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉"
                status_emoji = self.format_status_emoji(sym['status'])
                lines.append(f"{emoji} {sym['symbol']} {status_emoji}: €{sym['today_pnl']:+.2f}")
            lines.append("")

        # Section 3: Risk Management (Critical info only)
        dd = risk.get('daily_drawdown', {})
        dd_status = dd.get('status', 'UNKNOWN')

        if dd_status != 'SAFE':
            lines.append("⚠️ <b>Risk Alert</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            dd_current = dd.get('current', 0)
            if dd_status == 'EMERGENCY':
                lines.append(f"🚨 EMERGENCY: €{dd_current:+.2f}")
            elif dd_status == 'CRITICAL':
                lines.append(f"🔴 CRITICAL: €{dd_current:+.2f}")
            elif dd_status == 'WARNING':
                lines.append(f"⚠️ WARNING: €{dd_current:+.2f}")
            lines.append("")

        # Section 7: System Health (only if issues)
        mt5 = health.get('mt5_connection', {})
        if not mt5.get('connected'):
            lines.append("🔴 <b>MT5 DISCONNECTED</b>")
            hb = mt5.get('last_heartbeat_seconds_ago')
            if hb:
                lines.append(f"Last heartbeat: {hb:.0f}s ago")
            lines.append("")

        # Section 8: Performance (Compact)
        summary = perf.get('summary', {})
        lines.append("📈 <b>24h Performance</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        total_trades = summary.get('total_trades', 0)
        wins = summary.get('winning_trades', 0)
        losses = summary.get('losing_trades', 0)
        wr = summary.get('win_rate', 0)
        total_pnl_24h = summary.get('total_pnl', 0)
        pf = summary.get('profit_factor', 0)

        lines.append(f"Trades: <b>{total_trades}</b> ({wins}W / {losses}L)")

        wr_indicator = "✅" if wr >= 60 else "⚠️" if wr >= 50 else "❌"
        lines.append(f"Win Rate: {wr_indicator} <b>{wr:.1f}%</b>")

        pnl_24h_emoji = self.format_pnl_emoji(total_pnl_24h)
        lines.append(f"P&L: {pnl_24h_emoji} <b>€{total_pnl_24h:+.2f}</b>")

        pf_indicator = "✅" if pf >= 1.5 else "⚠️" if pf >= 1.0 else "❌"
        lines.append(f"Profit Factor: {pf_indicator} <b>{pf:.2f}</b>")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("📱 Automated 4h Report")

        return "\n".join(lines)

    def generate_full_report(self) -> str:
        """Generate full report (All 9 sections)

        Returns:
            Formatted Telegram message (may be multiple messages if too long)
        """
        # Fetch all data
        trading = self.dashboard.get_realtime_trading_overview()
        ml = self.dashboard.get_ml_performance_metrics()
        risk = self.dashboard.get_risk_management_status()
        positions = self.dashboard.get_live_positions()
        signals = self.dashboard.get_signal_quality_metrics()
        shadow = self.dashboard.get_shadow_trading_analytics()
        health = self.dashboard.get_system_health()
        perf_24h = self.dashboard.get_performance_analytics(hours=24)
        perf_7d = self.dashboard.get_performance_analytics(hours=168)

        lines = []
        lines.append("🤖 <b>ngTradingBot Full Dashboard Report</b>")
        lines.append(f"📅 {datetime.now().strftime('%d.%m.%Y %H:%M')}")
        lines.append("")

        # Section 1: Trading Overview
        lines.append("📊 <b>TRADING OVERVIEW</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        symbols = trading.get('symbols', [])
        for sym in symbols:
            status_emoji = self.format_status_emoji(sym['status'])
            wr_str = f"{sym['win_rate']:.1f}%" if sym['win_rate'] is not None else "N/A"
            lines.append(f"{status_emoji} <b>{sym['symbol']}</b>: €{sym['today_pnl']:+.2f} | {wr_str} WR | {sym['signals_today']} sig")

        total = trading.get('total', {})
        lines.append(f"\n<b>TOTAL:</b> {total.get('open_positions', 0)} open | €{total.get('today_pnl', 0):+.2f} | {total.get('win_rate', 0):.1f}% WR")
        lines.append("")

        # Section 2: ML Performance
        ml_symbols = ml.get('symbols', [])
        if any(m['avg_confidence'] for m in ml_symbols):
            lines.append("🤖 <b>ML PERFORMANCE</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for m in ml_symbols:
                if m['avg_confidence']:
                    conf_str = f"{m['avg_confidence']:.1f}%"
                    acc_str = f"{m['prediction_accuracy']:.1f}%" if m['prediction_accuracy'] else "N/A"
                    lines.append(f"{m['symbol']}: Conf {conf_str} | Acc {acc_str} | {m['trades_24h']} trades")

            overall = ml.get('overall', {})
            if overall.get('avg_confidence'):
                lines.append(f"\n<b>AVG:</b> {overall['avg_confidence']:.1f}% conf | {overall.get('avg_accuracy', 0):.1f}% acc")
            lines.append("")

        # Section 3: Risk Management
        lines.append("🛡️ <b>RISK MANAGEMENT</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        dd = risk.get('daily_drawdown', {})
        dd_status = dd.get('status', 'UNKNOWN')
        dd_emoji = "🟢" if dd_status == 'SAFE' else "⚠️" if dd_status == 'WARNING' else "🔴"
        lines.append(f"{dd_emoji} Drawdown: €{dd.get('current', 0):+.2f} ({dd_status})")

        pos = risk.get('position_limits', {})
        lines.append(f"Positions: {pos.get('current_open', 0)}/{pos.get('max_total', 0)} ({pos.get('usage_pct', 0):.0f}% used)")

        sl = risk.get('sl_enforcement', {})
        sl_emoji = "✅" if sl.get('all_trades_have_sl') else "❌"
        sl_status = 'OK' if sl.get('all_trades_have_sl') else f"FAILED ({sl.get('trades_without_sl', 0)} trades)"
        lines.append(f"{sl_emoji} SL Enforcement: {sl_status}")
        lines.append("")

        # Section 4: Live Positions
        pos_list = positions.get('positions', [])
        if pos_list:
            lines.append("📈 <b>OPEN POSITIONS</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            for p in pos_list[:5]:  # Max 5 to avoid message length
                dir_emoji = "🔵" if p['direction'] == 'BUY' else "🟠"
                pnl = p.get('unrealized_pnl')
                pnl_str = f"€{pnl:+.2f}" if pnl else "N/A"
                lines.append(f"{dir_emoji} {p['symbol']} {p['direction']} | Entry: {p['entry_price']:.5f} | {pnl_str}")

            if len(pos_list) > 5:
                lines.append(f"... and {len(pos_list) - 5} more")

            total_pnl = positions.get('total_unrealized_pnl', 0)
            lines.append(f"\n<b>Unrealized P&L:</b> €{total_pnl:+.2f}")
            lines.append("")

        # Section 5: Signal Quality
        last_hour = signals.get('last_hour', {})
        lines.append("🎯 <b>SIGNAL QUALITY (1H)</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"Generated: {last_hour.get('generated', 0)}")
        lines.append(f"Executed: {last_hour.get('executed', 0)} ({last_hour.get('execution_rate_pct', 0):.1f}%)")
        lines.append(f"Rejected: {last_hour.get('rejected', 0)}")

        latency = signals.get('latency', {})
        avg_lat = latency.get('average_ms')
        if avg_lat:
            lat_emoji = "✅" if latency.get('within_target') else "⚠️"
            lines.append(f"{lat_emoji} Latency: {avg_lat:.0f}ms (target: {latency.get('target_ms', 0)}ms)")
        lines.append("")

        # Section 6: Shadow Trading
        if self.config.ENABLE_SHADOW_TRADING_SECTION:
            progress = shadow.get('progress', {})
            lines.append("🔬 <b>SHADOW TRADING (XAGUSD)</b>")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"Trades: {progress.get('total_trades', 0)}/{progress.get('target_trades', 0)} ({progress.get('trade_progress_pct', 0):.0f}%)")
            lines.append(f"Win Rate: {progress.get('win_rate', 0):.1f}% (target: {progress.get('target_win_rate', 0):.0f}%)")
            lines.append(f"Simulated P&L: €{progress.get('simulated_pnl', 0):+.2f}")

            if shadow.get('ready_to_activate'):
                lines.append("\n✅ <b>READY TO ACTIVATE!</b>")
            else:
                eta = shadow.get('eta', {})
                eta_days = eta.get('days_remaining')
                if eta_days:
                    lines.append(f"\nETA: ~{eta_days:.0f} days")
            lines.append("")

        # Section 7: System Health
        lines.append("💻 <b>SYSTEM HEALTH</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        mt5 = health.get('mt5_connection', {})
        mt5_emoji = "🟢" if mt5.get('connected') else "🔴"
        hb = mt5.get('last_heartbeat_seconds_ago')
        hb_str = f"{hb:.0f}s ago" if hb else "N/A"
        lines.append(f"{mt5_emoji} MT5: {'Connected' if mt5.get('connected') else 'DISCONNECTED'} ({hb_str})")

        pg = health.get('postgresql', {})
        lines.append(f"🟢 PostgreSQL: {pg.get('active_connections', 0)} conn, {pg.get('database_size_mb', 0):.0f} MB")

        redis = health.get('redis', {})
        redis_emoji = "🟢" if redis.get('connected') else "🔴"
        lines.append(f"{redis_emoji} Redis: {'OK' if redis.get('connected') else 'DOWN'}")
        lines.append("")

        # Section 8: Performance Analytics
        lines.append("📈 <b>PERFORMANCE (24H / 7D)</b>")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        sum_24h = perf_24h.get('summary', {})
        sum_7d = perf_7d.get('summary', {})

        lines.append(f"<b>24h:</b> {sum_24h.get('total_trades', 0)} trades | {sum_24h.get('win_rate', 0):.1f}% WR | €{sum_24h.get('total_pnl', 0):+.2f} | PF {sum_24h.get('profit_factor', 0):.2f}")
        lines.append(f"<b>7d:</b> {sum_7d.get('total_trades', 0)} trades | {sum_7d.get('win_rate', 0):.1f}% WR | €{sum_7d.get('total_pnl', 0):+.2f} | PF {sum_7d.get('profit_factor', 0):.2f}")

        best_24h = perf_24h.get('best_trade')
        worst_24h = perf_24h.get('worst_trade')

        if best_24h:
            lines.append(f"\nBest: {best_24h['symbol']} {best_24h['direction']} €{best_24h['profit']:+.2f}")
        if worst_24h:
            lines.append(f"Worst: {worst_24h['symbol']} {worst_24h['direction']} €{worst_24h['profit']:+.2f}")

        lines.append("")
        lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lines.append("📱 Automated Daily Report")

        return "\n".join(lines)

    def send_lightweight_report(self) -> bool:
        """Generate and send lightweight report"""
        try:
            logger.info("Generating lightweight Telegram report...")
            report = self.generate_lightweight_report()

            logger.info("Sending report to Telegram...")
            success = self.telegram.send_message(report, parse_mode='HTML', silent=True)

            if success:
                logger.info("✅ Lightweight report sent successfully")
            else:
                logger.error("❌ Failed to send lightweight report")

            return success

        except Exception as e:
            logger.error(f"Error sending lightweight report: {e}", exc_info=True)
            return False

    def send_full_report(self) -> bool:
        """Generate and send full report"""
        try:
            logger.info("Generating full Telegram report...")
            report = self.generate_full_report()

            logger.info("Sending report to Telegram...")

            # Check if message is too long (Telegram limit: 4096 chars)
            if len(report) > 4000:
                # Split into multiple messages
                chunks = []
                current_chunk = []
                current_length = 0

                for line in report.split('\n'):
                    line_length = len(line) + 1  # +1 for newline

                    if current_length + line_length > 4000:
                        chunks.append('\n'.join(current_chunk))
                        current_chunk = [line]
                        current_length = line_length
                    else:
                        current_chunk.append(line)
                        current_length += line_length

                if current_chunk:
                    chunks.append('\n'.join(current_chunk))

                logger.info(f"Message too long, splitting into {len(chunks)} parts...")

                for i, chunk in enumerate(chunks, 1):
                    success = self.telegram.send_message(chunk, parse_mode='HTML', silent=True)
                    if not success:
                        logger.error(f"❌ Failed to send part {i}/{len(chunks)}")
                        return False

                logger.info(f"✅ Full report sent successfully ({len(chunks)} parts)")
            else:
                success = self.telegram.send_message(report, parse_mode='HTML', silent=True)
                if success:
                    logger.info("✅ Full report sent successfully")
                else:
                    logger.error("❌ Failed to send full report")
                    return False

            return True

        except Exception as e:
            logger.error(f"Error sending full report: {e}", exc_info=True)
            return False

    def send_event_alert(self, event_type: str, message: str, level: str = 'WARNING') -> bool:
        """Send event-driven alert

        Args:
            event_type: Type of event (e.g., 'DRAWDOWN_WARNING', 'MAX_POSITIONS')
            message: Alert message
            level: Alert level ('INFO', 'WARNING', 'CRITICAL')

        Returns:
            True if sent successfully
        """
        return self.telegram.send_alert(event_type, message, level=level)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='ngTradingBot Telegram Dashboard Reporter')
    parser.add_argument('--lightweight', action='store_true', help='Send lightweight report')
    parser.add_argument('--full', action='store_true', help='Send full report')
    parser.add_argument('--test', action='store_true', help='Test connection')
    parser.add_argument('--account-id', type=int, help='Account ID (defaults to config)')

    args = parser.parse_args()

    reporter = TelegramDashboardReporter(account_id=args.account_id)

    if not reporter.telegram.enabled:
        logger.error("Telegram is not configured! Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        sys.exit(1)

    if args.test:
        logger.info("Testing Telegram connection...")
        if reporter.telegram.test_connection():
            logger.info("✅ Test message sent successfully!")
            sys.exit(0)
        else:
            logger.error("❌ Failed to send test message")
            sys.exit(1)

    if args.lightweight:
        success = reporter.send_lightweight_report()
        sys.exit(0 if success else 1)

    if args.full:
        success = reporter.send_full_report()
        sys.exit(0 if success else 1)

    # Default: send lightweight
    success = reporter.send_lightweight_report()
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
