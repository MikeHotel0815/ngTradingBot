"""
Smart TP/SL Calculator - Enhanced with Symbol-Specific Configuration

Combines multiple factors for realistic and achievable TP/SL levels:
1. ATR-based targets (volatility)
2. Bollinger Bands (statistical boundaries)
3. Support/Resistance levels (technical analysis)
4. Psychological levels (round numbers)
5. **NEW:** Symbol-specific broker limits and asset-class configurations

Goal: Generate REALISTIC targets that are likely to be reached AND accepted by broker.
"""

import logging
from typing import Dict, Optional, Tuple
from sqlalchemy.orm import Session
from database import get_db
from models import OHLCData, BrokerSymbol
from technical_indicators import TechnicalIndicators

logger = logging.getLogger(__name__)


class SymbolConfig:
    """Symbol-specific trading configuration based on asset class"""
    
    ASSET_CLASSES = {
        'FOREX_MAJOR': {
            'symbols': ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD'],
            'atr_tp_multiplier': 2.0,      # Conservative for Forex
            'atr_sl_multiplier': 0.9,      # ✅ TIGHTER: Was 1.2, now 0.9 (prevent 18h losses)
            'trailing_multiplier': 0.6,    # ✅ MORE AGGRESSIVE: Was 0.8, now 0.6
            'max_tp_pct': 1.0,             # Max 1% (100 pips typically)
            'min_sl_pct': 0.15,            # Min 15 pips
            'fallback_atr_pct': 0.0008,    # 0.08% (~8 pips @ 1.0000)
        },
        'FOREX_MINOR': {
            'symbols': ['EURGBP', 'EURJPY', 'GBPJPY', 'EURCHF', 'EURAUD', 'EURCAD', 
                       'AUDCAD', 'AUDNZD', 'CADJPY', 'CHFJPY', 'GBPAUD', 'GBPCAD'],
            'atr_tp_multiplier': 2.5,
            'atr_sl_multiplier': 1.3,
            'trailing_multiplier': 0.9,
            'max_tp_pct': 1.2,
            'min_sl_pct': 0.2,
            'fallback_atr_pct': 0.0012,    # 0.12%
        },
        'FOREX_EXOTIC': {
            'symbols': ['USDTRY', 'USDZAR', 'USDMXN', 'USDBRL', 'EURTRY', 'USDRUB'],
            'atr_tp_multiplier': 3.0,      # Wider due to volatility
            'atr_sl_multiplier': 1.5,
            'trailing_multiplier': 1.2,
            'max_tp_pct': 2.0,
            'min_sl_pct': 0.5,
            'fallback_atr_pct': 0.0020,    # 0.20%
        },
        'CRYPTO': {
            'symbols': ['BTCUSD', 'ETHUSD', 'LTCUSD', 'XRPUSD', 'BCHUSD', 'ADAUSD', 
                       'DOTUSD', 'LINKUSD', 'SOLUSD', 'MATICUSD'],
            'atr_tp_multiplier': 1.8,      # Aggressive (high volatility)
            'atr_sl_multiplier': 1.0,      # Wider stop (volatility)
            'trailing_multiplier': 0.7,    
            'max_tp_pct': 5.0,             # Crypto can move 5%
            'min_sl_pct': 1.0,             # Min 1% stop
            'fallback_atr_pct': 0.020,     # 2%
        },
        'METALS': {
            'symbols': ['XAUUSD', 'XAGUSD', 'XPTUSD', 'XPDUSD'],
            'atr_tp_multiplier': 2.2,
            'atr_sl_multiplier': 1.8,      # ✅ FIXED: Increased from 1.2 to 1.8 (more breathing room)
            'trailing_multiplier': 0.6,    # ✅ FIXED: Reduced from 0.8 to 0.6 (more aggressive trailing)
            'max_tp_pct': 2.0,             # Gold: max 2%
            'min_sl_pct': 0.5,             # Min 0.5%
            'fallback_atr_pct': 0.008,     # 0.8%
        },
        'INDICES': {
            'symbols': ['US30', 'NAS100', 'SPX500', 'GER40', 'UK100', 'JPN225', 
                       'AUS200', 'FRA40', 'ESP35', 'ITA40'],
            'atr_tp_multiplier': 2.0,
            'atr_sl_multiplier': 1.2,
            'trailing_multiplier': 0.9,
            'max_tp_pct': 1.5,
            'min_sl_pct': 0.3,
            'fallback_atr_pct': 0.006,     # 0.6%
        },
        'COMMODITIES': {
            'symbols': ['XTIUSD', 'XBRUSD', 'NATGAS', 'UKOUSD'],  # Oil, Brent, Gas
            'atr_tp_multiplier': 2.5,
            'atr_sl_multiplier': 1.5,
            'trailing_multiplier': 1.0,
            'max_tp_pct': 3.0,
            'min_sl_pct': 0.8,
            'fallback_atr_pct': 0.015,     # 1.5%
        },
        'STOCKS': {
            'symbols': ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META'],
            'atr_tp_multiplier': 2.0,
            'atr_sl_multiplier': 1.3,
            'trailing_multiplier': 0.9,
            'max_tp_pct': 2.0,
            'min_sl_pct': 0.5,
            'fallback_atr_pct': 0.010,     # 1%
        }
    }
    
    @classmethod
    def get_asset_class_config(cls, symbol: str) -> Dict:
        """Get asset class configuration for symbol"""
        for asset_class, config in cls.ASSET_CLASSES.items():
            if symbol in config['symbols']:
                return {
                    'asset_class': asset_class,
                    **config
                }
        
        # Default fallback (treat as forex major)
        logger.warning(f"Unknown symbol {symbol}, using FOREX_MAJOR defaults")
        return {
            'asset_class': 'UNKNOWN',
            **cls.ASSET_CLASSES['FOREX_MAJOR']
        }


class SmartTPSLCalculator:
    """
    Intelligent TP/SL calculation using hybrid approach with broker-aware validation
    """

    def __init__(self, account_id: int, symbol: str, timeframe: str):
        self.account_id = account_id
        self.symbol = symbol
        self.timeframe = timeframe
        self.indicators = TechnicalIndicators(account_id, symbol, timeframe)
        self.asset_config = SymbolConfig.get_asset_class_config(symbol)
        self.broker_specs = None  # Lazy loaded

    def _get_broker_specs(self, db: Session) -> Dict:
        """Get broker symbol specifications"""
        if self.broker_specs:
            return self.broker_specs
        
        try:
            broker_symbol = db.query(BrokerSymbol).filter_by(
                account_id=self.account_id,
                symbol=self.symbol
            ).first()
            
            if broker_symbol:
                self.broker_specs = {
                    'digits': broker_symbol.digits or 5,
                    'point': float(broker_symbol.point_value) if broker_symbol.point_value else 0.00001,
                    'stops_level': broker_symbol.stops_level or 10,
                    'freeze_level': broker_symbol.freeze_level or 0,
                    'volume_min': float(broker_symbol.volume_min) if broker_symbol.volume_min else 0.01,
                    'volume_step': float(broker_symbol.volume_step) if broker_symbol.volume_step else 0.01,
                }
                logger.debug(f"Loaded broker specs for {self.symbol}: {self.broker_specs}")
            else:
                # Fallback defaults
                self.broker_specs = self._get_default_broker_specs()
                logger.warning(f"No broker specs for {self.symbol}, using defaults")
            
            return self.broker_specs
            
        except Exception as e:
            logger.error(f"Error loading broker specs for {self.symbol}: {e}")
            self.broker_specs = self._get_default_broker_specs()
            return self.broker_specs
    
    def _get_default_broker_specs(self) -> Dict:
        """Default broker specs based on asset class"""
        asset_class = self.asset_config.get('asset_class', 'UNKNOWN')
        
        defaults = {
            'FOREX_MAJOR': {'digits': 5, 'point': 0.00001, 'stops_level': 10},
            'FOREX_MINOR': {'digits': 5, 'point': 0.00001, 'stops_level': 15},
            'FOREX_EXOTIC': {'digits': 5, 'point': 0.00001, 'stops_level': 50},
            'CRYPTO': {'digits': 2, 'point': 0.01, 'stops_level': 50},
            'METALS': {'digits': 2, 'point': 0.01, 'stops_level': 30},
            'INDICES': {'digits': 2, 'point': 0.01, 'stops_level': 10},
            'COMMODITIES': {'digits': 3, 'point': 0.001, 'stops_level': 20},
            'STOCKS': {'digits': 2, 'point': 0.01, 'stops_level': 5},
        }
        
        spec = defaults.get(asset_class, defaults['FOREX_MAJOR'])
        return {
            **spec,
            'freeze_level': 0,
            'volume_min': 0.01,
            'volume_step': 0.01
        }

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
                - tp_distance_points: TP distance in broker points
                - sl_distance_points: SL distance in broker points
        """
        db = next(get_db())
        try:
            # Get broker specifications
            broker_specs = self._get_broker_specs(db)
            
            # Get all candidate levels
            atr = self._get_atr()
            if atr == 0:
                atr = self._get_smart_atr_fallback(entry_price)
            
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
            tp, tp_reason = self._select_best_tp(tp_candidates, entry_price, signal_type, atr)

            # Select best SL (tightest safe level)
            sl, sl_reason = self._select_best_sl(sl_candidates, entry_price, signal_type, atr)

            # Apply broker limits and rounding
            tp, sl = self._apply_broker_limits(entry_price, tp, sl, signal_type, broker_specs)

            # Validate TP/SL
            if not self._validate_tp_sl(entry_price, tp, sl, signal_type):
                # Fallback to ATR-based if validation fails
                logger.warning(f"TP/SL validation failed, using ATR fallback for {self.symbol}")
                return self._atr_fallback(signal_type, entry_price, atr, broker_specs)

            # Calculate risk/reward
            risk = abs(entry_price - sl)
            reward = abs(tp - entry_price)
            risk_reward = reward / risk if risk > 0 else 0

            # Calculate distances in broker points
            point = broker_specs['point']
            tp_distance_points = round(abs(tp - entry_price) / point, 1)
            sl_distance_points = round(abs(sl - entry_price) / point, 1)

            # Calculate trailing stop distance (based on ATR, not TP distance)
            trailing_distance_pct = self._calculate_trailing_distance(atr, entry_price)

            logger.info(
                f"🎯 {self.symbol} ({self.asset_config['asset_class']}) {signal_type}: "
                f"Entry={entry_price:.{broker_specs['digits']}f} | "
                f"TP={tp:.{broker_specs['digits']}f} ({tp_reason}, {tp_distance_points}pts) | "
                f"SL={sl:.{broker_specs['digits']}f} ({sl_reason}, {sl_distance_points}pts) | "
                f"R:R={risk_reward:.2f} | Trail={trailing_distance_pct:.2f}%"
            )

            return {
                'tp': tp,
                'sl': sl,
                'tp_reason': tp_reason,
                'sl_reason': sl_reason,
                'risk_reward': round(risk_reward, 2),
                'trailing_distance_pct': round(trailing_distance_pct, 2),
                'tp_distance_points': tp_distance_points,
                'sl_distance_points': sl_distance_points,
                'broker_stops_level': broker_specs['stops_level']
            }

        except Exception as e:
            logger.error(f"Error in smart TP/SL calculation: {e}", exc_info=True)
            # Ultimate fallback
            atr = self._get_smart_atr_fallback(entry_price)
            broker_specs = self._get_default_broker_specs()
            return self._atr_fallback(signal_type, entry_price, atr, broker_specs)
        finally:
            db.close()

    def _get_atr(self) -> float:
        """Get Average True Range"""
        try:
            atr_data = self.indicators.calculate_atr()
            return atr_data['value'] if atr_data else 0
        except Exception as e:
            logger.warning(f"ATR calculation failed for {self.symbol} {self.timeframe}: {e}")
            return 0
    
    def _get_smart_atr_fallback(self, entry_price: float) -> float:
        """
        Asset-class aware ATR fallback
        Uses realistic ATR percentages based on asset class
        """
        fallback_pct = self.asset_config.get('fallback_atr_pct', 0.005)
        atr = entry_price * fallback_pct
        
        logger.info(
            f"Using smart ATR fallback for {self.symbol} ({self.asset_config['asset_class']}): "
            f"{atr:.5f} ({fallback_pct*100:.2f}%)"
        )
        
        return atr

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
        except Exception as e:
            logger.debug(f"Bollinger Bands calculation failed for {self.symbol}: {e}")
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
        
        # Get asset-specific multiplier
        tp_multiplier = self.asset_config.get('atr_tp_multiplier', 2.5)

        # 1. ATR-based TP (asset-specific multiplier)
        if atr > 0:
            atr_tp = entry + (tp_multiplier * atr) if signal_type == 'BUY' else entry - (tp_multiplier * atr)
            candidates.append({
                'price': atr_tp,
                'distance': abs(atr_tp - entry),
                'reason': f'ATR {tp_multiplier}x'
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
        
        # Get asset-specific multiplier
        sl_multiplier = self.asset_config.get('atr_sl_multiplier', 1.5)

        # 1. ATR-based SL (asset-specific multiplier)
        if atr > 0:
            atr_sl = entry - (sl_multiplier * atr) if signal_type == 'BUY' else entry + (sl_multiplier * atr)
            candidates.append({
                'price': atr_sl,
                'distance': abs(atr_sl - entry),
                'reason': f'ATR {sl_multiplier}x'
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

        # 3. SuperTrend SL
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
        except Exception as e:
            logger.debug(f"SuperTrend SL calculation failed for {self.symbol}: {e}")

        return candidates

    def _select_best_tp(self, candidates: list, entry: float, signal_type: str, atr: float) -> Tuple[float, str]:
        """
        Select best TP: Closest realistic target that's at least 1.5x ATR away
        """
        if not candidates:
            # Fallback
            tp_multiplier = self.asset_config.get('atr_tp_multiplier', 2.5)
            tp = entry + (tp_multiplier * atr) if signal_type == 'BUY' else entry - (tp_multiplier * atr)
            return tp, 'ATR Fallback'

        # Minimum distance: 1.5x ATR
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

    def _select_best_sl(self, candidates: list, entry: float, signal_type: str, atr: float) -> Tuple[float, str]:
        """
        Select best SL: Tightest safe level (but not too tight)
        """
        if not candidates:
            # Fallback
            sl_multiplier = self.asset_config.get('atr_sl_multiplier', 1.5)
            sl = entry - (sl_multiplier * atr) if signal_type == 'BUY' else entry + (sl_multiplier * atr)
            return sl, 'ATR Fallback'

        # Minimum distance: 1.0x ATR (don't go tighter)
        min_distance = 1.0 * atr

        # Filter candidates that are too tight
        valid_candidates = [c for c in candidates if c['distance'] >= min_distance]

        if not valid_candidates:
            # All too tight, use ATR-based
            for c in candidates:
                if c['reason'].startswith('ATR'):
                    return c['price'], c['reason']
            # Ultimate fallback
            sl_multiplier = self.asset_config.get('atr_sl_multiplier', 1.5)
            sl = entry - (sl_multiplier * atr) if signal_type == 'BUY' else entry + (sl_multiplier * atr)
            return sl, 'ATR Fallback Tight'

        # Sort by distance (tightest first)
        valid_candidates.sort(key=lambda x: x['distance'])

        # Return tightest safe level
        best = valid_candidates[0]
        return best['price'], best['reason']

    def _apply_broker_limits(
        self, entry: float, tp: float, sl: float, 
        signal_type: str, broker_specs: Dict
    ) -> Tuple[float, float]:
        """
        Apply broker limits (stops_level) and round to correct digits
        """
        point = broker_specs['point']
        min_stops = broker_specs['stops_level']
        digits = broker_specs['digits']
        
        # Calculate distances in points
        tp_distance_points = abs(tp - entry) / point
        sl_distance_points = abs(sl - entry) / point
        
        # Adjust TP if too close
        if tp_distance_points < min_stops:
            tp = entry + (min_stops * point) if signal_type == 'BUY' else entry - (min_stops * point)
            logger.warning(
                f"TP adjusted to broker minimum: {min_stops} points "
                f"(was {tp_distance_points:.1f} points)"
            )
        
        # Adjust SL if too close
        if sl_distance_points < min_stops:
            sl = entry - (min_stops * point) if signal_type == 'BUY' else entry + (min_stops * point)
            logger.warning(
                f"SL adjusted to broker minimum: {min_stops} points "
                f"(was {sl_distance_points:.1f} points)"
            )
        
        # Round to correct digits
        tp = round(tp, digits)
        sl = round(sl, digits)
        
        return tp, sl

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

        # 3. Check TP not too far (asset-specific maximum)
        tp_distance_pct = abs(tp - entry) / entry * 100
        max_distance = self.asset_config.get('max_tp_pct', 5.0)

        if tp_distance_pct > max_distance:
            logger.warning(f"TP too far: {tp_distance_pct:.2f}% (max: {max_distance}%)")
            return False

        # 4. Check SL not too tight (asset-specific minimum)
        sl_distance_pct = abs(sl - entry) / entry * 100
        min_sl_distance = self.asset_config.get('min_sl_pct', 0.1)

        if sl_distance_pct < min_sl_distance:
            logger.warning(f"SL too tight: {sl_distance_pct:.2f}% (min: {min_sl_distance}%)")
            return False

        return True

    def _calculate_trailing_distance(self, atr: float, entry: float) -> float:
        """
        Calculate trailing stop distance in %
        Based on ATR with asset-specific multiplier
        """
        # Get asset-specific multiplier
        trailing_multiplier = self.asset_config.get('trailing_multiplier', 1.0)
        
        # Trailing distance: asset-specific multiplier * ATR
        trailing_distance = trailing_multiplier * atr
        trailing_distance_pct = (trailing_distance / entry) * 100

        # Clamp to reasonable range: 0.3% - 3.0%
        trailing_distance_pct = max(0.3, min(3.0, trailing_distance_pct))

        return trailing_distance_pct

    def _atr_fallback(
        self, signal_type: str, entry: float, atr: float, broker_specs: Dict
    ) -> Dict:
        """Fallback to simple ATR-based calculation with asset-specific multipliers"""
        tp_multiplier = self.asset_config.get('atr_tp_multiplier', 2.5)
        sl_multiplier = self.asset_config.get('atr_sl_multiplier', 1.5)
        
        if signal_type == 'BUY':
            tp = entry + (tp_multiplier * atr)
            sl = entry - (sl_multiplier * atr)
        else:
            tp = entry - (tp_multiplier * atr)
            sl = entry + (sl_multiplier * atr)
        
        # Apply broker limits
        tp, sl = self._apply_broker_limits(entry, tp, sl, signal_type, broker_specs)

        risk = abs(entry - sl)
        reward = abs(tp - entry)
        risk_reward = reward / risk if risk > 0 else 1.67

        trailing_distance_pct = self._calculate_trailing_distance(atr, entry)
        
        # Calculate distances in points
        point = broker_specs['point']
        tp_distance_points = round(abs(tp - entry) / point, 1)
        sl_distance_points = round(abs(sl - entry) / point, 1)

        return {
            'tp': tp,
            'sl': sl,
            'tp_reason': f'ATR Fallback {tp_multiplier}x',
            'sl_reason': f'ATR Fallback {sl_multiplier}x',
            'risk_reward': round(risk_reward, 2),
            'trailing_distance_pct': round(trailing_distance_pct, 2),
            'tp_distance_points': tp_distance_points,
            'sl_distance_points': sl_distance_points,
            'broker_stops_level': broker_specs['stops_level']
        }


def get_smart_tp_sl(account_id: int, symbol: str, timeframe: str) -> SmartTPSLCalculator:
    """Factory function to get SmartTPSLCalculator instance"""
    return SmartTPSLCalculator(account_id, symbol, timeframe)
