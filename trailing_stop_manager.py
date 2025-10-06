#!/usr/bin/env python3
"""
Smart Trailing Stop Manager for ngTradingBot
Implements multi-stage trailing stop strategy with break-even protection
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from models import Trade, Command, GlobalSettings, Tick
from database import ScopedSession

logger = logging.getLogger(__name__)


class TrailingStopManager:
    """
    Smart trailing stop with multiple stages:

    Stage 1: Break-Even Move
    - When profit reaches X% of TP distance, move SL to entry (break-even + spread)

    Stage 2: Partial Trailing
    - When profit reaches Y% of TP distance, start trailing with wider distance

    Stage 3: Aggressive Trailing
    - When profit reaches Z% of TP distance, tighten trailing distance

    Stage 4: Near TP Protection
    - When very close to TP, aggressive trailing to lock in maximum profit
    """

    def __init__(self):
        self.redis = None  # Will be set by app.py if needed

        # Default settings (can be overridden by GlobalSettings)
        self.default_settings = {
            'trailing_stop_enabled': True,

            # Stage 1: Break-even
            'breakeven_enabled': True,
            'breakeven_trigger_percent': 30.0,  # Move to BE at 30% of TP distance
            'breakeven_offset_points': 5.0,     # Offset above/below entry (covers spread)

            # Stage 2: Partial trailing
            'partial_trailing_trigger_percent': 50.0,  # Start at 50% of TP distance
            'partial_trailing_distance_percent': 40.0,  # Trail 40% behind current price

            # Stage 3: Aggressive trailing
            'aggressive_trailing_trigger_percent': 75.0,  # Start at 75% of TP distance
            'aggressive_trailing_distance_percent': 25.0,  # Trail 25% behind current price

            # Stage 4: Near TP protection
            'near_tp_trigger_percent': 90.0,    # Start at 90% of TP distance
            'near_tp_trailing_distance_percent': 15.0,  # Trail 15% behind current price

            # Safety settings
            'min_sl_distance_points': 10.0,     # Never set SL closer than this
            'max_sl_move_per_update': 100.0,    # Max points SL can move in one update
            'trailing_update_interval': 5,       # Only update every 5 seconds per trade
        }

        # Track last trailing stop update time per trade
        self.last_update_time = {}

    def _load_settings(self, db: Session) -> Dict:
        """Load trailing stop settings from database or use defaults"""
        try:
            settings = GlobalSettings.get_settings(db)

            # Merge with defaults
            result = self.default_settings.copy()

            # Override with database settings if they exist
            if hasattr(settings, 'trailing_stop_enabled'):
                result['trailing_stop_enabled'] = settings.trailing_stop_enabled
            if hasattr(settings, 'breakeven_trigger_percent'):
                result['breakeven_trigger_percent'] = float(settings.breakeven_trigger_percent)
            if hasattr(settings, 'partial_trailing_trigger_percent'):
                result['partial_trailing_trigger_percent'] = float(settings.partial_trailing_trigger_percent)

            return result

        except Exception as e:
            logger.warning(f"Could not load trailing stop settings, using defaults: {e}")
            return self.default_settings

    def should_update_trailing_stop(self, trade: Trade) -> bool:
        """Check if enough time has passed since last update"""
        now = datetime.utcnow()
        last_update = self.last_update_time.get(trade.ticket)

        if not last_update:
            return True

        interval = self.default_settings['trailing_update_interval']
        elapsed = (now - last_update).total_seconds()

        return elapsed >= interval

    def calculate_trailing_stop(
        self,
        trade: Trade,
        current_price: float,
        settings: Dict
    ) -> Optional[Dict]:
        """
        Calculate new trailing stop level based on current price and profit

        Returns:
            Dict with 'new_sl', 'stage', 'reason' or None if no adjustment needed
        """
        try:
            if not settings.get('trailing_stop_enabled', True):
                return None

            # Determine direction
            is_buy = trade.direction.upper() in ['BUY', '0'] if isinstance(trade.direction, str) else trade.direction == 0

            # Get entry, SL, TP
            entry_price = float(trade.open_price)
            current_sl = float(trade.sl) if trade.sl else None
            tp_price = float(trade.tp) if trade.tp else None

            if not tp_price:
                logger.debug(f"Trade {trade.ticket} has no TP, skipping trailing stop")
                return None

            if not current_sl:
                logger.debug(f"Trade {trade.ticket} has no SL, skipping trailing stop")
                return None

            # Calculate distances
            if is_buy:
                # BUY trade
                tp_distance = tp_price - entry_price
                current_profit_distance = current_price - entry_price
                sl_distance = current_price - current_sl
            else:
                # SELL trade
                tp_distance = entry_price - tp_price
                current_profit_distance = entry_price - current_price
                sl_distance = current_sl - current_price

            # Calculate profit as percentage of TP distance
            profit_percent = (current_profit_distance / tp_distance * 100) if tp_distance > 0 else 0

            logger.debug(
                f"Trade {trade.ticket} ({trade.symbol}): "
                f"Profit {profit_percent:.1f}% of TP distance, "
                f"Current SL distance: {sl_distance:.5f}"
            )

            # Determine which stage to apply
            new_sl = None
            stage = None
            reason = None

            # Stage 4: Near TP Protection (highest priority)
            if profit_percent >= settings['near_tp_trigger_percent']:
                new_sl, reason = self._calculate_near_tp_protection(
                    is_buy, current_price, tp_distance, settings
                )
                stage = "near_tp"

            # Stage 3: Aggressive Trailing
            elif profit_percent >= settings['aggressive_trailing_trigger_percent']:
                new_sl, reason = self._calculate_aggressive_trailing(
                    is_buy, current_price, tp_distance, settings
                )
                stage = "aggressive"

            # Stage 2: Partial Trailing
            elif profit_percent >= settings['partial_trailing_trigger_percent']:
                new_sl, reason = self._calculate_partial_trailing(
                    is_buy, current_price, tp_distance, settings
                )
                stage = "partial"

            # Stage 1: Break-even
            elif settings.get('breakeven_enabled') and profit_percent >= settings['breakeven_trigger_percent']:
                new_sl, reason = self._calculate_breakeven(
                    is_buy, entry_price, settings
                )
                stage = "breakeven"

            # No stage triggered
            if not new_sl:
                return None

            # Validate new SL
            if not self._validate_new_sl(is_buy, new_sl, current_sl, current_price, settings):
                return None

            # Check if SL actually needs to move
            sl_change = abs(new_sl - current_sl)
            if sl_change < 0.00001:  # Less than 0.1 pip
                return None

            # Only move SL in profit direction (never worse)
            if is_buy:
                if new_sl <= current_sl:
                    return None  # Don't move SL down
            else:
                if new_sl >= current_sl:
                    return None  # Don't move SL up

            logger.info(
                f"🎯 Trailing Stop [{stage.upper()}]: Trade {trade.ticket} ({trade.symbol}) - "
                f"Moving SL from {current_sl:.5f} to {new_sl:.5f} ({reason})"
            )

            return {
                'new_sl': round(new_sl, 5),
                'stage': stage,
                'reason': reason,
                'profit_percent': round(profit_percent, 1)
            }

        except Exception as e:
            logger.error(f"Error calculating trailing stop for trade {trade.ticket}: {e}")
            return None

    def _calculate_breakeven(
        self,
        is_buy: bool,
        entry_price: float,
        settings: Dict
    ) -> Tuple[float, str]:
        """Calculate break-even SL"""
        offset = settings['breakeven_offset_points'] * 0.00001  # Convert points to price

        if is_buy:
            new_sl = entry_price + offset  # Slightly above entry
        else:
            new_sl = entry_price - offset  # Slightly below entry

        return new_sl, f"Break-even + {settings['breakeven_offset_points']} points"

    def _calculate_partial_trailing(
        self,
        is_buy: bool,
        current_price: float,
        tp_distance: float,
        settings: Dict
    ) -> Tuple[float, str]:
        """Calculate partial trailing SL"""
        trail_distance = tp_distance * (settings['partial_trailing_distance_percent'] / 100)

        if is_buy:
            new_sl = current_price - trail_distance
        else:
            new_sl = current_price + trail_distance

        return new_sl, f"Partial trail {settings['partial_trailing_distance_percent']}%"

    def _calculate_aggressive_trailing(
        self,
        is_buy: bool,
        current_price: float,
        tp_distance: float,
        settings: Dict
    ) -> Tuple[float, str]:
        """Calculate aggressive trailing SL"""
        trail_distance = tp_distance * (settings['aggressive_trailing_distance_percent'] / 100)

        if is_buy:
            new_sl = current_price - trail_distance
        else:
            new_sl = current_price + trail_distance

        return new_sl, f"Aggressive trail {settings['aggressive_trailing_distance_percent']}%"

    def _calculate_near_tp_protection(
        self,
        is_buy: bool,
        current_price: float,
        tp_distance: float,
        settings: Dict
    ) -> Tuple[float, str]:
        """Calculate near-TP protection SL"""
        trail_distance = tp_distance * (settings['near_tp_trailing_distance_percent'] / 100)

        if is_buy:
            new_sl = current_price - trail_distance
        else:
            new_sl = current_price + trail_distance

        return new_sl, f"Near-TP protection {settings['near_tp_trailing_distance_percent']}%"

    def _validate_new_sl(
        self,
        is_buy: bool,
        new_sl: float,
        current_sl: float,
        current_price: float,
        settings: Dict
    ) -> bool:
        """Validate that new SL is safe and makes sense"""

        # Check minimum distance from current price
        min_distance = settings['min_sl_distance_points'] * 0.00001
        actual_distance = abs(new_sl - current_price)

        if actual_distance < min_distance:
            logger.debug(f"New SL too close to price ({actual_distance:.5f} < {min_distance:.5f})")
            return False

        # Check max movement per update
        max_move = settings['max_sl_move_per_update'] * 0.00001
        sl_movement = abs(new_sl - current_sl)

        if sl_movement > max_move:
            logger.warning(f"SL movement too large ({sl_movement:.5f} > {max_move:.5f})")
            return False

        # Ensure SL is on correct side of price
        if is_buy:
            if new_sl >= current_price:
                logger.warning(f"Invalid BUY SL: {new_sl:.5f} >= {current_price:.5f}")
                return False
        else:
            if new_sl <= current_price:
                logger.warning(f"Invalid SELL SL: {new_sl:.5f} <= {current_price:.5f}")
                return False

        return True

    def send_sl_modify_command(
        self,
        db: Session,
        trade: Trade,
        new_sl: float,
        reason: str
    ) -> bool:
        """
        Send command to MT5 EA to modify stop loss

        Returns:
            True if command created successfully
        """
        try:
            # Create modify command
            command = Command(
                account_id=trade.account_id,
                command_type='modify_sl',
                ticket=trade.ticket,
                symbol=trade.symbol,
                sl=Decimal(str(new_sl)),
                status='pending',
                created_at=datetime.utcnow(),
                metadata={
                    'trailing_stop': True,
                    'reason': reason,
                    'old_sl': float(trade.sl) if trade.sl else None
                }
            )

            db.add(command)
            db.commit()

            # Update last update time
            self.last_update_time[trade.ticket] = datetime.utcnow()

            logger.info(
                f"✅ SL Modify command created: Ticket {trade.ticket} → "
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
        Process a single trade for trailing stop adjustment

        Returns:
            Dict with result info or None if no action taken
        """
        try:
            # Check if update is needed (rate limiting)
            if not self.should_update_trailing_stop(trade):
                return None

            # Load settings
            settings = self._load_settings(db)

            # Calculate new trailing stop
            result = self.calculate_trailing_stop(trade, current_price, settings)

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
                    'stage': result['stage'],
                    'old_sl': float(trade.sl),
                    'new_sl': result['new_sl'],
                    'reason': result['reason'],
                    'profit_percent': result['profit_percent']
                }

            return None

        except Exception as e:
            logger.error(f"Error processing trade {trade.ticket} for trailing stop: {e}")
            return None


# Singleton instance
_manager = None


def get_trailing_stop_manager():
    """Get or create trailing stop manager instance"""
    global _manager
    if _manager is None:
        _manager = TrailingStopManager()
    return _manager
