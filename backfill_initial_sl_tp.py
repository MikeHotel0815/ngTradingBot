#!/usr/bin/env python3
"""
Backfill initial_sl and initial_tp for existing trades

Problem:
- All closed trades have sl=0, tp=0 (overwritten on close)
- All trades have initial_sl=NULL, initial_tp=NULL

Solution:
- Get first SL/TP values from trade_history_events
- If no events, use current sl/tp from open trades
- Update trades.initial_sl and trades.initial_tp

Author: Claude Code
Date: 2025-10-27
"""

import logging
from database import ScopedSession
from models import Trade, TradeHistoryEvent
from sqlalchemy import and_

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def backfill_initial_sl_tp():
    """
    Backfill initial_sl and initial_tp for all trades
    """
    db = ScopedSession()
    try:
        logger.info("🔄 Starting backfill of initial_sl and initial_tp...")

        # Get all trades without initial_sl/tp
        trades = db.query(Trade).filter(
            Trade.initial_sl.is_(None)
        ).all()

        logger.info(f"Found {len(trades)} trades without initial_sl/tp")

        updated_count = 0
        skipped_count = 0

        for trade in trades:
            try:
                # Get first SL modification event for this trade
                first_sl_event = db.query(TradeHistoryEvent).filter(
                    TradeHistoryEvent.ticket == trade.ticket,
                    TradeHistoryEvent.event_type == 'SL_MODIFIED'
                ).order_by(TradeHistoryEvent.timestamp.asc()).first()

                # Get first TP modification event for this trade
                first_tp_event = db.query(TradeHistoryEvent).filter(
                    TradeHistoryEvent.ticket == trade.ticket,
                    TradeHistoryEvent.event_type == 'TP_MODIFIED'
                ).order_by(TradeHistoryEvent.timestamp.asc()).first()

                # Determine initial SL
                if first_sl_event and first_sl_event.old_value and first_sl_event.old_value != 0:
                    # Use the OLD value from first modification (that's the original SL)
                    initial_sl = float(first_sl_event.old_value)
                elif trade.status == 'open' and trade.sl and trade.sl != 0:
                    # For open trades, use current SL
                    initial_sl = float(trade.sl)
                else:
                    # No SL information available
                    initial_sl = None

                # Determine initial TP
                if first_tp_event and first_tp_event.old_value and first_tp_event.old_value != 0:
                    # Use the OLD value from first modification (that's the original TP)
                    initial_tp = float(first_tp_event.old_value)
                elif trade.status == 'open' and trade.tp and trade.tp != 0:
                    # For open trades, use current TP
                    initial_tp = float(trade.tp)
                else:
                    # No TP information available
                    initial_tp = None

                # Update trade if we have at least one value
                if initial_sl is not None or initial_tp is not None:
                    if initial_sl is not None:
                        trade.initial_sl = initial_sl
                    if initial_tp is not None:
                        trade.initial_tp = initial_tp

                    updated_count += 1

                    logger.debug(
                        f"✅ Trade {trade.ticket} ({trade.symbol}): "
                        f"initial_sl={initial_sl}, initial_tp={initial_tp}"
                    )
                else:
                    skipped_count += 1
                    logger.debug(f"⏭️  Trade {trade.ticket}: No SL/TP data available")

                # Commit in batches of 100
                if updated_count % 100 == 0:
                    db.commit()
                    logger.info(f"Progress: {updated_count} updated, {skipped_count} skipped")

            except Exception as e:
                logger.error(f"Error processing trade {trade.ticket}: {e}")
                db.rollback()  # Rollback failed transaction
                continue

        # Final commit
        db.commit()

        logger.info(
            f"✅ Backfill complete: {updated_count} trades updated, "
            f"{skipped_count} skipped (no data)"
        )

        return updated_count, skipped_count

    except Exception as e:
        logger.error(f"Error in backfill: {e}", exc_info=True)
        db.rollback()
        return 0, 0
    finally:
        db.close()


def verify_backfill():
    """
    Verify backfill results
    """
    db = ScopedSession()
    try:
        # Count trades with initial_sl/tp
        total_trades = db.query(Trade).count()
        with_initial_sl = db.query(Trade).filter(Trade.initial_sl.isnot(None)).count()
        with_initial_tp = db.query(Trade).filter(Trade.initial_tp.isnot(None)).count()

        logger.info("\n📊 Backfill Verification:")
        logger.info(f"Total trades: {total_trades}")
        logger.info(f"Trades with initial_sl: {with_initial_sl} ({with_initial_sl/total_trades*100:.1f}%)")
        logger.info(f"Trades with initial_tp: {with_initial_tp} ({with_initial_tp/total_trades*100:.1f}%)")

        # Sample some recent trades
        logger.info("\n📋 Sample Recent Trades:")
        recent_trades = db.query(Trade).filter(
            Trade.status == 'closed'
        ).order_by(Trade.close_time.desc()).limit(5).all()

        for trade in recent_trades:
            logger.info(
                f"  Ticket {trade.ticket}: sl={trade.sl}, tp={trade.tp}, "
                f"initial_sl={trade.initial_sl}, initial_tp={trade.initial_tp}"
            )

    except Exception as e:
        logger.error(f"Error in verification: {e}")
    finally:
        db.close()


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Backfill initial_sl and initial_tp')
    parser.add_argument('--verify', action='store_true', help='Only verify, don\'t backfill')

    args = parser.parse_args()

    if args.verify:
        verify_backfill()
    else:
        updated, skipped = backfill_initial_sl_tp()
        print(f"\n✅ Backfill complete: {updated} trades updated, {skipped} skipped")
        print("\nRunning verification...")
        verify_backfill()
