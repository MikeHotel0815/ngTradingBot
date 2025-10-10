#!/usr/bin/env python3
"""
Emergency fix to prevent duplicate trades per symbol+timeframe
This script adds a check before creating OPEN_TRADE commands
"""

import logging
from database import ScopedSession
from models import Trade, TradingSignal, GlobalSettings
from sqlalchemy import and_

logger = logging.getLogger(__name__)

def check_duplicate_position(account_id, symbol, timeframe):
    """
    Check if there's already an open position for this symbol+timeframe
    Returns True if a position exists, False otherwise
    """
    db = ScopedSession()
    try:
        existing_count = db.query(Trade).filter(
            and_(
                Trade.account_id == account_id,
                Trade.symbol == symbol,
                Trade.timeframe == timeframe,
                Trade.status == 'open'
            )
        ).count()

        logger.info(f"🔍 Duplicate check: {symbol} {timeframe} - Found {existing_count} open positions")

        return existing_count > 0
    finally:
        db.close()

def should_skip_signal(signal):
    """
    Determine if a signal should be skipped due to existing positions
    """
    if check_duplicate_position(signal.account_id, signal.symbol, signal.timeframe):
        logger.warning(f"⚠️ Skipping signal #{signal.id}: Already have open position for {signal.symbol} {signal.timeframe}")
        return True
    return False

if __name__ == "__main__":
    # Test the function
    logging.basicConfig(level=logging.INFO)

    db = ScopedSession()
    try:
        # Check all active signals
        active_signals = db.query(TradingSignal).filter_by(status='active').all()

        for signal in active_signals:
            if should_skip_signal(signal):
                print(f"Signal #{signal.id} ({signal.symbol} {signal.timeframe}) should be skipped - duplicate position exists")
            else:
                print(f"Signal #{signal.id} ({signal.symbol} {signal.timeframe}) OK to execute")

    finally:
        db.close()