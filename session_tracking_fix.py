#!/usr/bin/env python3
"""
Session Tracking Fix

Fills missing 'session' field in Trades table and ensures future trades are tagged.

According to Baseline Performance Report:
- ALL 190 trades have session = NULL
- This prevents session-based performance analysis
- Need to backfill existing trades and fix ongoing tracking

Solution:
1. Backfill existing trades based on open_time
2. Add session tracking to trade synchronization process
3. Monitor and report session-based performance

Usage:
    # Backfill all trades with missing session
    python3 session_tracking_fix.py --backfill

    # Check session distribution
    python3 session_tracking_fix.py --report

    # Fix specific account
    python3 session_tracking_fix.py --backfill --account-id 1
"""

import logging
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session
from models import Trade, Account
from database import get_session
from market_hours import get_trading_session

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SessionTracker:
    """Handles session tracking for trades"""

    def __init__(self, db: Optional[Session] = None):
        """
        Initialize Session Tracker

        Args:
            db: Optional database session
        """
        self.db = db or next(get_session())

    def backfill_sessions(self, account_id: Optional[int] = None) -> Dict:
        """
        Backfill session field for existing trades

        Args:
            account_id: Optional account ID filter

        Returns:
            Dict with statistics
        """
        logger.info("Starting session backfill...")

        # Query trades with missing session
        query = self.db.query(Trade).filter(
            (Trade.session == None) | (Trade.session == '')
        )

        if account_id:
            query = query.filter(Trade.account_id == account_id)

        trades_to_fix = query.all()

        if not trades_to_fix:
            logger.info("✅ No trades need session backfill")
            return {
                'total': 0,
                'updated': 0,
                'failed': 0
            }

        logger.info(f"Found {len(trades_to_fix)} trades with missing session")

        stats = {
            'total': len(trades_to_fix),
            'updated': 0,
            'failed': 0,
            'sessions': {
                'ASIAN': 0,
                'LONDON': 0,
                'US': 0,
                'LONDON_US_OVERLAP': 0,
                'CLOSED': 0
            }
        }

        for trade in trades_to_fix:
            try:
                # Calculate session based on open_time
                if trade.open_time:
                    session = get_trading_session(trade.symbol, trade.open_time)
                    trade.session = session
                    stats['sessions'][session] = stats['sessions'].get(session, 0) + 1
                    stats['updated'] += 1

                    if stats['updated'] % 100 == 0:
                        self.db.commit()
                        logger.info(f"  Progress: {stats['updated']}/{stats['total']} trades updated...")

                else:
                    logger.warning(f"Trade #{trade.id} has no open_time, cannot determine session")
                    stats['failed'] += 1

            except Exception as e:
                logger.error(f"Error processing trade #{trade.id}: {e}")
                stats['failed'] += 1

        # Final commit
        self.db.commit()

        logger.info("\n" + "="*60)
        logger.info("SESSION BACKFILL COMPLETE")
        logger.info("="*60)
        logger.info(f"Total trades processed: {stats['total']}")
        logger.info(f"Successfully updated: {stats['updated']}")
        logger.info(f"Failed: {stats['failed']}")
        logger.info("\nSession Distribution:")
        for session, count in stats['sessions'].items():
            pct = (count / stats['updated'] * 100) if stats['updated'] > 0 else 0
            logger.info(f"  {session:<20} {count:>5} ({pct:>5.1f}%)")
        logger.info("="*60 + "\n")

        return stats

    def get_session_report(self, account_id: Optional[int] = None, days: int = 30) -> Dict:
        """
        Generate session-based performance report

        Args:
            account_id: Optional account ID filter
            days: Number of days to analyze

        Returns:
            Dict with session performance metrics
        """
        from datetime import datetime, timedelta
        from sqlalchemy import func

        logger.info(f"Generating session report (last {days} days)...")

        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # Query closed trades with session data
        query = self.db.query(
            Trade.session,
            func.count(Trade.id).label('total_trades'),
            func.sum(func.case((Trade.profit > 0, 1), else_=0)).label('winning_trades'),
            func.sum(Trade.profit).label('total_profit'),
            func.avg(Trade.profit).label('avg_profit')
        ).filter(
            Trade.status == 'closed',
            Trade.close_time >= cutoff_date,
            Trade.session != None,
            Trade.session != ''
        ).group_by(Trade.session)

        if account_id:
            query = query.filter(Trade.account_id == account_id)

        results = query.all()

        report = {}

        for row in results:
            session = row.session
            total = row.total_trades
            winning = row.winning_trades or 0
            win_rate = (winning / total * 100) if total > 0 else 0

            report[session] = {
                'total_trades': total,
                'winning_trades': winning,
                'losing_trades': total - winning,
                'win_rate': win_rate,
                'total_profit': float(row.total_profit or 0),
                'avg_profit': float(row.avg_profit or 0)
            }

        # Print report
        logger.info("\n" + "="*80)
        logger.info(f"SESSION PERFORMANCE REPORT (Last {days} days)")
        logger.info("="*80)
        logger.info(f"{'Session':<20} {'Trades':<8} {'Win Rate':<10} {'Total P/L':<12} {'Avg P/L':<10}")
        logger.info("-"*80)

        for session in ['ASIAN', 'LONDON', 'US', 'LONDON_US_OVERLAP', 'CLOSED']:
            if session in report:
                data = report[session]
                logger.info(
                    f"{session:<20} "
                    f"{data['total_trades']:<8} "
                    f"{data['win_rate']:<10.1f}% "
                    f"€{data['total_profit']:<11.2f} "
                    f"€{data['avg_profit']:<9.2f}"
                )
            else:
                logger.info(f"{session:<20} {'0':<8} {'-':<10} {'-':<12} {'-':<10}")

        logger.info("="*80 + "\n")

        return report

    def set_trade_session(self, trade_id: int) -> bool:
        """
        Set session for a specific trade

        Args:
            trade_id: Trade ID

        Returns:
            True if successful
        """
        trade = self.db.query(Trade).filter(Trade.id == trade_id).first()

        if not trade:
            logger.error(f"Trade #{trade_id} not found")
            return False

        if trade.open_time:
            session = get_trading_session(trade.symbol, trade.open_time)
            trade.session = session
            self.db.commit()
            logger.info(f"✅ Set Trade #{trade_id} session to {session}")
            return True
        else:
            logger.error(f"Trade #{trade_id} has no open_time")
            return False


def add_session_to_trade_sync():
    """
    Add session tracking to trade synchronization process

    This should be called in the trade sync endpoint to ensure
    all new trades from MT5 get session field populated.

    Returns:
        Function decorator for trade sync
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            # Call original function
            result = func(*args, **kwargs)

            # If it's a trade sync, add session
            if isinstance(result, dict) and 'trades' in result:
                from database import get_session
                db = next(get_session())

                for trade_data in result['trades']:
                    if 'id' in trade_data:
                        trade = db.query(Trade).filter(Trade.id == trade_data['id']).first()
                        if trade and trade.open_time and not trade.session:
                            session = get_trading_session(trade.symbol, trade.open_time)
                            trade.session = session

                db.commit()

            return result

        return wrapper
    return decorator


def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='Session Tracking Fix')
    parser.add_argument('--backfill', action='store_true', help='Backfill sessions for existing trades')
    parser.add_argument('--report', action='store_true', help='Generate session performance report')
    parser.add_argument('--account-id', type=int, help='Filter by account ID')
    parser.add_argument('--days', type=int, default=30, help='Days for report (default: 30)')
    parser.add_argument('--trade-id', type=int, help='Set session for specific trade ID')

    args = parser.parse_args()

    tracker = SessionTracker()

    if args.backfill:
        stats = tracker.backfill_sessions(account_id=args.account_id)
        return 0 if stats['failed'] == 0 else 1

    elif args.report:
        report = tracker.get_session_report(account_id=args.account_id, days=args.days)
        return 0

    elif args.trade_id:
        success = tracker.set_trade_session(args.trade_id)
        return 0 if success else 1

    else:
        parser.print_help()
        return 1


if __name__ == '__main__':
    import sys
    sys.exit(main())
