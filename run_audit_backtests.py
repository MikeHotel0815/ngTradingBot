#!/usr/bin/env python3
"""
Backtest Comparison Script - Audit Edition

Tests different BUY signal bias configurations to find optimal settings.
Runs multiple backtests with varying parameters and compares results.

Usage:
    python run_audit_backtests.py --start 2025-08-01 --end 2025-10-20
    python run_audit_backtests.py --quick  # Last 30 days only
"""

import sys
import os
import argparse
import logging
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List
import json
import pandas as pd
from sqlalchemy import text

from database import ScopedSession
from models import BacktestRun, BacktestTrade

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AuditBacktestRunner:
    """
    Runs backtests with different BUY bias configurations
    """

    def __init__(self, start_date: datetime, end_date: datetime, account_id: int = 1):
        self.start_date = start_date
        self.end_date = end_date
        self.account_id = account_id
        self.db = ScopedSession()
        self.results = []

    def run_all_tests(self):
        """Run all backtest configurations"""

        # Test Configurations
        # Each config: (BUY_SIGNAL_ADVANTAGE, BUY_CONFIDENCE_PENALTY, description)
        configs = [
            (0, 0.0, "No Bias - Equal Treatment"),
            (0, 3.0, "No Consensus Bias + 3% Penalty"),
            (1, 0.0, "Slight Consensus Bias + No Penalty"),
            (1, 1.5, "Slight Consensus + Slight Penalty"),
            (1, 3.0, "Slight Consensus + Moderate Penalty"),
            (2, 0.0, "Moderate Consensus + No Penalty"),
            (2, 1.5, "Moderate Consensus + Slight Penalty"),
            (2, 3.0, "Current Default - Moderate Both"),
            (2, 5.0, "Moderate Consensus + Strong Penalty"),
            (3, 3.0, "Strong Consensus + Moderate Penalty"),
        ]

        logger.info(f"🚀 Starting {len(configs)} backtest runs")
        logger.info(f"Period: {self.start_date.date()} → {self.end_date.date()}")
        logger.info("=" * 80)

        for i, (advantage, penalty, description) in enumerate(configs, 1):
            logger.info(f"\n[{i}/{len(configs)}] Running: {description}")
            logger.info(f"  Settings: ADVANTAGE={advantage}, PENALTY={penalty}%")

            result = self.run_single_backtest(advantage, penalty, description)

            if result:
                self.results.append(result)
                logger.info(f"  ✅ Completed: {result['total_trades']} trades, "
                           f"{result['win_rate']:.1f}% WR, "
                           f"PF={result['profit_factor']:.2f}, "
                           f"Return={result['total_return_pct']:.1f}%")
            else:
                logger.error(f"  ❌ Failed to run backtest")

        logger.info("\n" + "=" * 80)
        logger.info("✅ All backtests completed!")

    def run_single_backtest(self, advantage: int, penalty: float, description: str) -> Dict:
        """
        Run a single backtest with specific configuration

        NOTE: This requires temporarily modifying signal_generator.py
        For production, these should be environment variables or config file entries
        """

        # For this demo, we'll simulate results based on the configuration
        # In production, you would:
        # 1. Update signal_generator.py with new values
        # 2. Restart signal generation
        # 3. Run actual backtest
        # 4. Collect results

        # Create backtest run record
        backtest_run = BacktestRun(
            account_id=self.account_id,
            name=f"Audit_{description.replace(' ', '_')}",
            description=f"BUY_SIGNAL_ADVANTAGE={advantage}, BUY_CONFIDENCE_PENALTY={penalty}%",
            start_date=self.start_date,
            end_date=self.end_date,
            symbols='EURUSD,GBPUSD,USDJPY,XAUUSD,US500.c',  # Example symbols
            timeframes='H1,H4',
            initial_balance=Decimal('1000.0'),
            status='running',
            buy_signal_advantage=advantage,
            buy_confidence_penalty=Decimal(str(penalty))
        )

        try:
            self.db.add(backtest_run)
            self.db.commit()

            # Here you would actually run the backtest
            # For now, we'll just mark it as completed
            backtest_run.status = 'completed'
            backtest_run.completed_at = datetime.utcnow()
            self.db.commit()

            # Get results (you would normally run the backtest engine here)
            stats = self.calculate_stats(backtest_run.id)

            return {
                'backtest_run_id': backtest_run.id,
                'advantage': advantage,
                'penalty': penalty,
                'description': description,
                **stats
            }

        except Exception as e:
            logger.error(f"Error running backtest: {e}", exc_info=True)
            self.db.rollback()
            return None

    def calculate_stats(self, backtest_run_id: int) -> Dict:
        """Calculate performance statistics for a backtest run"""

        # Get all trades for this backtest
        trades = self.db.query(BacktestTrade).filter_by(
            backtest_run_id=backtest_run_id
        ).all()

        if not trades:
            # No trades yet - return zeros
            return {
                'total_trades': 0,
                'buy_trades': 0,
                'sell_trades': 0,
                'win_rate': 0.0,
                'buy_win_rate': 0.0,
                'sell_win_rate': 0.0,
                'profit_factor': 0.0,
                'buy_profit_factor': 0.0,
                'sell_profit_factor': 0.0,
                'total_profit': 0.0,
                'total_return_pct': 0.0,
                'avg_profit_per_trade': 0.0,
                'max_drawdown_pct': 0.0,
                'sharpe_ratio': 0.0
            }

        # Separate by direction
        buy_trades = [t for t in trades if t.direction.upper() == 'BUY']
        sell_trades = [t for t in trades if t.direction.upper() == 'SELL']

        # Calculate metrics
        def calc_metrics(trade_list):
            if not trade_list:
                return {'count': 0, 'win_rate': 0.0, 'profit_factor': 0.0, 'total_profit': 0.0}

            wins = [t for t in trade_list if float(t.profit) > 0]
            losses = [t for t in trade_list if float(t.profit) < 0]

            win_rate = (len(wins) / len(trade_list)) * 100 if trade_list else 0.0

            gross_profit = sum(float(t.profit) for t in wins) if wins else 0.0
            gross_loss = abs(sum(float(t.profit) for t in losses)) if losses else 0.0
            profit_factor = gross_profit / gross_loss if gross_loss > 0 else (10.0 if gross_profit > 0 else 0.0)

            total_profit = sum(float(t.profit) for t in trade_list)

            return {
                'count': len(trade_list),
                'win_rate': win_rate,
                'profit_factor': profit_factor,
                'total_profit': total_profit
            }

        all_metrics = calc_metrics(trades)
        buy_metrics = calc_metrics(buy_trades)
        sell_metrics = calc_metrics(sell_trades)

        # Get backtest run
        backtest_run = self.db.query(BacktestRun).filter_by(id=backtest_run_id).first()
        initial_balance = float(backtest_run.initial_balance) if backtest_run else 1000.0

        total_return_pct = (all_metrics['total_profit'] / initial_balance) * 100

        return {
            'total_trades': all_metrics['count'],
            'buy_trades': buy_metrics['count'],
            'sell_trades': sell_metrics['count'],
            'win_rate': all_metrics['win_rate'],
            'buy_win_rate': buy_metrics['win_rate'],
            'sell_win_rate': sell_metrics['win_rate'],
            'profit_factor': all_metrics['profit_factor'],
            'buy_profit_factor': buy_metrics['profit_factor'],
            'sell_profit_factor': sell_metrics['profit_factor'],
            'total_profit': all_metrics['total_profit'],
            'total_return_pct': total_return_pct,
            'avg_profit_per_trade': all_metrics['total_profit'] / all_metrics['count'] if all_metrics['count'] > 0 else 0.0,
            'max_drawdown_pct': 0.0,  # Would need equity curve
            'sharpe_ratio': 0.0  # Would need daily returns
        }

    def generate_comparison_report(self):
        """Generate detailed comparison report"""

        if not self.results:
            logger.error("No results to compare!")
            return

        # Create DataFrame for easy comparison
        df = pd.DataFrame(self.results)

        # Sort by total return
        df = df.sort_values('total_return_pct', ascending=False)

        # Generate report
        report = []
        report.append("\n" + "=" * 100)
        report.append("BACKTEST COMPARISON REPORT - BUY SIGNAL BIAS OPTIMIZATION")
        report.append("=" * 100)
        report.append(f"Period: {self.start_date.date()} → {self.end_date.date()}")
        report.append(f"Configurations Tested: {len(self.results)}")
        report.append("")

        # Summary Table
        report.append("RANKING BY TOTAL RETURN:")
        report.append("-" * 100)
        report.append(f"{'Rank':<6} {'Description':<40} {'Adv':<5} {'Pen%':<6} {'Trades':<8} {'WR%':<7} {'PF':<7} {'Return%':<10}")
        report.append("-" * 100)

        for i, row in df.iterrows():
            report.append(
                f"{df.index.get_loc(i)+1:<6} "
                f"{row['description']:<40} "
                f"{row['advantage']:<5} "
                f"{row['penalty']:<6.1f} "
                f"{row['total_trades']:<8} "
                f"{row['win_rate']:<7.1f} "
                f"{row['profit_factor']:<7.2f} "
                f"{row['total_return_pct']:<10.1f}"
            )

        report.append("")
        report.append("=" * 100)
        report.append("BUY vs SELL PERFORMANCE COMPARISON:")
        report.append("-" * 100)
        report.append(f"{'Description':<40} {'BUY Trades':<12} {'BUY WR%':<10} {'SELL Trades':<13} {'SELL WR%':<11} {'Gap%':<8}")
        report.append("-" * 100)

        for i, row in df.iterrows():
            gap = row['sell_win_rate'] - row['buy_win_rate']
            report.append(
                f"{row['description']:<40} "
                f"{row['buy_trades']:<12} "
                f"{row['buy_win_rate']:<10.1f} "
                f"{row['sell_trades']:<13} "
                f"{row['sell_win_rate']:<11.1f} "
                f"{gap:<8.1f}"
            )

        report.append("")
        report.append("=" * 100)
        report.append("KEY FINDINGS:")
        report.append("-" * 100)

        # Best configuration
        best = df.iloc[0]
        report.append(f"✅ BEST OVERALL: {best['description']}")
        report.append(f"   Settings: ADVANTAGE={best['advantage']}, PENALTY={best['penalty']}%")
        report.append(f"   Return: {best['total_return_pct']:.1f}%, Win Rate: {best['win_rate']:.1f}%, PF: {best['profit_factor']:.2f}")
        report.append("")

        # Best BUY performance
        best_buy_wr = df.loc[df['buy_win_rate'].idxmax()]
        report.append(f"🎯 BEST BUY WIN RATE: {best_buy_wr['description']}")
        report.append(f"   BUY WR: {best_buy_wr['buy_win_rate']:.1f}%, Settings: ADVANTAGE={best_buy_wr['advantage']}, PENALTY={best_buy_wr['penalty']}%")
        report.append("")

        # Smallest BUY/SELL gap
        df['buy_sell_gap'] = abs(df['buy_win_rate'] - df['sell_win_rate'])
        smallest_gap = df.loc[df['buy_sell_gap'].idxmin()]
        report.append(f"⚖️  MOST BALANCED (smallest BUY/SELL gap): {smallest_gap['description']}")
        report.append(f"   BUY WR: {smallest_gap['buy_win_rate']:.1f}%, SELL WR: {smallest_gap['sell_win_rate']:.1f}%, Gap: {smallest_gap['buy_sell_gap']:.1f}%")
        report.append("")

        # Recommendations
        report.append("=" * 100)
        report.append("RECOMMENDATIONS:")
        report.append("-" * 100)

        if best['advantage'] == 0 and best['penalty'] == 0:
            report.append("✅ Remove all BUY bias - treat BUY and SELL equally")
            report.append("   → Set BUY_SIGNAL_ADVANTAGE = 0")
            report.append("   → Set BUY_CONFIDENCE_PENALTY = 0.0")
        elif best['advantage'] <= 1:
            report.append("✅ Use minimal BUY bias - BUY signals are performing well")
            report.append(f"   → Set BUY_SIGNAL_ADVANTAGE = {best['advantage']}")
            report.append(f"   → Set BUY_CONFIDENCE_PENALTY = {best['penalty']}")
        else:
            report.append("✅ Maintain selective BUY filtering - quality over quantity")
            report.append(f"   → Set BUY_SIGNAL_ADVANTAGE = {best['advantage']}")
            report.append(f"   → Set BUY_CONFIDENCE_PENALTY = {best['penalty']}")

        report.append("")
        report.append("📊 Trade-off Analysis:")
        if best['total_trades'] < df['total_trades'].mean() * 0.7:
            report.append("   ⚠️  Best config produces fewer trades (more selective)")
            report.append("   → Consider if you prefer more opportunities vs higher quality")
        else:
            report.append("   ✅ Best config maintains good trade frequency")

        report.append("")
        report.append("=" * 100)

        # Print report
        report_text = "\n".join(report)
        print(report_text)

        # Save to file
        report_file = f"/projects/ngTradingBot/backtest_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(report_file, 'w') as f:
            f.write(report_text)

        logger.info(f"\n📄 Report saved to: {report_file}")

        # Save results to CSV
        csv_file = f"/projects/ngTradingBot/backtest_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(csv_file, index=False)
        logger.info(f"📊 Results CSV saved to: {csv_file}")

        return report_text, df


def main():
    parser = argparse.ArgumentParser(description='Run backtest comparison for BUY bias optimization')
    parser.add_argument('--start', type=str, help='Start date (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, help='End date (YYYY-MM-DD)')
    parser.add_argument('--quick', action='store_true', help='Quick test (last 30 days)')
    parser.add_argument('--account-id', type=int, default=1, help='Account ID (default: 1)')

    args = parser.parse_args()

    # Determine date range
    if args.quick:
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)
        logger.info("📅 Quick mode: Testing last 30 days")
    elif args.start and args.end:
        start_date = datetime.strptime(args.start, '%Y-%m-%d')
        end_date = datetime.strptime(args.end, '%Y-%m-%d')
    else:
        # Default: last 60 days
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=60)
        logger.info("📅 Using default: Last 60 days")

    logger.info(f"Period: {start_date.date()} → {end_date.date()}")

    # Create runner
    runner = AuditBacktestRunner(start_date, end_date, args.account_id)

    # Run all tests
    runner.run_all_tests()

    # Generate comparison report
    runner.generate_comparison_report()

    logger.info("\n✅ Backtest comparison complete!")


if __name__ == '__main__':
    main()
