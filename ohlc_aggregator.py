"""
OHLC Aggregation Module
Converts tick data to OHLC candles for various timeframes
"""

from datetime import datetime, timedelta
from sqlalchemy import func
from models import Tick, OHLCData
import logging

logger = logging.getLogger(__name__)


def aggregate_ticks_to_m1(db, account_id, symbol, start_time, end_time):
    """
    Aggregate ticks to M1 (1-minute) OHLC candles

    NOTE: account_id parameter kept for backwards compatibility but not used
    Ticks are now global (no account_id column)

    Args:
        db: Database session
        account_id: Account ID (not used, ticks are global)
        symbol: Trading symbol
        start_time: Start timestamp
        end_time: End timestamp

    Returns:
        Number of M1 candles created
    """
    # Query ticks for the given time range (ticks are now global, no account_id)
    ticks = db.query(Tick).filter(
        Tick.symbol == symbol,
        Tick.timestamp >= start_time,
        Tick.timestamp < end_time
    ).order_by(Tick.timestamp).all()

    if not ticks:
        return 0

    # Group ticks by minute
    minute_groups = {}
    for tick in ticks:
        # Round timestamp to minute
        minute_key = tick.timestamp.replace(second=0, microsecond=0)

        if minute_key not in minute_groups:
            minute_groups[minute_key] = []

        # Use mid price (average of bid and ask)
        mid_price = (tick.bid + tick.ask) / 2
        minute_groups[minute_key].append({
            'price': mid_price,
            'volume': tick.volume,
            'timestamp': tick.timestamp
        })

    # Create M1 OHLC candles
    candles_created = 0
    for minute_time, tick_group in minute_groups.items():
        prices = [t['price'] for t in tick_group]
        volumes = [t['volume'] for t in tick_group]

        # Check if candle already exists (OHLC is now global too)
        existing = db.query(OHLCData).filter(
            OHLCData.symbol == symbol,
            OHLCData.timeframe == 'M1',
            OHLCData.timestamp == minute_time
        ).first()

        if not existing:
            ohlc = OHLCData(
                symbol=symbol,
                timeframe='M1',
                open=tick_group[0]['price'],  # First tick price
                high=max(prices),
                low=min(prices),
                close=tick_group[-1]['price'],  # Last tick price
                volume=sum(volumes),
                timestamp=minute_time
            )
            db.add(ohlc)
            candles_created += 1

    db.commit()
    logger.info(f"Created {candles_created} M1 candles for {symbol}")
    return candles_created


def aggregate_m1_to_higher_timeframes(db, account_id, symbol):
    """
    Aggregate M1 candles to higher timeframes: M5, M15, M30, H1, H4, D1

    NOTE: account_id kept for compatibility but not used (OHLC is global now)
    """
    timeframes = {
        'M5': 5,      # 5 minutes
        'M15': 15,    # 15 minutes
        'M30': 30,    # 30 minutes
        'H1': 60,     # 1 hour
        'H4': 240,    # 4 hours
        'D1': 1440,   # 1 day (24 hours)
        'W1': 10080   # 1 week (7 days * 24 hours * 60 minutes)
    }

    total_created = 0

    for tf_name, minutes in timeframes.items():
        # Get latest M1 candles (OHLC is now global)
        m1_candles = db.query(OHLCData).filter(
            OHLCData.symbol == symbol,
            OHLCData.timeframe == 'M1'
        ).order_by(OHLCData.timestamp.desc()).limit(minutes * 2).all()  # Get enough data

        if not m1_candles:
            continue

        # Group M1 candles by timeframe period
        m1_candles.reverse()  # Oldest first

        groups = {}
        for candle in m1_candles:
            # Calculate period start for this timeframe
            if tf_name == 'W1':
                # Week starts on Monday (weekday=0)
                days_since_monday = candle.timestamp.weekday()
                period_start = (candle.timestamp - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
            elif tf_name == 'D1':
                period_start = candle.timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            elif tf_name == 'H4':
                hour_group = (candle.timestamp.hour // 4) * 4
                period_start = candle.timestamp.replace(hour=hour_group, minute=0, second=0, microsecond=0)
            elif tf_name == 'H1':
                period_start = candle.timestamp.replace(minute=0, second=0, microsecond=0)
            else:  # M5, M15, M30
                minute_group = (candle.timestamp.minute // minutes) * minutes
                period_start = candle.timestamp.replace(minute=minute_group, second=0, microsecond=0)

            if period_start not in groups:
                groups[period_start] = []
            groups[period_start].append(candle)

        # Create higher timeframe candles
        for period_time, candle_group in groups.items():
            # Check if already exists (OHLC is global)
            existing = db.query(OHLCData).filter(
                OHLCData.symbol == symbol,
                OHLCData.timeframe == tf_name,
                OHLCData.timestamp == period_time
            ).first()

            # Require sufficient M1 candles to create a valid higher timeframe candle
            # For continuous data: need at least 80% of expected candles (to allow for minor gaps)
            # M5=4 (80% of 5), M15=12 (80% of 15), H1=48 (80% of 60), H4=192 (80% of 240), D1=1152 (80% of 1440)
            min_candles_required = max(1, int(minutes * 0.8))
            if not existing and len(candle_group) >= min_candles_required:
                ohlc = OHLCData(
                    symbol=symbol,
                    timeframe=tf_name,
                    open=candle_group[0].open,
                    high=max(c.high for c in candle_group),
                    low=min(c.low for c in candle_group),
                    close=candle_group[-1].close,
                    volume=sum(c.volume for c in candle_group),
                    timestamp=period_time
                )
                db.add(ohlc)
                total_created += 1

        db.commit()

    logger.info(f"Created {total_created} higher timeframe candles for {symbol}")
    return total_created


def cleanup_ticks_with_aggregation(db, account_id=None, minutes=1):
    """
    Aggregate old ticks to OHLC before deleting them

    NOTE: account_id kept for compatibility but not used (ticks are global now)
    """
    from datetime import datetime, timedelta

    # Get the latest tick timestamp from the database (ticks are global)
    latest_tick_time = db.query(func.max(Tick.timestamp)).scalar()

    if not latest_tick_time:
        return 0, 0  # No ticks to process

    # Calculate cutoff relative to latest tick (not server time)
    cutoff_time = latest_tick_time - timedelta(minutes=minutes)

    # Get symbols with old ticks (ticks are global, no account_id)
    symbols_with_ticks = db.query(Tick.symbol).filter(
        Tick.timestamp < cutoff_time
    ).distinct().all()

    total_aggregated = 0
    total_deleted = 0

    for (symbol,) in symbols_with_ticks:
        # Get time range of old ticks (no account_id filter)
        oldest_tick = db.query(func.min(Tick.timestamp)).filter(
            Tick.symbol == symbol,
            Tick.timestamp < cutoff_time
        ).scalar()

        if oldest_tick:
            # Aggregate to M1 (account_id passed but not used)
            candles = aggregate_ticks_to_m1(
                db, account_id, symbol,
                oldest_tick, cutoff_time
            )
            total_aggregated += candles

            # Aggregate to higher timeframes
            aggregate_m1_to_higher_timeframes(db, account_id, symbol)

    # Delete old ticks (global, no account_id)
    deleted = db.query(Tick).filter(
        Tick.timestamp < cutoff_time
    ).delete()

    db.commit()
    total_deleted = deleted

    logger.info(f"Aggregated {total_aggregated} M1 candles, deleted {total_deleted} old ticks")

    return total_aggregated, total_deleted
