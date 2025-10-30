#!/usr/bin/env python3
"""
P/L Time Series Analyzer for Dashboard Charts

Provides P/L data for different time intervals:
- 1 hour
- 12 hours
- 24 hours
- 1 week
- 1 year

Usage:
    analyzer = PnLAnalyzer(account_id=3)
    data = analyzer.get_pnl_timeseries('24h')
"""

import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from sqlalchemy import create_engine, and_
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from models import Trade

import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PnLAnalyzer:
    """Analyze and provide P/L data for dashboard charts"""

    def __init__(self, account_id: int):
        self.account_id = account_id

        # Database setup
        database_url = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
        self.engine = create_engine(database_url)
        Session = sessionmaker(bind=self.engine)
        self.db = Session()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.db.close()

    def get_pnl_timeseries(self, interval: str) -> Dict:
        """
        Get P/L time series data for the specified interval

        Args:
            interval: One of '1h', '12h', '24h', '1w', '1y'

        Returns:
            Dict with:
                - timestamps: List of datetime strings
                - pnl_values: List of cumulative P/L values
                - trade_counts: List of trade counts per period
                - total_pnl: Total P/L for the period
                - trade_count: Total trade count
                - win_rate: Win rate percentage
                - period_start: Start of the period
                - period_end: End of the period
        """

        # Define time periods
        now = datetime.utcnow()

        intervals = {
            '1h': timedelta(hours=1),
            '12h': timedelta(hours=12),
            '24h': timedelta(hours=24),
            '1w': timedelta(weeks=1),
            '1y': timedelta(days=365),
            'ytd': None  # Year-to-date (special handling)
        }

        if interval not in intervals:
            raise ValueError(f"Invalid interval: {interval}. Must be one of {list(intervals.keys())}")

        # Special handling for year-to-date
        if interval == 'ytd':
            period_start = datetime(now.year, 1, 1)  # Start of current year
        else:
            period_delta = intervals[interval]
            period_start = now - period_delta

        # Query trades in the period
        trades = self.db.query(Trade).filter(
            and_(
                Trade.account_id == self.account_id,
                Trade.close_time >= period_start,
                Trade.status == 'closed'
            )
        ).order_by(Trade.close_time.asc()).all()

        if not trades:
            return {
                'timestamps': [],
                'pnl_values': [],
                'trade_counts': [],
                'total_pnl': 0.0,
                'trade_count': 0,
                'win_rate': 0.0,
                'period_start': period_start.isoformat(),
                'period_end': now.isoformat(),
                'interval': interval
            }

        # Calculate cumulative P/L
        timestamps = []
        pnl_values = []
        cumulative_pnl = 0.0

        for trade in trades:
            cumulative_pnl += float(trade.profit)
            timestamps.append(trade.close_time.isoformat())
            pnl_values.append(round(cumulative_pnl, 2))

        # Calculate statistics
        winning_trades = sum(1 for t in trades if float(t.profit) > 0)
        win_rate = (winning_trades / len(trades) * 100) if trades else 0.0

        total_pnl = sum(float(t.profit) for t in trades)

        return {
            'timestamps': timestamps,
            'pnl_values': pnl_values,
            'trade_counts': [1] * len(trades),  # One trade per data point
            'total_pnl': round(total_pnl, 2),
            'trade_count': len(trades),
            'win_rate': round(win_rate, 1),
            'period_start': period_start.isoformat(),
            'period_end': now.isoformat(),
            'interval': interval
        }

    def get_aggregated_pnl(self, interval: str, bucket_size: str = 'auto') -> Dict:
        """
        Get aggregated P/L data with time buckets

        Args:
            interval: One of '1h', '12h', '24h', '1w', '1y'
            bucket_size: Size of time buckets ('auto', '5min', '1h', '1d')

        Returns:
            Dict with aggregated P/L data in time buckets
        """

        now = datetime.utcnow()

        intervals = {
            '1h': timedelta(hours=1),
            '12h': timedelta(hours=12),
            '24h': timedelta(hours=24),
            '1w': timedelta(weeks=1),
            '1y': timedelta(days=365),
            'ytd': None  # Year-to-date
        }

        if interval not in intervals:
            raise ValueError(f"Invalid interval: {interval}")

        # Special handling for year-to-date
        if interval == 'ytd':
            period_start = datetime(now.year, 1, 1)
        else:
            period_delta = intervals[interval]
            period_start = now - period_delta

        # Auto-determine bucket size
        if bucket_size == 'auto':
            if interval == '1h':
                bucket_delta = timedelta(minutes=5)
            elif interval == '12h':
                bucket_delta = timedelta(minutes=30)
            elif interval == '24h':
                bucket_delta = timedelta(hours=1)
            elif interval == '1w':
                bucket_delta = timedelta(hours=6)
            elif interval == 'ytd':
                bucket_delta = timedelta(days=7)
            else:  # 1y
                bucket_delta = timedelta(days=7)
        else:
            bucket_deltas = {
                '5min': timedelta(minutes=5),
                '30min': timedelta(minutes=30),
                '1h': timedelta(hours=1),
                '6h': timedelta(hours=6),
                '1d': timedelta(days=1),
                '1w': timedelta(weeks=1)
            }
            bucket_delta = bucket_deltas.get(bucket_size, timedelta(hours=1))

        # Query trades
        trades = self.db.query(Trade).filter(
            and_(
                Trade.account_id == self.account_id,
                Trade.close_time >= period_start,
                Trade.status == 'closed'
            )
        ).order_by(Trade.close_time.asc()).all()

        # Create buckets
        buckets = []
        current_bucket_start = period_start

        while current_bucket_start < now:
            bucket_end = current_bucket_start + bucket_delta
            buckets.append({
                'start': current_bucket_start,
                'end': bucket_end,
                'trades': [],
                'pnl': 0.0,
                'trade_count': 0
            })
            current_bucket_start = bucket_end

        # Fill buckets with trades
        for trade in trades:
            trade_time = trade.close_time
            for bucket in buckets:
                if bucket['start'] <= trade_time < bucket['end']:
                    bucket['trades'].append(trade)
                    bucket['pnl'] += float(trade.profit)
                    bucket['trade_count'] += 1
                    break

        # Calculate cumulative P/L
        cumulative_pnl = 0.0
        timestamps = []
        pnl_values = []
        trade_counts = []

        for bucket in buckets:
            cumulative_pnl += bucket['pnl']
            timestamps.append(bucket['end'].isoformat())
            pnl_values.append(round(cumulative_pnl, 2))
            trade_counts.append(bucket['trade_count'])

        # Statistics
        winning_trades = sum(1 for t in trades if float(t.profit) > 0)
        win_rate = (winning_trades / len(trades) * 100) if trades else 0.0
        total_pnl = sum(float(t.profit) for t in trades)

        return {
            'timestamps': timestamps,
            'pnl_values': pnl_values,
            'trade_counts': trade_counts,
            'total_pnl': round(total_pnl, 2),
            'trade_count': len(trades),
            'win_rate': round(win_rate, 1),
            'period_start': period_start.isoformat(),
            'period_end': now.isoformat(),
            'interval': interval,
            'bucket_size': bucket_size
        }

    def get_multi_interval_summary(self) -> Dict:
        """Get P/L summary for all intervals"""

        intervals = ['1h', '12h', '24h', '1w', 'ytd']
        summary = {}

        for interval in intervals:
            try:
                data = self.get_pnl_timeseries(interval)
                summary[interval] = {
                    'total_pnl': data['total_pnl'],
                    'trade_count': data['trade_count'],
                    'win_rate': data['win_rate'],
                    'last_value': data['pnl_values'][-1] if data['pnl_values'] else 0.0
                }
            except Exception as e:
                logger.error(f"Error getting {interval} data: {e}")
                summary[interval] = {
                    'total_pnl': 0.0,
                    'trade_count': 0,
                    'win_rate': 0.0,
                    'last_value': 0.0
                }

        return summary


def main():
    """Test the P/L analyzer"""
    import argparse

    parser = argparse.ArgumentParser(description='P/L Time Series Analyzer')
    parser.add_argument('account_id', type=int, help='MT5 Account ID')
    parser.add_argument('--interval', choices=['1h', '12h', '24h', '1w', '1y'], default='24h', help='Time interval')
    parser.add_argument('--aggregated', action='store_true', help='Use aggregated buckets')
    parser.add_argument('--summary', action='store_true', help='Show summary for all intervals')

    args = parser.parse_args()

    with PnLAnalyzer(args.account_id) as analyzer:
        if args.summary:
            summary = analyzer.get_multi_interval_summary()
            print("\n📊 P/L SUMMARY FOR ALL INTERVALS")
            print("=" * 60)
            for interval, data in summary.items():
                print(f"\n{interval.upper()}:")
                print(f"  P/L: ${data['total_pnl']:.2f}")
                print(f"  Trades: {data['trade_count']}")
                print(f"  Win Rate: {data['win_rate']:.1f}%")
        elif args.aggregated:
            data = analyzer.get_aggregated_pnl(args.interval)
            print(f"\n📊 AGGREGATED P/L DATA ({args.interval.upper()})")
            print("=" * 60)
            print(f"Period: {data['period_start']} to {data['period_end']}")
            print(f"Total P/L: ${data['total_pnl']:.2f}")
            print(f"Trades: {data['trade_count']}")
            print(f"Win Rate: {data['win_rate']:.1f}%")
            print(f"\nData points: {len(data['timestamps'])}")
        else:
            data = analyzer.get_pnl_timeseries(args.interval)
            print(f"\n📊 P/L TIME SERIES ({args.interval.upper()})")
            print("=" * 60)
            print(f"Period: {data['period_start']} to {data['period_end']}")
            print(f"Total P/L: ${data['total_pnl']:.2f}")
            print(f"Trades: {data['trade_count']}")
            print(f"Win Rate: {data['win_rate']:.1f}%")
            print(f"\nData points: {len(data['timestamps'])}")

            if data['pnl_values']:
                print(f"First value: ${data['pnl_values'][0]:.2f}")
                print(f"Last value: ${data['pnl_values'][-1]:.2f}")


if __name__ == '__main__':
    main()
