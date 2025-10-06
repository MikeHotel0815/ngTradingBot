"""
Candlestick Pattern Recognition Module
Detects candlestick patterns using TA-Lib
"""

import logging
import talib
import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime
from redis_client import get_redis
from database import ScopedSession
from models import OHLCData, PatternDetection
import json

logger = logging.getLogger(__name__)


class PatternRecognizer:
    """
    Detect candlestick patterns with Redis caching
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str, cache_ttl: int = 60):
        """
        Initialize Pattern Recognizer

        Args:
            account_id: Account ID
            symbol: Trading symbol (e.g., EURUSD)
            timeframe: Timeframe (M5, M15, H1, H4, D1)
            cache_ttl: Cache TTL in seconds (default: 60 seconds)
        """
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.cache_ttl = cache_ttl
        self.redis = get_redis()

    def _cache_key(self) -> str:
        """Generate Redis cache key"""
        return f"patterns:{self.account_id}:{self.symbol}:{self.timeframe}"

    def _get_cached(self) -> Optional[List[Dict]]:
        """Get cached patterns from Redis"""
        try:
            key = self._cache_key()
            cached = self.redis.client.get(key)
            if cached:
                return json.loads(cached)
            return None
        except Exception as e:
            logger.error(f"Cache get error: {e}")
            return None

    def _set_cache(self, patterns: List[Dict]):
        """Set patterns in Redis cache"""
        try:
            key = self._cache_key()
            self.redis.client.setex(
                key,
                self.cache_ttl,
                json.dumps(patterns)
            )
        except Exception as e:
            logger.error(f"Cache set error: {e}")

    def _get_ohlc_data(self, limit: int = 100) -> Optional[pd.DataFrame]:
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

    def detect_patterns(self) -> List[Dict]:
        """
        Detect all candlestick patterns

        Returns:
            List of detected patterns with type and reliability
        """
        # Check cache first
        cached = self._get_cached()
        if cached is not None:
            return cached

        patterns = []

        # Get OHLC data
        df = self._get_ohlc_data()
        if df is None or len(df) < 5:
            return patterns

        open_p = df['open'].values
        high = df['high'].values
        low = df['low'].values
        close = df['close'].values

        # Bullish Patterns
        bullish_patterns = {
            'Hammer': talib.CDLHAMMER,
            'Inverted Hammer': talib.CDLINVERTEDHAMMER,
            'Bullish Engulfing': talib.CDLENGULFING,
            'Morning Star': talib.CDLMORNINGSTAR,
            'Three White Soldiers': talib.CDL3WHITESOLDIERS,
            'Dragonfly Doji': talib.CDLDRAGONFLYDOJI,
            'Piercing Pattern': talib.CDLPIERCING,
        }

        # Bearish Patterns
        bearish_patterns = {
            'Shooting Star': talib.CDLSHOOTINGSTAR,
            'Hanging Man': talib.CDLHANGINGMAN,
            'Evening Star': talib.CDLEVENINGSTAR,
            'Three Black Crows': talib.CDL3BLACKCROWS,
            'Gravestone Doji': talib.CDLGRAVESTONEDOJI,
            'Dark Cloud Cover': talib.CDLDARKCLOUDCOVER,
        }

        # Harami Patterns (can be bullish or bearish depending on context)
        harami_patterns = {
            'Harami': talib.CDLHARAMI,
        }

        # Detect bullish patterns
        for pattern_name, pattern_func in bullish_patterns.items():
            try:
                result = pattern_func(open_p, high, low, close)
                # Check last candle
                if result[-1] != 0:
                    reliability = self._calculate_pattern_reliability(
                        pattern_name,
                        'bullish',
                        df
                    )
                    patterns.append({
                        'name': pattern_name,
                        'type': 'bullish',
                        'reliability': reliability,
                        'detected_at': datetime.utcnow().isoformat()
                    })
            except Exception as e:
                logger.error(f"Error detecting {pattern_name}: {e}")

        # Detect bearish patterns
        for pattern_name, pattern_func in bearish_patterns.items():
            try:
                result = pattern_func(open_p, high, low, close)
                # Check last candle
                if result[-1] != 0:
                    reliability = self._calculate_pattern_reliability(
                        pattern_name,
                        'bearish',
                        df
                    )
                    patterns.append({
                        'name': pattern_name,
                        'type': 'bearish',
                        'reliability': reliability,
                        'detected_at': datetime.utcnow().isoformat()
                    })
            except Exception as e:
                logger.error(f"Error detecting {pattern_name}: {e}")

        # Detect Harami patterns (context-dependent)
        for pattern_name, pattern_func in harami_patterns.items():
            try:
                result = pattern_func(open_p, high, low, close)
                # Check last candle
                if result[-1] > 0:  # Bullish Harami
                    reliability = self._calculate_pattern_reliability(
                        'Bullish Harami',
                        'bullish',
                        df
                    )
                    patterns.append({
                        'name': 'Bullish Harami',
                        'type': 'bullish',
                        'reliability': reliability,
                        'detected_at': datetime.utcnow().isoformat()
                    })
                elif result[-1] < 0:  # Bearish Harami
                    reliability = self._calculate_pattern_reliability(
                        'Bearish Harami',
                        'bearish',
                        df
                    )
                    patterns.append({
                        'name': 'Bearish Harami',
                        'type': 'bearish',
                        'reliability': reliability,
                        'detected_at': datetime.utcnow().isoformat()
                    })
            except Exception as e:
                logger.error(f"Error detecting {pattern_name}: {e}")

        # Cache patterns
        self._set_cache(patterns)

        return patterns

    def _calculate_pattern_reliability(
        self,
        pattern_name: str,
        pattern_type: str,
        df: pd.DataFrame
    ) -> float:
        """
        Calculate pattern reliability score (0-100)

        Factors:
        - Volume confirmation
        - Trend context
        - Pattern location (support/resistance)

        Args:
            pattern_name: Name of the pattern
            pattern_type: bullish or bearish
            df: OHLC DataFrame

        Returns:
            Reliability score (0-100)
        """
        score = 50.0  # Base score

        # Volume confirmation (±10 points)
        try:
            current_volume = df['volume'].iloc[-1]
            avg_volume = df['volume'].iloc[-20:].mean()
            if current_volume > avg_volume * 1.5:
                score += 10
            elif current_volume < avg_volume * 0.5:
                score -= 10
        except:
            pass

        # Trend context (±15 points)
        try:
            # Simple trend check using close prices
            close = df['close'].values
            if len(close) >= 20:
                recent_trend = close[-1] - close[-20]
                if pattern_type == 'bullish' and recent_trend < 0:
                    score += 15  # Bullish reversal in downtrend
                elif pattern_type == 'bearish' and recent_trend > 0:
                    score += 15  # Bearish reversal in uptrend
        except:
            pass

        # Pattern-specific adjustments
        high_reliability_patterns = [
            'Bullish Engulfing',
            'Bearish Engulfing',
            'Morning Star',
            'Evening Star',
            'Three White Soldiers',
            'Three Black Crows',
            'Bullish Harami',
            'Bearish Harami'
        ]
        if pattern_name in high_reliability_patterns:
            score += 10

        # Cap score between 0-100
        score = max(0, min(100, score))

        return round(score, 2)

    def save_pattern_detection(self, pattern: Dict):
        """
        Save pattern detection to database

        Args:
            pattern: Pattern dictionary
        """
        db = ScopedSession()
        try:
            # Get latest OHLC snapshot (last 5 candles)
            ohlc = db.query(OHLCData).filter_by(
                account_id=self.account_id,
                symbol=self.symbol,
                timeframe=self.timeframe
            ).order_by(OHLCData.timestamp.desc()).limit(5).all()

            ohlc_snapshot = [{
                'timestamp': o.timestamp.isoformat(),
                'open': float(o.open),
                'high': float(o.high),
                'low': float(o.low),
                'close': float(o.close),
                'volume': float(o.volume) if o.volume else 0
            } for o in reversed(ohlc)]

            detection = PatternDetection(
                account_id=self.account_id,
                symbol=self.symbol,
                timeframe=self.timeframe,
                pattern_name=pattern['name'],
                pattern_type=pattern['type'],
                reliability_score=pattern['reliability'],
                ohlc_snapshot=ohlc_snapshot,
                detected_at=datetime.utcnow()
            )

            db.add(detection)
            db.commit()

            logger.info(
                f"Pattern saved: {pattern['name']} {self.symbol} {self.timeframe} "
                f"(reliability: {pattern['reliability']}%)"
            )

        except Exception as e:
            logger.error(f"Error saving pattern detection: {e}")
            db.rollback()
        finally:
            db.close()

    def get_pattern_signals(self) -> List[Dict]:
        """
        Get trading signals from detected patterns

        Returns:
            List of signal dictionaries
        """
        patterns = self.detect_patterns()
        signals = []

        for pattern in patterns:
            # Only consider patterns with reliability > 50%
            if pattern['reliability'] > 50:
                signal_type = 'BUY' if pattern['type'] == 'bullish' else 'SELL'

                # Determine strength based on reliability
                if pattern['reliability'] >= 70:
                    strength = 'strong'
                elif pattern['reliability'] >= 60:
                    strength = 'medium'
                else:
                    strength = 'weak'

                signals.append({
                    'pattern': pattern['name'],
                    'type': signal_type,
                    'reason': f"{pattern['name']} Pattern",
                    'strength': strength,
                    'reliability': pattern['reliability']
                })

                # Save high-reliability patterns to database
                if pattern['reliability'] >= 60:
                    self.save_pattern_detection(pattern)

        return signals
