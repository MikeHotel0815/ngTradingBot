#!/usr/bin/env python3
"""
Unified Worker Manager
Runs all background workers in separate threads with centralized error handling

Consolidates:
- decision_cleanup_worker
- news_fetch_worker
- trade_timeout_worker
- strategy_validation_worker
- drawdown_protection_worker
- partial_close_worker

Benefits:
- Single container instead of 6 (saves ~250 MB RAM)
- Centralized logging and error handling
- Faster deployment
- Easier maintenance
"""

import os
import sys
import time
import logging
import threading
import signal
import json
from datetime import datetime
from typing import Dict, Callable

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global shutdown flag
shutdown_event = threading.Event()

# Redis connection for metrics export
redis_client = None

def get_redis_client():
    """Get or create Redis client for metrics"""
    global redis_client
    if redis_client is None:
        try:
            import redis
            redis_url = os.getenv('REDIS_URL', 'redis://redis:6379/0')
            redis_client = redis.from_url(redis_url, decode_responses=True)
            logger.info("✅ Redis client connected for metrics export")
        except Exception as e:
            logger.warning(f"⚠️  Redis metrics export disabled: {e}")
    return redis_client


class WorkerThread(threading.Thread):
    """
    Enhanced thread class with error recovery and health monitoring
    """
    def __init__(self, name: str, target: Callable, interval_seconds: int = 60):
        super().__init__(name=name, daemon=True)
        self.target_func = target
        self.interval_seconds = interval_seconds
        self.last_run = None
        self.last_success = None
        self.error_count = 0
        self.success_count = 0
        self.is_healthy = True
        self.started_at = datetime.utcnow()
        
    def get_metrics(self) -> Dict:
        """Get current worker metrics"""
        uptime_seconds = (datetime.utcnow() - self.started_at).total_seconds()
        
        return {
            'name': self.name,
            'interval_seconds': self.interval_seconds,
            'is_healthy': self.is_healthy,
            'is_alive': self.is_alive(),
            'success_count': self.success_count,
            'error_count': self.error_count,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'last_success': self.last_success.isoformat() if self.last_success else None,
            'started_at': self.started_at.isoformat(),
            'uptime_seconds': int(uptime_seconds),
            'uptime_hours': round(uptime_seconds / 3600, 1)
        }
    
    def export_metrics(self):
        """Export metrics to Redis"""
        try:
            redis = get_redis_client()
            if redis:
                key = f"worker:metrics:{self.name}"
                metrics = self.get_metrics()
                redis.setex(key, 300, json.dumps(metrics))  # Expire after 5 minutes
        except Exception as e:
            logger.debug(f"Failed to export metrics for {self.name}: {e}")
        
    def run(self):
        """Run worker in loop with error recovery"""
        logger.info(f"🚀 Starting worker: {self.name} (interval: {self.interval_seconds}s)")
        
        while not shutdown_event.is_set():
            try:
                # Run the worker function
                logger.debug(f"⚙️  {self.name}: Running iteration...")
                self.target_func()
                
                # Update status
                self.last_run = datetime.utcnow()
                self.last_success = datetime.utcnow()
                self.success_count += 1
                self.is_healthy = True
                self.error_count = 0  # Reset error count on success
                
                # Export metrics
                self.export_metrics()
                
                # Sleep for interval (check shutdown flag every second)
                for _ in range(self.interval_seconds):
                    if shutdown_event.is_set():
                        break
                    time.sleep(1)
                    
            except Exception as e:
                self.error_count += 1
                self.is_healthy = (self.error_count < 5)  # Unhealthy after 5 consecutive errors
                self.last_run = datetime.utcnow()
                
                logger.error(
                    f"❌ {self.name}: Error in iteration (consecutive errors: {self.error_count}): {e}",
                    exc_info=True
                )
                
                # Export metrics even on error
                self.export_metrics()
                
                # Exponential backoff on errors (max 5 minutes)
                backoff = min(60 * self.error_count, 300)
                logger.warning(f"⏸️  {self.name}: Backing off for {backoff}s due to errors")
                
                for _ in range(backoff):
                    if shutdown_event.is_set():
                        break
                    time.sleep(1)
        
        logger.info(f"🛑 Worker stopped: {self.name}")


def import_worker_functions():
    """
    Import all worker functions and create single-iteration wrappers
    Returns dict of {worker_name: function}
    """
    workers = {}
    
    try:
        # Decision Cleanup Worker - single iteration wrapper
        logger.info("📦 Importing decision_cleanup_worker...")
        from ai_decision_log import get_decision_logger
        
        def cleanup_iteration():
            decision_logger = get_decision_logger()
            deleted_count = decision_logger.cleanup_old_decisions(hours=24)
            if deleted_count > 0:
                logger.info(f"✅ Cleanup: {deleted_count} old decisions deleted")
        
        workers['decision_cleanup'] = cleanup_iteration
        
    except Exception as e:
        logger.error(f"Failed to import decision_cleanup_worker: {e}")
    
    try:
        # News Fetch Worker - single iteration wrapper
        logger.info("📦 Importing news_fetch_worker...")
        from news_filter import get_news_filter
        
        def fetch_news_iteration():
            news_filter = get_news_filter(account_id=1)
            count = news_filter.fetch_and_store_events()
            if count > 0:
                logger.info(f"✅ News: Fetched {count} new economic events")
        
        workers['news_fetch'] = fetch_news_iteration
        
    except Exception as e:
        logger.error(f"Failed to import news_fetch_worker: {e}")
    
    try:
        # Trade Timeout Worker
        logger.info("📦 Importing trade_timeout_worker...")
        from database import ScopedSession
        from models import Trade
        from datetime import datetime, timedelta
        import os
        
        def check_timeouts():
            timeout_enabled = os.getenv('TRADE_TIMEOUT_ENABLED', 'true').lower() == 'true'
            if not timeout_enabled:
                return
            
            timeout_hours = int(os.getenv('TRADE_TIMEOUT_HOURS', '48'))
            timeout_action = os.getenv('TRADE_TIMEOUT_ACTION', 'alert')
            
            db = ScopedSession()
            try:
                timeout_limit = datetime.utcnow() - timedelta(hours=timeout_hours)
                
                old_trades = db.query(Trade).filter(
                    Trade.status == 'open',
                    Trade.open_time < timeout_limit
                ).all()
                
                if old_trades:
                    logger.warning(f"⏰ Found {len(old_trades)} trades older than {timeout_hours}h")
                    for trade in old_trades:
                        age_hours = (datetime.utcnow() - trade.open_time).total_seconds() / 3600
                        logger.warning(
                            f"  Trade {trade.ticket}: {trade.symbol} open for {age_hours:.1f}h "
                            f"(P/L: {trade.profit})"
                        )
            finally:
                db.close()
        
        workers['trade_timeout'] = check_timeouts
        
    except Exception as e:
        logger.error(f"Failed to import trade_timeout_worker: {e}")
    
    try:
        # Strategy Validation Worker
        logger.info("📦 Importing strategy_validation_worker...")
        from database import ScopedSession
        from models import Trade
        import os
        
        def validate_strategies():
            validation_enabled = os.getenv('STRATEGY_VALIDATION_ENABLED', 'true').lower() == 'true'
            if not validation_enabled:
                return
            
            min_loss = float(os.getenv('MIN_LOSS_TO_CHECK', '-5.0'))
            
            db = ScopedSession()
            try:
                losing_trades = db.query(Trade).filter(
                    Trade.status == 'open',
                    Trade.profit < min_loss
                ).all()
                
                if losing_trades:
                    logger.info(f"📊 Validating {len(losing_trades)} trades with loss > €{abs(min_loss)}")
            finally:
                db.close()
        
        workers['strategy_validation'] = validate_strategies
        
    except Exception as e:
        logger.error(f"Failed to import strategy_validation_worker: {e}")
    
    try:
        # Drawdown Protection Worker
        logger.info("📦 Importing drawdown_protection_worker...")
        import workers.drawdown_protection_worker as dpw
        from database import ScopedSession
        
        def check_drawdown():
            db = ScopedSession()
            try:
                dpw.check_drawdown_protection(db, account_id=1)
            finally:
                db.close()
        
        workers['drawdown_protection'] = check_drawdown
        
    except Exception as e:
        logger.error(f"Failed to import drawdown_protection_worker: {e}")
    
    try:
        # Partial Close Worker  
        logger.info("📦 Importing partial_close_worker...")
        import workers.partial_close_worker as pcw
        from database import ScopedSession
        
        def check_partial():
            db = ScopedSession()
            try:
                pcw.process_open_trades(db)
            finally:
                db.close()
        
        workers['partial_close'] = check_partial
        
    except Exception as e:
        logger.error(f"Failed to import partial_close_worker: {e}")
    
    try:
        # Auto Trader Worker
        logger.info("📦 Importing auto_trader_worker...")
        from auto_trader import get_auto_trader
        from database import ScopedSession
        
        def run_auto_trader():
            """Execute auto-trading logic"""
            auto_trader = get_auto_trader()
            db = ScopedSession()
            try:
                auto_trader.process_new_signals(db)
            finally:
                db.close()
        
        workers['auto_trader'] = run_auto_trader
        
    except Exception as e:
        logger.error(f"Failed to import auto_trader_worker: {e}")
    
    try:
        # Session Volatility Analyzer - Market Noise Logging
        logger.info("📦 Importing session_volatility_analyzer...")
        from session_volatility_analyzer import SessionVolatilityAnalyzer
        from database import ScopedSession
        from models import Trade
        
        def analyze_market_conditions():
            """Log current market conditions (session, volatility, noise) with timezone context"""
            analyzer = SessionVolatilityAnalyzer()
            from timezone_manager import tz
            db = ScopedSession()
            try:
                # Get current session with timezone info
                session_info = tz.get_current_session_info()
                session_name = session_info['session']
                
                # Get all open trades and analyze their symbols
                open_trades = db.query(Trade).filter_by(status='open').all()
                symbols = list(set(t.symbol for t in open_trades))
                
                if symbols:
                    logger.info(f"📊 Market Conditions Analysis ({session_name}):")
                    logger.info(f"   🕒 UTC: {session_info['utc_time']} | Broker: {session_info['broker_time']}")
                    
                    for symbol in symbols[:5]:  # Limit to first 5 symbols
                        # Calculate volatility (note: parameter order is symbol, db, account_id)
                        volatility = analyzer.calculate_recent_volatility(symbol, db, account_id=1)
                        
                        # Get trailing distance multiplier
                        multiplier, reason = analyzer.get_trailing_distance_multiplier(symbol, db, account_id=1)
                        
                        # Determine volatility label
                        if volatility < 0.8:
                            vol_label = "LOW"
                        elif volatility < 1.2:
                            vol_label = "NORMAL"
                        elif volatility < 1.8:
                            vol_label = "HIGH"
                        else:
                            vol_label = "EXTREME"
                        
                        logger.info(
                            f"   {symbol:8s} | Session: {session_name:18s} | "
                            f"Volatility: {vol_label:8s} ({volatility:.2f}x) | "
                            f"Trailing: {multiplier:.2f}x"
                        )
                        
            finally:
                db.close()
        
        workers['market_conditions'] = analyze_market_conditions
        
    except Exception as e:
        logger.error(f"Failed to import session_volatility_analyzer: {e}")
    
    try:
        # Time Exit Worker - Time-based position closing
        logger.info("📦 Importing time_exit_worker...")
        import workers.time_exit_worker as tew
        from database import ScopedSession
        
        def check_time_exits():
            """Check for trades that should be closed based on time"""
            time_exit_enabled = os.getenv('TIME_EXIT_ENABLED', 'false').lower() == 'true'
            if not time_exit_enabled:
                return
            
            db = ScopedSession()
            try:
                # Process time-based exits
                results = tew.process_open_trades(db)
                if results.get('closed_count', 0) > 0:
                    logger.info(f"⏰ Time Exit: Closed {results['closed_count']} trades")
            finally:
                db.close()
        
        workers['time_exit'] = check_time_exits
        
    except Exception as e:
        logger.error(f"Failed to import time_exit_worker: {e}")
    
    try:
        # TP/SL Monitor Worker
        logger.info("📦 Importing tpsl_monitor_worker...")
        import workers.tpsl_monitor_worker as tpsl
        from database import ScopedSession
        
        _tpsl_monitor = tpsl.TPSLMonitor()
        
        def check_tpsl():
            """Check for missing TP/SL on open trades"""
            db = ScopedSession()
            try:
                _tpsl_monitor.check_trades(db)
            finally:
                db.close()
        
        workers['tpsl_monitor'] = check_tpsl
        
    except Exception as e:
        logger.error(f"Failed to import tpsl_monitor_worker: {e}")
    
    try:
        # ✅ Signal Generator Worker - Generates trading signals
        logger.info("📦 Importing signal_worker...")
        from database import ScopedSession
        from models import Account, SubscribedSymbol
        from signal_generator import SignalGenerator

        def run_signal_generation():
            """Generate signals for all subscribed symbols"""
            db = ScopedSession()
            try:
                signals_generated = 0
                accounts = db.query(Account).all()

                for account in accounts:
                    # Get account risk profile (default to 'normal' if not set)
                    risk_profile = getattr(account, 'risk_profile', 'normal')

                    subscribed = db.query(SubscribedSymbol).filter(
                        SubscribedSymbol.account_id == account.id,
                        SubscribedSymbol.active == True
                    ).all()

                    for sub in subscribed:
                        for timeframe in ['H1', 'H4']:
                            try:
                                # Pass risk_profile to SignalGenerator for regime filtering
                                generator = SignalGenerator(account.id, sub.symbol, timeframe, risk_profile)
                                signal = generator.generate_signal()
                                if signal:
                                    signals_generated += 1
                                    logger.info(f"📊 Generated {signal['signal_type']} signal for {sub.symbol} {timeframe} (confidence: {signal['confidence']:.1f}%)")
                            except Exception as e:
                                logger.debug(f"Signal generation failed for {sub.symbol} {timeframe}: {e}")

                if signals_generated > 0:
                    logger.info(f"✅ Signal generation: {signals_generated} new signals created")
            finally:
                db.close()

        workers['signal_generator'] = run_signal_generation

    except Exception as e:
        logger.error(f"Failed to import signal_generator: {e}")

    try:
        # ✅ Signal Validation Worker - Continuous indicator-based validation
        logger.info("📦 Importing signal_validator...")
        from signal_validator import SignalValidator

        _signal_validator = SignalValidator()

        def run_signal_validation():
            """Validate all active signals against indicator conditions"""
            _signal_validator.validate_all_signals()

        workers['signal_validation'] = run_signal_validation

    except Exception as e:
        logger.error(f"Failed to import signal_validator: {e}")
    
    try:
        # ✅ NEW: Trade Monitor with Smart Trailing Stop
        logger.info("📦 Importing trade_monitor...")
        import trade_monitor as tm
        from database import ScopedSession
        
        _trade_monitor = tm.get_monitor()
        
        def run_trade_monitor_cycle():
            """Run one cycle of trade monitoring"""
            db = ScopedSession()
            try:
                _trade_monitor.monitor_once(db)
            finally:
                db.close()
        
        workers['trade_monitor'] = run_trade_monitor_cycle
        
    except Exception as e:
        logger.error(f"Failed to import trade_monitor: {e}")
    
    try:
        # ✅ NEW: MFE/MAE Tracker - Maximum Favorable/Adverse Excursion
        logger.info("📦 Importing mfe_mae_tracker...")
        import workers.mfe_mae_tracker as mfe
        
        _mfe_tracker = mfe.MFEMAETracker()
        
        workers['mfe_mae_tracker'] = _mfe_tracker.update_all_trades
        
    except Exception as e:
        logger.error(f"Failed to import mfe_mae_tracker: {e}")
    
    return workers


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"🛑 Received signal {signum}, initiating graceful shutdown...")
    shutdown_event.set()


def print_status(threads: Dict[str, WorkerThread]):
    """Print status of all workers"""
    logger.info("=" * 80)
    logger.info("UNIFIED WORKERS STATUS")
    logger.info("=" * 80)
    
    for name, thread in threads.items():
        status = "✅ HEALTHY" if thread.is_healthy else "❌ UNHEALTHY"
        last_run = thread.last_run.strftime('%Y-%m-%d %H:%M:%S') if thread.last_run else "Never"
        
        logger.info(
            f"{name:25s} {status:12s} | "
            f"Success: {thread.success_count:4d} | "
            f"Errors: {thread.error_count:2d} | "
            f"Last: {last_run}"
        )
    
    logger.info("=" * 80)


def main():
    """
    Main entry point - starts all workers
    """
    logger.info("=" * 80)
    logger.info("🚀 UNIFIED WORKER MANAGER - Starting")
    logger.info("=" * 80)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Import all worker functions
    logger.info("\n📦 Loading worker modules...")
    worker_functions = import_worker_functions()
    
    if not worker_functions:
        logger.error("❌ No workers loaded! Exiting...")
        sys.exit(1)
    
    logger.info(f"✅ Loaded {len(worker_functions)} workers")
    
    # Worker configurations (intervals in seconds)
    worker_configs = {
        'decision_cleanup': {
            'function': worker_functions.get('decision_cleanup'),
            'interval': int(os.getenv('CLEANUP_INTERVAL_SECONDS', 3600)),  # 1 hour
        },
        'news_fetch': {
            'function': worker_functions.get('news_fetch'),
            'interval': int(os.getenv('NEWS_FETCH_INTERVAL_SECONDS', 3600)),  # 1 hour
        },
        'trade_timeout': {
            'function': worker_functions.get('trade_timeout'),
            'interval': int(os.getenv('TRADE_TIMEOUT_CHECK_INTERVAL', 300)),  # 5 minutes
        },
        'strategy_validation': {
            'function': worker_functions.get('strategy_validation'),
            'interval': int(os.getenv('STRATEGY_VALIDATION_CHECK_INTERVAL', 300)),  # 5 minutes
        },
        'drawdown_protection': {
            'function': worker_functions.get('drawdown_protection'),
            'interval': int(os.getenv('DRAWDOWN_CHECK_INTERVAL', 60)),  # 1 minute
        },
        'partial_close': {
            'function': worker_functions.get('partial_close'),
            'interval': int(os.getenv('PARTIAL_CLOSE_CHECK_INTERVAL', 60)),  # 1 minute
        },
        'mfe_mae_tracker': {
            'function': worker_functions.get('mfe_mae_tracker'),
            'interval': int(os.getenv('MFE_MAE_UPDATE_INTERVAL', 10)),  # 10 seconds
        },
        'signal_generator': {
            'function': worker_functions.get('signal_generator'),
            'interval': int(os.getenv('SIGNAL_GENERATOR_INTERVAL', 60)),  # 1 minute
        },
        'auto_trader': {
            'function': worker_functions.get('auto_trader'),
            'interval': int(os.getenv('AUTO_TRADER_CHECK_INTERVAL', 60)),  # 1 minute
        },
        'market_conditions': {
            'function': worker_functions.get('market_conditions'),
            'interval': int(os.getenv('MARKET_CONDITIONS_CHECK_INTERVAL', 300)),  # 5 minutes
        },
        'time_exit': {
            'function': worker_functions.get('time_exit'),
            'interval': int(os.getenv('TIME_EXIT_CHECK_INTERVAL', 300)),  # 5 minutes
        },
        'tpsl_monitor': {
            'function': worker_functions.get('tpsl_monitor'),
            'interval': int(os.getenv('TPSL_MONITOR_CHECK_INTERVAL', 60)),  # 1 minute
        },
        'signal_validation': {
            'function': worker_functions.get('signal_validation'),
            'interval': int(os.getenv('SIGNAL_VALIDATION_CHECK_INTERVAL', 10)),  # 10 seconds - continuous validation
        },
        'trade_monitor': {
            'function': worker_functions.get('trade_monitor'),
            'interval': int(os.getenv('TRADE_MONITOR_CHECK_INTERVAL', 1)),  # 1 second for real-time monitoring
        },
    }
    
    # Start worker threads
    logger.info("\n🧵 Starting worker threads...")
    threads: Dict[str, WorkerThread] = {}
    
    for name, config in worker_configs.items():
        if config['function'] is None:
            logger.warning(f"⚠️  Skipping {name}: Function not loaded")
            continue
            
        thread = WorkerThread(
            name=name,
            target=config['function'],
            interval_seconds=config['interval']
        )
        thread.start()
        threads[name] = thread
        logger.info(f"✅ Started: {name} (interval: {config['interval']}s)")
    
    logger.info(f"\n✅ All workers started! Running {len(threads)} workers in parallel")
    logger.info("=" * 80)
    
    # Monitor workers and print status periodically
    status_interval = 300  # Print status every 5 minutes
    last_status = time.time()
    
    try:
        while not shutdown_event.is_set():
            # Check if any thread died unexpectedly
            for name, thread in threads.items():
                if not thread.is_alive():
                    logger.error(f"💀 Worker thread died: {name} - Restarting...")
                    
                    # Restart the thread
                    config = worker_configs[name]
                    new_thread = WorkerThread(
                        name=name,
                        target=config['function'],
                        interval_seconds=config['interval']
                    )
                    new_thread.start()
                    threads[name] = new_thread
            
            # Print status periodically
            if time.time() - last_status >= status_interval:
                print_status(threads)
                last_status = time.time()
            
            time.sleep(10)  # Check every 10 seconds
            
    except KeyboardInterrupt:
        logger.info("\n🛑 Keyboard interrupt received")
        shutdown_event.set()
    
    # Wait for all threads to finish
    logger.info("\n⏳ Waiting for workers to finish...")
    for name, thread in threads.items():
        thread.join(timeout=30)
        if thread.is_alive():
            logger.warning(f"⚠️  {name} did not stop gracefully")
        else:
            logger.info(f"✅ {name} stopped")
    
    logger.info("\n" + "=" * 80)
    logger.info("🛑 UNIFIED WORKER MANAGER - Shutdown complete")
    logger.info("=" * 80)


if __name__ == '__main__':
    main()
