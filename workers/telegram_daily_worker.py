#!/usr/bin/env python3
"""
Telegram Daily Report Worker

Sends daily trading report at 23:00 (after market close)
Integrated into unified_workers.py
"""

import os
import sys
import time
import logging
from datetime import datetime, time as dt_time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram_daily_report import TelegramDailyReporter

logger = logging.getLogger(__name__)


class TelegramDailyWorker:
    """Worker that sends daily report at 23:00"""

    def __init__(self, account_id: int = 3):
        self.account_id = account_id
        self.reporter = TelegramDailyReporter(account_id=account_id)
        self.last_report_date = None
        self.target_hour = 23  # 23:00 local time
        logger.info(f"📱 Telegram Daily Report Worker initialized (Account: {account_id}, Time: {self.target_hour}:00)")

    def should_send_report(self) -> bool:
        """Check if it's time to send the report (23:00)"""
        now = datetime.now()
        current_date = now.date()

        # Check if we're at the target hour
        if now.hour != self.target_hour:
            return False

        # Check if we've already sent today
        if self.last_report_date == current_date:
            return False

        return True

    def run_check(self):
        """Check if it's time to send daily report"""
        try:
            if self.should_send_report():
                logger.info("⏰ Time is 23:00 - Sending daily Telegram report...")

                success = self.reporter.send_daily_report()

                if success:
                    self.last_report_date = datetime.now().date()
                    logger.info("✅ Daily Telegram report sent successfully!")
                else:
                    logger.error("❌ Failed to send daily Telegram report")

        except Exception as e:
            logger.error(f"❌ Error in Telegram daily worker: {e}", exc_info=True)


def telegram_daily_scheduler():
    """Worker function for unified_workers.py"""
    worker = TelegramDailyWorker(account_id=int(os.getenv('ACCOUNT_ID', 3)))
    worker.run_check()


if __name__ == '__main__':
    # Test mode
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger.info("🧪 Testing Telegram Daily Worker...")
    worker = TelegramDailyWorker(account_id=3)

    # Force send report for testing
    logger.info("Forcing report send...")
    worker.reporter.send_daily_report()
