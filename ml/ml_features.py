"""
Feature Engineering for ML Trading

Extracts 80-100 features from market data for ML model training.

Feature Categories:
1. Technical Indicators (RSI, MACD, Bollinger, ADX, etc.)
2. Price Action (Candlestick patterns, volatility)
3. Multi-Timeframe (M5, M15, H1, H4 combined)
4. Market Regime (TRENDING/RANGING)
5. Session Context (ASIAN/LONDON/US)
6. Historical Performance (symbol-specific metrics)

Usage:
    from ml.ml_features import FeatureEngineer

    fe = FeatureEngineer(db_session)
    features = fe.extract_features(
        symbol='EURUSD',
        timeframe='M15',
        timestamp=datetime.now()
    )
    # Returns: dict with 80+ features
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import numpy as np
from sqlalchemy.orm import Session

# Import existing bot components
from technical_indicators import TechnicalIndicators
from pattern_recognition import PatternRecognizer
from models import OHLCData, Trade, SymbolTradingConfig
from market_hours import get_trading_session

logger = logging.getLogger(__name__)


class FeatureEngineer:
    """Extract ML features from market data"""

    def __init__(self, db: Session, account_id: int = 1):
        """
        Initialize Feature Engineer

        Args:
            db: Database session
            account_id: Account ID for context
        """
        self.db = db
        self.account_id = account_id

    def extract_features(
        self,
        symbol: str,
        timeframe: str = 'M15',
        timestamp: Optional[datetime] = None,
        include_multi_timeframe: bool = True
    ) -> Dict:
        """
        Extract all features for given symbol/timeframe/timestamp

        Args:
            symbol: Trading symbol
            timeframe: Primary timeframe
            timestamp: Optional timestamp (default: now)
            include_multi_timeframe: Include M5, H1, H4 features

        Returns:
            Dict with ~80-100 features
        """
        if timestamp is None:
            timestamp = datetime.utcnow()

        logger.debug(f"Extracting features for {symbol} {timeframe} at {timestamp}")

        features = {}

        # 1. Technical Indicators (primary timeframe)
        features.update(
            self._extract_indicator_features(symbol, timeframe, timestamp)
        )

        # 2. Price Action features
        features.update(
            self._extract_price_action_features(symbol, timeframe, timestamp)
        )

        # 3. Pattern Recognition
        features.update(
            self._extract_pattern_features(symbol, timeframe, timestamp)
        )

        # 4. Market Regime
        features.update(
            self._extract_regime_features(symbol, timeframe, timestamp)
        )

        # 5. Session Context
        features.update(
            self._extract_session_features(symbol, timestamp)
        )

        # 6. Historical Performance
        features.update(
            self._extract_performance_features(symbol)
        )

        # 7. Multi-Timeframe (optional, adds ~30 features)
        if include_multi_timeframe:
            for tf in ['M5', 'H1', 'H4']:
                if tf != timeframe:
                    mtf_features = self._extract_indicator_features(
                        symbol, tf, timestamp, prefix=f'{tf}_'
                    )
                    features.update(mtf_features)

        # 8. Metadata
        features['symbol'] = symbol
        features['timeframe'] = timeframe
        features['timestamp'] = timestamp
        features['feature_count'] = len([k for k in features.keys() if not k in ['symbol', 'timeframe', 'timestamp']])

        return features

    def _extract_indicator_features(
        self,
        symbol: str,
        timeframe: str,
        timestamp: datetime,
        prefix: str = ''
    ) -> Dict:
        """
        Extract technical indicator features

        Returns ~25 features per timeframe
        """
        features = {}

        try:
            ti = TechnicalIndicators(
                account_id=self.account_id,
                symbol=symbol,
                timeframe=timeframe
            )

            # RSI
            rsi_data = ti.calculate_rsi()
            if rsi_data:
                features[f'{prefix}rsi_value'] = rsi_data.get('value', 50.0)
                features[f'{prefix}rsi_signal'] = 1 if rsi_data.get('signal') == 'BUY' else (-1 if rsi_data.get('signal') == 'SELL' else 0)
                features[f'{prefix}rsi_oversold'] = 1 if rsi_data.get('value', 50) < 30 else 0
                features[f'{prefix}rsi_overbought'] = 1 if rsi_data.get('value', 50) > 70 else 0

            # MACD
            macd_data = ti.calculate_macd()
            if macd_data:
                features[f'{prefix}macd_value'] = macd_data.get('macd', 0.0)
                features[f'{prefix}macd_signal'] = macd_data.get('signal_line', 0.0)
                features[f'{prefix}macd_histogram'] = macd_data.get('histogram', 0.0)
                features[f'{prefix}macd_trend'] = 1 if macd_data.get('signal') == 'BUY' else (-1 if macd_data.get('signal') == 'SELL' else 0)

            # Bollinger Bands
            bb_data = ti.calculate_bollinger_bands()
            if bb_data:
                features[f'{prefix}bb_upper'] = bb_data.get('upper', 0.0)
                features[f'{prefix}bb_middle'] = bb_data.get('middle', 0.0)
                features[f'{prefix}bb_lower'] = bb_data.get('lower', 0.0)
                features[f'{prefix}bb_width'] = bb_data.get('width', 0.0)
                features[f'{prefix}bb_position'] = bb_data.get('position', 0.5)  # 0-1 where price is in bands

            # ADX (Trend Strength)
            adx_data = ti.calculate_adx()
            if adx_data:
                features[f'{prefix}adx_value'] = adx_data.get('adx', 0.0)
                features[f'{prefix}adx_plus_di'] = adx_data.get('plus_di', 0.0)
                features[f'{prefix}adx_minus_di'] = adx_data.get('minus_di', 0.0)
                features[f'{prefix}adx_trending'] = 1 if adx_data.get('adx', 0) > 25 else 0

            # EMA
            ema_data = ti.calculate_ema()
            if ema_data:
                features[f'{prefix}ema_value'] = ema_data.get('ema', 0.0)
                features[f'{prefix}ema_signal'] = 1 if ema_data.get('signal') == 'BUY' else (-1 if ema_data.get('signal') == 'SELL' else 0)

            # Stochastic
            stoch_data = ti.calculate_stochastic()
            if stoch_data:
                features[f'{prefix}stoch_k'] = stoch_data.get('k', 50.0)
                features[f'{prefix}stoch_d'] = stoch_data.get('d', 50.0)
                features[f'{prefix}stoch_signal'] = 1 if stoch_data.get('signal') == 'BUY' else (-1 if stoch_data.get('signal') == 'SELL' else 0)

            # ATR (Volatility)
            atr_data = ti.calculate_atr()
            if atr_data:
                features[f'{prefix}atr_value'] = atr_data.get('value', 0.0)

        except Exception as e:
            logger.warning(f"Error extracting indicators for {symbol} {timeframe}: {e}")
            # Fill with defaults
            for key in ['rsi_value', 'macd_value', 'bb_width', 'adx_value', 'atr_value']:
                features[f'{prefix}{key}'] = 0.0

        return features

    def _extract_price_action_features(
        self,
        symbol: str,
        timeframe: str,
        timestamp: datetime
    ) -> Dict:
        """
        Extract price action features from recent candles

        Returns ~15 features
        """
        features = {}

        try:
            # Get last 20 candles
            candles = self.db.query(OHLCData).filter(
                OHLCData.symbol == symbol,
                OHLCData.timeframe == timeframe,
                OHLCData.timestamp <= timestamp
            ).order_by(OHLCData.timestamp.desc()).limit(20).all()

            if len(candles) < 5:
                logger.warning(f"Not enough candles for {symbol} {timeframe}")
                return self._default_price_action_features()

            candles = list(reversed(candles))  # Oldest first

            # Current candle
            current = candles[-1]
            features['close_price'] = float(current.close)
            features['open_price'] = float(current.open)
            features['high_price'] = float(current.high)
            features['low_price'] = float(current.low)

            # Candle body & wicks
            body = abs(current.close - current.open)
            total_range = current.high - current.low
            features['candle_body_pct'] = (body / total_range * 100) if total_range > 0 else 0

            upper_wick = current.high - max(current.open, current.close)
            lower_wick = min(current.open, current.close) - current.low
            features['upper_wick_pct'] = (upper_wick / total_range * 100) if total_range > 0 else 0
            features['lower_wick_pct'] = (lower_wick / total_range * 100) if total_range > 0 else 0

            # Trend direction (5 candles)
            closes = [float(c.close) for c in candles[-5:]]
            features['price_change_5'] = (closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
            features['trending_up'] = 1 if all(closes[i] >= closes[i-1] for i in range(1, len(closes))) else 0
            features['trending_down'] = 1 if all(closes[i] <= closes[i-1] for i in range(1, len(closes))) else 0

            # Volatility (std dev of last 10 closes)
            if len(candles) >= 10:
                recent_closes = [float(c.close) for c in candles[-10:]]
                features['volatility_std'] = float(np.std(recent_closes))
                features['volatility_cv'] = features['volatility_std'] / np.mean(recent_closes) if np.mean(recent_closes) > 0 else 0
            else:
                features['volatility_std'] = 0.0
                features['volatility_cv'] = 0.0

            # Volume analysis
            if current.volume and current.volume > 0:
                avg_volume = np.mean([float(c.volume) for c in candles[-10:] if c.volume])
                features['volume_ratio'] = float(current.volume) / avg_volume if avg_volume > 0 else 1.0
            else:
                features['volume_ratio'] = 1.0

        except Exception as e:
            logger.error(f"Error extracting price action: {e}")
            return self._default_price_action_features()

        return features

    def _extract_pattern_features(
        self,
        symbol: str,
        timeframe: str,
        timestamp: datetime
    ) -> Dict:
        """
        Extract candlestick pattern features

        Returns ~10 features
        """
        features = {
            'pattern_detected': 0,
            'pattern_bullish': 0,
            'pattern_bearish': 0,
            'pattern_reliability': 0.0
        }

        try:
            recognizer = PatternRecognizer(
                account_id=self.account_id,
                symbol=symbol,
                timeframe=timeframe
            )

            patterns = recognizer.detect_patterns()

            if patterns and len(patterns) > 0:
                # Get most reliable pattern
                best_pattern = max(patterns, key=lambda p: p.get('reliability', 0))

                features['pattern_detected'] = 1
                features['pattern_reliability'] = best_pattern.get('reliability', 0) / 100.0
                features['pattern_bullish'] = 1 if best_pattern.get('signal_type') == 'BUY' else 0
                features['pattern_bearish'] = 1 if best_pattern.get('signal_type') == 'SELL' else 0
                features['pattern_count'] = len(patterns)

        except Exception as e:
            logger.warning(f"Error extracting patterns: {e}")

        return features

    def _extract_regime_features(
        self,
        symbol: str,
        timeframe: str,
        timestamp: datetime
    ) -> Dict:
        """
        Extract market regime features

        Returns ~5 features
        """
        features = {
            'regime_trending': 0,
            'regime_ranging': 0,
            'regime_strength': 0.0
        }

        try:
            ti = TechnicalIndicators(
                account_id=self.account_id,
                symbol=symbol,
                timeframe=timeframe
            )

            regime = ti.detect_market_regime()

            if regime:
                features['regime_trending'] = 1 if regime == 'TRENDING' else 0
                features['regime_ranging'] = 1 if regime == 'RANGING' else 0

                # ADX as regime strength
                adx_data = ti.calculate_adx()
                if adx_data:
                    features['regime_strength'] = adx_data.get('adx', 0) / 100.0

        except Exception as e:
            logger.warning(f"Error extracting regime: {e}")

        return features

    def _extract_session_features(
        self,
        symbol: str,
        timestamp: datetime
    ) -> Dict:
        """
        Extract trading session features

        Returns ~5 features
        """
        session = get_trading_session(symbol, timestamp)

        features = {
            'session_asian': 1 if session == 'ASIAN' else 0,
            'session_london': 1 if session == 'LONDON' else 0,
            'session_us': 1 if session == 'US' else 0,
            'session_overlap': 1 if session == 'LONDON_US_OVERLAP' else 0,
            'hour_of_day': timestamp.hour
        }

        return features

    def _extract_performance_features(
        self,
        symbol: str
    ) -> Dict:
        """
        Extract historical performance features for symbol

        Returns ~8 features
        """
        features = {
            'symbol_win_rate': 0.5,  # Default 50%
            'symbol_avg_profit': 0.0,
            'symbol_trade_count': 0,
            'symbol_consecutive_wins': 0,
            'symbol_consecutive_losses': 0
        }

        try:
            # Get symbol config
            config = self.db.query(SymbolTradingConfig).filter(
                SymbolTradingConfig.account_id == self.account_id,
                SymbolTradingConfig.symbol == symbol
            ).first()

            if config:
                features['symbol_win_rate'] = config.rolling_winrate or 0.5
                features['symbol_consecutive_wins'] = config.consecutive_wins or 0
                features['symbol_consecutive_losses'] = config.consecutive_losses or 0

            # Recent trades (last 30 days)
            cutoff = datetime.utcnow() - timedelta(days=30)
            recent_trades = self.db.query(Trade).filter(
                Trade.account_id == self.account_id,
                Trade.symbol == symbol,
                Trade.status == 'closed',
                Trade.close_time >= cutoff
            ).all()

            if recent_trades:
                features['symbol_trade_count'] = len(recent_trades)
                features['symbol_avg_profit'] = np.mean([t.profit for t in recent_trades])

        except Exception as e:
            logger.warning(f"Error extracting performance features: {e}")

        return features

    def _default_price_action_features(self) -> Dict:
        """Default price action features when data unavailable"""
        return {
            'close_price': 0.0,
            'open_price': 0.0,
            'high_price': 0.0,
            'low_price': 0.0,
            'candle_body_pct': 0.0,
            'upper_wick_pct': 0.0,
            'lower_wick_pct': 0.0,
            'price_change_5': 0.0,
            'trending_up': 0,
            'trending_down': 0,
            'volatility_std': 0.0,
            'volatility_cv': 0.0,
            'volume_ratio': 1.0
        }
