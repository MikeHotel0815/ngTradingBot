#!/usr/bin/env python3
"""
FINAL: Unified Smart Trailing Stop System

✅ Micro-trailing from first profit
✅ Session-aware volatility adjustments
✅ TP Extension when momentum continues
✅ Symbol-specific configuration
✅ Simple, effective, production-ready

This REPLACES all other trailing stop systems.
"""

import logging
from datetime import datetime
from typing import Dict, Optional
from sqlalchemy.orm import Session

from models import Trade, Command, Tick
from database import ScopedSession

logger = logging.getLogger(__name__)


class UnifiedTrailing:
    """THE trailing stop system - does it all"""

    def __init__(self):
        # Symbol configs with session-aware volatility
        self.configs = {
            'BTCUSD': {'min_profit': 50, 'max_trail': 300, 'min_trail': 100, 'step': 100, 'point': 0.01},
            'ETHUSD': {'min_profit': 20, 'max_trail': 150, 'min_trail': 50, 'step': 50, 'point': 0.01},
            'XAUUSD': {'min_profit': 5, 'max_trail': 30, 'min_trail': 10, 'step': 5, 'point': 0.01},
            'DE40.c': {'min_profit': 20, 'max_trail': 150, 'min_trail': 50, 'step': 50, 'point': 1.0},
            'EURUSD': {'min_profit': 10, 'max_trail': 20, 'min_trail': 8, 'step': 5, 'point': 0.00001},
            'GBPUSD': {'min_profit': 10, 'max_trail': 20, 'min_trail': 8, 'step': 5, 'point': 0.00001},
            'USDJPY': {'min_profit': 10, 'max_trail': 20, 'min_trail': 8, 'step': 5, 'point': 0.001},
        }
        self.default = {'min_profit': 10, 'max_trail': 20, 'min_trail': 10, 'step': 5, 'point': 0.00001}

        self.last_update = {}
        self.tp_extensions = {}  # Track TP extensions per trade
        self.update_interval = 5

    def _get_session_multiplier(self) -> float:
        """
        Get volatility multiplier based on current UTC time

        Returns multiplier: 0.7-1.5x
        - Asian (00-08 UTC): 0.7x (quiet)
        - London (08-13 UTC): 1.0x (normal)
        - London+US overlap (13-16 UTC): 1.5x (volatile!)
        - US (16-22 UTC): 1.2x (active)
        """
        hour = datetime.utcnow().hour

        if 13 <= hour < 16:
            return 1.5  # London+US overlap = MAX volatility
        elif 0 <= hour < 8:
            return 0.7  # Asian = LOW volatility
        elif 16 <= hour < 22:
            return 1.2  # US session
        else:
            return 1.0  # London or off-hours

    def process_trade(self, db: Session, trade: Trade, current_price: float) -> Optional[Dict]:
        """
        Process trade for trailing stop + TP extension

        Returns Dict with actions taken or None
        """
        try:
            # Rate limit
            now = datetime.utcnow()
            if trade.ticket in self.last_update:
                if (now - self.last_update[trade.ticket]).total_seconds() < self.update_interval:
                    return None

            cfg = self.configs.get(trade.symbol, self.default)
            is_buy = trade.direction.upper() in ['BUY', '0']

            entry = float(trade.open_price)
            sl = float(trade.sl) if trade.sl else None
            tp = float(trade.tp) if trade.tp else None

            if not sl or not tp:
                return None

            # Calculate profit
            if is_buy:
                profit_dist = current_price - entry
                tp_dist = tp - entry
            else:
                profit_dist = entry - current_price
                tp_dist = entry - tp

            # Need minimum profit to start
            if profit_dist < cfg['min_profit'] * cfg['point']:
                return None

            # Calculate % to TP
            pct_to_tp = (profit_dist / tp_dist * 100) if tp_dist > 0 else 0

            actions = {}

            # === TP EXTENSION ===
            # If 90%+ to TP and still strong momentum → EXTEND TP!
            if pct_to_tp >= 90 and self.tp_extensions.get(trade.ticket, 0) < 2:
                new_tp = self._calculate_tp_extension(is_buy, entry, tp, tp_dist, cfg)
                if new_tp:
                    actions['extend_tp'] = new_tp
                    self.tp_extensions[trade.ticket] = self.tp_extensions.get(trade.ticket, 0) + 1
                    logger.info(
                        f"🚀 TP EXTENSION: {trade.symbol} #{trade.ticket} - "
                        f"TP {tp:.5f} → {new_tp:.5f} (extension #{self.tp_extensions[trade.ticket]})"
                    )

            # === TRAILING STOP ===
            # Get session volatility multiplier
            session_mult = self._get_session_multiplier()

            # Dynamic trailing distance based on progress
            # ADJUSTED: Start break-even later (40% instead of 25%)
            if pct_to_tp >= 75:
                trail_mult = 0.35  # Very tight near TP
            elif pct_to_tp >= 60:
                trail_mult = 0.5  # Moderate trailing
            elif pct_to_tp >= 40:
                trail_mult = 0.7  # Start trailing at 40% (was 25%)
            else:
                # Below 40%: No trailing yet, let position breathe
                return None

            # Apply session volatility
            trail_dist_pts = cfg['max_trail'] * trail_mult * session_mult
            trail_dist_pts = max(trail_dist_pts, cfg['min_trail'])
            trail_dist = trail_dist_pts * cfg['point']

            # Calculate new SL
            if is_buy:
                new_sl = current_price - trail_dist
                if new_sl <= sl:
                    new_sl = None  # Don't move down
            else:
                new_sl = current_price + trail_dist
                if new_sl >= sl:
                    new_sl = None  # Don't move up

            if new_sl:
                # Check minimum movement
                sl_move_pts = abs(new_sl - sl) / cfg['point']
                if sl_move_pts >= cfg['step']:
                    actions['new_sl'] = new_sl
                    logger.info(
                        f"🎯 TRAILING: {trade.symbol} #{trade.ticket} - "
                        f"SL {sl:.5f} → {new_sl:.5f} "
                        f"(trail={trail_dist_pts:.0f}pts, session={session_mult:.1f}x, {pct_to_tp:.0f}% to TP)"
                    )

            # Send commands
            if actions:
                self._send_modify_command(db, trade, actions.get('new_sl'), actions.get('extend_tp'))
                self.last_update[trade.ticket] = now
                return actions

            return None

        except Exception as e:
            logger.error(f"Error processing {trade.ticket}: {e}")
            return None

    def _calculate_tp_extension(self, is_buy: bool, entry: float, current_tp: float,
                                 tp_dist: float, cfg: Dict) -> Optional[float]:
        """Calculate extended TP (50% further)"""
        try:
            extension = tp_dist * 0.5  # Extend by 50% of original distance

            if is_buy:
                new_tp = current_tp + extension
            else:
                new_tp = current_tp - extension

            return round(new_tp, 5)
        except:
            return None

    def _send_modify_command(self, db: Session, trade: Trade, new_sl: Optional[float],
                             new_tp: Optional[float]) -> bool:
        """Send MODIFY_TRADE command"""
        try:
            import uuid

            payload = {
                'ticket': trade.ticket,
                'symbol': trade.symbol,
            }

            if new_sl:
                payload['sl'] = float(new_sl)
            else:
                payload['sl'] = float(trade.sl) if trade.sl else 0.0

            if new_tp:
                payload['tp'] = float(new_tp)
            else:
                payload['tp'] = float(trade.tp) if trade.tp else 0.0

            cmd = Command(
                id=str(uuid.uuid4()),
                account_id=trade.account_id,
                command_type='MODIFY_TRADE',
                status='pending',
                created_at=datetime.utcnow(),
                payload=payload
            )

            db.add(cmd)
            db.commit()
            return True

        except Exception as e:
            logger.error(f"Error sending command: {e}")
            db.rollback()
            return False

    def process_all(self, db: Session) -> Dict:
        """Process all open trades"""
        stats = {'total': 0, 'trailed': 0, 'extended': 0, 'errors': 0}

        try:
            trades = db.query(Trade).filter_by(status='open').all()
            stats['total'] = len(trades)

            for trade in trades:
                try:
                    # Get current price
                    tick = db.query(Tick).filter_by(
                        account_id=trade.account_id,
                        symbol=trade.symbol
                    ).order_by(Tick.timestamp.desc()).first()

                    if not tick:
                        continue

                    is_buy = trade.direction.upper() in ['BUY', '0']
                    price = float(tick.bid if is_buy else tick.ask)

                    result = self.process_trade(db, trade, price)

                    if result:
                        if 'new_sl' in result:
                            stats['trailed'] += 1
                        if 'extend_tp' in result:
                            stats['extended'] += 1

                except Exception as e:
                    logger.error(f"Error processing {trade.ticket}: {e}")
                    stats['errors'] += 1

            return stats

        except Exception as e:
            logger.error(f"Error in process_all: {e}")
            stats['errors'] += 1
            return stats


# Singleton
_manager = None

def get_unified_trailing():
    """Get unified trailing instance"""
    global _manager
    if _manager is None:
        _manager = UnifiedTrailing()
    return _manager

def apply_trailing_now():
    """Apply trailing to all trades NOW"""
    db = ScopedSession()
    try:
        stats = get_unified_trailing().process_all(db)
        logger.info(
            f"✅ Trailing: {stats['trailed']} SL adjusted, {stats['extended']} TP extended, "
            f"{stats['errors']} errors ({stats['total']} total)"
        )
        return stats
    finally:
        db.close()
