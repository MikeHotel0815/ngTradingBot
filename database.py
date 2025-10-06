"""
Database connection and session management
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base
import os
import logging

logger = logging.getLogger(__name__)

# Database URL from environment (required - no default for security)
DATABASE_URL = os.getenv('DATABASE_URL')
if not DATABASE_URL:
    raise ValueError("DATABASE_URL environment variable is required")

# Create engine
engine = create_engine(
    DATABASE_URL,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verify connections before using
    echo=False  # Set to True for SQL debugging
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Thread-safe scoped session
ScopedSession = scoped_session(SessionLocal)


def init_db():
    """Initialize database - create all tables"""
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database tables created successfully")
    except Exception as e:
        logger.error(f"Error creating database tables: {e}")
        raise


def get_db():
    """Get database session - for use in requests"""
    db = ScopedSession()
    try:
        yield db
    finally:
        db.close()


def aggregate_spread_statistics(session, cutoff_time):
    """
    Aggregate spread statistics from ticks before deletion.

    Calculates hourly spread stats (avg, min, max) grouped by symbol, hour, and day of week.
    Stores in spread_statistics table for long-term analysis.

    Args:
        session: Database session
        cutoff_time: Only aggregate ticks older than this time

    Returns:
        Number of aggregated records
    """
    from models import Tick
    from sqlalchemy import func
    from datetime import datetime

    try:
        # Query ticks to be deleted, grouped by symbol, hour, and day of week
        stats_query = session.query(
            Tick.symbol,
            func.extract('hour', Tick.timestamp).label('hour_utc'),
            func.extract('dow', Tick.timestamp).label('day_of_week'),
            func.avg(Tick.spread).label('avg_spread'),
            func.min(Tick.spread).label('min_spread'),
            func.max(Tick.spread).label('max_spread'),
            func.count(Tick.id).label('sample_count'),
            func.min(Tick.timestamp).label('first_recorded'),
            func.max(Tick.timestamp).label('last_updated')
        ).filter(
            Tick.timestamp < cutoff_time,
            Tick.spread.isnot(None)
        ).group_by(
            Tick.symbol,
            func.extract('hour', Tick.timestamp),
            func.extract('dow', Tick.timestamp)
        ).all()

        aggregated_count = 0

        for stat in stats_query:
            # Insert or update spread_statistics
            from sqlalchemy import text

            upsert_sql = text("""
                INSERT INTO spread_statistics
                    (symbol, hour_utc, day_of_week, avg_spread, min_spread, max_spread,
                     sample_count, first_recorded, last_updated)
                VALUES
                    (:symbol, :hour_utc, :day_of_week, :avg_spread, :min_spread, :max_spread,
                     :sample_count, :first_recorded, :last_updated)
                ON CONFLICT (symbol, hour_utc, day_of_week)
                DO UPDATE SET
                    avg_spread = (spread_statistics.avg_spread * spread_statistics.sample_count +
                                 :avg_spread * :sample_count) /
                                (spread_statistics.sample_count + :sample_count),
                    min_spread = LEAST(spread_statistics.min_spread, :min_spread),
                    max_spread = GREATEST(spread_statistics.max_spread, :max_spread),
                    sample_count = spread_statistics.sample_count + :sample_count,
                    last_updated = :last_updated
            """)

            session.execute(upsert_sql, {
                'symbol': stat.symbol,
                'hour_utc': int(stat.hour_utc),
                'day_of_week': int(stat.day_of_week),
                'avg_spread': float(stat.avg_spread),
                'min_spread': float(stat.min_spread),
                'max_spread': float(stat.max_spread),
                'sample_count': stat.sample_count,
                'first_recorded': stat.first_recorded,
                'last_updated': stat.last_updated
            })
            aggregated_count += 1

        session.commit()

        if aggregated_count > 0:
            logger.info(f"Aggregated {aggregated_count} spread statistics records")

        return aggregated_count

    except Exception as e:
        logger.error(f"Error aggregating spread statistics: {e}", exc_info=True)
        session.rollback()
        return 0


def cleanup_old_ticks(session, minutes=1):
    """Delete ticks older than specified minutes (legacy function)"""
    from models import Tick
    from datetime import datetime, timedelta

    cutoff_time = datetime.utcnow() - timedelta(minutes=minutes)
    deleted = session.query(Tick).filter(Tick.timestamp < cutoff_time).delete()
    session.commit()
    return deleted


def cleanup_old_data(session, tick_days=7, pattern_days=30):
    """
    Cleanup old tick, OHLC, and pattern detection data based on retention policy

    OHLC retention is timeframe-specific for optimal trend analysis:
    - M1/M5: 2-3 days (fast decisions)
    - M15: 3 days (intraday)
    - H1: 7 days (daily trends)
    - H4: 14 days (weekly trends)
    - D1: 30 days (monthly trends)

    Args:
        session: Database session
        tick_days: Days to keep tick data (default: 7 days)
        pattern_days: Days to keep pattern detections (default: 30 days)

    Returns:
        dict with deleted counts
    """
    from models import Tick, OHLCData, PatternDetection
    from datetime import datetime, timedelta

    tick_cutoff = datetime.utcnow() - timedelta(days=tick_days)
    pattern_cutoff = datetime.utcnow() - timedelta(days=pattern_days)

    # Aggregate spread statistics BEFORE deleting ticks
    aggregated_spreads = aggregate_spread_statistics(session, tick_cutoff)

    # Delete old ticks
    deleted_ticks = session.query(Tick).filter(Tick.timestamp < tick_cutoff).delete()

    # Delete old OHLC data - timeframe-specific retention
    ohlc_retention = {
        'M1': 2,   # 2 days for M1
        'M5': 2,   # 2 days for M5
        'M15': 3,  # 3 days for M15
        'H1': 7,   # 7 days for H1
        'H4': 14,  # 14 days for H4
        'D1': 30   # 30 days for D1
    }

    deleted_ohlc = 0
    for timeframe, days in ohlc_retention.items():
        cutoff = datetime.utcnow() - timedelta(days=days)
        count = session.query(OHLCData).filter(
            OHLCData.timeframe == timeframe,
            OHLCData.timestamp < cutoff
        ).delete(synchronize_session=False)
        deleted_ohlc += count

    # Delete old pattern detections
    deleted_patterns = session.query(PatternDetection).filter(PatternDetection.detected_at < pattern_cutoff).delete()

    session.commit()

    logger.info(f"Cleanup completed: {deleted_ticks} ticks (>{tick_days}d), {deleted_ohlc} OHLC (timeframe-specific), {deleted_patterns} patterns (>{pattern_days}d), {aggregated_spreads} spread stats aggregated")

    return {
        'deleted_ticks': deleted_ticks,
        'deleted_ohlc': deleted_ohlc,
        'deleted_patterns': deleted_patterns,
        'aggregated_spreads': aggregated_spreads,
        'tick_retention_days': tick_days,
        'ohlc_retention': ohlc_retention,
        'pattern_retention_days': pattern_days
    }
