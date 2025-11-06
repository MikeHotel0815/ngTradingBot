#!/usr/bin/env python3
"""
Post-Close TP Tracker Worker
Tracks if TP would have been hit AFTER Trailing Stop closed the trade

This enables ML learning about Trailing Stop aggressiveness:
- Was TS too aggressive? (closed early, TP hit later)
- Was TS optimal? (closed near best price)
- Was TS too passive? (price reversed significantly)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict
from decimal import Decimal

from database import ScopedSession
from models import Trade, Tick

logger = logging.getLogger(__name__)


class PostCloseTracker:
    """
    Tracks price movement after TS closes a trade to determine if TP would have been hit
    """

    def __init__(self):
        self.tracking_window_hours = 4  # Track for 4 hours after close
        self.check_interval_seconds = 60  # Check every minute

    def get_trades_needing_tracking(self, db) -> list:
        """
        Get trades that were closed by TS and need post-close tracking

        Returns:
            List of Trade objects that need tracking
        """
        now = datetime.utcnow()

        # Find TS trades that:
        # 1. Were closed by TRAILING_STOP or PARTIAL_CLOSE
        # 2. Have initial_tp set (so we know what to track)
        # 3. Haven't been tracked yet OR tracking window expired
        # 4. Closed within last 4 hours (still relevant to track)

        trades = db.query(Trade).filter(
            Trade.close_reason.in_(['TRAILING_STOP', 'PARTIAL_CLOSE']),
            Trade.status == 'closed',
            Trade.initial_tp.isnot(None),
            Trade.initial_tp > 0,
            Trade.close_time.isnot(None),
            Trade.close_time >= now - timedelta(hours=self.tracking_window_hours),
            Trade.post_close_tracked_until.is_(None)  # Not tracked yet
        ).order_by(Trade.close_time.asc()).all()

        logger.info(f"🔍 Found {len(trades)} TS trades needing post-close tracking")
        return trades

    def calculate_pips(self, price_diff: float, symbol: str) -> float:
        """
        Convert price difference to pips based on symbol type

        Args:
            price_diff: Price difference (positive or negative)
            symbol: Trading symbol

        Returns:
            Pips value (positive or negative)
        """
        # Forex majors/minors: 4-5 decimal places (0.0001 = 1 pip)
        if any(x in symbol for x in ['USD', 'EUR', 'GBP', 'AUD', 'NZD', 'CAD', 'CHF']):
            if 'JPY' in symbol:
                return price_diff * 100  # JPY pairs: 2 decimals (0.01 = 1 pip)
            else:
                return price_diff * 10000  # Standard forex: 4 decimals

        # Indices, metals, crypto: 1 point = 1 pip (already in correct scale)
        return price_diff

    def get_price_for_direction(self, tick: Tick, direction: str) -> float:
        """
        Get relevant price based on trade direction

        Args:
            tick: Tick object
            direction: 'BUY' or 'SELL'

        Returns:
            Bid for SELL, Ask for BUY
        """
        if direction == 'BUY':
            return float(tick.bid)  # BUY closes at bid
        else:
            return float(tick.ask)  # SELL closes at ask

    def track_single_trade(self, db, trade: Trade) -> bool:
        """
        Track post-close price movement for a single trade

        Args:
            db: Database session
            trade: Trade object to track

        Returns:
            True if tracking completed, False if still ongoing
        """
        now = datetime.utcnow()
        tracking_end_time = trade.close_time + timedelta(hours=self.tracking_window_hours)

        # Check if tracking window has expired
        if now >= tracking_end_time:
            # Finalize tracking
            trade.post_close_tracked_until = tracking_end_time
            db.commit()
            logger.info(f"✅ Post-close tracking completed for #{trade.ticket} (window expired)")
            return True

        # Get ticks since trade close
        ticks = db.query(Tick).filter(
            Tick.symbol == trade.symbol,
            Tick.timestamp >= trade.close_time,
            Tick.timestamp <= now
        ).order_by(Tick.timestamp.asc()).all()

        if not ticks:
            logger.debug(f"No ticks available yet for {trade.symbol} after close")
            return False

        # Calculate TP level and distance
        initial_tp = float(trade.initial_tp)
        close_price = float(trade.close_price)

        # Initialize tracking variables
        tp_was_hit = False
        tp_hit_time = None
        tp_hit_minutes = None
        max_favorable = 0.0
        max_adverse = 0.0

        # Analyze each tick
        # IMPORTANT: Stop tracking if SL or TP hit (realistic "what if" scenario)
        initial_sl = float(trade.initial_sl) if trade.initial_sl else None

        for tick in ticks:
            current_price = self.get_price_for_direction(tick, trade.direction)

            # Calculate price movement from close price
            if trade.direction == 'BUY':
                # BUY: favorable = up, adverse = down
                price_diff = current_price - close_price
                favorable_pips = self.calculate_pips(price_diff, trade.symbol) if price_diff > 0 else 0
                adverse_pips = abs(self.calculate_pips(price_diff, trade.symbol)) if price_diff < 0 else 0

                # Check if TP hit (EXIT tracking - target reached!)
                if not tp_was_hit and current_price >= initial_tp:
                    tp_was_hit = True
                    tp_hit_time = tick.timestamp
                    tp_hit_minutes = int((tp_hit_time - trade.close_time).total_seconds() / 60)
                    # STOP tracking - TP reached, trade would have closed
                    logger.debug(f"#{trade.ticket} TP hit at {tp_hit_time}, stopping tracking")
                    break

                # Check if SL hit (EXIT tracking - stop loss triggered!)
                if initial_sl and current_price <= initial_sl:
                    logger.debug(f"#{trade.ticket} SL hit at {tick.timestamp}, stopping tracking (worst case)")
                    break

            else:  # SELL
                # SELL: favorable = down, adverse = up
                price_diff = close_price - current_price
                favorable_pips = self.calculate_pips(price_diff, trade.symbol) if price_diff > 0 else 0
                adverse_pips = abs(self.calculate_pips(price_diff, trade.symbol)) if price_diff < 0 else 0

                # Check if TP hit (EXIT tracking - target reached!)
                if not tp_was_hit and current_price <= initial_tp:
                    tp_was_hit = True
                    tp_hit_time = tick.timestamp
                    tp_hit_minutes = int((tp_hit_time - trade.close_time).total_seconds() / 60)
                    # STOP tracking - TP reached, trade would have closed
                    logger.debug(f"#{trade.ticket} TP hit at {tp_hit_time}, stopping tracking")
                    break

                # Check if SL hit (EXIT tracking - stop loss triggered!)
                if initial_sl and current_price >= initial_sl:
                    logger.debug(f"#{trade.ticket} SL hit at {tick.timestamp}, stopping tracking (worst case)")
                    break

            # Track max favorable/adverse
            max_favorable = max(max_favorable, favorable_pips)
            max_adverse = max(max_adverse, adverse_pips)

        # Update trade with findings
        trade.tp_hit_after_close = tp_was_hit
        trade.tp_hit_after_close_time = tp_hit_time
        trade.tp_hit_after_close_minutes = tp_hit_minutes
        trade.max_favorable_after_close = Decimal(str(round(max_favorable, 2)))
        trade.max_adverse_after_close = Decimal(str(round(max_adverse, 2)))

        # If tracking window complete, mark as done
        if now >= tracking_end_time:
            trade.post_close_tracked_until = tracking_end_time

            # Log results
            if tp_was_hit:
                logger.info(
                    f"📊 TS EARLY EXIT: #{trade.ticket} {trade.symbol} - "
                    f"TP hit {tp_hit_minutes}min after TS close "
                    f"(max: +{max_favorable:.1f} pips)"
                )
            else:
                logger.info(
                    f"📊 TS OPTIMAL: #{trade.ticket} {trade.symbol} - "
                    f"TP NOT hit in 4h window "
                    f"(max: +{max_favorable:.1f} pips, worst: -{max_adverse:.1f} pips)"
                )

            db.commit()
            return True

        # Still tracking, save intermediate results
        db.commit()
        return False

    def run(self):
        """
        Main worker loop - tracks all TS trades needing post-close analysis
        """
        logger.info("🚀 Post-Close Tracker Worker started")

        db = ScopedSession()
        try:
            # Get trades needing tracking
            trades = self.get_trades_needing_tracking(db)

            if not trades:
                logger.debug("No trades need post-close tracking right now")
                return

            # Track each trade
            completed = 0
            ongoing = 0
            for trade in trades:
                try:
                    is_complete = self.track_single_trade(db, trade)
                    if is_complete:
                        completed += 1
                    else:
                        ongoing += 1

                except Exception as e:
                    logger.error(f"Error tracking trade #{trade.ticket}: {e}")
                    continue

            logger.info(
                f"📊 Post-close tracking: {completed} completed, {ongoing} ongoing"
            )

        except Exception as e:
            logger.error(f"Error in post-close tracker: {e}")
        finally:
            db.close()


def run_post_close_tracker():
    """Entry point for worker"""
    tracker = PostCloseTracker()
    tracker.run()


if __name__ == '__main__':
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Run once for testing
    run_post_close_tracker()
