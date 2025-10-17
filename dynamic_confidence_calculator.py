#!/usr/bin/env python3
"""
Dynamic Confidence Calculator
Calculates required minimum confidence based on:
- Risk profile (moderate/normal/aggressive)
- Symbol characteristics
- Trading session
- Current market volatility
"""

import logging
from typing import Dict, Tuple
from datetime import datetime

logger = logging.getLogger(__name__)


class DynamicConfidenceCalculator:
    """Calculate context-aware minimum confidence requirements"""
    
    def __init__(self):
        # Base confidence levels per risk profile
        self.base_confidence = {
            'moderate': 65.0,    # Conservative: Only high-quality signals
            'normal': 55.0,      # Balanced: Standard risk
            'aggressive': 50.0   # Risk-seeking: More trades
        }
        
        # Symbol-specific adjustments
        # Negative = easier (lower confidence OK), Positive = harder (higher confidence needed)
        self.symbol_adjustments = {
            # Major Forex Pairs (most liquid)
            'EURUSD': -2.0,  # Very stable, low spreads
            'GBPUSD': 0.0,   # Standard
            'USDJPY': -1.0,  # Good liquidity
            'USDCHF': +1.0,  # Less popular
            'AUDUSD': +1.0,  # More volatile
            'NZDUSD': +2.0,  # Less liquid
            'USDCAD': +1.0,  # Commodity-linked
            
            # Cross Pairs (less liquid)
            'EURJPY': +2.0,
            'GBPJPY': +3.0,  # Very volatile
            'EURGBP': +1.0,
            'EURAUD': +2.0,
            'EURCHF': +2.0,
            'AUDNZD': +3.0,
            
            # Commodities
            'XAUUSD': +5.0,  # Gold: High volatility, wide spreads
            'XAGUSD': +6.0,  # Silver: Even more volatile
            'XBRUSD': +5.0,  # Oil
            
            # Indices
            'US30': +3.0,    # Dow Jones
            'US500': +2.0,   # S&P 500
            'USTEC': +4.0,   # Nasdaq (very volatile)
            'DE40': +3.0,    # DAX (renamed from DE40.c)
            'DE40.c': +3.0,  # DAX (with .c suffix)
            'UK100': +3.0,   # FTSE
            'JP225': +4.0,   # Nikkei
            
            # Crypto (highest volatility)
            'BTCUSD': +8.0,  # Bitcoin
            'ETHUSD': +9.0,  # Ethereum
            'XRPUSD': +10.0, # Ripple
            'LTCUSD': +9.0,  # Litecoin
        }
        
        # Session-specific adjustments
        self.session_adjustments = {
            'ASIAN': +5.0,       # Low liquidity, wider spreads
            'LONDON': 0.0,       # Best time to trade
            'US': +2.0,          # Good but more volatile
            'LONDON_US_OVERLAP': -3.0  # Highest liquidity, tightest spreads
        }
    
    def calculate_required_confidence(
        self,
        symbol: str,
        risk_profile: str,
        session: str,
        volatility: float
    ) -> Tuple[float, Dict]:
        """
        Calculate minimum required confidence for a signal
        
        Args:
            symbol: Trading symbol (e.g., 'EURUSD', 'XAUUSD')
            risk_profile: 'moderate', 'normal', or 'aggressive'
            session: 'ASIAN', 'LONDON', 'US', 'LONDON_US_OVERLAP'
            volatility: Current volatility multiplier (0.5=low, 1.0=normal, 2.0=high)
        
        Returns:
            (required_confidence, breakdown_dict)
        """
        # Start with base confidence
        base = self.base_confidence.get(risk_profile, 55.0)
        
        # Symbol adjustment
        symbol_adj = self.symbol_adjustments.get(symbol, 0.0)
        
        # Session adjustment
        session_adj = self.session_adjustments.get(session, 0.0)
        
        # Volatility adjustment
        if volatility > 1.5:  # High volatility
            volatility_adj = +5.0
        elif volatility > 1.2:  # Above normal
            volatility_adj = +2.0
        elif volatility < 0.7:  # Low volatility (tricky)
            volatility_adj = +3.0
        elif volatility < 0.9:  # Below normal
            volatility_adj = +1.0
        else:  # Normal volatility
            volatility_adj = 0.0
        
        # Calculate final required confidence
        required = base + symbol_adj + session_adj + volatility_adj
        
        # Clamp between 50% and 85%
        required = max(50.0, min(required, 85.0))
        
        # Build breakdown for logging/debugging
        breakdown = {
            'base': base,
            'symbol_adjustment': symbol_adj,
            'session_adjustment': session_adj,
            'volatility_adjustment': volatility_adj,
            'total_adjustment': symbol_adj + session_adj + volatility_adj,
            'required_confidence': required,
            'risk_profile': risk_profile,
            'session': session,
            'volatility_multiplier': volatility
        }
        
        return required, breakdown
    
    def get_all_requirements(
        self,
        symbols: list,
        risk_profile: str,
        session: str,
        volatility_map: Dict[str, float]
    ) -> Dict[str, Dict]:
        """
        Get required confidence for multiple symbols
        
        Returns:
            {
                'EURUSD': {
                    'required_confidence': 53.0,
                    'breakdown': {...}
                },
                ...
            }
        """
        results = {}
        
        for symbol in symbols:
            volatility = volatility_map.get(symbol, 1.0)
            required, breakdown = self.calculate_required_confidence(
                symbol, risk_profile, session, volatility
            )
            results[symbol] = {
                'required_confidence': required,
                'breakdown': breakdown
            }
        
        return results


# Singleton instance
_calculator = None

def get_confidence_calculator() -> DynamicConfidenceCalculator:
    """Get or create singleton calculator instance"""
    global _calculator
    if _calculator is None:
        _calculator = DynamicConfidenceCalculator()
    return _calculator
