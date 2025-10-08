"""
Smart TP/SL Calculator - Hybrid Approach

Combines multiple factors for realistic and achievable TP/SL levels:
1. ATR-based targets (volatility)
2. Bollinger Bands (statistical boundaries)
3. Support/Resistance levels (technical analysis)
4. Psychologica levels (round numbers)

Goal: Generate REALISTIC targets that are likely to be reached.
"""

import logging
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from database import get_db
from models import OHLCData
from technical_indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class SmartTPSLCalculator:
    """
    Intelligent TP/SL calculation using hybrid approach
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str):
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.indicators = TechnicalIndicators(account_id, symbol, timeframe)

    def calculate(self, signal_type: str, entry_price: float) -> Dict:
        """
        Calculate optimal TP, SL, and trailing stop distance

        Args:
            signal_type: 'BUY' or 'SELL'
            entry_price: Entry price for the trade

        Returns:
            Dict with:
                - tp: Take profit price
                - sl: Stop loss price
                - tp_reason: Why this TP was chosen
                - sl_reason: Why this SL was chosen
                - risk_reward: Risk/Reward ratio
                - trailing_distance_pct: Trailing stop distance in %
        """
        try:
            # Get all candidate levels
            atr = self._get_atr()
            bb_levels = self._get_bollinger_levels()
            sr_levels = self._get_support_resistance_levels()
            psych_levels = self._get_psychological_levels(entry_price)

            # Calculate TP candidates
            tp_candidates = self._calculate_tp_candidates(
                signal_type, entry_price, atr, bb_levels, sr_levels, psych_levels
            )

            # Calculate SL candidates
            sl_candidates = self._calculate_sl_candidates(
                signal_type, entry_price, atr, bb_levels
            )

            # Select best TP (closest realistic target)
            tp, tp_reason = self._select_best_tp(tp_candidates, entry_price, signal_type)

            # Select best SL (tightest safe level)
            sl, sl_reason = self._select_best_sl(sl_candidates, entry_price, signal_type)

            # Validate TP/SL
            if not self._validate_tp_sl(entry_price, tp, sl, signal_type):
                # Fallback to ATR-based if validation fails
                logger.warning(f"TP/SL validation failed, using ATR fallback for {self.symbol}")
                return self._atr_fallback(signal_type, entry_price, atr)

            # Calculate risk/reward
            risk = abs(entry_price - sl)
            reward = abs(tp - entry_price)
            risk_reward = reward / risk if risk > 0 else 0

            # Calculate trailing stop distance (based on ATR, not TP distance)
            trailing_distance_pct = self._calculate_trailing_distance(atr, entry_price)

            logger.info(
                f"🎯 {self.symbol} {signal_type}: Entry={entry_price:.5f} | "
                f"TP={tp:.5f} ({tp_reason}) | SL={sl:.5f} ({sl_reason}) | "
                f"R:R={risk_reward:.2f} | Trail={trailing_distance_pct:.2f}%"
            )

            return {
                'tp': round(tp, 5),
                'sl': round(sl, 5),
                'tp_reason': tp_reason,
                'sl_reason': sl_reason,
                'risk_reward': round(risk_reward, 2),
                'trailing_distance_pct': round(trailing_distance_pct, 2)
            }

        except Exception as e:
            logger.error(f"Error in smart TP/SL calculation: {e}", exc_info=True)
            # Ultimate fallback
            atr = entry_price * 0.002  # 0.2% fallback
            return self._atr_fallback(signal_type, entry_price, atr)

    def _get_atr(self) -> float:
        """Get Average True Range"""
        try:
            atr_data = self.indicators.calculate_atr()
            return atr_data['value'] if atr_data else 0
        except:
            return 0

    def _get_bollinger_levels(self) -> Dict:
        """Get Bollinger Band levels"""
        try:
            bb = self.indicators.calculate_bollinger_bands()
            if bb:
                return {
                    'upper': bb['upper'],
                    'middle': bb['middle'],
                    'lower': bb['lower']
                }
        except:
            pass
        return {}

    def _get_support_resistance_levels(self) -> Dict:
        """
        Find support/resistance levels from recent swing highs/lows
        """
        db = next(get_db())
        try:
            # Get last 50 candles
            candles = db.query(OHLCData).filter_by(
                account_id=self.account_id,
                symbol=self.symbol,
                timeframe=self.timeframe
            ).order_by(OHLCData.timestamp.desc()).limit(50).all()

            if len(candles) < 10:
                return {}

            # Find swing highs and lows
            highs = []
            lows = []

            for i in range(1, len(candles) - 1):
                # Swing High: higher than neighbors
                if float(candles[i].high) > float(candles[i-1].high) and \
                   float(candles[i].high) > float(candles[i+1].high):
                    highs.append(float(candles[i].high))

                # Swing Low: lower than neighbors
                if float(candles[i].low) < float(candles[i-1].low) and \
                   float(candles[i].low) < float(candles[i+1].low):
                    lows.append(float(candles[i].low))

            # Get recent swing points
            return {
                'resistance': highs[:5] if highs else [],  # Last 5 swing highs
                'support': lows[:5] if lows else []        # Last 5 swing lows
            }

        except Exception as e:
            logger.debug(f"Error getting S/R levels: {e}")
            return {}
        finally:
            db.close()

    def _get_psychological_levels(self, current_price: float) -> Dict:
        """
        Calculate nearby psychological levels (round numbers)
        """
        # Determine rounding based on price magnitude
        if current_price > 10000:
            # BTC, indices: round to 1000s
            round_to = 1000
        elif current_price > 1000:
            # Gold: round to 100s
            round_to = 100
        elif current_price > 100:
            # Stocks: round to 10s
            round_to = 10
        elif current_price > 10:
            # Some pairs: round to 1s
            round_to = 1
        else:
            # Forex: round to 0.1 or 0.01
            round_to = 0.01 if current_price > 1 else 0.001

        # Find nearest round levels above and below
        above = round(current_price / round_to + 1) * round_to
        below = round(current_price / round_to - 1) * round_to

        return {
            'above': above,
            'below': below
        }

    def _calculate_tp_candidates(
        self, signal_type: str, entry: float, atr: float,
        bb_levels: Dict, sr_levels: Dict, psych_levels: Dict
    ) -> list:
        """Calculate all TP candidates with distances"""
        candidates = []

        # 1. ATR-based TP (current system: 2.5x ATR)
        if atr > 0:
            atr_tp = entry + (2.5 * atr) if signal_type == 'BUY' else entry - (2.5 * atr)
            candidates.append({
                'price': atr_tp,
                'distance': abs(atr_tp - entry),
                'reason': 'ATR 2.5x'
            })

        # 2. Bollinger Band TP
        if bb_levels:
            if signal_type == 'BUY' and 'upper' in bb_levels:
                candidates.append({
                    'price': bb_levels['upper'],
                    'distance': abs(bb_levels['upper'] - entry),
                    'reason': 'BB Upper'
                })
            elif signal_type == 'SELL' and 'lower' in bb_levels:
                candidates.append({
                    'price': bb_levels['lower'],
                    'distance': abs(bb_levels['lower'] - entry),
                    'reason': 'BB Lower'
                })

        # 3. Support/Resistance TP
        if sr_levels:
            if signal_type == 'BUY' and 'resistance' in sr_levels:
                for r in sr_levels['resistance']:
                    if r > entry:  # Only above entry for BUY
                        candidates.append({
                            'price': r,
                            'distance': abs(r - entry),
                            'reason': f'Resistance {r:.5f}'
                        })
            elif signal_type == 'SELL' and 'support' in sr_levels:
                for s in sr_levels['support']:
                    if s < entry:  # Only below entry for SELL
                        candidates.append({
                            'price': s,
                            'distance': abs(s - entry),
                            'reason': f'Support {s:.5f}'
                        })

        # 4. Psychological levels
        if psych_levels:
            if signal_type == 'BUY' and 'above' in psych_levels and psych_levels['above'] > entry:
                candidates.append({
                    'price': psych_levels['above'],
                    'distance': abs(psych_levels['above'] - entry),
                    'reason': f'Psych Level {psych_levels["above"]:.5f}'
                })
            elif signal_type == 'SELL' and 'below' in psych_levels and psych_levels['below'] < entry:
                candidates.append({
                    'price': psych_levels['below'],
                    'distance': abs(psych_levels['below'] - entry),
                    'reason': f'Psych Level {psych_levels["below"]:.5f}'
                })

        return candidates

    def _calculate_sl_candidates(
        self, signal_type: str, entry: float, atr: float, bb_levels: Dict
    ) -> list:
        """Calculate all SL candidates"""
        candidates = []

        # 1. ATR-based SL (current system: 1.5x ATR)
        if atr > 0:
            atr_sl = entry - (1.5 * atr) if signal_type == 'BUY' else entry + (1.5 * atr)
            candidates.append({
                'price': atr_sl,
                'distance': abs(atr_sl - entry),
                'reason': 'ATR 1.5x'
            })

        # 2. Bollinger Band SL (outside the band)
        if bb_levels:
            if signal_type == 'BUY' and 'lower' in bb_levels:
                # Place SL slightly below lower BB
                bb_sl = bb_levels['lower'] * 0.998  # 0.2% below lower band
                if bb_sl < entry:  # Safety check
                    candidates.append({
                        'price': bb_sl,
                        'distance': abs(bb_sl - entry),
                        'reason': 'BB Lower -0.2%'
                    })
            elif signal_type == 'SELL' and 'upper' in bb_levels:
                # Place SL slightly above upper BB
                bb_sl = bb_levels['upper'] * 1.002  # 0.2% above upper band
                if bb_sl > entry:  # Safety check
                    candidates.append({
                        'price': bb_sl,
                        'distance': abs(bb_sl - entry),
                        'reason': 'BB Upper +0.2%'
                    })

        # 3. SuperTrend SL (already implemented in auto_trader, but good to have here too)
        try:
            supertrend = self.indicators.calculate_supertrend()
            if supertrend and supertrend['value']:
                if (signal_type == 'BUY' and supertrend['direction'] == 'bullish' and supertrend['value'] < entry) or \
                   (signal_type == 'SELL' and supertrend['direction'] == 'bearish' and supertrend['value'] > entry):
                    candidates.append({
                        'price': supertrend['value'],
                        'distance': abs(supertrend['value'] - entry),
                        'reason': 'SuperTrend'
                    })
        except:
            pass

        return candidates

    def _select_best_tp(self, candidates: list, entry: float, signal_type: str) -> Tuple[float, str]:
        """
        Select best TP: Closest realistic target that's at least 1.5x ATR away
        """
        if not candidates:
            # Fallback
            atr = self._get_atr() or (entry * 0.002)
            tp = entry + (2.5 * atr) if signal_type == 'BUY' else entry - (2.5 * atr)
            return tp, 'ATR Fallback'

        # Minimum distance: 1.5x ATR
        atr = self._get_atr() or (entry * 0.002)
        min_distance = 1.5 * atr

        # Filter candidates that are too close
        valid_candidates = [c for c in candidates if c['distance'] >= min_distance]

        if not valid_candidates:
            # If all too close, use the farthest one
            valid_candidates = candidates

        # Sort by distance (closest first)
        valid_candidates.sort(key=lambda x: x['distance'])

        # Return closest realistic target
        best = valid_candidates[0]
        return best['price'], best['reason']

    def _select_best_sl(self, candidates: list, entry: float, signal_type: str) -> Tuple[float, str]:
        """
        Select best SL: Tightest safe level (but not too tight)
        """
        if not candidates:
            # Fallback
            atr = self._get_atr() or (entry * 0.002)
            sl = entry - (1.5 * atr) if signal_type == 'BUY' else entry + (1.5 * atr)
            return sl, 'ATR Fallback'

        # Minimum distance: 1.0x ATR (don't go tighter)
        atr = self._get_atr() or (entry * 0.002)
        min_distance = 1.0 * atr

        # Filter candidates that are too tight
        valid_candidates = [c for c in candidates if c['distance'] >= min_distance]

        if not valid_candidates:
            # All too tight, use ATR-based
            for c in candidates:
                if c['reason'].startswith('ATR'):
                    return c['price'], c['reason']
            # Ultimate fallback
            sl = entry - (1.5 * atr) if signal_type == 'BUY' else entry + (1.5 * atr)
            return sl, 'ATR Fallback Tight'

        # Sort by distance (tightest first)
        valid_candidates.sort(key=lambda x: x['distance'])

        # Return tightest safe level
        best = valid_candidates[0]
        return best['price'], best['reason']

    def _validate_tp_sl(self, entry: float, tp: float, sl: float, signal_type: str) -> bool:
        """
        Validate TP/SL are realistic and safe
        """
        # 1. Check direction
        if signal_type == 'BUY':
            if tp <= entry or sl >= entry:
                return False
        else:  # SELL
            if tp >= entry or sl <= entry:
                return False

        # 2. Check risk/reward minimum (1:1.5)
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk == 0 or reward / risk < 1.5:
            logger.warning(f"Risk/Reward too low: {reward/risk:.2f}")
            return False

        # 3. Check TP not too far (max 5% for most assets, 3% for volatile)
        tp_distance_pct = abs(tp - entry) / entry * 100
        max_distance = 3.0 if self.symbol in ['BTCUSD', 'ETHUSD', 'XAUUSD'] else 5.0

        if tp_distance_pct > max_distance:
            logger.warning(f"TP too far: {tp_distance_pct:.2f}% (max: {max_distance}%)")
            return False

        # 4. Check SL not too tight (min 0.1% for forex, 0.3% for volatile)
        sl_distance_pct = abs(sl - entry) / entry * 100
        min_sl_distance = 0.3 if self.symbol in ['BTCUSD', 'ETHUSD', 'XAUUSD'] else 0.1

        if sl_distance_pct < min_sl_distance:
            logger.warning(f"SL too tight: {sl_distance_pct:.2f}% (min: {min_sl_distance}%)")
            return False

        return True

    def _calculate_trailing_distance(self, atr: float, entry: float) -> float:
        """
        Calculate trailing stop distance in %
        Based on ATR, not TP distance
        """
        if atr == 0:
            atr = entry * 0.002

        # Trailing distance: 1.0x ATR (tighter than TP, but not too tight)
        trailing_distance = 1.0 * atr
        trailing_distance_pct = (trailing_distance / entry) * 100

        # Clamp to reasonable range: 0.5% - 2.0%
        trailing_distance_pct = max(0.5, min(2.0, trailing_distance_pct))

        return trailing_distance_pct

    def _atr_fallback(self, signal_type: str, entry: float, atr: float) -> Dict:
        """Fallback to simple ATR-based calculation"""
        if atr == 0:
            atr = entry * 0.002

        if signal_type == 'BUY':
            tp = entry + (2.5 * atr)
            sl = entry - (1.5 * atr)
        else:
            tp = entry - (2.5 * atr)
            sl = entry + (1.5 * atr)

        risk = abs(entry - sl)
        reward = abs(tp - entry)
        risk_reward = reward / risk if risk > 0 else 1.67

        trailing_distance_pct = self._calculate_trailing_distance(atr, entry)

        return {
            'tp': round(tp, 5),
            'sl': round(sl, 5),
            'tp_reason': 'ATR Fallback',
            'sl_reason': 'ATR Fallback',
            'risk_reward': round(risk_reward, 2),
            'trailing_distance_pct': round(trailing_distance_pct, 2)
        }


def get_smart_tp_sl(account_id: int, symbol: str, timeframe: str) -> SmartTPSLCalculator:
    """Factory function to get SmartTPSLCalculator instance"""
    return SmartTPSLCalculator(account_id, symbol, timeframe)
