#!/usr/bin/env python3
"""
Parameter Optimization Scheduler
Schedules weekly and monthly optimization jobs
"""

import os
import sys
import logging
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from weekly_performance_analyzer import WeeklyPerformanceAnalyzer
from monthly_parameter_optimizer import MonthlyParameterOptimizer
from top_performers_analyzer import TopPerformersAnalyzer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ParameterOptimizationScheduler:
    """Schedules parameter optimization tasks"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.setup_jobs()

    def setup_jobs(self):
        """Setup scheduled jobs"""

        # Weekly Performance Report - Every Friday at 22:00 UTC
        self.scheduler.add_job(
            self.run_weekly_analysis,
            trigger=CronTrigger(
                day_of_week='fri',
                hour=22,
                minute=0,
                timezone='UTC'
            ),
            id='weekly_performance_report',
            name='Weekly Performance Analysis',
            replace_existing=True
        )

        # Monthly Parameter Optimization - Last Friday of month at 23:00 UTC
        self.scheduler.add_job(
            self.run_monthly_optimization,
            trigger=CronTrigger(
                day='last fri',
                hour=23,
                minute=0,
                timezone='UTC'
            ),
            id='monthly_parameter_optimization',
            name='Monthly Parameter Optimization',
            replace_existing=True
        )

        # Top Performers Analysis - Every Friday at 22:30 UTC (after weekly report)
        self.scheduler.add_job(
            self.run_top_performers_analysis,
            trigger=CronTrigger(
                day_of_week='fri',
                hour=22,
                minute=30,
                timezone='UTC'
            ),
            id='top_performers_analysis',
            name='Top Performers Analysis',
            replace_existing=True
        )

        logger.info("✅ Scheduled jobs configured:")
        logger.info("   - Weekly Performance Report: Every Friday 22:00 UTC")
        logger.info("   - Top Performers Analysis: Every Friday 22:30 UTC")
        logger.info("   - Monthly Optimization: Last Friday of month 23:00 UTC")

    def run_weekly_analysis(self):
        """Run weekly performance analysis"""
        logger.info("🔄 Starting weekly performance analysis...")

        try:
            analyzer = WeeklyPerformanceAnalyzer()
            report_id = analyzer.generate_weekly_report()

            if report_id:
                logger.info(f"✅ Weekly report generated (ID: {report_id})")
            else:
                logger.warning("⚠️  Weekly report not generated")

        except Exception as e:
            logger.error(f"❌ Error running weekly analysis: {e}", exc_info=True)

    def run_monthly_optimization(self):
        """Run monthly parameter optimization"""
        logger.info("🔄 Starting monthly parameter optimization...")

        try:
            optimizer = MonthlyParameterOptimizer()
            results = optimizer.run_monthly_optimization()

            successful = len([r for r in results.values() if r is not None])
            logger.info(f"✅ Monthly optimization complete ({successful} symbols)")

        except Exception as e:
            logger.error(f"❌ Error running monthly optimization: {e}", exc_info=True)

    def run_top_performers_analysis(self):
        """Run top performers analysis"""
        logger.info("🔄 Starting top performers analysis...")

        try:
            analyzer = TopPerformersAnalyzer(days_back=14)
            success = analyzer.generate_report()

            if success:
                logger.info("✅ Top performers analysis complete")
            else:
                logger.warning("⚠️  Top performers analysis completed with no data")

        except Exception as e:
            logger.error(f"❌ Error running top performers analysis: {e}", exc_info=True)

    def start(self):
        """Start the scheduler"""
        self.scheduler.start()
        logger.info("✅ Parameter Optimization Scheduler started")

        # Print next run times
        jobs = self.scheduler.get_jobs()
        for job in jobs:
            logger.info(f"   - {job.name}: Next run at {job.next_run_time}")

    def stop(self):
        """Stop the scheduler"""
        self.scheduler.shutdown()
        logger.info("✅ Parameter Optimization Scheduler stopped")


def main():
    """Main entry point - run scheduler in foreground"""

    scheduler = ParameterOptimizationScheduler()
    scheduler.start()

    try:
        # Keep the process running
        import time
        logger.info("Scheduler running... Press Ctrl+C to exit")
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down...")
        scheduler.stop()


if __name__ == '__main__':
    main()
