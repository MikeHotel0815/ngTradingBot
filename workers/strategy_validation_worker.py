#!/usr/bin/env python3
"""
Strategy Validation Worker

Monitors open trades and closes ONLY losing trades when their entry strategy
no longer applies (pattern disappeared, indicators reversed, confidence dropped).

IMPORTANT: Only closes trades when BOTH conditions are met:
1. Trade is LOSING money (profit < 0)
2. Entry strategy is NO LONGER VALID

This prevents premature exits of winning trades and lets good trades run,
while cutting losses when the reason for entry no longer exists.

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

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from models import Trade, Command, TradingSignal
from signal_generator import SignalGenerator

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
STRATEGY_VALIDATION_ENABLED = os.getenv('STRATEGY_VALIDATION_ENABLED', 'true').lower() == 'true'
CHECK_INTERVAL_SECONDS = int(os.getenv('STRATEGY_VALIDATION_CHECK_INTERVAL', '300'))  # 5 minutes
MIN_LOSS_TO_CHECK = float(os.getenv('MIN_LOSS_TO_CHECK', '-5.0'))  # Only check trades losing >5 EUR


def get_current_trade_profit(trade: Trade) -> Optional[float]:
    """
    Get current unrealized profit for trade.

    The EA continuously updates trade.profit with MT5's PositionGetDouble(POSITION_PROFIT)
    which is always in account currency (EUR for this account).
    """
    try:
        if trade.profit is not None:
            return float(trade.profit)
        return None
    except Exception as e:
        logger.error(f"Error getting profit for trade {trade.ticket}: {e}")
        return None


def is_strategy_still_valid(db: Session, trade: Trade) -> tuple[bool, str]:
    """
    Check if the entry strategy for this trade is still valid.

    Returns:
        (is_valid, reason)
    """
    try:
        # Get the signal that triggered this trade
        if not trade.signal_id:
            logger.warning(f"Trade {trade.ticket} has no signal_id - cannot validate strategy")
            return True, "no_signal_id"  # Keep trade if we can't validate

        signal = db.query(TradingSignal).filter_by(id=trade.signal_id).first()
        if not signal:
            logger.warning(f"Signal #{trade.signal_id} not found for trade {trade.ticket}")
            return True, "signal_not_found"  # Keep trade if signal is missing

        # Create signal generator for re-analysis
        generator = SignalGenerator(
            account_id=trade.account_id,
            symbol=trade.symbol,
            timeframe=signal.timeframe
        )

        # Validate if strategy still applies
        is_valid = generator.validate_signal(signal)

        if not is_valid:
            return False, "strategy_invalidated"

        return True, "strategy_still_valid"

    except Exception as e:
        logger.error(f"Error validating strategy for trade {trade.ticket}: {e}")
        # On error, keep trade (don't close due to technical issues)
        return True, "validation_error"


def should_close_losing_trade(db: Session, trade: Trade) -> tuple[bool, str]:
    """
    Determine if a losing trade should be closed because strategy no longer applies.

    Rules:
    1. Only consider LOSING trades (profit < MIN_LOSS_TO_CHECK)
    2. Only close if entry strategy is NO LONGER VALID
    3. NEVER close winning trades (let them run!)
    4. NEVER close break-even trades (profit near 0)

    Returns:
        (should_close, reason)
    """
    # Get current profit
    current_profit = get_current_trade_profit(trade)

    if current_profit is None:
        logger.warning(f"Trade {trade.ticket}: Cannot get profit - keeping trade")
        return False, "no_profit_data"

    # Rule 1: Only check losing trades
    if current_profit >= MIN_LOSS_TO_CHECK:
        logger.debug(f"Trade {trade.ticket}: Profit {current_profit:.2f} EUR >= {MIN_LOSS_TO_CHECK} - skipping validation")
        return False, "not_losing_enough"

    logger.info(f"🔍 Trade {trade.ticket} ({trade.symbol} {trade.direction}) losing {current_profit:.2f} EUR - validating strategy...")

    # Rule 2: Check if strategy still valid
    is_valid, reason = is_strategy_still_valid(db, trade)

    if not is_valid:
        logger.warning(
            f"⚠️ Trade {trade.ticket} ({trade.symbol} {trade.direction}): "
            f"Strategy NO LONGER VALID (profit: {current_profit:.2f} EUR) - should close! Reason: {reason}"
        )
        return True, f"losing_strategy_invalid_{reason}"

    logger.debug(f"Trade {trade.ticket}: Strategy still valid - keeping trade")
    return False, "strategy_valid"


def create_close_command(db: Session, trade: Trade, reason: str) -> bool:
    """Create CLOSE_TRADE command for EA to execute"""
    try:
        command_id = str(uuid.uuid4())

        payload_data = {
            'ticket': int(trade.ticket),
            'reason': f'strategy_validation_{reason}',
            'worker': 'strategy_validation_worker'
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
    """Process all open trades and create close commands for losing trades with invalid strategies"""

    stats = {
        'total_open': 0,
        'checked': 0,
        'losing_trades': 0,
        'strategy_invalid': 0,
        'closed': 0,
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

                should_close, reason = should_close_losing_trade(db, trade)

                if 'losing' in reason.lower():
                    stats['losing_trades'] += 1

                if 'invalid' in reason.lower():
                    stats['strategy_invalid'] += 1

                if should_close:
                    profit = get_current_trade_profit(trade)
                    logger.warning(
                        f"💸 Trade {trade.ticket} ({trade.symbol} {trade.direction}) "
                        f"needs strategy-based exit: {reason} (profit: {profit:.2f} EUR)"
                    )

                    if create_close_command(db, trade, reason):
                        stats['closed'] += 1
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
    logger.info("STRATEGY VALIDATION WORKER STARTING")
    logger.info("=" * 80)
    logger.info(f"Enabled: {STRATEGY_VALIDATION_ENABLED}")
    logger.info(f"Check Interval: {CHECK_INTERVAL_SECONDS}s")
    logger.info(f"Min Loss to Check: {MIN_LOSS_TO_CHECK} EUR")
    logger.info("")
    logger.info("🎯 PURPOSE: Close LOSING trades when entry strategy no longer applies")
    logger.info("✅ KEEPS: Winning trades, break-even trades, trades with valid strategy")
    logger.info("❌ CLOSES: Losing trades where pattern/indicators reversed or disappeared")
    logger.info("=" * 80)

    if not STRATEGY_VALIDATION_ENABLED:
        logger.warning("⚠️  STRATEGY_VALIDATION_ENABLED=false - Worker running but will not create close commands")

    iteration = 0

    while True:
        try:
            iteration += 1
            logger.info(f"\n--- Iteration {iteration} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC ---")

            db = SessionLocal()
            try:
                stats = process_open_trades(db)

                if stats['total_open'] > 0:
                    logger.info(
                        f"📊 Stats: {stats['checked']} checked, "
                        f"{stats['losing_trades']} losing, "
                        f"{stats['strategy_invalid']} invalid strategy, "
                        f"{stats['closed']} closed, "
                        f"{stats['errors']} errors"
                    )
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
