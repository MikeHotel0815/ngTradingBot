"""
Heiken Ashi Trend Indicator Configuration
Symbol-specific parameters based on 30-day backtest results
"""

# Symbol-specific configuration for Heiken Ashi Trend indicator
HEIKEN_ASHI_CONFIG = {
    'XAUUSD': {
        'enabled': True,
        'timeframes': {
            'M5': {
                'enabled': True,
                'priority': 'HIGHEST',
                'sl_multiplier': 1.5,  # Tighter for M5
                'tp_multiplier': 3.0,
                'min_confidence': 60,  # Lower bar (proven profitable)
                'notes': 'Star performer: +23.74% in 30 days, 42.0% WR'
            },
            'H1': {
                'enabled': True,
                'priority': 'HIGH',
                'sl_multiplier': 2.0,  # Wider for H1 volatility
                'tp_multiplier': 4.0,
                'min_confidence': 65,
                'notes': 'Solid performer: +4.00% in 30 days, 45.5% WR'
            }
        }
    },
    'EURUSD': {
        'enabled': True,
        'timeframes': {
            'H1': {
                'enabled': True,
                'priority': 'HIGH',
                'sl_multiplier': 1.5,
                'tp_multiplier': 3.0,
                'min_confidence': 70,  # Higher bar for selectivity
                'notes': 'Best win rate: 50.7%, +3.75% in 30 days'
            },
            'M5': {
                'enabled': False,  # Too noisy, disabled for now
                'priority': 'LOW',
                'sl_multiplier': 1.0,
                'tp_multiplier': 2.0,
                'min_confidence': 75,
                'notes': 'High volume (823 trades), marginal profit (+1.98%)'
            }
        }
    },
    'USDJPY': {
        'enabled': True,
        'timeframes': {
            'H1': {
                'enabled': True,
                'priority': 'MEDIUM',
                'sl_multiplier': 1.5,
                'tp_multiplier': 3.0,
                'min_confidence': 65,
                'notes': 'Consistent performer: +2.47% in 30 days, 41.2% WR'
            }
        }
    },
    'GBPUSD': {
        'enabled': True,
        'timeframes': {
            'H1': {
                'enabled': True,
                'priority': 'LOW',
                'sl_multiplier': 1.5,
                'tp_multiplier': 3.0,
                'min_confidence': 70,
                'notes': 'Marginal performer: +0.67% in 30 days, 38.7% WR'
            }
        }
    },
    # Disabled symbols (poor performance in backtest)
    'DE40.c': {
        'enabled': False,
        'timeframes': {},
        'notes': 'DISABLED: 25.0% WR, -3.60% in 30 days'
    }
}


def get_heiken_ashi_config(symbol: str, timeframe: str) -> dict:
    """
    Get Heiken Ashi configuration for a specific symbol/timeframe

    Args:
        symbol: Trading symbol (e.g., 'XAUUSD')
        timeframe: Timeframe (e.g., 'H1', 'M5')

    Returns:
        Configuration dict or None if disabled
    """
    if symbol not in HEIKEN_ASHI_CONFIG:
        return None

    symbol_config = HEIKEN_ASHI_CONFIG[symbol]

    if not symbol_config.get('enabled', False):
        return None

    timeframes = symbol_config.get('timeframes', {})
    if timeframe not in timeframes:
        return None

    tf_config = timeframes[timeframe]
    if not tf_config.get('enabled', False):
        return None

    return tf_config


def is_heiken_ashi_enabled(symbol: str, timeframe: str) -> bool:
    """
    Check if Heiken Ashi is enabled for a symbol/timeframe

    Args:
        symbol: Trading symbol
        timeframe: Timeframe

    Returns:
        True if enabled, False otherwise
    """
    config = get_heiken_ashi_config(symbol, timeframe)
    return config is not None


def get_enabled_symbols() -> list:
    """
    Get list of all enabled symbols for Heiken Ashi

    Returns:
        List of enabled symbols
    """
    enabled = []
    for symbol, config in HEIKEN_ASHI_CONFIG.items():
        if config.get('enabled', False):
            enabled.append(symbol)
    return enabled


def get_enabled_timeframes(symbol: str) -> list:
    """
    Get list of enabled timeframes for a symbol

    Args:
        symbol: Trading symbol

    Returns:
        List of enabled timeframes
    """
    if symbol not in HEIKEN_ASHI_CONFIG:
        return []

    symbol_config = HEIKEN_ASHI_CONFIG[symbol]
    if not symbol_config.get('enabled', False):
        return []

    timeframes = symbol_config.get('timeframes', {})
    enabled = [
        tf for tf, config in timeframes.items()
        if config.get('enabled', False)
    ]
    return enabled


# Confidence calculation parameters (recalibrated based on backtest)
CONFIDENCE_PARAMS = {
    'base': 40,  # Down from 50 (less generous)
    'strong_ha_signal': 10,
    'ema_alignment': 12,
    'recent_reversal': 8,
    'volume_multipliers': {
        'very_high': 1.30,  # ≥1.5x avg volume
        'high': 1.15,       # ≥1.2x avg volume
        'normal': 1.00,     # 0.8x - 1.2x
        'low': 0.90         # <0.8x avg volume
    }
}


def calculate_ha_confidence(
    ha_signal: str,
    has_no_wick: bool,
    ema_aligned: bool,
    recent_reversal: bool,
    volume_ratio: float
) -> int:
    """
    Calculate confidence score for Heiken Ashi signal

    Args:
        ha_signal: 'strong_buy', 'buy', 'strong_sell', 'sell'
        has_no_wick: True if candle has no opposite wick
        ema_aligned: True if EMAs are properly aligned
        recent_reversal: True if recent reversal detected
        volume_ratio: Current volume / average volume

    Returns:
        Confidence score (0-100)
    """
    confidence = CONFIDENCE_PARAMS['base']

    # Strong HA signal bonus
    if ha_signal in ['strong_buy', 'strong_sell']:
        confidence += CONFIDENCE_PARAMS['strong_ha_signal']

    # EMA alignment bonus
    if ema_aligned:
        confidence += CONFIDENCE_PARAMS['ema_alignment']

    # Recent reversal bonus
    if recent_reversal:
        confidence += CONFIDENCE_PARAMS['recent_reversal']

    # Volume multiplier
    volume_mult = 1.0
    if volume_ratio >= 1.5:
        volume_mult = CONFIDENCE_PARAMS['volume_multipliers']['very_high']
    elif volume_ratio >= 1.2:
        volume_mult = CONFIDENCE_PARAMS['volume_multipliers']['high']
    elif volume_ratio < 0.8:
        volume_mult = CONFIDENCE_PARAMS['volume_multipliers']['low']

    confidence = int(confidence * volume_mult)

    # Cap at 100
    return min(100, confidence)
