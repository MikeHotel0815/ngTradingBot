"""
Signal Generator Module
Combines pattern recognition and technical indicators to generate trading signals

Features:
- Configurable thresholds and parameters (see signal_config.py)
- Optional ML confidence enhancement
- News filter integration
- Market hours checking
- Multi-timeframe analysis
- Continuous signal validation
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from database import ScopedSession
from models import TradingSignal, OHLCData
from technical_indicators import TechnicalIndicators
from pattern_recognition import PatternRecognizer
from signal_config import get_config

# ML Integration (optional - graceful degradation if unavailable)
try:
    from ml.ml_features import FeatureEngineer
    from ml.ml_model_manager import MLModelManager
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False

logger = logging.getLogger(__name__)


class SignalGenerator:
    """
    Generate trading signals by combining patterns and indicators
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str, risk_profile: str = 'normal'):
        """
        Initialize Signal Generator

        Args:
            account_id: Account ID
            symbol: Trading symbol
            timeframe: Timeframe (M5, M15, H1, H4, D1)
            risk_profile: Risk profile (aggressive, normal, moderate) - affects regime filtering
        """
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.risk_profile = risk_profile

        # Load symbol-specific configuration
        self.config = get_config(symbol)

        # Initialize indicators and patterns with configured cache TTL
        cache_ttl = self.config['CACHE_TTL']
        self.indicators = TechnicalIndicators(
            account_id, symbol, timeframe,
            cache_ttl=cache_ttl,
            risk_profile=risk_profile
        )
        self.patterns = PatternRecognizer(account_id, symbol, timeframe, cache_ttl=cache_ttl)

        # ML Integration (initialized lazily when needed)
        self.ml_manager = None
        self.ml_feature_engineer = None
        self.ml_prediction_id = None  # Track prediction for outcome logging

    def generate_signal(self) -> Optional[Dict]:
        """
        Generate trading signal based on patterns and indicators

        Returns:
            Signal dictionary or None if no strong signal
        """
        try:
            # ✅ Check if market is open for this symbol
            from market_hours import is_market_open
            if not is_market_open(self.symbol):
                logger.debug(f"Market closed for {self.symbol}, skipping signal generation")
                self._expire_active_signals("market closed")
                return None

            # ✅ Check news filter - prevent trading during high-impact events
            from news_filter import NewsFilter
            news_filter = NewsFilter(self.account_id)
            news_check = news_filter.check_trading_allowed(self.symbol)

            if not news_check['allowed']:
                reason = news_check.get('reason', 'high-impact news event')
                logger.warning(f"⛔ Trading paused for {self.symbol}: {reason}")
                self._expire_active_signals(f"news_filter: {reason}")

                # Log upcoming event details if available
                if 'upcoming_event' in news_check:
                    event = news_check['upcoming_event']
                    logger.info(f"📰 Upcoming: {event.get('event_name')} at {event.get('event_time')} (Impact: {event.get('impact')})")

                return None

            # Get pattern signals
            pattern_signals = self.patterns.get_pattern_signals()

            # Get indicator signals
            indicator_signals = self.indicators.get_indicator_signals()

            # No signals - expire any existing active signals for this symbol/timeframe
            if not pattern_signals and not indicator_signals:
                self._expire_active_signals("no pattern/indicator detected")
                return None

            # Aggregate signals
            signal = self._aggregate_signals(pattern_signals, indicator_signals)

            # Check minimum confidence threshold (from config)
            min_confidence = self.config['MIN_GENERATION_CONFIDENCE']

            # 🎯 ADDED 2025-11-06: Timeframe-specific confidence adjustments
            # H1 loses -324€ vs H4 +131€, needs higher threshold
            from signal_config import TIMEFRAME_MIN_CONFIDENCE
            if self.timeframe in TIMEFRAME_MIN_CONFIDENCE:
                timeframe_min = TIMEFRAME_MIN_CONFIDENCE[self.timeframe]
                if timeframe_min > min_confidence:
                    logger.debug(
                        f"Applying timeframe-specific min confidence for {self.timeframe}: "
                        f"{min_confidence}% → {timeframe_min}%"
                    )
                    min_confidence = timeframe_min

            if signal and signal['confidence'] >= min_confidence:
                logger.info(
                    f"✅ Signal PASSED: {self.symbol} {self.timeframe} "
                    f"{signal['signal_type']} | Confidence: {signal['confidence']:.1f}% "
                    f"(min: {min_confidence}%)"
                )

                # Calculate entry, SL, TP
                entry, sl, tp = self._calculate_entry_sl_tp(signal)

                signal['entry_price'] = entry
                signal['sl_price'] = sl
                signal['tp_price'] = tp

                # ✅ CRITICAL: SL ENFORCEMENT - Reject signals without valid SL
                if not sl or sl == 0:
                    logger.error(
                        f"🚨 Signal REJECTED: {self.symbol} {self.timeframe} {signal['signal_type']} | "
                        f"SL is ZERO (entry={entry}, sl={sl}, tp={tp}). "
                        f"All signals MUST have Stop Loss!"
                    )
                    return None

                # Validate SL direction
                if signal['signal_type'] == 'BUY' and sl >= entry:
                    logger.error(
                        f"🚨 Signal REJECTED: {self.symbol} BUY | "
                        f"SL ({sl}) must be BELOW entry ({entry})"
                    )
                    return None

                if signal['signal_type'] == 'SELL' and sl <= entry:
                    logger.error(
                        f"🚨 Signal REJECTED: {self.symbol} SELL | "
                        f"SL ({sl}) must be ABOVE entry ({entry})"
                    )
                    return None

                # Check if signal direction changed from existing active signal
                self._check_signal_direction_change(signal['signal_type'])

                # Save signal to database
                self._save_signal(signal)

                return signal

            # Signal too weak - expire existing signals
            self._expire_active_signals(f"confidence too low (< {min_confidence}%)")
            return None

        except Exception as e:
            logger.error(f"Error generating signal: {e}", exc_info=True)
            return None

    def _aggregate_signals(
        self,
        pattern_signals: List[Dict],
        indicator_signals: List[Dict]
    ) -> Optional[Dict]:
        """
        Aggregate pattern and indicator signals

        Args:
            pattern_signals: List of pattern signals
            indicator_signals: List of indicator signals

        Returns:
            Aggregated signal or None
        """
        # Count BUY and SELL signals
        buy_signals = []
        sell_signals = []

        for sig in pattern_signals:
            if sig['type'] == 'BUY':
                buy_signals.append(sig)
            elif sig['type'] == 'SELL':
                sell_signals.append(sig)

        for sig in indicator_signals:
            if sig['type'] == 'BUY':
                buy_signals.append(sig)
            elif sig['type'] == 'SELL':
                sell_signals.append(sig)

        # Get BUY signal advantage from config
        buy_advantage = self.config['BUY_SIGNAL_ADVANTAGE']

        buy_count = len(buy_signals)
        sell_count = len(sell_signals)

        signal_type = None
        if buy_count >= sell_count + buy_advantage:
            # BUY: Need advantage over SELL signals
            signal_type = 'BUY'
            signals = buy_signals
            logger.debug(
                f"BUY signal consensus: {buy_count} BUY vs {sell_count} SELL "
                f"(advantage: {buy_advantage})"
            )
        elif sell_count > buy_count:
            # SELL: Just need majority
            signal_type = 'SELL'
            signals = sell_signals
            logger.debug(f"SELL signal consensus: {sell_count} SELL vs {buy_count} BUY")
        else:
            # Not enough consensus or conflicting signals
            logger.debug(
                f"No consensus: {buy_count} BUY vs {sell_count} SELL "
                f"(BUY needs {sell_count + buy_advantage})"
            )
            return None

        # Calculate confidence score (rules-based)
        rules_confidence = self._calculate_confidence(
            signals,
            pattern_signals,
            indicator_signals
        )

        # ML Enhancement: Apply ML model if available
        ml_confidence, final_confidence, ab_test_group = self._apply_ml_enhancement(
            signal_type,
            rules_confidence
        )

        # Multi-Timeframe Conflict Detection
        # Check if this signal conflicts with higher timeframes and adjust confidence
        from multi_timeframe_analyzer import MultiTimeframeAnalyzer

        mtf_result = MultiTimeframeAnalyzer.check_conflict(
            current_signal_type=signal_type,
            current_timeframe=self.timeframe,
            symbol=self.symbol,
            account_id=self.account_id
        )

        # Apply MTF adjustment to final confidence
        mtf_adjustment = mtf_result['confidence_adjustment']
        if mtf_adjustment != 0:
            final_confidence = max(0.0, min(100.0, final_confidence + mtf_adjustment))

            if mtf_result['has_conflict']:
                logger.warning(
                    f"⚠️ MTF Conflict: {self.symbol} {self.timeframe} {signal_type} | "
                    f"Confidence: {final_confidence - mtf_adjustment:.1f}% → {final_confidence:.1f}% "
                    f"({mtf_adjustment:+.1f}%) | {mtf_result['reason']}"
                )
            else:
                logger.info(
                    f"✅ MTF Aligned: {self.symbol} {self.timeframe} {signal_type} | "
                    f"Confidence: {final_confidence - mtf_adjustment:.1f}% → {final_confidence:.1f}% "
                    f"({mtf_adjustment:+.1f}%) | {mtf_result['reason']}"
                )

        # Collect reasons
        reasons = [sig['reason'] for sig in signals]

        # Add MTF reason if there was an adjustment
        if mtf_adjustment != 0:
            reasons.append(mtf_result['reason'])

        # Add ML reason if used
        if ml_confidence is not None and ab_test_group != 'rules_only':
            ml_reason = f"ML Model: {ml_confidence:.1f}% confidence"
            if ab_test_group == 'hybrid':
                ml_reason += f" (hybrid with rules: {rules_confidence:.1f}%)"
            reasons.append(ml_reason)

        # Collect patterns
        patterns_detected = [
            sig['pattern'] for sig in pattern_signals
            if sig['type'] == signal_type
        ]

        # Collect indicators with ACTUAL indicator data (not just True/False)
        # This fixes the "invalid snapshot data" validation errors
        all_indicators = self.indicators.calculate_all()
        indicators_used = {}
        for sig in indicator_signals:
            if sig['type'] == signal_type:
                indicator_name = sig['indicator']
                # Look up actual indicator data from calculate_all()
                indicator_data = all_indicators.get(indicator_name)
                # Only store if it's a valid dict (skip False/None values)
                if indicator_data and isinstance(indicator_data, dict):
                    indicators_used[indicator_name] = indicator_data
                else:
                    logger.debug(f"Skipping {indicator_name} - no valid data available")

        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'signal_type': signal_type,
            'confidence': final_confidence,
            'rules_confidence': rules_confidence,  # Keep original for logging
            'ml_confidence': ml_confidence,  # Keep ML score for logging
            'ab_test_group': ab_test_group,  # Track which method was used
            'reasons': reasons,
            'patterns_detected': patterns_detected,
            'indicators_used': indicators_used,
            'signal_count': len(signals)
        }

    def _calculate_confidence(
        self,
        signals: List[Dict],
        pattern_signals: List[Dict],
        indicator_signals: List[Dict]
    ) -> float:
        """
        Calculate confidence score (0-100) using symbol-specific indicator weights

        Formula (from config):
        - Pattern Reliability: PATTERN_WEIGHT%
        - Weighted Indicator Confluence: INDICATOR_WEIGHT%
        - Signal Strength: STRENGTH_WEIGHT%

        Uses IndicatorScorer to weight indicators based on historical performance

        Args:
            signals: List of all signals (same direction)
            pattern_signals: List of pattern signals
            indicator_signals: List of indicator signals

        Returns:
            Confidence score (0-100)
        """
        from indicator_scorer import IndicatorScorer

        # Get weights from config
        pattern_weight = self.config['PATTERN_WEIGHT']
        indicator_weight = self.config['INDICATOR_WEIGHT']
        strength_weight = self.config['STRENGTH_WEIGHT']

        # Pattern reliability score
        pattern_score = 0
        if pattern_signals:
            avg_reliability = sum(
                sig.get('reliability', 50) for sig in pattern_signals
            ) / len(pattern_signals)
            pattern_score = (avg_reliability / 100) * pattern_weight

        # Indicator confluence score - weighted by symbol-specific performance
        indicator_score = 0
        if indicator_signals:
            scorer = IndicatorScorer(self.account_id, self.symbol, self.timeframe)

            # Get weights for each indicator
            total_weight = 0
            weighted_score = 0

            for sig in indicator_signals:
                indicator_name = sig.get('indicator', 'UNKNOWN')
                weight = scorer.get_indicator_weight(indicator_name)

                # Strength contribution (strong=10, medium=6, weak=3)
                strength_map = {'strong': 10, 'medium': 6, 'weak': 3}
                strength_value = strength_map.get(sig.get('strength', 'weak'), 3)

                # Weighted contribution
                weighted_score += strength_value * weight
                total_weight += weight

            # Normalize to indicator_weight range
            if total_weight > 0:
                # Average weighted score
                avg_weighted = weighted_score / total_weight

                # Scale to indicator_weight range (assuming max strength_value is 10)
                indicator_score = (avg_weighted / 10) * indicator_weight

                # Bonus for multiple indicators agreeing (confluence)
                confluence_bonus_per = self.config['CONFLUENCE_BONUS_PER_INDICATOR']
                confluence_bonus = min(10, len(indicator_signals) * confluence_bonus_per)
                indicator_score = min(indicator_weight, indicator_score + confluence_bonus)

            # ADX bonus: Add confidence if strong trend is present
            adx_bonus = self.config['ADX_STRONG_TREND_BONUS']
            adx_signal = next((sig for sig in indicator_signals if sig.get('indicator') == 'ADX'), None)
            if adx_signal and 'Strong Trend' in adx_signal.get('reason', ''):
                indicator_score = min(indicator_weight, indicator_score + adx_bonus)

            # OBV bonus: Add confidence if volume confirms the move
            obv_bonus = self.config['OBV_DIVERGENCE_BONUS']
            obv_signal = next((sig for sig in indicator_signals if sig.get('indicator') == 'OBV'), None)
            if obv_signal and 'Divergence' in obv_signal.get('reason', ''):
                indicator_score = min(indicator_weight, indicator_score + obv_bonus)

        # Signal strength score
        # Scale strength values to match strength_weight
        strength_map = {
            'strong': strength_weight,
            'medium': strength_weight * 0.67,
            'weak': strength_weight * 0.33
        }
        strength_scores = [
            strength_map.get(sig.get('strength', 'weak'), strength_weight * 0.33)
            for sig in signals
        ]
        strength_score = sum(strength_scores) / len(strength_scores) if strength_scores else (strength_weight * 0.33)

        # Total confidence (before direction adjustment)
        confidence = pattern_score + indicator_score + strength_score

        # Apply BUY confidence penalty from config (deprecated, kept for backward compatibility)
        buy_penalty = self.config['BUY_CONFIDENCE_PENALTY']
        signal_type = signals[0]['type'] if signals else 'UNKNOWN'

        if signal_type == 'BUY' and buy_penalty > 0:
            original_confidence = confidence
            confidence = max(0, confidence - buy_penalty)
            logger.debug(
                f"Applied BUY penalty: {original_confidence:.1f}% → {confidence:.1f}% "
                f"(-{buy_penalty}%)"
            )

        # 🎯 NEW 2025-11-06: Apply trend-alignment confidence adjustment
        # This is the CORRECT approach - adjust confidence based on trend quality and alignment
        confidence = self._apply_trend_alignment_adjustment(confidence, signal_type)

        return round(min(100, confidence), 2)

    def _apply_trend_alignment_adjustment(self, confidence: float, signal_type: str) -> float:
        """
        Apply trend-alignment confidence adjustment based on market regime
        🎯 NEW 2025-11-06: Replace blanket BUY/SELL penalties with intelligent trend-based adjustment

        Logic:
        - CHOPPY market: -30% confidence (avoid whipsaw)
        - TRENDING + WITH-TREND: +10% confidence (ideal setup)
        - TRENDING + COUNTER-TREND: -25% confidence (dangerous)
        - RANGING: no adjustment (neutral)
        - TOO_WEAK: already filtered earlier

        Args:
            confidence: Current confidence score
            signal_type: 'BUY' or 'SELL'

        Returns:
            Adjusted confidence score
        """
        try:
            # Get market regime from indicators
            regime = self.indicators.detect_market_regime()

            # Load adjustment parameters from config
            from signal_config import (
                TREND_ALIGNMENT_BONUS,
                COUNTER_TREND_PENALTY,
                CHOPPY_MARKET_PENALTY
            )

            original_confidence = confidence
            adjustment = 0
            adjustment_reason = ""

            # 1. CHOPPY market: Reduce confidence significantly
            if regime['regime'] == 'CHOPPY':
                adjustment = -CHOPPY_MARKET_PENALTY
                adjustment_reason = f"CHOPPY market (ADX={regime['adx']:.1f}, DI_diff={regime['di_diff']:.1f})"

            # 2. TRENDING market: Check trend alignment
            elif regime['regime'] == 'TRENDING':
                direction = regime.get('direction', 'neutral')

                # Check if signal aligns with trend
                is_with_trend = (
                    (signal_type == 'BUY' and direction == 'bullish') or
                    (signal_type == 'SELL' and direction == 'bearish')
                )

                if is_with_trend:
                    # WITH-TREND: Bonus confidence
                    adjustment = TREND_ALIGNMENT_BONUS
                    adjustment_reason = f"WITH-TREND ({signal_type} in {direction} trend)"
                elif direction != 'neutral':
                    # COUNTER-TREND: Penalty
                    adjustment = -COUNTER_TREND_PENALTY
                    adjustment_reason = f"COUNTER-TREND ({signal_type} against {direction} trend)"
                else:
                    # Neutral direction in trending market
                    adjustment_reason = "TRENDING but direction unclear"

            # 3. RANGING market: No adjustment
            elif regime['regime'] == 'RANGING':
                adjustment_reason = "RANGING market (neutral)"

            # Apply adjustment
            confidence = max(0, min(100, confidence + adjustment))

            if adjustment != 0:
                logger.info(
                    f"🎯 Trend-alignment adjustment: {original_confidence:.1f}% → {confidence:.1f}% "
                    f"({adjustment:+.1f}%) - {adjustment_reason}"
                )

            return confidence

        except Exception as e:
            logger.error(f"Error applying trend-alignment adjustment: {e}")
            return confidence  # Return original on error

    def _calculate_entry_sl_tp(self, signal: Dict) -> Tuple[float, float, float]:
        """
        Calculate Entry, Stop Loss, and Take Profit prices based on current market price

        Args:
            signal: Signal dictionary

        Returns:
            Tuple of (entry, sl, tp)
        """
        # Get current price from latest TICK (real-time price)
        from models import Tick
        db = ScopedSession()
        try:
            # Get latest tick for current market price (ticks are global - no account_id)
            latest_tick = db.query(Tick).filter_by(
                symbol=self.symbol
            ).order_by(Tick.timestamp.desc()).first()

            if not latest_tick:
                # Fallback to OHLC if no tick available (OHLC is global - no account_id)
                latest_ohlc = db.query(OHLCData).filter_by(
                    symbol=self.symbol,
                    timeframe=self.timeframe
                ).order_by(OHLCData.timestamp.desc()).first()

                if not latest_ohlc:
                    return (0, 0, 0)

                entry = float(latest_ohlc.close)
            else:
                # Check spread before calculating entry
                spread = abs(float(latest_tick.ask) - float(latest_tick.bid))

                # Calculate average spread from recent ticks (last 100 ticks)
                avg_spread = self._get_average_spread(db)

                # Reject signal if spread is abnormally high
                max_spread_mult = self.config['MAX_SPREAD_MULTIPLIER']
                if avg_spread > 0 and spread > avg_spread * max_spread_mult:
                    logger.warning(
                        f"Spread too high for {self.symbol}: {spread:.5f} "
                        f"(avg: {avg_spread:.5f}, max allowed: {avg_spread * max_spread_mult:.5f}) - rejecting signal"
                    )
                    return (0, 0, 0)  # Reject signal

                # Use BID for SELL, ASK for BUY (realistic entry price)
                if signal['signal_type'] == 'BUY':
                    entry = float(latest_tick.ask)
                else:  # SELL
                    entry = float(latest_tick.bid)

            # Use Smart TP/SL Calculator (hybrid approach: ATR + BB + S/R + Psych)
            from smart_tp_sl import get_smart_tp_sl

            smart_calculator = get_smart_tp_sl(
                self.account_id,
                self.symbol,
                self.timeframe
            )

            tp_sl_result = smart_calculator.calculate(signal['signal_type'], entry)

            # Extract TP/SL from smart calculator result
            tp = tp_sl_result['tp']
            sl = tp_sl_result['sl']

            # Log the reasoning for transparency
            logger.info(
                f"🎯 Smart TP/SL: Entry={entry:.5f} | "
                f"TP={tp:.5f} ({tp_sl_result['tp_reason']}) | "
                f"SL={sl:.5f} ({tp_sl_result['sl_reason']}) | "
                f"R:R={tp_sl_result['risk_reward']}"
            )

            return (
                round(entry, 5),
                sl,  # Already rounded in smart calculator
                tp   # Already rounded in smart calculator
            )

        except Exception as e:
            logger.error(f"Error calculating entry/SL/TP with smart calculator: {e}", exc_info=True)
            # Fallback to simple ATR-based calculation
            try:
                atr_data = self.indicators.calculate_atr()
                atr = atr_data['value'] if atr_data else (entry * 0.002)

                if signal['signal_type'] == 'BUY':
                    sl = entry - (1.5 * atr)
                    tp = entry + (2.5 * atr)
                else:
                    sl = entry + (1.5 * atr)
                    tp = entry - (2.5 * atr)

                logger.warning(f"Using ATR fallback for {self.symbol}")
                return (round(entry, 5), round(sl, 5), round(tp, 5))
            except Exception as e:
                logger.error(f"ATR fallback calculation failed for {self.symbol}: {e}", exc_info=True)
                return (0, 0, 0)
        finally:
            db.close()

    def _get_average_spread(self, db) -> float:
        """
        Calculate average spread from recent ticks

        Args:
            db: Database session

        Returns:
            Average spread (float)
        """
        from models import Tick
        try:
            # Get last 100 ticks for this symbol (ticks are global - no account_id)
            recent_ticks = db.query(Tick).filter_by(
                symbol=self.symbol
            ).order_by(Tick.timestamp.desc()).limit(100).all()

            if not recent_ticks:
                return 0

            # Calculate spreads
            spreads = [abs(float(tick.ask) - float(tick.bid)) for tick in recent_ticks]

            # Return average
            return sum(spreads) / len(spreads)

        except Exception as e:
            logger.error(f"Error calculating average spread: {e}")
            return 0

    def _save_signal(self, signal: Dict):
        """
        Save or update signal in database.

        ✅ NEW LOGIC:
        - If signal exists with SAME direction → UPDATE (confidence, prices, indicators)
        - If signal exists with DIFFERENT direction → EXPIRE old + CREATE new
        - If no signal exists → CREATE new
        - If confidence drops below minimum → EXPIRE signal
        - STORES indicator snapshot for continuous validation

        Args:
            signal: Signal dictionary
        """
        db = ScopedSession()
        try:
            from models import TradingSignal
            from datetime import datetime, timedelta

            # ✅ Capture indicator snapshot for continuous validation
            indicator_snapshot = self._capture_indicator_snapshot(signal)

            # ✅ FIX: Use SELECT FOR UPDATE to prevent race conditions
            # This locks the row so other threads wait until we're done
            # Note: Signals are now global (no account_id)
            existing_signal = db.query(TradingSignal).filter_by(
                symbol=self.symbol,
                timeframe=self.timeframe,
                status='active'
            ).with_for_update().first()

            # Get minimum confidence threshold from config
            min_confidence = self.config['MIN_ACTIVE_CONFIDENCE']

            # Case 1: Signal exists with SAME direction → UPDATE
            if existing_signal and existing_signal.signal_type == signal['signal_type']:
                old_confidence = float(existing_signal.confidence)
                new_confidence = float(signal['confidence'])

                # Check if confidence dropped below minimum
                if new_confidence < min_confidence:
                    existing_signal.status = 'expired'
                    db.commit()
                    logger.warning(
                        f"❌ Signal EXPIRED [ID:{existing_signal.id}]: {self.symbol} {self.timeframe} "
                        f"{signal['signal_type']} - Confidence dropped to {new_confidence:.1f}% (min: {min_confidence}%)"
                    )
                    return

                # Update existing signal (DO NOT update indicator_snapshot - keep original creation conditions)
                existing_signal.confidence = new_confidence
                existing_signal.entry_price = float(signal.get('entry_price', 0))
                existing_signal.sl_price = float(signal.get('sl_price', 0))
                existing_signal.tp_price = float(signal.get('tp_price', 0))
                existing_signal.indicators_used = signal.get('indicators_used', {})
                existing_signal.patterns_detected = signal.get('patterns_detected', [])
                existing_signal.reasons = signal.get('reasons', [])
                existing_signal.updated_at = datetime.utcnow()
                existing_signal.last_validated = datetime.utcnow()
                existing_signal.is_valid = True

                db.commit()

                confidence_change = new_confidence - old_confidence
                change_emoji = "📈" if confidence_change > 0 else "📉" if confidence_change < 0 else "➡️"

                logger.info(
                    f"🔄 Signal UPDATED [ID:{existing_signal.id}]: {self.symbol} {self.timeframe} "
                    f"{signal['signal_type']} | Confidence: {old_confidence:.1f}% → {new_confidence:.1f}% "
                    f"{change_emoji} ({confidence_change:+.1f}%)"
                )
                return

            # Case 2: Signal exists with DIFFERENT direction → EXPIRE old + CREATE new
            elif existing_signal:
                existing_signal.status = 'expired'
                logger.info(
                    f"🔄 Signal direction changed: {existing_signal.signal_type} → {signal['signal_type']}, "
                    f"expiring old signal [ID:{existing_signal.id}]"
                )

            # Case 3: Create new signal with indicator snapshot (signals are now global)
            expiration_hours = self.config['SIGNAL_EXPIRATION_HOURS']
            new_signal = TradingSignal(
                symbol=self.symbol,
                timeframe=self.timeframe,
                signal_type=signal['signal_type'],
                confidence=float(signal['confidence']),
                ml_confidence=float(signal['ml_confidence']) if signal.get('ml_confidence') is not None else None,
                ab_test_group=signal.get('ab_test_group'),
                entry_price=float(signal.get('entry_price', 0)),
                sl_price=float(signal.get('sl_price', 0)),
                tp_price=float(signal.get('tp_price', 0)),
                indicators_used=signal.get('indicators_used', {}),
                patterns_detected=signal.get('patterns_detected', []),
                reasons=signal.get('reasons', []),
                indicator_snapshot=indicator_snapshot,  # ✅ Store creation conditions
                last_validated=datetime.utcnow(),
                is_valid=True,
                status='active',
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=expiration_hours)
            )

            db.add(new_signal)
            db.commit()

            # Link ML prediction to this signal if prediction was logged
            if hasattr(self, 'ml_prediction_id') and self.ml_prediction_id:
                try:
                    from models import MLPrediction
                    ml_pred = db.query(MLPrediction).filter(MLPrediction.id == self.ml_prediction_id).first()
                    if ml_pred:
                        ml_pred.signal_id = new_signal.id
                        db.commit()
                        logger.debug(f"✅ Linked ML prediction {self.ml_prediction_id} to signal {new_signal.id}")
                except Exception as link_error:
                    logger.warning(f"Could not link ML prediction to signal: {link_error}")

            logger.info(
                f"✨ Signal CREATED [ID:{new_signal.id}]: "
                f"{signal['signal_type']} {self.symbol} {self.timeframe} "
                f"(confidence: {signal['confidence']:.1f}%, entry: {signal.get('entry_price', 0):.5f}) "
                f"with {len(indicator_snapshot.get('indicators', {}))} indicators snapshot"
            )

        except Exception as e:
            logger.error(f"Error saving/updating signal: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

    def _capture_indicator_snapshot(self, signal: Dict) -> Dict:
        """
        Capture current state of all indicators and patterns for validation

        IMPORTANT: Now captures ALL indicators from signal['indicators_used'],
        not just a whitelist. This ensures complete data for retrospective analysis.

        Args:
            signal: Signal dictionary with indicators_used and patterns_detected

        Returns:
            Dict containing snapshot of all relevant indicator values
        """
        try:
            snapshot = {
                'timestamp': datetime.utcnow().isoformat(),
                'signal_type': signal['signal_type'],
                'indicators': {},
                'patterns': signal.get('patterns_detected', []),
                'price_levels': {},
                'market_regime': {}
            }

            # Capture ALL indicator values directly from signal
            # This ensures we capture EVERY indicator that contributed to the signal
            for indicator_name, value in signal.get('indicators_used', {}).items():
                try:
                    # Only store valid dict values (skip True/False/None)
                    if isinstance(value, dict):
                        snapshot['indicators'][indicator_name] = value
                    else:
                        logger.debug(f"Skipping {indicator_name} snapshot - invalid type: {type(value)}")
                except Exception as e:
                    logger.warning(f"Failed to capture {indicator_name} snapshot: {e}")

            # Capture market regime information (critical for retrospective analysis)
            try:
                regime = self.indicators.detect_market_regime()
                if regime:
                    snapshot['market_regime'] = {
                        'state': regime.get('regime'),  # TRENDING/RANGING/TOO_WEAK
                        'trend_strength': regime.get('trend_strength'),
                        'volatility': regime.get('volatility'),
                        'direction': regime.get('direction')  # bullish/bearish/neutral
                    }
            except Exception as e:
                logger.warning(f"Failed to capture market regime: {e}")

            # Capture current price for reference
            from models import Tick
            db = ScopedSession()
            try:
                latest_tick = db.query(Tick).filter_by(
                    symbol=self.symbol
                ).order_by(Tick.timestamp.desc()).first()

                if latest_tick:
                    snapshot['price_levels']['bid'] = float(latest_tick.bid)
                    snapshot['price_levels']['ask'] = float(latest_tick.ask)
                    snapshot['price_levels']['spread'] = float(latest_tick.ask) - float(latest_tick.bid)
            finally:
                db.close()

            return snapshot

        except Exception as e:
            logger.error(f"Error capturing indicator snapshot: {e}", exc_info=True)
            return {
                'timestamp': datetime.utcnow().isoformat(),
                'error': str(e)
            }

    def get_multi_timeframe_analysis(self) -> Dict:
        """
        Analyze multiple timeframes for trend alignment

        Returns:
            Dict with analysis for different timeframes
        """
        # Full timeframe spectrum: M1 (scalping) to D1 (long-term trends)
        timeframes = ['M1', 'M5', 'M15', 'H1', 'H4', 'D1']
        analysis = {}

        for tf in timeframes:
            try:
                gen = SignalGenerator(self.account_id, self.symbol, tf)
                signal = gen.generate_signal()
                analysis[tf] = signal
            except Exception as e:
                logger.error(f"Error analyzing {tf}: {e}")
                analysis[tf] = None

        return analysis

    def _check_signal_direction_change(self, new_signal_type: str):
        """
        Check if the signal direction changed (BUY → SELL or SELL → BUY).
        If yes, expire the old signal since conditions have reversed.

        Args:
            new_signal_type: New signal type (BUY or SELL)
        """
        db = ScopedSession()
        try:
            # Find active signal for this symbol/timeframe (signals are now global)
            active_signal = db.query(TradingSignal).filter(
                TradingSignal.symbol == self.symbol,
                TradingSignal.timeframe == self.timeframe,
                TradingSignal.status == 'active'
            ).first()

            # If signal exists and direction changed, expire it
            if active_signal and active_signal.signal_type != new_signal_type:
                active_signal.status = 'expired'
                logger.info(
                    f"✅ Signal #{active_signal.id} ({active_signal.symbol} {active_signal.timeframe}) "
                    f"expired: direction changed from {active_signal.signal_type} to {new_signal_type}"
                )
                db.commit()

        except Exception as e:
            logger.error(f"Error checking signal direction change: {e}")
            db.rollback()
        finally:
            db.close()

    def _apply_ml_enhancement(
        self,
        signal_type: str,
        rules_confidence: float
    ) -> Tuple[Optional[float], float, str]:
        """
        Apply ML model to enhance confidence score

        Args:
            signal_type: 'BUY' or 'SELL'
            rules_confidence: Rules-based confidence (0-100)

        Returns:
            (ml_confidence, final_confidence, ab_test_group)
        """
        if not ML_AVAILABLE:
            # ML not installed - use rules-based confidence
            return (None, rules_confidence, 'rules_only')

        try:
            # Lazy initialization of ML components
            if self.ml_manager is None:
                db = ScopedSession()
                self.ml_manager = MLModelManager(db, self.account_id)
                self.ml_feature_engineer = FeatureEngineer(db, self.account_id)
                db.close()

            # Determine A/B test group
            ab_test_group = self.ml_manager.get_ab_test_group(self.symbol)

            # Extract features for ML
            db = ScopedSession()
            features = self.ml_feature_engineer.extract_features(
                symbol=self.symbol,
                timeframe=self.timeframe,
                timestamp=datetime.utcnow(),
                include_multi_timeframe=True
            )
            db.close()

            # Get ML prediction
            ml_confidence_raw = None
            if ab_test_group in ['ml_only', 'hybrid']:
                db = ScopedSession()
                ml_confidence_raw = self.ml_manager.predict(
                    symbol=self.symbol,
                    features=features,
                    use_global_fallback=True
                )
                db.close()

                # Convert 0-1 to 0-100
                if ml_confidence_raw is not None:
                    ml_confidence_raw = ml_confidence_raw * 100

            # Calculate final confidence based on A/B group
            db = ScopedSession()
            final_confidence = self.ml_manager.get_hybrid_confidence(
                ml_confidence=ml_confidence_raw / 100 if ml_confidence_raw else None,
                rules_confidence=rules_confidence / 100,
                ab_test_group=ab_test_group
            ) * 100  # Convert back to 0-100
            db.close()

            # Log prediction for later evaluation
            db = ScopedSession()
            decision = 'trade' if final_confidence >= 60 else 'no_trade'
            self.ml_prediction_id = self.ml_manager.log_prediction(
                symbol=self.symbol,
                features=features,
                ml_confidence=ml_confidence_raw / 100 if ml_confidence_raw else 0.0,
                rules_confidence=rules_confidence / 100,
                final_confidence=final_confidence / 100,
                decision=decision,
                ab_test_group=ab_test_group
            )
            db.commit()
            db.close()

            ml_conf_str = f"{ml_confidence_raw:.1f}" if ml_confidence_raw is not None else "N/A"
            logger.debug(
                f"ML Enhancement: {self.symbol} {signal_type} | "
                f"Rules: {rules_confidence:.1f}% | "
                f"ML: {ml_conf_str}% | "
                f"Final: {final_confidence:.1f}% | "
                f"Group: {ab_test_group}"
            )

            return (ml_confidence_raw, final_confidence, ab_test_group)

        except Exception as e:
            logger.warning(f"ML enhancement failed, using rules-based confidence: {e}")
            return (None, rules_confidence, 'rules_only')

    def _expire_active_signals(self, reason: str):
        """
        Expire or delete active signals for this symbol/timeframe when conditions no longer apply

        Args:
            reason: Reason for expiration (for logging)
                   If reason is "market closed", signals will be DELETED instead of expired
        """
        db = ScopedSession()
        try:
            # Find active signals for this symbol/timeframe (signals are now global)
            active_signals = db.query(TradingSignal).filter(
                TradingSignal.symbol == self.symbol,
                TradingSignal.timeframe == self.timeframe,
                TradingSignal.status == 'active'
            ).all()

            if active_signals:
                # DELETE signals when market closes (don't keep them as expired)
                if reason == "market closed":
                    for sig in active_signals:
                        logger.info(
                            f"🗑️  Signal #{sig.id} ({sig.symbol} {sig.timeframe} {sig.signal_type}) "
                            f"DELETED: {reason}"
                        )
                        db.delete(sig)
                else:
                    # EXPIRE signals for other reasons (keep in DB for analysis)
                    for sig in active_signals:
                        sig.status = 'expired'
                        logger.info(
                            f"Signal #{sig.id} ({sig.symbol} {sig.timeframe} {sig.signal_type}) "
                            f"expired: {reason}"
                        )

                db.commit()

        except Exception as e:
            logger.error(f"Error expiring/deleting active signals: {e}")
            db.rollback()
        finally:
            db.close()

    def validate_signal(self, signal: TradingSignal) -> bool:
        """
        Validate if a signal's pattern/indicator conditions still apply

        Args:
            signal: TradingSignal database object

        Returns:
            True if signal is still valid, False if conditions no longer apply
        """
        try:
            # Re-generate signal using current data
            current_signal = self.generate_signal()

            # If no signal generated, conditions no longer apply
            if not current_signal:
                logger.info(
                    f"Signal #{signal.id} ({signal.symbol} {signal.timeframe} {signal.signal_type}) "
                    f"no longer valid - no pattern/indicator detected"
                )
                return False

            # If signal direction changed, old signal is invalid
            if current_signal['signal_type'] != signal.signal_type:
                logger.info(
                    f"Signal #{signal.id} ({signal.symbol} {signal.timeframe}) direction changed: "
                    f"{signal.signal_type} → {current_signal['signal_type']}"
                )
                return False

            # If confidence dropped significantly (>20%), signal weakened
            if current_signal['confidence'] < signal.confidence - 20:
                logger.info(
                    f"Signal #{signal.id} ({signal.symbol} {signal.timeframe} {signal.signal_type}) "
                    f"confidence dropped: {signal.confidence}% → {current_signal['confidence']}%"
                )
                return False

            # Signal is still valid
            return True

        except Exception as e:
            logger.error(f"Error validating signal #{signal.id}: {e}")
            # On error, keep signal (don't delete due to technical issues)
            return True

    @staticmethod
    def expire_old_signals():
        """
        Expire old signals (run periodically)
        DELETE signals for symbols outside trading hours (market closed)
        """
        from models import Tick
        from market_hours import is_market_open
        db = ScopedSession()
        try:
            now = datetime.utcnow()

            # Expire signals that passed their expiry time (keep in DB for analysis)
            expired_count = db.query(TradingSignal).filter(
                TradingSignal.status == 'active',
                TradingSignal.expires_at <= now
            ).update({'status': 'expired'})

            # DELETE signals for symbols outside trading hours (market closed)
            active_signals = db.query(TradingSignal).filter(
                TradingSignal.status == 'active'
            ).all()

            deleted_market_closed = 0
            for signal in active_signals:
                # Check if market is open using market_hours configuration
                if not is_market_open(signal.symbol, now):
                    logger.info(
                        f"🗑️  Signal #{signal.id} ({signal.symbol} {signal.timeframe} {signal.signal_type}) "
                        f"DELETED: market closed"
                    )
                    db.delete(signal)
                    deleted_market_closed += 1
                else:
                    # Fallback: Check if symbol is tradeable via tick data
                    latest_tick = db.query(Tick).filter_by(
                        symbol=signal.symbol
                    ).order_by(Tick.timestamp.desc()).first()

                    if latest_tick and not latest_tick.tradeable:
                        logger.info(
                            f"🗑️  Signal #{signal.id} ({signal.symbol} {signal.timeframe} {signal.signal_type}) "
                            f"DELETED: not tradeable (tick flag)"
                        )
                        db.delete(signal)
                        deleted_market_closed += 1

            db.commit()

            if expired_count > 0:
                logger.info(f"Expired {expired_count} old signals")

            if deleted_market_closed > 0:
                logger.info(f"🗑️  Deleted {deleted_market_closed} signals (market closed)")

        except Exception as e:
            logger.error(f"Error expiring signals: {e}")
            db.rollback()
        finally:
            db.close()
