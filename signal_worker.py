"""
Signal Worker - Background worker for continuous signal generation
"""

import time
import logging
from threading import Thread
from datetime import datetime
from database import ScopedSession
from models import Account, SubscribedSymbol
from signal_generator import SignalGenerator

logger = logging.getLogger(__name__)


class SignalWorker:
    """
    Background worker that continuously generates trading signals with smart caching
    Only regenerates signals when candles actually close (H1=60min, H4=240min)
    """

    def __init__(self, interval=10):
        """
        Initialize Signal Worker

        Args:
            interval: Base signal generation interval in seconds (default: 10)
                     Used for checking if candles closed, not for signal generation
        """
        self.base_interval = interval
        self.current_interval = interval
        self.running = False
        self.thread = None
        self.total_signals = 0
        self.total_iterations = 0
        self.last_prices = {}  # Track price changes for volatility detection

        # Smart caching: Track last candle close time for each symbol/timeframe
        # Structure: {symbol_timeframe: last_candle_close_datetime}
        self.last_candle_close = {}
        self.cache_hits = 0
        self.cache_misses = 0

    def start(self):
        """Start the background worker"""
        if self.running:
            logger.warning("Signal worker already running")
            return

        # Cleanup any duplicate signals on startup
        self._cleanup_duplicates()

        self.running = True
        self.thread = Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        logger.info(f"Signal worker started (interval={self.interval}s)")

    def stop(self):
        """Stop the background worker"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=10)
        logger.info(
            f"Signal worker stopped (generated {self.total_signals} signals "
            f"in {self.total_iterations} iterations)"
        )

    def _worker_loop(self):
        """Main worker loop with adaptive interval based on market volatility"""
        while self.running:
            try:
                start_time = time.time()

                # Generate signals for all subscribed symbols and timeframes
                signals_generated = self._generate_all_signals()

                self.total_signals += signals_generated
                self.total_iterations += 1

                # Expire old signals
                SignalGenerator.expire_old_signals()

                # Cleanup old signals every 5 minutes (every ~30 iterations at 10s interval)
                if self.total_iterations % 30 == 0:
                    self._cleanup_old_signals(minutes_to_keep=10)

                # Calculate market volatility and adjust interval
                volatility_level = self._calculate_market_volatility()
                self._adjust_interval(volatility_level)

                elapsed = time.time() - start_time

                # Calculate cache efficiency
                total_checks = self.cache_hits + self.cache_misses
                cache_efficiency = (self.cache_hits / total_checks * 100) if total_checks > 0 else 0

                logger.info(
                    f"Signal generation cycle completed in {elapsed:.2f}s "
                    f"({signals_generated} signals generated, "
                    f"cache efficiency: {cache_efficiency:.1f}% ({self.cache_hits} hits / {total_checks} checks), "
                    f"volatility: {volatility_level}, next interval: {self.current_interval}s)"
                )

            except Exception as e:
                logger.error(f"Signal worker error: {e}", exc_info=True)

            # Sleep for adaptive interval
            time.sleep(self.current_interval)

    def _generate_all_signals(self) -> int:
        """
        Generate signals for all subscribed symbols and timeframes

        Returns:
            Number of signals generated
        """
        db = ScopedSession()
        signals_count = 0

        try:
            # Get active account (most recent heartbeat) and extract ID immediately
            account = db.query(Account).order_by(Account.last_heartbeat.desc()).first()
            if not account:
                logger.warning("No account found")
                return 0

            # Extract account ID and risk_profile immediately to avoid detached instance issues
            account_id = account.id
            risk_profile = getattr(account, 'risk_profile', 'normal')

            # Check drawdown protection - pause signals if drawdown too high
            account_equity = float(account.equity) if account.equity else 0
            account_balance = float(account.balance) if account.balance else 0

            if account_balance > 0:
                drawdown_pct = ((account_balance - account_equity) / account_balance) * 100

                MAX_DRAWDOWN_FOR_NEW_SIGNALS = 15.0  # 15% max drawdown

                if drawdown_pct > MAX_DRAWDOWN_FOR_NEW_SIGNALS:
                    logger.warning(
                        f"⚠️ Drawdown protection activated: {drawdown_pct:.1f}% "
                        f"(max: {MAX_DRAWDOWN_FOR_NEW_SIGNALS}%) - pausing new signals"
                    )
                    return 0  # No new signals

            # Get subscribed symbols and extract data immediately to avoid detached instance issues
            subscribed = db.query(SubscribedSymbol).filter_by(
                account_id=account_id,
                active=True
            ).all()

            if not subscribed:
                logger.warning("No subscribed symbols found")
                return 0

            # Extract symbol names immediately while session is active
            symbol_names = [sub.symbol for sub in subscribed]

            # Timeframes to analyze - optimized for best performance and quality
            # H1: Daily trends (7 days data needed)
            # H4: Weekly trends (14 days data needed)
            # Note: M1/M5/M15 removed due to noise, D1 removed due to low frequency
            timeframes = ['H1', 'H4']

            # Generate signals for each symbol and timeframe
            for symbol_name in symbol_names:
                # Check if symbol is tradeable (within trading hours)
                from models import Tick
                from datetime import datetime, timedelta

                # NOTE: Ticks are now GLOBAL (no account_id) - a EURUSD tick is the same for everyone
                latest_tick = db.query(Tick).filter_by(
                    symbol=symbol_name
                ).order_by(Tick.timestamp.desc()).first()

                # Skip if no tick data available
                if not latest_tick:
                    logger.debug(f"Skipping signal generation for {symbol_name} (no tick data)")
                    continue

                # ✅ FIX: Extract tick data immediately to avoid detached instance errors
                tick_tradeable = latest_tick.tradeable
                tick_timestamp = latest_tick.timestamp

                # Skip signal generation for non-tradeable symbols
                if not tick_tradeable:
                    logger.debug(f"Skipping signal generation for {symbol_name} (outside trading hours)")
                    continue

                for timeframe in timeframes:
                    # Timeframe-dependent stale data tolerance
                    # Higher timeframes need longer windows since candles close less frequently
                    STALE_TOLERANCE = {
                        'M5': timedelta(minutes=10),
                        'M15': timedelta(minutes=30),
                        'H1': timedelta(hours=2),
                        'H4': timedelta(hours=6),   # 1.5x timeframe duration
                        'D1': timedelta(days=2)
                    }

                    max_tick_age = STALE_TOLERANCE.get(timeframe, timedelta(minutes=5))
                    tick_age = datetime.utcnow() - tick_timestamp

                    if tick_age > max_tick_age:
                        logger.debug(f"Skipping {symbol_name} {timeframe} (stale data: {tick_age.total_seconds():.0f}s > {max_tick_age.total_seconds():.0f}s)")
                        continue
                    try:
                        cache_key = f"{symbol_name}_{timeframe}"

                        # Check if a new candle has closed since last signal generation
                        should_generate = self._should_generate_signal(
                            symbol_name, timeframe, datetime.utcnow(), db
                        )

                        if not should_generate:
                            self.cache_hits += 1
                            logger.debug(
                                f"Skipping {symbol_name} {timeframe} - candle hasn't closed yet "
                                f"(cache hit {self.cache_hits}/{self.cache_hits + self.cache_misses})"
                            )
                            continue

                        # Candle has closed - generate fresh signal
                        self.cache_misses += 1

                        # Pass risk_profile to SignalGenerator for regime filtering
                        generator = SignalGenerator(
                            account_id,
                            symbol_name,
                            timeframe,
                            risk_profile
                        )

                        signal = generator.generate_signal()

                        if signal:
                            signals_count += 1
                            logger.info(
                                f"✨ Fresh signal generated: {signal['signal_type']} "
                                f"{symbol_name} {timeframe} "
                                f"(confidence: {signal['confidence']}%, new candle closed)"
                            )

                        # Update last candle close time
                        self.last_candle_close[cache_key] = self._get_current_candle_close(
                            timeframe, datetime.utcnow()
                        )

                    except Exception as e:
                        # Use local variable instead of accessing sub.symbol which might fail
                        try:
                            symbol_name = sub.symbol
                        except AttributeError:
                            symbol_name = "UNKNOWN"
                        logger.error(
                            f"Error generating signal for {symbol_name} {timeframe}: {e}",
                            exc_info=True
                        )

            return signals_count

        except Exception as e:
            logger.error(f"Error in signal generation: {e}", exc_info=True)
            return 0
        finally:
            db.close()

    def _get_current_candle_close(self, timeframe: str, current_time: datetime) -> datetime:
        """
        Calculate when the current candle will close

        Args:
            timeframe: Timeframe (H1, H4, etc.)
            current_time: Current time

        Returns:
            Datetime when current candle closes
        """
        timeframe_minutes = {
            'M5': 5,
            'M15': 15,
            'M30': 30,
            'H1': 60,
            'H4': 240,
            'D1': 1440
        }

        minutes = timeframe_minutes.get(timeframe, 60)
        total_minutes = current_time.hour * 60 + current_time.minute

        if timeframe == 'D1':
            # Daily candle closes at midnight
            from datetime import timedelta
            return current_time.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:
            # Calculate next candle close
            from datetime import timedelta
            minutes_into_candle = total_minutes % minutes
            minutes_until_close = minutes - minutes_into_candle if minutes_into_candle > 0 else 0
            return current_time.replace(second=0, microsecond=0) + timedelta(minutes=minutes_until_close)

    def _should_generate_signal(self, symbol: str, timeframe: str, current_time: datetime, db) -> bool:
        """
        Determine if we should generate a signal for this symbol/timeframe
        Only generate if a NEW candle has closed since last signal

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            current_time: Current datetime
            db: Database session

        Returns:
            True if should generate signal, False if cached signal is still valid
        """
        cache_key = f"{symbol}_{timeframe}"

        # First run - always generate
        if cache_key not in self.last_candle_close:
            return True

        # Get last candle close time from OHLC data
        from models import OHLCData
        latest_ohlc = db.query(OHLCData).filter_by(
            symbol=symbol,
            timeframe=timeframe
        ).order_by(OHLCData.timestamp.desc()).first()

        if not latest_ohlc:
            return True  # No OHLC data - generate to populate

        # Check if a new candle has been created since last signal generation
        last_signal_time = self.last_candle_close[cache_key]

        if latest_ohlc.timestamp > last_signal_time:
            # New candle has closed - generate fresh signal
            logger.debug(
                f"New candle detected for {symbol} {timeframe}: "
                f"latest={latest_ohlc.timestamp}, last_signal={last_signal_time}"
            )
            return True

        # Candle hasn't closed yet - skip signal generation
        return False

    def _calculate_market_volatility(self) -> str:
        """
        Calculate market volatility based on price changes across all symbols

        Returns:
            'high', 'normal', or 'low' volatility level
        """
        from models import Tick
        db = ScopedSession()

        try:
            # Get latest ticks for all symbols
            latest_ticks = db.query(Tick).filter(
                Tick.tradeable == True
            ).order_by(Tick.symbol, Tick.timestamp.desc()).distinct(Tick.symbol).all()

            if not latest_ticks:
                return 'normal'

            total_volatility = 0
            count = 0

            for tick in latest_ticks:
                symbol = tick.symbol
                current_price = float(tick.bid)

                # Compare with last recorded price
                if symbol in self.last_prices:
                    last_price = self.last_prices[symbol]
                    # Calculate percentage change
                    if last_price > 0:
                        price_change = abs((current_price - last_price) / last_price) * 100
                        total_volatility += price_change
                        count += 1

                # Update last price
                self.last_prices[symbol] = current_price

            if count == 0:
                return 'normal'

            # Average volatility across all symbols
            avg_volatility = total_volatility / count

            # Classify volatility
            # High: > 0.05% average change (5 pips on major pairs)
            # Low: < 0.01% average change (1 pip on major pairs)
            if avg_volatility > 0.05:
                return 'high'
            elif avg_volatility < 0.01:
                return 'low'
            else:
                return 'normal'

        except Exception as e:
            logger.error(f"Error calculating volatility: {e}")
            return 'normal'
        finally:
            db.close()

    def _adjust_interval(self, volatility_level: str):
        """
        Adjust signal generation interval based on market volatility

        Args:
            volatility_level: 'high', 'normal', or 'low'
        """
        if volatility_level == 'high':
            # Fast updates during volatile markets
            self.current_interval = max(5, self.base_interval // 2)
        elif volatility_level == 'low':
            # Slower updates during quiet markets
            self.current_interval = min(20, self.base_interval * 2)
        else:
            # Normal interval
            self.current_interval = self.base_interval

        # Store volatility level and interval in Redis for API access
        try:
            from redis_client import get_redis
            redis = get_redis()
            redis.set_with_expiry('market_volatility', volatility_level, 60)
            redis.set_with_expiry('signal_interval', str(self.current_interval), 60)
        except Exception as e:
            logger.error(f"Error storing volatility in Redis: {e}")

    def _cleanup_duplicates(self):
        """Remove duplicate signals (same symbol+timeframe+status)"""
        from models import TradingSignal
        from sqlalchemy import func

        db = ScopedSession()
        try:
            # Find duplicates (signals are now global - no account_id)
            duplicates = db.query(
                TradingSignal.symbol,
                TradingSignal.timeframe
            ).filter(
                TradingSignal.status == 'active'
            ).group_by(
                TradingSignal.symbol,
                TradingSignal.timeframe
            ).having(
                func.count(TradingSignal.id) > 1
            ).all()

            cleaned = 0
            for symbol, timeframe in duplicates:
                # Get all signals for this combination (signals are now global)
                signals = db.query(TradingSignal).filter_by(
                    symbol=symbol,
                    timeframe=timeframe,
                    status='active'
                ).all()

                # Keep only the best one (highest confidence, then newest)
                best = max(signals, key=lambda x: (x.confidence, x.id))
                for sig in signals:
                    if sig.id != best.id:
                        sig.status = 'replaced'
                        cleaned += 1
                        logger.info(f"Cleaned duplicate signal ID {sig.id} for {symbol} {timeframe}")

            if cleaned > 0:
                db.commit()
                logger.info(f"Cleaned up {cleaned} duplicate signals on startup")
        except Exception as e:
            logger.error(f"Error cleaning duplicates: {e}")
            db.rollback()
        finally:
            db.close()

    def _cleanup_old_signals(self, minutes_to_keep: int = 10):
        """
        Remove old trading signals to prevent database bloat

        Args:
            minutes_to_keep: Keep signals from last N minutes (default: 10)
        """
        from models import TradingSignal
        from datetime import datetime, timedelta

        db = ScopedSession()
        try:
            cutoff_time = datetime.utcnow() - timedelta(minutes=minutes_to_keep)

            # Delete old signals
            deleted = db.query(TradingSignal).filter(
                TradingSignal.created_at < cutoff_time
            ).delete(synchronize_session=False)

            if deleted > 0:
                db.commit()
                logger.info(f"🗑️  Cleaned up {deleted} old signals (older than {minutes_to_keep} min)")

            return deleted

        except Exception as e:
            logger.error(f"Error cleaning old signals: {e}")
            db.rollback()
            return 0
        finally:
            db.close()

    def get_stats(self) -> dict:
        """Get worker statistics"""
        return {
            'running': self.running,
            'interval': self.interval,
            'total_signals': self.total_signals,
            'total_iterations': self.total_iterations,
            'avg_per_iteration': (
                self.total_signals / self.total_iterations
                if self.total_iterations > 0 else 0
            )
        }


# Global instance
_signal_worker = None


def get_signal_worker():
    """Get global signal worker instance"""
    global _signal_worker
    if _signal_worker is None:
        _signal_worker = SignalWorker(interval=10)  # Every 10 seconds
    return _signal_worker


def start_signal_worker(interval=10):
    """Start the global signal worker"""
    worker = get_signal_worker()
    worker.interval = interval
    worker.start()
    return worker
