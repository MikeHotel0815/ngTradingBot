"""
Daily Backtest Scheduler for Auto-Optimization System
Runs automated backtests daily and triggers performance analysis
"""

import logging
from datetime import datetime, timedelta, time as dt_time
from typing import List, Dict
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import threading

from models import (
    Account, BacktestRun, DailyBacktestSchedule,
    AutoOptimizationConfig, SymbolPerformanceTracking
)
from performance_analyzer import PerformanceAnalyzer
from database import ScopedSession

logger = logging.getLogger(__name__)


class DailyBacktestScheduler:
    """Manages daily automated backtests for all accounts"""

    def __init__(self):
        self.scheduler = BackgroundScheduler()
        self.lock = threading.Lock()
        self._running = False

    def start(self):
        """Start the scheduler"""
        if self._running:
            logger.warning("Scheduler already running")
            return

        # Schedule daily backtest at 00:00 UTC
        self.scheduler.add_job(
            func=self.run_daily_backtests,
            trigger=CronTrigger(hour=0, minute=0),
            id='daily_backtest',
            name='Daily Backtest Runner',
            replace_existing=True
        )

        # Also add manual trigger capability
        self.scheduler.start()
        self._running = True
        logger.info("✅ Daily Backtest Scheduler started (runs at 00:00 UTC)")

    def stop(self):
        """Stop the scheduler"""
        if self._running:
            self.scheduler.shutdown(wait=False)
            self._running = False
            logger.info("🛑 Daily Backtest Scheduler stopped")

    def run_daily_backtests(self):
        """Execute daily backtests for all enabled accounts"""
        with self.lock:
            logger.info("🚀 Starting daily backtest run...")
            db = ScopedSession()

            try:
                # Get all accounts with auto-optimization enabled
                configs = db.query(AutoOptimizationConfig).filter(
                    AutoOptimizationConfig.enabled == True
                ).all()

                for config in configs:
                    try:
                        self._run_backtest_for_account(db, config)
                    except Exception as e:
                        logger.error(f"Error running backtest for account {config.account_id}: {e}", exc_info=True)

                logger.info("✅ Daily backtest run completed")

            except Exception as e:
                logger.error(f"Error in daily backtest run: {e}", exc_info=True)
            finally:
                db.close()

    def _run_backtest_for_account(self, db: Session, config: AutoOptimizationConfig):
        """Run backtests for a single account"""
        account_id = config.account_id
        logger.info(f"📊 Running backtest for account {account_id}")

        # Get or create schedule record
        today = datetime.utcnow().date()
        schedule = db.query(DailyBacktestSchedule).filter_by(
            account_id=account_id,
            scheduled_date=today
        ).first()

        if not schedule:
            schedule = DailyBacktestSchedule(
                account_id=account_id,
                scheduled_date=today,
                status='running',
                started_at=datetime.utcnow()
            )
            db.add(schedule)
        else:
            # Update existing schedule
            schedule.status = 'running'
            schedule.started_at = datetime.utcnow()
            schedule.error_message = None

        db.commit()

        try:
            # Get symbols to test (from subscribed symbols or default list)
            symbols = self._get_symbols_for_account(db, account_id)

            # Get backtest parameters from config
            window_days = config.backtest_window_days
            min_confidence = float(config.backtest_min_confidence)

            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=window_days)

            logger.info(
                f"Testing {len(symbols)} symbols over {window_days} days "
                f"(from {start_date.date()} to {end_date.date()})"
            )

            # Run backtest for each symbol individually
            backtest_runs_created = 0
            symbols_enabled = 0
            symbols_disabled = 0
            symbols_watch = 0

            analyzer = PerformanceAnalyzer(db, account_id)

            for symbol in symbols:
                try:
                    logger.info(f"🔄 Running backtest for {symbol}...")

                    # Create and run backtest
                    backtest_run = self._create_backtest_run(
                        db=db,
                        account_id=account_id,
                        symbol=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        min_confidence=min_confidence,
                        window_days=window_days
                    )

                    if backtest_run:
                        backtest_runs_created += 1

                        # Analyze performance
                        perf = analyzer.analyze_symbol_performance(
                            symbol=symbol,
                            backtest_run=backtest_run,
                            evaluation_date=end_date
                        )

                        # Count by status
                        if perf.status == 'active':
                            symbols_enabled += 1
                        elif perf.status == 'disabled':
                            symbols_disabled += 1
                        elif perf.status == 'watch':
                            symbols_watch += 1

                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}", exc_info=True)

            # Update schedule record
            schedule.status = 'completed'
            schedule.completed_at = datetime.utcnow()
            schedule.backtest_runs_created = backtest_runs_created
            schedule.total_symbols_evaluated = len(symbols)
            schedule.symbols_enabled = symbols_enabled
            schedule.symbols_disabled = symbols_disabled
            schedule.symbols_watch = symbols_watch
            db.commit()

            logger.info(
                f"✅ Backtest completed for account {account_id}: "
                f"{symbols_enabled} active, {symbols_disabled} disabled, {symbols_watch} watch"
            )

        except Exception as e:
            schedule.status = 'failed'
            schedule.error_message = str(e)
            schedule.completed_at = datetime.utcnow()
            db.commit()
            raise

    def _get_symbols_for_account(self, db: Session, account_id: int) -> List[str]:
        """Get list of symbols to backtest for account"""
        # For now, use a default symbol list
        # In production, this could come from subscribed_symbols table
        default_symbols = ['BTCUSD', 'EURUSD', 'GBPUSD', 'USDJPY', 'XAUUSD']

        # You could also query from subscribed_symbols:
        # from models import SubscribedSymbol
        # results = db.query(SubscribedSymbol.symbol).filter(
        #     SubscribedSymbol.account_id == account_id,
        #     SubscribedSymbol.active == True
        # ).distinct().all()
        # return [r[0] for r in results] if results else default_symbols

        return default_symbols

    def _create_backtest_run(
        self,
        db: Session,
        account_id: int,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
        min_confidence: float,
        window_days: int
    ) -> BacktestRun:
        """
        Create a backtest run for a single symbol

        This is a placeholder - in production, this would:
        1. Create BacktestRun record
        2. Trigger backtesting_engine.py to execute
        3. Wait for completion
        4. Return completed BacktestRun

        For now, we'll just create a record that links to existing backtest data
        """
        from backtesting_engine import BacktestingEngine

        # Create backtest run record
        backtest_run = BacktestRun(
            account_id=account_id,
            name=f"Auto-Backtest {symbol} {window_days}d",
            description=f"Automated daily backtest for {symbol}",
            symbols=symbol,  # Single symbol
            timeframes='H1,H4',  # Use both H1 and H4
            start_date=start_date,
            end_date=end_date,
            initial_balance=1000.00,  # Default balance
            min_confidence=min_confidence,
            position_size_percent=0.01,  # 1% position size
            max_positions=5,
            status='pending'
        )
        db.add(backtest_run)
        db.commit()

        logger.info(f"Created backtest run #{backtest_run.id} for {symbol}")

        # Execute backtest
        backtest_id = backtest_run.id
        try:
            engine = BacktestingEngine(backtest_id)
            engine.run()

            # Reload the backtest_run from DB to get updated results
            backtest_run = db.query(BacktestRun).filter_by(id=backtest_id).first()

            if not backtest_run:
                logger.error(f"Backtest #{backtest_id} not found after execution")
                return None

            logger.info(
                f"Backtest #{backtest_run.id} completed: "
                f"{backtest_run.total_trades} trades, "
                f"${backtest_run.total_profit} profit"
            )

            return backtest_run

        except Exception as e:
            logger.error(f"Error executing backtest for {symbol}: {e}", exc_info=True)
            # Reload and update status
            failed_run = db.query(BacktestRun).filter_by(id=backtest_id).first()
            if failed_run:
                failed_run.status = 'failed'
                failed_run.error_message = str(e)
                db.commit()
            return None

    def trigger_manual_run(self):
        """Manually trigger a backtest run (for testing)"""
        logger.info("🔧 Manual backtest trigger requested")
        self.run_daily_backtests()


# Global scheduler instance
_scheduler_instance = None


def get_scheduler() -> DailyBacktestScheduler:
    """Get or create global scheduler instance"""
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = DailyBacktestScheduler()
    return _scheduler_instance


def start_scheduler():
    """Start the global scheduler"""
    scheduler = get_scheduler()
    scheduler.start()


def stop_scheduler():
    """Stop the global scheduler"""
    scheduler = get_scheduler()
    scheduler.stop()


def trigger_manual_backtest():
    """Manually trigger a backtest run"""
    scheduler = get_scheduler()
    scheduler.trigger_manual_run()
