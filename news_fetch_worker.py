"""
News Fetch Worker

Fetches economic calendar events every 4 hours
"""

import logging
import time
from news_filter import get_news_filter

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def fetch_loop():
    """Main fetch loop - runs every 4 hours"""
    logger.info("📰 News Fetch Worker started")

    while True:
        try:
            # Fetch for account 1 (stores events globally)
            news_filter = get_news_filter(account_id=1)
            count = news_filter.fetch_and_store_events()

            if count > 0:
                logger.info(f"✅ Fetched {count} new economic events")
            else:
                logger.debug("No new events fetched")

        except Exception as e:
            logger.error(f"Error in news fetch loop: {e}")

        # Sleep for 4 hours
        time.sleep(14400)


if __name__ == "__main__":
    fetch_loop()
