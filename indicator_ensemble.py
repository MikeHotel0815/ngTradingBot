"""
Indicator Ensemble Validator

Validates trading signals using ensemble methods:
- Multiple indicators must agree
- Weighted voting based on historical performance
- Stricter validation for BUY signals

This prevents false signals from single indicator spikes.
"""

import logging
from typing import Dict, List, Tuple
from technical_indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class IndicatorEnsemble:
    """
    Ensemble validator for technical indicators

    Requires multiple indicators to agree before generating a signal.
    Weights indicators based on their historical performance.
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str):
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.indicators = TechnicalIndicators(account_id, symbol, timeframe)

    def validate_signal(self, signal_type: str) -> Dict:
        """
        Validate signal using ensemble of indicators

        Args:
            signal_type: 'BUY' or 'SELL'

        Returns:
            {
                'valid': bool,
                'confidence': float,
                'reasons': List[str],
                'indicators_agreeing': int,
                'indicators_total': int
            }
        """
        try:
            # Get all indicator signals
            indicators = self._get_all_indicators()

            # Count agreement
            agreement = self._count_agreement(indicators, signal_type)

            # Calculate ensemble confidence
            confidence = self._calculate_ensemble_confidence(
                indicators, signal_type, agreement
            )

            # Minimum requirements - INCREASED for better signal quality
            min_agreeing = 4 if signal_type == 'BUY' else 4  # Both need 4/7 indicators
            min_confidence = 70.0 if signal_type == 'BUY' else 65.0  # BUY needs higher confidence

            is_valid = (
                agreement['agreeing'] >= min_agreeing and
                confidence >= min_confidence
            )

            reasons = []
            if is_valid:
                reasons.append(f"{agreement['agreeing']}/{agreement['total']} indicators agree")
                reasons.extend(agreement['agreeing_indicators'])
            else:
                if agreement['agreeing'] < min_agreeing:
                    reasons.append(
                        f"Insufficient consensus: {agreement['agreeing']}/{agreement['total']} "
                        f"(min: {min_agreeing})"
                    )
                if confidence < min_confidence:
                    reasons.append(f"Low confidence: {confidence:.1f}% (min: {min_confidence}%)")

            return {
                'valid': is_valid,
                'confidence': confidence,
                'reasons': reasons,
                'indicators_agreeing': agreement['agreeing'],
                'indicators_total': agreement['total'],
                'disagreeing_indicators': agreement['disagreeing_indicators']
            }

        except Exception as e:
            logger.error(f"Error in ensemble validation: {e}", exc_info=True)
            return {
                'valid': False,
                'confidence': 0.0,
                'reasons': [f"Validation error: {str(e)}"],
                'indicators_agreeing': 0,
                'indicators_total': 0,
                'disagreeing_indicators': []
            }

    def _get_all_indicators(self) -> Dict:
        """Get current values from all indicators"""
        indicators = {}

        try:
            # RSI
            rsi_data = self.indicators.calculate_rsi()
            if rsi_data:
                indicators['RSI'] = {
                    'value': rsi_data['value'],
                    'signal': self._interpret_rsi(rsi_data['value'])
                }

            # MACD
            macd_data = self.indicators.calculate_macd()
            if macd_data:
                indicators['MACD'] = {
                    'value': macd_data,
                    'signal': self._interpret_macd(macd_data)
                }

            # EMA (simple trend check using 20 EMA vs price)
            ema_data = self.indicators.calculate_ema(period=20)
            if ema_data:
                indicators['EMA'] = {
                    'value': ema_data,
                    'signal': self._interpret_ema(ema_data)
                }

            # Bollinger Bands
            bb_data = self.indicators.calculate_bollinger_bands()
            if bb_data:
                indicators['BB'] = {
                    'value': bb_data,
                    'signal': self._interpret_bollinger(bb_data)
                }

            # ADX (Trend Strength)
            adx_data = self.indicators.calculate_adx()
            if adx_data:
                indicators['ADX'] = {
                    'value': adx_data,
                    'signal': self._interpret_adx(adx_data)
                }

            # Stochastic
            stoch_data = self.indicators.calculate_stochastic()
            if stoch_data:
                indicators['STOCH'] = {
                    'value': stoch_data,
                    'signal': self._interpret_stochastic(stoch_data)
                }

            # OBV (Volume)
            obv_data = self.indicators.calculate_obv()
            if obv_data:
                indicators['OBV'] = {
                    'value': obv_data,
                    'signal': self._interpret_obv(obv_data)
                }

        except Exception as e:
            logger.error(f"Error getting indicators: {e}")

        return indicators

    def _interpret_rsi(self, value: float) -> str:
        """Interpret RSI value"""
        if value < 30:
            return 'BUY'  # Oversold
        elif value > 70:
            return 'SELL'  # Overbought
        return 'NEUTRAL'

    def _interpret_macd(self, data: Dict) -> str:
        """Interpret MACD crossover"""
        crossover = data.get('crossover')
        if crossover == 'bullish':
            return 'BUY'
        elif crossover == 'bearish':
            return 'SELL'
        return 'NEUTRAL'

    def _interpret_ema(self, data: Dict) -> str:
        """Interpret EMA trend (price vs EMA)"""
        trend = data.get('trend')
        if trend == 'above':
            return 'BUY'  # Price above EMA = bullish
        elif trend == 'below':
            return 'SELL'  # Price below EMA = bearish
        return 'NEUTRAL'

    def _interpret_bollinger(self, data: Dict) -> str:
        """Interpret Bollinger Bands"""
        position = data.get('position')
        if position == 'oversold':
            return 'BUY'  # Price at/below lower band = oversold
        elif position == 'overbought':
            return 'SELL'  # Price at/above upper band = overbought
        return 'NEUTRAL'

    def _interpret_adx(self, data: Dict) -> str:
        """Interpret ADX (trend strength)"""
        # ADX only measures trend strength, not direction
        # We always return NEUTRAL since ADX confirms but doesn't predict
        # Strong ADX just means "trust the other indicators more"
        return 'NEUTRAL'

    def _interpret_stochastic(self, data: Dict) -> str:
        """Interpret Stochastic oscillator"""
        if data.get('signal') == 'oversold':
            return 'BUY'
        elif data.get('signal') == 'overbought':
            return 'SELL'
        return 'NEUTRAL'

    def _interpret_obv(self, data: Dict) -> str:
        """Interpret On-Balance Volume"""
        # Check for divergences first
        divergence = data.get('divergence')
        if divergence == 'bullish':
            return 'BUY'
        elif divergence == 'bearish':
            return 'SELL'

        # If no divergence, check signal
        signal = data.get('signal')
        if signal == 'bullish':
            return 'BUY'
        elif signal == 'bearish':
            return 'SELL'

        return 'NEUTRAL'

    def _count_agreement(self, indicators: Dict, signal_type: str) -> Dict:
        """Count how many indicators agree with the signal"""
        agreeing = []
        disagreeing = []
        neutral = []

        for name, data in indicators.items():
            signal = data.get('signal', 'NEUTRAL')

            if signal == signal_type:
                agreeing.append(name)
            elif signal == 'NEUTRAL':
                neutral.append(name)
            else:
                disagreeing.append(name)

        return {
            'agreeing': len(agreeing),
            'disagreeing': len(disagreeing),
            'neutral': len(neutral),
            'total': len(indicators),
            'agreeing_indicators': agreeing,
            'disagreeing_indicators': disagreeing,
            'neutral_indicators': neutral
        }

    def _calculate_ensemble_confidence(
        self, indicators: Dict, signal_type: str, agreement: Dict
    ) -> float:
        """
        Calculate ensemble confidence based on:
        - Number of agreeing indicators
        - Strength of each indicator's signal
        - Historical performance (from IndicatorScorer)
        """
        from indicator_scorer import IndicatorScorer

        scorer = IndicatorScorer(self.account_id, self.symbol, self.timeframe)

        # Base confidence from agreement percentage
        agreement_pct = (agreement['agreeing'] / agreement['total']) * 100 if agreement['total'] > 0 else 0

        # Weighted confidence using historical performance
        weighted_sum = 0.0
        total_weight = 0.0

        for name in agreement['agreeing_indicators']:
            weight = scorer.get_indicator_weight(name)
            weighted_sum += weight * 100  # Each agreeing indicator contributes its weight
            total_weight += weight

        # Weighted confidence (0-100)
        weighted_confidence = (weighted_sum / total_weight) if total_weight > 0 else 0

        # Penalty for disagreeing indicators
        disagreement_penalty = agreement['disagreeing'] * 10  # -10% per disagreeing indicator

        # Final confidence
        confidence = (agreement_pct * 0.4 + weighted_confidence * 0.6) - disagreement_penalty

        return max(0, min(100, confidence))


def get_indicator_ensemble(account_id: int, symbol: str, timeframe: str) -> IndicatorEnsemble:
    """Factory function to get IndicatorEnsemble instance"""
    return IndicatorEnsemble(account_id, symbol, timeframe)
