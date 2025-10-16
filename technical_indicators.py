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
            # OHLC data is now global (no account_id column)
            ohlc = db.query(OHLCData).filter_by(
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

        # Get market regime for adaptive thresholds
        regime_info = self.detect_market_regime()
        market_regime = regime_info.get('regime', 'UNKNOWN')

        # Regime-dependent RSI thresholds
        # RANGING: Stricter thresholds (wait for extremes)
        # TRENDING: Relaxed thresholds (enter earlier in pullbacks)
        if market_regime == 'RANGING':
            oversold_threshold = 30
            overbought_threshold = 70
        elif market_regime == 'TRENDING':
            oversold_threshold = 40
            overbought_threshold = 60
        else:  # UNKNOWN or TOO_WEAK
            oversold_threshold = 35  # Middle ground
            overbought_threshold = 65

        # Determine signal with adaptive thresholds
        signal = 'neutral'
        if current_rsi > overbought_threshold:
            signal = 'overbought'
        elif current_rsi < oversold_threshold:
            signal = 'oversold'

        result = {
            'value': round(current_rsi, 2),
            'signal': signal,
            'period': period,
            'threshold_oversold': oversold_threshold,
            'threshold_overbought': overbought_threshold,
            'market_regime': market_regime,
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

        # Get market regime for adaptive thresholds
        regime_info = self.detect_market_regime()
        market_regime = regime_info.get('regime', 'UNKNOWN')

        # Regime-dependent Stochastic thresholds
        if market_regime == 'RANGING':
            oversold_threshold = 20
            overbought_threshold = 80
        elif market_regime == 'TRENDING':
            oversold_threshold = 30
            overbought_threshold = 70
        else:  # UNKNOWN or TOO_WEAK
            oversold_threshold = 25
            overbought_threshold = 75

        # Determine signal with adaptive thresholds
        signal = 'neutral'
        if current_k > overbought_threshold and current_d > overbought_threshold:
            signal = 'overbought'
        elif current_k < oversold_threshold and current_d < oversold_threshold:
            signal = 'oversold'

        result = {
            'k': round(current_k, 2),
            'd': round(current_d, 2),
            'signal': signal,
            'threshold_oversold': oversold_threshold,
            'threshold_overbought': overbought_threshold,
            'market_regime': market_regime,
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

    def calculate_ichimoku(self) -> Optional[Dict]:
        """
        Calculate Ichimoku Cloud (Ichimoku Kinko Hyo)

        Components:
        - Tenkan-sen (Conversion Line): (9-period high + 9-period low) / 2
        - Kijun-sen (Base Line): (26-period high + 26-period low) / 2
        - Senkou Span A (Leading Span A): (Tenkan-sen + Kijun-sen) / 2, plotted 26 periods ahead
        - Senkou Span B (Leading Span B): (52-period high + 52-period low) / 2, plotted 26 periods ahead
        - Chikou Span (Lagging Span): Current close, plotted 26 periods back

        Returns:
            Dict with Ichimoku components and signals
        """
        indicator_name = 'ICHIMOKU'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data (need at least 52 + 26 = 78 candles)
        df = self._get_ohlc_data(limit=100)
        if df is None or len(df) < 78:
            return None

        try:
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values

            # Tenkan-sen (Conversion Line): (9-period high + 9-period low) / 2
            period9_high = pd.Series(high).rolling(window=9).max()
            period9_low = pd.Series(low).rolling(window=9).min()
            tenkan_sen = (period9_high + period9_low) / 2

            # Kijun-sen (Base Line): (26-period high + 26-period low) / 2
            period26_high = pd.Series(high).rolling(window=26).max()
            period26_low = pd.Series(low).rolling(window=26).min()
            kijun_sen = (period26_high + period26_low) / 2

            # Senkou Span A (Leading Span A): (Tenkan + Kijun) / 2
            senkou_span_a = ((tenkan_sen + kijun_sen) / 2).shift(26)

            # Senkou Span B (Leading Span B): (52-period high + 52-period low) / 2
            period52_high = pd.Series(high).rolling(window=52).max()
            period52_low = pd.Series(low).rolling(window=52).min()
            senkou_span_b = ((period52_high + period52_low) / 2).shift(26)

            # Chikou Span (Lagging Span): Current close plotted 26 periods back
            chikou_span = pd.Series(close).shift(-26)

            # Current values
            current_price = float(close[-1])
            current_tenkan = float(tenkan_sen.iloc[-1]) if not pd.isna(tenkan_sen.iloc[-1]) else None
            current_kijun = float(kijun_sen.iloc[-1]) if not pd.isna(kijun_sen.iloc[-1]) else None
            current_span_a = float(senkou_span_a.iloc[-1]) if not pd.isna(senkou_span_a.iloc[-1]) else None
            current_span_b = float(senkou_span_b.iloc[-1]) if not pd.isna(senkou_span_b.iloc[-1]) else None

            # Determine cloud color and position
            cloud_color = None
            price_vs_cloud = None

            if current_span_a and current_span_b:
                # Cloud color
                if current_span_a > current_span_b:
                    cloud_color = 'bullish'  # Green cloud
                else:
                    cloud_color = 'bearish'  # Red cloud

                # Price position relative to cloud
                cloud_top = max(current_span_a, current_span_b)
                cloud_bottom = min(current_span_a, current_span_b)

                if current_price > cloud_top:
                    price_vs_cloud = 'above'  # Bullish
                elif current_price < cloud_bottom:
                    price_vs_cloud = 'below'  # Bearish
                else:
                    price_vs_cloud = 'inside'  # Neutral/Uncertain

            # Determine signals
            signal = 'neutral'
            tk_cross = None

            # TK Cross (Tenkan-Kijun crossover)
            if current_tenkan and current_kijun:
                prev_tenkan = float(tenkan_sen.iloc[-2]) if not pd.isna(tenkan_sen.iloc[-2]) else None
                prev_kijun = float(kijun_sen.iloc[-2]) if not pd.isna(kijun_sen.iloc[-2]) else None

                if prev_tenkan and prev_kijun:
                    # Bullish TK cross
                    if prev_tenkan <= prev_kijun and current_tenkan > current_kijun:
                        tk_cross = 'bullish'
                        if price_vs_cloud == 'above':
                            signal = 'strong_buy'
                        else:
                            signal = 'buy'
                    # Bearish TK cross
                    elif prev_tenkan >= prev_kijun and current_tenkan < current_kijun:
                        tk_cross = 'bearish'
                        if price_vs_cloud == 'below':
                            signal = 'strong_sell'
                        else:
                            signal = 'sell'

            # Strong trend signals based on all components alignment
            if price_vs_cloud == 'above' and cloud_color == 'bullish' and current_tenkan and current_kijun and current_tenkan > current_kijun:
                signal = 'strong_buy'
            elif price_vs_cloud == 'below' and cloud_color == 'bearish' and current_tenkan and current_kijun and current_tenkan < current_kijun:
                signal = 'strong_sell'

            result = {
                'tenkan_sen': round(current_tenkan, 5) if current_tenkan else None,
                'kijun_sen': round(current_kijun, 5) if current_kijun else None,
                'senkou_span_a': round(current_span_a, 5) if current_span_a else None,
                'senkou_span_b': round(current_span_b, 5) if current_span_b else None,
                'cloud_color': cloud_color,
                'price_vs_cloud': price_vs_cloud,
                'tk_cross': tk_cross,
                'signal': signal,
                'current_price': round(current_price, 5),
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"Ichimoku calculation error: {e}")
            return None

    def calculate_vwap(self) -> Optional[Dict]:
        """
        Calculate VWAP (Volume Weighted Average Price)

        VWAP = Sum(Price * Volume) / Sum(Volume)
        where Price = (High + Low + Close) / 3 (Typical Price)

        Returns:
            Dict with VWAP value and price position signal
        """
        indicator_name = 'VWAP'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data for current trading session
        df = self._get_ohlc_data(limit=50)
        if df is None or len(df) < 10:
            return None

        try:
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values
            volume = df['volume'].values

            # Calculate Typical Price
            typical_price = (high + low + close) / 3

            # Calculate VWAP
            # For intraday: cumulative from session start
            # For our case: rolling VWAP over available data
            pv = typical_price * volume  # Price * Volume
            cumulative_pv = np.cumsum(pv)
            cumulative_volume = np.cumsum(volume)

            vwap = cumulative_pv / cumulative_volume

            current_vwap = float(vwap[-1])
            current_price = float(close[-1])

            # Calculate distance from VWAP (as percentage)
            distance_pct = ((current_price - current_vwap) / current_vwap) * 100

            # Determine signal based on price position relative to VWAP
            signal = 'neutral'
            position = 'at'

            if distance_pct > 0.5:
                signal = 'overbought'
                position = 'above'
            elif distance_pct < -0.5:
                signal = 'oversold'
                position = 'below'
            elif current_price > current_vwap:
                signal = 'bullish'
                position = 'above'
            elif current_price < current_vwap:
                signal = 'bearish'
                position = 'below'

            # Calculate VWAP bands (standard deviation)
            # Rolling standard deviation of typical price
            typical_price_series = pd.Series(typical_price)
            vwap_std = typical_price_series.rolling(window=20).std().iloc[-1]

            upper_band = current_vwap + (vwap_std * 2) if not pd.isna(vwap_std) else None
            lower_band = current_vwap - (vwap_std * 2) if not pd.isna(vwap_std) else None

            result = {
                'value': round(current_vwap, 5),
                'current_price': round(current_price, 5),
                'distance_pct': round(distance_pct, 2),
                'position': position,
                'signal': signal,
                'upper_band': round(upper_band, 5) if upper_band else None,
                'lower_band': round(lower_band, 5) if lower_band else None,
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"VWAP calculation error: {e}")
            return None

    def calculate_supertrend(self, period: int = 10, multiplier: float = 3.0) -> Optional[Dict]:
        """
        Calculate SuperTrend indicator

        SuperTrend uses ATR to calculate dynamic support/resistance levels
        - Green (Bullish): Price above SuperTrend line
        - Red (Bearish): Price below SuperTrend line

        Args:
            period: ATR period (default: 10)
            multiplier: ATR multiplier (default: 3.0)

        Returns:
            Dict with SuperTrend value, direction, and signal
        """
        indicator_name = f'SUPERTREND_{period}_{multiplier}'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data(limit=100)
        if df is None or len(df) < period + 1:
            return None

        try:
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values

            # Calculate ATR
            atr = talib.ATR(high, low, close, timeperiod=period)

            # Calculate basic upper and lower bands
            hl_avg = (high + low) / 2

            # Initialize arrays
            supertrend = np.zeros(len(close))
            direction = np.zeros(len(close))  # 1 = bullish, -1 = bearish

            basic_upper = hl_avg + (multiplier * atr)
            basic_lower = hl_avg - (multiplier * atr)

            final_upper = np.zeros(len(close))
            final_lower = np.zeros(len(close))

            # Calculate SuperTrend
            for i in range(period, len(close)):
                # Final upper band
                if i == period:
                    final_upper[i] = basic_upper[i]
                else:
                    if basic_upper[i] < final_upper[i-1] or close[i-1] > final_upper[i-1]:
                        final_upper[i] = basic_upper[i]
                    else:
                        final_upper[i] = final_upper[i-1]

                # Final lower band
                if i == period:
                    final_lower[i] = basic_lower[i]
                else:
                    if basic_lower[i] > final_lower[i-1] or close[i-1] < final_lower[i-1]:
                        final_lower[i] = basic_lower[i]
                    else:
                        final_lower[i] = final_lower[i-1]

                # Determine direction and SuperTrend value
                if i == period:
                    if close[i] <= final_upper[i]:
                        supertrend[i] = final_upper[i]
                        direction[i] = -1
                    else:
                        supertrend[i] = final_lower[i]
                        direction[i] = 1
                else:
                    if supertrend[i-1] == final_upper[i-1] and close[i] <= final_upper[i]:
                        supertrend[i] = final_upper[i]
                        direction[i] = -1
                    elif supertrend[i-1] == final_upper[i-1] and close[i] > final_upper[i]:
                        supertrend[i] = final_lower[i]
                        direction[i] = 1
                    elif supertrend[i-1] == final_lower[i-1] and close[i] >= final_lower[i]:
                        supertrend[i] = final_lower[i]
                        direction[i] = 1
                    elif supertrend[i-1] == final_lower[i-1] and close[i] < final_lower[i]:
                        supertrend[i] = final_upper[i]
                        direction[i] = -1

            # Current values
            current_supertrend = float(supertrend[-1])
            current_direction = int(direction[-1])
            current_price = float(close[-1])
            prev_direction = int(direction[-2]) if len(direction) > 1 else current_direction

            # Determine signal
            signal = 'neutral'
            trend = 'bullish' if current_direction == 1 else 'bearish'

            # Trend change signals
            if prev_direction == -1 and current_direction == 1:
                signal = 'buy'  # Trend changed to bullish
            elif prev_direction == 1 and current_direction == -1:
                signal = 'sell'  # Trend changed to bearish
            elif current_direction == 1:
                signal = 'hold_long'
            elif current_direction == -1:
                signal = 'hold_short'

            # Calculate distance to SuperTrend (for dynamic SL)
            distance = abs(current_price - current_supertrend)
            distance_pct = (distance / current_price) * 100

            result = {
                'value': round(current_supertrend, 5),
                'direction': trend,
                'signal': signal,
                'current_price': round(current_price, 5),
                'distance': round(distance, 5),
                'distance_pct': round(distance_pct, 2),
                'period': period,
                'multiplier': multiplier,
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"SuperTrend calculation error: {e}")
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
        indicators['ICHIMOKU'] = self.calculate_ichimoku()
        indicators['SUPERTREND'] = self.calculate_supertrend()

        # Volatility indicators
        indicators['BB'] = self.calculate_bollinger_bands()
        indicators['ATR'] = self.calculate_atr()

        # Momentum indicators
        indicators['STOCH'] = self.calculate_stochastic()

        # Volume indicators
        indicators['OBV'] = self.calculate_obv()
        indicators['VWAP'] = self.calculate_vwap()

        return indicators

    def detect_market_regime(self) -> Dict:
        """
        Detect market regime: TRENDING or RANGING

        Uses ADX and Bollinger Band width to determine market state

        Returns:
            Dict with regime, strength, and details
        """
        try:
            # Get required data
            df = self._get_ohlc_data(limit=50)
            if df is None or len(df) < 30:
                return {'regime': 'UNKNOWN', 'strength': 0, 'adx': None, 'bb_width': None}

            close = df['close'].values
            high = df['high'].values
            low = df['low'].values

            # Calculate ADX (Average Directional Index) - measures trend strength
            adx = talib.ADX(high, low, close, timeperiod=14)
            current_adx = adx[-1] if len(adx) > 0 and not np.isnan(adx[-1]) else None

            # Calculate Bollinger Band Width (normalized) - measures volatility
            bb_upper, bb_middle, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
            bb_width = ((bb_upper[-1] - bb_lower[-1]) / bb_middle[-1]) * 100 if len(bb_upper) > 0 else None

            # Determine regime
            regime = 'UNKNOWN'
            strength = 0

            if current_adx is not None and bb_width is not None:
                # ADX minimum threshold - market too weak for any strategy
                MIN_ADX_FOR_TRADING = 12

                if current_adx < MIN_ADX_FOR_TRADING:
                    regime = 'TOO_WEAK'
                    strength = 0
                    logger.info(f"{self.symbol} {self.timeframe} Market too weak for trading (ADX: {current_adx:.1f} < {MIN_ADX_FOR_TRADING})")
                # ADX > 25 = Strong trend
                elif current_adx > 25:
                    regime = 'TRENDING'
                    strength = min(100, int((current_adx - 25) / 50 * 100))  # Scale 25-75 ADX to 0-100%
                # ADX 12-20 = Weak/no trend (ranging)
                elif current_adx < 20:
                    regime = 'RANGING'
                    strength = min(100, int((current_adx - MIN_ADX_FOR_TRADING) / (20 - MIN_ADX_FOR_TRADING) * 100))  # Scale 12-20 ADX to 0-100%
                else:
                    # Borderline case (ADX 20-25) - use BB width as tie-breaker
                    if bb_width < 2.0:  # Narrow bands = ranging
                        regime = 'RANGING'
                        strength = 50
                    else:
                        regime = 'TRENDING'
                        strength = 50

            logger.debug(f"{self.symbol} {self.timeframe} Market Regime: {regime} (ADX: {current_adx:.1f}, BB Width: {bb_width:.2f}%, Strength: {strength}%)")

            return {
                'regime': regime,
                'strength': strength,
                'adx': float(current_adx) if current_adx else None,
                'bb_width': float(bb_width) if bb_width else None
            }

        except Exception as e:
            logger.error(f"Error detecting market regime: {e}")
            return {'regime': 'UNKNOWN', 'strength': 0, 'adx': None, 'bb_width': None}

    def get_indicator_signals(self) -> List[Dict]:
        """
        Extract trading signals from indicators with market regime awareness

        Returns:
            List of signal dictionaries with strategy_type field
        """
        indicators = self.calculate_all()
        signals = []

        # Detect market regime first
        regime = self.detect_market_regime()
        market_regime = regime['regime']

        # MEAN-REVERSION Indicators (best for RANGING markets)
        # These indicators work when price bounces between support/resistance

        # RSI signals (Mean-Reversion)
        if indicators['RSI']:
            rsi = indicators['RSI']
            if rsi['signal'] == 'oversold':
                signals.append({
                    'indicator': 'RSI',
                    'type': 'BUY',
                    'reason': f"RSI Oversold ({rsi['value']})",
                    'strength': 'medium',
                    'strategy_type': 'mean_reversion'
                })
            elif rsi['signal'] == 'overbought':
                signals.append({
                    'indicator': 'RSI',
                    'type': 'SELL',
                    'reason': f"RSI Overbought ({rsi['value']})",
                    'strength': 'medium',
                    'strategy_type': 'mean_reversion'
                })

        # Bollinger Bands signals (Mean-Reversion)
        if indicators['BB']:
            bb = indicators['BB']
            if bb['position'] == 'oversold':
                signals.append({
                    'indicator': 'BB',
                    'type': 'BUY',
                    'reason': 'Price at Lower Bollinger Band',
                    'strength': 'medium',
                    'strategy_type': 'mean_reversion'
                })
            elif bb['position'] == 'overbought':
                signals.append({
                    'indicator': 'BB',
                    'type': 'SELL',
                    'reason': 'Price at Upper Bollinger Band',
                    'strength': 'medium',
                    'strategy_type': 'mean_reversion'
                })

        # Stochastic signals (Mean-Reversion)
        if indicators['STOCH']:
            stoch = indicators['STOCH']
            if stoch['signal'] == 'oversold':
                signals.append({
                    'indicator': 'STOCH',
                    'type': 'BUY',
                    'reason': f"Stochastic Oversold (K:{stoch['k']}, D:{stoch['d']})",
                    'strength': 'medium',
                    'strategy_type': 'mean_reversion'
                })
            elif stoch['signal'] == 'overbought':
                signals.append({
                    'indicator': 'STOCH',
                    'type': 'SELL',
                    'reason': f"Stochastic Overbought (K:{stoch['k']}, D:{stoch['d']})",
                    'strength': 'medium',
                    'strategy_type': 'mean_reversion'
                })

        # TREND-FOLLOWING Indicators (best for TRENDING markets)
        # These indicators work when price makes sustained directional moves

        # MACD signals (Trend-Following)
        if indicators['MACD']:
            macd = indicators['MACD']
            if macd['crossover'] == 'bullish':
                signals.append({
                    'indicator': 'MACD',
                    'type': 'BUY',
                    'reason': 'MACD Bullish Crossover',
                    'strength': 'strong',
                    'strategy_type': 'trend_following'
                })
            elif macd['crossover'] == 'bearish':
                signals.append({
                    'indicator': 'MACD',
                    'type': 'SELL',
                    'reason': 'MACD Bearish Crossover',
                    'strength': 'strong',
                    'strategy_type': 'trend_following'
                })

        # EMA trend signals (Trend-Following)
        if indicators['EMA_200']:
            ema = indicators['EMA_200']
            if ema['trend'] == 'above':
                signals.append({
                    'indicator': 'EMA_200',
                    'type': 'BUY',
                    'reason': 'Price Above 200 EMA',
                    'strength': 'weak',
                    'strategy_type': 'trend_following'
                })
            elif ema['trend'] == 'below':
                signals.append({
                    'indicator': 'EMA_200',
                    'type': 'SELL',
                    'reason': 'Price Below 200 EMA',
                    'strength': 'weak',
                    'strategy_type': 'trend_following'
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

        # SMA crossover signals (Trend-Following)
        if indicators['SMA_50'] and indicators['SMA_200']:
            sma50 = indicators['SMA_50']
            sma200 = indicators['SMA_200']

            if sma50['crossover'] == 'golden_cross':
                signals.append({
                    'indicator': 'SMA',
                    'type': 'BUY',
                    'reason': 'Golden Cross (50 SMA > 200 SMA)',
                    'strength': 'strong',
                    'strategy_type': 'trend_following'
                })
            elif sma50['crossover'] == 'death_cross':
                signals.append({
                    'indicator': 'SMA',
                    'type': 'SELL',
                    'reason': 'Death Cross (50 SMA < 200 SMA)',
                    'strength': 'strong',
                    'strategy_type': 'trend_following'
                })

        # ADX: Mark as trend_following for regime filtering
        for sig in signals:
            if sig.get('indicator') == 'ADX':
                sig['strategy_type'] = 'trend_following'

        # OBV signals (volume confirmation - works in both regimes)
        if indicators['OBV']:
            obv = indicators['OBV']
            if obv['divergence'] == 'bullish':
                signals.append({
                    'indicator': 'OBV',
                    'type': 'BUY',
                    'reason': 'Bullish Volume Divergence',
                    'strength': 'medium',
                    'strategy_type': 'neutral'  # Volume works in both regimes
                })
            elif obv['divergence'] == 'bearish':
                signals.append({
                    'indicator': 'OBV',
                    'type': 'SELL',
                    'reason': 'Bearish Volume Divergence',
                    'strength': 'medium',
                    'strategy_type': 'neutral'
                })
            elif obv['signal'] == 'bullish' and obv['trend'] == 'rising':
                signals.append({
                    'indicator': 'OBV',
                    'type': 'BUY',
                    'reason': 'Volume Trending Up',
                    'strength': 'weak',
                    'strategy_type': 'neutral'
                })
            elif obv['signal'] == 'bearish' and obv['trend'] == 'falling':
                signals.append({
                    'indicator': 'OBV',
                    'type': 'SELL',
                    'reason': 'Volume Trending Down',
                    'strength': 'weak',
                    'strategy_type': 'neutral'
                })

        # Ichimoku Cloud signals (Trend-Following - very strong)
        if indicators['ICHIMOKU']:
            ichi = indicators['ICHIMOKU']
            if ichi['signal'] == 'strong_buy':
                signals.append({
                    'indicator': 'ICHIMOKU',
                    'type': 'BUY',
                    'reason': f"Strong Bullish Ichimoku (Price above {ichi['cloud_color']} cloud, TK bullish)",
                    'strength': 'very_strong',
                    'strategy_type': 'trend_following'
                })
            elif ichi['signal'] == 'buy':
                signals.append({
                    'indicator': 'ICHIMOKU',
                    'type': 'BUY',
                    'reason': f"Ichimoku TK Cross (Tenkan > Kijun)",
                    'strength': 'strong',
                    'strategy_type': 'trend_following'
                })
            elif ichi['signal'] == 'strong_sell':
                signals.append({
                    'indicator': 'ICHIMOKU',
                    'type': 'SELL',
                    'reason': f"Strong Bearish Ichimoku (Price below {ichi['cloud_color']} cloud, TK bearish)",
                    'strength': 'very_strong',
                    'strategy_type': 'trend_following'
                })
            elif ichi['signal'] == 'sell':
                signals.append({
                    'indicator': 'ICHIMOKU',
                    'type': 'SELL',
                    'reason': f"Ichimoku TK Cross (Tenkan < Kijun)",
                    'strength': 'strong',
                    'strategy_type': 'trend_following'
                })

        # VWAP signals (Support/Resistance - works in both regimes)
        if indicators['VWAP']:
            vwap = indicators['VWAP']
            if vwap['signal'] == 'oversold':
                signals.append({
                    'indicator': 'VWAP',
                    'type': 'BUY',
                    'reason': f"Price far below VWAP ({vwap['distance_pct']}%)",
                    'strength': 'strong',
                    'strategy_type': 'mean_reversion'
                })
            elif vwap['signal'] == 'overbought':
                signals.append({
                    'indicator': 'VWAP',
                    'type': 'SELL',
                    'reason': f"Price far above VWAP ({vwap['distance_pct']}%)",
                    'strength': 'strong',
                    'strategy_type': 'mean_reversion'
                })
            elif vwap['position'] == 'above' and vwap['signal'] == 'bullish':
                signals.append({
                    'indicator': 'VWAP',
                    'type': 'BUY',
                    'reason': 'Price above VWAP (institutional support)',
                    'strength': 'weak',
                    'strategy_type': 'neutral'
                })
            elif vwap['position'] == 'below' and vwap['signal'] == 'bearish':
                signals.append({
                    'indicator': 'VWAP',
                    'type': 'SELL',
                    'reason': 'Price below VWAP (institutional resistance)',
                    'strength': 'weak',
                    'strategy_type': 'neutral'
                })

        # SuperTrend signals (Trend-Following with dynamic SL)
        if indicators['SUPERTREND']:
            st = indicators['SUPERTREND']
            if st['signal'] == 'buy':
                signals.append({
                    'indicator': 'SUPERTREND',
                    'type': 'BUY',
                    'reason': 'SuperTrend Bullish Reversal',
                    'strength': 'very_strong',
                    'strategy_type': 'trend_following'
                })
            elif st['signal'] == 'sell':
                signals.append({
                    'indicator': 'SUPERTREND',
                    'type': 'SELL',
                    'reason': 'SuperTrend Bearish Reversal',
                    'strength': 'very_strong',
                    'strategy_type': 'trend_following'
                })
            elif st['signal'] == 'hold_long' and st['direction'] == 'bullish':
                signals.append({
                    'indicator': 'SUPERTREND',
                    'type': 'BUY',
                    'reason': 'SuperTrend Bullish Trend',
                    'strength': 'strong',
                    'strategy_type': 'trend_following'
                })
            elif st['signal'] == 'hold_short' and st['direction'] == 'bearish':
                signals.append({
                    'indicator': 'SUPERTREND',
                    'type': 'SELL',
                    'reason': 'SuperTrend Bearish Trend',
                    'strength': 'strong',
                    'strategy_type': 'trend_following'
                })

        # Filter signals based on market regime
        filtered_signals = self._filter_by_regime(signals, market_regime)

        # Add regime info to each signal
        for sig in filtered_signals:
            sig['market_regime'] = market_regime
            sig['regime_strength'] = regime['strength']

        logger.info(f"{self.symbol} {self.timeframe} Market: {market_regime} ({regime['strength']}%) - Signals: {len(signals)} total, {len(filtered_signals)} after regime filter")

        return filtered_signals

    def _filter_by_regime(self, signals: List[Dict], regime: str) -> List[Dict]:
        """
        Filter signals based on market regime to avoid conflicting strategies

        Args:
            signals: List of all signals
            regime: Market regime (TRENDING, RANGING, TOO_WEAK, or UNKNOWN)

        Returns:
            Filtered signals appropriate for the regime
        """
        if regime == 'TOO_WEAK':
            # Market too weak - no signals should be generated
            logger.info(f"{self.symbol} {self.timeframe} Market too weak - all signals filtered")
            return []

        if regime == 'UNKNOWN':
            # If regime unclear, keep all signals but log warning
            logger.warning(f"{self.symbol} {self.timeframe} Market regime unknown - using all signals")
            return signals

        filtered = []

        for sig in signals:
            strategy_type = sig.get('strategy_type', 'neutral')

            if regime == 'TRENDING':
                # In trending markets: prioritize trend-following, exclude mean-reversion
                if strategy_type in ['trend_following', 'neutral']:
                    filtered.append(sig)
                else:
                    logger.debug(f"{self.symbol} Excluded {sig['indicator']} (mean-reversion in trending market)")

            elif regime == 'RANGING':
                # In ranging markets: prioritize mean-reversion, exclude trend-following
                if strategy_type in ['mean_reversion', 'neutral']:
                    filtered.append(sig)
                else:
                    logger.debug(f"{self.symbol} Excluded {sig['indicator']} (trend-following in ranging market)")

        return filtered
