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


def cleanup_old_signals(
    minutes_to_keep_active: int = 10,
    minutes_to_keep_expired: int = 2
):
    """
    Delete trading signals older than specified minutes

    Uses different retention times for active vs. expired signals:
    - Active signals: Keep longer for potential trading
    - Expired/invalid signals: Delete faster to reduce noise

    Args:
        minutes_to_keep_active: Minutes to keep active signals (default: 10)
        minutes_to_keep_expired: Minutes to keep expired signals (default: 2)
    """
    db = ScopedSession()

    try:
        cutoff_active = datetime.utcnow() - timedelta(minutes=minutes_to_keep_active)
        cutoff_expired = datetime.utcnow() - timedelta(minutes=minutes_to_keep_expired)

        # Count how many signals will be deleted
        count_active = db.query(TradingSignal).filter(
            TradingSignal.created_at < cutoff_active,
            TradingSignal.status == 'active'
        ).count()

        count_expired = db.query(TradingSignal).filter(
            TradingSignal.created_at < cutoff_expired,
            TradingSignal.status == 'expired'
        ).count()

        total_count = count_active + count_expired

        if total_count == 0:
            logger.debug("✅ No old signals to delete")
            return 0

        logger.info(
            f"🗑️  Deleting signals: "
            f"{count_active:,} active (>{minutes_to_keep_active}m), "
            f"{count_expired:,} expired (>{minutes_to_keep_expired}m)"
        )

        # Delete old active signals
        deleted_active = db.query(TradingSignal).filter(
            TradingSignal.created_at < cutoff_active,
            TradingSignal.status == 'active'
        ).delete(synchronize_session=False)

        # Delete old expired signals (faster cleanup)
        deleted_expired = db.query(TradingSignal).filter(
            TradingSignal.created_at < cutoff_expired,
            TradingSignal.status == 'expired'
        ).delete(synchronize_session=False)

        total_deleted = deleted_active + deleted_expired
        db.commit()

        logger.info(
            f"✅ Deleted {total_deleted:,} trading signals "
            f"(active: {deleted_active:,}, expired: {deleted_expired:,})"
        )

        return total_deleted

    except Exception as e:
        logger.error(f"❌ Error during signal cleanup: {e}")
        db.rollback()
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    # Run cleanup with different retention times:
    # - Active signals: 10 minutes (for potential trading)
    # - Expired signals: 2 minutes (quick cleanup)
    cleanup_old_signals(minutes_to_keep_active=10, minutes_to_keep_expired=2)
