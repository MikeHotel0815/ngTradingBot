#!/usr/bin/env python3
"""
Backtesting Engine for ngTradingBot
Replays historical data and generates virtual trades without future knowledge
"""

import logging
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import and_

from database import ScopedSession
from models import BacktestRun, BacktestTrade, OHLCData, Account

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class BacktestingEngine:
    """
    Backtesting engine that replays historical data and simulates trades
    Key Principle: NO FUTURE KNOWLEDGE - only use data up to current backtest timestamp
    """

    def __init__(self, backtest_run_id: int):
        self.backtest_run_id = backtest_run_id
        self.db = ScopedSession()
        self.backtest_run = self.db.query(BacktestRun).filter_by(id=backtest_run_id).first()

        if not self.backtest_run:
            raise ValueError(f"Backtest run {backtest_run_id} not found")

        self.account_id = self.backtest_run.account_id
        self.symbols = self.backtest_run.symbols.split(',') if self.backtest_run.symbols else []
        self.timeframes = self.backtest_run.timeframes.split(',') if self.backtest_run.timeframes else ['H1']

        # Load global settings
        from models import GlobalSettings
        self.settings = GlobalSettings.get_settings(self.db)

        # Virtual account state
        self.balance = float(self.backtest_run.initial_balance)
        self.initial_balance = self.balance
        self.equity = self.balance
        self.open_positions: List[Dict] = []
        self.closed_trades: List[BacktestTrade] = []

        # Performance tracking
        self.equity_curve = []
        self.peak_equity = self.balance
        self.max_drawdown = 0.0

        # Cooldown tracking after SL hits: symbol -> cooldown_until_time
        self.symbol_cooldowns = {}

        # OHLC Data Cache: Pre-load all data once instead of querying DB repeatedly
        # Structure: {symbol_timeframe: [sorted list of OHLC bars]}
        self.ohlc_cache: Dict[str, List[OHLCData]] = {}

        # Signal Cache: Cache signals until candle closes for that timeframe
        # Structure: {symbol_timeframe: {'signals': [...], 'cached_until': datetime}}
        self.signal_cache: Dict[str, Dict] = {}
        self._cache_cleanup_counter = 0  # Clean up cache every N iterations

        # Backtest-specific scorers (ISOLATED from live scores)
        # One scorer per symbol/timeframe combination
        from backtest_scorer import BacktestScorer
        self.scorers: Dict[str, BacktestScorer] = {}
        for symbol in self.symbols:
            for timeframe in self.timeframes:
                key = f"{symbol}_{timeframe}"
                self.scorers[key] = BacktestScorer(symbol, timeframe)

        logger.info(f"📊 Initialized {len(self.scorers)} isolated BacktestScorers")
        logger.info(f"🚀 Signal caching enabled: signals will be cached until candle close")

        logger.info(f"Loaded settings: max_positions={self.settings.max_positions}, sl_cooldown={self.settings.sl_cooldown_minutes}min")

        logger.info(f"Backtest Engine initialized: {self.backtest_run.name}")
        logger.info(f"Period: {self.backtest_run.start_date} → {self.backtest_run.end_date}")
        logger.info(f"Symbols: {self.symbols}, Timeframes: {self.timeframes}")

    def _update_progress(self, percent: float, status: str):
        """
        Update backtest progress in database

        Args:
            percent: Progress percentage (0-100)
            status: Current status message
        """
        try:
            self.db.execute(
                BacktestRun.__table__.update()
                .where(BacktestRun.id == self.backtest_run_id)
                .values(
                    progress_percent=round(percent, 2),
                    current_status=status
                )
            )
            self.db.commit()
        except Exception as e:
            logger.error(f"Error updating progress: {e}")
            self.db.rollback()

    def calculate_commission(self, symbol: str, volume: float) -> float:
        """
        Calculate broker commission for a trade.

        Typical broker commissions:
        - Forex: $7 per lot round-turn (entry + exit)
        - Gold/Silver: $10 per lot
        - Crypto: $15 per lot
        - Indices: $5 per lot

        Args:
            symbol: Trading symbol
            volume: Position size in lots

        Returns:
            Commission cost in USD
        """
        if 'XAU' in symbol or 'XAG' in symbol:
            # Metals: $10/lot
            return volume * 10.0
        elif 'BTC' in symbol or 'ETH' in symbol:
            # Crypto: $15/lot
            return volume * 15.0
        elif any(idx in symbol for idx in ['DAX', 'DE40', 'SPX', 'US500', 'NDX', 'US100']):
            # Indices: $5/lot
            return volume * 5.0
        else:
            # Forex: $7/lot
            return volume * 7.0

    def calculate_slippage(self, symbol: str, volume: float) -> float:
        """
        Calculate realistic slippage based on liquidity and position size.

        Slippage increases with:
        1. Position size (larger orders = more slippage)
        2. Symbol type (exotic pairs = more slippage)
        3. Market volatility

        For backtesting, we use conservative fixed estimates.

        Args:
            symbol: Trading symbol
            volume: Position size in lots

        Returns:
            Slippage cost in USD
        """
        # Base slippage (1 pip equivalent in USD)
        if symbol in ['EURUSD', 'GBPUSD', 'USDJPY']:
            # Majors: 0.5 pips base + 0.2 pips per lot
            slippage_pips = 0.5 + (volume * 0.2)
            slippage_cost = slippage_pips * volume * 10  # $10 per pip per lot
        elif 'XAUUSD' in symbol:
            # Gold: $0.20 base + $0.10 per lot
            slippage_cost = (0.20 + (volume * 0.10)) * volume * 100
        elif 'BTCUSD' in symbol:
            # Bitcoin: $10 base + $5 per lot
            slippage_cost = (10 + (volume * 5)) * volume
        elif any(idx in symbol for idx in ['DE40', 'DAX', 'SPX', 'NDX']):
            # Indices: 1 point base + 0.5 points per lot
            slippage_cost = (1.0 + (volume * 0.5)) * volume
        else:
            # Other pairs: 1 pip base + 0.3 pips per lot
            slippage_pips = 1.0 + (volume * 0.3)
            slippage_cost = slippage_pips * volume * 10

        return slippage_cost

    def run(self):
        """Execute the backtest"""
        try:
            # Update status and capture backtest start time
            # CRITICAL: Store this to prevent using OHLC data created DURING the backtest
            self.backtest_start_time = datetime.utcnow()
            self.backtest_run.status = 'running'
            self.backtest_run.started_at = self.backtest_start_time
            self.db.commit()

            logger.info(f"🚀 Starting backtest execution at {self.backtest_start_time}")
            logger.info(f"⚠️  CRITICAL: Will only use OHLC data with timestamp < {self.backtest_start_time}")

            # Wait for OHLC data to be available
            self._wait_for_ohlc_data()

            # Pre-load ALL OHLC data into memory cache (HUGE performance boost!)
            self._preload_ohlc_cache()

            # IMPORTANT: Lock start/end dates at backtest start to prevent changes during execution
            # These are the BACKTEST period dates (not real-time), frozen at start
            backtest_start_date = self.backtest_run.start_date
            backtest_end_date = self.backtest_run.end_date

            logger.info(f"📅 Backtest period LOCKED: {backtest_start_date} → {backtest_end_date}")

            # Main backtest loop - iterate through time
            current_time = backtest_start_date
            end_time = backtest_end_date

            # Determine time step based on shortest timeframe
            # M5 = 5 min, M15 = 15 min, M30 = 30 min, H1 = 1 hour, H4 = 4 hours, D1 = 1 day
            timeframe_minutes = {
                'M5': 5,
                'M15': 15,
                'M30': 30,
                'H1': 60,
                'H4': 240,
                'D1': 1440
            }

            # Get shortest timeframe to determine step size
            shortest_tf = min(
                [timeframe_minutes.get(tf.strip(), 60) for tf in self.timeframes]
            )
            time_step = timedelta(minutes=shortest_tf)

            logger.info(f"Using {shortest_tf}-minute time steps for simulation (shortest timeframe: {self.timeframes})")

            total_steps = int((end_time - backtest_start_date).total_seconds() / (shortest_tf * 60))
            step_count = 0
            last_progress_update = 0

            # Initialize progress tracking
            logger.info(f"📊 Initializing progress tracking: total_steps={total_steps}")
            self.db.execute(
                BacktestRun.__table__.update()
                .where(BacktestRun.id == self.backtest_run_id)
                .values(total_candles=total_steps, processed_candles=0)
            )
            self.db.commit()
            logger.info(f"✅ Progress tracking initialized: total_candles={total_steps}, DB committed")
            logger.info(f"🔄 Starting simulation loop: current_time={current_time}, end_time={end_time}")

            while current_time <= end_time:
                # Log first iteration to confirm loop is running
                if step_count == 0:
                    logger.info("🎯 First iteration of simulation loop starting...")

                # Process this time step
                self.process_timestep(current_time)

                # Move to next time step
                current_time += time_step
                step_count += 1

                # Update progress every 1% to show it's working
                current_progress = (step_count / total_steps * 100) if total_steps > 0 else 0
                current_progress = min(current_progress, 100.0)

                if current_progress >= last_progress_update + 1:
                    last_progress_update = int(current_progress)

                    # Create status message
                    status_msg = f"Progress: {current_progress:.1f}% | Balance: ${self.balance:.2f} | Open: {len(self.open_positions)} | Closed: {len(self.closed_trades)}"
                    logger.info(status_msg)

                    # Calculate estimated completion time
                    eta = None
                    if step_count > 0:
                        elapsed = (datetime.utcnow() - self.backtest_run.started_at).total_seconds()
                        time_per_step = elapsed / step_count
                        remaining_steps = total_steps - step_count
                        remaining_seconds = remaining_steps * time_per_step
                        eta = datetime.utcnow() + timedelta(seconds=remaining_seconds)
                        logger.info(f"📈 Detailed progress: {current_time} | Candles: {step_count}/{total_steps} | ETA: {eta.strftime('%H:%M:%S')}")

                    # Update detailed progress in database using direct SQL
                    self.db.execute(
                        BacktestRun.__table__.update()
                        .where(BacktestRun.id == self.backtest_run_id)
                        .values(
                            progress_percent=round(current_progress, 2),
                            current_status=status_msg,
                            processed_candles=step_count,
                            current_processing_date=current_time,
                            estimated_completion=eta
                        )
                    )
                    self.db.commit()

            # Close all remaining positions at end
            self.close_all_positions(current_time, reason='END_OF_BACKTEST')

            # Calculate final metrics
            self.calculate_metrics()

            # Export learned indicator scores
            self.export_learned_scores()

            # Save results
            self.save_results()

            logger.info("✅ Backtest completed successfully")

        except Exception as e:
            logger.error(f"Backtest failed: {e}")
            self.backtest_run.status = 'failed'
            self.backtest_run.error_message = str(e)
            self.db.commit()
            raise

        finally:
            self.db.close()

    def _wait_for_ohlc_data(self):
        """
        Intelligent OHLC data availability check with automatic gap detection

        Strategy:
        1. Check for existing data in DB (persistent storage)
        2. Detect gaps in time series
        3. Request missing historical data from EA if needed
        4. Wait for data to be loaded

        This ensures we only request historical data ONCE and it stays in DB permanently
        """
        import time

        logger.info(f"📊 Checking OHLC data availability and detecting gaps...")
        self._update_progress(0.0, "Checking OHLC data availability...")

        # Calculate required date range (backtest period + 180 days for indicator warmup)
        # NOTE: Limited to 180 days because MT5 rejects requests spanning >1 year
        lookback_start = self.backtest_run.start_date - timedelta(days=180)
        lookback_end = self.backtest_run.end_date

        total_checks = len(self.symbols) * len(self.timeframes)
        current_check = 0

        for symbol in self.symbols:
            for timeframe in self.timeframes:
                current_check += 1
                progress_pct = (current_check / total_checks) * 5.0  # Gap detection = 0-5%
                self._update_progress(
                    progress_pct,
                    f"Checking {symbol} {timeframe} data ({current_check}/{total_checks})..."
                )
                # Check what data we have in DB
                existing_data = self.db.query(OHLCData).filter(
                    and_(
                        OHLCData.account_id == self.account_id,
                        OHLCData.symbol == symbol,
                        OHLCData.timeframe == timeframe,
                        OHLCData.timestamp >= lookback_start,
                        OHLCData.timestamp <= lookback_end
                    )
                ).order_by(OHLCData.timestamp.asc()).all()

                # Calculate expected number of bars for this period
                expected_bars = self._calculate_expected_bars(
                    lookback_start, lookback_end, timeframe
                )
                actual_bars = len(existing_data)

                coverage_percent = (actual_bars / expected_bars * 100) if expected_bars > 0 else 0

                logger.info(
                    f"  {symbol} {timeframe}: {actual_bars:,} bars in DB "
                    f"({coverage_percent:.1f}% coverage, expected ~{expected_bars:,})"
                )

                # If we have <80% coverage, request historical data
                if coverage_percent < 80:
                    logger.warning(
                        f"⚠️  Insufficient data for {symbol} {timeframe} "
                        f"({coverage_percent:.1f}% < 80%) - requesting historical data from EA..."
                    )

                    self._update_progress(
                        progress_pct,
                        f"Requesting historical data for {symbol} {timeframe}..."
                    )

                    # Send REQUEST_HISTORICAL_DATA to EA
                    self._request_historical_data(symbol, timeframe, lookback_start, lookback_end)

                    # Wait for data to arrive (max 5 minutes)
                    self._wait_for_historical_data_arrival(
                        symbol, timeframe, lookback_start, lookback_end,
                        target_bars=expected_bars, timeout=300,
                        base_progress=progress_pct
                    )
                else:
                    logger.info(f"✅ Sufficient data for {symbol} {timeframe} - using existing DB data")

    def _calculate_expected_bars(self, start_date: datetime, end_date: datetime, timeframe: str) -> int:
        """
        Calculate expected number of bars for a date range and timeframe

        Note: This is an approximation (doesn't account for weekends/holidays)
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
        total_minutes = (end_date - start_date).total_seconds() / 60

        # Forex markets are open ~120 hours/week (5 days), so adjust for ~71% uptime
        expected = int(total_minutes / minutes * 0.71)

        return max(expected, 1)

    def _request_historical_data(self, symbol: str, timeframe: str, start_date: datetime, end_date: datetime):
        """Send REQUEST_HISTORICAL_DATA command to EA"""
        from models import Account, Command
        import uuid

        try:
            account = self.db.query(Account).filter_by(id=self.account_id).first()
            if not account:
                logger.error(f"Account {self.account_id} not found")
                return

            # Create EA command
            command = Command(
                id=str(uuid.uuid4()),
                account_id=self.account_id,
                command_type='REQUEST_HISTORICAL_DATA',
                payload={
                    'symbol': symbol,
                    'timeframe': timeframe,
                    'start_date': start_date.strftime('%Y-%m-%d'),
                    'end_date': end_date.strftime('%Y-%m-%d')
                },
                status='pending'
            )

            self.db.add(command)
            self.db.commit()

            logger.info(
                f"📡 Sent REQUEST_HISTORICAL_DATA to EA: {symbol} {timeframe} "
                f"from {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
            )

        except Exception as e:
            logger.error(f"Error sending historical data request: {e}")
            self.db.rollback()

    def _wait_for_historical_data_arrival(
        self, symbol: str, timeframe: str,
        start_date: datetime, end_date: datetime,
        target_bars: int, timeout: int = 300,
        base_progress: float = 0.0
    ):
        """
        Wait for historical data to arrive from EA

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            start_date: Start of date range
            end_date: End of date range
            target_bars: Expected number of bars
            timeout: Maximum wait time in seconds
            base_progress: Base progress percentage for this step
        """
        import time

        check_interval = 3  # seconds
        waited = 0

        logger.info(f"⏳ Waiting for historical data to arrive (target: {target_bars:,} bars, timeout: {timeout}s)...")
        self._update_progress(base_progress, f"Waiting for {symbol} {timeframe} data from EA...")

        while waited < timeout:
            # Check current bar count
            count = self.db.query(OHLCData).filter(
                and_(
                    OHLCData.account_id == self.account_id,
                    OHLCData.symbol == symbol,
                    OHLCData.timeframe == timeframe,
                    OHLCData.timestamp >= start_date,
                    OHLCData.timestamp <= end_date
                )
            ).count()

            coverage = (count / target_bars * 100) if target_bars > 0 else 0

            # Accept if we have >70% coverage (accounting for market closures)
            if coverage >= 70:
                logger.info(
                    f"✅ Historical data arrived: {count:,} bars "
                    f"({coverage:.1f}% coverage) - sufficient for backtest"
                )
                self._update_progress(base_progress, f"✅ {symbol} {timeframe} data loaded ({count:,} bars)")
                return

            # Update progress every 15 seconds
            if waited > 0 and waited % 15 == 0:
                logger.info(f"  Progress: {count:,} / {target_bars:,} bars ({coverage:.1f}%) - waiting...")
                self._update_progress(
                    base_progress,
                    f"Loading {symbol} {timeframe}: {count:,}/{target_bars:,} bars ({coverage:.1f}%)"
                )

            time.sleep(check_interval)
            waited += check_interval

        # Timeout reached
        final_count = self.db.query(OHLCData).filter(
            and_(
                OHLCData.account_id == self.account_id,
                OHLCData.symbol == symbol,
                OHLCData.timeframe == timeframe,
                OHLCData.timestamp >= start_date,
                OHLCData.timestamp <= end_date
            )
        ).count()

        logger.warning(
            f"⚠️  Timeout waiting for historical data ({waited}s) - "
            f"received {final_count:,} / {target_bars:,} bars - proceeding with available data"
        )
        self._update_progress(
            base_progress,
            f"⚠️ {symbol} {timeframe}: Timeout ({final_count:,}/{target_bars:,} bars) - proceeding"
        )

    def _preload_ohlc_cache(self):
        """
        Pre-load ALL OHLC data into memory cache to avoid repeated DB queries
        This is a MASSIVE performance optimization for backtests
        """
        logger.info(f"🚀 Pre-loading OHLC data into memory cache...")
        self._update_progress(5.0, "Loading OHLC data into memory cache...")

        total_bars = 0
        total_pairs = len(self.symbols) * len(self.timeframes)
        current_pair = 0

        for symbol in self.symbols:
            for timeframe in self.timeframes:
                current_pair += 1
                key = f"{symbol}_{timeframe}"

                # Load ALL data from before backtest start (to prevent time contamination)
                # and within a reasonable range (180 days before backtest start for indicator warmup)
                # Note: We filter by backtest_start_time to exclude data created DURING backtest
                lookback_start = self.backtest_run.start_date - timedelta(days=180)

                bars = self.db.query(OHLCData).filter(
                    and_(
                        OHLCData.account_id == self.account_id,
                        OHLCData.symbol == symbol,
                        OHLCData.timeframe == timeframe,
                        OHLCData.timestamp >= lookback_start,
                        OHLCData.timestamp < self.backtest_start_time  # CRITICAL: No data from during backtest
                    )
                ).order_by(OHLCData.timestamp.asc()).all()  # Sort ascending for easy slicing

                self.ohlc_cache[key] = bars
                total_bars += len(bars)
                logger.info(f"  Cached {len(bars)} bars for {symbol} {timeframe}")

                # Progress: 5-10% for cache loading
                progress_pct = 5.0 + (current_pair / total_pairs) * 5.0
                self._update_progress(
                    progress_pct,
                    f"Cached {symbol} {timeframe}: {len(bars):,} bars ({current_pair}/{total_pairs})"
                )

        logger.info(f"✅ OHLC cache loaded: {total_bars} total bars in memory")
        self._update_progress(10.0, f"✅ Cache loaded: {total_bars:,} bars in memory")

    def _get_cached_bars(self, symbol: str, timeframe: str, before_time: datetime, limit: int = 200) -> List[OHLCData]:
        """
        Get OHLC bars from cache instead of DB query
        Returns bars BEFORE the given time (no future knowledge)

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            before_time: Only return bars before this time
            limit: Maximum number of bars to return

        Returns:
            List of OHLC bars (newest first, same as DB query order)
        """
        key = f"{symbol}_{timeframe}"

        if key not in self.ohlc_cache:
            return []

        # Filter bars before the given time
        # Cache is sorted ascending, so we can use binary search for efficiency
        all_bars = self.ohlc_cache[key]

        # Simple linear filter (could optimize with bisect for huge datasets)
        filtered = [bar for bar in all_bars if bar.timestamp < before_time]

        # Return last N bars in descending order (newest first)
        return list(reversed(filtered[-limit:]))

    def _get_next_candle_close(self, current_time: datetime, timeframe: str) -> datetime:
        """
        Calculate when the next candle closes for this timeframe

        Args:
            current_time: Current backtest time
            timeframe: Timeframe (H1, H4, etc.)

        Returns:
            Next candle close time
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

        # Round up to next candle close
        # Example: if current_time is 14:23 and timeframe is H1 (60 min)
        # Next close is 15:00
        total_minutes = current_time.hour * 60 + current_time.minute

        if timeframe == 'D1':
            # Daily candle closes at midnight
            next_close = current_time.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:
            # Calculate minutes until next candle close
            minutes_into_candle = total_minutes % minutes
            if minutes_into_candle == 0:
                # Exactly on candle close
                next_close = current_time
            else:
                # Round up to next close
                minutes_until_close = minutes - minutes_into_candle
                next_close = current_time + timedelta(minutes=minutes_until_close)

        return next_close

    def process_timestep(self, current_time: datetime):
        """Process one time step in the backtest"""

        # Log every 1000 steps to show it's working
        if not hasattr(self, '_last_logged_step'):
            self._last_logged_step = 0

        current_step = getattr(self, '_current_step_count', 0)
        if current_step % 1000 == 0:
            logger.info(f"🔄 Processing timestep {current_step}: {current_time}")
        self._current_step_count = current_step + 1

        # 1. Update open positions (check for TP/SL hits)
        self.update_open_positions(current_time)

        # 2. Generate signals for this timestamp with SMART CACHING
        signals = self.generate_signals_cached(current_time)

        # 3. Execute new trades based on signals
        for signal in signals:
            self.execute_signal(signal, current_time)

        # 4. Update equity curve
        self.update_equity(current_time)

    def _cleanup_expired_cache(self, current_time: datetime):
        """
        Remove expired cache entries to prevent memory pollution.

        Runs periodically (every 100 timesteps) to clean up signal cache.
        Removes entries where cached_until < current_time.
        """
        keys_to_remove = []

        for cache_key, cache_data in self.signal_cache.items():
            cached_until = cache_data.get('cached_until')
            if cached_until and cached_until < current_time:
                keys_to_remove.append(cache_key)

        if keys_to_remove:
            for key in keys_to_remove:
                del self.signal_cache[key]

            logger.debug(f"🧹 Cache cleanup: Removed {len(keys_to_remove)} expired entries")

    def generate_signals_cached(self, current_time: datetime) -> List[Dict]:
        """
        Generate signals with smart caching - only regenerate when candle closes

        Performance optimization:
        - H1: Only regenerate every 60 minutes (12x speedup vs M5 timesteps)
        - H4: Only regenerate every 240 minutes (48x speedup vs M5 timesteps)

        This avoids recalculating indicators on the same unclosed candle repeatedly
        """
        # Periodic cache cleanup (every 100 calls)
        self._cache_cleanup_counter += 1
        if self._cache_cleanup_counter >= 100:
            self._cleanup_expired_cache(current_time)
            self._cache_cleanup_counter = 0

        all_signals = []

        for symbol in self.symbols:
            for timeframe in self.timeframes:
                cache_key = f"{symbol}_{timeframe}"

                # Check if we have cached signals that are still valid
                if cache_key in self.signal_cache:
                    cached_until = self.signal_cache[cache_key].get('cached_until')

                    # If cache is still valid (candle hasn't closed yet)
                    if cached_until and current_time < cached_until:
                        # Use cached signals (already filtered by confidence)
                        cached_signals = self.signal_cache[cache_key].get('signals', [])
                        # NOTE: Cached signals are already confidence-filtered when they were cached
                        all_signals.extend(cached_signals)
                        continue

                # Cache expired or doesn't exist - generate fresh signals
                try:
                    bars_needed = 50
                    bars_to_fetch = 200

                    historical_bars = self._get_cached_bars(symbol, timeframe, current_time, bars_to_fetch)

                    if len(historical_bars) < bars_needed:
                        # Not enough data - cache empty result
                        next_close = self._get_next_candle_close(current_time, timeframe)
                        self.signal_cache[cache_key] = {
                            'signals': [],
                            'cached_until': next_close
                        }
                        continue

                    # Generate full signal
                    signal = self._generate_full_signal(symbol, timeframe, current_time)

                    # Determine signals to cache
                    signals_to_cache = []
                    if signal and signal.get('signal_type') in ['BUY', 'SELL']:
                        signal_conf = signal.get('confidence', 0)
                        # Convert min_confidence from decimal (0.7) to percentage (70)
                        min_conf = float(self.backtest_run.min_confidence) * 100

                        if signal_conf >= min_conf:
                            signals_to_cache.append(signal)
                            all_signals.append(signal)
                            logger.info(f"✅ Signal ACCEPTED: {symbol} {timeframe} conf={signal_conf:.1f}% (min={min_conf:.1f}%)")
                        else:
                            logger.info(f"❌ Signal REJECTED: {symbol} {timeframe} conf={signal_conf:.1f}% < min={min_conf:.1f}%)")

                    # Cache signals until next candle close
                    next_close = self._get_next_candle_close(current_time, timeframe)
                    self.signal_cache[cache_key] = {
                        'signals': signals_to_cache,
                        'cached_until': next_close
                    }

                    # Log cache hits every 100 signals for debugging
                    if not hasattr(self, '_cache_log_counter'):
                        self._cache_log_counter = 0
                    self._cache_log_counter += 1

                    if self._cache_log_counter % 100 == 0:
                        logger.info(
                            f"🔄 Signal cache: Generated fresh signal for {symbol} {timeframe}, "
                            f"cached until {next_close} ({(next_close - current_time).total_seconds() / 60:.0f} min)"
                        )

                except Exception as e:
                    logger.error(f"Error generating cached signal for {symbol} {timeframe}: {e}")

        return all_signals

    def generate_signals(self, current_time: datetime) -> List[Dict]:
        """
        Generate trading signals at this timestamp using FULL signal generation logic
        CRITICAL: Only use OHLC data from BEFORE current_time (NO FUTURE KNOWLEDGE)

        This uses the SAME logic as live trading (TechnicalIndicators + PatternRecognizer)
        """
        signals = []

        for symbol in self.symbols:
            for timeframe in self.timeframes:
                try:
                    # Check if we have enough historical data
                    # We need at least 50 bars for basic indicators (EMA 20, RSI, etc.)
                    bars_needed = 50
                    bars_to_fetch = 200  # Fetch more for better indicator calculation

                    # USE CACHE instead of DB query (HUGE performance boost!)
                    historical_bars = self._get_cached_bars(symbol, timeframe, current_time, bars_to_fetch)

                    if len(historical_bars) < bars_needed:
                        continue  # Not enough data

                    # FULL signal generation using same logic as live trading
                    signal = self._generate_full_signal(symbol, timeframe, current_time)

                    if signal and signal.get('signal_type') in ['BUY', 'SELL']:
                        # Filter by confidence (convert from decimal to percentage)
                        if signal.get('confidence', 0) >= float(self.backtest_run.min_confidence) * 100:
                            signals.append(signal)

                except Exception as e:
                    logger.error(f"Error generating signal for {symbol} {timeframe}: {e}")

        return signals

    def _generate_full_signal(self, symbol: str, timeframe: str, current_time: datetime) -> Optional[Dict]:
        """
        Generate signal using indicators calculated on historical bars only
        Uses same logic as live trading but with time-filtered data

        Args:
            symbol: Trading symbol
            timeframe: Timeframe
            current_time: Current backtest time (for NO FUTURE KNOWLEDGE)

        Returns:
            Signal dict or None
        """
        try:
            # Get historical bars BEFORE current_time from CACHE
            historical_bars = self._get_cached_bars(symbol, timeframe, current_time, 200)

            if len(historical_bars) < 50:
                return None

            # Detect market regime first
            regime_info = self._detect_regime_on_bars(historical_bars)

            # Calculate indicators on historical bars
            indicator_signals = self._calculate_indicators_on_bars(historical_bars)

            # Pattern recognition on historical bars
            pattern_signals = self._recognize_patterns_on_bars(historical_bars)

            # Debug logging
            if indicator_signals or pattern_signals:
                logger.info(f"Signals at {current_time}: {len(indicator_signals)} indicators, {len(pattern_signals)} patterns")

            # No signals
            if not pattern_signals and not indicator_signals:
                return None

            # Aggregate signals with regime filtering (EXACT same logic as SignalGenerator)
            signal = self._aggregate_signals(pattern_signals, indicator_signals, symbol, timeframe, regime_info)

            if signal:
                logger.info(f"Aggregated signal: {signal['signal_type']} with confidence {signal['confidence']}%")

            if signal and signal['confidence'] >= 40:  # Minimum threshold
                # Calculate entry, SL, TP
                entry, sl, tp = self._calculate_entry_sl_tp_backtest(signal, current_time)

                signal['entry_price'] = entry
                signal['sl'] = sl
                signal['tp'] = tp

                return signal

            return None

        except Exception as e:
            logger.error(f"Error in full signal generation for {symbol} {timeframe}: {e}", exc_info=True)
            return None

    def _detect_regime_on_bars(self, bars: List[OHLCData]) -> Dict:
        """
        Detect market regime (TRENDING or RANGING) on historical bars
        Same logic as TechnicalIndicators.detect_market_regime()
        """
        import numpy as np
        import talib

        try:
            if len(bars) < 30:
                return {'regime': 'UNKNOWN', 'strength': 0, 'adx': None, 'bb_width': None}

            # Reverse to chronological order
            bars_sorted = list(reversed(bars))
            closes = np.array([float(bar.close) for bar in bars_sorted])
            highs = np.array([float(bar.high) for bar in bars_sorted])
            lows = np.array([float(bar.low) for bar in bars_sorted])

            # Calculate ADX (Average Directional Index) - measures trend strength
            adx = talib.ADX(highs, lows, closes, timeperiod=14)
            current_adx = adx[-1] if len(adx) > 0 and not np.isnan(adx[-1]) else None

            # Calculate Bollinger Band Width (normalized) - measures volatility
            bb_upper, bb_middle, bb_lower = talib.BBANDS(closes, timeperiod=20, nbdevup=2, nbdevdn=2)
            bb_width = ((bb_upper[-1] - bb_lower[-1]) / bb_middle[-1]) * 100 if len(bb_upper) > 0 else None

            # Determine regime
            regime = 'UNKNOWN'
            strength = 0

            if current_adx is not None and bb_width is not None:
                # ADX > 25 = Strong trend
                # ADX < 20 = Weak/no trend (ranging)
                if current_adx > 25:
                    regime = 'TRENDING'
                    strength = min(100, int((current_adx - 25) / 50 * 100))
                elif current_adx < 20:
                    regime = 'RANGING'
                    strength = min(100, int((20 - current_adx) / 20 * 100))
                else:
                    # Borderline case (ADX 20-25) - use BB width as tie-breaker
                    if bb_width < 2.0:  # Narrow bands = ranging
                        regime = 'RANGING'
                        strength = 50
                    else:
                        regime = 'TRENDING'
                        strength = 50

            return {
                'regime': regime,
                'strength': strength,
                'adx': float(current_adx) if current_adx else None,
                'bb_width': float(bb_width) if bb_width else None
            }

        except Exception as e:
            logger.error(f"Error detecting regime on bars: {e}")
            return {'regime': 'UNKNOWN', 'strength': 0, 'adx': None, 'bb_width': None}

    def _calculate_indicators_on_bars(self, bars: List[OHLCData]) -> List[Dict]:
        """Calculate technical indicators on historical bars"""
        import numpy as np
        import talib

        if len(bars) < 20:
            return []

        # Reverse to chronological order
        bars = list(reversed(bars))
        closes = np.array([float(bar.close) for bar in bars])
        highs = np.array([float(bar.high) for bar in bars])
        lows = np.array([float(bar.low) for bar in bars])

        signals = []

        # RSI (14) - Relaxed thresholds for backtesting - MEAN-REVERSION
        if len(closes) >= 14:
            deltas = np.diff(closes)
            gains = np.where(deltas > 0, deltas, 0)
            losses = np.where(deltas < 0, -deltas, 0)
            avg_gain = np.mean(gains[-14:])
            avg_loss = np.mean(losses[-14:])
            if avg_loss > 0:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))

                # Relaxed thresholds: 40/60 instead of 30/70
                if rsi < 40:
                    signals.append({'type': 'BUY', 'indicator': 'RSI', 'value': rsi, 'reason': f'RSI oversold ({rsi:.1f})', 'strength': 'medium', 'strategy_type': 'mean_reversion'})
                elif rsi > 60:
                    signals.append({'type': 'SELL', 'indicator': 'RSI', 'value': rsi, 'reason': f'RSI overbought ({rsi:.1f})', 'strength': 'medium', 'strategy_type': 'mean_reversion'})

        # EMA 20/50 crossover AND trend alignment - TREND-FOLLOWING
        if len(closes) >= 50:
            ema20 = self._calculate_ema(closes, 20)
            ema50 = self._calculate_ema(closes, 50)

            # Crossover signals
            if ema20[-1] > ema50[-1] and ema20[-2] <= ema50[-2]:
                signals.append({'type': 'BUY', 'indicator': 'EMA_CROSS', 'reason': 'EMA 20/50 bullish crossover', 'strength': 'medium', 'strategy_type': 'trend_following'})
            elif ema20[-1] < ema50[-1] and ema20[-2] >= ema50[-2]:
                signals.append({'type': 'SELL', 'indicator': 'EMA_CROSS', 'reason': 'EMA 20/50 bearish crossover', 'strength': 'medium', 'strategy_type': 'trend_following'})

            # Trend alignment (price above/below both EMAs)
            elif closes[-1] > ema20[-1] and closes[-1] > ema50[-1]:
                signals.append({'type': 'BUY', 'indicator': 'EMA_TREND', 'reason': 'Price above EMAs (uptrend)', 'strength': 'weak', 'strategy_type': 'trend_following'})
            elif closes[-1] < ema20[-1] and closes[-1] < ema50[-1]:
                signals.append({'type': 'SELL', 'indicator': 'EMA_TREND', 'reason': 'Price below EMAs (downtrend)', 'strength': 'weak', 'strategy_type': 'trend_following'})

        # MACD - TREND-FOLLOWING
        if len(closes) >= 26:
            ema12 = self._calculate_ema(closes, 12)
            ema26 = self._calculate_ema(closes, 26)
            macd_line = ema12 - ema26
            signal_line = self._calculate_ema(macd_line, 9)

            if macd_line[-1] > signal_line[-1] and macd_line[-2] <= signal_line[-2]:
                signals.append({'type': 'BUY', 'indicator': 'MACD', 'reason': 'MACD bullish crossover', 'strength': 'medium', 'strategy_type': 'trend_following'})
            elif macd_line[-1] < signal_line[-1] and macd_line[-2] >= signal_line[-2]:
                signals.append({'type': 'SELL', 'indicator': 'MACD', 'reason': 'MACD bearish crossover', 'strength': 'medium', 'strategy_type': 'trend_following'})

        return signals

    def _calculate_ema(self, data: np.ndarray, period: int) -> np.ndarray:
        """Calculate Exponential Moving Average"""
        import numpy as np
        ema = np.zeros_like(data)
        ema[0] = data[0]
        multiplier = 2 / (period + 1)
        for i in range(1, len(data)):
            ema[i] = (data[i] - ema[i-1]) * multiplier + ema[i-1]
        return ema

    def _recognize_patterns_on_bars(self, bars: List[OHLCData]) -> List[Dict]:
        """Recognize chart patterns on historical bars"""
        if len(bars) < 3:
            return []

        # Reverse to chronological order
        bars = list(reversed(bars))
        signals = []

        # Simple bullish/bearish engulfing pattern
        if len(bars) >= 2:
            last = bars[-1]
            prev = bars[-2]

            # Bullish engulfing
            if (float(prev.open) > float(prev.close) and  # Previous bearish
                float(last.close) > float(last.open) and  # Current bullish
                float(last.open) <= float(prev.close) and  # Opens at/below prev close
                float(last.close) >= float(prev.open)):   # Closes at/above prev open
                signals.append({
                    'type': 'BUY',
                    'pattern': 'BULLISH_ENGULFING',
                    'reason': 'Bullish engulfing pattern',
                    'reliability': 60,
                    'strength': 'medium'
                })

            # Bearish engulfing
            elif (float(prev.close) > float(prev.open) and  # Previous bullish
                  float(last.open) > float(last.close) and  # Current bearish
                  float(last.open) >= float(prev.close) and  # Opens at/above prev close
                  float(last.close) <= float(prev.open)):   # Closes at/below prev open
                signals.append({
                    'type': 'SELL',
                    'pattern': 'BEARISH_ENGULFING',
                    'reason': 'Bearish engulfing pattern',
                    'reliability': 60,
                    'strength': 'medium'
                })

        return signals

    def _filter_signals_by_regime(self, signals: List[Dict], regime: str) -> List[Dict]:
        """
        Filter signals based on market regime to avoid conflicting strategies
        Same logic as TechnicalIndicators._filter_by_regime()
        """
        if regime == 'UNKNOWN':
            # If regime unclear, keep all signals
            return signals

        filtered = []

        for sig in signals:
            strategy_type = sig.get('strategy_type', 'neutral')

            if regime == 'TRENDING':
                # In trending markets: prioritize trend-following, exclude mean-reversion
                if strategy_type in ['trend_following', 'neutral']:
                    filtered.append(sig)
            elif regime == 'RANGING':
                # In ranging markets: prioritize mean-reversion, exclude trend-following
                if strategy_type in ['mean_reversion', 'neutral']:
                    filtered.append(sig)

        return filtered

    def _aggregate_signals(
        self,
        pattern_signals: List[Dict],
        indicator_signals: List[Dict],
        symbol: str,
        timeframe: str,
        regime_info: Dict
    ) -> Optional[Dict]:
        """
        Aggregate pattern and indicator signals with regime filtering
        EXACT same logic as SignalGenerator._aggregate_signals() + TechnicalIndicators regime filtering
        """
        # Filter signals by market regime
        regime = regime_info.get('regime', 'UNKNOWN')
        strength = regime_info.get('strength', 0)

        # Filter indicator signals based on regime
        filtered_indicator_signals = self._filter_signals_by_regime(indicator_signals, regime)

        # Log regime filtering
        if len(indicator_signals) != len(filtered_indicator_signals):
            logger.info(f"{symbol} {timeframe} Market: {regime} ({strength}%) - Signals: {len(indicator_signals)} total, {len(filtered_indicator_signals)} after regime filter")

        # Count BUY and SELL signals
        buy_signals = []
        sell_signals = []

        for sig in pattern_signals:
            if sig['type'] == 'BUY':
                buy_signals.append(sig)
            elif sig['type'] == 'SELL':
                sell_signals.append(sig)

        for sig in filtered_indicator_signals:
            if sig['type'] == 'BUY':
                buy_signals.append(sig)
            elif sig['type'] == 'SELL':
                sell_signals.append(sig)

        # Determine dominant signal
        signal_type = None
        if len(buy_signals) > len(sell_signals):
            signal_type = 'BUY'
            signals = buy_signals
        elif len(sell_signals) > len(buy_signals):
            signal_type = 'SELL'
            signals = sell_signals
        else:
            # Conflicting signals - no clear direction
            return None

        # Calculate confidence score (using backtest scorer)
        confidence = self._calculate_confidence(
            signals,
            pattern_signals,
            indicator_signals,
            symbol,
            timeframe
        )

        # Collect reasons
        reasons = [sig['reason'] for sig in signals]

        # Collect patterns
        patterns_detected = [
            sig['pattern'] for sig in pattern_signals
            if sig['type'] == signal_type
        ]

        # Collect indicators
        indicators_used = {
            sig['indicator']: sig.get('value', True)
            for sig in indicator_signals
            if sig['type'] == signal_type
        }

        return {
            'symbol': symbol,
            'timeframe': timeframe,
            'signal_type': signal_type,
            'confidence': confidence,
            'reasons': reasons,
            'patterns_detected': patterns_detected,
            'indicators_used': indicators_used,
            'signal_count': len(signals)
        }

    def _calculate_confidence(
        self,
        signals: List[Dict],
        pattern_signals: List[Dict],
        indicator_signals: List[Dict],
        symbol: str,
        timeframe: str
    ) -> float:
        """
        Calculate confidence score (0-100) using backtest-specific scores
        Uses ISOLATED BacktestScorer (does NOT affect live scores)
        Same formula as SignalGenerator but with dynamic weights
        """
        # Pattern reliability score (0-30)
        pattern_score = 0
        if pattern_signals:
            avg_reliability = sum(
                sig.get('reliability', 50) for sig in pattern_signals
            ) / len(pattern_signals)
            pattern_score = (avg_reliability / 100) * 30

        # Indicator confluence score (0-40) - NOW WEIGHTED BY BACKTEST SCORES
        indicator_score = 0
        if indicator_signals:
            # Get backtest scorer for this symbol/timeframe
            scorer_key = f"{symbol}_{timeframe}"
            scorer = self.scorers.get(scorer_key)

            if scorer:
                # Get weights for each indicator
                total_weight = 0
                weighted_score = 0

                for sig in indicator_signals:
                    indicator_name = sig.get('indicator', 'UNKNOWN')
                    weight = scorer.get_indicator_weight(indicator_name)

                    # Strength contribution (strong=10, medium=6, weak=3)
                    strength_map = {'strong': 10, 'medium': 6, 'weak': 3}
                    strength_value = strength_map.get(sig.get('strength', 'weak'), 3)

                    # Weighted contribution
                    weighted_score += strength_value * weight
                    total_weight += weight

                # Normalize to 0-40 range
                if total_weight > 0:
                    # Average weighted score
                    avg_weighted = weighted_score / total_weight

                    # Scale to 0-40 (assuming max strength_value is 10)
                    indicator_score = (avg_weighted / 10) * 40

                    # Bonus for multiple indicators agreeing (confluence)
                    confluence_bonus = min(10, len(indicator_signals) * 2)
                    indicator_score = min(40, indicator_score + confluence_bonus)

                # ADX bonus
                adx_signal = next((sig for sig in indicator_signals if sig.get('indicator') == 'ADX'), None)
                if adx_signal and 'Strong Trend' in adx_signal.get('reason', ''):
                    indicator_score = min(40, indicator_score + 3)

                # OBV bonus
                obv_signal = next((sig for sig in indicator_signals if sig.get('indicator') == 'OBV'), None)
                if obv_signal and 'Divergence' in obv_signal.get('reason', ''):
                    indicator_score = min(40, indicator_score + 2)

        # Signal strength score (0-30)
        strength_map = {'strong': 30, 'medium': 20, 'weak': 10}
        strength_scores = [
            strength_map.get(sig.get('strength', 'weak'), 10)
            for sig in signals
        ]
        strength_score = sum(strength_scores) / len(strength_scores) if strength_scores else 10

        # Total confidence
        confidence = pattern_score + indicator_score + strength_score

        return round(min(100, confidence), 2)

    def _calculate_entry_sl_tp_backtest(self, signal: Dict, current_time: datetime) -> tuple:
        """
        Calculate Entry, SL, TP for backtest
        Uses OHLC close price at current_time (no tick data in backtest)
        """
        try:
            # Get latest OHLC bar BEFORE current_time from CACHE
            bars = self._get_cached_bars(signal['symbol'], signal['timeframe'], current_time, 1)

            if not bars:
                return (0, 0, 0)

            latest_bar = bars[0]

            # Use close price as entry
            entry = float(latest_bar.close)

            # Calculate ATR on historical bars for volatility-based SL/TP from CACHE
            historical_bars = self._get_cached_bars(signal['symbol'], signal['timeframe'], current_time, 14)

            if len(historical_bars) >= 14:
                # Calculate ATR (14-period Average True Range)
                bars = list(reversed(historical_bars))
                true_ranges = []
                for i in range(1, len(bars)):
                    high = float(bars[i].high)
                    low = float(bars[i].low)
                    prev_close = float(bars[i-1].close)
                    tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
                    true_ranges.append(tr)
                atr = sum(true_ranges) / len(true_ranges) if true_ranges else (entry * 0.002)
            else:
                atr = entry * 0.002  # 0.2% fallback

            # Calculate SL and TP (same as SignalGenerator)
            if signal['signal_type'] == 'BUY':
                sl = entry - (1.5 * atr)
                tp = entry + (2.5 * atr)
            else:  # SELL
                sl = entry + (1.5 * atr)
                tp = entry - (2.5 * atr)

            return (
                round(entry, 5),
                round(sl, 5),
                round(tp, 5)
            )

        except Exception as e:
            logger.error(f"Error calculating entry/SL/TP for backtest: {e}")
            return (0, 0, 0)

    def execute_signal(self, signal: Dict, current_time: datetime):
        """Execute a trade based on signal"""

        # Check if we already have an open position for this symbol
        symbol = signal['symbol']
        if any(pos['symbol'] == symbol for pos in self.open_positions):
            logger.debug(f"Already have open position for {symbol}, skipping signal")
            return

        # Check cooldown after SL hit (1 hour cooldown to prevent immediate re-entry into bad trades)
        if symbol in self.symbol_cooldowns:
            cooldown_until = self.symbol_cooldowns[symbol]
            if current_time < cooldown_until:
                logger.debug(f"{symbol} in cooldown until {cooldown_until}, skipping signal")
                return

        # Check position limits
        if len(self.open_positions) >= self.backtest_run.max_positions:
            logger.debug(f"Max positions reached ({self.backtest_run.max_positions}), skipping signal")
            return

        # Calculate position size
        volume = self.calculate_position_size(signal)

        if volume < 0.01:
            logger.debug(f"Position size too small ({volume}), skipping")
            return

        # Build entry reason from signal
        entry_reasons = []
        if signal.get('reasons'):
            entry_reasons.extend(signal['reasons'])
        if signal.get('patterns_detected'):
            entry_reasons.extend([f"Pattern: {p}" for p in signal['patterns_detected']])
        entry_reason_str = ', '.join(entry_reasons) if entry_reasons else 'Signal generated'

        # Create virtual position
        position = {
            'symbol': signal['symbol'],
            'timeframe': signal['timeframe'],
            'direction': signal['signal_type'],
            'volume': volume,
            'entry_time': current_time,
            'entry_price': signal['entry_price'],
            'entry_reason': entry_reason_str,
            'sl': signal['sl'],
            'tp': signal['tp'],
            'confidence': signal.get('confidence', 0),
            'signal_id': signal.get('id'),
            'indicators_used': signal.get('indicators_used', {}),  # Store for score updates
            'trailing_stop': False  # Will be updated when Phase 3 is implemented
        }

        self.open_positions.append(position)
        logger.info(f"📈 Opened {signal['signal_type']} {signal['symbol']} @ {signal['entry_price']} (Vol: {volume})")

    def calculate_position_size(self, signal: Dict) -> float:
        """
        Calculate position size in LOTS based on risk management.

        CRITICAL: Validates all inputs to prevent division by zero and invalid calculations.
        """
        symbol = signal.get('symbol', '')

        # Define contract specifications per symbol
        # contract_size = how many units in 1 lot
        contract_specs = {
            'EURUSD': {'contract_size': 100000},  # 1 lot = 100,000 EUR
            'GBPUSD': {'contract_size': 100000},
            'USDJPY': {'contract_size': 100000},
            'XAUUSD': {'contract_size': 100},     # 1 lot = 100 oz
            'BTCUSD': {'contract_size': 1},       # 1 lot = 1 BTC
            'DE40.c': {'contract_size': 1},       # 1 lot = 1 contract
        }

        # Default to Forex major pair
        spec = contract_specs.get(symbol, {'contract_size': 100000})

        # CRITICAL VALIDATION: Check contract size
        if spec['contract_size'] <= 0:
            logger.error(f"Invalid contract size for {symbol}: {spec['contract_size']}, using fallback")
            return 0.01

        # CRITICAL VALIDATION: Check balance
        if self.balance <= 0:
            logger.error(f"Invalid balance: {self.balance}, using minimum lot size")
            return 0.01

        # Risk-based sizing
        if signal.get('sl') and signal.get('entry_price'):
            entry_price = float(signal['entry_price'])
            sl_price = float(signal['sl'])

            # CRITICAL VALIDATION: Check entry price
            if entry_price <= 0:
                logger.warning(f"Invalid entry price: {entry_price}, using fallback sizing")
                return 0.01

            sl_distance = abs(entry_price - sl_price)

            # CRITICAL VALIDATION: Check SL distance
            if sl_distance <= 0:
                logger.warning(f"Invalid SL distance for {symbol}: {sl_distance} (Entry: {entry_price}, SL: {sl_price})")
                return 0.01

            # SL distance sanity check - must be at least 0.1% of price
            min_sl_distance = entry_price * 0.001  # 0.1%
            if sl_distance < min_sl_distance:
                logger.warning(f"SL too tight for {symbol}: {sl_distance} < {min_sl_distance}, using minimum lot")
                return 0.01

            risk_amount = self.balance * 0.02  # Risk 2% per trade

            # Calculate lot size using direct formula:
            # Profit/Loss = (Exit - Entry) * Lot_Size * Contract_Size
            # For SL: risk_amount = sl_distance * lot_size * contract_size
            # Therefore: lot_size = risk_amount / (sl_distance * contract_size)

            denominator = sl_distance * spec['contract_size']

            # FINAL VALIDATION: Check denominator
            if denominator <= 0:
                logger.error(f"Invalid denominator: {denominator} (SL distance: {sl_distance}, Contract: {spec['contract_size']})")
                return 0.01

            lot_size = risk_amount / denominator

            # Limit lot size to reasonable range
            # Min: 0.01, Max: 10% of balance in lots (scales with balance)
            max_lot_size = max(1.0, (self.balance / 1000) * 1.0)  # Scale with balance
            lot_size = max(0.01, min(lot_size, max_lot_size))

            # Final sanity check
            if lot_size <= 0 or lot_size > 100:
                logger.error(f"Calculated lot size out of range: {lot_size}, using fallback")
                return 0.01

            return round(lot_size, 2)

        # Fallback to fixed percentage
        entry_price = float(signal.get('entry_price', 0))

        # VALIDATION: Check entry price for fallback
        if entry_price <= 0:
            logger.error(f"Invalid entry price in fallback: {entry_price}")
            return 0.01

        position_value = self.balance * float(self.backtest_run.position_size_percent)
        denominator = entry_price * spec['contract_size']

        # VALIDATION: Check denominator for fallback
        if denominator <= 0:
            logger.error(f"Invalid denominator in fallback: {denominator}")
            return 0.01

        lot_size = position_value / denominator
        max_lot_size = max(1.0, (self.balance / 1000) * 1.0)

        final_lot_size = max(0.01, min(lot_size, max_lot_size))

        # Final validation
        if final_lot_size <= 0 or final_lot_size > 100:
            logger.error(f"Final lot size out of range: {final_lot_size}, using minimum")
            return 0.01

        return round(final_lot_size, 2)

    def update_open_positions(self, current_time: datetime):
        """Check if any open positions hit TP/SL using REALISTIC intra-bar movement"""

        # Get current prices for all open positions
        for position in list(self.open_positions):
            # Get price at current_time (OHLC bar)
            price_data = self.get_price_at_time(
                position['symbol'],
                current_time
            )

            if not price_data:
                continue

            # REALISTIC INTRA-BAR CHECK:
            # Check High/Low to determine what was hit FIRST (no future knowledge)
            exit_reason = None
            exit_price = None

            if position['direction'] == 'BUY':
                # For BUY: Check if Low hit SL OR High hit TP
                sl_hit = position['sl'] and price_data['low'] <= position['sl']
                tp_hit = position['tp'] and price_data['high'] >= position['tp']

                if sl_hit and tp_hit:
                    # BOTH hit in same bar - which came FIRST?
                    # Conservative assumption: SL is hit first (worst case)
                    exit_reason = 'SL_HIT'
                    exit_price = position['sl']
                elif sl_hit:
                    exit_reason = 'SL_HIT'
                    exit_price = position['sl']
                elif tp_hit:
                    exit_reason = 'TP_HIT'
                    exit_price = position['tp']

            else:  # SELL
                # For SELL: Check if High hit SL OR Low hit TP
                sl_hit = position['sl'] and price_data['high'] >= position['sl']
                tp_hit = position['tp'] and price_data['low'] <= position['tp']

                if sl_hit and tp_hit:
                    # BOTH hit in same bar - which came FIRST?
                    # Conservative assumption: SL is hit first (worst case)
                    exit_reason = 'SL_HIT'
                    exit_price = position['sl']
                elif sl_hit:
                    exit_reason = 'SL_HIT'
                    exit_price = position['sl']
                elif tp_hit:
                    exit_reason = 'TP_HIT'
                    exit_price = position['tp']

            if exit_reason:
                self.close_position(position, current_time, exit_price, exit_reason)

    def close_position(self, position: Dict, exit_time: datetime, exit_price: float, reason: str):
        """Close a position and record the trade"""

        # Get contract specs for this symbol
        symbol = position['symbol']

        # Calculate profit - different formula per symbol type
        price_diff = exit_price - position['entry_price']
        if position['direction'] == 'SELL':
            price_diff = -price_diff

        # Symbol-specific profit calculation (account currency = USD)
        if symbol in ['EURUSD', 'GBPUSD', 'AUDUSD', 'NZDUSD']:
            # Quote currency is USD: Profit = price_diff * lot * 100,000
            raw_profit = price_diff * position['volume'] * 100000

        elif symbol == 'USDJPY':
            # Quote currency is JPY: Need to convert to USD
            # Profit in JPY = price_diff * lot * 100,000
            # Profit in USD = Profit_JPY / exit_price
            raw_profit = (price_diff * position['volume'] * 100000) / exit_price

        elif symbol == 'XAUUSD':
            # Gold: 1 lot = 100 oz, quote is USD
            raw_profit = price_diff * position['volume'] * 100

        elif symbol == 'BTCUSD':
            # Bitcoin: 1 lot = 1 BTC, quote is USD
            raw_profit = price_diff * position['volume'] * 1

        else:
            # Default: assume major forex pair with USD quote
            raw_profit = price_diff * position['volume'] * 100000

        # Calculate trading costs (commission + slippage)
        commission_cost = self.calculate_commission(symbol, position['volume'])
        slippage_cost = self.calculate_slippage(symbol, position['volume'])
        total_trading_costs = commission_cost + slippage_cost

        # Final profit after costs
        profit = raw_profit - total_trading_costs

        # Update balance
        self.balance += profit

        # Calculate duration
        duration = (exit_time - position['entry_time']).total_seconds() / 60  # minutes

        # Create backtest trade record
        trade = BacktestTrade(
            backtest_run_id=self.backtest_run_id,
            signal_id=position.get('signal_id'),
            symbol=position['symbol'],
            timeframe=position['timeframe'],
            direction=position['direction'],
            volume=position['volume'],
            entry_time=position['entry_time'],
            entry_price=position['entry_price'],
            entry_reason=position.get('entry_reason', 'Signal generated'),
            sl=position['sl'],
            tp=position['tp'],
            exit_time=exit_time,
            exit_price=exit_price,
            exit_reason=reason,
            profit=round(profit, 2),
            profit_percent=round(profit / (position['entry_price'] * position['volume']) * 100, 4),
            duration_minutes=int(duration),
            signal_confidence=position.get('confidence'),
            trailing_stop_used=position.get('trailing_stop', False)
        )

        self.db.add(trade)
        self.db.commit()

        self.closed_trades.append(trade)
        self.open_positions.remove(position)

        # Update backtest indicator scores (ISOLATED - does NOT affect live)
        if position.get('indicators_used'):
            scorer_key = f"{position['symbol']}_{position['timeframe']}"
            scorer = self.scorers.get(scorer_key)

            if scorer:
                was_profitable = profit > 0
                scorer.update_multiple_scores(
                    position['indicators_used'],
                    was_profitable,
                    profit
                )

        # Set cooldown after trade to prevent immediate re-entry
        # Use longer cooldown for SL hits, shorter for TP hits
        if reason == 'SL_HIT' and self.settings.sl_cooldown_minutes > 0:
            cooldown_duration = timedelta(minutes=self.settings.sl_cooldown_minutes)
            self.symbol_cooldowns[symbol] = exit_time + cooldown_duration
            logger.info(f"📊 Closed {position['direction']} {position['symbol']} @ {exit_price} | Profit: ${profit:.2f} | Reason: {reason} | Cooldown until {self.symbol_cooldowns[symbol]}")
        else:
            # Apply minimum 15-minute cooldown after ANY trade to prevent rapid re-entry
            cooldown_duration = timedelta(minutes=15)
            self.symbol_cooldowns[symbol] = exit_time + cooldown_duration
            logger.info(f"📊 Closed {position['direction']} {position['symbol']} @ {exit_price} | Profit: ${profit:.2f} | Reason: {reason} | Cooldown: 15 min")

    def close_all_positions(self, current_time: datetime, reason: str):
        """Force close all open positions"""
        for position in list(self.open_positions):
            price_data = self.get_price_at_time(position['symbol'], current_time)
            if price_data:
                self.close_position(position, current_time, price_data['close'], reason)

    def get_price_at_time(self, symbol: str, timestamp: datetime) -> Optional[Dict]:
        """Get price data at specific timestamp"""
        # Get closest OHLC bar from CACHE (using H1 for simplicity)
        bars = self._get_cached_bars(symbol, 'H1', timestamp + timedelta(seconds=1), 1)

        if bars:
            bar = bars[0]
            return {
                'open': float(bar.open),
                'high': float(bar.high),
                'low': float(bar.low),
                'close': float(bar.close)
            }
        return None

    def update_equity(self, current_time: datetime):
        """Update equity curve"""
        # Calculate current equity (balance + unrealized P&L)
        unrealized_pnl = 0.0

        for position in self.open_positions:
            price_data = self.get_price_at_time(position['symbol'], current_time)
            if price_data:
                current_price = price_data['close']
                if position['direction'] == 'BUY':
                    pnl = (current_price - position['entry_price']) * position['volume']
                else:
                    pnl = (position['entry_price'] - current_price) * position['volume']
                unrealized_pnl += pnl

        self.equity = self.balance + unrealized_pnl

        # Track drawdown
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity

        drawdown = self.peak_equity - self.equity
        if drawdown > self.max_drawdown:
            self.max_drawdown = drawdown

        self.equity_curve.append({
            'timestamp': current_time,
            'equity': self.equity,
            'balance': self.balance
        })

    def calculate_metrics(self):
        """Calculate final performance metrics"""

        if not self.closed_trades:
            logger.warning("No trades executed in backtest")
            self.backtest_run.total_trades = 0
            return

        total_trades = len(self.closed_trades)
        winning_trades = [t for t in self.closed_trades if t.profit > 0]
        losing_trades = [t for t in self.closed_trades if t.profit < 0]

        total_profit = sum(t.profit for t in winning_trades) if winning_trades else 0
        total_loss = abs(sum(t.profit for t in losing_trades)) if losing_trades else 0

        win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0
        profit_factor = total_profit / total_loss if total_loss > 0 else (total_profit if total_profit > 0 else 0)

        # Sharpe Ratio (simplified)
        if len(self.equity_curve) > 1:
            returns = [(self.equity_curve[i]['equity'] - self.equity_curve[i-1]['equity']) / self.equity_curve[i-1]['equity']
                       for i in range(1, len(self.equity_curve))]
            avg_return = sum(returns) / len(returns) if returns else 0
            std_return = (sum((r - avg_return) ** 2 for r in returns) / len(returns)) ** 0.5 if returns else 1
            sharpe_ratio = (avg_return / std_return) * (252 ** 0.5) if std_return > 0 else 0  # Annualized
        else:
            sharpe_ratio = 0

        # Update backtest run with results
        self.backtest_run.final_balance = self.balance
        self.backtest_run.total_trades = total_trades
        self.backtest_run.winning_trades = len(winning_trades)
        self.backtest_run.losing_trades = len(losing_trades)
        self.backtest_run.win_rate = round(win_rate, 4)
        self.backtest_run.profit_factor = round(profit_factor, 4)
        self.backtest_run.total_profit = round(total_profit, 2)
        self.backtest_run.total_loss = round(total_loss, 2)
        self.backtest_run.max_drawdown = round(self.max_drawdown, 2)
        self.backtest_run.max_drawdown_percent = round(self.max_drawdown / self.initial_balance, 4) if self.initial_balance > 0 else 0
        self.backtest_run.sharpe_ratio = round(sharpe_ratio, 4)

        logger.info(f"📈 Final Results:")
        logger.info(f"   Total Trades: {total_trades}")
        logger.info(f"   Win Rate: {win_rate:.2%}")
        logger.info(f"   Profit Factor: {profit_factor:.2f}")
        logger.info(f"   Net Profit: ${self.balance - self.initial_balance:.2f}")
        logger.info(f"   Max Drawdown: ${self.max_drawdown:.2f} ({self.backtest_run.max_drawdown_percent:.2%})")
        logger.info(f"   Sharpe Ratio: {sharpe_ratio:.2f}")

    def export_learned_scores(self):
        """
        Export indicator scores learned during backtest
        Saves to backtest_run.learned_scores (JSONB field)
        These can be used as recommendations for live system
        """
        learned_scores = {}

        for key, scorer in self.scorers.items():
            symbol, timeframe = key.split('_')

            # Get score summary
            summary = scorer.get_score_summary()

            # Filter only indicators with enough data (min 5 signals)
            significant_scores = [s for s in summary if s['total_signals'] >= 5]

            if significant_scores:
                if symbol not in learned_scores:
                    learned_scores[symbol] = {}

                learned_scores[symbol][timeframe] = significant_scores

                logger.info(
                    f"📊 Learned scores for {symbol} {timeframe}: "
                    f"{len(significant_scores)} indicators with 5+ signals"
                )

        # Save to backtest_run
        self.backtest_run.learned_scores = learned_scores

        logger.info(f"✅ Exported learned scores for {len(learned_scores)} symbols")

    def save_results(self):
        """Save final results to database"""
        # Use direct SQL update to ensure status is set correctly
        self.db.execute(
            BacktestRun.__table__.update()
            .where(BacktestRun.id == self.backtest_run_id)
            .values(status='completed', completed_at=datetime.utcnow())
        )
        self.db.commit()
        logger.info(f"✅ Results saved to database")


def run_backtest(backtest_run_id: int):
    """Run a backtest by ID"""
    engine = BacktestingEngine(backtest_run_id)
    engine.run()
    return engine.backtest_run


if __name__ == '__main__':
    # Example usage
    import sys
    if len(sys.argv) > 1:
        run_id = int(sys.argv[1])
        run_backtest(run_id)
    else:
        print("Usage: python backtesting_engine.py <backtest_run_id>")
