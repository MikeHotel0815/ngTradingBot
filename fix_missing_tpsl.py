#!/usr/bin/env python3
"""
Fix Missing TP/SL for Open Trades
Creates MODIFY_TRADE commands to set TP/SL on trades that don't have them
"""

import os
import sys
from database import init_db, ScopedSession
from models import Trade, Command, TradingSignal, GlobalSettings
from datetime import datetime
import uuid
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def calculate_tpsl_from_signal(trade: Trade, signal: TradingSignal):
    """Calculate TP/SL from signal data"""
    if not signal:
        return None, None

    return float(signal.tp_price) if signal.tp_price else None, float(signal.sl_price) if signal.sl_price else None


def calculate_default_tpsl(trade: Trade):
    """Calculate default TP/SL based on 2:1 risk-reward"""
    entry = float(trade.open_price)

    if trade.direction.upper() == 'BUY':
        # BUY: SL below, TP above
        sl = entry * 0.995  # 0.5% SL
        tp = entry * 1.010  # 1.0% TP (2:1 RR)
    else:
        # SELL: SL above, TP below
        sl = entry * 1.005  # 0.5% SL
        tp = entry * 0.990  # 1.0% TP (2:1 RR)

    return tp, sl


def fix_trade_tpsl(db, trade: Trade, dry_run=True):
    """Create MODIFY_TRADE command to set TP/SL"""

    logger.info(f"Processing Trade #{trade.ticket} - {trade.symbol} {trade.direction}")

    # Try to get TP/SL from signal
    tp, sl = None, None

    if trade.signal_id:
        signal = db.query(TradingSignal).filter_by(id=trade.signal_id).first()
        if signal:
            tp, sl = calculate_tpsl_from_signal(trade, signal)
            logger.info(f"  Found signal #{signal.id}: TP={tp}, SL={sl}")

    # Fallback to default calculation
    if not tp or not sl:
        tp, sl = calculate_default_tpsl(trade)
        logger.info(f"  Using default 2:1 RR: TP={tp:.5f}, SL={sl:.5f}")

    if not tp or not sl:
        logger.error(f"  ❌ Could not calculate TP/SL!")
        return False

    # Create MODIFY_TRADE command
    command_id = str(uuid.uuid4())

    payload_data = {
        'ticket': int(trade.ticket),
        'sl': sl,
        'tp': tp,
        'reason': 'fix_missing_tpsl'
    }

    if dry_run:
        logger.info(f"  [DRY RUN] Would create MODIFY_TRADE command:")
        logger.info(f"    Command ID: {command_id}")
        logger.info(f"    Ticket: {trade.ticket}")
        logger.info(f"    TP: {tp:.5f}")
        logger.info(f"    SL: {sl:.5f}")
        return True
    else:
        command = Command(
            id=command_id,
            account_id=trade.account_id,
            command_type='MODIFY_TRADE',
            payload=payload_data,
            status='pending',
            created_at=datetime.utcnow()
        )

        db.add(command)
        db.commit()

        logger.info(f"  ✅ Created MODIFY_TRADE command {command_id}")
        logger.info(f"     TP: {tp:.5f}, SL: {sl:.5f}")

        return True


def main():
    # Parse arguments
    dry_run = True
    if len(sys.argv) > 1 and sys.argv[1] == '--execute':
        dry_run = False

    if dry_run:
        logger.info("=" * 80)
        logger.info("DRY RUN MODE - No commands will be created")
        logger.info("Run with --execute to actually create MODIFY commands")
        logger.info("=" * 80)
        logger.info("")

    init_db()

    with ScopedSession() as db:
        # Get all open trades without TP/SL
        trades = db.query(Trade).filter(
            Trade.status == 'open',
            ((Trade.tp == 0) | (Trade.tp == None) | (Trade.sl == 0) | (Trade.sl == None))
        ).all()

        if not trades:
            logger.info("✅ No open trades with missing TP/SL found!")
            return

        logger.info(f"Found {len(trades)} trade(s) with missing TP/SL\n")

        fixed_count = 0
        for trade in trades:
            if fix_trade_tpsl(db, trade, dry_run=dry_run):
                fixed_count += 1
            logger.info("")

        logger.info("=" * 80)
        logger.info(f"{'[DRY RUN] Would fix' if dry_run else 'Fixed'} {fixed_count}/{len(trades)} trades")

        if dry_run and fixed_count > 0:
            logger.info("\nRun with --execute to actually create MODIFY commands:")
            logger.info("  python3 fix_missing_tpsl.py --execute")


if __name__ == '__main__':
    main()
