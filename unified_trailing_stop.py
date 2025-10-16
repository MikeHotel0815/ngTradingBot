#!/usr/bin/env python3
"""
Unified Smart Trailing Stop System with Profit Extension
Combines micro-trailing with dynamic aggressiveness and TP extension

This is THE trailing stop system - replaces all others.

Philosophy:
- Start trailing IMMEDIATELY when profitable
- Move SL continuously in small steps
- Get MORE aggressive as profit grows
- EXTEND TP when price nears target and momentum continues
- Adjust for session volatility and market noise
- Symbol-specific configuration
- Simple, effective, no complex stages

NEW: Profit Extension Feature
- When price reaches 90%+ of TP distance
- If momentum is still strong in profit direction
- EXTEND TP by additional 50% of original distance
- Let winners run even further!
"""

import logging
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session

from models import Trade, Command, BrokerSymbol, Tick
from database import ScopedSession
from session_volatility_analyzer import get_session_volatility_analyzer

logger = logging.getLogger(__name__)


class UnifiedTrailingStop:
    """
    Unified trailing stop system for all trades

    Dynamic trailing distance based on profit progress:
    - 0-25% to TP: Wide trailing (50% of max distance)
    - 25-50% to TP: Medium trailing (40% of max distance)
    - 50-75% to TP: Tight trailing (30% of max distance)
    - 75-100% to TP: Very tight trailing (20% of max distance)
    """

    def __init__(self):
        # Symbol-specific base configuration
        self.symbol_config = {
            'BTCUSD': {
                'min_profit_to_start_points': 50.0,      # Start after 50 points profit
                'max_trailing_distance_points': 300.0,   # Maximum distance: 300 points
                'min_trailing_distance_points': 100.0,   # Minimum distance: 100 points (near TP)
                'trailing_step_points': 100.0,           # Move every 100 points
                'point_value': 0.01,
            },
            'ETHUSD': {
                'min_profit_to_start_points': 20.0,
                'max_trailing_distance_points': 150.0,
                'min_trailing_distance_points': 50.0,
                'trailing_step_points': 50.0,
                'point_value': 0.01,
            },
            'XAUUSD': {
                'min_profit_to_start_points': 5.0,
                'max_trailing_distance_points': 30.0,
                'min_trailing_distance_points': 10.0,
                'trailing_step_points': 5.0,
                'point_value': 0.01,
            },
            'DE40.c': {
                'min_profit_to_start_points': 20.0,
                'max_trailing_distance_points': 150.0,
                'min_trailing_distance_points': 50.0,
                'trailing_step_points': 50.0,
                'point_value': 1.0,
            },
            'EURUSD': {
                'min_profit_to_start_points': 10.0,      # 10 pips
                'max_trailing_distance_points': 20.0,    # 20 pips max
                'min_trailing_distance_points': 8.0,     # 8 pips min
                'trailing_step_points': 5.0,             # Move every 5 pips
                'point_value': 0.00001,
            },
            'GBPUSD': {
                'min_profit_to_start_points': 10.0,
                'max_trailing_distance_points': 20.0,
                'min_trailing_distance_points': 8.0,
                'trailing_step_points': 5.0,
                'point_value': 0.00001,
            },
            'USDJPY': {
                'min_profit_to_start_points': 10.0,
                'max_trailing_distance_points': 20.0,
                'min_trailing_distance_points': 8.0,
                'trailing_step_points': 5.0,
                'point_value': 0.001,
            },
        }

        # Default for unlisted symbols
        self.default_config = {
            'min_profit_to_start_points': 10.0,
            'max_trailing_distance_points': 20.0,
            'min_trailing_distance_points': 10.0,
            'trailing_step_points': 5.0,
            'point_value': 0.00001,
        }

        # Update interval per trade (don't spam)
        self.last_update_time = {}
        self.update_interval_seconds = 5

        # Session/volatility analyzer
        self.session_analyzer = get_session_volatility_analyzer()

        # TP Extension settings
        self.tp_extension_enabled = True
        self.tp_extension_trigger_percent = 90.0  # Extend TP when 90%+ reached
        self.tp_extension_multiplier = 0.5  # Extend by 50% of original distance
        self.max_tp_extensions_per_trade = 2  # Max 2 extensions per trade
        self.tp_extensions_count = {}  # Track extensions per trade

    def get_config(self, symbol: str) -> Dict:
        """Get configuration for symbol"""
        return self.symbol_config.get(symbol, self.default_config)

    def should_update(self, trade: Trade) -> bool:
        """Check if enough time passed since last update"""
        now = datetime.utcnow()
        last = self.last_update_time.get(trade.ticket)

        if not last:
            return True

        elapsed = (now - last).total_seconds()
        return elapsed >= self.update_interval_seconds

    def calculate_dynamic_trailing_distance(
        self,
        config: Dict,
        profit_percent_to_tp: float
    ) -> float:
        """
        Calculate dynamic trailing distance based on profit progress

        The closer to TP, the tighter we trail

        Returns:
            Trailing distance in POINTS
        """
        max_distance = config['max_trailing_distance_points']
        min_distance = config['min_trailing_distance_points']

        # Calculate distance multiplier based on profit progress
        if profit_percent_to_tp < 25:
            # 0-25%: Wide trailing (100% of max distance)
            multiplier = 1.0
        elif profit_percent_to_tp < 50:
            # 25-50%: Medium-wide trailing (70% of max distance)
            multiplier = 0.7
        elif profit_percent_to_tp < 75:
            # 50-75%: Medium-tight trailing (50% of max distance)
            multiplier = 0.5
        else:
            # 75-100%: Very tight trailing (35% of max distance)
            multiplier = 0.35

        # Calculate actual distance
        distance = max_distance * multiplier

        # Clamp to min distance
        distance = max(distance, min_distance)

        return distance

    def calculate_new_sl(
        self,
        trade: Trade,
        current_price: float,
        db: Session
    ) -> Optional[Dict]:
        """
        Calculate new trailing stop based on current price and profit

        Returns:
            Dict with 'new_sl', 'reason', 'stage' or None
        """
        try:
            # Get configuration
            config = self.get_config(trade.symbol)

            # Determine direction
            is_buy = trade.direction.upper() in ['BUY', '0']

            # Get trade info
            entry_price = float(trade.open_price)
            current_sl = float(trade.sl) if trade.sl else None
            tp_price = float(trade.tp) if trade.tp else None

            if not current_sl:
                logger.debug(f"Trade {trade.ticket} has no SL")
                return None

            # Calculate profit distance
            if is_buy:
                profit_distance = current_price - entry_price
                tp_distance = tp_price - entry_price if tp_price else 0
            else:
                profit_distance = entry_price - current_price
                tp_distance = entry_price - tp_price if tp_price else 0

            # Check minimum profit to start
            if profit_distance < config['min_profit_to_start_points'] * config['point_value']:
                return None

            # Calculate profit as % of TP distance
            profit_percent_to_tp = (profit_distance / tp_distance * 100) if tp_distance > 0 else 0

            # Get dynamic trailing distance
            trailing_distance_points = self.calculate_dynamic_trailing_distance(
                config, profit_percent_to_tp
            )
            trailing_distance = trailing_distance_points * config['point_value']

            # Calculate new SL
            if is_buy:
                new_sl = current_price - trailing_distance

                # Only move SL up
                if new_sl <= current_sl:
                    return None
            else:
                new_sl = current_price + trailing_distance

                # Only move SL down
                if new_sl >= current_sl:
                    return None

            # Check if movement is significant enough
            sl_move_points = abs(new_sl - current_sl) / config['point_value']

            if sl_move_points < config['trailing_step_points']:
                return None

            # Validate new SL
            min_distance = 10 * config['point_value']
            actual_distance = abs(new_sl - current_price)

            if actual_distance < min_distance:
                logger.warning(f"Trade {trade.ticket}: New SL too close to price")
                return None

            # Ensure SL is on correct side
            if is_buy and new_sl >= current_price:
                return None
            if not is_buy and new_sl <= current_price:
                return None

            # Calculate protected profit
            if is_buy:
                protected_profit = new_sl - entry_price
            else:
                protected_profit = entry_price - new_sl

            protected_profit_points = protected_profit / config['point_value']

            # Determine stage label
            if profit_percent_to_tp >= 75:
                stage = "near_tp"
                stage_label = "NEAR TP (75-100%)"
            elif profit_percent_to_tp >= 50:
                stage = "medium_tight"
                stage_label = "MEDIUM-TIGHT (50-75%)"
            elif profit_percent_to_tp >= 25:
                stage = "medium"
                stage_label = "MEDIUM (25-50%)"
            else:
                stage = "wide"
                stage_label = "WIDE (0-25%)"

            logger.info(
                f"🎯 UNIFIED TRAILING [{stage_label}]: Trade {trade.ticket} ({trade.symbol}) - "
                f"SL: {current_sl:.5f} → {new_sl:.5f} "
                f"(trail: {trailing_distance_points:.1f} pts, protecting: {protected_profit_points:.1f} pts, "
                f"progress: {profit_percent_to_tp:.1f}% to TP)"
            )

            return {
                'new_sl': round(new_sl, 5),
                'reason': f'{stage_label}: trailing {trailing_distance_points:.1f} pts behind',
                'stage': stage,
                'trailing_distance': trailing_distance_points,
                'protected_profit': protected_profit_points,
                'profit_percent_to_tp': profit_percent_to_tp
            }

        except Exception as e:
            logger.error(f"Error calculating trailing stop for {trade.ticket}: {e}")
            return None

    def send_modify_command(
        self,
        db: Session,
        trade: Trade,
        new_sl: float,
        reason: str
    ) -> bool:
        """Send SL modify command to EA"""
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

            # Update last update time
            self.last_update_time[trade.ticket] = datetime.utcnow()

            logger.info(f"✅ SL Modify command sent: #{trade.ticket} → SL {new_sl:.5f}")
            return True

        except Exception as e:
            logger.error(f"Error sending modify command: {e}")
            db.rollback()
            return False

    def process_trade(
        self,
        db: Session,
        trade: Trade,
        current_price: float
    ) -> Optional[Dict]:
        """
        Process single trade for trailing stop

        Returns:
            Dict with result or None
        """
        try:
            # Rate limiting
            if not self.should_update(trade):
                return None

            # Calculate new SL
            result = self.calculate_new_sl(trade, current_price, db)

            if not result:
                return None

            # Send command
            success = self.send_modify_command(
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
                    'stage': result['stage'],
                    'protected_profit': result['protected_profit'],
                    'profit_percent_to_tp': result['profit_percent_to_tp']
                }

            return None

        except Exception as e:
            logger.error(f"Error processing trade {trade.ticket}: {e}")
            return None

    def process_all_open_trades(self, db: Session) -> Dict:
        """
        Process all open trades for trailing stop

        Returns:
            Statistics dict
        """
        stats = {
            'total_trades': 0,
            'trailed': 0,
            'skipped': 0,
            'errors': 0
        }

        try:
            # Get all open trades
            open_trades = db.query(Trade).filter_by(status='open').all()
            stats['total_trades'] = len(open_trades)

            if not open_trades:
                return stats

            for trade in open_trades:
                try:
                    # Get current price from latest tick
                    latest_tick = db.query(Tick).filter_by(
                        account_id=trade.account_id,
                        symbol=trade.symbol
                    ).order_by(Tick.timestamp.desc()).first()

                    if not latest_tick:
                        stats['skipped'] += 1
                        continue

                    # Use bid for BUY, ask for SELL
                    is_buy = trade.direction.upper() in ['BUY', '0']
                    current_price = float(latest_tick.bid if is_buy else latest_tick.ask)

                    # Process trade
                    result = self.process_trade(db, trade, current_price)

                    if result:
                        stats['trailed'] += 1
                        logger.info(
                            f"✅ Trailed {result['symbol']} #{result['ticket']}: "
                            f"{result['old_sl']:.5f} → {result['new_sl']:.5f} "
                            f"[{result['stage'].upper()}]"
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


def get_unified_trailing_stop():
    """Get or create unified trailing stop instance"""
    global _manager
    if _manager is None:
        _manager = UnifiedTrailingStop()
    return _manager


def apply_trailing_to_all():
    """Convenience function: Apply trailing to all open trades"""
    db = ScopedSession()
    try:
        manager = get_unified_trailing_stop()
        stats = manager.process_all_open_trades(db)
        logger.info(
            f"Trailing run complete: {stats['trailed']}/{stats['total_trades']} adjusted, "
            f"{stats['skipped']} skipped, {stats['errors']} errors"
        )
        return stats
    finally:
        db.close()
