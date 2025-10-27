"""
Signal Validator Worker
Continuously validates active signals based on indicator conditions instead of age.
Deletes signals immediately when ANY prerequisite condition no longer holds.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from database import ScopedSession
from models import TradingSignal
from technical_indicators import TechnicalIndicators
from pattern_recognition import PatternRecognizer

logger = logging.getLogger(__name__)


class SignalValidator:
    """
    Validates active signals by re-checking indicator and pattern conditions
    """

    def __init__(self):
        """Initialize Signal Validator"""
        self.validation_interval = 10  # Check every 10 seconds
        self.tolerance_pct = 5.0  # 5% tolerance for indicator value changes

    def run(self):
        """
        Main validation loop - continuously check all active signals
        """
        logger.info("🔍 Signal Validator Worker started")

        while True:
            try:
                self.validate_all_signals()
                time.sleep(self.validation_interval)
            except Exception as e:
                logger.error(f"Error in validation loop: {e}", exc_info=True)
                time.sleep(self.validation_interval)

    def validate_all_signals(self):
        """
        Validate all active signals against their creation conditions
        """
        db = ScopedSession()
        try:
            # Get all active signals with indicator snapshots
            active_signals = db.query(TradingSignal).filter(
                TradingSignal.status == 'active',
                TradingSignal.is_valid == True,
                TradingSignal.indicator_snapshot.isnot(None)
            ).all()

            if not active_signals:
                logger.debug("No active signals to validate")
                return

            logger.info(f"🔍 Validating {len(active_signals)} active signals...")

            validated_count = 0
            invalidated_count = 0

            for signal in active_signals:
                try:
                    is_valid, reasons = self._validate_signal(signal, db)

                    # Update last_validated timestamp
                    signal.last_validated = datetime.utcnow()

                    if not is_valid:
                        # ❌ Signal no longer valid - DELETE it immediately
                        logger.warning(
                            f"❌ Signal INVALID [ID:{signal.id}]: {signal.symbol} {signal.timeframe} "
                            f"{signal.signal_type} - {', '.join(reasons)}"
                        )

                        # Mark as invalid and delete
                        signal.is_valid = False
                        signal.status = 'expired'
                        db.commit()
                        invalidated_count += 1

                        # Send notification if configured
                        self._notify_signal_invalidation(signal, reasons)
                    else:
                        # ✅ Signal still valid
                        signal.is_valid = True
                        db.commit()
                        validated_count += 1

                        logger.debug(
                            f"✅ Signal VALID [ID:{signal.id}]: {signal.symbol} {signal.timeframe} "
                            f"{signal.signal_type}"
                        )

                except Exception as e:
                    logger.error(f"Error validating signal {signal.id}: {e}", exc_info=True)
                    # Don't delete signal on error - might be temporary DB/network issue
                    db.rollback()

            if validated_count > 0 or invalidated_count > 0:
                logger.info(
                    f"📊 Validation complete: {validated_count} valid, "
                    f"{invalidated_count} invalidated and deleted"
                )

        except Exception as e:
            logger.error(f"Error validating signals: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

    def _validate_signal(self, signal: TradingSignal, db) -> tuple[bool, List[str]]:
        """
        Validate a single signal against its indicator snapshot

        Args:
            signal: TradingSignal object
            db: Database session

        Returns:
            Tuple of (is_valid: bool, reasons: List[str])
        """
        reasons = []

        try:
            snapshot = signal.indicator_snapshot
            if not snapshot or 'indicators' not in snapshot:
                reasons.append("No indicator snapshot available")
                return (False, reasons)

            # Initialize indicator calculators
            # NOTE: TradingSignal is GLOBAL (no account_id), but indicators/patterns
            # still need account_id for cache keys. Use default account_id=1.
            indicators = TechnicalIndicators(
                account_id=1,  # Default account for validation
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                cache_ttl=0  # No cache - always get fresh values
            )

            patterns = PatternRecognizer(
                account_id=1,  # Default account for validation
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                cache_ttl=0
            )

            # ✅ Check market hours first
            from market_hours import is_market_open
            if not is_market_open(signal.symbol):
                reasons.append("Market closed")
                return (False, reasons)

            # ✅ Validate each indicator that was part of the signal creation
            for indicator_name, snapshot_value in snapshot.get('indicators', {}).items():
                is_valid, reason = self._validate_indicator(
                    indicator_name,
                    snapshot_value,
                    indicators,
                    signal.signal_type
                )

                if not is_valid:
                    reasons.append(f"{indicator_name}: {reason}")
                    return (False, reasons)  # FAIL FAST - one invalid indicator = delete signal

            # ✅ Validate patterns if they were part of the signal
            snapshot_patterns = snapshot.get('patterns', [])
            if snapshot_patterns:
                current_pattern_signals = patterns.get_pattern_signals()
                current_patterns = [
                    sig['pattern'] for sig in current_pattern_signals
                    if sig['type'] == signal.signal_type
                ]

                # Check if ANY of the original patterns still exists
                pattern_still_valid = any(
                    pattern in current_patterns
                    for pattern in snapshot_patterns
                )

                if not pattern_still_valid:
                    reasons.append(f"Patterns no longer detected: {snapshot_patterns}")
                    return (False, reasons)

            # ✅ All conditions still hold - signal is valid
            return (True, [])

        except Exception as e:
            logger.error(f"Error validating signal {signal.id}: {e}", exc_info=True)
            reasons.append(f"Validation error: {str(e)}")
            return (False, reasons)

    def _validate_indicator(
        self,
        indicator_name: str,
        snapshot_value: Dict,
        indicators: TechnicalIndicators,
        signal_type: str
    ) -> tuple[bool, str]:
        """
        Validate a specific indicator against its snapshot value

        Args:
            indicator_name: Name of indicator (RSI, MACD, etc.)
            snapshot_value: Snapshot value from signal creation
            indicators: TechnicalIndicators instance
            signal_type: BUY or SELL

        Returns:
            Tuple of (is_valid: bool, reason: str)
        """
        try:
            if indicator_name == 'RSI':
                return self._validate_rsi(snapshot_value, indicators, signal_type)
            elif indicator_name == 'MACD':
                return self._validate_macd(snapshot_value, indicators, signal_type)
            elif indicator_name == 'BB':
                return self._validate_bollinger_bands(snapshot_value, indicators, signal_type)
            elif indicator_name in ['Stochastic', 'STOCH']:
                return self._validate_stochastic(snapshot_value, indicators, signal_type)
            elif indicator_name == 'ADX':
                return self._validate_adx(snapshot_value, indicators, signal_type)
            elif indicator_name == 'EMA':
                return self._validate_ema(snapshot_value, indicators, signal_type)
            elif indicator_name == 'EMA_200':
                return self._validate_ema_200(snapshot_value, indicators, signal_type)
            elif indicator_name == 'OBV':
                return self._validate_obv(snapshot_value, indicators, signal_type)
            elif indicator_name == 'VWAP':
                return self._validate_vwap(snapshot_value, indicators, signal_type)
            elif indicator_name == 'SUPERTREND':
                return self._validate_supertrend(snapshot_value, indicators, signal_type)
            elif indicator_name == 'HEIKEN_ASHI_TREND':
                return self._validate_heiken_ashi(snapshot_value, indicators, signal_type)
            elif indicator_name == 'ICHIMOKU':
                return self._validate_ichimoku(snapshot_value, indicators, signal_type)
            else:
                logger.warning(f"Unknown indicator: {indicator_name}")
                return (True, "")  # Don't invalidate on unknown indicator

        except Exception as e:
            logger.error(f"Error validating {indicator_name}: {e}")
            return (False, f"Error: {str(e)}")

    def _validate_rsi(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate RSI indicator"""
        current_rsi = indicators.calculate_rsi()
        if not current_rsi or not isinstance(current_rsi, dict):
            return (False, "RSI data unavailable")

        if not isinstance(snapshot, dict):
            return (False, "RSI snapshot data invalid")

        snapshot_value = snapshot.get('value')
        current_value = current_rsi.get('value') if isinstance(current_rsi, dict) else None

        if snapshot_value is None or current_value is None:
            return (False, "RSI data incomplete")

        # Get RSI signal states (oversold/overbought/neutral)
        snapshot_signal = snapshot.get('signal')
        current_signal = current_rsi.get('signal')

        # Check if RSI signal changed (e.g., from oversold to overbought)
        if snapshot_signal and current_signal:
            # For BUY: was oversold/neutral, shouldn't become overbought
            if signal_type == 'BUY' and snapshot_signal in ['oversold', 'neutral'] and current_signal == 'overbought':
                return (False, f"RSI became overbought ({snapshot_value:.1f} → {current_value:.1f})")

            # For SELL: was overbought/neutral, shouldn't become oversold
            if signal_type == 'SELL' and snapshot_signal in ['overbought', 'neutral'] and current_signal == 'oversold':
                return (False, f"RSI became oversold ({snapshot_value:.1f} → {current_value:.1f})")

        return (True, "")

    def _validate_macd(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate MACD indicator"""
        current_macd = indicators.calculate_macd()
        if not current_macd:
            return (False, "MACD data unavailable")

        snapshot_histogram = snapshot['histogram']
        current_histogram = current_macd['histogram']

        # For BUY: Histogram should still be positive (or became positive)
        if signal_type == 'BUY':
            if snapshot_histogram > 0 and current_histogram < 0:
                return (False, f"MACD histogram turned negative ({snapshot_histogram:.5f} → {current_histogram:.5f})")

        # For SELL: Histogram should still be negative (or became negative)
        elif signal_type == 'SELL':
            if snapshot_histogram < 0 and current_histogram > 0:
                return (False, f"MACD histogram turned positive ({snapshot_histogram:.5f} → {current_histogram:.5f})")

        return (True, "")

    def _validate_bollinger_bands(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate Bollinger Bands indicator"""
        current_bb = indicators.calculate_bollinger_bands()
        if not current_bb:
            return (False, "Bollinger Bands data unavailable")

        # Get current price
        from models import Tick
        db = ScopedSession()
        try:
            latest_tick = db.query(Tick).filter_by(
                symbol=indicators.symbol
            ).order_by(Tick.timestamp.desc()).first()

            if not latest_tick:
                return (False, "No price data available")

            current_price = float(latest_tick.bid if signal_type == 'SELL' else latest_tick.ask)
        finally:
            db.close()

        # For BUY: Price should still be near/below lower band
        if signal_type == 'BUY':
            # If signal was created when price was at lower band, it should not cross to upper band
            if current_price > current_bb['upper']:
                return (False, f"Price crossed to upper BB ({current_price:.5f} > {current_bb['upper']:.5f})")

        # For SELL: Price should still be near/above upper band
        elif signal_type == 'SELL':
            # If signal was created when price was at upper band, it should not cross to lower band
            if current_price < current_bb['lower']:
                return (False, f"Price crossed to lower BB ({current_price:.5f} < {current_bb['lower']:.5f})")

        return (True, "")

    def _validate_stochastic(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate Stochastic indicator"""
        current_stoch = indicators.calculate_stochastic()
        if not current_stoch:
            return (False, "Stochastic data unavailable")

        snapshot_k = snapshot['k']
        current_k = current_stoch['k']

        # For BUY: K should not move from oversold to overbought
        if signal_type == 'BUY':
            if snapshot_k < 20 and current_k > 80:
                return (False, f"Stochastic moved from oversold to overbought ({snapshot_k:.1f} → {current_k:.1f})")

        # For SELL: K should not move from overbought to oversold
        elif signal_type == 'SELL':
            if snapshot_k > 80 and current_k < 20:
                return (False, f"Stochastic moved from overbought to oversold ({snapshot_k:.1f} → {current_k:.1f})")

        return (True, "")

    def _validate_adx(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate ADX indicator"""
        current_adx = indicators.calculate_adx()
        if not current_adx:
            return (False, "ADX data unavailable")

        snapshot_adx = snapshot['adx']
        current_adx_value = current_adx['value']

        # ADX should stay above 25 for strong trends
        if snapshot_adx > 25 and current_adx_value < 20:
            return (False, f"ADX weakened significantly ({snapshot_adx:.1f} → {current_adx_value:.1f})")

        # Check DI direction for BUY/SELL
        if 'plus_di' in snapshot and 'minus_di' in snapshot:
            snapshot_plus = snapshot['plus_di']
            snapshot_minus = snapshot['minus_di']
            current_plus = current_adx.get('plus_di')
            current_minus = current_adx.get('minus_di')

            if current_plus is not None and current_minus is not None:
                # For BUY: +DI should still be above -DI
                if signal_type == 'BUY':
                    if snapshot_plus > snapshot_minus and current_plus < current_minus:
                        return (False, f"ADX direction reversed: +DI < -DI")

                # For SELL: -DI should still be above +DI
                elif signal_type == 'SELL':
                    if snapshot_minus > snapshot_plus and current_minus < current_plus:
                        return (False, f"ADX direction reversed: -DI < +DI")

        return (True, "")

    def _validate_ema(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate EMA indicator"""
        current_ema = indicators.calculate_ema()
        if not current_ema:
            return (False, "EMA data unavailable")

        # Get current price
        from models import Tick
        db = ScopedSession()
        try:
            latest_tick = db.query(Tick).filter_by(
                symbol=indicators.symbol
            ).order_by(Tick.timestamp.desc()).first()

            if not latest_tick:
                return (False, "No price data available")

            current_price = float(latest_tick.bid if signal_type == 'SELL' else latest_tick.ask)
        finally:
            db.close()

        # For BUY: Price should still be above EMA or EMA alignment should be bullish
        if signal_type == 'BUY':
            if 'ema_fast' in current_ema and 'ema_slow' in current_ema:
                # Fast EMA should still be above slow EMA
                if current_ema['ema_fast'] < current_ema['ema_slow']:
                    return (False, "EMA alignment turned bearish")

        # For SELL: Price should still be below EMA or EMA alignment should be bearish
        elif signal_type == 'SELL':
            if 'ema_fast' in current_ema and 'ema_slow' in current_ema:
                # Fast EMA should still be below slow EMA
                if current_ema['ema_fast'] > current_ema['ema_slow']:
                    return (False, "EMA alignment turned bullish")

        return (True, "")

    def _validate_obv(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate OBV indicator"""
        current_obv = indicators.calculate_obv()
        if not current_obv or not isinstance(current_obv, dict):
            return (False, "OBV data unavailable")

        if not isinstance(snapshot, dict):
            return (False, "OBV snapshot data invalid")

        snapshot_trend = snapshot.get('trend')
        current_trend = current_obv.get('trend') if isinstance(current_obv, dict) else None

        if snapshot_trend and current_trend:
            # For BUY: OBV trend should still be bullish
            if signal_type == 'BUY' and snapshot_trend == 'bullish':
                if current_trend == 'bearish':
                    return (False, "OBV trend turned bearish")

            # For SELL: OBV trend should still be bearish
            elif signal_type == 'SELL' and snapshot_trend == 'bearish':
                if current_trend == 'bullish':
                    return (False, "OBV trend turned bullish")

        return (True, "")

    def _validate_vwap(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate VWAP indicator (Volume Weighted Average Price)"""
        current_vwap = indicators.calculate_vwap()
        if not current_vwap or not isinstance(current_vwap, dict):
            return (False, "VWAP data unavailable")

        if not isinstance(snapshot, dict):
            return (False, "VWAP snapshot data invalid")

        # VWAP shows price vs volume-weighted average
        # For BUY: current price should still be near or below VWAP
        # For SELL: current price should still be near or above VWAP
        snapshot_signal = snapshot.get('signal')
        current_signal = current_vwap.get('signal')

        if snapshot_signal and current_signal and snapshot_signal != current_signal:
            return (False, f"VWAP signal changed: {snapshot_signal} → {current_signal}")

        return (True, "")

    def _validate_ema_200(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate EMA 200 indicator"""
        current_ema = indicators.calculate_ema(200)
        if not current_ema or not isinstance(current_ema, dict):
            return (False, "EMA_200 data unavailable")

        if not isinstance(snapshot, dict):
            return (False, "EMA_200 snapshot data invalid")

        # Check if trend direction is still the same
        snapshot_trend = snapshot.get('trend')
        current_trend = current_ema.get('trend')

        if snapshot_trend and current_trend and snapshot_trend != current_trend:
            return (False, f"EMA_200 trend changed: {snapshot_trend} → {current_trend}")

        return (True, "")

    def _validate_supertrend(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate Supertrend indicator"""
        current_st = indicators.calculate_supertrend()
        if not current_st or not isinstance(current_st, dict):
            return (False, "Supertrend data unavailable")

        if not isinstance(snapshot, dict):
            return (False, "Supertrend snapshot data invalid")

        # Supertrend is a trend-following indicator
        # Check if trend signal is still the same
        snapshot_signal = snapshot.get('signal')
        current_signal = current_st.get('signal')

        if snapshot_signal and current_signal and snapshot_signal != current_signal:
            return (False, f"Supertrend signal changed: {snapshot_signal} → {current_signal}")

        return (True, "")

    def _validate_heiken_ashi(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate Heiken Ashi Trend indicator"""
        current_ha = indicators.calculate_heiken_ashi_trend()
        if not current_ha or not isinstance(current_ha, dict):
            return (False, "Heiken Ashi data unavailable")

        if not isinstance(snapshot, dict):
            return (False, "Heiken Ashi snapshot data invalid")

        # Check if trend is still the same
        snapshot_trend = snapshot.get('trend')
        current_trend = current_ha.get('trend')

        if snapshot_trend and current_trend and snapshot_trend != current_trend:
            return (False, f"Heiken Ashi trend changed: {snapshot_trend} → {current_trend}")

        return (True, "")

    def _validate_ichimoku(self, snapshot: Dict, indicators: TechnicalIndicators, signal_type: str) -> tuple[bool, str]:
        """Validate Ichimoku indicator"""
        current_ichimoku = indicators.calculate_ichimoku()
        if not current_ichimoku or not isinstance(current_ichimoku, dict):
            return (False, "Ichimoku data unavailable")

        if not isinstance(snapshot, dict):
            return (False, "Ichimoku snapshot data invalid")

        # Check if cloud signal is still the same
        snapshot_signal = snapshot.get('signal')
        current_signal = current_ichimoku.get('signal')

        if snapshot_signal and current_signal and snapshot_signal != current_signal:
            return (False, f"Ichimoku signal changed: {snapshot_signal} → {current_signal}")

        return (True, "")

    def _notify_signal_invalidation(self, signal: TradingSignal, reasons: List[str]):
        """
        Send notification when signal is invalidated

        Args:
            signal: Invalidated signal
            reasons: Reasons for invalidation
        """
        try:
            from telegram_notifier import get_telegram_notifier
            notifier = get_telegram_notifier()
            message = (
                f"❌ Signal Invalidated\n\n"
                f"Symbol: {signal.symbol}\n"
                f"Timeframe: {signal.timeframe}\n"
                f"Direction: {signal.signal_type}\n"
                f"Confidence: {signal.confidence:.1f}%\n"
                f"Reasons:\n" + "\n".join(f"  • {r}" for r in reasons)
            )
            notifier.send_message(message)
        except Exception as e:
            logger.warning(f"Failed to send invalidation notification: {e}")


def main():
    """Main entry point for signal validator worker"""
    import sys
    import os

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )

    validator = SignalValidator()
    validator.run()


if __name__ == '__main__':
    main()
