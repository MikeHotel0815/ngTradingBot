#!/usr/bin/env python3
"""
Dashboard Background Worker
Automatic report generation on schedule
"""

import sys
import os
import time
import logging
import signal
from datetime import datetime
from typing import Optional

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from monitoring.dashboard_telegram import TelegramDashboardReporter
from monitoring.chart_generator import ChartGenerator
from monitoring.dashboard_config import get_config

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


class DashboardWorker:
    """Background worker for automatic dashboard reports"""

    def __init__(self, account_id: Optional[int] = None):
        self.config = get_config()
        self.account_id = account_id or self.config.DEFAULT_ACCOUNT_ID

        self.telegram_reporter = TelegramDashboardReporter(account_id=self.account_id)
        self.scheduler = BlockingScheduler()

        self.running = True

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
        self.scheduler.shutdown(wait=False)

    # =========================================================================
    # Scheduled Jobs
    # =========================================================================

    def send_lightweight_report_job(self):
        """Job: Send lightweight Telegram report"""
        try:
            logger.info("Running lightweight report job...")
            success = self.telegram_reporter.send_lightweight_report()

            if success:
                logger.info("✅ Lightweight report sent successfully")
            else:
                logger.error("❌ Lightweight report failed")

        except Exception as e:
            logger.error(f"Error in lightweight report job: {e}", exc_info=True)

    def send_full_report_job(self):
        """Job: Send full Telegram report"""
        try:
            logger.info("Running full report job...")
            success = self.telegram_reporter.send_full_report()

            if success:
                logger.info("✅ Full report sent successfully")
            else:
                logger.error("❌ Full report failed")

        except Exception as e:
            logger.error(f"Error in full report job: {e}", exc_info=True)

    def generate_charts_job(self):
        """Job: Generate analytics charts"""
        try:
            logger.info("Running chart generation job...")

            with ChartGenerator(account_id=self.account_id) as generator:
                charts = generator.generate_all_charts(days_back=7, output_dir='/app/data/charts')

            logger.info(f"✅ Generated {len(charts)} charts successfully")

        except Exception as e:
            logger.error(f"Error in chart generation job: {e}", exc_info=True)

    def health_check_job(self):
        """Job: Health check and alerts"""
        try:
            logger.info("Running health check job...")

            # Check critical metrics and send alerts if needed
            from monitoring.dashboard_core import DashboardCore

            with DashboardCore(account_id=self.account_id) as dashboard:
                # Check risk management status
                risk = dashboard.get_risk_management_status()
                dd = risk.get('daily_drawdown', {})
                dd_status = dd.get('status', 'UNKNOWN')

                if dd_status in ['WARNING', 'CRITICAL', 'EMERGENCY']:
                    message = f"Daily drawdown: €{dd.get('current', 0):+.2f}"
                    level = 'WARNING' if dd_status == 'WARNING' else 'CRITICAL'
                    self.telegram_reporter.send_event_alert(
                        'DRAWDOWN_' + dd_status,
                        message,
                        level=level
                    )
                    logger.warning(f"⚠️ Drawdown alert sent: {dd_status}")

                # Check position limits
                pos = risk.get('position_limits', {})
                usage_pct = pos.get('usage_pct', 0)

                if usage_pct >= 90:
                    message = f"Position usage: {usage_pct:.0f}% ({pos.get('current_open', 0)}/{pos.get('max_total', 0)})"
                    self.telegram_reporter.send_event_alert(
                        'MAX_POSITIONS_WARNING',
                        message,
                        level='WARNING'
                    )
                    logger.warning("⚠️ Max positions alert sent")

                # Check MT5 connection
                health = dashboard.get_system_health()
                mt5 = health.get('mt5_connection', {})

                if not mt5.get('connected'):
                    hb = mt5.get('last_heartbeat_seconds_ago')
                    message = f"MT5 disconnected. Last heartbeat: {hb:.0f}s ago" if hb else "MT5 disconnected"
                    self.telegram_reporter.send_event_alert(
                        'MT5_CONNECTION_LOST',
                        message,
                        level='CRITICAL'
                    )
                    logger.error("🔴 MT5 disconnection alert sent")

            logger.info("✅ Health check completed")

        except Exception as e:
            logger.error(f"Error in health check job: {e}", exc_info=True)

    # =========================================================================
    # Worker Setup
    # =========================================================================

    def setup_jobs(self):
        """Setup all scheduled jobs"""

        if self.config.ENABLE_TELEGRAM_REPORTS:
            # Lightweight report every 4 hours
            self.scheduler.add_job(
                self.send_lightweight_report_job,
                trigger=IntervalTrigger(seconds=self.config.TELEGRAM_LIGHTWEIGHT_INTERVAL),
                id='lightweight_report',
                name='Lightweight Telegram Report',
                replace_existing=True,
                max_instances=1
            )
            logger.info(f"Scheduled lightweight report: every {self.config.TELEGRAM_LIGHTWEIGHT_INTERVAL}s (4h)")

            # Full report daily at 22:00 UTC
            self.scheduler.add_job(
                self.send_full_report_job,
                trigger=CronTrigger(hour=22, minute=0, timezone='UTC'),
                id='full_report',
                name='Full Telegram Report (Daily)',
                replace_existing=True,
                max_instances=1
            )
            logger.info("Scheduled full report: daily at 22:00 UTC")

        if self.config.ENABLE_CHART_GENERATION:
            # Generate charts every hour
            self.scheduler.add_job(
                self.generate_charts_job,
                trigger=IntervalTrigger(seconds=self.config.CHART_GENERATION_INTERVAL),
                id='chart_generation',
                name='Chart Generation',
                replace_existing=True,
                max_instances=1
            )
            logger.info(f"Scheduled chart generation: every {self.config.CHART_GENERATION_INTERVAL}s (1h)")

        # Health check every 5 minutes
        self.scheduler.add_job(
            self.health_check_job,
            trigger=IntervalTrigger(minutes=5),
            id='health_check',
            name='Health Check & Alerts',
            replace_existing=True,
            max_instances=1
        )
        logger.info("Scheduled health check: every 5 minutes")

    def run(self):
        """Start the dashboard worker"""
        logger.info("=" * 60)
        logger.info("ngTradingBot Dashboard Worker Starting")
        logger.info("=" * 60)
        logger.info(f"Account ID: {self.account_id}")
        logger.info(f"Telegram enabled: {self.config.ENABLE_TELEGRAM_REPORTS}")
        logger.info(f"Charts enabled: {self.config.ENABLE_CHART_GENERATION}")
        logger.info("=" * 60)

        # Check Telegram configuration
        if self.config.ENABLE_TELEGRAM_REPORTS and not self.telegram_reporter.telegram.enabled:
            logger.warning("⚠️ Telegram reports enabled but not configured properly!")
            logger.warning("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables")

        # Setup jobs
        self.setup_jobs()

        # Print job summary
        logger.info("\nScheduled Jobs:")
        for job in self.scheduler.get_jobs():
            logger.info(f"  - {job.name} (ID: {job.id})")
            logger.info(f"    Next run: {job.next_run_time}")

        logger.info("\n" + "=" * 60)
        logger.info("Worker started. Press Ctrl+C to stop.")
        logger.info("=" * 60 + "\n")

        try:
            # Start scheduler
            self.scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("Worker stopped by user")
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
        finally:
            logger.info("Shutting down dashboard worker...")


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description='ngTradingBot Dashboard Background Worker')
    parser.add_argument('--account-id', type=int, help='Account ID (defaults to config)')
    parser.add_argument('--test-immediate', action='store_true', help='Run all jobs immediately once (for testing)')

    args = parser.parse_args()

    worker = DashboardWorker(account_id=args.account_id)

    if args.test_immediate:
        logger.info("TEST MODE: Running all jobs immediately once...")

        logger.info("\n1. Running lightweight report...")
        worker.send_lightweight_report_job()

        logger.info("\n2. Running chart generation...")
        worker.generate_charts_job()

        logger.info("\n3. Running health check...")
        worker.health_check_job()

        logger.info("\n✅ All test jobs completed")
        sys.exit(0)

    # Normal mode: run as background worker
    worker.run()


if __name__ == '__main__':
    main()
