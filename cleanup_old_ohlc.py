#!/usr/bin/env python3
"""
Cleanup old OHLC data that is older than 1 year
This prevents the database from growing indefinitely
"""

import logging
from datetime import datetime, timedelta
from database import ScopedSession
from models import OHLCData

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def cleanup_old_ohlc_data(days_to_keep: int = 365):
    """
    Delete OHLC data older than specified days
    M1 data is cleaned more aggressively (7 days) since it's only used for tick aggregation

    Args:
        days_to_keep: Number of days of data to keep for higher timeframes (default: 365 = 1 year)
    """
    db = ScopedSession()

    try:
        # STEP 1: M1 cleanup - Keep only 7 days (used for tick aggregation only)
        m1_cutoff = datetime.utcnow() - timedelta(days=7)
        m1_count = db.query(OHLCData).filter(
            OHLCData.timeframe == 'M1',
            OHLCData.timestamp < m1_cutoff
        ).count()

        if m1_count > 0:
            logger.info(f"🗑️  M1 cleanup: deleting {m1_count:,} bars older than 7 days...")
            deleted = 0
            batch_size = 10000

            while True:
                batch_deleted = db.query(OHLCData).filter(
                    OHLCData.timeframe == 'M1',
                    OHLCData.timestamp < m1_cutoff
                ).limit(batch_size).delete(synchronize_session=False)

                if batch_deleted == 0:
                    break

                db.commit()
                deleted += batch_deleted
                if deleted % 50000 == 0:  # Log every 50k rows
                    logger.info(f"  M1: Deleted {deleted:,} / {m1_count:,}...")

            logger.info(f"✅ M1 cleanup complete: deleted {deleted:,} M1 bars (~{deleted * 0.2:.1f} KB saved)")

        # STEP 2: Higher timeframes cleanup - Keep 1 year
        cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

        logger.info(f"🗑️  Starting cleanup for M5/M15/H1/H4/D1: deleting data older than {cutoff_date.strftime('%Y-%m-%d')}")

        # Count how many rows will be deleted (excluding M1)
        count = db.query(OHLCData).filter(
            OHLCData.timeframe != 'M1',
            OHLCData.timestamp < cutoff_date
        ).count()

        if count == 0:
            logger.info("✅ No old OHLC data to delete for higher timeframes")
            return

        logger.info(f"Found {count:,} old OHLC bars to delete (M5/M15/H1/H4/D1)")

        # Delete in batches to avoid locking the table for too long
        batch_size = 10000
        total_deleted = 0

        while True:
            # Delete one batch (excluding M1)
            deleted = db.query(OHLCData).filter(
                OHLCData.timeframe != 'M1',
                OHLCData.timestamp < cutoff_date
            ).limit(batch_size).delete(synchronize_session=False)

            if deleted == 0:
                break

            db.commit()
            total_deleted += deleted
            logger.info(f"  Deleted {total_deleted:,} / {count:,} rows...")

        logger.info(f"✅ Cleanup complete: deleted {total_deleted:,} old OHLC bars")
        logger.info(f"💾 Database space saved: ~{total_deleted * 0.2:.1f} KB")

    except Exception as e:
        logger.error(f"❌ Error during OHLC cleanup: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    # Run cleanup: keep 1 year of data, delete older
    cleanup_old_ohlc_data(days_to_keep=365)
