#!/usr/bin/env python3
"""
Real-Time Audit Monitoring Dashboard

Monitors the new audit parameters in real-time:
- Position sizing (volume calculation)
- Signal staleness
- BUY signal bias impact
- Circuit breaker status
- Command execution success rate

Usage:
    python audit_monitor.py                    # Run continuously
    python audit_monitor.py --once             # Single snapshot
    python audit_monitor.py --watch-signals    # Focus on signal generation
"""

import sys
import os
import time
import argparse
from datetime import datetime, timedelta
from typing import Dict, List
from decimal import Decimal
from sqlalchemy import text, func, and_

from database import ScopedSession
from models import Trade, TradingSignal, Command

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AuditMonitor:
    """Real-time monitoring of audit parameters"""

    def __init__(self, account_id: int = 1):
        self.account_id = account_id
        self.db = ScopedSession()

    def get_position_sizing_stats(self) -> Dict:
        """Monitor position sizing (last 24 hours)"""

        since = datetime.utcnow() - timedelta(hours=24)

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.open_time >= since
        ).all()

        if not trades:
            return {
                'count': 0,
                'avg_volume': 0.0,
                'min_volume': 0.0,
                'max_volume': 0.0,
                'hitting_cap': 0,
                'volumes': []
            }

        volumes = [float(t.volume) for t in trades]

        return {
            'count': len(trades),
            'avg_volume': sum(volumes) / len(volumes),
            'min_volume': min(volumes),
            'max_volume': max(volumes),
            'hitting_cap': sum(1 for v in volumes if v >= 0.99),  # Near 1.0 lot cap
            'volumes': volumes
        }

    def get_signal_staleness_stats(self) -> Dict:
        """Monitor signal staleness (last hour)"""

        since = datetime.utcnow() - timedelta(hours=1)

        # Get signals created in last hour (signals are now global)
        signals = self.db.query(TradingSignal).filter(
            TradingSignal.created_at >= since
        ).all()

        if not signals:
            return {
                'total_signals': 0,
                'avg_age_seconds': 0.0,
                'max_age_seconds': 0.0,
                'stale_signals': 0,
                'aging_signals': 0
            }

        now = datetime.utcnow()
        ages = [(now - s.created_at).total_seconds() for s in signals]

        stale_count = sum(1 for age in ages if age > 300)  # >5 min
        aging_count = sum(1 for age in ages if 120 < age <= 300)  # 2-5 min

        return {
            'total_signals': len(signals),
            'avg_age_seconds': sum(ages) / len(ages),
            'max_age_seconds': max(ages),
            'stale_signals': stale_count,
            'aging_signals': aging_count
        }

    def get_buy_signal_bias_stats(self) -> Dict:
        """Monitor BUY vs SELL signal generation (last 24 hours)"""

        since = datetime.utcnow() - timedelta(hours=24)

        # Get all signals (signals are now global)
        signals = self.db.query(TradingSignal).filter(
            TradingSignal.created_at >= since
        ).all()

        if not signals:
            return {
                'total_signals': 0,
                'buy_signals': 0,
                'sell_signals': 0,
                'buy_pct': 0.0,
                'buy_avg_confidence': 0.0,
                'sell_avg_confidence': 0.0,
                'confidence_gap': 0.0
            }

        buy_signals = [s for s in signals if s.signal_type == 'BUY']
        sell_signals = [s for s in signals if s.signal_type == 'SELL']

        buy_conf = [float(s.confidence) for s in buy_signals] if buy_signals else [0.0]
        sell_conf = [float(s.confidence) for s in sell_signals] if sell_signals else [0.0]

        buy_avg = sum(buy_conf) / len(buy_conf)
        sell_avg = sum(sell_conf) / len(sell_conf)

        return {
            'total_signals': len(signals),
            'buy_signals': len(buy_signals),
            'sell_signals': len(sell_signals),
            'buy_pct': (len(buy_signals) / len(signals)) * 100 if signals else 0.0,
            'buy_avg_confidence': buy_avg,
            'sell_avg_confidence': sell_avg,
            'confidence_gap': sell_avg - buy_avg
        }

    def get_buy_vs_sell_trade_performance(self) -> Dict:
        """Compare BUY vs SELL actual trade performance (last 7 days)"""

        since = datetime.utcnow() - timedelta(days=7)

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= since,
            Trade.status == 'closed'
        ).all()

        if not trades:
            return {
                'total_trades': 0,
                'buy_trades': 0,
                'sell_trades': 0,
                'buy_win_rate': 0.0,
                'sell_win_rate': 0.0,
                'performance_gap': 0.0,
                'buy_profit': 0.0,
                'sell_profit': 0.0
            }

        buy_trades = [t for t in trades if t.direction.upper() == 'BUY']
        sell_trades = [t for t in trades if t.direction.upper() == 'SELL']

        def calc_wr(trade_list):
            if not trade_list:
                return 0.0, 0.0
            wins = sum(1 for t in trade_list if float(t.profit) > 0)
            profit = sum(float(t.profit) for t in trade_list)
            return (wins / len(trade_list)) * 100, profit

        buy_wr, buy_profit = calc_wr(buy_trades)
        sell_wr, sell_profit = calc_wr(sell_trades)

        return {
            'total_trades': len(trades),
            'buy_trades': len(buy_trades),
            'sell_trades': len(sell_trades),
            'buy_win_rate': buy_wr,
            'sell_win_rate': sell_wr,
            'performance_gap': sell_wr - buy_wr,
            'buy_profit': buy_profit,
            'sell_profit': sell_profit
        }

    def get_circuit_breaker_status(self) -> Dict:
        """Check circuit breaker status and command success rate"""

        # Get recent circuit breaker events
        cb_events = self.db.query(AIDecisionLog).filter(
            AIDecisionLog.account_id == self.account_id,
            AIDecisionLog.decision_type == 'CIRCUIT_BREAKER'
        ).order_by(AIDecisionLog.created_at.desc()).limit(5).all()

        # Command success rate (last 100 commands)
        commands = self.db.query(Command).filter(
            Command.account_id == self.account_id
        ).order_by(Command.created_at.desc()).limit(100).all()

        if commands:
            successful = sum(1 for c in commands if c.status == 'executed')
            failed = sum(1 for c in commands if c.status == 'failed')
            pending = sum(1 for c in commands if c.status == 'pending')

            success_rate = (successful / len(commands)) * 100 if commands else 0.0
        else:
            successful = failed = pending = 0
            success_rate = 0.0

        return {
            'recent_trips': len(cb_events),
            'last_trip': cb_events[0].created_at if cb_events else None,
            'total_commands': len(commands),
            'successful_commands': successful,
            'failed_commands': failed,
            'pending_commands': pending,
            'success_rate': success_rate,
            'consecutive_failures': failed  # Simplified - would need sequential check
        }

    def print_dashboard(self):
        """Print comprehensive monitoring dashboard"""

        print("\n" + "=" * 100)
        print(f"AUDIT MONITORING DASHBOARD - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 100)

        # 1. Position Sizing
        print("\n1️⃣  POSITION SIZING (Last 24 Hours)")
        print("-" * 100)
        ps_stats = self.get_position_sizing_stats()

        if ps_stats['count'] > 0:
            print(f"   Total Trades:      {ps_stats['count']}")
            print(f"   Average Volume:    {ps_stats['avg_volume']:.3f} lot")
            print(f"   Min Volume:        {ps_stats['min_volume']:.3f} lot")
            print(f"   Max Volume:        {ps_stats['max_volume']:.3f} lot")
            print(f"   Hitting Cap (1.0): {ps_stats['hitting_cap']} trades")

            if ps_stats['hitting_cap'] > 0:
                print(f"   ⚠️  WARNING: {ps_stats['hitting_cap']} trades hit the 1.0 lot safety cap!")
                print("   → Consider increasing cap or reviewing high-confidence signals")
            else:
                print("   ✅ No trades hitting volume cap")

            if ps_stats['min_volume'] == ps_stats['max_volume'] == 0.01:
                print("   ⚠️  WARNING: All trades are 0.01 lot - position sizer may not be working!")
            elif ps_stats['max_volume'] > ps_stats['avg_volume'] * 2:
                print("   ✅ Position sizing is scaling with signal quality")
        else:
            print("   No trades in last 24 hours")

        # 2. Signal Staleness
        print("\n2️⃣  SIGNAL STALENESS (Last Hour)")
        print("-" * 100)
        ss_stats = self.get_signal_staleness_stats()

        if ss_stats['total_signals'] > 0:
            print(f"   Total Signals:     {ss_stats['total_signals']}")
            print(f"   Average Age:       {ss_stats['avg_age_seconds']:.0f} seconds")
            print(f"   Max Age:           {ss_stats['max_age_seconds']:.0f} seconds")
            print(f"   Aging (2-5 min):   {ss_stats['aging_signals']} signals")
            print(f"   Stale (>5 min):    {ss_stats['stale_signals']} signals")

            if ss_stats['stale_signals'] > 0:
                print(f"   ⚠️  WARNING: {ss_stats['stale_signals']} signals are stale (>5 min)")
                print("   → These should be rejected by auto-trader")
            else:
                print("   ✅ All signals are fresh (<5 min)")

            if ss_stats['aging_signals'] > ss_stats['total_signals'] * 0.3:
                print(f"   ⚠️  NOTICE: {ss_stats['aging_signals']} signals aging (2-5 min)")
                print("   → Signal processing may be slow")
        else:
            print("   No signals in last hour")

        # 3. BUY Signal Bias
        print("\n3️⃣  BUY SIGNAL BIAS (Last 24 Hours)")
        print("-" * 100)
        bias_stats = self.get_buy_signal_bias_stats()

        if bias_stats['total_signals'] > 0:
            print(f"   Total Signals:         {bias_stats['total_signals']}")
            print(f"   BUY Signals:           {bias_stats['buy_signals']} ({bias_stats['buy_pct']:.1f}%)")
            print(f"   SELL Signals:          {bias_stats['sell_signals']} ({100-bias_stats['buy_pct']:.1f}%)")
            print(f"   BUY Avg Confidence:    {bias_stats['buy_avg_confidence']:.1f}%")
            print(f"   SELL Avg Confidence:   {bias_stats['sell_avg_confidence']:.1f}%")
            print(f"   Confidence Gap:        {bias_stats['confidence_gap']:.1f}% (SELL - BUY)")

            if bias_stats['confidence_gap'] > 5.0:
                print(f"   ⚠️  BUY confidence is {bias_stats['confidence_gap']:.1f}% lower than SELL")
                print("   → BUY_CONFIDENCE_PENALTY is working")
            elif bias_stats['confidence_gap'] < -5.0:
                print(f"   ⚠️  SELL confidence is {abs(bias_stats['confidence_gap']):.1f}% lower than BUY")
                print("   → Unexpected! Check signal generation logic")
            else:
                print("   ✅ BUY/SELL confidence gap is balanced (<5%)")

            if bias_stats['buy_pct'] < 30.0:
                print(f"   ⚠️  Only {bias_stats['buy_pct']:.1f}% BUY signals - bias may be too strong")
                print("   → Consider reducing BUY_SIGNAL_ADVANTAGE or BUY_CONFIDENCE_PENALTY")
            elif bias_stats['buy_pct'] > 70.0:
                print(f"   ⚠️  {bias_stats['buy_pct']:.1f}% BUY signals - bias may be too weak")
                print("   → Consider increasing BUY_SIGNAL_ADVANTAGE or BUY_CONFIDENCE_PENALTY")
            else:
                print(f"   ✅ BUY/SELL ratio is balanced ({bias_stats['buy_pct']:.1f}% / {100-bias_stats['buy_pct']:.1f}%)")
        else:
            print("   No signals in last 24 hours")

        # 4. BUY vs SELL Trade Performance
        print("\n4️⃣  BUY vs SELL TRADE PERFORMANCE (Last 7 Days)")
        print("-" * 100)
        perf_stats = self.get_buy_vs_sell_trade_performance()

        if perf_stats['total_trades'] > 0:
            print(f"   Total Trades:      {perf_stats['total_trades']}")
            print(f"   BUY Trades:        {perf_stats['buy_trades']} ({perf_stats['buy_trades']/perf_stats['total_trades']*100:.1f}%)")
            print(f"   SELL Trades:       {perf_stats['sell_trades']} ({perf_stats['sell_trades']/perf_stats['total_trades']*100:.1f}%)")
            print(f"   BUY Win Rate:      {perf_stats['buy_win_rate']:.1f}%")
            print(f"   SELL Win Rate:     {perf_stats['sell_win_rate']:.1f}%")
            print(f"   Performance Gap:   {perf_stats['performance_gap']:.1f}% (SELL - BUY)")
            print(f"   BUY Profit:        €{perf_stats['buy_profit']:.2f}")
            print(f"   SELL Profit:       €{perf_stats['sell_profit']:.2f}")

            if abs(perf_stats['performance_gap']) > 10.0:
                if perf_stats['performance_gap'] > 0:
                    print(f"   ⚠️  SELL outperforming BUY by {perf_stats['performance_gap']:.1f}%")
                    print("   → Current bias settings appear justified")
                else:
                    print(f"   ⚠️  BUY outperforming SELL by {abs(perf_stats['performance_gap']):.1f}%")
                    print("   → Consider reducing BUY bias (run backtests!)")
            else:
                print("   ✅ BUY/SELL performance is balanced (<10% gap)")
        else:
            print("   No closed trades in last 7 days")

        # 5. Circuit Breaker & Command Status
        print("\n5️⃣  CIRCUIT BREAKER & COMMAND STATUS")
        print("-" * 100)
        cb_stats = self.get_circuit_breaker_status()

        print(f"   Circuit Breaker Trips:  {cb_stats['recent_trips']} (recent)")
        if cb_stats['last_trip']:
            time_since = datetime.utcnow() - cb_stats['last_trip']
            print(f"   Last Trip:              {cb_stats['last_trip'].strftime('%Y-%m-%d %H:%M:%S')} ({time_since.seconds//3600}h ago)")
        else:
            print(f"   Last Trip:              Never")

        print(f"\n   Command Stats (Last 100):")
        print(f"   Total:                  {cb_stats['total_commands']}")
        print(f"   Successful:             {cb_stats['successful_commands']}")
        print(f"   Failed:                 {cb_stats['failed_commands']}")
        print(f"   Pending:                {cb_stats['pending_commands']}")
        print(f"   Success Rate:           {cb_stats['success_rate']:.1f}%")

        if cb_stats['success_rate'] < 90.0:
            print(f"   ⚠️  WARNING: Low success rate ({cb_stats['success_rate']:.1f}%)")
            print("   → Check MT5 connection and circuit breaker threshold")
        else:
            print("   ✅ Command execution is healthy")

        if cb_stats['failed_commands'] >= 3:
            print(f"   ⚠️  WARNING: {cb_stats['failed_commands']} recent failures")
            print(f"   → Circuit breaker threshold is 5 - currently at {cb_stats['failed_commands']}/5")

        print("\n" + "=" * 100)
        print("Dashboard refresh: Press Ctrl+C to exit")
        print("=" * 100 + "\n")

    def run_continuous(self, interval: int = 10):
        """Run dashboard continuously"""
        logger.info(f"Starting continuous monitoring (refresh every {interval}s)")

        try:
            while True:
                self.print_dashboard()
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("\nMonitoring stopped by user")


def main():
    parser = argparse.ArgumentParser(description='Real-time audit monitoring dashboard')
    parser.add_argument('--once', action='store_true', help='Single snapshot (no refresh)')
    parser.add_argument('--interval', type=int, default=10, help='Refresh interval in seconds (default: 10)')
    parser.add_argument('--account-id', type=int, default=1, help='Account ID (default: 1)')

    args = parser.parse_args()

    monitor = AuditMonitor(account_id=args.account_id)

    if args.once:
        monitor.print_dashboard()
    else:
        monitor.run_continuous(interval=args.interval)


if __name__ == '__main__':
    main()
