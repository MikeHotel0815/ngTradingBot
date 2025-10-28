#!/usr/bin/env python3
"""
Smart Trailing Stop V2 - Hybrid Adaptive System
================================================

OPTION C: Combines 60-second volatility analysis + ML reversal prediction + ATR

Key Features:
1. 60-second tick analysis - detects recent price jumps and volatility
2. Symbol-specific noise calibration - different spreads, tick sizes, behaviors
3. ML reversal prediction - uses trained model to predict reversal probability
4. Adaptive trail distance - tighter in calm markets, wider in volatile markets
5. Real-time updates - checks every 10-30 seconds based on market conditions

Strategy:
- Calm market + low reversal risk → VERY TIGHT trail (0.3% - 0.5%)
- Volatile market + high reversal risk → WIDER trail (1.5% - 2.5%)
- Progressive tightening as approaching TP
- Never create loss with trailing stop
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
from sqlalchemy.orm import Session
from sqlalchemy import and_
import numpy as np

from models import Trade, Command, Tick, OHLCData, BrokerSymbol
from database import ScopedSession

logger = logging.getLogger(__name__)


class VolatilityAnalyzer:
    """
    Analyzes recent price movements to determine optimal trail distance
    """

    def __init__(self):
        # Symbol-specific noise profiles (spread + typical tick movement)
        self.noise_profiles = {
            # Crypto - high volatility, large spreads
            'BTCUSD': {
                'typical_spread': 0.10,      # 10 USD typical spread
                'noise_threshold': 0.15,     # 15 USD = normal noise
                'calm_threshold': 0.05,      # 5 USD = very calm
                'volatile_threshold': 0.50,  # 50 USD = very volatile
                'point': 0.01
            },
            'ETHUSD': {
                'typical_spread': 0.05,
                'noise_threshold': 0.10,
                'calm_threshold': 0.03,
                'volatile_threshold': 0.30,
                'point': 0.01
            },

            # Metals - moderate volatility, tight spreads
            'XAUUSD': {
                'typical_spread': 0.30,      # 30 cents typical
                'noise_threshold': 0.50,     # 50 cents normal
                'calm_threshold': 0.20,      # 20 cents calm
                'volatile_threshold': 2.00,  # $2 volatile
                'point': 0.01
            },
            'XAGUSD': {
                'typical_spread': 0.02,
                'noise_threshold': 0.05,
                'calm_threshold': 0.02,
                'volatile_threshold': 0.15,
                'point': 0.001
            },

            # Indices - moderate spreads
            'DE40.c': {
                'typical_spread': 2.0,       # 2 points typical
                'noise_threshold': 5.0,      # 5 points normal
                'calm_threshold': 2.0,       # 2 points calm
                'volatile_threshold': 15.0,  # 15 points volatile
                'point': 1.0
            },
            'US500.c': {
                'typical_spread': 0.50,
                'noise_threshold': 1.50,
                'calm_threshold': 0.50,
                'volatile_threshold': 5.00,
                'point': 0.01
            },

            # Forex - very tight spreads, low noise
            'EURUSD': {
                'typical_spread': 0.00010,   # 1 pip
                'noise_threshold': 0.00020,  # 2 pips normal
                'calm_threshold': 0.00010,   # 1 pip calm
                'volatile_threshold': 0.00050, # 5 pips volatile
                'point': 0.00001
            },
            'GBPUSD': {
                'typical_spread': 0.00015,
                'noise_threshold': 0.00025,
                'calm_threshold': 0.00015,
                'volatile_threshold': 0.00060,
                'point': 0.00001
            },
            'USDJPY': {
                'typical_spread': 0.015,     # 1.5 pips
                'noise_threshold': 0.025,
                'calm_threshold': 0.015,
                'volatile_threshold': 0.060,
                'point': 0.001
            },
            'AUDUSD': {
                'typical_spread': 0.00015,
                'noise_threshold': 0.00025,
                'calm_threshold': 0.00015,
                'volatile_threshold': 0.00060,
                'point': 0.00001
            },
        }

        # Default for unknown symbols
        self.default_profile = {
            'typical_spread': 0.00020,
            'noise_threshold': 0.00030,
            'calm_threshold': 0.00015,
            'volatile_threshold': 0.00080,
            'point': 0.00001
        }

    def analyze_recent_volatility(self, db: Session, symbol: str, window_seconds: int = 60) -> Dict:
        """
        Analyze price movements in the last X seconds

        Returns:
        {
            'volatility_level': 'calm' | 'normal' | 'volatile',
            'price_range': float,           # Max - Min price in window
            'avg_jump_size': float,         # Average tick-to-tick movement
            'max_jump_size': float,         # Largest single tick movement
            'tick_count': int,              # Number of ticks analyzed
            'volatility_score': float       # 0.0 - 1.0 (0=calm, 1=very volatile)
        }
        """
        try:
            profile = self.noise_profiles.get(symbol, self.default_profile)

            # Get ticks from last X seconds
            cutoff = datetime.utcnow() - timedelta(seconds=window_seconds)
            ticks = db.query(Tick).filter(
                and_(
                    Tick.symbol == symbol,
                    Tick.timestamp >= cutoff
                )
            ).order_by(Tick.timestamp.asc()).all()

            if len(ticks) < 5:
                logger.warning(f"{symbol}: Not enough ticks for volatility analysis ({len(ticks)} ticks)")
                return {
                    'volatility_level': 'normal',
                    'price_range': profile['noise_threshold'],
                    'avg_jump_size': profile['noise_threshold'] / 2,
                    'max_jump_size': profile['noise_threshold'],
                    'tick_count': len(ticks),
                    'volatility_score': 0.5
                }

            # Extract mid prices (bid + ask) / 2
            prices = [(float(t.bid) + float(t.ask)) / 2 for t in ticks]

            # Calculate metrics
            price_range = max(prices) - min(prices)

            # Calculate tick-to-tick jumps
            jumps = [abs(prices[i] - prices[i-1]) for i in range(1, len(prices))]
            avg_jump = np.mean(jumps) if jumps else 0
            max_jump = max(jumps) if jumps else 0

            # Determine volatility level
            if price_range <= profile['calm_threshold']:
                volatility_level = 'calm'
                volatility_score = price_range / profile['calm_threshold'] * 0.33  # 0.0 - 0.33
            elif price_range >= profile['volatile_threshold']:
                volatility_level = 'volatile'
                # Scale from 0.67 to 1.0
                excess = min(price_range - profile['volatile_threshold'], profile['volatile_threshold'])
                volatility_score = 0.67 + (excess / profile['volatile_threshold']) * 0.33
            else:
                volatility_level = 'normal'
                # Scale from 0.33 to 0.67
                range_ratio = (price_range - profile['calm_threshold']) / (profile['volatile_threshold'] - profile['calm_threshold'])
                volatility_score = 0.33 + range_ratio * 0.34

            logger.info(
                f"📊 {symbol} Volatility (60s): {volatility_level.upper()} | "
                f"Range: {price_range:.5f} | Avg Jump: {avg_jump:.5f} | "
                f"Max Jump: {max_jump:.5f} | Score: {volatility_score:.2f} | Ticks: {len(ticks)}"
            )

            return {
                'volatility_level': volatility_level,
                'price_range': price_range,
                'avg_jump_size': avg_jump,
                'max_jump_size': max_jump,
                'tick_count': len(ticks),
                'volatility_score': volatility_score
            }

        except Exception as e:
            logger.error(f"Error analyzing volatility for {symbol}: {e}")
            # Return conservative defaults on error
            return {
                'volatility_level': 'normal',
                'price_range': profile['noise_threshold'],
                'avg_jump_size': profile['noise_threshold'] / 2,
                'max_jump_size': profile['noise_threshold'],
                'tick_count': 0,
                'volatility_score': 0.5
            }


class MLReversalPredictor:
    """
    Predicts probability of trend reversal using ML model
    """

    def __init__(self):
        self.model = None
        self._load_model()

    def _load_model(self):
        """Load trained ML model for reversal prediction"""
        try:
            from ml.ml_confidence_model import MLConfidenceModel

            # Try to load existing model
            ml_model = MLConfidenceModel()
            if ml_model.load_model('global'):
                self.model = ml_model
                logger.info("✅ ML Reversal Predictor: Model loaded successfully")
            else:
                logger.warning("⚠️ ML Reversal Predictor: No model found, using heuristics")
                self.model = None

        except Exception as e:
            logger.warning(f"ML Reversal Predictor: Could not load model: {e}")
            self.model = None

    def predict_reversal_probability(self, db: Session, trade: Trade, current_price: float) -> float:
        """
        Predict probability of reversal (0.0 - 1.0)

        Higher value = higher risk of reversal = wider trail needed

        Features used:
        - Profit percentage
        - Time in trade
        - Distance to TP
        - Recent price momentum
        - ATR ratio
        """
        try:
            if self.model is None:
                # Fallback to simple heuristic
                return self._heuristic_reversal_probability(trade, current_price)

            # TODO: Implement full ML prediction when model is trained for this
            # For now, use heuristic
            return self._heuristic_reversal_probability(trade, current_price)

        except Exception as e:
            logger.error(f"Error predicting reversal: {e}")
            return 0.5  # Conservative default

    def _heuristic_reversal_probability(self, trade: Trade, current_price: float) -> float:
        """
        Simple heuristic-based reversal probability

        Logic:
        - Near TP (>80%) = high reversal risk (0.7-0.9)
        - Mid-range (40-80%) = moderate risk (0.4-0.6)
        - Early (<40%) = low risk (0.2-0.4)
        - Consider time in trade (longer = higher risk)
        """
        try:
            is_buy = trade.direction.upper() in ['BUY', '0']
            entry = float(trade.open_price)
            tp = float(trade.tp) if trade.tp else None

            if not tp:
                return 0.5

            # Calculate % to TP
            if is_buy:
                profit_dist = current_price - entry
                tp_dist = tp - entry
            else:
                profit_dist = entry - current_price
                tp_dist = entry - tp

            pct_to_tp = (profit_dist / tp_dist * 100) if tp_dist > 0 else 0

            # Base reversal risk on distance to TP
            if pct_to_tp >= 80:
                base_risk = 0.80  # High risk near TP
            elif pct_to_tp >= 60:
                base_risk = 0.60
            elif pct_to_tp >= 40:
                base_risk = 0.45
            elif pct_to_tp >= 20:
                base_risk = 0.35
            else:
                base_risk = 0.25  # Low risk early in trade

            # Adjust for time in trade (longer = more unstable)
            if trade.open_time:
                minutes_open = (datetime.utcnow() - trade.open_time).total_seconds() / 60
                if minutes_open > 120:  # > 2 hours
                    base_risk += 0.15
                elif minutes_open > 60:  # > 1 hour
                    base_risk += 0.10
                elif minutes_open > 30:  # > 30 min
                    base_risk += 0.05

            # Cap at 0.95
            return min(base_risk, 0.95)

        except Exception as e:
            logger.error(f"Error in heuristic reversal prediction: {e}")
            return 0.5


class SmartTrailingStopV2:
    """
    Hybrid Adaptive Trailing Stop System

    Combines:
    1. 60-second volatility analysis (tick-based)
    2. Symbol-specific noise calibration
    3. ML reversal prediction
    4. ATR-based base distance
    """

    def __init__(self):
        self.volatility_analyzer = VolatilityAnalyzer()
        self.reversal_predictor = MLReversalPredictor()

        # Update intervals (adaptive based on volatility)
        self.update_intervals = {
            'calm': 30,      # 30 seconds in calm markets
            'normal': 15,    # 15 seconds normally
            'volatile': 5    # 5 seconds in volatile markets (very responsive!)
        }

        self.last_update = {}
        self.tp_extensions = {}

    def calculate_adaptive_trail_distance(
        self,
        db: Session,
        trade: Trade,
        current_price: float,
        volatility_analysis: Dict,
        reversal_probability: float
    ) -> Tuple[float, Dict]:
        """
        Calculate optimal trail distance based on:
        - Recent 60s volatility
        - ML reversal prediction
        - ATR baseline
        - Progress to TP

        Returns: (trail_distance, debug_info)
        """
        try:
            is_buy = trade.direction.upper() in ['BUY', '0']
            entry = float(trade.open_price)
            tp = float(trade.tp) if trade.tp else None

            profile = self.volatility_analyzer.noise_profiles.get(
                trade.symbol,
                self.volatility_analyzer.default_profile
            )

            # Calculate profit and % to TP
            if is_buy:
                profit_dist = current_price - entry
                tp_dist = tp - entry if tp else profit_dist * 2
            else:
                profit_dist = entry - current_price
                tp_dist = entry - tp if tp else profit_dist * 2

            pct_to_tp = (profit_dist / tp_dist * 100) if tp_dist > 0 else 0

            # === STEP 1: Base Trail Distance from Volatility ===
            vol_score = volatility_analysis['volatility_score']

            # Calm market (score 0.0-0.33): Tight trail 0.3% - 0.8%
            # Normal market (score 0.33-0.67): Medium trail 0.8% - 1.5%
            # Volatile market (score 0.67-1.0): Wide trail 1.5% - 2.5%

            if vol_score < 0.33:  # Calm
                base_trail_pct = 0.003 + (vol_score / 0.33) * 0.005  # 0.3% - 0.8%
            elif vol_score < 0.67:  # Normal
                base_trail_pct = 0.008 + ((vol_score - 0.33) / 0.34) * 0.007  # 0.8% - 1.5%
            else:  # Volatile
                base_trail_pct = 0.015 + ((vol_score - 0.67) / 0.33) * 0.010  # 1.5% - 2.5%

            base_trail = entry * base_trail_pct

            # === STEP 2: Adjust for Reversal Risk ===
            # Higher reversal risk = wider trail to avoid premature exit
            reversal_multiplier = 0.8 + (reversal_probability * 0.6)  # 0.8x - 1.4x

            trail_with_reversal = base_trail * reversal_multiplier

            # === STEP 3: Progressive Tightening as Approaching TP ===
            if pct_to_tp >= 90:
                progress_mult = 0.3  # VERY tight near TP
            elif pct_to_tp >= 75:
                progress_mult = 0.5
            elif pct_to_tp >= 50:
                progress_mult = 0.7
            elif pct_to_tp >= 25:
                progress_mult = 0.9
            else:
                progress_mult = 1.0  # Full distance early on

            final_trail = trail_with_reversal * progress_mult

            # === STEP 4: Safety Cap (max 50% of current profit) ===
            max_trail = profit_dist * 0.5
            if final_trail > max_trail:
                logger.info(
                    f"🔧 {trade.symbol} #{trade.ticket}: Trail capped at 50% profit: "
                    f"{final_trail/profile['point']:.1f}pts → {max_trail/profile['point']:.1f}pts"
                )
                final_trail = max_trail

            # === STEP 5: Minimum Trail (at least 2x typical spread) ===
            min_trail = profile['typical_spread'] * 2
            if final_trail < min_trail:
                final_trail = min_trail

            debug_info = {
                'volatility_score': vol_score,
                'volatility_level': volatility_analysis['volatility_level'],
                'reversal_probability': reversal_probability,
                'base_trail_pct': base_trail_pct,
                'reversal_mult': reversal_multiplier,
                'progress_mult': progress_mult,
                'pct_to_tp': pct_to_tp,
                'final_trail_pts': final_trail / profile['point']
            }

            return final_trail, debug_info

        except Exception as e:
            logger.error(f"Error calculating trail distance: {e}")
            # Conservative fallback
            return entry * 0.01, {}

    def process_trade(self, db: Session, trade: Trade, current_price: float) -> Optional[Dict]:
        """
        Process trade with hybrid adaptive trailing stop
        """
        try:
            # === STEP 1: Analyze Recent Volatility (60 seconds) ===
            volatility = self.volatility_analyzer.analyze_recent_volatility(
                db, trade.symbol, window_seconds=60
            )

            # === STEP 2: Determine Update Interval (adaptive) ===
            update_interval = self.update_intervals[volatility['volatility_level']]

            # Rate limiting based on volatility
            now = datetime.utcnow()
            if trade.ticket in self.last_update:
                elapsed = (now - self.last_update[trade.ticket]).total_seconds()
                if elapsed < update_interval:
                    return None

            # === STEP 3: ML Reversal Prediction ===
            reversal_prob = self.reversal_predictor.predict_reversal_probability(
                db, trade, current_price
            )

            # === STEP 4: Calculate Adaptive Trail Distance ===
            trail_dist, debug_info = self.calculate_adaptive_trail_distance(
                db, trade, current_price, volatility, reversal_prob
            )

            # === STEP 5: Calculate New SL ===
            is_buy = trade.direction.upper() in ['BUY', '0']
            sl = float(trade.sl) if trade.sl else None
            entry = float(trade.open_price)

            if not sl:
                logger.debug(f"Trade {trade.ticket}: No SL set, skipping")
                return None

            if is_buy:
                new_sl = current_price - trail_dist
            else:
                new_sl = current_price + trail_dist

            # === STEP 6: Safety Checks ===

            # 6.1: NEVER move SL against trade
            if is_buy:
                if new_sl <= sl:
                    return None
            else:
                if new_sl >= sl:
                    return None

            # 6.2: NEVER create loss
            profile = self.volatility_analyzer.noise_profiles.get(
                trade.symbol,
                self.volatility_analyzer.default_profile
            )

            if is_buy:
                if new_sl < entry:
                    min_be_buffer = profile['point'] * 2
                    new_sl = max(new_sl, entry + min_be_buffer)
                    logger.info(f"⚠️ {trade.ticket}: Adjusted to break-even + buffer")
            else:
                if new_sl > entry:
                    min_be_buffer = profile['point'] * 2
                    new_sl = min(new_sl, entry - min_be_buffer)
                    logger.info(f"⚠️ {trade.ticket}: Adjusted to break-even + buffer")

            # 6.3: Minimum movement required
            sl_move = abs(new_sl - sl)
            sl_move_pts = sl_move / profile['point']
            min_move_pts = 3  # At least 3 points movement

            if sl_move_pts < min_move_pts:
                return None

            # === STEP 7: Log and Execute ===
            logger.info(
                f"🎯 HYBRID TS: {trade.symbol} #{trade.ticket} - "
                f"SL {sl:.5f} → {new_sl:.5f} | "
                f"Vol: {debug_info['volatility_level']} ({debug_info['volatility_score']:.2f}) | "
                f"Reversal: {reversal_prob:.0%} | "
                f"Trail: {debug_info['final_trail_pts']:.1f}pts | "
                f"{debug_info['pct_to_tp']:.0f}% to TP"
            )

            self._send_modify_command(db, trade, new_sl)
            self.last_update[trade.ticket] = now

            return {'new_sl': new_sl, 'debug': debug_info}

        except Exception as e:
            logger.error(f"Error processing trade {trade.ticket}: {e}", exc_info=True)
            return None

    def _send_modify_command(self, db: Session, trade: Trade, new_sl: float) -> bool:
        """Send MODIFY_TRADE command to EA"""
        try:
            import uuid
            from models import TradeHistoryEvent, Tick

            # Get current price for logging
            current_tick = db.query(Tick).filter_by(
                symbol=trade.symbol
            ).order_by(Tick.timestamp.desc()).first()

            current_price = None
            if current_tick:
                if trade.direction.upper() == 'BUY':
                    current_price = float(current_tick.bid)
                else:
                    current_price = float(current_tick.ask)

            payload = {
                'ticket': trade.ticket,
                'symbol': trade.symbol,
                'sl': float(new_sl),
                'tp': float(trade.tp) if trade.tp else 0.0,
                'trailing_stop': True,
                'trailing_version': 'v2_hybrid'
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

            # Log history event
            old_sl = float(trade.sl) if trade.sl else None
            if old_sl and old_sl != new_sl:
                sl_event = TradeHistoryEvent(
                    trade_id=trade.id,
                    ticket=trade.ticket,
                    event_type='SL_MODIFIED',
                    timestamp=datetime.utcnow(),
                    old_value=old_sl,
                    new_value=new_sl,
                    reason="Hybrid Adaptive Trailing Stop V2",
                    source='smart_trailing_stop_v2',
                    price_at_change=current_price
                )
                db.add(sl_event)

                # Update tracking
                trade.trailing_stop_active = True
                if trade.trailing_stop_moves is None:
                    trade.trailing_stop_moves = 0
                trade.trailing_stop_moves += 1

            db.commit()
            logger.info(f"✅ Modify command sent for trade {trade.ticket}")
            return True

        except Exception as e:
            logger.error(f"Error sending modify command: {e}")
            db.rollback()
            return False

    def process_all(self, db: Session) -> Dict:
        """Process all open trades"""
        stats = {'total': 0, 'trailed': 0, 'errors': 0}

        try:
            from models import Trade
            open_trades = db.query(Trade).filter_by(status='open').all()
            stats['total'] = len(open_trades)

            if not open_trades:
                return stats

            logger.info(f"🔄 Processing {len(open_trades)} trades with Hybrid Adaptive TS V2")

            for trade in open_trades:
                try:
                    # Get current price
                    tick = db.query(Tick).filter_by(symbol=trade.symbol).order_by(
                        Tick.timestamp.desc()
                    ).first()

                    if not tick:
                        continue

                    is_buy = trade.direction.upper() in ['BUY', '0']
                    current_price = float(tick.bid) if is_buy else float(tick.ask)

                    result = self.process_trade(db, trade, current_price)

                    if result and 'new_sl' in result:
                        stats['trailed'] += 1

                except Exception as e:
                    logger.error(f"Error processing trade {trade.ticket}: {e}")
                    stats['errors'] += 1

            logger.info(
                f"✅ Hybrid TS V2 completed: {stats['trailed']} trailed, {stats['errors']} errors"
            )

        except Exception as e:
            logger.error(f"Error in process_all: {e}", exc_info=True)

        return stats


# Singleton instance
_smart_trailing_v2 = None

def get_smart_trailing_v2() -> SmartTrailingStopV2:
    """Get singleton instance"""
    global _smart_trailing_v2
    if _smart_trailing_v2 is None:
        _smart_trailing_v2 = SmartTrailingStopV2()
    return _smart_trailing_v2
