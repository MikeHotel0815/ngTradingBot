#!/usr/bin/env python3
"""
Analyze trading hours for each symbol based on historical tick data.
This helps determine when to suppress watchdog alerts for legitimate market closures.
"""

from database import SessionLocal
from models import Tick
from sqlalchemy import func, extract
from datetime import datetime, timedelta
import pytz
from collections import defaultdict

def analyze_trading_hours():
    """Analyze tick data to determine trading hours for each symbol."""

    db = SessionLocal()
    berlin_tz = pytz.timezone('Europe/Berlin')
    now_utc = datetime.now(pytz.UTC)
    week_ago = now_utc - timedelta(days=7)

    # Get all distinct symbols
    symbols = db.query(Tick.symbol).distinct().all()
    symbols = [s[0] for s in symbols]

    print("=" * 100)
    print(f"TRADING HOURS ANALYSIS - Last 7 Days")
    print(f"Current time: {now_utc.astimezone(berlin_tz).strftime('%Y-%m-%d %H:%M:%S')} Berlin")
    print("=" * 100)

    trading_schedules = {}

    for symbol in sorted(symbols):
        print(f"\n📊 {symbol}")
        print("-" * 100)

        # Get all ticks for this symbol in last 7 days
        ticks = db.query(Tick).filter(
            Tick.symbol == symbol,
            Tick.timestamp >= week_ago
        ).all()

        if not ticks:
            print("  ⚠️  No ticks in last 7 days")
            continue

        # Analyze by hour and day of week
        hourly_counts = defaultdict(int)
        dow_counts = defaultdict(int)  # 0=Monday, 6=Sunday

        for tick in ticks:
            tick_berlin = tick.timestamp.astimezone(berlin_tz)
            hour = tick_berlin.hour
            dow = tick_berlin.weekday()

            hourly_counts[hour] += 1
            dow_counts[dow] += 1

        # Get first and last tick
        first_tick_utc = min(t.timestamp for t in ticks)
        last_tick_utc = max(t.timestamp for t in ticks)

        # Ensure timezone aware
        if first_tick_utc.tzinfo is None:
            first_tick_utc = pytz.UTC.localize(first_tick_utc)
        if last_tick_utc.tzinfo is None:
            last_tick_utc = pytz.UTC.localize(last_tick_utc)

        first_tick = first_tick_utc.astimezone(berlin_tz)
        last_tick = last_tick_utc.astimezone(berlin_tz)

        age_seconds = (now_utc - last_tick_utc).total_seconds()
        age_hours = age_seconds / 3600

        total_ticks = len(ticks)

        print(f"  Total ticks: {total_ticks:,}")
        print(f"  First tick:  {first_tick.strftime('%Y-%m-%d %H:%M:%S')} Berlin")
        print(f"  Last tick:   {last_tick.strftime('%Y-%m-%d %H:%M:%S')} Berlin")
        print(f"  Age:         {age_hours:.1f} hours")

        # Determine active hours (hours with >0.5% of total ticks)
        threshold = total_ticks * 0.005
        active_hours = sorted([h for h, count in hourly_counts.items() if count > threshold])

        if active_hours:
            print(f"\n  Trading Hours (Berlin): {min(active_hours):02d}:00 - {max(active_hours):02d}:59")

            # Show hourly distribution
            print(f"\n  {'Hour':<6} {'Ticks':>8}  {'Activity':<30} {'%':>6}")
            print(f"  {'-' * 56}")

            max_count = max(hourly_counts.values())
            for hour in range(24):
                count = hourly_counts.get(hour, 0)
                if count > 0:
                    pct = (count / total_ticks) * 100
                    bar_len = int((count / max_count) * 30)
                    bar = "█" * bar_len
                    print(f"  {hour:02d}:00  {count:8,}  {bar:<30} {pct:5.1f}%")

        # Day of week analysis
        print(f"\n  Day of Week Distribution:")
        days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        dow_mapping = {0: 'Mon', 1: 'Tue', 2: 'Wed', 3: 'Thu', 4: 'Fri', 5: 'Sat', 6: 'Sun'}

        max_dow_count = max(dow_counts.values()) if dow_counts else 1
        for dow in range(7):
            count = dow_counts.get(dow, 0)
            pct = (count / total_ticks * 100) if total_ticks > 0 else 0
            bar_len = int((count / max_dow_count) * 30) if count > 0 else 0
            bar = "█" * bar_len
            print(f"  {dow_mapping[dow]}: {bar:<30} {count:7,} ({pct:5.1f}%)")

        # Determine trading schedule
        trading_schedules[symbol] = {
            'active_hours': active_hours,
            'active_days': sorted([d for d, count in dow_counts.items() if count > threshold]),
            'total_ticks': total_ticks,
            'last_tick_age_hours': age_hours
        }

    db.close()

    print("\n" + "=" * 100)
    print("RECOMMENDED WATCHDOG CONFIGURATION")
    print("=" * 100)

    for symbol, schedule in trading_schedules.items():
        print(f"\n{symbol}:")
        if schedule['active_hours']:
            print(f"  Active hours: {min(schedule['active_hours']):02d}:00 - {max(schedule['active_hours']):02d}:59 Berlin")

        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        active_day_names = [day_names[d] for d in schedule['active_days']]
        print(f"  Active days: {', '.join(active_day_names)}")
        print(f"  Current age: {schedule['last_tick_age_hours']:.1f} hours")

        # Recommendation
        if schedule['last_tick_age_hours'] > 6:
            # Check if it's outside trading hours
            now_berlin = datetime.now(berlin_tz)
            current_hour = now_berlin.hour
            current_dow = now_berlin.weekday()

            if current_hour in schedule['active_hours'] and current_dow in schedule['active_days']:
                print(f"  ⚠️  ALERT: Market should be open but no recent ticks!")
            else:
                print(f"  ✅ OK: Market is closed (outside trading hours)")
        else:
            print(f"  ✅ OK: Recent ticks received")

    print("\n" + "=" * 100)
    return trading_schedules

if __name__ == "__main__":
    analyze_trading_hours()
