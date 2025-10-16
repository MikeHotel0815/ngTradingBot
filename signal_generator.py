"""
Signal Generator Module
Combines pattern recognition and technical indicators to generate trading signals
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from database import ScopedSession
from models import TradingSignal, OHLCData
from technical_indicators import TechnicalIndicators
from pattern_recognition import PatternRecognizer

logger = logging.getLogger(__name__)


class SignalGenerator:
    """
    Generate trading signals by combining patterns and indicators
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str):
        """
        Initialize Signal Generator

        Args:
            account_id: Account ID
            symbol: Trading symbol
            timeframe: Timeframe (M5, M15, H1, H4, D1)
        """
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        # Reduced cache TTL from 300s (default) to 15s for faster signal updates in live trading
        self.indicators = TechnicalIndicators(account_id, symbol, timeframe, cache_ttl=15)
        self.patterns = PatternRecognizer(account_id, symbol, timeframe, cache_ttl=15)

    def generate_signal(self) -> Optional[Dict]:
        """
        Generate trading signal based on patterns and indicators

        Returns:
            Signal dictionary or None if no strong signal
        """
        try:
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

            # ✅ UPDATED: Minimum confidence threshold for signal generation (40%)
            # Note: This is NOT the display/auto-trade threshold
            # - Trading Signals slider controls which signals are SHOWN in UI
            # - Auto-Trade slider controls which signals are AUTO-TRADED
            # This just ensures we don't generate completely weak signals
            # LOWERED from 50% to 40% to match active symbol configs
            MIN_GENERATION_CONFIDENCE = 40

            if signal and signal['confidence'] >= MIN_GENERATION_CONFIDENCE:
                # ✅ NEW: Ensemble validation BEFORE multi-timeframe check
                from indicator_ensemble import get_indicator_ensemble

                ensemble = get_indicator_ensemble(self.account_id, self.symbol, self.timeframe)
                ensemble_result = ensemble.validate_signal(signal['signal_type'])

                if not ensemble_result['valid']:
                    logger.warning(
                        f"⚠️ Ensemble validation FAILED for {self.symbol} {self.timeframe} "
                        f"{signal['signal_type']}: {', '.join(ensemble_result['reasons'])}"
                    )
                    self._expire_active_signals(
                        f"ensemble validation failed: {ensemble_result['reasons'][0]}"
                    )
                    return None

                # Apply ensemble confidence (weighted average with original)
                original_confidence = signal['confidence']
                signal['confidence'] = (original_confidence * 0.6 + ensemble_result['confidence'] * 0.4)

                # Add ensemble info to reasons
                signal['reasons'].append(
                    f"Ensemble: {ensemble_result['indicators_agreeing']}/{ensemble_result['indicators_total']} agree"
                )

                logger.info(
                    f"✅ Ensemble validation PASSED: {self.symbol} {self.timeframe} "
                    f"{signal['signal_type']} | Confidence: {original_confidence:.1f}% → "
                    f"{signal['confidence']:.1f}% | Agreement: {ensemble_result['indicators_agreeing']}/{ensemble_result['indicators_total']}"
                )

                # ✅ NEW: Check multi-timeframe alignment BEFORE calculating TP/SL
                from multi_timeframe_analyzer import check_multi_timeframe_conflict

                mtf_check = check_multi_timeframe_conflict(
                    signal_type=signal['signal_type'],
                    timeframe=self.timeframe,
                    symbol=self.symbol,
                    account_id=self.account_id
                )

                # Apply confidence adjustment from multi-timeframe analysis
                if mtf_check['confidence_adjustment'] != 0:
                    original_confidence = signal['confidence']
                    signal['confidence'] = max(0, min(100,
                        signal['confidence'] + mtf_check['confidence_adjustment']
                    ))

                    # Add MTF info to reasons
                    if mtf_check['reason']:
                        signal['reasons'].append(f"MTF: {mtf_check['reason']}")

                    logger.info(
                        f"🔄 Multi-TF Adjustment: {self.symbol} {self.timeframe} "
                        f"{signal['signal_type']} confidence {original_confidence:.1f}% → "
                        f"{signal['confidence']:.1f}% ({mtf_check['confidence_adjustment']:+.1f}%)"
                    )

                    # Re-check minimum threshold after adjustment
                    if signal['confidence'] < MIN_GENERATION_CONFIDENCE:
                        logger.warning(
                            f"⚠️ Signal rejected after MTF adjustment: "
                            f"{signal['confidence']:.1f}% < {MIN_GENERATION_CONFIDENCE}%"
                        )
                        self._expire_active_signals(
                            f"confidence too low after MTF adjustment ({signal['confidence']:.1f}%)"
                        )
                        return None

                # Calculate entry, SL, TP
                entry, sl, tp = self._calculate_entry_sl_tp(signal)

                signal['entry_price'] = entry
                signal['sl_price'] = sl
                signal['tp_price'] = tp

                # Check if signal direction changed from existing active signal
                self._check_signal_direction_change(signal['signal_type'])

                # Save signal to database
                self._save_signal(signal)

                return signal

            # Signal too weak (< 40%) - expire existing signals
            self._expire_active_signals(f"confidence too low (< {MIN_GENERATION_CONFIDENCE}%)")
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

        # ✅ ENHANCED: Require stronger consensus for BUY signals
        # BUY needs 2+ more signals than SELL to account for downward bias
        buy_count = len(buy_signals)
        sell_count = len(sell_signals)

        signal_type = None
        if buy_count >= sell_count + 2:
            # BUY: Need at least 2 more BUY signals than SELL
            signal_type = 'BUY'
            signals = buy_signals
        elif sell_count > buy_count:
            # SELL: Just need majority
            signal_type = 'SELL'
            signals = sell_signals
        else:
            # Not enough consensus or conflicting signals
            return None

        # Calculate confidence score
        confidence = self._calculate_confidence(
            signals,
            pattern_signals,
            indicator_signals
        )

        # Collect reasons
        reasons = [sig['reason'] for sig in signals]

        # Collect patterns
        patterns_detected = [
            sig['pattern'] for sig in pattern_signals
            if sig['type'] == signal_type
        ]

        # Collect indicators
        indicators_used = {
            sig['indicator']: sig.get('value', True)
            for sig in indicator_signals
            if sig['type'] == signal_type
        }

        return {
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'signal_type': signal_type,
            'confidence': confidence,
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

        Formula:
        - Pattern Reliability: 30%
        - Weighted Indicator Confluence: 40%
        - Signal Strength: 30%

        Uses IndicatorScorer to weight indicators based on historical performance

        Args:
            signals: List of all signals (same direction)
            pattern_signals: List of pattern signals
            indicator_signals: List of indicator signals

        Returns:
            Confidence score (0-100)
        """
        from indicator_scorer import IndicatorScorer

        # Pattern reliability score (0-30)
        pattern_score = 0
        if pattern_signals:
            avg_reliability = sum(
                sig.get('reliability', 50) for sig in pattern_signals
            ) / len(pattern_signals)
            pattern_score = (avg_reliability / 100) * 30

        # Indicator confluence score (0-40) - NOW WEIGHTED BY SYMBOL-SPECIFIC SCORES
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

            # Normalize to 0-40 range
            if total_weight > 0:
                # Average weighted score
                avg_weighted = weighted_score / total_weight

                # Scale to 0-40 (assuming max strength_value is 10)
                indicator_score = (avg_weighted / 10) * 40

                # Bonus for multiple indicators agreeing (confluence)
                confluence_bonus = min(10, len(indicator_signals) * 2)
                indicator_score = min(40, indicator_score + confluence_bonus)

            # ADX bonus: Add confidence if strong trend is present
            adx_signal = next((sig for sig in indicator_signals if sig.get('indicator') == 'ADX'), None)
            if adx_signal and 'Strong Trend' in adx_signal.get('reason', ''):
                indicator_score = min(40, indicator_score + 3)  # +3 bonus for trend confirmation

            # OBV bonus: Add confidence if volume confirms the move
            obv_signal = next((sig for sig in indicator_signals if sig.get('indicator') == 'OBV'), None)
            if obv_signal and 'Divergence' in obv_signal.get('reason', ''):
                indicator_score = min(40, indicator_score + 2)  # +2 bonus for volume divergence

        # Signal strength score (0-30)
        strength_map = {'strong': 30, 'medium': 20, 'weak': 10}
        strength_scores = [
            strength_map.get(sig.get('strength', 'weak'), 10)
            for sig in signals
        ]
        strength_score = sum(strength_scores) / len(strength_scores) if strength_scores else 10

        # Total confidence (before direction adjustment)
        confidence = pattern_score + indicator_score + strength_score

        # ✅ ASYMMETRIC ADJUSTMENT: Penalize BUY signals slightly to account for market bias
        # BUY signals are historically less profitable, so we require higher confidence
        signal_type = signals[0]['type'] if signals else 'UNKNOWN'
        if signal_type == 'BUY':
            # Reduce BUY confidence by 3% to make them harder to trigger (reduced from 5%)
            confidence = max(0, confidence - 3.0)
            logger.debug(f"Applied BUY penalty: confidence reduced by 3%")

        return round(min(100, confidence), 2)

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

                # Reject signal if spread is abnormally high (> 3x normal)
                MAX_SPREAD_MULTIPLIER = 3.0
                if avg_spread > 0 and spread > avg_spread * MAX_SPREAD_MULTIPLIER:
                    logger.warning(
                        f"Spread too high for {self.symbol}: {spread:.5f} "
                        f"(avg: {avg_spread:.5f}, max allowed: {avg_spread * MAX_SPREAD_MULTIPLIER:.5f}) - rejecting signal"
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
        Save signal to database.
        
        First expires any existing active signals for this symbol/timeframe,
        then inserts the new signal.

        Args:
            signal: Signal dictionary
        """
        db = ScopedSession()
        try:
            from models import TradingSignal
            from datetime import datetime, timedelta
            
            # Expire any existing active signals for this symbol/timeframe
            existing = db.query(TradingSignal).filter_by(
                account_id=self.account_id,
                symbol=self.symbol,
                timeframe=self.timeframe,
                status='active'
            ).all()
            
            for sig in existing:
                sig.status = 'expired'
            
            # Create new signal
            new_signal = TradingSignal(
                account_id=self.account_id,
                symbol=self.symbol,
                timeframe=self.timeframe,
                signal_type=signal['signal_type'],
                confidence=float(signal['confidence']),
                entry_price=float(signal.get('entry_price', 0)),
                sl_price=float(signal.get('sl_price', 0)),
                tp_price=float(signal.get('tp_price', 0)),
                indicators_used=signal.get('indicators_used', {}),
                patterns_detected=signal.get('patterns_detected', []),
                reasons=signal.get('reasons', []),
                status='active',
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=24)
            )
            
            db.add(new_signal)
            db.commit()

            logger.info(
                f"✓ Signal created [ID:{new_signal.id}]: "
                f"{signal['signal_type']} {self.symbol} {self.timeframe} "
                f"(confidence: {signal['confidence']}%, entry: {signal.get('entry_price', 0):.5f})"
            )

        except Exception as e:
            logger.error(f"Error saving signal: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

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
            # Find active signal for this symbol/timeframe
            active_signal = db.query(TradingSignal).filter(
                TradingSignal.account_id == self.account_id,
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

    def _expire_active_signals(self, reason: str):
        """
        Expire active signals for this symbol/timeframe when conditions no longer apply

        Args:
            reason: Reason for expiration (for logging)
        """
        db = ScopedSession()
        try:
            # Find active signals for this symbol/timeframe
            active_signals = db.query(TradingSignal).filter(
                TradingSignal.account_id == self.account_id,
                TradingSignal.symbol == self.symbol,
                TradingSignal.timeframe == self.timeframe,
                TradingSignal.status == 'active'
            ).all()

            if active_signals:
                for sig in active_signals:
                    sig.status = 'expired'
                    logger.info(
                        f"Signal #{sig.id} ({sig.symbol} {sig.timeframe} {sig.signal_type}) "
                        f"expired: {reason}"
                    )

                db.commit()

        except Exception as e:
            logger.error(f"Error expiring active signals: {e}")
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
        """
        from models import Tick
        db = ScopedSession()
        try:
            now = datetime.utcnow()

            # Expire signals that passed their expiry time
            expired_count = db.query(TradingSignal).filter(
                TradingSignal.status == 'active',
                TradingSignal.expires_at <= now
            ).update({'status': 'expired'})

            # Also expire signals for symbols outside trading hours
            active_signals = db.query(TradingSignal).filter(
                TradingSignal.status == 'active'
            ).all()

            non_tradeable_expired = 0
            for signal in active_signals:
                # Check if symbol is tradeable (ticks are global - no account_id)
                latest_tick = db.query(Tick).filter_by(
                    symbol=signal.symbol
                ).order_by(Tick.timestamp.desc()).first()

                if latest_tick and not latest_tick.tradeable:
                    signal.status = 'expired'
                    non_tradeable_expired += 1

            db.commit()

            if expired_count > 0:
                logger.info(f"Expired {expired_count} old signals")

            if non_tradeable_expired > 0:
                logger.info(f"Expired {non_tradeable_expired} signals (outside trading hours)")

        except Exception as e:
            logger.error(f"Error expiring signals: {e}")
            db.rollback()
        finally:
            db.close()
