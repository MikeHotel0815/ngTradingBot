"""
Market Hours Configuration
Based on actual tick/OHLC data analysis from broker

All times in UTC (server timezone)
"""

from typing import Dict, List, Tuple
from datetime import datetime, time
import logging

logger = logging.getLogger(__name__)


class MarketHours:
    """
    Market hours configuration per symbol
    Based on empirical analysis of tick/OHLC data patterns
    """

    # Market hours: {symbol: {day_of_week: (open_hour, close_hour)}}
    # day_of_week: 0=Sunday, 1=Monday, ..., 6=Saturday
    # Times in UTC

    MARKET_HOURS = {
        # FOREX - 24h trading Mon-Fri, opens Sunday evening
        'EURUSD': {
            0: (22, 23),  # Sunday: Opens 22:00 UTC
            1: (0, 23),   # Monday-Thursday: Full 24h
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),   # Friday: Closes ~21:00 UTC
            6: None       # Saturday: Closed
        },
        'GBPUSD': {
            0: (22, 23),
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),
            6: None
        },
        'USDJPY': {
            0: (22, 23),
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),
            6: None
        },
        'AUDUSD': {
            0: (22, 23),  # Sunday: Opens 22:00 UTC (Monday 8am Sydney)
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),
            6: None
        },
        'USDCHF': {
            0: (22, 23),
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),
            6: None
        },
        'NZDUSD': {
            0: (22, 23),
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),
            6: None
        },

        # COMMODITIES - 23h trading with 1h break
        'XAUUSD': {
            0: (23, 23),  # Sunday: Opens 23:00 UTC
            1: (1, 23),   # Monday-Thursday: 01:00-23:00 (23h break 00:00-01:00)
            2: (1, 23),
            3: (1, 23),
            4: (1, 23),
            5: (0, 21),   # Friday: 00:00-21:00
            6: None
        },
        'XAGUSD': {
            0: (23, 23),  # Sunday: Opens 23:00 UTC
            1: (1, 23),   # Monday-Thursday: 01:00-23:00
            2: (1, 23),
            3: (1, 23),
            4: (1, 23),
            5: (1, 21),   # Friday: 01:00-21:00
            6: None
        },

        # INDICES
        'DE40.c': {
            0: None,      # Sunday: Closed
            1: (8, 22),   # Monday-Thursday: 09:00-22:00 CET (08:00-21:00 UTC in winter)
            2: (8, 22),
            3: (8, 22),
            4: (8, 22),
            5: (6, 22),   # Friday: Opens earlier at 06:00 UTC
            6: None       # Saturday: Closed
        },
        'US500.c': {
            0: (18, 23),  # Sunday: Opens 18:00 UTC (6pm ET futures open)
            1: (0, 23),   # Monday-Thursday: Nearly 24h
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),   # Friday: Closes 21:00 UTC
            6: None
        },
        'US30': {
            0: (18, 23),
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),
            6: None
        },
        'USTEC': {  # Nasdaq
            0: (18, 23),
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 21),
            6: None
        },

        # CRYPTO - 24/7
        'BTCUSD': {
            0: (0, 23),
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 23),
            6: (0, 23)
        },
        'ETHUSD': {
            0: (0, 23),
            1: (0, 23),
            2: (0, 23),
            3: (0, 23),
            4: (0, 23),
            5: (0, 23),
            6: (0, 23)
        },
    }

    @classmethod
    def is_market_open(cls, symbol: str, dt: datetime = None) -> bool:
        """
        Check if market is open for given symbol at given time

        Args:
            symbol: Trading symbol
            dt: Datetime to check (default: now UTC)

        Returns:
            True if market is open, False otherwise
        """
        if dt is None:
            dt = datetime.utcnow()

        # Get market hours for symbol
        hours = cls.MARKET_HOURS.get(symbol)
        if not hours:
            logger.warning(f"No market hours defined for {symbol}, assuming open")
            return True

        # Get day of week (0=Sunday)
        dow = (dt.weekday() + 1) % 7

        # Get hours for this day
        day_hours = hours.get(dow)
        if day_hours is None:
            return False  # Market closed this day

        open_hour, close_hour = day_hours
        current_hour = dt.hour

        # Check if within trading hours
        if open_hour <= close_hour:
            # Normal case: 09:00-22:00
            return open_hour <= current_hour <= close_hour
        else:
            # Spans midnight: 22:00-02:00
            return current_hour >= open_hour or current_hour <= close_hour

    @classmethod
    def get_next_open_time(cls, symbol: str, dt: datetime = None) -> datetime:
        """
        Get next market open time for symbol

        Returns:
            Datetime of next market open
        """
        if dt is None:
            dt = datetime.utcnow()

        hours = cls.MARKET_HOURS.get(symbol)
        if not hours:
            return dt  # Unknown symbol, return current time

        # Search next 7 days
        for day_offset in range(8):
            check_dt = dt + timedelta(days=day_offset)
            dow = (check_dt.weekday() + 1) % 7
            day_hours = hours.get(dow)

            if day_hours is None:
                continue  # Closed this day

            open_hour, _ = day_hours
            open_time = check_dt.replace(hour=open_hour, minute=0, second=0)

            if open_time > dt:
                return open_time

        return dt  # Fallback

    @classmethod
    def get_trading_session(cls, symbol: str, dt: datetime = None) -> str:
        """
        Get current trading session for symbol

        Returns:
            'ASIAN', 'LONDON', 'US', 'LONDON_US_OVERLAP', or 'CLOSED'
        """
        if dt is None:
            dt = datetime.utcnow()

        if not cls.is_market_open(symbol, dt):
            return 'CLOSED'

        hour = dt.hour

        # Session times (UTC)
        # ASIAN: 00:00-08:00 UTC (Tokyo 09:00-17:00 JST)
        # LONDON: 08:00-16:00 UTC (London 08:00-16:00 GMT)
        # US: 13:00-22:00 UTC (New York 08:00-17:00 EST)
        # OVERLAP: 13:00-16:00 UTC

        if 13 <= hour < 16:
            return 'LONDON_US_OVERLAP'  # Highest liquidity
        elif 8 <= hour < 16:
            return 'LONDON'
        elif 13 <= hour < 22:
            return 'US'
        else:  # 0-8, 22-24
            return 'ASIAN'

    @classmethod
    def get_market_hours_string(cls, symbol: str) -> str:
        """Get human-readable market hours string"""
        hours = cls.MARKET_HOURS.get(symbol)
        if not hours:
            return "Unknown"

        days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
        schedule = []

        for dow in range(7):
            day_hours = hours.get(dow)
            if day_hours:
                open_h, close_h = day_hours
                schedule.append(f"{days[dow]} {open_h:02d}:00-{close_h:02d}:00")
            else:
                schedule.append(f"{days[dow]} CLOSED")

        return " | ".join(schedule)


# Quick access functions
def is_market_open(symbol: str, dt: datetime = None) -> bool:
    """Check if market is open for symbol"""
    return MarketHours.is_market_open(symbol, dt)


def get_trading_session(symbol: str, dt: datetime = None) -> str:
    """Get current trading session"""
    return MarketHours.get_trading_session(symbol, dt)


def get_market_hours(symbol: str) -> str:
    """Get market hours string"""
    return MarketHours.get_market_hours_string(symbol)


# Import for timedelta
from datetime import timedelta
