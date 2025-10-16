#!/usr/bin/env python3
"""
Session and Volatility Analyzer
Analyzes market noise and volatility for different trading sessions

Critical for trailing stops:
- Asian session (low volatility) = tighter stops
- London session (high volatility) = wider stops
- US session (very high volatility) = widest stops
- Overlaps (London+US) = maximum volatility

Also considers:
- News events
- Market holidays
- Weekend vs. weekday
"""

import logging
from datetime import datetime, time
from typing import Dict, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import func
from models import Tick
import pytz

logger = logging.getLogger(__name__)


class SessionVolatilityAnalyzer:
    """Analyze trading sessions and adjust for volatility"""

    def __init__(self):
        self.sessions = {
            'ASIAN': {
                'start': time(0, 0),    # 00:00 UTC
                'end': time(8, 0),      # 08:00 UTC
                'volatility_multiplier': 0.7,  # Lower volatility
                'description': 'Asian Session (Tokyo)'
            },
            'LONDON': {
                'start': time(8, 0),    # 08:00 UTC
                'end': time(16, 0),     # 16:00 UTC
                'volatility_multiplier': 1.2,  # Higher volatility
                'description': 'London Session'
            },
            'US': {
                'start': time(13, 0),   # 13:00 UTC
                'end': time(22, 0),     # 22:00 UTC
                'volatility_multiplier': 1.3,  # Highest volatility
                'description': 'US Session (NYSE)'
            },
            'LONDON_US_OVERLAP': {
                'start': time(13, 0),   # 13:00 UTC
                'end': time(16, 0),     # 16:00 UTC
                'volatility_multiplier': 1.5,  # Maximum volatility
                'description': 'London+US Overlap'
            },
        }

        # Symbol-specific session importance
        self.symbol_session_weights = {
            'EURUSD': {'LONDON': 1.5, 'US': 1.2, 'ASIAN': 0.6},
            'GBPUSD': {'LONDON': 1.8, 'US': 1.3, 'ASIAN': 0.5},
            'USDJPY': {'US': 1.4, 'ASIAN': 1.2, 'LONDON': 0.9},
            'XAUUSD': {'US': 1.5, 'LONDON': 1.3, 'ASIAN': 0.7},
            'BTCUSD': {'US': 1.3, 'LONDON': 1.2, 'ASIAN': 1.1},  # 24/7 but US-driven
        }

    def get_current_session(self, utc_time: datetime = None) -> Tuple[str, Dict]:
        """
        Determine current trading session

        Returns:
            (session_name, session_info)
        """
        if utc_time is None:
            utc_time = datetime.utcnow()

        current_time = utc_time.time()

        # Check for overlap first (highest priority)
        overlap = self.sessions['LONDON_US_OVERLAP']
        if overlap['start'] <= current_time < overlap['end']:
            return 'LONDON_US_OVERLAP', overlap

        # Check other sessions
        for session_name, session_info in self.sessions.items():
            if session_name == 'LONDON_US_OVERLAP':
                continue

            start = session_info['start']
            end = session_info['end']

            # Handle overnight sessions (e.g., Asian wrapping around midnight)
            if start > end:
                if current_time >= start or current_time < end:
                    return session_name, session_info
            else:
                if start <= current_time < end:
                    return session_name, session_info

        # Default to Asian if nothing matched
        return 'ASIAN', self.sessions['ASIAN']

    def calculate_recent_volatility(
        self,
        db: Session,
        symbol: str,
        account_id: int,
        lookback_minutes: int = 60
    ) -> float:
        """
        Calculate recent volatility from tick data

        Returns:
            Volatility score (0.5 = low, 1.0 = normal, 2.0 = high)
        """
        try:
            from datetime import timedelta

            cutoff_time = datetime.utcnow() - timedelta(minutes=lookback_minutes)

            # Get ticks from last N minutes (ticks are global - no account_id)
            ticks = db.query(Tick).filter(
                Tick.symbol == symbol,
                Tick.timestamp >= cutoff_time
            ).all()

            if len(ticks) < 10:
                logger.debug(f"Not enough ticks for {symbol} volatility calculation")
                return 1.0  # Default to normal

            # Calculate price range
            prices = [float(t.bid) for t in ticks]
            price_range = max(prices) - min(prices)
            avg_price = sum(prices) / len(prices)

            # Calculate volatility as % of price
            if avg_price > 0:
                volatility_percent = (price_range / avg_price) * 100
            else:
                return 1.0

            # Map to multiplier
            # Low volatility: < 0.05% range = 0.5x
            # Normal: 0.05-0.15% = 1.0x
            # High: > 0.15% = up to 2.0x
            if volatility_percent < 0.05:
                return 0.5
            elif volatility_percent < 0.15:
                return 1.0
            elif volatility_percent < 0.3:
                return 1.5
            else:
                return 2.0

        except Exception as e:
            logger.error(f"Error calculating volatility: {e}")
            return 1.0

    def get_trailing_distance_multiplier(
        self,
        symbol: str,
        db: Session = None,
        account_id: int = 1,
        utc_time: datetime = None
    ) -> Tuple[float, str]:
        """
        Calculate trailing distance multiplier based on:
        - Current session
        - Recent volatility
        - Symbol-specific session importance

        Returns:
            (multiplier, reason)
        """
        # Get current session
        session_name, session_info = self.get_current_session(utc_time)
        base_multiplier = session_info['volatility_multiplier']

        # Get symbol-specific session weight
        symbol_weights = self.symbol_session_weights.get(symbol, {})
        session_weight = symbol_weights.get(session_name, 1.0)

        # Combine session base and symbol weight
        session_multiplier = base_multiplier * session_weight

        # Get recent volatility if DB available
        if db:
            volatility_multiplier = self.calculate_recent_volatility(
                db, symbol, account_id, lookback_minutes=60
            )
        else:
            volatility_multiplier = 1.0

        # Final multiplier
        final_multiplier = session_multiplier * volatility_multiplier

        # Clamp to reasonable range (0.5x to 2.5x)
        final_multiplier = max(0.5, min(final_multiplier, 2.5))

        reason = (
            f"{session_info['description']}: "
            f"session={session_multiplier:.2f}x, "
            f"volatility={volatility_multiplier:.2f}x, "
            f"final={final_multiplier:.2f}x"
        )

        logger.debug(f"{symbol} trailing multiplier: {reason}")

        return final_multiplier, reason

    def is_high_volatility_period(
        self,
        symbol: str,
        db: Session = None,
        account_id: int = 1
    ) -> bool:
        """Check if current period has high volatility"""
        multiplier, _ = self.get_trailing_distance_multiplier(symbol, db, account_id)
        return multiplier > 1.5


# Singleton
_analyzer = None


def get_session_volatility_analyzer():
    """Get or create analyzer instance"""
    global _analyzer
    if _analyzer is None:
        _analyzer = SessionVolatilityAnalyzer()
    return _analyzer
