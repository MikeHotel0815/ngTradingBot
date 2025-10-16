"""
Symbol-specific configuration for adaptive trading parameters
Allows different SL/TP/TS settings per symbol based on performance
"""

import logging
from typing import Dict, Optional
from decimal import Decimal

logger = logging.getLogger(__name__)


class SymbolConfig:
    """
    Symbol-specific trading configuration
    Provides adaptive parameters based on symbol type and performance
    """

    # Default parameters per symbol category
    # ✅ UPDATED 2025-10-16: Lowered min_confidence across all categories to allow more quality signals
    INDEX_CONFIG = {
        'sl_multiplier': 1.0,  # Use full SL
        'breakeven_trigger_percent': 30.0,
        'partial_trailing_trigger_percent': 50.0,
        'aggressive_trailing_trigger_percent': 75.0,
        'min_confidence': 45.0,  # ✅ LOWERED from 55% - allow quality signals
        'risk_per_trade_percent': 0.02,  # 2% risk
    }

    FOREX_CONFIG = {
        'sl_multiplier': 0.5,  # Tighter SL (50%)
        'breakeven_trigger_percent': 15.0,  # Earlier break-even
        'partial_trailing_trigger_percent': 35.0,  # Earlier partial trailing
        'aggressive_trailing_trigger_percent': 60.0,  # Earlier aggressive trailing
        'min_confidence': 50.0,  # ✅ LOWERED from 65% - allow quality forex signals
        'risk_per_trade_percent': 0.015,  # 1.5% risk
    }

    CRYPTO_CONFIG = {
        'sl_multiplier': 0.7,  # Moderate SL
        'breakeven_trigger_percent': 20.0,
        'partial_trailing_trigger_percent': 40.0,
        'aggressive_trailing_trigger_percent': 70.0,
        'min_confidence': 55.0,  # ✅ LOWERED from 60% - crypto needs slightly higher due to volatility
        'risk_per_trade_percent': 0.025,  # 2.5% risk (more volatile)
    }

    COMMODITY_CONFIG = {
        'sl_multiplier': 0.8,
        'breakeven_trigger_percent': 25.0,
        'partial_trailing_trigger_percent': 45.0,
        'aggressive_trailing_trigger_percent': 70.0,
        'min_confidence': 50.0,  # ✅ LOWERED from 60% - allow quality commodity signals
        'risk_per_trade_percent': 0.02,
    }

    # Symbol-specific overrides (learned from performance)
    SYMBOL_OVERRIDES = {
        'USDJPY': {
            'sl_multiplier': 0.4,  # Very tight SL for USDJPY
            'breakeven_trigger_percent': 12.0,  # Very early break-even
            'partial_trailing_trigger_percent': 25.0,
            'aggressive_trailing_trigger_percent': 50.0,
            'min_confidence': 48.0,  # ✅ LOWERED from 60% - allow quality signals through
            'risk_per_trade_percent': 0.01,  # Lower risk
        },
        'EURUSD': {
            'sl_multiplier': 0.5,
            'breakeven_trigger_percent': 15.0,
            'min_confidence': 48.0,  # ✅ LOWERED from 60% - allow quality signals through
            'risk_per_trade_percent': 0.015,
        },
        'GBPUSD': {
            'sl_multiplier': 0.6,
            'breakeven_trigger_percent': 18.0,
            'min_confidence': 52.0,  # ✅ LOWERED from 65% (good performer, keep slightly higher)
            'risk_per_trade_percent': 0.018,
        },
        'BTCUSD': {
            # PERFORMANCE: 42.4% win-rate, avg -€1.18 → NEEDS STRICTER RULES
            'sl_multiplier': 0.5,  # Tighter SL
            'breakeven_trigger_percent': 15.0,  # Early break-even
            'partial_trailing_trigger_percent': 30.0,
            'aggressive_trailing_trigger_percent': 55.0,
            'min_confidence': 62.0,  # ✅ LOWERED from 70% - still strict due to poor performance
            'risk_per_trade_percent': 0.015,  # Lower risk (was 2.5%)
        },
        'XAUUSD': {
            # ✅ UPDATED 2025-10-16: Lowering confidence to allow more quality signals
            'sl_multiplier': 0.9,           # Slightly increased from 0.8 to allow more room
            'breakeven_trigger_percent': 15.0,  # Reduced from 25% to 15% (earlier break-even)
            'min_confidence': 52.0,         # ✅ LOWERED from 65% to 52% (balance quality vs quantity)
            'risk_per_trade_percent': 0.015,  # Reduced risk from 2% to 1.5%
        },
        'DE40.c': {
            # PERFORMANCE: 100% win-rate, €0.97 avg → PERFECT, keep aggressive
            'sl_multiplier': 1.0,
            'breakeven_trigger_percent': 30.0,
            'min_confidence': 45.0,  # ✅ LOWERED from 55% (perfect performer, allow more trades)
            'risk_per_trade_percent': 0.02,
        },
    }

    @classmethod
    def get_symbol_type(cls, symbol: str) -> str:
        """Determine symbol type (index, forex, crypto, commodity)"""
        symbol_upper = symbol.upper()

        # Indices
        if any(idx in symbol_upper for idx in ['DE40', 'US30', 'US500', 'NAS100', 'FTSE', 'DAX', 'SPX', 'NDX']):
            return 'index'

        # Cryptocurrencies
        if any(crypto in symbol_upper for crypto in ['BTC', 'ETH', 'CRYPTO']):
            return 'crypto'

        # Commodities
        if any(comm in symbol_upper for comm in ['XAUUSD', 'XAGUSD', 'OIL', 'GOLD', 'SILVER']):
            return 'commodity'

        # Default to forex
        return 'forex'

    @classmethod
    def get_config(cls, symbol: str) -> Dict:
        """
        Get configuration for a specific symbol

        Returns merged config: base category + symbol-specific overrides
        """
        # Check for symbol-specific override first
        if symbol in cls.SYMBOL_OVERRIDES:
            # Merge with category defaults
            symbol_type = cls.get_symbol_type(symbol)
            base_config = cls._get_category_config(symbol_type).copy()
            base_config.update(cls.SYMBOL_OVERRIDES[symbol])
            return base_config

        # Use category defaults
        symbol_type = cls.get_symbol_type(symbol)
        return cls._get_category_config(symbol_type)

    @classmethod
    def _get_category_config(cls, symbol_type: str) -> Dict:
        """Get base configuration for symbol category"""
        if symbol_type == 'index':
            return cls.INDEX_CONFIG.copy()
        elif symbol_type == 'forex':
            return cls.FOREX_CONFIG.copy()
        elif symbol_type == 'crypto':
            return cls.CRYPTO_CONFIG.copy()
        elif symbol_type == 'commodity':
            return cls.COMMODITY_CONFIG.copy()
        else:
            return cls.FOREX_CONFIG.copy()  # Default to forex

    @classmethod
    def get_sl_multiplier(cls, symbol: str) -> float:
        """Get stop-loss multiplier for symbol"""
        config = cls.get_config(symbol)
        return config['sl_multiplier']

    @classmethod
    def get_breakeven_trigger(cls, symbol: str) -> float:
        """Get break-even trigger percentage for symbol"""
        config = cls.get_config(symbol)
        return config['breakeven_trigger_percent']

    @classmethod
    def get_min_confidence(cls, symbol: str) -> float:
        """Get minimum confidence threshold for symbol"""
        config = cls.get_config(symbol)
        return config['min_confidence']

    @classmethod
    def get_risk_per_trade(cls, symbol: str) -> float:
        """Get risk per trade percentage for symbol"""
        config = cls.get_config(symbol)
        return config['risk_per_trade_percent']

    @classmethod
    def update_symbol_override(cls, symbol: str, parameter: str, value: float):
        """
        Update symbol-specific override (learned from performance)

        Args:
            symbol: Symbol to update
            parameter: Parameter name (e.g., 'sl_multiplier')
            value: New value
        """
        if symbol not in cls.SYMBOL_OVERRIDES:
            # Create new override based on category
            symbol_type = cls.get_symbol_type(symbol)
            cls.SYMBOL_OVERRIDES[symbol] = cls._get_category_config(symbol_type).copy()

        cls.SYMBOL_OVERRIDES[symbol][parameter] = value
        logger.info(f"📝 Updated {symbol} {parameter} = {value}")

    @classmethod
    def get_all_configs(cls) -> Dict:
        """Get all symbol configurations for display"""
        configs = {}

        # Add all symbols from overrides
        for symbol in cls.SYMBOL_OVERRIDES:
            configs[symbol] = cls.get_config(symbol)

        return configs


# Quick access functions
def get_symbol_sl_multiplier(symbol: str) -> float:
    """Get SL multiplier for symbol"""
    return SymbolConfig.get_sl_multiplier(symbol)


def get_symbol_min_confidence(symbol: str) -> float:
    """Get minimum confidence for symbol"""
    return SymbolConfig.get_min_confidence(symbol)


def get_symbol_breakeven_trigger(symbol: str) -> float:
    """Get break-even trigger for symbol"""
    return SymbolConfig.get_breakeven_trigger(symbol)
