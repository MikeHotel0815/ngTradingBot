#!/usr/bin/env python3
"""
Cleanup old trading signals that are older than configured threshold
This prevents the database from growing indefinitely with stale signals
"""

import logging
from datetime import datetime, timedelta
from database import ScopedSession
from models import TradingSignal

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def cleanup_old_signals(minutes_to_keep: int = 10):
    """
    Delete trading signals older than specified minutes

    Args:
        minutes_to_keep: Number of minutes to keep signals (default: 10)
    """
    db = ScopedSession()

    try:
        cutoff_time = datetime.utcnow() - timedelta(minutes=minutes_to_keep)

        # Count how many signals will be deleted
        count = db.query(TradingSignal).filter(
            TradingSignal.created_at < cutoff_time
        ).count()

        if count == 0:
            logger.debug("✅ No old signals to delete")
            return 0

        logger.info(f"🗑️  Deleting {count:,} signals older than {minutes_to_keep} minutes...")

        # Delete old signals
        deleted = db.query(TradingSignal).filter(
            TradingSignal.created_at < cutoff_time
        ).delete(synchronize_session=False)

        db.commit()
        logger.info(f"✅ Deleted {deleted:,} old trading signals")

        return deleted

    except Exception as e:
        logger.error(f"❌ Error during signal cleanup: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    # Run cleanup: keep 10 minutes of signals, delete older
    cleanup_old_signals(minutes_to_keep=10)
