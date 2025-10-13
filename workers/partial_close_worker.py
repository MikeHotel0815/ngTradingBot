#!/usr/bin/env python3
"""
Partial Close Strategy Worker

Implements staged profit-taking to lock in gains while letting winners run.

Strategy:
- At 50% of TP distance: Close 50% of position (lock profit, risk-free runner)
- At 75% of TP distance: Close 25% more (total 75% closed)
- Final 25%: Runs to TP or Trailing SL

Benefits:
- Locks in partial profits before reversal
- Lets winners run with remaining position
- Reduces psychological pressure to close early
- Better win-rate (more trades hit partial targets)

Part of Phase 4: Position Management
See: AUTONOMOUS_TRADING_ROADMAP.md
"""

import os
import sys
import time
import logging
from datetime import datetime
from typing import Dict, Optional
import uuid

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from models import Trade, Command

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
PARTIAL_CLOSE_ENABLED = os.getenv('PARTIAL_CLOSE_ENABLED', 'true').lower() == 'true'
CHECK_INTERVAL_SECONDS = int(os.getenv('PARTIAL_CLOSE_CHECK_INTERVAL', '60'))  # Check every minute

# Partial close thresholds (% of TP distance)
FIRST_PARTIAL_PERCENT = float(os.getenv('FIRST_PARTIAL_PERCENT', '50.0'))  # Close 50% at 50% TP
FIRST_PARTIAL_CLOSE = float(os.getenv('FIRST_PARTIAL_CLOSE', '0.50'))  # Close 50% of position

SECOND_PARTIAL_PERCENT = float(os.getenv('SECOND_PARTIAL_PERCENT', '75.0'))  # Close 25% at 75% TP
SECOND_PARTIAL_CLOSE = float(os.getenv('SECOND_PARTIAL_CLOSE', '0.25'))  # Close 25% more

# Minimum position size for partial close (avoid too small lots)
MIN_LOT_FOR_PARTIAL = float(os.getenv('MIN_LOT_FOR_PARTIAL', '0.02'))


def calculate_tp_progress(trade: Trade, current_price: float) -> float:
    """
    Calculate progress toward TP (0-100%)

    Args:
        trade: Trade object
        current_price: Current market price

    Returns:
        Progress percentage (0-100)
    """
    try:
        entry = float(trade.open_price)
        tp = float(trade.tp)
        sl = float(trade.sl)

        if not tp or not sl:
            return 0.0

        # Calculate TP distance
        if trade.direction.lower() == 'buy':
            tp_distance = tp - entry
            current_distance = current_price - entry
        else:  # SELL
            tp_distance = entry - tp
            current_distance = entry - current_price

        if tp_distance <= 0:
            return 0.0

        progress = (current_distance / tp_distance) * 100
        return max(0.0, min(100.0, progress))

    except Exception as e:
        logger.error(f"Error calculating TP progress for trade {trade.ticket}: {e}")
        return 0.0


def get_current_price(trade: Trade) -> Optional[float]:
    """Get current price for closing (bid for BUY, ask for SELL)"""
    try:
        # Use trade.profit to infer current price is available
        # In reality, you'd want to query Tick table or get from MT5
        # For now, return None if profit not available (will be handled by caller)
        if trade.profit is None:
            return None

        # Approximate current price from profit
        # This is simplified - in production, fetch from Tick table
        if trade.direction.lower() == 'buy':
            # For BUY: profit = (current_price - entry) * volume * contract_size
            # Simplified: return entry + some estimate
            return float(trade.open_price)  # Placeholder
        else:
            return float(trade.open_price)  # Placeholder

    except Exception as e:
        logger.error(f"Error getting current price for trade {trade.ticket}: {e}")
        return None


def has_partial_close_tag(trade: Trade, stage: str) -> bool:
    """Check if trade already has partial close marker for this stage"""
    try:
        # Check if comment/metadata contains partial close marker
        # This would be stored in a trade_metadata table or in comment field
        # For now, simplified check
        return False  # Placeholder - implement metadata check

    except Exception as e:
        logger.error(f"Error checking partial close tag: {e}")
        return False


def create_partial_close_command(
    db: Session,
    trade: Trade,
    close_percent: float,
    reason: str
) -> bool:
    """
    Create PARTIAL_CLOSE_TRADE command

    Args:
        db: Database session
        trade: Trade to partially close
        close_percent: Percentage of position to close (0.0-1.0)
        reason: Reason for partial close

    Returns:
        True if command created successfully
    """
    try:
        # Calculate close volume
        current_volume = float(trade.volume)
        close_volume = current_volume * close_percent

        # Round to lot step (assume 0.01)
        close_volume = round(close_volume / 0.01) * 0.01

        # Minimum close volume
        if close_volume < 0.01:
            logger.debug(f"Trade {trade.ticket}: Close volume {close_volume} too small, skipping")
            return False

        command_id = str(uuid.uuid4())

        payload_data = {
            'ticket': int(trade.ticket),
            'volume': close_volume,
            'reason': f'partial_close_{reason}',
            'worker': 'partial_close_worker'
        }

        command = Command(
            id=command_id,
            account_id=trade.account_id,
            command_type='PARTIAL_CLOSE_TRADE',
            payload=payload_data,
            status='pending',
            created_at=datetime.utcnow()
        )

        db.add(command)
        db.commit()

        logger.info(
            f"✂️  Created PARTIAL_CLOSE command for trade {trade.ticket}: "
            f"{close_volume:.2f} lot ({close_percent*100:.0f}%) - {reason}"
        )

        return True

    except Exception as e:
        logger.error(f"Error creating partial close command for trade {trade.ticket}: {e}")
        db.rollback()
        return False


def should_partial_close(
    db: Session,
    trade: Trade,
    progress: float
) -> tuple[bool, Optional[float], Optional[str]]:
    """
    Determine if trade should be partially closed

    Returns:
        (should_close, close_percent, reason)
    """
    try:
        # Check minimum volume for partial close
        if float(trade.volume) < MIN_LOT_FOR_PARTIAL:
            return False, None, "volume_too_small"

        # Check if trade has TP/SL set
        if not trade.tp or not trade.sl:
            return False, None, "no_tp_sl"

        # Stage 1: First partial close at 50% TP
        if progress >= FIRST_PARTIAL_PERCENT and not has_partial_close_tag(trade, 'stage1'):
            return True, FIRST_PARTIAL_CLOSE, f'stage1_{FIRST_PARTIAL_PERCENT}pct'

        # Stage 2: Second partial close at 75% TP
        if progress >= SECOND_PARTIAL_PERCENT and not has_partial_close_tag(trade, 'stage2'):
            # Only close if stage 1 already done (or would have been too small)
            return True, SECOND_PARTIAL_CLOSE, f'stage2_{SECOND_PARTIAL_PERCENT}pct'

        return False, None, "no_threshold_reached"

    except Exception as e:
        logger.error(f"Error checking partial close for trade {trade.ticket}: {e}")
        return False, None, "error"


def process_open_trades(db: Session) -> Dict[str, int]:
    """Process all open trades for partial close opportunities"""

    stats = {
        'total_open': 0,
        'checked': 0,
        'partial_closed': 0,
        'skipped_no_tpsl': 0,
        'skipped_too_small': 0,
        'errors': 0
    }

    try:
        # Get all open trades with TP/SL set
        open_trades = db.query(Trade).filter_by(status='open').all()
        stats['total_open'] = len(open_trades)

        if not open_trades:
            logger.debug("No open trades to process")
            return stats

        logger.info(f"Processing {len(open_trades)} open trade(s) for partial close")

        for trade in open_trades:
            try:
                stats['checked'] += 1

                # Skip if no TP/SL
                if not trade.tp or not trade.sl:
                    stats['skipped_no_tpsl'] += 1
                    continue

                # Skip if volume too small
                if float(trade.volume) < MIN_LOT_FOR_PARTIAL:
                    stats['skipped_too_small'] += 1
                    continue

                # Calculate progress toward TP
                # Get current price from trade profit (EA updates continuously)
                if trade.profit is None:
                    continue

                # Approximate current price from entry and profit
                # In production, fetch from Tick table
                entry = float(trade.open_price)
                tp = float(trade.tp)

                # Estimate progress from profit
                # This is simplified - should calculate from actual price
                if trade.direction.lower() == 'buy':
                    # Rough estimate
                    max_profit = (tp - entry) * float(trade.volume) * 100000  # Simplified
                    current_profit = float(trade.profit) if trade.profit else 0
                    progress = (current_profit / max_profit * 100) if max_profit > 0 else 0
                else:
                    max_profit = (entry - tp) * float(trade.volume) * 100000
                    current_profit = float(trade.profit) if trade.profit else 0
                    progress = (current_profit / max_profit * 100) if max_profit > 0 else 0

                progress = max(0, min(100, progress))

                # Check if should partial close
                should_close, close_percent, reason = should_partial_close(db, trade, progress)

                if should_close and close_percent:
                    logger.info(
                        f"💰 Trade {trade.ticket} ({trade.symbol} {trade.direction}): "
                        f"Progress {progress:.1f}% → Partial close {close_percent*100:.0f}% ({reason})"
                    )

                    if create_partial_close_command(db, trade, close_percent, reason):
                        stats['partial_closed'] += 1
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
    logger.info("PARTIAL CLOSE STRATEGY WORKER STARTING")
    logger.info("=" * 80)
    logger.info(f"Enabled: {PARTIAL_CLOSE_ENABLED}")
    logger.info(f"Check Interval: {CHECK_INTERVAL_SECONDS}s")
    logger.info("")
    logger.info("📊 PARTIAL CLOSE LEVELS:")
    logger.info(f"  Stage 1: {FIRST_PARTIAL_PERCENT}% of TP → Close {FIRST_PARTIAL_CLOSE*100:.0f}% of position")
    logger.info(f"  Stage 2: {SECOND_PARTIAL_PERCENT}% of TP → Close {SECOND_PARTIAL_CLOSE*100:.0f}% more")
    logger.info(f"  Remaining: Run to TP or Trailing SL")
    logger.info(f"  Min Lot for Partial: {MIN_LOT_FOR_PARTIAL:.2f}")
    logger.info("=" * 80)

    if not PARTIAL_CLOSE_ENABLED:
        logger.warning("⚠️  PARTIAL_CLOSE_ENABLED=false - Worker running but will not create commands")

    iteration = 0

    while True:
        try:
            iteration += 1
            logger.info(f"\n--- Iteration {iteration} - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC ---")

            db = SessionLocal()
            try:
                if PARTIAL_CLOSE_ENABLED:
                    stats = process_open_trades(db)

                    if stats['total_open'] > 0:
                        logger.info(
                            f"📊 Stats: {stats['checked']} checked, "
                            f"{stats['partial_closed']} partial closed, "
                            f"{stats['skipped_no_tpsl']} no TP/SL, "
                            f"{stats['skipped_too_small']} too small, "
                            f"{stats['errors']} errors"
                        )
                    else:
                        logger.debug("No open trades")
                else:
                    logger.debug("Partial close disabled, monitoring only")

            finally:
                db.close()

            # Sleep until next check
            time.sleep(CHECK_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("\n⚠️  Shutdown signal received - stopping worker")
            break
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(60)


if __name__ == '__main__':
    try:
        run_worker()
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
