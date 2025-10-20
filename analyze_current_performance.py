#!/usr/bin/env python3
"""
Current Performance Analyzer

Analyzes current trading performance with focus on:
- Overall system performance
- BUY vs SELL comparison
- Symbol-by-symbol breakdown
- Timeframe analysis
- Recent trends
- Recommendations

Usage:
    python analyze_current_performance.py
    python analyze_current_performance.py --days 30
    python analyze_current_performance.py --export
"""

import sys
import argparse
from datetime import datetime, timedelta
from typing import Dict, List
from decimal import Decimal
from collections import defaultdict
import json

from database import ScopedSession
from models import Trade, TradingSignal, SymbolTradingConfig
from sqlalchemy import func, and_

import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """Analyzes current trading performance"""

    def __init__(self, account_id: int = 1, days: int = 30):
        self.account_id = account_id
        self.days = days
        self.since = datetime.utcnow() - timedelta(days=days)
        self.db = ScopedSession()

    def get_overall_stats(self) -> Dict:
        """Get overall system performance"""

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= self.since,
            Trade.status == 'closed'
        ).all()

        if not trades:
            return None

        wins = [t for t in trades if float(t.profit) > 0]
        losses = [t for t in trades if float(t.profit) < 0]

        total_profit = sum(float(t.profit) for t in trades)
        gross_profit = sum(float(t.profit) for t in wins)
        gross_loss = abs(sum(float(t.profit) for t in losses))

        # Calculate profit factor
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

        # Calculate win rate
        win_rate = (len(wins) / len(trades)) * 100 if trades else 0.0

        # Average profit/loss
        avg_win = gross_profit / len(wins) if wins else 0.0
        avg_loss = gross_loss / len(losses) if losses else 0.0

        # Risk/Reward
        risk_reward = avg_win / avg_loss if avg_loss > 0 else 0.0

        # Max consecutive wins/losses
        max_consec_wins = 0
        max_consec_losses = 0
        current_streak = 0
        last_result = None

        for trade in sorted(trades, key=lambda t: t.close_time):
            is_win = float(trade.profit) > 0

            if last_result is None or last_result == is_win:
                current_streak += 1
            else:
                if last_result:
                    max_consec_wins = max(max_consec_wins, current_streak)
                else:
                    max_consec_losses = max(max_consec_losses, current_streak)
                current_streak = 1

            last_result = is_win

        # Final streak
        if last_result:
            max_consec_wins = max(max_consec_wins, current_streak)
        else:
            max_consec_losses = max(max_consec_losses, current_streak)

        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': win_rate,
            'total_profit': total_profit,
            'gross_profit': gross_profit,
            'gross_loss': gross_loss,
            'profit_factor': profit_factor,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'risk_reward': risk_reward,
            'max_consec_wins': max_consec_wins,
            'max_consec_losses': max_consec_losses
        }

    def get_buy_vs_sell_stats(self) -> Dict:
        """Compare BUY vs SELL performance"""

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= self.since,
            Trade.status == 'closed'
        ).all()

        buy_trades = [t for t in trades if t.direction.upper() == 'BUY']
        sell_trades = [t for t in trades if t.direction.upper() == 'SELL']

        def calc_stats(trade_list, label):
            if not trade_list:
                return None

            wins = [t for t in trade_list if float(t.profit) > 0]
            losses = [t for t in trade_list if float(t.profit) < 0]

            total_profit = sum(float(t.profit) for t in trade_list)
            gross_profit = sum(float(t.profit) for t in wins)
            gross_loss = abs(sum(float(t.profit) for t in losses))

            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)
            win_rate = (len(wins) / len(trade_list)) * 100 if trade_list else 0.0

            avg_win = gross_profit / len(wins) if wins else 0.0
            avg_loss = gross_loss / len(losses) if losses else 0.0

            return {
                'label': label,
                'count': len(trade_list),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': win_rate,
                'total_profit': total_profit,
                'gross_profit': gross_profit,
                'gross_loss': gross_loss,
                'profit_factor': profit_factor,
                'avg_win': avg_win,
                'avg_loss': avg_loss
            }

        buy_stats = calc_stats(buy_trades, 'BUY')
        sell_stats = calc_stats(sell_trades, 'SELL')

        return {
            'buy': buy_stats,
            'sell': sell_stats
        }

    def get_symbol_breakdown(self) -> List[Dict]:
        """Get per-symbol performance breakdown"""

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= self.since,
            Trade.status == 'closed'
        ).all()

        # Group by symbol
        by_symbol = defaultdict(list)
        for trade in trades:
            by_symbol[trade.symbol].append(trade)

        results = []
        for symbol, symbol_trades in by_symbol.items():
            wins = [t for t in symbol_trades if float(t.profit) > 0]
            losses = [t for t in symbol_trades if float(t.profit) < 0]

            total_profit = sum(float(t.profit) for t in symbol_trades)
            gross_profit = sum(float(t.profit) for t in wins)
            gross_loss = abs(sum(float(t.profit) for t in losses))

            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)
            win_rate = (len(wins) / len(symbol_trades)) * 100 if symbol_trades else 0.0

            results.append({
                'symbol': symbol,
                'count': len(symbol_trades),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': win_rate,
                'total_profit': total_profit,
                'profit_factor': profit_factor
            })

        # Sort by total profit
        results.sort(key=lambda x: x['total_profit'], reverse=True)

        return results

    def get_timeframe_breakdown(self) -> List[Dict]:
        """Get per-timeframe performance breakdown"""

        trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= self.since,
            Trade.status == 'closed'
        ).all()

        # Group by timeframe
        by_timeframe = defaultdict(list)
        for trade in trades:
            if trade.timeframe:
                by_timeframe[trade.timeframe].append(trade)

        results = []
        for timeframe, tf_trades in by_timeframe.items():
            wins = [t for t in tf_trades if float(t.profit) > 0]
            losses = [t for t in tf_trades if float(t.profit) < 0]

            total_profit = sum(float(t.profit) for t in tf_trades)
            gross_profit = sum(float(t.profit) for t in wins)
            gross_loss = abs(sum(float(t.profit) for t in losses))

            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)
            win_rate = (len(wins) / len(tf_trades)) * 100 if tf_trades else 0.0

            results.append({
                'timeframe': timeframe,
                'count': len(tf_trades),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': win_rate,
                'total_profit': total_profit,
                'profit_factor': profit_factor
            })

        # Sort by count
        results.sort(key=lambda x: x['count'], reverse=True)

        return results

    def get_recent_trend(self) -> Dict:
        """Analyze recent trend (last 7 days vs previous period)"""

        # Last 7 days
        last_7_start = datetime.utcnow() - timedelta(days=7)
        recent_trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= last_7_start,
            Trade.status == 'closed'
        ).all()

        # Previous 7 days
        prev_7_start = datetime.utcnow() - timedelta(days=14)
        prev_7_end = last_7_start
        previous_trades = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.close_time >= prev_7_start,
            Trade.close_time < prev_7_end,
            Trade.status == 'closed'
        ).all()

        def calc_metrics(trades):
            if not trades:
                return {'count': 0, 'win_rate': 0.0, 'profit': 0.0}

            wins = sum(1 for t in trades if float(t.profit) > 0)
            win_rate = (wins / len(trades)) * 100
            profit = sum(float(t.profit) for t in trades)

            return {'count': len(trades), 'win_rate': win_rate, 'profit': profit}

        recent = calc_metrics(recent_trades)
        previous = calc_metrics(previous_trades)

        # Calculate trends
        count_change = recent['count'] - previous['count']
        wr_change = recent['win_rate'] - previous['win_rate']
        profit_change = recent['profit'] - previous['profit']

        return {
            'recent': recent,
            'previous': previous,
            'count_change': count_change,
            'wr_change': wr_change,
            'profit_change': profit_change,
            'improving': wr_change > 0 and profit_change > 0
        }

    def generate_recommendations(self, stats: Dict) -> List[str]:
        """Generate actionable recommendations"""

        recommendations = []

        overall = stats['overall']
        buy_sell = stats['buy_vs_sell']
        symbols = stats['symbol_breakdown']
        trend = stats['recent_trend']

        # Overall performance
        if overall['win_rate'] < 45.0:
            recommendations.append("⚠️  Win rate is low (<45%). Review signal quality and entry criteria.")
        elif overall['win_rate'] > 60.0:
            recommendations.append("✅ Excellent win rate (>60%). System performing well!")

        if overall['profit_factor'] < 1.0:
            recommendations.append("🔴 CRITICAL: Profit factor < 1.0 (losing money). Immediate review needed!")
        elif overall['profit_factor'] < 1.5:
            recommendations.append("⚠️  Profit factor is low (<1.5). Optimize risk/reward or win rate.")
        elif overall['profit_factor'] > 2.0:
            recommendations.append("✅ Strong profit factor (>2.0). Good risk management!")

        # BUY vs SELL
        if buy_sell['buy'] and buy_sell['sell']:
            buy_wr = buy_sell['buy']['win_rate']
            sell_wr = buy_sell['sell']['win_rate']
            gap = sell_wr - buy_wr

            if gap > 10.0:
                recommendations.append(f"⚠️  SELL outperforming BUY by {gap:.1f}%. Current BUY bias appears justified.")
            elif gap < -10.0:
                recommendations.append(f"✅ BUY outperforming SELL by {abs(gap):.1f}%. Consider reducing BUY bias!")
                recommendations.append("   → Run backtests with lower BUY_SIGNAL_ADVANTAGE (1 or 0)")
                recommendations.append("   → Reduce BUY_CONFIDENCE_PENALTY to 0-1.5%")

        # Symbol performance
        if symbols:
            losing_symbols = [s for s in symbols if s['total_profit'] < -10.0]
            winning_symbols = [s for s in symbols if s['total_profit'] > 10.0]

            if losing_symbols:
                top_losers = losing_symbols[:3]
                recommendations.append(f"⚠️  {len(losing_symbols)} symbols losing money:")
                for sym in top_losers:
                    recommendations.append(f"   → {sym['symbol']}: €{sym['total_profit']:.2f} loss - consider pausing")

            if winning_symbols:
                top_winners = winning_symbols[:3]
                recommendations.append(f"✅ {len(winning_symbols)} profitable symbols:")
                for sym in top_winners:
                    recommendations.append(f"   → {sym['symbol']}: €{sym['total_profit']:.2f} profit")

        # Recent trend
        if trend['improving']:
            recommendations.append("📈 Recent trend is IMPROVING - keep current settings")
        elif trend['wr_change'] < -5.0:
            recommendations.append("📉 Recent win rate declining - review market conditions")

        return recommendations

    def print_report(self):
        """Print comprehensive performance report"""

        print("\n" + "=" * 100)
        print(f"PERFORMANCE ANALYSIS REPORT - Last {self.days} Days")
        print(f"Period: {self.since.strftime('%Y-%m-%d')} → {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 100)

        # 1. Overall Performance
        overall = self.get_overall_stats()

        if not overall:
            print("\n❌ No closed trades found in the analysis period!")
            return

        print("\n📊 OVERALL PERFORMANCE")
        print("-" * 100)
        print(f"Total Trades:          {overall['total_trades']}")
        print(f"Wins:                  {overall['wins']} ({overall['win_rate']:.1f}%)")
        print(f"Losses:                {overall['losses']} ({100-overall['win_rate']:.1f}%)")
        print(f"Total Profit:          €{overall['total_profit']:.2f}")
        print(f"Gross Profit:          €{overall['gross_profit']:.2f}")
        print(f"Gross Loss:            €{overall['gross_loss']:.2f}")
        print(f"Profit Factor:         {overall['profit_factor']:.2f}")
        print(f"Average Win:           €{overall['avg_win']:.2f}")
        print(f"Average Loss:          €{overall['avg_loss']:.2f}")
        print(f"Risk/Reward:           1:{overall['risk_reward']:.2f}")
        print(f"Max Consecutive Wins:  {overall['max_consec_wins']}")
        print(f"Max Consecutive Losses:{overall['max_consec_losses']}")

        # 2. BUY vs SELL
        buy_sell = self.get_buy_vs_sell_stats()

        print("\n🎯 BUY vs SELL COMPARISON")
        print("-" * 100)
        print(f"{'Metric':<25} {'BUY':>15} {'SELL':>15} {'Gap':>15}")
        print("-" * 100)

        if buy_sell['buy'] and buy_sell['sell']:
            b = buy_sell['buy']
            s = buy_sell['sell']

            print(f"{'Trades':<25} {b['count']:>15} {s['count']:>15} {b['count']-s['count']:>15}")
            print(f"{'Win Rate':<25} {b['win_rate']:>14.1f}% {s['win_rate']:>14.1f}% {b['win_rate']-s['win_rate']:>14.1f}%")
            print(f"{'Total Profit':<25} €{b['total_profit']:>13.2f} €{s['total_profit']:>13.2f} €{b['total_profit']-s['total_profit']:>13.2f}")
            print(f"{'Profit Factor':<25} {b['profit_factor']:>14.2f} {s['profit_factor']:>14.2f} {b['profit_factor']-s['profit_factor']:>14.2f}")
            print(f"{'Avg Win':<25} €{b['avg_win']:>13.2f} €{s['avg_win']:>13.2f} €{b['avg_win']-s['avg_win']:>13.2f}")
            print(f"{'Avg Loss':<25} €{b['avg_loss']:>13.2f} €{s['avg_loss']:>13.2f} €{b['avg_loss']-s['avg_loss']:>13.2f}")

        # 3. Symbol Breakdown
        symbols = self.get_symbol_breakdown()

        if symbols:
            print("\n💹 SYMBOL BREAKDOWN")
            print("-" * 100)
            print(f"{'Symbol':<12} {'Trades':>8} {'Wins':>6} {'Losses':>8} {'WR%':>7} {'Profit':>12} {'PF':>7}")
            print("-" * 100)

            for sym in symbols:
                print(f"{sym['symbol']:<12} {sym['count']:>8} {sym['wins']:>6} {sym['losses']:>8} "
                      f"{sym['win_rate']:>6.1f}% €{sym['total_profit']:>10.2f} {sym['profit_factor']:>6.2f}")

        # 4. Timeframe Breakdown
        timeframes = self.get_timeframe_breakdown()

        if timeframes:
            print("\n⏱️  TIMEFRAME BREAKDOWN")
            print("-" * 100)
            print(f"{'TF':<6} {'Trades':>8} {'Wins':>6} {'Losses':>8} {'WR%':>7} {'Profit':>12} {'PF':>7}")
            print("-" * 100)

            for tf in timeframes:
                print(f"{tf['timeframe']:<6} {tf['count']:>8} {tf['wins']:>6} {tf['losses']:>8} "
                      f"{tf['win_rate']:>6.1f}% €{tf['total_profit']:>10.2f} {tf['profit_factor']:>6.2f}")

        # 5. Recent Trend
        trend = self.get_recent_trend()

        print("\n📈 RECENT TREND (Last 7 Days vs Previous 7 Days)")
        print("-" * 100)
        print(f"{'Metric':<25} {'Last 7 Days':>15} {'Previous 7':>15} {'Change':>15}")
        print("-" * 100)
        print(f"{'Trades':<25} {trend['recent']['count']:>15} {trend['previous']['count']:>15} {trend['count_change']:>+15}")
        print(f"{'Win Rate':<25} {trend['recent']['win_rate']:>14.1f}% {trend['previous']['win_rate']:>14.1f}% {trend['wr_change']:>+14.1f}%")
        print(f"{'Profit':<25} €{trend['recent']['profit']:>13.2f} €{trend['previous']['profit']:>13.2f} €{trend['profit_change']:>+13.2f}")

        if trend['improving']:
            print("\n✅ Trend: IMPROVING")
        else:
            print("\n⚠️  Trend: DECLINING")

        # 6. Recommendations
        stats = {
            'overall': overall,
            'buy_vs_sell': buy_sell,
            'symbol_breakdown': symbols,
            'recent_trend': trend
        }

        recommendations = self.generate_recommendations(stats)

        print("\n💡 RECOMMENDATIONS")
        print("-" * 100)
        for rec in recommendations:
            print(rec)

        print("\n" + "=" * 100)

        return stats


def main():
    parser = argparse.ArgumentParser(description='Analyze current trading performance')
    parser.add_argument('--days', type=int, default=30, help='Analysis period in days (default: 30)')
    parser.add_argument('--account-id', type=int, default=1, help='Account ID (default: 1)')
    parser.add_argument('--export', action='store_true', help='Export to JSON file')

    args = parser.parse_args()

    analyzer = PerformanceAnalyzer(account_id=args.account_id, days=args.days)
    stats = analyzer.print_report()

    if args.export and stats:
        filename = f"/projects/ngTradingBot/performance_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w') as f:
            # Convert Decimal to float for JSON serialization
            json.dump(stats, f, indent=2, default=str)
        logger.info(f"\n📄 Report exported to: {filename}")


if __name__ == '__main__':
    main()
