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
from heiken_ashi_config import (
    get_heiken_ashi_config,
    is_heiken_ashi_enabled,
    calculate_ha_confidence
)

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """
    Calculate technical indicators with Redis caching
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str, cache_ttl: int = 300, risk_profile: str = 'normal'):
        """
        Initialize Technical Indicators

        Args:
            account_id: Account ID
            symbol: Trading symbol (e.g., EURUSD)
            timeframe: Timeframe (M5, M15, H1, H4, D1)
            cache_ttl: Cache TTL in seconds (default: 300 = 5 minutes)
            risk_profile: Risk profile (aggressive, normal, moderate) - affects regime filtering
        """
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.cache_ttl = max(int(cache_ttl) if cache_ttl else 300, 1)  # Ensure positive integer
        self.risk_profile = risk_profile
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

    def calculate_heiken_ashi(self) -> Optional[Dict]:
        """
        Calculate Heiken Ashi candles and trend signals

        Heiken Ashi smooths price action and filters out market noise.
        Strong trend signals:
        - Bullish: Green candles with no lower wick (strong buyers)
        - Bearish: Red candles with no upper wick (strong sellers)

        Returns:
            Dict with HA OHLC values, trend, and signal strength
        """
        indicator_name = 'HEIKEN_ASHI'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data(limit=50)
        if df is None or len(df) < 10:
            return None

        try:
            open_price = df['open'].values
            high = df['high'].values
            low = df['low'].values
            close = df['close'].values

            # Initialize Heiken Ashi arrays
            ha_open = np.zeros(len(close))
            ha_close = np.zeros(len(close))
            ha_high = np.zeros(len(close))
            ha_low = np.zeros(len(close))

            # First HA candle
            ha_open[0] = (open_price[0] + close[0]) / 2
            ha_close[0] = (open_price[0] + high[0] + low[0] + close[0]) / 4
            ha_high[0] = high[0]
            ha_low[0] = low[0]

            # Calculate subsequent HA candles
            for i in range(1, len(close)):
                # HA Close = (O + H + L + C) / 4
                ha_close[i] = (open_price[i] + high[i] + low[i] + close[i]) / 4

                # HA Open = (previous HA Open + previous HA Close) / 2
                ha_open[i] = (ha_open[i-1] + ha_close[i-1]) / 2

                # HA High = max(H, HA Open, HA Close)
                ha_high[i] = max(high[i], ha_open[i], ha_close[i])

                # HA Low = min(L, HA Open, HA Close)
                ha_low[i] = min(low[i], ha_open[i], ha_close[i])

            # Current HA candle
            current_ha_open = float(ha_open[-1])
            current_ha_close = float(ha_close[-1])
            current_ha_high = float(ha_high[-1])
            current_ha_low = float(ha_low[-1])

            # Determine candle color
            is_bullish = current_ha_close > current_ha_open
            is_bearish = current_ha_close < current_ha_open

            # Calculate body and wicks
            body_size = abs(current_ha_close - current_ha_open)
            upper_wick = current_ha_high - max(current_ha_open, current_ha_close)
            lower_wick = min(current_ha_open, current_ha_close) - current_ha_low

            # Strong trend detection (no opposite wick)
            has_no_lower_wick = lower_wick < (body_size * 0.1)  # Lower wick < 10% of body
            has_no_upper_wick = upper_wick < (body_size * 0.1)  # Upper wick < 10% of body

            # Count consecutive same-color candles (trend strength)
            consecutive_count = 1
            for i in range(len(ha_close) - 2, max(0, len(ha_close) - 6), -1):
                if is_bullish and ha_close[i] > ha_open[i]:
                    consecutive_count += 1
                elif is_bearish and ha_close[i] < ha_open[i]:
                    consecutive_count += 1
                else:
                    break

            # Check for recent reversal (recent opposite color candle in last 4 bars)
            recent_reversal = False
            lookback = min(4, len(ha_close) - 1)
            for i in range(len(ha_close) - 2, len(ha_close) - lookback - 1, -1):
                if is_bullish and ha_close[i] < ha_open[i]:
                    recent_reversal = True
                    break
                elif is_bearish and ha_close[i] > ha_open[i]:
                    recent_reversal = True
                    break

            # Determine signal
            signal = 'neutral'
            trend = 'neutral'
            strength = 0

            if is_bullish and has_no_lower_wick:
                signal = 'strong_buy'
                trend = 'strong_bullish'
                strength = min(100, 60 + (consecutive_count * 10))
            elif is_bullish:
                signal = 'buy'
                trend = 'bullish'
                strength = min(100, 40 + (consecutive_count * 8))
            elif is_bearish and has_no_upper_wick:
                signal = 'strong_sell'
                trend = 'strong_bearish'
                strength = min(100, 60 + (consecutive_count * 10))
            elif is_bearish:
                signal = 'sell'
                trend = 'bearish'
                strength = min(100, 40 + (consecutive_count * 8))

            result = {
                'ha_open': round(current_ha_open, 5),
                'ha_close': round(current_ha_close, 5),
                'ha_high': round(current_ha_high, 5),
                'ha_low': round(current_ha_low, 5),
                'trend': trend,
                'signal': signal,
                'is_bullish': is_bullish,
                'is_bearish': is_bearish,
                'has_no_lower_wick': has_no_lower_wick,
                'has_no_upper_wick': has_no_upper_wick,
                'consecutive_count': consecutive_count,
                'recent_reversal': recent_reversal,
                'strength': strength,
                'body_size': round(body_size, 5),
                'upper_wick': round(upper_wick, 5),
                'lower_wick': round(lower_wick, 5),
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"Heiken Ashi calculation error: {e}")
            return None

    def calculate_volume_analysis(self, period: int = 20) -> Optional[Dict]:
        """
        Analyze volume strength relative to average

        Args:
            period: Lookback period for volume average (default: 20)

        Returns:
            Dict with volume analysis and strength signal
        """
        indicator_name = f'VOLUME_ANALYSIS_{period}'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        # Get OHLC data
        df = self._get_ohlc_data(limit=period + 10)
        if df is None or len(df) < period:
            return None

        try:
            volume = df['volume'].values

            # Calculate average volume
            avg_volume = np.mean(volume[-period:])
            current_volume = float(volume[-1])

            # Volume strength (relative to average)
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

            # Determine signal
            signal = 'neutral'
            strength = 'normal'

            if volume_ratio >= 1.5:
                signal = 'high_volume'
                strength = 'very_high'
            elif volume_ratio >= 1.2:
                signal = 'above_average'
                strength = 'high'
            elif volume_ratio <= 0.6:
                signal = 'low_volume'
                strength = 'very_low'
            elif volume_ratio <= 0.8:
                signal = 'below_average'
                strength = 'low'

            result = {
                'current_volume': round(current_volume, 2),
                'average_volume': round(avg_volume, 2),
                'volume_ratio': round(volume_ratio, 2),
                'signal': signal,
                'strength': strength,
                'period': period,
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"Volume analysis error: {e}")
            return None

    def calculate_heiken_ashi_trend(
        self,
        ema_fast: int = 8,
        ema_slow: int = 30
    ) -> Optional[Dict]:
        """
        Calculate Heiken Ashi Trend w/vol Signals

        Combines:
        - Heiken Ashi candle patterns (strong trend detection)
        - EMA confirmation (8/30 period)
        - Volume analysis (strength confirmation)

        Entry Signals:
        - LONG: Strong bullish HA candle + price above EMAs + recent reversal + high volume
        - SHORT: Strong bearish HA candle + price below EMAs + recent reversal + high volume

        Args:
            ema_fast: Fast EMA period (default: 8)
            ema_slow: Slow EMA period (default: 30)

        Returns:
            Dict with complete signal analysis and entry/exit signals
        """
        # Check if enabled for this symbol/timeframe
        if not is_heiken_ashi_enabled(self.symbol, self.timeframe):
            return None

        indicator_name = f'HA_TREND_{ema_fast}_{ema_slow}'

        # Check cache
        cached = self._get_cached(indicator_name)
        if cached:
            return cached

        try:
            # Get Heiken Ashi data
            ha = self.calculate_heiken_ashi()
            if not ha:
                return None

            # Get EMA data
            ema_fast_data = self.calculate_ema(ema_fast)
            ema_slow_data = self.calculate_ema(ema_slow)
            if not ema_fast_data or not ema_slow_data:
                return None

            # Get volume analysis
            volume = self.calculate_volume_analysis()
            if not volume:
                return None

            # Get current price
            df = self._get_ohlc_data(limit=5)
            if df is None or len(df) < 1:
                return None
            current_price = float(df['close'].values[-1])

            # EMA values
            ema_fast_value = ema_fast_data['value']
            ema_slow_value = ema_slow_data['value']

            # Check EMA alignment
            price_above_emas = current_price > ema_fast_value and current_price > ema_slow_value
            price_below_emas = current_price < ema_fast_value and current_price < ema_slow_value
            ema_bullish_aligned = ema_fast_value > ema_slow_value
            ema_bearish_aligned = ema_fast_value < ema_slow_value

            # Volume confirmation
            high_volume = volume['signal'] in ['high_volume', 'above_average']
            volume_multiplier = 1.0
            if volume['signal'] == 'high_volume':
                volume_multiplier = 1.3
            elif volume['signal'] == 'above_average':
                volume_multiplier = 1.15
            elif volume['signal'] in ['low_volume', 'below_average']:
                volume_multiplier = 0.85

            # Generate signals
            signal = 'neutral'
            signal_type = None
            confidence = 0
            reasons = []

            # LONG ENTRY CONDITIONS
            if (ha['signal'] in ['strong_buy', 'buy'] and
                ha['has_no_lower_wick'] and
                price_above_emas and
                ema_bullish_aligned and
                ha['recent_reversal']):

                signal = 'buy'
                signal_type = 'LONG_ENTRY'

                # Use recalibrated confidence calculation
                confidence = calculate_ha_confidence(
                    ha_signal=ha['signal'],
                    has_no_wick=ha['has_no_lower_wick'],
                    ema_aligned=ema_bullish_aligned,
                    recent_reversal=ha['recent_reversal'],
                    volume_ratio=volume['volume_ratio']
                )

                # Build reasons list
                if ha['signal'] == 'strong_buy':
                    reasons.append('Strong bullish HA candle (no lower wick)')
                else:
                    reasons.append('Bullish HA candle')

                if price_above_emas and ema_bullish_aligned:
                    reasons.append(f'Price above EMAs ({ema_fast}/{ema_slow})')

                if ha['recent_reversal']:
                    reasons.append('Recent reversal detected')

                if high_volume:
                    reasons.append(f'Volume {volume["signal"]} (ratio: {volume["volume_ratio"]:.2f}x)')

            # SHORT ENTRY CONDITIONS
            elif (ha['signal'] in ['strong_sell', 'sell'] and
                  ha['has_no_upper_wick'] and
                  price_below_emas and
                  ema_bearish_aligned and
                  ha['recent_reversal']):

                signal = 'sell'
                signal_type = 'SHORT_ENTRY'

                # Use recalibrated confidence calculation
                confidence = calculate_ha_confidence(
                    ha_signal=ha['signal'],
                    has_no_wick=ha['has_no_upper_wick'],
                    ema_aligned=ema_bearish_aligned,
                    recent_reversal=ha['recent_reversal'],
                    volume_ratio=volume['volume_ratio']
                )

                # Build reasons list
                if ha['signal'] == 'strong_sell':
                    reasons.append('Strong bearish HA candle (no upper wick)')
                else:
                    reasons.append('Bearish HA candle')

                if price_below_emas and ema_bearish_aligned:
                    reasons.append(f'Price below EMAs ({ema_fast}/{ema_slow})')

                if ha['recent_reversal']:
                    reasons.append('Recent reversal detected')

                if high_volume:
                    reasons.append(f'Volume {volume["signal"]} (ratio: {volume["volume_ratio"]:.2f}x)')

            # EXIT SIGNALS (opposing candle color appears)
            elif ha['is_bearish'] and ha['consecutive_count'] == 1:
                signal = 'exit_long'
                signal_type = 'LONG_EXIT'
                confidence = 50
                reasons.append('Opposing bearish candle (exit long)')

            elif ha['is_bullish'] and ha['consecutive_count'] == 1:
                signal = 'exit_short'
                signal_type = 'SHORT_EXIT'
                confidence = 50
                reasons.append('Opposing bullish candle (exit short)')

            # Cap confidence at 100
            confidence = min(100, confidence)

            result = {
                'signal': signal,
                'signal_type': signal_type,
                'confidence': confidence,
                'reasons': reasons,
                'ha_trend': ha['trend'],
                'ha_consecutive': ha['consecutive_count'],
                'ha_has_no_lower_wick': ha['has_no_lower_wick'],
                'ha_has_no_upper_wick': ha['has_no_upper_wick'],
                'ha_recent_reversal': ha['recent_reversal'],
                'price_above_emas': price_above_emas,
                'price_below_emas': price_below_emas,
                'ema_bullish_aligned': ema_bullish_aligned,
                'ema_bearish_aligned': ema_bearish_aligned,
                'ema_fast': round(ema_fast_value, 5),
                'ema_slow': round(ema_slow_value, 5),
                'volume_signal': volume['signal'],
                'volume_ratio': volume['volume_ratio'],
                'current_price': round(current_price, 5),
                'calculated_at': datetime.utcnow().isoformat()
            }

            # Cache result
            self._set_cache(indicator_name, result)

            return result

        except Exception as e:
            logger.error(f"Heiken Ashi Trend calculation error: {e}")
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
        indicators['EMA_8'] = self.calculate_ema(8)
        indicators['EMA_20'] = self.calculate_ema(20)
        indicators['EMA_30'] = self.calculate_ema(30)
        indicators['EMA_50'] = self.calculate_ema(50)
        indicators['EMA_200'] = self.calculate_ema(200)
        indicators['SMA_20'] = self.calculate_sma(20)
        indicators['SMA_50'] = self.calculate_sma(50)
        indicators['SMA_200'] = self.calculate_sma(200)
        indicators['ADX'] = self.calculate_adx()
        indicators['ICHIMOKU'] = self.calculate_ichimoku()
        indicators['SUPERTREND'] = self.calculate_supertrend()
        indicators['HEIKEN_ASHI_TREND'] = self.calculate_heiken_ashi_trend()

        # Volatility indicators
        indicators['BB'] = self.calculate_bollinger_bands()
        indicators['ATR'] = self.calculate_atr()

        # Momentum indicators
        indicators['STOCH'] = self.calculate_stochastic()

        # Volume indicators
        indicators['OBV'] = self.calculate_obv()
        indicators['VWAP'] = self.calculate_vwap()
        indicators['VOLUME'] = self.calculate_volume_analysis()

        return indicators

    def detect_market_regime(self) -> Dict:
        """
        Detect market regime: TRENDING or RANGING
        🔧 ENHANCED 2025-10-28: Now includes trend DIRECTION (bullish/bearish)

        Uses ADX and Bollinger Band width to determine market state
        Uses EMA cross to determine trend direction

        Returns:
            Dict with regime, strength, direction, and details
        """
        try:
            # Get required data
            df = self._get_ohlc_data(limit=50)
            if df is None or len(df) < 30:
                return {'regime': 'UNKNOWN', 'strength': 0, 'direction': 'neutral', 'adx': None, 'bb_width': None}

            close = df['close'].values
            high = df['high'].values
            low = df['low'].values

            # Calculate ADX (Average Directional Index) - measures trend strength
            adx = talib.ADX(high, low, close, timeperiod=14)
            current_adx = adx[-1] if len(adx) > 0 and not np.isnan(adx[-1]) else None

            # Calculate Bollinger Band Width (normalized) - measures volatility
            bb_upper, bb_middle, bb_lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
            bb_width = ((bb_upper[-1] - bb_lower[-1]) / bb_middle[-1]) * 100 if len(bb_upper) > 0 else None

            # 🔧 NEW: Determine trend DIRECTION using EMAs
            ema_20 = talib.EMA(close, timeperiod=20)
            ema_50 = talib.EMA(close, timeperiod=50)

            direction = 'neutral'
            if len(ema_20) > 0 and len(ema_50) > 0:
                current_ema20 = ema_20[-1]
                current_ema50 = ema_50[-1]

                # Bullish: EMA20 > EMA50 and price > EMA20
                if current_ema20 > current_ema50 and close[-1] > current_ema20:
                    direction = 'bullish'
                # Bearish: EMA20 < EMA50 and price < EMA20
                elif current_ema20 < current_ema50 and close[-1] < current_ema20:
                    direction = 'bearish'
                # Weak trend or consolidation
                else:
                    direction = 'neutral'

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

            logger.debug(f"{self.symbol} {self.timeframe} Market Regime: {regime} | Direction: {direction} (ADX: {current_adx:.1f}, BB Width: {bb_width:.2f}%, Strength: {strength}%)")

            return {
                'regime': regime,
                'strength': strength,
                'direction': direction,  # 🔧 NEW: bullish/bearish/neutral
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

        # Heiken Ashi Trend signals (Trend-Following with volume confirmation)
        if indicators['HEIKEN_ASHI_TREND']:
            ha_trend = indicators['HEIKEN_ASHI_TREND']
            if ha_trend['signal'] == 'buy' and ha_trend['signal_type'] == 'LONG_ENTRY':
                # Map confidence to strength
                if ha_trend['confidence'] >= 80:
                    strength = 'very_strong'
                elif ha_trend['confidence'] >= 70:
                    strength = 'strong'
                elif ha_trend['confidence'] >= 60:
                    strength = 'medium'
                else:
                    strength = 'weak'

                signals.append({
                    'indicator': 'HEIKEN_ASHI_TREND',
                    'type': 'BUY',
                    'reason': f"HA Trend: {', '.join(ha_trend['reasons'])}",
                    'strength': strength,
                    'strategy_type': 'trend_following',
                    'confidence': ha_trend['confidence']
                })
            elif ha_trend['signal'] == 'sell' and ha_trend['signal_type'] == 'SHORT_ENTRY':
                # Map confidence to strength
                if ha_trend['confidence'] >= 80:
                    strength = 'very_strong'
                elif ha_trend['confidence'] >= 70:
                    strength = 'strong'
                elif ha_trend['confidence'] >= 60:
                    strength = 'medium'
                else:
                    strength = 'weak'

                signals.append({
                    'indicator': 'HEIKEN_ASHI_TREND',
                    'type': 'SELL',
                    'reason': f"HA Trend: {', '.join(ha_trend['reasons'])}",
                    'strength': strength,
                    'strategy_type': 'trend_following',
                    'confidence': ha_trend['confidence']
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

        ✅ NEW: Risk profile affects filtering strictness:
        - aggressive: Loose filtering (allows more signals in RANGING markets)
        - normal: Standard filtering (as before)
        - moderate: Strict filtering (very conservative)

        Args:
            signals: List of all signals
            regime: Market regime (TRENDING, RANGING, TOO_WEAK, or UNKNOWN)

        Returns:
            Filtered signals appropriate for the regime
        """
        if regime == 'TOO_WEAK':
            # Market too weak - no signals should be generated (unless aggressive mode)
            if self.risk_profile == 'aggressive':
                logger.warning(f"{self.symbol} {self.timeframe} Market too weak - but AGGRESSIVE mode allows neutral signals")
                # In aggressive mode, allow neutral signals even in weak markets
                return [s for s in signals if s.get('strategy_type') == 'neutral']
            else:
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
                elif self.risk_profile == 'aggressive':
                    # AGGRESSIVE: Allow mean-reversion signals too (more trades)
                    filtered.append(sig)
                    logger.debug(f"{self.symbol} AGGRESSIVE: Included {sig['indicator']} (mean-reversion in trending market)")
                else:
                    logger.debug(f"{self.symbol} Excluded {sig['indicator']} (mean-reversion in trending market)")

            elif regime == 'RANGING':
                # In ranging markets: prioritize mean-reversion
                if strategy_type in ['mean_reversion', 'neutral']:
                    filtered.append(sig)
                elif self.risk_profile == 'aggressive':
                    # AGGRESSIVE: Allow trend-following signals too (more trades)
                    # This helps catch early trend reversals in ranging markets
                    filtered.append(sig)
                    logger.debug(f"{self.symbol} AGGRESSIVE: Included {sig['indicator']} (trend-following in ranging market)")
                elif self.risk_profile == 'moderate':
                    # MODERATE: Only allow neutral (very conservative in ranging)
                    if strategy_type == 'neutral':
                        filtered.append(sig)
                    logger.debug(f"{self.symbol} MODERATE: Excluded {sig['indicator']} (strict filtering)")
                else:
                    # NORMAL: Standard behavior (exclude trend-following)
                    logger.debug(f"{self.symbol} Excluded {sig['indicator']} (trend-following in ranging market)")

        logger.info(f"{self.symbol} {self.timeframe} Regime filter ({self.risk_profile}): {len(signals)} → {len(filtered)} signals")
        return filtered
