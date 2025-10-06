"""
Technical Indicators Module
Calculates technical indicators using TA-Lib with Redis caching
"""

import logging
import talib
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from redis_client import get_redis
from database import ScopedSession
from models import OHLCData, IndicatorValue
import json

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """
    Calculate technical indicators with Redis caching
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str, cache_ttl: int = 300):
        """
        Initialize Technical Indicators

        Args:
            account_id: Account ID
            symbol: Trading symbol (e.g., EURUSD)
            timeframe: Timeframe (M5, M15, H1, H4, D1)
            cache_ttl: Cache TTL in seconds (default: 300 = 5 minutes)
        """
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.cache_ttl = cache_ttl
        self.redis = get_redis()

    def _cache_key(self, indicator_name: str) -> str:
        """Generate Redis cache key"""
        return f"indicator:{self.account_id}:{self.symbol}:{self.timeframe}:{indicator_name}"

    def _get_cached(self, indicator_name: str) -> Optional[Dict]:
        """Get cached indicator value from Redis"""
        try:
            key = self._cache_key(indicator_name)
            cached = self.redis.client.get(key)
            if cached:
                return json.loads(cached)
            return None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None

    def _set_cache(self, indicator_name: str, value: Dict):
        """Set indicator value in Redis cache"""
        try:
            key = self._cache_key(indicator_name)
            self.redis.client.setex(
                key,
                self.cache_ttl,
                json.dumps(value)
            )
        except Exception as e:
            logger.error(f"Cache set error: {e}")

    def _get_ohlc_data(self, limit: int = 200) -> Optional[pd.DataFrame]:
        """
        Get OHLC data from database

        Args:
            limit: Number of candles to retrieve

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        db = ScopedSession()
        try:
            ohlc = db.query(OHLCData).filter_by(
                account_id=self.account_id,
                symbol=self.symbol,
                timeframe=self.timeframe
            ).order_by(OHLCData.timestamp.desc()).limit(limit).all()

            if not ohlc:
                logger.warning(f"No OHLC data found for {self.symbol} {self.timeframe}")
                return None

            # Convert to DataFrame (reverse to chronological order)
            df = pd.DataFrame([{
                'timestamp': o.timestamp,
                'open': float(o.open),
                'high': float(o.high),
                'low': float(o.low),
                'close': float(o.close),
                'volume': float(o.volume) if o.volume else 0
            } for o in reversed(ohlc)])

            return df

        except Exception as e:
            logger.error(f"Error getting OHLC data: {e}")
            return None
        finally:
            db.close()

    def calculate_rsi(self, period: int = 14) -> Optional[Dict]:
        """
        Calculate RSI (Relative Strength Index)

        Args:
            period: RSI period (default: 14)

        Returns:
            Dict with RSI value and signal
        """
        indicator_name = f"RSI_{period}"

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data()
        if df is None or len(df) < period + 1:
            return None

        # Calculate RSI
        close = df['close'].values
        rsi = talib.RSI(close, timeperiod=period)

        current_rsi = float(rsi[-1])

        # Determine signal
        signal = 'neutral'
        if current_rsi > 70:
            signal = 'overbought'
        elif current_rsi < 30:
            signal = 'oversold'

        result = {
            'value': round(current_rsi, 2),
            'signal': signal,
            'period': period,
            'calculated_at': datetime.utcnow().isoformat()
        }

        # Cache result
        self._set_cache(indicator_name, result)

        return result

    def calculate_macd(self, fast: int = 12, slow: int = 26, signal: int = 9) -> Optional[Dict]:
        """
        Calculate MACD (Moving Average Convergence Divergence)

        Args:
            fast: Fast EMA period (default: 12)
            slow: Slow EMA period (default: 26)
            signal: Signal line period (default: 9)

        Returns:
            Dict with MACD line, signal line, histogram, and crossover signal
        """
        indicator_name = f"MACD_{fast}_{slow}_{signal}"

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data()
        if df is None or len(df) < slow + signal:
            return None

        # Calculate MACD
        close = df['close'].values
        macd, macd_signal, macd_hist = talib.MACD(
            close,
            fastperiod=fast,
            slowperiod=slow,
            signalperiod=signal
        )

        current_macd = float(macd[-1])
        current_signal = float(macd_signal[-1])
        current_hist = float(macd_hist[-1])
        prev_hist = float(macd_hist[-2])

        # Determine crossover signal
        crossover = 'neutral'
        if prev_hist < 0 and current_hist > 0:
            crossover = 'bullish'
        elif prev_hist > 0 and current_hist < 0:
            crossover = 'bearish'

        result = {
            'macd': round(current_macd, 5),
            'signal': round(current_signal, 5),
            'histogram': round(current_hist, 5),
            'crossover': crossover,
            'calculated_at': datetime.utcnow().isoformat()
        }

        # Cache result
        self._set_cache(indicator_name, result)

        return result

    def calculate_ema(self, period: int = 20) -> Optional[Dict]:
        """
        Calculate EMA (Exponential Moving Average)

        Args:
            period: EMA period (default: 20)

        Returns:
            Dict with EMA value and trend signal
        """
        indicator_name = f"EMA_{period}"

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data()
        if df is None or len(df) < period:
            return None

        # Calculate EMA
        close = df['close'].values
        ema = talib.EMA(close, timeperiod=period)

        current_ema = float(ema[-1])
        current_price = float(close[-1])

        # Determine trend
        trend = 'neutral'
        if current_price > current_ema:
            trend = 'above'  # Price above EMA (bullish)
        elif current_price < current_ema:
            trend = 'below'  # Price below EMA (bearish)

        result = {
            'value': round(current_ema, 5),
            'current_price': round(current_price, 5),
            'trend': trend,
            'period': period,
            'calculated_at': datetime.utcnow().isoformat()
        }

        # Cache result
        self._set_cache(indicator_name, result)

        return result

    def calculate_bollinger_bands(self, period: int = 20, std_dev: float = 2.0) -> Optional[Dict]:
        """
        Calculate Bollinger Bands

        Args:
            period: MA period (default: 20)
            std_dev: Standard deviations (default: 2.0)

        Returns:
            Dict with upper, middle, lower bands and position signal
        """
        indicator_name = f"BB_{period}_{std_dev}"

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data()
        if df is None or len(df) < period:
            return None

        # Calculate Bollinger Bands
        close = df['close'].values
        upper, middle, lower = talib.BBANDS(
            close,
            timeperiod=period,
            nbdevup=std_dev,
            nbdevdn=std_dev,
            matype=0
        )

        current_price = float(close[-1])
        current_upper = float(upper[-1])
        current_middle = float(middle[-1])
        current_lower = float(lower[-1])

        # Determine position
        position = 'neutral'
        if current_price >= current_upper:
            position = 'overbought'
        elif current_price <= current_lower:
            position = 'oversold'
        elif current_price > current_middle:
            position = 'above_middle'
        elif current_price < current_middle:
            position = 'below_middle'

        result = {
            'upper': round(current_upper, 5),
            'middle': round(current_middle, 5),
            'lower': round(current_lower, 5),
            'current_price': round(current_price, 5),
            'position': position,
            'period': period,
            'calculated_at': datetime.utcnow().isoformat()
        }

        # Cache result
        self._set_cache(indicator_name, result)

        return result

    def calculate_atr(self, period: int = 14) -> Optional[Dict]:
        """
        Calculate ATR (Average True Range) - for volatility and stop-loss

        Args:
            period: ATR period (default: 14)

        Returns:
            Dict with ATR value
        """
        indicator_name = f"ATR_{period}"

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data()
        if df is None or len(df) < period:
            return None

        # Calculate ATR
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        atr = talib.ATR(high, low, close, timeperiod=period)

        current_atr = float(atr[-1])

        result = {
            'value': round(current_atr, 5),
            'period': period,
            'calculated_at': datetime.utcnow().isoformat()
        }

        # Cache result
        self._set_cache(indicator_name, result)

        return result

    def calculate_stochastic(self, k_period: int = 14, d_period: int = 3) -> Optional[Dict]:
        """
        Calculate Stochastic Oscillator

        Args:
            k_period: %K period (default: 14)
            d_period: %D period (default: 3)

        Returns:
            Dict with %K, %D and signal
        """
        indicator_name = f"STOCH_{k_period}_{d_period}"

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data()
        if df is None or len(df) < k_period + d_period:
            return None

        # Calculate Stochastic
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values
        k, d = talib.STOCH(
            high, low, close,
            fastk_period=k_period,
            slowk_period=d_period,
            slowk_matype=0,
            slowd_period=d_period,
            slowd_matype=0
        )

        current_k = float(k[-1])
        current_d = float(d[-1])

        # Determine signal
        signal = 'neutral'
        if current_k > 80 and current_d > 80:
            signal = 'overbought'
        elif current_k < 20 and current_d < 20:
            signal = 'oversold'

        result = {
            'k': round(current_k, 2),
            'd': round(current_d, 2),
            'signal': signal,
            'calculated_at': datetime.utcnow().isoformat()
        }

        # Cache result
        self._set_cache(indicator_name, result)

        return result

    def calculate_adx(self, period: int = 14) -> Optional[Dict]:
        """
        Calculate ADX (Average Directional Index) - measures trend strength

        Args:
            period: ADX period (default: 14)

        Returns:
            Dict with ADX value and signal
        """
        indicator_name = f'ADX_{period}'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data(limit=period * 3)
        if df is None or len(df) < period + 1:
            return None

        try:
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values

            # Calculate ADX
            adx = talib.ADX(high, low, close, timeperiod=period)

            # Get current value
            current_adx = float(adx[-1])

            # ADX interpretation:
            # 0-25: Absent or weak trend
            # 25-50: Strong trend
            # 50-75: Very strong trend
            # 75-100: Extremely strong trend

            if current_adx < 25:
                trend_strength = 'weak'
                signal = 'ranging'  # No clear trend, avoid trend-following strategies
            elif current_adx < 50:
                trend_strength = 'strong'
                signal = 'trending'
            elif current_adx < 75:
                trend_strength = 'very_strong'
                signal = 'trending'
            else:
                trend_strength = 'extreme'
                signal = 'trending'

            result = {
                'value': round(current_adx, 2),
                'trend_strength': trend_strength,
                'signal': signal,
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"ADX calculation error: {e}")
            return None

    def calculate_sma(self, period: int = 20) -> Optional[Dict]:
        """
        Calculate SMA (Simple Moving Average)

        Args:
            period: SMA period (default: 20)

        Returns:
            Dict with SMA value and trend signal
        """
        indicator_name = f'SMA_{period}'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data(limit=period * 2)
        if df is None or len(df) < period + 1:
            return None

        try:
            close = df['close'].values

            # Calculate SMA
            sma = talib.SMA(close, timeperiod=period)

            # Get current values
            current_sma = float(sma[-1])
            current_price = float(close[-1])
            previous_price = float(close[-2])
            previous_sma = float(sma[-2])

            # Determine signal
            if current_price > current_sma:
                signal = 'bullish'
                position = 'above'
            elif current_price < current_sma:
                signal = 'bearish'
                position = 'below'
            else:
                signal = 'neutral'
                position = 'at'

            # Detect crossovers
            crossover = None
            if previous_price <= previous_sma and current_price > current_sma:
                crossover = 'golden_cross'  # Bullish crossover
                signal = 'bullish'
            elif previous_price >= previous_sma and current_price < current_sma:
                crossover = 'death_cross'  # Bearish crossover
                signal = 'bearish'

            # Calculate distance from SMA (in percentage)
            distance_pct = ((current_price - current_sma) / current_sma) * 100

            result = {
                'value': round(current_sma, 5),
                'current_price': round(current_price, 5),
                'signal': signal,
                'position': position,
                'crossover': crossover,
                'distance_pct': round(distance_pct, 2),
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"SMA calculation error: {e}")
            return None

    def calculate_obv(self) -> Optional[Dict]:
        """
        Calculate OBV (On-Balance Volume) - volume-based momentum indicator

        Returns:
            Dict with OBV value and trend signal
        """
        indicator_name = 'OBV'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data (need more data for trend detection)
        df = self._get_ohlc_data(limit=50)
        if df is None or len(df) < 20:
            return None

        try:
            close = df['close'].values.astype(float)
            volume = df['volume'].values.astype(float)

            # Calculate OBV
            obv = talib.OBV(close, volume)

            # Get current value
            current_obv = float(obv[-1])

            # Calculate OBV trend (using SMA of OBV)
            obv_sma = talib.SMA(obv, timeperiod=10)
            current_obv_sma = float(obv_sma[-1])

            # Determine signal
            if current_obv > current_obv_sma:
                signal = 'bullish'
                trend = 'rising'
            elif current_obv < current_obv_sma:
                signal = 'bearish'
                trend = 'falling'
            else:
                signal = 'neutral'
                trend = 'flat'

            # Check for divergence (simplified)
            # Compare price trend vs OBV trend over last 10 candles
            price_change = (close[-1] - close[-10]) / close[-10]
            obv_change = (obv[-1] - obv[-10]) / abs(obv[-10]) if obv[-10] != 0 else 0

            divergence = None
            if price_change > 0 and obv_change < 0:
                divergence = 'bearish'  # Price up, OBV down = bearish divergence
            elif price_change < 0 and obv_change > 0:
                divergence = 'bullish'  # Price down, OBV up = bullish divergence

            result = {
                'value': round(current_obv, 2),
                'signal': signal,
                'trend': trend,
                'divergence': divergence,
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"OBV calculation error: {e}")
            return None

    def calculate_all(self) -> Dict[str, any]:
        """
        Calculate all indicators

        Returns:
            Dict with all indicator values
        """
        indicators = {}

        # Trend indicators
        indicators['RSI'] = self.calculate_rsi()
        indicators['MACD'] = self.calculate_macd()
        indicators['EMA_20'] = self.calculate_ema(20)
        indicators['EMA_50'] = self.calculate_ema(50)
        indicators['EMA_200'] = self.calculate_ema(200)
        indicators['SMA_20'] = self.calculate_sma(20)
        indicators['SMA_50'] = self.calculate_sma(50)
        indicators['SMA_200'] = self.calculate_sma(200)
        indicators['ADX'] = self.calculate_adx()

        # Volatility indicators
        indicators['BB'] = self.calculate_bollinger_bands()
        indicators['ATR'] = self.calculate_atr()

        # Momentum indicators
        indicators['STOCH'] = self.calculate_stochastic()

        # Volume indicators
        indicators['OBV'] = self.calculate_obv()

        return indicators

    def get_indicator_signals(self) -> List[Dict]:
        """
        Extract trading signals from indicators

        Returns:
            List of signal dictionaries
        """
        indicators = self.calculate_all()
        signals = []

        # RSI signals
        if indicators['RSI']:
            rsi = indicators['RSI']
            if rsi['signal'] == 'oversold':
                signals.append({
                    'indicator': 'RSI',
                    'type': 'BUY',
                    'reason': f"RSI Oversold ({rsi['value']})",
                    'strength': 'medium'
                })
            elif rsi['signal'] == 'overbought':
                signals.append({
                    'indicator': 'RSI',
                    'type': 'SELL',
                    'reason': f"RSI Overbought ({rsi['value']})",
                    'strength': 'medium'
                })

        # MACD signals
        if indicators['MACD']:
            macd = indicators['MACD']
            if macd['crossover'] == 'bullish':
                signals.append({
                    'indicator': 'MACD',
                    'type': 'BUY',
                    'reason': 'MACD Bullish Crossover',
                    'strength': 'strong'
                })
            elif macd['crossover'] == 'bearish':
                signals.append({
                    'indicator': 'MACD',
                    'type': 'SELL',
                    'reason': 'MACD Bearish Crossover',
                    'strength': 'strong'
                })

        # EMA trend signals
        if indicators['EMA_200']:
            ema = indicators['EMA_200']
            if ema['trend'] == 'above':
                signals.append({
                    'indicator': 'EMA_200',
                    'type': 'BUY',
                    'reason': 'Price Above 200 EMA',
                    'strength': 'weak'
                })
            elif ema['trend'] == 'below':
                signals.append({
                    'indicator': 'EMA_200',
                    'type': 'SELL',
                    'reason': 'Price Below 200 EMA',
                    'strength': 'weak'
                })

        # Bollinger Bands signals
        if indicators['BB']:
            bb = indicators['BB']
            if bb['position'] == 'oversold':
                signals.append({
                    'indicator': 'BB',
                    'type': 'BUY',
                    'reason': 'Price at Lower Bollinger Band',
                    'strength': 'medium'
                })
            elif bb['position'] == 'overbought':
                signals.append({
                    'indicator': 'BB',
                    'type': 'SELL',
                    'reason': 'Price at Upper Bollinger Band',
                    'strength': 'medium'
                })

        # Stochastic signals
        if indicators['STOCH']:
            stoch = indicators['STOCH']
            if stoch['signal'] == 'oversold':
                signals.append({
                    'indicator': 'STOCH',
                    'type': 'BUY',
                    'reason': f"Stochastic Oversold (K:{stoch['k']}, D:{stoch['d']})",
                    'strength': 'medium'
                })
            elif stoch['signal'] == 'overbought':
                signals.append({
                    'indicator': 'STOCH',
                    'type': 'SELL',
                    'reason': f"Stochastic Overbought (K:{stoch['k']}, D:{stoch['d']})",
                    'strength': 'medium'
                })

        # ADX signals (trend strength confirmation)
        if indicators['ADX']:
            adx = indicators['ADX']
            if adx['signal'] == 'trending' and adx['trend_strength'] in ['strong', 'very_strong', 'extreme']:
                # ADX doesn't give direction, just confirms trend strength
                # We use it to boost confidence of other signals
                signals.append({
                    'indicator': 'ADX',
                    'type': 'NEUTRAL',
                    'reason': f"Strong Trend Confirmed (ADX: {adx['value']})",
                    'strength': 'strong'
                })
            elif adx['signal'] == 'ranging':
                signals.append({
                    'indicator': 'ADX',
                    'type': 'NEUTRAL',
                    'reason': f"Weak Trend / Ranging Market (ADX: {adx['value']})",
                    'strength': 'weak'
                })

        # SMA crossover signals
        if indicators['SMA_50'] and indicators['SMA_200']:
            sma50 = indicators['SMA_50']
            sma200 = indicators['SMA_200']

            if sma50['crossover'] == 'golden_cross':
                signals.append({
                    'indicator': 'SMA',
                    'type': 'BUY',
                    'reason': 'Golden Cross (50 SMA > 200 SMA)',
                    'strength': 'strong'
                })
            elif sma50['crossover'] == 'death_cross':
                signals.append({
                    'indicator': 'SMA',
                    'type': 'SELL',
                    'reason': 'Death Cross (50 SMA < 200 SMA)',
                    'strength': 'strong'
                })

        # OBV signals (volume confirmation)
        if indicators['OBV']:
            obv = indicators['OBV']
            if obv['divergence'] == 'bullish':
                signals.append({
                    'indicator': 'OBV',
                    'type': 'BUY',
                    'reason': 'Bullish Volume Divergence',
                    'strength': 'medium'
                })
            elif obv['divergence'] == 'bearish':
                signals.append({
                    'indicator': 'OBV',
                    'type': 'SELL',
                    'reason': 'Bearish Volume Divergence',
                    'strength': 'medium'
                })
            elif obv['signal'] == 'bullish' and obv['trend'] == 'rising':
                signals.append({
                    'indicator': 'OBV',
                    'type': 'BUY',
                    'reason': 'Volume Trending Up',
                    'strength': 'weak'
                })
            elif obv['signal'] == 'bearish' and obv['trend'] == 'falling':
                signals.append({
                    'indicator': 'OBV',
                    'type': 'SELL',
                    'reason': 'Volume Trending Down',
                    'strength': 'weak'
                })

        return signals
