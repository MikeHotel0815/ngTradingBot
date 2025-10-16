"""
Trading hours configuration for different symbols.
Based on standard market trading hours to prevent false watchdog alerts.
"""

from datetime import time
from typing import Dict, List, Tuple, Optional
import pytz

# Trading hours are in UTC
TRADING_SCHEDULES = {
    # Forex pairs - Trade 24/5 (Sunday 22:00 UTC to Friday 22:00 UTC)
    'EURUSD': {
        'type': 'forex',
        'days': [0, 1, 2, 3, 4],  # Monday-Friday
        'hours_utc': list(range(24)),  # All hours
        'sunday_from': 22,  # Opens Sunday 22:00 UTC
        'friday_until': 22,  # Closes Friday 22:00 UTC
        'description': 'Forex 24/5 (Sun 22:00 - Fri 22:00 UTC)'
    },
    'GBPUSD': {
        'type': 'forex',
        'days': [0, 1, 2, 3, 4],
        'hours_utc': list(range(24)),
        'sunday_from': 22,
        'friday_until': 22,
        'description': 'Forex 24/5 (Sun 22:00 - Fri 22:00 UTC)'
    },
    'USDJPY': {
        'type': 'forex',
        'days': [0, 1, 2, 3, 4],
        'hours_utc': list(range(24)),
        'sunday_from': 22,
        'friday_until': 22,
        'description': 'Forex 24/5 (Sun 22:00 - Fri 22:00 UTC)'
    },

    # Gold - Similar to Forex, trades nearly 24/5
    'XAUUSD': {
        'type': 'commodity',
        'days': [0, 1, 2, 3, 4],
        'hours_utc': list(range(1, 24)) + [0],  # 01:00-23:59 UTC
        'sunday_from': 23,
        'friday_until': 22,
        'description': 'Gold 24/5 (Sun 23:00 - Fri 22:00 UTC)'
    },

    # DAX (DE40) - German index
    # Xetra: 07:00-17:30 UTC (09:00-19:30 Berlin summer, 08:00-18:30 winter)
    # Extended hours with derivatives: 01:00-22:00 UTC
    'DE40.c': {
        'type': 'index',
        'days': [0, 1, 2, 3, 4],  # Monday-Friday
        'hours_utc': list(range(1, 22)),  # 01:00-21:59 UTC (extended hours)
        'core_hours_utc': list(range(7, 18)),  # 07:00-17:59 UTC (main session)
        'description': 'DAX Mon-Fri 01:00-22:00 UTC (core: 07:00-18:00)'
    },

    # Bitcoin - Trades 24/7
    'BTCUSD': {
        'type': 'crypto',
        'days': [0, 1, 2, 3, 4, 5, 6],  # Every day
        'hours_utc': list(range(24)),  # All hours
        'description': 'Bitcoin 24/7'
    },
}


def is_market_open(symbol: str, dt_utc) -> Tuple[bool, Optional[str]]:
    """
    Check if a market should be open for a given symbol at a specific UTC time.

    Args:
        symbol: Trading symbol (e.g., 'EURUSD', 'DE40.c')
        dt_utc: datetime object in UTC timezone

    Returns:
        Tuple of (is_open: bool, reason: str)
        - is_open: True if market should be open
        - reason: Explanation if market is closed
    """

    if symbol not in TRADING_SCHEDULES:
        # Unknown symbol - assume always open (don't suppress alerts)
        return True, None

    schedule = TRADING_SCHEDULES[symbol]

    # Get day of week (0=Monday, 6=Sunday)
    weekday = dt_utc.weekday()
    hour = dt_utc.hour

    # Check crypto (24/7)
    if schedule['type'] == 'crypto':
        return True, None

    # Check if it's a trading day
    if weekday not in schedule['days']:
        # Special check for Sunday opening (Forex)
        if weekday == 6 and 'sunday_from' in schedule:
            if hour >= schedule['sunday_from']:
                return True, None
            return False, f"Market closed: Before Sunday opening ({schedule['sunday_from']:02d}:00 UTC)"

        # Special check for Friday closing
        if weekday == 4 and 'friday_until' in schedule:
            if hour < schedule['friday_until']:
                return True, None
            return False, f"Market closed: After Friday close ({schedule['friday_until']:02d}:00 UTC)"

        day_names = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
        return False, f"Market closed: {day_names[weekday]} not a trading day"

    # Check trading hours
    if hour not in schedule['hours_utc']:
        return False, f"Market closed: Outside trading hours ({hour:02d}:00 UTC)"

    return True, None


def get_next_open_time(symbol: str, dt_utc) -> Optional[str]:
    """
    Get a human-readable string for when the market opens next.

    Args:
        symbol: Trading symbol
        dt_utc: Current datetime in UTC

    Returns:
        String describing when market opens, or None if unknown
    """

    if symbol not in TRADING_SCHEDULES:
        return None

    schedule = TRADING_SCHEDULES[symbol]

    if schedule['type'] == 'crypto':
        return "Market is 24/7"

    weekday = dt_utc.weekday()
    hour = dt_utc.hour

    # If it's weekend
    if weekday == 5:  # Saturday
        return f"Opens Sunday {schedule.get('sunday_from', 22):02d}:00 UTC"

    if weekday == 6:  # Sunday before opening
        if hour < schedule.get('sunday_from', 22):
            return f"Opens today at {schedule.get('sunday_from', 22):02d}:00 UTC"

    # If it's Friday after close
    if weekday == 4 and hour >= schedule.get('friday_until', 22):
        return f"Opens Sunday {schedule.get('sunday_from', 22):02d}:00 UTC"

    # During week - opens next trading day
    if 'hours_utc' in schedule and schedule['hours_utc']:
        next_hour = min(schedule['hours_utc'])
        return f"Opens tomorrow at {next_hour:02d}:00 UTC"

    return schedule.get('description', 'Unknown schedule')


# Quick reference
def print_all_schedules():
    """Print all configured trading schedules."""

    print("=" * 100)
    print("CONFIGURED TRADING SCHEDULES")
    print("=" * 100)

    for symbol, schedule in TRADING_SCHEDULES.items():
        print(f"\n{symbol} ({schedule['type'].upper()})")
        print(f"  {schedule['description']}")

        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        active_days = [day_names[d] for d in schedule['days']]
        print(f"  Days: {', '.join(active_days)}")

        if schedule['type'] != 'crypto':
            hours = schedule['hours_utc']
            if hours:
                print(f"  Hours (UTC): {min(hours):02d}:00 - {max(hours):02d}:59")

    print("\n" + "=" * 100)


if __name__ == "__main__":
    from datetime import datetime
    import pytz

    print_all_schedules()

    # Test current time
    now_utc = datetime.now(pytz.UTC)
    print(f"\nCurrent time: {now_utc.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print("\nMarket Status:")
    print("-" * 100)

    for symbol in TRADING_SCHEDULES.keys():
        is_open, reason = is_market_open(symbol, now_utc)
        status = "✅ OPEN" if is_open else "❌ CLOSED"
        print(f"{symbol:10s} {status:12s}  {reason or ''}")

        if not is_open:
            next_open = get_next_open_time(symbol, now_utc)
            if next_open:
                print(f"{'':10s} {'':12s}  → {next_open}")
