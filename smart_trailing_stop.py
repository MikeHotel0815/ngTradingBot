#!/usr/bin/env python3
"""
Smart Trailing Stop System with Market Noise Compensation
=========================================================

Goals:
1. Get trades out of loss zone ASAP → Quick break-even
2. Compensate for market noise → ATR-based buffer
3. Never create a loss with trailing stop
4. Adaptive to session volatility and trade progress

Key Features:
- ATR-based dynamic trail distance (adapts to current volatility)
- Aggressive break-even (locks profit early)
- Progressive tightening as trade moves to TP
- Session-aware multipliers
- Symbol-specific configurations
"""

import logging
from datetime import datetime
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session

from models import Trade, Command, Tick, OHLCData
from database import ScopedSession

logger = logging.getLogger(__name__)


class SmartTrailingStop:
    """
    Intelligent trailing stop with ATR-based noise compensation
    """

    def __init__(self):
        # Symbol-specific base configs
        # 🔧 OPTIMIZED 2025-11-03: Increased min_profit to prevent premature trailing in small profits
        self.configs = {
            'BTCUSD': {'min_profit_pts': 200, 'atr_period': 14, 'atr_multiplier': 1.5, 'point': 0.01},  # 100 → 200 ($2 profit min)
            'ETHUSD': {'min_profit_pts': 100, 'atr_period': 14, 'atr_multiplier': 1.5, 'point': 0.01},  # 50 → 100 ($1 profit min)
            'XAUUSD': {'min_profit_pts': 100, 'atr_period': 14, 'atr_multiplier': 1.0, 'point': 0.01},  # 10 → 100 ($1 profit min, was TOO LOW!)
            'DE40.c': {'min_profit_pts': 100, 'atr_period': 14, 'atr_multiplier': 1.8, 'point': 1.0},   # 30 → 100 (100pts profit min)
            'EURUSD': {'min_profit_pts': 15, 'atr_period': 14, 'atr_multiplier': 1.0, 'point': 0.00001},  # 5 → 15 (15 pips min)
            'GBPUSD': {'min_profit_pts': 15, 'atr_period': 14, 'atr_multiplier': 1.0, 'point': 0.00001},  # 5 → 15 (15 pips min)
            'USDJPY': {'min_profit_pts': 15, 'atr_period': 14, 'atr_multiplier': 1.0, 'point': 0.001},    # 5 → 15 (15 pips min)
            'US500.c': {'min_profit_pts': 25, 'atr_period': 14, 'atr_multiplier': 1.3, 'point': 0.01},    # 8 → 25 (25pts min)
        }
        self.default = {'min_profit_pts': 20, 'atr_period': 14, 'atr_multiplier': 1.0, 'point': 0.00001}  # 10 → 20

        self.last_update = {}
        self.update_interval = 5  # Seconds between updates
        self.tp_extensions = {}

    def _get_session_volatility_multiplier(self) -> float:
        """
        Session-aware volatility multiplier for trail distance
        
        Returns multiplier: 0.6-1.8x
        - Asian (00-08 UTC): 0.6x (very quiet - tighter trails OK)
        - London (08-13 UTC): 1.0x (normal)
        - Overlap (13-16 UTC): 1.8x (VERY volatile - wider trails needed!)
        - US (16-22 UTC): 1.3x (active)
        - Off-hours (22-00 UTC): 0.8x (quiet)
        """
        hour = datetime.utcnow().hour

        if 13 <= hour < 16:
            return 1.8  # London+US overlap = MAX volatility, wide trails
        elif 0 <= hour < 8:
            return 0.6  # Asian = LOW volatility, tight trails
        elif 16 <= hour < 22:
            return 1.3  # US session = active
        elif 22 <= hour < 24:
            return 0.8  # Late evening = quieter
        else:
            return 1.0  # London or default

    def _calculate_atr(self, db: Session, symbol: str, timeframe: str, period: int = 14) -> Optional[float]:
        """
        Calculate ATR (Average True Range) for market noise measurement
        
        ATR tells us how much "normal" price movement to expect.
        Trail distance should be > ATR to avoid noise-based stops.
        """
        try:
            # Get recent candles
            candles = db.query(OHLCData).filter(
                OHLCData.symbol == symbol,
                OHLCData.timeframe == timeframe
            ).order_by(OHLCData.timestamp.desc()).limit(period + 1).all()

            if len(candles) < period:
                logger.warning(f"Not enough candles for ATR calculation: {len(candles)}/{period}")
                return None

            # Calculate True Range for each candle
            true_ranges = []
            for i in range(len(candles) - 1):
                high = float(candles[i].high)
                low = float(candles[i].low)
                prev_close = float(candles[i + 1].close)
                
                tr = max(
                    high - low,
                    abs(high - prev_close),
                    abs(low - prev_close)
                )
                true_ranges.append(tr)

            # ATR = Average of True Ranges
            atr = sum(true_ranges) / len(true_ranges) if true_ranges else None
            
            if atr:
                logger.debug(f"ATR({period}) for {symbol} {timeframe}: {atr:.5f}")
            
            return atr

        except Exception as e:
            logger.error(f"Error calculating ATR for {symbol}: {e}")
            return None

    def process_trade(self, db: Session, trade: Trade, current_price: float) -> Optional[Dict]:
        """
        Process trade for smart trailing stop
        
        Strategy:
        1. Calculate profit in pips/points
        2. Get current ATR for noise measurement
        3. Set trail distance = ATR * multiplier * session_mult
        4. Implement aggressive break-even at 20% to TP
        5. Progressive tightening as trade approaches TP
        6. NEVER move SL against trade (only lock profits)
        
        Returns: Dict with actions or None
        """
        try:
            # Rate limiting
            now = datetime.utcnow()
            if trade.ticket in self.last_update:
                if (now - self.last_update[trade.ticket]).total_seconds() < self.update_interval:
                    return None

            # Get config
            cfg = self.configs.get(trade.symbol, self.default)
            is_buy = trade.direction.upper() in ['BUY', '0']

            entry = float(trade.open_price)
            sl = float(trade.sl) if trade.sl else None
            tp = float(trade.tp) if trade.tp else None

            if not sl or not tp:
                logger.debug(f"Trade {trade.ticket}: No SL/TP set, skipping trailing")
                return None

            # Calculate profit distance
            if is_buy:
                profit_dist = current_price - entry
                tp_dist = tp - entry
                current_sl_dist = current_price - sl
            else:
                profit_dist = entry - current_price
                tp_dist = entry - tp
                current_sl_dist = sl - current_price

            # Convert to points
            profit_pts = profit_dist / cfg['point']
            tp_dist_pts = tp_dist / cfg['point']
            
            # Calculate % to TP
            pct_to_tp = (profit_dist / tp_dist * 100) if tp_dist > 0 else 0

            # Need SOME profit to start (but very small threshold)
            min_profit = cfg['min_profit_pts'] * cfg['point']
            if profit_dist < min_profit:
                logger.debug(f"Trade {trade.ticket}: Profit {profit_pts:.1f}pts < min {cfg['min_profit_pts']}pts")
                return None

            # === CALCULATE DYNAMIC TRAIL DISTANCE ===
            
            # 1. Get ATR (market noise measurement)
            atr = self._calculate_atr(db, trade.symbol, trade.timeframe or 'H1', cfg['atr_period'])
            
            if atr:
                # Use ATR as base for trail distance (smart noise compensation!)
                base_trail_dist = atr * cfg['atr_multiplier']
            else:
                # Fallback: Use fixed percentage of entry price
                base_trail_dist = entry * 0.005  # 0.5% fallback
                logger.warning(f"Trade {trade.ticket}: No ATR, using fallback trail distance")

            # 2. Apply session volatility multiplier
            session_mult = self._get_session_volatility_multiplier()
            
            # 3. Apply progress-based multiplier (tighter as approaching TP)
            if pct_to_tp >= 80:
                progress_mult = 0.4  # Very tight near TP (40% of base)
            elif pct_to_tp >= 60:
                progress_mult = 0.6  # Moderate (60% of base)
            elif pct_to_tp >= 40:
                progress_mult = 0.8  # Still generous (80% of base)
            elif pct_to_tp >= 20:
                progress_mult = 1.0  # Full ATR distance
            else:
                # < 20% to TP: Aggressive break-even mode!
                # Use MINIMUM trail distance to get to break-even fast
                progress_mult = 0.7  # Slightly tighter for quick BE
            
            # Final trail distance
            trail_dist = base_trail_dist * session_mult * progress_mult
            
            # ✅ CRITICAL: Cap trail distance to max 50% of current profit
            # This ensures we can always reach break-even even with high ATR
            # Use profit_pts (already in points) for comparison
            max_trail_pts = profit_pts * 0.5
            trail_pts = trail_dist / cfg['point']
            
            if trail_pts > max_trail_pts:
                old_trail_pts = trail_pts
                trail_dist = max_trail_pts * cfg['point']  # Convert back to price
                logger.info(
                    f"🔧 Trade {trade.ticket}: Trail capped at 50% of profit: "
                    f"{old_trail_pts:.1f}pts → {max_trail_pts:.1f}pts"
                )
            
            trail_dist_pts = trail_dist / cfg['point']

            logger.info(
                f"📏 Trade {trade.ticket} ({trade.symbol}): "
                f"Profit={profit_pts:.1f}pts ({pct_to_tp:.0f}% to TP) | "
                f"ATR={atr/cfg['point']:.1f}pts | "
                f"Trail={trail_dist_pts:.1f}pts (sess={session_mult:.1f}x, prog={progress_mult:.1f}x)"
            )

            # === CALCULATE NEW SL ===
            if is_buy:
                new_sl = current_price - trail_dist
            else:
                new_sl = current_price + trail_dist

            # === SAFETY CHECKS ===
            
            # 1. NEVER move SL against trade (only lock profits)
            # For BUY: New SL must be HIGHER than current (moving up towards price)
            # For SELL: New SL must be LOWER than current (moving down towards price)
            if is_buy:
                if new_sl <= sl:
                    logger.debug(f"Trade {trade.ticket}: New SL {new_sl:.5f} <= current {sl:.5f}, skipping")
                    return None
            else:
                if new_sl >= sl:
                    logger.debug(f"Trade {trade.ticket}: New SL {new_sl:.5f} >= current {sl:.5f}, not better - skipping")
                    return None

            # 2. NEVER create a loss with trailing stop
            if is_buy:
                if new_sl < entry:
                    # SL below entry = potential loss
                    # Set to break-even + small buffer instead
                    min_be_buffer = cfg['point'] * 2  # 2 points above BE
                    new_sl = max(new_sl, entry + min_be_buffer)
                    logger.info(f"⚠️ Trade {trade.ticket}: Adjusted SL to break-even + buffer: {new_sl:.5f}")
            else:
                if new_sl > entry:
                    # SL above entry = potential loss
                    min_be_buffer = cfg['point'] * 2
                    new_sl = min(new_sl, entry - min_be_buffer)
                    logger.info(f"⚠️ Trade {trade.ticket}: Adjusted SL to break-even + buffer: {new_sl:.5f}")

            # 3. Minimum movement required (avoid micro-adjustments)
            sl_move = abs(new_sl - sl)
            sl_move_pts = sl_move / cfg['point']
            min_move_pts = max(cfg['min_profit_pts'] * 0.3, 3)  # At least 30% of min profit or 3 pts
            
            if sl_move_pts < min_move_pts:
                logger.debug(f"Trade {trade.ticket}: SL move {sl_move_pts:.1f}pts < min {min_move_pts:.1f}pts")
                return None

            # === TP EXTENSION (Bonus Feature) ===
            actions = {}

            # If 90%+ to TP and strong momentum → extend TP
            if pct_to_tp >= 90 and self.tp_extensions.get(trade.ticket, 0) < 2:
                extension_dist = tp_dist * 0.75  # 🔧 OPTIMIZED: 75% extension (was 50%)
                if is_buy:
                    new_tp = tp + extension_dist
                else:
                    new_tp = tp - extension_dist
                
                actions['extend_tp'] = new_tp
                self.tp_extensions[trade.ticket] = self.tp_extensions.get(trade.ticket, 0) + 1
                logger.info(
                    f"🚀 TP EXTENSION: {trade.symbol} #{trade.ticket} - "
                    f"TP {tp:.5f} → {new_tp:.5f} (extension #{self.tp_extensions[trade.ticket]})"
                )

            # === SEND MODIFICATION COMMAND ===
            actions['new_sl'] = new_sl
            
            logger.info(
                f"🎯 TRAILING STOP: {trade.symbol} #{trade.ticket} - "
                f"SL {sl:.5f} → {new_sl:.5f} (move={sl_move_pts:.1f}pts, trail={trail_dist_pts:.1f}pts, {pct_to_tp:.0f}% to TP)"
            )

            self._send_modify_command(db, trade, new_sl, actions.get('extend_tp'))
            self.last_update[trade.ticket] = now
            
            return actions

        except Exception as e:
            logger.error(f"Error processing trade {trade.ticket}: {e}", exc_info=True)
            return None

    def _send_modify_command(self, db: Session, trade: Trade, new_sl: float, new_tp: Optional[float] = None) -> bool:
        """Send MODIFY_TRADE command to EA and log history event"""
        try:
            import uuid
            from models import TradeHistoryEvent, Tick

            # Get current price for history logging
            current_tick = db.query(Tick).filter_by(
                symbol=trade.symbol
            ).order_by(Tick.timestamp.desc()).first()
            
            current_price = None
            current_spread = None
            if current_tick:
                if trade.direction.upper() == 'BUY':
                    current_price = float(current_tick.bid)
                else:
                    current_price = float(current_tick.ask)
                current_spread = float(current_tick.spread) if current_tick.spread else None

            payload = {
                'ticket': trade.ticket,
                'symbol': trade.symbol,
                'sl': float(new_sl),
                'tp': float(new_tp) if new_tp else float(trade.tp),
                'trailing_stop': True  # ✅ Mark this as trailing stop modification
            }

            cmd = Command(
                id=str(uuid.uuid4()),
                account_id=trade.account_id,
                command_type='MODIFY_TRADE',
                status='pending',
                created_at=datetime.utcnow(),
                payload=payload
            )

            db.add(cmd)
            
            # ✅ PHASE 6: Log SL modification in history
            old_sl = float(trade.sl) if trade.sl else None
            if old_sl and old_sl != new_sl:
                # Determine reason based on SL movement
                if trade.direction.upper() == 'BUY':
                    if new_sl >= float(trade.open_price):
                        reason = "Trailing Stop - moved to profit zone"
                    else:
                        reason = "Trailing Stop - risk reduction"
                else:  # SELL
                    if new_sl <= float(trade.open_price):
                        reason = "Trailing Stop - moved to profit zone"
                    else:
                        reason = "Trailing Stop - risk reduction"
                
                sl_event = TradeHistoryEvent(
                    trade_id=trade.id,
                    ticket=trade.ticket,
                    event_type='SL_MODIFIED',
                    timestamp=datetime.utcnow(),
                    old_value=old_sl,
                    new_value=new_sl,
                    reason=reason,
                    source='smart_trailing_stop',
                    price_at_change=current_price,
                    spread_at_change=current_spread
                )
                db.add(sl_event)
                
                # Update trailing stop tracking
                trade.trailing_stop_active = True
                if trade.trailing_stop_moves is None:
                    trade.trailing_stop_moves = 0
                trade.trailing_stop_moves += 1
                
                logger.info(f"📝 History: SL change logged for #{trade.ticket}: {old_sl:.5f} → {new_sl:.5f}")
            
            # ✅ PHASE 6: Log TP modification in history (if TP extension)
            if new_tp:
                old_tp = float(trade.tp) if trade.tp else None
                if old_tp and old_tp != new_tp:
                    tp_event = TradeHistoryEvent(
                        trade_id=trade.id,
                        ticket=trade.ticket,
                        event_type='TP_MODIFIED',
                        timestamp=datetime.utcnow(),
                        old_value=old_tp,
                        new_value=new_tp,
                        reason="TP extension - trailing stop with TP extension enabled",
                        source='smart_trailing_stop',
                        price_at_change=current_price,
                        spread_at_change=current_spread
                    )
                    db.add(tp_event)
                    
                    # Update TP extension tracking
                    if trade.tp_extended_count is None:
                        trade.tp_extended_count = 0
                    trade.tp_extended_count += 1
                    
                    logger.info(f"📝 History: TP extension logged for #{trade.ticket}: {old_tp:.5f} → {new_tp:.5f}")
            
            db.commit()
            
            logger.info(f"✅ Modify command sent for trade {trade.ticket}")
            return True

        except Exception as e:
            logger.error(f"Error sending modify command: {e}")
            db.rollback()
            db.rollback()
            return False

    def process_all(self, db: Session) -> Dict:
        """Process all open trades"""
        stats = {'total': 0, 'trailed': 0, 'extended': 0, 'errors': 0}

        try:
            # Get all open trades
            from models import Trade
            open_trades = db.query(Trade).filter_by(status='open').all()
            stats['total'] = len(open_trades)

            if not open_trades:
                logger.debug("No open trades to process")
                return stats

            logger.info(f"🔄 Processing {len(open_trades)} open trade(s) for smart trailing stop")

            for trade in open_trades:
                try:
                    # Get current price
                    tick = db.query(Tick).filter_by(symbol=trade.symbol).order_by(
                        Tick.timestamp.desc()
                    ).first()

                    if not tick:
                        logger.warning(f"No tick data for {trade.symbol}")
                        continue

                    # Use bid for BUY (closing price), ask for SELL
                    is_buy = trade.direction.upper() in ['BUY', '0']
                    current_price = float(tick.bid) if is_buy else float(tick.ask)

                    # Process trailing stop
                    result = self.process_trade(db, trade, current_price)

                    if result:
                        if 'new_sl' in result:
                            stats['trailed'] += 1
                        if 'extend_tp' in result:
                            stats['extended'] += 1

                except Exception as e:
                    logger.error(f"Error processing trade {trade.ticket}: {e}")
                    stats['errors'] += 1

            logger.info(
                f"✅ Smart Trailing Stop completed: {stats['trailed']} trailed, "
                f"{stats['extended']} TP extended, {stats['errors']} errors"
            )

        except Exception as e:
            logger.error(f"Error in process_all: {e}", exc_info=True)

        return stats


# Singleton instance
_smart_trailing = None

def get_smart_trailing() -> SmartTrailingStop:
    """Get singleton instance"""
    global _smart_trailing
    if _smart_trailing is None:
        _smart_trailing = SmartTrailingStop()
    return _smart_trailing
