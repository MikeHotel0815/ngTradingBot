#!/usr/bin/env python3
"""
Time-based Exit Worker

Monitors all open trades and closes them based on:
1. Maximum duration per timeframe (H1: 8h, H4: 24h, D1: 72h)
2. Force-close thresholds for losing trades
3. Break-even protection for long-running trades

This prevents indefinitely running trades and provides automatic exit
when Trailing Stop hasn't been triggered.

Part of Phase 2: Exit-Strategie Optimierung
See: AUTONOMOUS_TRADING_ROADMAP.md
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from models import Trade, Command, TradingSignal

# Logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database
DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot')
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine)

# Configuration
TIME_EXIT_ENABLED = os.getenv('TIME_EXIT_ENABLED', 'true').lower() == 'true'
CHECK_INTERVAL_SECONDS = int(os.getenv('TIME_EXIT_CHECK_INTERVAL', '300'))  # 5 minutes

# Time-based exit rules per timeframe
TIME_EXIT_RULES = {
    'H1': {
        'max_duration_hours': 8,
        'min_profit_to_hold': 0.0,  # At break-even: hold longer
        'force_close_at_loss': -10.0,  # Force close at -10 EUR
    },
    'H4': {
        'max_duration_hours': 24,
        'min_profit_to_hold': 0.0,
        'force_close_at_loss': -15.0,  # Force close at -15 EUR
    },
    'D1': {
        'max_duration_hours': 72,  # 3 days
        'min_profit_to_hold': 0.0,
        'force_close_at_loss': -20.0,  # Force close at -20 EUR
    },
    'DEFAULT': {
        'max_duration_hours': 48,  # Default for unknown timeframes
        'min_profit_to_hold': 0.0,
        'force_close_at_loss': -15.0,
    }
}


def get_trade_timeframe(db: Session, trade: Trade) -> str:
    """Get timeframe from associated signal"""
    if trade.signal_id:
        signal = db.query(TradingSignal).filter_by(id=trade.signal_id).first()
        if signal and signal.timeframe:
            return signal.timeframe

    # Default to H4 if unknown
    return 'H4'


def get_current_trade_profit(db: Session, trade: Trade) -> Optional[float]:
    """
    Get current unrealized profit for trade.

    The EA continuously updates trade.profit with MT5's PositionGetDouble(POSITION_PROFIT)
    which is always in account currency (EUR for this account).
    """
    try:
        # Use MT5 profit directly - it's continuously updated by EA
        if trade.profit is not None:
            return float(trade.profit)

        return None
    except Exception as e:
        logger.error(f"Error getting profit for trade {trade.ticket}: {e}")
        return None


def should_close_trade(db: Session, trade: Trade) -> tuple[bool, str]:
    """
    Determine if trade should be closed based on time rules

    Returns:
        (should_close, reason)
    """
    now = datetime.utcnow()
    trade_duration = now - trade.open_time
    duration_hours = trade_duration.total_seconds() / 3600

    # Get timeframe and rules
    timeframe = get_trade_timeframe(db, trade)
    rules = TIME_EXIT_RULES.get(timeframe, TIME_EXIT_RULES['DEFAULT'])

    max_hours = rules['max_duration_hours']
    force_loss = rules['force_close_at_loss']
    min_profit = rules['min_profit_to_hold']

    # Get current profit
    current_profit = get_current_trade_profit(db, trade)

    logger.debug(f"Trade {trade.ticket}: Duration={duration_hours:.1f}h, "
                f"Profit={current_profit}, TF={timeframe}, MaxHours={max_hours}")

    # Rule 1: Force close on large loss regardless of time
    if current_profit is not None and current_profit <= force_loss:
        return True, f"force_loss_threshold_{force_loss}EUR"

    # Rule 2: Max duration exceeded
    if duration_hours > max_hours:
        # If at break-even or profit, allow some grace period
        if current_profit is not None and current_profit >= min_profit:
            # Add 25% grace period for break-even trades
            grace_hours = max_hours * 0.25
            if duration_hours > (max_hours + grace_hours):
                return True, f"max_duration_{max_hours}h_exceeded_with_grace"
            else:
                logger.info(f"Trade {trade.ticket} at BE/profit, giving grace period")
                return False, "grace_period_active"
        else:
            # Loss or unknown profit: close at max duration
            return True, f"max_duration_{max_hours}h_exceeded"

    return False, "within_time_limits"


def create_close_command(db: Session, trade: Trade, reason: str) -> bool:
    """Create CLOSE_TRADE command for EA to execute"""
    try:
        command_id = str(uuid.uuid4())

        # Normalize close reason for consistent display
        # Map worker reasons to standard close reasons
        close_reason_map = {
            'max_duration': 'TIME_EXIT',
            'force_loss': 'TIME_EXIT',
            'grace_period': 'TIME_EXIT'
        }
        
        # Extract base reason (remove hours/details)
        base_reason = reason.split('_')[0] if '_' in reason else reason
        normalized_reason = close_reason_map.get(base_reason, 'TIME_EXIT')

        payload_data = {
            'ticket': int(trade.ticket),
            'reason': normalized_reason,  # Use normalized reason
            'worker': 'time_exit_worker',
            'details': reason  # Keep original for logging
        }

        command = Command(
            id=command_id,
            account_id=trade.account_id,
            command_type='CLOSE_TRADE',
            payload=payload_data,
            status='pending',
            created_at=datetime.utcnow()
        )

        db.add(command)
        db.commit()

        logger.info(f"✅ Created CLOSE_TRADE command for trade {trade.ticket}: {reason}")
        return True

    except Exception as e:
        logger.error(f"Error creating close command for trade {trade.ticket}: {e}")
        db.rollback()
        return False


def process_open_trades(db: Session) -> Dict[str, int]:
    """Process all open trades and create close commands if needed"""

    stats = {
        'total_open': 0,
        'checked': 0,
        'closed_max_duration': 0,
        'closed_force_loss': 0,
        'errors': 0
    }

    try:
        # Get all open trades
        open_trades = db.query(Trade).filter_by(status='open').all()
        stats['total_open'] = len(open_trades)

        if not open_trades:
            logger.debug("No open trades to process")
            return stats

        logger.info(f"Processing {len(open_trades)} open trade(s)")

        for trade in open_trades:
            try:
                stats['checked'] += 1

                should_close, reason = should_close_trade(db, trade)

                if should_close:
                    logger.warning(f"⏰ Trade {trade.ticket} ({trade.symbol} {trade.direction}) "
                                 f"needs time-based exit: {reason}")

                    if create_close_command(db, trade, reason):
                        if 'force_loss' in reason:
                            stats['closed_force_loss'] += 1
                        elif 'max_duration' in reason:
                            stats['closed_max_duration'] += 1
                    else:
                        stats['errors'] += 1

            except Exception as e:
                logger.error(f"Error processing trade {trade.ticket}: {e}")
                stats['errors'] += 1
                continue

        return stats

    except Exception as e:
        logger.error(f"Error querying open trades: {e}")
        stats['errors'] += 1
        return stats


def run_worker():
    """Main worker loop"""
    logger.info("=" * 80)
    logger.info("TIME-BASED EXIT WORKER STARTING")
    logger.info("=" * 80)
    logger.info(f"Enabled: {TIME_EXIT_ENABLED}")
    logger.info(f"Check Interval: {CHECK_INTERVAL_SECONDS}s")
    logger.info(f"Time Exit Rules:")
    for tf, rules in TIME_EXIT_RULES.items():
        if tf != 'DEFAULT':
            logger.info(f"  {tf}: Max {rules['max_duration_hours']}h, "
                       f"Force close at {rules['force_close_at_loss']} EUR")
    logger.info("=" * 80)

    if not TIME_EXIT_ENABLED:
        logger.warning("⚠️  TIME_EXIT_ENABLED=false - Worker running but will not create close commands")

    iteration = 0

    while True:
        try:
            iteration += 1
            logger.info(f"\n--- Iteration {iteration} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC ---")

            db = SessionLocal()
            try:
                stats = process_open_trades(db)

                if stats['total_open'] > 0:
                    logger.info(f"📊 Stats: {stats['checked']} checked, "
                              f"{stats['closed_max_duration']} duration closes, "
                              f"{stats['closed_force_loss']} force closes, "
                              f"{stats['errors']} errors")
                else:
                    logger.debug("No open trades")

            finally:
                db.close()

            # Sleep until next check
            time.sleep(CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("\n⚠️  Shutdown signal received - stopping worker")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(60)  # Sleep 1 minute on error


if __name__ == '__main__':
    try:
        run_worker()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
