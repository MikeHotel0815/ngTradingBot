"""
AI Decision Log Cleanup Worker

Automatically cleans up AI decision logs older than 24 hours.
Runs every hour to maintain database efficiency.
"""

import logging
import time
from datetime import datetime
from ai_decision_log import get_decision_logger

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def cleanup_loop():
    """Main cleanup loop - runs every hour"""
    logger.info("🧹 AI Decision Log Cleanup Worker started")

    while True:
        try:
            decision_logger = get_decision_logger()
            deleted_count = decision_logger.cleanup_old_decisions(hours=24)

            if deleted_count > 0:
                logger.info(f"✅ Cleanup complete: {deleted_count} old decisions deleted")
            else:
                logger.debug("No old decisions to clean up")

        except Exception as e:
            logger.error(f"Error in cleanup loop: {e}")

        # Sleep for 1 hour
        time.sleep(3600)


if __name__ == "__main__":
    cleanup_loop()
