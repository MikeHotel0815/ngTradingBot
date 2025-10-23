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
            # ✅ Check if market is open for this symbol
            from market_hours import is_market_open
            if not is_market_open(self.symbol):
                logger.debug(f"Market closed for {self.symbol}, skipping signal generation")
                self._expire_active_signals("market closed")
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

            # ✅ UPDATED: Minimum confidence threshold for signal generation (45%)
            # Note: This is NOT the display/auto-trade threshold
            # - Trading Signals slider controls which signals are SHOWN in UI
            # - Auto-Trade slider controls which signals are AUTO-TRADED
            # This ensures we generate only moderately strong signals
            # OPTIMIZED to 50% based on performance analysis (2025-10-22)
            # Analysis showed: 50-60% confidence → 94.7% Win Rate vs 70-80% → 71.4% Win Rate
            # - Prevents weak signals from entering the system
            # - Filter systems will boost quality signals to 60-70%+
            MIN_GENERATION_CONFIDENCE = 50

            if signal and signal['confidence'] >= MIN_GENERATION_CONFIDENCE:
                # ✅ SIMPLIFIED: REMOVED overengineered filters!
                # REMOVED: Loss-adaptive filter (unused, added complexity)
                # REMOVED: Ensemble validation (blocked 84-100% win rate signals!)
                # REMOVED: Multi-timeframe analyzer (unused, overengineered)
                #
                # REASON: We already have 84-100% win rates with just:
                # - Pattern Recognition ✅
                # - Technical Indicators ✅
                # - 50% minimum confidence ✅
                #
                # The additional filters were blocking profitable signals (DE40.c 100% win rate!)
                # KISS principle: Keep It Simple, Stupid

                logger.info(
                    f"✅ Signal PASSED: {self.symbol} {self.timeframe} "
                    f"{signal['signal_type']} | Confidence: {signal['confidence']:.1f}%"
                )

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

        # ✅ CONFIGURABLE: BUY signal consensus requirement
        # NOTE: Adjusted based on parameter analysis (2025-10-21)
        # - 0 = No bias (simple majority for both)
        # - 1 = BUY needs 1 more confirming signal than SELL
        # - 2 = BUY needs 2 more confirming signals than SELL (PROVEN BETTER - 2025-10-22)
        # REVERTED to 2 based on performance analysis showing better results with conservative BUY filtering
        # Historical data: Lower confidence + advantage=1 correlated with losses
        # Multi-layer validation (Ensemble/MTF/Regime) provides additional filtering
        BUY_SIGNAL_ADVANTAGE = 2  # Conservative: requires stronger BUY confirmation

        buy_count = len(buy_signals)
        sell_count = len(sell_signals)

        signal_type = None
        if buy_count >= sell_count + BUY_SIGNAL_ADVANTAGE:
            # BUY: Need advantage over SELL signals
            signal_type = 'BUY'
            signals = buy_signals
            logger.debug(
                f"BUY signal consensus: {buy_count} BUY vs {sell_count} SELL "
                f"(advantage: {BUY_SIGNAL_ADVANTAGE})"
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
                f"(BUY needs {sell_count + BUY_SIGNAL_ADVANTAGE})"
            )
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

        # ✅ CONFIGURABLE: BUY signal confidence penalty
        # NOTE: Adjusted based on parameter analysis (2025-10-21)
        # - 0.0 = No penalty (treat BUY and SELL equally)
        # - 2.0 = Reduce BUY confidence by 2% (CURRENT - more balanced)
        # - 3.0 = Reduce BUY confidence by 3% (TOO HARSH)
        # - 5.0 = Reduce BUY confidence by 5% (way too conservative)
        # CHANGED from 3.0 to 2.0 to reduce double-penalty on BUY signals
        # (Already have BUY_SIGNAL_ADVANTAGE, don't need harsh penalty too)
        BUY_CONFIDENCE_PENALTY = 2.0  # Reduced: -2% for BUY signals

        signal_type = signals[0]['type'] if signals else 'UNKNOWN'
        if signal_type == 'BUY' and BUY_CONFIDENCE_PENALTY > 0:
            # Reduce BUY confidence to make them harder to trigger
            original_confidence = confidence
            confidence = max(0, confidence - BUY_CONFIDENCE_PENALTY)
            logger.debug(
                f"Applied BUY penalty: {original_confidence:.1f}% → {confidence:.1f}% "
                f"(-{BUY_CONFIDENCE_PENALTY}%)"
            )

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

            # Check for existing active signal
            existing_signal = db.query(TradingSignal).filter_by(
                account_id=self.account_id,
                symbol=self.symbol,
                timeframe=self.timeframe,
                status='active'
            ).first()

            MIN_CONFIDENCE_THRESHOLD = 50  # Expire signals below this (raised from 40% for more conservative approach)

            # Case 1: Signal exists with SAME direction → UPDATE
            if existing_signal and existing_signal.signal_type == signal['signal_type']:
                old_confidence = float(existing_signal.confidence)
                new_confidence = float(signal['confidence'])

                # Check if confidence dropped below minimum
                if new_confidence < MIN_CONFIDENCE_THRESHOLD:
                    existing_signal.status = 'expired'
                    db.commit()
                    logger.warning(
                        f"❌ Signal EXPIRED [ID:{existing_signal.id}]: {self.symbol} {self.timeframe} "
                        f"{signal['signal_type']} - Confidence dropped to {new_confidence:.1f}% (min: {MIN_CONFIDENCE_THRESHOLD}%)"
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

            # Case 3: Create new signal with indicator snapshot
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
                indicator_snapshot=indicator_snapshot,  # ✅ Store creation conditions
                last_validated=datetime.utcnow(),
                is_valid=True,
                status='active',
                created_at=datetime.utcnow(),
                expires_at=datetime.utcnow() + timedelta(hours=24)
            )

            db.add(new_signal)
            db.commit()

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
                'price_levels': {}
            }

            # Capture indicator values
            for indicator_name, value in signal.get('indicators_used', {}).items():
                try:
                    if indicator_name == 'RSI':
                        rsi_data = self.indicators.calculate_rsi()
                        snapshot['indicators']['RSI'] = {
                            'value': rsi_data['value'],
                            'overbought': rsi_data.get('overbought', 70),
                            'oversold': rsi_data.get('oversold', 30)
                        }
                    elif indicator_name == 'MACD':
                        macd_data = self.indicators.calculate_macd()
                        snapshot['indicators']['MACD'] = {
                            'macd': macd_data['macd'],
                            'signal': macd_data['signal'],
                            'histogram': macd_data['histogram']
                        }
                    elif indicator_name == 'BB':
                        bb_data = self.indicators.calculate_bollinger_bands()
                        snapshot['indicators']['BB'] = {
                            'upper': bb_data['upper'],
                            'middle': bb_data['middle'],
                            'lower': bb_data['lower']
                        }
                    elif indicator_name == 'Stochastic':
                        stoch_data = self.indicators.calculate_stochastic()
                        snapshot['indicators']['Stochastic'] = {
                            'k': stoch_data['k'],
                            'd': stoch_data['d']
                        }
                    elif indicator_name == 'ADX':
                        adx_data = self.indicators.calculate_adx()
                        snapshot['indicators']['ADX'] = {
                            'adx': adx_data['value'],
                            'plus_di': adx_data.get('plus_di'),
                            'minus_di': adx_data.get('minus_di')
                        }
                    elif indicator_name == 'ATR':
                        atr_data = self.indicators.calculate_atr()
                        snapshot['indicators']['ATR'] = {
                            'value': atr_data['value']
                        }
                    elif indicator_name == 'EMA':
                        ema_data = self.indicators.calculate_ema()
                        snapshot['indicators']['EMA'] = ema_data
                    elif indicator_name == 'OBV':
                        obv_data = self.indicators.calculate_obv()
                        snapshot['indicators']['OBV'] = {
                            'value': obv_data['value'],
                            'trend': obv_data.get('trend')
                        }
                except Exception as e:
                    logger.warning(f"Failed to capture {indicator_name} snapshot: {e}")

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
