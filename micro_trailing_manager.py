#!/usr/bin/env python3
"""
Micro-Trailing Stop Manager
Implements continuous, small-step trailing even for small profits

This complements the existing multi-stage trailing stop by:
- Starting IMMEDIATELY when trade goes into profit (no 30% wait)
- Moving SL in SMALL increments (1-5 points at a time)
- Protecting EVERY point of profit gain
- Perfect for volatile assets like BTCUSD

Philosophy: "Lock in profit continuously, not just at stages"
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session

from models import Trade, Command, BrokerSymbol, Tick
from database import ScopedSession

logger = logging.getLogger(__name__)


class MicroTrailingManager:
    """
    Continuous micro-trailing stop manager

    Moves SL in tiny increments to protect every bit of profit
    """

    def __init__(self):
        # Micro-trailing settings per symbol
        self.symbol_config = {
            'BTCUSD': {
                'min_profit_to_start': 50.0,      # Start trailing after 50 points profit
                'trailing_step_points': 100.0,     # Move SL every 100 points
                'trailing_distance_points': 200.0, # Keep SL 200 points behind price
                'point_value': 0.01,               # BTC point size
            },
            'ETHUSD': {
                'min_profit_to_start': 20.0,
                'trailing_step_points': 50.0,
                'trailing_distance_points': 100.0,
                'point_value': 0.01,
            },
            'XAUUSD': {
                'min_profit_to_start': 5.0,        # Gold: start after $5 profit
                'trailing_step_points': 10.0,      # Move every $10
                'trailing_distance_points': 20.0,  # Keep $20 behind
                'point_value': 0.01,
            },
            'DE40.c': {
                'min_profit_to_start': 20.0,
                'trailing_step_points': 50.0,
                'trailing_distance_points': 100.0,
                'point_value': 1.0,
            },
            'EURUSD': {
                'min_profit_to_start': 0.0010,     # 10 pips
                'trailing_step_points': 10.0,      # Move every 10 pips
                'trailing_distance_points': 15.0,  # Keep 15 pips behind
                'point_value': 0.00001,
            },
            'GBPUSD': {
                'min_profit_to_start': 0.0010,
                'trailing_step_points': 10.0,
                'trailing_distance_points': 15.0,
                'point_value': 0.00001,
            },
            'USDJPY': {
                'min_profit_to_start': 0.010,      # 10 pips
                'trailing_step_points': 10.0,
                'trailing_distance_points': 15.0,
                'point_value': 0.001,
            },
        }

        # Default config for unlisted symbols
        self.default_config = {
            'min_profit_to_start': 10.0,
            'trailing_step_points': 10.0,
            'trailing_distance_points': 20.0,
            'point_value': 0.00001,
        }

        # Track last SL values to detect when to move
        self.last_sl_values = {}

    def get_config(self, symbol: str) -> Dict:
        """Get micro-trailing config for symbol"""
        return self.symbol_config.get(symbol, self.default_config)

    def calculate_micro_trailing_stop(
        self,
        trade: Trade,
        current_price: float,
        db: Session
    ) -> Optional[Dict]:
        """
        Calculate new SL using micro-trailing logic

        Returns:
            Dict with 'new_sl', 'reason' or None if no adjustment needed
        """
        try:
            # Get configuration
            config = self.get_config(trade.symbol)

            # Determine direction
            is_buy = trade.direction.upper() in ['BUY', 'BUY', '0']

            # Get trade info
            entry_price = float(trade.open_price)
            current_sl = float(trade.sl) if trade.sl else None

            if not current_sl:
                logger.debug(f"Trade {trade.ticket} has no SL, skipping micro-trailing")
                return None

            # Calculate current profit in price points
            if is_buy:
                profit_distance = current_price - entry_price
            else:
                profit_distance = entry_price - current_price

            # Check if we have minimum profit to start trailing
            if profit_distance < config['min_profit_to_start']:
                logger.debug(
                    f"Trade {trade.ticket}: Profit {profit_distance:.2f} < "
                    f"min {config['min_profit_to_start']:.2f} - not trailing yet"
                )
                return None

            # Calculate new trailing SL
            trailing_distance = config['trailing_distance_points'] * config['point_value']

            if is_buy:
                # BUY: SL below current price
                new_sl = current_price - trailing_distance

                # Only move SL UP (never down)
                if new_sl <= current_sl:
                    return None

            else:
                # SELL: SL above current price
                new_sl = current_price + trailing_distance

                # Only move SL DOWN (never up)
                if new_sl >= current_sl:
                    return None

            # Check if movement is significant enough (at least 1 step)
            sl_move_points = abs(new_sl - current_sl) / config['point_value']

            if sl_move_points < config['trailing_step_points']:
                logger.debug(
                    f"Trade {trade.ticket}: SL move {sl_move_points:.1f} points < "
                    f"step {config['trailing_step_points']:.1f} - not moving yet"
                )
                return None

            # Validate new SL is safe
            min_distance = 10 * config['point_value']  # At least 10 points from price
            actual_distance = abs(new_sl - current_price)

            if actual_distance < min_distance:
                logger.warning(
                    f"Trade {trade.ticket}: New SL too close to price "
                    f"({actual_distance:.5f} < {min_distance:.5f})"
                )
                return None

            # Ensure SL is on correct side of price
            if is_buy and new_sl >= current_price:
                logger.warning(f"Invalid BUY SL: {new_sl:.5f} >= {current_price:.5f}")
                return None
            if not is_buy and new_sl <= current_price:
                logger.warning(f"Invalid SELL SL: {new_sl:.5f} <= {current_price:.5f}")
                return None

            # Calculate protected profit
            if is_buy:
                protected_profit = new_sl - entry_price
            else:
                protected_profit = entry_price - new_sl

            logger.info(
                f"🔥 MICRO-TRAILING: Trade {trade.ticket} ({trade.symbol}) - "
                f"Moving SL from {current_sl:.5f} to {new_sl:.5f} "
                f"(moved {sl_move_points:.1f} points, protecting {protected_profit:.2f} profit)"
            )

            return {
                'new_sl': round(new_sl, 5),
                'reason': f'Micro-trail: moved {sl_move_points:.1f} points',
                'protected_profit': protected_profit,
                'trailing_distance': trailing_distance
            }

        except Exception as e:
            logger.error(f"Error calculating micro-trailing for trade {trade.ticket}: {e}")
            return None

    def send_sl_modify_command(
        self,
        db: Session,
        trade: Trade,
        new_sl: float,
        reason: str
    ) -> bool:
        """Send command to MT5 EA to modify stop loss"""
        try:
            import uuid
            command = Command(
                id=str(uuid.uuid4()),
                account_id=trade.account_id,
                command_type='MODIFY_TRADE',
                status='pending',
                created_at=datetime.utcnow(),
                payload={
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'sl': float(new_sl),
                    'tp': float(trade.tp) if trade.tp else 0.0,
                }
            )

            db.add(command)
            db.commit()

            logger.info(
                f"✅ Micro-Trail SL Modify command created: Ticket {trade.ticket} → "
                f"New SL {new_sl:.5f} ({reason})"
            )

            return True

        except Exception as e:
            logger.error(f"Error creating SL modify command: {e}")
            db.rollback()
            return False

    def process_trade(
        self,
        db: Session,
        trade: Trade,
        current_price: float
    ) -> Optional[Dict]:
        """
        Process a single trade for micro-trailing stop adjustment

        Returns:
            Dict with result info or None if no action taken
        """
        try:
            result = self.calculate_micro_trailing_stop(trade, current_price, db)

            if not result:
                return None

            # Send modify command
            success = self.send_sl_modify_command(
                db=db,
                trade=trade,
                new_sl=result['new_sl'],
                reason=result['reason']
            )

            if success:
                return {
                    'ticket': trade.ticket,
                    'symbol': trade.symbol,
                    'old_sl': float(trade.sl),
                    'new_sl': result['new_sl'],
                    'reason': result['reason'],
                    'protected_profit': result.get('protected_profit', 0)
                }

            return None

        except Exception as e:
            logger.error(f"Error processing trade {trade.ticket} for micro-trailing: {e}")
            return None

    def process_all_open_trades(self, db: Session) -> Dict:
        """
        Process all open trades for micro-trailing

        Returns:
            Dict with statistics
        """
        stats = {
            'total_trades': 0,
            'trailed': 0,
            'errors': 0
        }

        try:
            # Get all open trades
            open_trades = db.query(Trade).filter_by(status='open').all()
            stats['total_trades'] = len(open_trades)

            if not open_trades:
                return stats

            # Get current prices from ticks
            from models import Tick

            for trade in open_trades:
                try:
                    # Get latest tick for current price
                    latest_tick = db.query(Tick).filter_by(
                        account_id=trade.account_id,
                        symbol=trade.symbol
                    ).order_by(Tick.timestamp.desc()).first()

                    if not latest_tick:
                        continue

                    # Use bid for BUY (closing at bid), ask for SELL (closing at ask)
                    is_buy = trade.direction.upper() in ['BUY', 'BUY', '0']
                    current_price = float(latest_tick.bid if is_buy else latest_tick.ask)

                    # Process trade
                    result = self.process_trade(db, trade, current_price)

                    if result:
                        stats['trailed'] += 1
                        logger.info(
                            f"✅ Micro-trailed {result['symbol']} #{result['ticket']}: "
                            f"{result['old_sl']:.5f} → {result['new_sl']:.5f}"
                        )

                except Exception as e:
                    logger.error(f"Error processing trade {trade.ticket}: {e}")
                    stats['errors'] += 1
                    continue

            return stats

        except Exception as e:
            logger.error(f"Error in process_all_open_trades: {e}")
            stats['errors'] += 1
            return stats


# Singleton instance
_manager = None


def get_micro_trailing_manager():
    """Get or create micro-trailing manager instance"""
    global _manager
    if _manager is None:
        _manager = MicroTrailingManager()
    return _manager


# Convenience function
def apply_micro_trailing_to_all():
    """Apply micro-trailing to all open trades"""
    db = ScopedSession()
    try:
        manager = get_micro_trailing_manager()
        stats = manager.process_all_open_trades(db)
        logger.info(
            f"Micro-trailing run: {stats['trailed']}/{stats['total_trades']} trades adjusted, "
            f"{stats['errors']} errors"
        )
        return stats
    finally:
        db.close()
