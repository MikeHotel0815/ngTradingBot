"""
Signal Generator Configuration
Centralized configuration for signal generation thresholds and parameters
"""

from typing import Dict

# ============================================================================
# CORE SIGNAL GENERATION PARAMETERS
# ============================================================================

# Minimum confidence threshold for generating signals (0-100)
# Signals below this threshold are not generated
MIN_GENERATION_CONFIDENCE = 50

# Minimum confidence threshold for keeping signals active (0-100)
# Active signals below this are expired
MIN_ACTIVE_CONFIDENCE = 50

# Maximum spread multiplier vs average
# Reject signals when spread > avg_spread * MAX_SPREAD_MULTIPLIER
MAX_SPREAD_MULTIPLIER = 3.0

# ============================================================================
# BUY/SELL SIGNAL BALANCE
# ============================================================================

# BUY signal advantage: requires this many more confirming signals than SELL
# 0 = No bias (simple majority for both)
# 1 = BUY needs 1 more confirming signal than SELL
# 2 = BUY needs 2 more confirming signals than SELL (conservative)
BUY_SIGNAL_ADVANTAGE = 1  # Reduced from 2 - less conservative

# BUY confidence penalty (percentage points)
# Reduces BUY signal confidence to make them harder to trigger
# 0.0 = No penalty (treat BUY and SELL equally)
# 5.0 = Reduce BUY confidence by 5%
# 🎯 INCREASED 2025-11-06: BUY trades have -263€ loss vs SELL +52€ profit
BUY_CONFIDENCE_PENALTY = 15.0  # Increased from 1.0 - BUY trades severely underperform

# ============================================================================
# CONFIDENCE CALCULATION WEIGHTS
# ============================================================================

# Confidence formula: Pattern + Indicators + Strength = 100%
PATTERN_WEIGHT = 30      # Pattern reliability contribution (0-30)
INDICATOR_WEIGHT = 40    # Indicator confluence contribution (0-40)
STRENGTH_WEIGHT = 30     # Signal strength contribution (0-30)

# Bonus points
ADX_STRONG_TREND_BONUS = 3   # Bonus when ADX shows strong trend
OBV_DIVERGENCE_BONUS = 2     # Bonus when OBV shows divergence
CONFLUENCE_BONUS_PER_INDICATOR = 2  # Bonus per agreeing indicator (max 10)

# ============================================================================
# MULTI-TIMEFRAME ANALYSIS
# ============================================================================

# Enable/disable multi-timeframe conflict detection
ENABLE_MTF_ANALYSIS = True

# Timeframe hierarchy (from lowest to highest)
# Lower timeframes checked against higher timeframes
TIMEFRAME_HIERARCHY = ['M1', 'M5', 'M15', 'H1', 'H4', 'D1']

# ============================================================================
# ML ENHANCEMENT
# ============================================================================

# Enable ML model enhancement (requires ml module)
ENABLE_ML_ENHANCEMENT = True

# A/B test distribution (must sum to 100)
ML_AB_TEST_DISTRIBUTION = {
    'ml_only': 80,    # 80% use ML confidence
    'rules_only': 10,  # 10% use rules-based confidence
    'hybrid': 10       # 10% use hybrid (average of both)
}

# ============================================================================
# VALIDATION & EXPIRATION
# ============================================================================

# Signal validation interval (seconds)
VALIDATION_INTERVAL = 10

# Indicator tolerance for validation (percentage)
INDICATOR_TOLERANCE_PCT = 5.0

# Signal expiration time (hours)
SIGNAL_EXPIRATION_HOURS = 24

# Cache TTL for indicators/patterns (seconds)
CACHE_TTL = 15  # Reduced from 300 for faster updates

# ============================================================================
# TIMEFRAME-SPECIFIC ADJUSTMENTS
# ============================================================================

# 🎯 ADDED 2025-11-06: H1 timeframe loses -324€ vs H4 +131€
# Increase minimum confidence for H1 to reduce low-quality signals
TIMEFRAME_MIN_CONFIDENCE = {
    'M1': 80,   # Very short-term, needs high confidence
    'M5': 75,   # Short-term
    'M15': 70,  # Medium-term
    'H1': 85,   # 🔴 INCREASED: H1 severely underperforms
    'H4': 60,   # ✅ H4 is profitable, keep lower threshold
    'D1': 65,   # Long-term
}

# ============================================================================
# SYMBOL-SPECIFIC OVERRIDES
# ============================================================================

# Override default parameters for specific symbols
# Format: 'SYMBOL': {'parameter': value}
SYMBOL_OVERRIDES: Dict[str, Dict] = {
    # Example: More conservative settings for volatile symbols
    'XAUUSD': {
        'MIN_GENERATION_CONFIDENCE': 55,
        'BUY_SIGNAL_ADVANTAGE': 2,
    },
    'XAGUSD': {
        'MIN_GENERATION_CONFIDENCE': 55,
        'BUY_SIGNAL_ADVANTAGE': 2,
    },
    # Example: Less conservative for forex majors
    'EURUSD': {
        'MIN_GENERATION_CONFIDENCE': 48,
        'BUY_SIGNAL_ADVANTAGE': 1,
    },
    'GBPUSD': {
        'MIN_GENERATION_CONFIDENCE': 48,
        'BUY_SIGNAL_ADVANTAGE': 1,
    },
    'AUDUSD': {
        'MIN_GENERATION_CONFIDENCE': 48,
        'BUY_SIGNAL_ADVANTAGE': 1,
    },
}

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_config(symbol: str = None) -> Dict:
    """
    Get configuration for a specific symbol with overrides applied

    Args:
        symbol: Trading symbol (optional)

    Returns:
        Dict with all configuration parameters
    """
    config = {
        # Core parameters
        'MIN_GENERATION_CONFIDENCE': MIN_GENERATION_CONFIDENCE,
        'MIN_ACTIVE_CONFIDENCE': MIN_ACTIVE_CONFIDENCE,
        'MAX_SPREAD_MULTIPLIER': MAX_SPREAD_MULTIPLIER,

        # BUY/SELL balance
        'BUY_SIGNAL_ADVANTAGE': BUY_SIGNAL_ADVANTAGE,
        'BUY_CONFIDENCE_PENALTY': BUY_CONFIDENCE_PENALTY,

        # Confidence weights
        'PATTERN_WEIGHT': PATTERN_WEIGHT,
        'INDICATOR_WEIGHT': INDICATOR_WEIGHT,
        'STRENGTH_WEIGHT': STRENGTH_WEIGHT,
        'ADX_STRONG_TREND_BONUS': ADX_STRONG_TREND_BONUS,
        'OBV_DIVERGENCE_BONUS': OBV_DIVERGENCE_BONUS,
        'CONFLUENCE_BONUS_PER_INDICATOR': CONFLUENCE_BONUS_PER_INDICATOR,

        # Multi-timeframe
        'ENABLE_MTF_ANALYSIS': ENABLE_MTF_ANALYSIS,
        'TIMEFRAME_HIERARCHY': TIMEFRAME_HIERARCHY,

        # ML
        'ENABLE_ML_ENHANCEMENT': ENABLE_ML_ENHANCEMENT,
        'ML_AB_TEST_DISTRIBUTION': ML_AB_TEST_DISTRIBUTION,

        # Validation
        'VALIDATION_INTERVAL': VALIDATION_INTERVAL,
        'INDICATOR_TOLERANCE_PCT': INDICATOR_TOLERANCE_PCT,
        'SIGNAL_EXPIRATION_HOURS': SIGNAL_EXPIRATION_HOURS,
        'CACHE_TTL': CACHE_TTL,
    }

    # Apply symbol-specific overrides
    if symbol and symbol in SYMBOL_OVERRIDES:
        config.update(SYMBOL_OVERRIDES[symbol])

    return config


def update_config(symbol: str, **kwargs):
    """
    Update configuration for a specific symbol

    Args:
        symbol: Trading symbol
        **kwargs: Configuration parameters to update
    """
    if symbol not in SYMBOL_OVERRIDES:
        SYMBOL_OVERRIDES[symbol] = {}

    SYMBOL_OVERRIDES[symbol].update(kwargs)
