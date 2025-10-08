#!/usr/bin/env python3
"""
Auto-Trading Engine for ngTradingBot
Automatically executes trades based on trading signals
"""

import logging
import time
import uuid
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_
from database import ScopedSession
from models import TradingSignal, Trade, Account, Command
from redis_client import get_redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class AutoTrader:
    """Automated trading based on signals"""

    def __init__(self):
        self.redis = get_redis()
        self.enabled = True  # ✅ ENABLED BY DEFAULT as requested
        self.check_interval = 10  # Check for new signals every 10 seconds

        # Track processed signals
        self.processed_signals = set()

        # Cooldown tracking after SL hits: symbol -> cooldown_until_time
        self.symbol_cooldowns = {}

        # ✅ Auto-trade minimum confidence: 60% DEFAULT (as requested by user)
        # This is the threshold for automatic trade execution
        self.min_autotrade_confidence = 60.0  # Default 60%

        # Circuit breaker settings
        self.circuit_breaker_enabled = True
        self.max_daily_loss_percent = 5.0  # Stop trading if daily loss exceeds 5%
        self.max_total_drawdown_percent = 20.0  # Stop if total drawdown exceeds 20%
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = None

        # Correlation limits - prevent over-exposure to correlated pairs
        self.max_correlated_positions = 2  # Max 2 positions in same currency group
        self.correlation_groups = {
            'EUR': ['EURUSD', 'EURJPY', 'EURGBP', 'EURAUD', 'EURCHF', 'EURCAD', 'EURNZD'],
            'GBP': ['GBPUSD', 'GBPJPY', 'EURGBP', 'GBPAUD', 'GBPCHF', 'GBPCAD', 'GBPNZD'],
            'JPY': ['USDJPY', 'EURJPY', 'GBPJPY', 'AUDJPY', 'CHFJPY', 'CADJPY', 'NZDJPY'],
            'AUD': ['AUDUSD', 'EURAUD', 'GBPAUD', 'AUDJPY', 'AUDCHF', 'AUDCAD', 'AUDNZD'],
            'CHF': ['USDCHF', 'EURCHF', 'GBPCHF', 'CHFJPY', 'AUDCHF', 'CADCHF', 'NZDCHF'],
            'CAD': ['USDCAD', 'EURCAD', 'GBPCAD', 'CADJPY', 'AUDCAD', 'CADCHF', 'NZDCAD'],
            'NZD': ['NZDUSD', 'EURNZD', 'GBPNZD', 'NZDJPY', 'AUDNZD', 'NZDCHF', 'NZDCAD'],
            'GOLD': ['XAUUSD', 'XAUEUR', 'XAUGBP'],
            'SILVER': ['XAGUSD', 'XAGEUR'],
            'CRYPTO': ['BTCUSD', 'ETHUSD', 'LTCUSD'],
        }

        # Settings will be loaded per-request from database
        logger.info("Auto-Trader initialized")

    def _load_settings(self, db: Session):
        """Load global settings from database"""
        from models import GlobalSettings
        return GlobalSettings.get_settings(db)

    def set_min_confidence(self, min_confidence: float):
        """Set minimum confidence threshold for auto-trading"""
        self.min_autotrade_confidence = float(min_confidence)
        logger.info(f"Auto-Trade min confidence set to {min_confidence}%")

    def enable(self):
        """Enable auto-trading"""
        self.enabled = True
        logger.info(f"🤖 Auto-Trading ENABLED (min confidence: {self.min_autotrade_confidence}%)")

    def disable(self):
        """Disable auto-trading (kill-switch)"""
        self.enabled = False
        logger.warning("🛑 Auto-Trading DISABLED (Kill-Switch)")

    def reset_circuit_breaker(self):
        """Reset circuit breaker manually"""
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = None
        logger.info("Circuit breaker reset manually")

    def check_circuit_breaker(self, db: Session, account_id: int) -> bool:
        """
        Check if circuit breaker should trip to prevent catastrophic losses.

        Circuit breaker trips if:
        1. Daily loss exceeds max_daily_loss_percent (default 5%)
        2. Total drawdown exceeds max_total_drawdown_percent (default 20%)

        Returns:
            True if safe to trade, False if circuit breaker tripped
        """
        if not self.circuit_breaker_enabled:
            return True  # Circuit breaker disabled

        if self.circuit_breaker_tripped:
            return False  # Already tripped

        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                logger.error("Account not found for circuit breaker check")
                return False

            # Check 1: Daily loss limit
            if hasattr(account, 'profit_today') and account.profit_today is not None:
                daily_loss_percent = (float(account.profit_today) / float(account.balance)) * 100

                if daily_loss_percent < -self.max_daily_loss_percent:
                    self.circuit_breaker_tripped = True
                    self.circuit_breaker_reason = f"Daily loss exceeded {self.max_daily_loss_percent}%: ${account.profit_today:.2f} ({daily_loss_percent:.2f}%)"
                    self.enabled = False

                    logger.critical(f"🚨 CIRCUIT BREAKER TRIPPED: {self.circuit_breaker_reason}")
                    logger.critical(f"🛑 Auto-trading STOPPED for safety")

                    return False

            # Check 2: Total drawdown limit
            if hasattr(account, 'initial_balance') and account.initial_balance:
                total_drawdown_percent = ((account.initial_balance - account.balance) / account.initial_balance) * 100

                if total_drawdown_percent > self.max_total_drawdown_percent:
                    self.circuit_breaker_tripped = True
                    self.circuit_breaker_reason = f"Total drawdown exceeded {self.max_total_drawdown_percent}%: ${account.initial_balance - account.balance:.2f} ({total_drawdown_percent:.2f}%)"
                    self.enabled = False

                    logger.critical(f"🚨 CIRCUIT BREAKER TRIPPED: {self.circuit_breaker_reason}")
                    logger.critical(f"🛑 Auto-trading STOPPED for safety")

                    return False

            # All checks passed
            return True

        except Exception as e:
            logger.error(f"Error in circuit breaker check: {e}", exc_info=True)
            # Fail-safe: trip breaker on error
            self.circuit_breaker_tripped = True
            self.circuit_breaker_reason = f"Circuit breaker error: {str(e)}"
            self.enabled = False
            return False

    def get_account_balance(self, db: Session, account_id: int) -> float:
        """Get current account balance"""
        account = db.query(Account).filter_by(id=account_id).first()
        return account.balance if account else 0.0

    def get_open_positions_count(self, db: Session, account_id: int) -> int:
        """Get number of open positions"""
        return db.query(Trade).filter(
            and_(
                Trade.account_id == account_id,
                Trade.status == 'open'
            )
        ).count()

    def check_correlation_exposure(self, db: Session, account_id: int, new_symbol: str) -> Dict:
        """
        Check if opening a new position would violate correlation limits.

        Prevents over-exposure to correlated currency pairs.
        For example: Don't open 3+ EUR positions (EURUSD, EURJPY, EURGBP) simultaneously.

        Args:
            db: Database session
            account_id: Account ID
            new_symbol: Symbol to check

        Returns:
            Dict with 'allowed' (bool) and 'reason' (str)
        """
        try:
            # Find which correlation group(s) this symbol belongs to
            symbol_groups = []
            for currency, symbols in self.correlation_groups.items():
                if new_symbol in symbols:
                    symbol_groups.append((currency, symbols))

            if not symbol_groups:
                # Symbol not in any correlation group - allow
                return {'allowed': True}

            # Check each group the symbol belongs to
            for currency, correlated_symbols in symbol_groups:
                # Count existing open positions in this currency group
                open_positions = db.query(Trade).filter(
                    and_(
                        Trade.account_id == account_id,
                        Trade.status == 'open',
                        Trade.symbol.in_(correlated_symbols)
                    )
                ).all()

                existing_count = len(open_positions)

                if existing_count >= self.max_correlated_positions:
                    # Already at/over correlation limit
                    existing_symbols = [p.symbol for p in open_positions]
                    return {
                        'allowed': False,
                        'reason': (
                            f'Correlation limit reached for {currency}: '
                            f'{existing_count}/{self.max_correlated_positions} positions '
                            f'({", ".join(existing_symbols)})'
                        )
                    }

            # All checks passed
            return {'allowed': True}

        except Exception as e:
            logger.error(f"Error checking correlation exposure: {e}", exc_info=True)
            # Fail-safe: block trade on error
            return {'allowed': False, 'reason': f'Correlation check error: {str(e)}'}

    def calculate_position_size(self, db: Session, account_id: int, signal: TradingSignal) -> float:
        """Calculate position size based on risk management"""
        try:
            settings = self._load_settings(db)
            balance = self.get_account_balance(db, account_id)

            # Calculate risk amount
            risk_amount = balance * float(settings.risk_per_trade_percent)

            # Calculate position size based on SL distance
            if signal.sl and signal.entry_price:
                sl_distance = abs(signal.entry_price - signal.sl)
                if sl_distance > 0:
                    # Position size = Risk Amount / SL Distance
                    volume = risk_amount / sl_distance
                    volume = round(volume, 2)  # Round to 2 decimals
                    return max(0.01, min(volume, 1.0))  # Min 0.01, Max 1.0

            # Fallback: use percentage of balance
            return round(balance * float(settings.position_size_percent) / signal.entry_price, 2)

        except Exception as e:
            logger.error(f"Error calculating position size: {e}")
            return 0.01  # Fallback to minimum

    def check_risk_limits(self, db: Session, account_id: int) -> Dict:
        """Check if risk limits are exceeded"""
        try:
            settings = self._load_settings(db)
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                return {'allowed': False, 'reason': 'Account not found'}

            balance = account.balance
            equity = account.equity

            # Check max positions
            open_positions = self.get_open_positions_count(db, account_id)
            if open_positions >= settings.max_positions:
                return {
                    'allowed': False,
                    'reason': f'Max positions reached ({settings.max_positions})'
                }

            # Check drawdown
            if equity < balance:
                drawdown_percent = (balance - equity) / balance
                if drawdown_percent > float(settings.max_drawdown_percent):
                    self.disable()  # Emergency stop
                    return {
                        'allowed': False,
                        'reason': f'Max drawdown exceeded ({drawdown_percent:.1%})'
                    }

            return {'allowed': True}

        except Exception as e:
            logger.error(f"Error checking risk limits: {e}")
            return {'allowed': False, 'reason': str(e)}

    def should_execute_signal(self, signal: TradingSignal, db: Session) -> Dict:
        """Determine if signal should be executed"""
        try:
            settings = self._load_settings(db)

            # Check DAILY DRAWDOWN PROTECTION FIRST (most critical check)
            from daily_drawdown_protection import get_drawdown_protection
            dd_protection = get_drawdown_protection(signal.account_id)
            dd_check = dd_protection.check_and_update(auto_trading_enabled=self.enabled)

            if not dd_check['allowed']:
                return {
                    'execute': False,
                    'reason': dd_check.get('reason', 'Daily drawdown limit reached')
                }

            # Check NEWS FILTER SECOND (prevent trading during high-impact news)
            from news_filter import get_news_filter
            news_filter = get_news_filter(signal.account_id)
            news_check = news_filter.check_trading_allowed(signal.symbol)

            if not news_check['allowed']:
                return {
                    'execute': False,
                    'reason': news_check.get('reason', 'Trading paused due to news')
                }

            # Check circuit breaker THIRD
            if not self.check_circuit_breaker(db, signal.account_id):
                return {
                    'execute': False,
                    'reason': f'Circuit breaker tripped: {self.circuit_breaker_reason}'
                }

            # Check correlation exposure SECOND (prevent over-exposure)
            correlation_check = self.check_correlation_exposure(db, signal.account_id, signal.symbol)
            if not correlation_check['allowed']:
                return {
                    'execute': False,
                    'reason': correlation_check['reason']
                }

            # Check per-symbol-timeframe position limit THIRD (prevent duplicate positions)
            existing_positions = db.query(Trade).filter(
                and_(
                    Trade.account_id == signal.account_id,
                    Trade.symbol == signal.symbol,
                    Trade.timeframe == signal.timeframe,
                    Trade.status == 'open'
                )
            ).count()

            if existing_positions >= settings.max_positions_per_symbol_timeframe:
                return {
                    'execute': False,
                    'reason': f'Max positions per symbol+timeframe reached: {existing_positions}/{settings.max_positions_per_symbol_timeframe} ({signal.symbol} {signal.timeframe})'
                }

            # Check signal age (don't execute old signals)
            signal_age = datetime.utcnow() - signal.created_at
            if signal_age > timedelta(minutes=settings.signal_max_age_minutes):
                return {
                    'execute': False,
                    'reason': f'Signal too old ({signal_age.seconds}s)'
                }

            # Check cooldown after SL hit (prevent revenge trading)
            if signal.symbol in self.symbol_cooldowns:
                cooldown_until = self.symbol_cooldowns[signal.symbol]
                if datetime.utcnow() < cooldown_until:
                    remaining = (cooldown_until - datetime.utcnow()).total_seconds() / 60
                    return {
                        'execute': False,
                        'reason': f'Symbol in cooldown ({remaining:.0f}min remaining)'
                    }

            # Check confidence threshold (use symbol-specific minimum if available)
            from symbol_config import get_symbol_min_confidence
            symbol_min_confidence = max(self.min_autotrade_confidence, get_symbol_min_confidence(signal.symbol))

            if signal.confidence and signal.confidence < symbol_min_confidence:
                return {
                    'execute': False,
                    'reason': f'Low confidence ({signal.confidence}% < {symbol_min_confidence}% for {signal.symbol})'
                }

            # Check if signal has required data
            if not signal.entry_price or not signal.sl or not signal.tp:
                return {
                    'execute': False,
                    'reason': 'Missing entry/SL/TP'
                }

            # Check if signal type is BUY or SELL
            if signal.signal_type not in ['BUY', 'SELL']:
                return {
                    'execute': False,
                    'reason': f'Invalid signal type: {signal.signal_type}'
                }

            return {'execute': True}

        except Exception as e:
            logger.error(f"Error evaluating signal: {e}")
            return {'execute': False, 'reason': str(e)}

    def create_trade_command(self, db: Session, signal: TradingSignal, volume: float) -> Optional[Command]:
        """
        Create trade command from signal with pre-execution spread validation

        ✅ ENHANCED: Added spread check before command creation to prevent execution at bad prices
        """
        try:
            # ✅ FIX #3: Pre-execution spread check
            spread_check = self._validate_spread_before_execution(db, signal)
            if not spread_check['allowed']:
                logger.warning(
                    f"⚠️  Pre-execution spread check FAILED for {signal.symbol}: {spread_check['reason']}"
                )
                return None

            command_id = f"auto_{uuid.uuid4().hex[:8]}"

            # Apply symbol-specific SL multiplier OR use SuperTrend for dynamic SL
            from symbol_config import get_symbol_sl_multiplier
            sl_multiplier = get_symbol_sl_multiplier(signal.symbol)

            # Try to get SuperTrend-based dynamic SL for better risk management
            adjusted_sl = signal.sl
            use_supertrend_sl = False

            try:
                from technical_indicators import TechnicalIndicators
                ti = TechnicalIndicators(signal.account_id, signal.symbol, signal.timeframe)
                supertrend = ti.calculate_supertrend()

                if supertrend and supertrend['value']:
                    # Use SuperTrend as dynamic SL (better than fixed distance)
                    if signal.signal_type == 'BUY' and supertrend['direction'] == 'bullish':
                        # For BUY: Use SuperTrend value as SL (price below SuperTrend = exit)
                        adjusted_sl = supertrend['value']
                        use_supertrend_sl = True
                        logger.info(f"🎯 {signal.symbol}: Using SuperTrend SL | Price: {signal.entry_price} | SuperTrend SL: {adjusted_sl:.5f} ({supertrend['distance_pct']:.2f}% distance)")
                    elif signal.signal_type == 'SELL' and supertrend['direction'] == 'bearish':
                        # For SELL: Use SuperTrend value as SL (price above SuperTrend = exit)
                        adjusted_sl = supertrend['value']
                        use_supertrend_sl = True
                        logger.info(f"🎯 {signal.symbol}: Using SuperTrend SL | Price: {signal.entry_price} | SuperTrend SL: {adjusted_sl:.5f} ({supertrend['distance_pct']:.2f}% distance)")
            except Exception as e:
                logger.debug(f"SuperTrend SL calculation failed for {signal.symbol}, using traditional SL: {e}")

            # Fallback to symbol-specific multiplier if SuperTrend not available
            if not use_supertrend_sl:
                if sl_multiplier != 1.0 and signal.entry_price and signal.sl:
                    sl_distance = abs(signal.entry_price - signal.sl)
                    adjusted_sl_distance = sl_distance * sl_multiplier

                    if signal.signal_type == 'BUY':
                        adjusted_sl = signal.entry_price - adjusted_sl_distance
                    else:  # SELL
                        adjusted_sl = signal.entry_price + adjusted_sl_distance

                    logger.info(f"📊 {signal.symbol}: Adjusted SL with multiplier {sl_multiplier} | Original: {signal.sl} → Adjusted: {adjusted_sl:.5f}")

            # Store signal_id and timeframe in payload for trade linking
            payload_data = {
                'symbol': signal.symbol,
                'order_type': signal.signal_type,  # BUY or SELL
                'volume': volume,
                'sl': adjusted_sl,  # Use adjusted SL
                'tp': signal.tp,
                'comment': f"Auto-Trade Signal #{signal.id} ({signal.timeframe})",
                'signal_id': signal.id,  # IMPORTANT: Link to signal
                'timeframe': signal.timeframe  # IMPORTANT: Store timeframe for limiting
            }

            command = Command(
                id=command_id,
                account_id=signal.account_id,
                command_type='OPEN_TRADE',
                payload=payload_data,
                status='pending',
                created_at=datetime.utcnow()
            )

            db.add(command)
            db.commit()

            # Push to Redis command queue
            command_data = {
                'id': command_id,
                'type': 'OPEN_TRADE',
                'symbol': signal.symbol,
                'order_type': signal.signal_type,
                'volume': volume,
                'sl': signal.sl,
                'tp': signal.tp,
                'comment': payload_data['comment']
            }

            self.redis.push_command(signal.account_id, command_data)

            logger.info(f"✅ Trade command created: {command_id} - {signal.signal_type} {volume} {signal.symbol} @ {signal.entry_price}")

            # Store command ID for execution tracking
            if not hasattr(self, 'pending_commands'):
                self.pending_commands = {}
            self.pending_commands[command_id] = {
                'signal_id': signal.id,
                'symbol': signal.symbol,
                'created_at': datetime.utcnow(),
                'timeout_at': datetime.utcnow() + timedelta(minutes=5)
            }

            return command

        except Exception as e:
            logger.error(f"Error creating trade command: {e}")
            db.rollback()
            return None

    def process_new_signals(self, db: Session):
        """Process new trading signals"""
        try:
            # Get recent unprocessed signals
            cutoff_time = datetime.utcnow() - timedelta(minutes=10)

            signals = db.query(TradingSignal).filter(
                and_(
                    TradingSignal.created_at >= cutoff_time,
                    TradingSignal.signal_type.in_(['BUY', 'SELL'])
                )
            ).order_by(TradingSignal.created_at.desc()).all()

            logger.info(f"🔍 Auto-trader found {len(signals)} signals in last 10 minutes, {len(self.processed_signals)} already processed")

            for signal in signals:
                # Skip already processed signals
                if signal.id in self.processed_signals:
                    continue

                # Mark as processed
                self.processed_signals.add(signal.id)

                # Check if should execute
                should_exec = self.should_execute_signal(signal, db)
                if not should_exec['execute']:
                    logger.info(f"⏭️  Skipping signal #{signal.id} ({signal.symbol} {signal.timeframe}): {should_exec['reason']}")

                    # Check if symbol is disabled - create shadow trade
                    from models import SymbolPerformanceTracking
                    perf = db.query(SymbolPerformanceTracking).filter(
                        SymbolPerformanceTracking.account_id == signal.account_id,
                        SymbolPerformanceTracking.symbol == signal.symbol,
                        SymbolPerformanceTracking.status == 'disabled'
                    ).order_by(SymbolPerformanceTracking.evaluation_date.desc()).first()

                    if perf and perf.status == 'disabled':
                        # Symbol is disabled - create shadow trade to monitor recovery
                        from shadow_trading_engine import get_shadow_trading_engine
                        shadow_engine = get_shadow_trading_engine()
                        shadow_trade = shadow_engine.process_signal_for_disabled_symbol(signal)
                        if shadow_trade:
                            logger.info(f"🌑 Shadow trade created for disabled symbol {signal.symbol}")

                    continue

                # Check risk limits
                risk_check = self.check_risk_limits(db, signal.account_id)
                if not risk_check['allowed']:
                    logger.warning(f"⚠️  Risk limit blocked signal #{signal.id}: {risk_check['reason']}")
                    continue

                # Calculate position size
                volume = self.calculate_position_size(db, signal.account_id, signal)

                # Create trade command
                command = self.create_trade_command(db, signal, volume)

                if command:
                    logger.info(f"🚀 Auto-Trade executed: Signal #{signal.id} → Command {command.id}")

        except Exception as e:
            logger.error(f"Error processing signals: {e}")

    def cleanup_processed_signals(self):
        """
        Clean up old processed signal IDs to prevent unbounded memory growth.

        Keeps last 500 IDs when threshold (1000) is reached.
        Runs every auto-trade iteration (every 10 seconds).
        """
        # Processed signals: Limit to 1000 entries
        if len(self.processed_signals) > 1000:
            # Convert to sorted list, keep last 500
            sorted_ids = sorted(list(self.processed_signals))
            self.processed_signals = set(sorted_ids[-500:])
            logger.debug(f"🧹 Cleaned up processed_signals: {len(sorted_ids)} → 500")

    def cleanup_expired_cooldowns(self):
        """
        Clean up expired symbol cooldowns to prevent memory growth.

        Removes cooldowns that have already expired.
        """
        from datetime import datetime
        now = datetime.utcnow()

        expired_symbols = []
        for symbol, cooldown_until in self.symbol_cooldowns.items():
            if cooldown_until < now:
                expired_symbols.append(symbol)

        if expired_symbols:
            for symbol in expired_symbols:
                del self.symbol_cooldowns[symbol]
            logger.debug(f"🧹 Cleaned up {len(expired_symbols)} expired cooldowns")

    def check_pending_commands(self, db: Session):
        """
        ✅ ENHANCED: Check if pending trade commands were executed by MT5.

        Verifies that commands sent to MT5 actually resulted in trades.
        Implements retry logic and alerts for failed commands.
        """
        if not hasattr(self, 'pending_commands'):
            self.pending_commands = {}
            return

        if not hasattr(self, 'failed_command_count'):
            self.failed_command_count = 0

        now = datetime.utcnow()
        commands_to_remove = []
        commands_to_retry = []

        for command_id, cmd_data in self.pending_commands.items():
            # Check if command resulted in a trade
            trade = db.query(Trade).filter_by(
                command_id=command_id
            ).first()

            if trade:
                # ✅ Command was executed successfully
                commands_to_remove.append(command_id)
                logger.info(f"✅ Command {command_id} executed successfully: ticket #{trade.ticket} ({cmd_data['symbol']})")

                # Reset failed count on success
                if self.failed_command_count > 0:
                    self.failed_command_count = max(0, self.failed_command_count - 1)

            elif now > cmd_data['timeout_at']:
                # ⚠️ Command timed out without execution
                commands_to_remove.append(command_id)

                # Check command status in database
                command = db.query(Command).filter_by(id=command_id).first()

                if command:
                    if command.status == 'failed':
                        # ❌ Command explicitly failed
                        error_msg = command.response.get('error', 'Unknown error') if command.response else 'No error details'
                        logger.error(
                            f"❌ Command {command_id} FAILED: {cmd_data['symbol']} - {error_msg}"
                        )
                        self.failed_command_count += 1

                        # Check if we should retry (only if error is retriable)
                        retry_count = cmd_data.get('retry_count', 0)
                        if retry_count < 2 and self._is_retriable_error(error_msg):
                            commands_to_retry.append((command_id, cmd_data, error_msg))
                            logger.info(f"🔄 Scheduling retry #{retry_count + 1} for command {command_id}")

                    elif command.status == 'pending':
                        # ⚠️ Command still pending after timeout - likely MT5 connection issue
                        logger.warning(
                            f"⚠️  Command {command_id} TIMEOUT (still pending): {cmd_data['symbol']} "
                            f"(sent {(now - cmd_data['created_at']).seconds}s ago) - "
                            f"MT5 may not be connected!"
                        )
                        self.failed_command_count += 1
                else:
                    # ⚠️ Command not found in database (shouldn't happen)
                    logger.error(f"❌ Command {command_id} not found in database!")

                # Critical alert if many commands are failing
                if self.failed_command_count >= 3:
                    logger.critical(
                        f"🚨 CRITICAL: {self.failed_command_count} consecutive command failures! "
                        f"MT5 connection may be down. Disabling auto-trading."
                    )
                    self.disable()
                    self.circuit_breaker_tripped = True
                    self.circuit_breaker_reason = f"{self.failed_command_count} consecutive command failures"

        # Clean up processed/timeout commands
        for cmd_id in commands_to_remove:
            del self.pending_commands[cmd_id]

        # Retry failed commands if applicable
        for command_id, cmd_data, error_msg in commands_to_retry:
            logger.info(f"🔄 Retrying command {command_id} for {cmd_data['symbol']} (previous error: {error_msg})")
            # Increment retry count
            cmd_data['retry_count'] = cmd_data.get('retry_count', 0) + 1
            cmd_data['timeout_at'] = datetime.utcnow() + timedelta(minutes=5)
            # Re-add to pending commands
            self.pending_commands[command_id] = cmd_data

        if commands_to_remove:
            logger.debug(f"🧹 Cleaned up {len(commands_to_remove)} pending commands")

    def _is_retriable_error(self, error_msg: str) -> bool:
        """Check if error is retriable (e.g., temporary network issues)"""
        retriable_errors = [
            'timeout',
            'connection',
            'network',
            'temporary',
            'try again'
        ]
        error_lower = error_msg.lower()
        return any(err in error_lower for err in retriable_errors)

    def _validate_spread_before_execution(self, db: Session, signal: TradingSignal) -> Dict:
        """
        ✅ FIX #3: Validate spread before trade execution

        Prevents execution at abnormally high spreads that could reduce profitability.
        Complements the spread check in signal generation.

        Returns:
            Dict with 'allowed' (bool) and 'reason' (str if rejected)
        """
        try:
            from models import Tick

            # Get latest tick for spread
            latest_tick = db.query(Tick).filter_by(
                account_id=signal.account_id,
                symbol=signal.symbol
            ).order_by(Tick.timestamp.desc()).first()

            if not latest_tick:
                logger.warning(f"No tick data for {signal.symbol} - allowing trade (risky)")
                return {'allowed': True}

            # Check tick age (if tick is too old, market may be closed)
            tick_age = datetime.utcnow() - latest_tick.timestamp
            if tick_age.total_seconds() > 60:
                return {
                    'allowed': False,
                    'reason': f'Tick data too old ({tick_age.seconds}s) - market may be closed'
                }

            # Calculate current spread
            current_spread = abs(float(latest_tick.ask) - float(latest_tick.bid))

            # Get average spread from recent ticks
            recent_ticks = db.query(Tick).filter_by(
                account_id=signal.account_id,
                symbol=signal.symbol
            ).order_by(Tick.timestamp.desc()).limit(100).all()

            if len(recent_ticks) < 10:
                logger.warning(f"Insufficient tick history for {signal.symbol} spread check")
                return {'allowed': True}

            spreads = [abs(float(t.ask) - float(t.bid)) for t in recent_ticks]
            avg_spread = sum(spreads) / len(spreads)

            # Reject if spread is abnormally high (> 3x average)
            MAX_SPREAD_MULTIPLIER = 3.0
            if current_spread > avg_spread * MAX_SPREAD_MULTIPLIER:
                return {
                    'allowed': False,
                    'reason': (
                        f'Spread too high: {current_spread:.5f} '
                        f'(avg: {avg_spread:.5f}, max: {avg_spread * MAX_SPREAD_MULTIPLIER:.5f})'
                    )
                }

            # Also check absolute spread limit (per symbol type)
            max_absolute_spread = self._get_max_allowed_spread(signal.symbol)
            if current_spread > max_absolute_spread:
                return {
                    'allowed': False,
                    'reason': f'Spread exceeds absolute limit: {current_spread:.5f} > {max_absolute_spread:.5f}'
                }

            logger.debug(
                f"✓ Spread check passed for {signal.symbol}: "
                f"{current_spread:.5f} (avg: {avg_spread:.5f})"
            )
            return {'allowed': True, 'spread': current_spread, 'avg_spread': avg_spread}

        except Exception as e:
            logger.error(f"Error in spread validation: {e}", exc_info=True)
            # Fail-safe: allow trade on error (but log it)
            return {'allowed': True, 'error': str(e)}

    def _get_max_allowed_spread(self, symbol: str) -> float:
        """Get maximum allowed spread per symbol type"""
        symbol_upper = symbol.upper()

        # Forex major pairs: tight spreads expected
        if any(pair in symbol_upper for pair in ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF']):
            return 0.0003  # 3 pips

        # Forex minor pairs: wider spreads acceptable
        elif any(pair in symbol_upper for pair in ['EURGBP', 'EURJPY', 'GBPJPY']):
            return 0.0005  # 5 pips

        # Exotic pairs: even wider spreads
        elif any(curr in symbol_upper for curr in ['ZAR', 'TRY', 'MXN']):
            return 0.001  # 10 pips

        # Crypto: variable spreads
        elif any(crypto in symbol_upper for crypto in ['BTC', 'ETH', 'XRP']):
            return symbol.replace('USD', '').replace('EUR', '') + ' 0.5%'  # 0.5% of price

        # Gold/Silver
        elif 'XAU' in symbol_upper:
            return 0.50  # $0.50
        elif 'XAG' in symbol_upper:
            return 0.05  # $0.05

        # Indices
        elif any(idx in symbol_upper for idx in ['US30', 'US500', 'NAS100', 'DE40']):
            return 5.0  # 5 points

        # Default: conservative limit
        return 0.001  # 10 pips

    def auto_trade_loop(self):
        """Main auto-trading loop"""
        logger.info(f"Auto-Trader loop started (interval: {self.check_interval}s)")

        while True:
            try:
                if not self.enabled:
                    logger.debug("Auto-Trading disabled, waiting...")
                    time.sleep(self.check_interval)
                    continue

                db = ScopedSession()
                self.process_new_signals(db)
                self.check_pending_commands(db)  # Verify trade execution
                db.close()

                # Cleanup every 10 iterations (~100 seconds)
                if int(time.time()) % 100 < 10:
                    self.cleanup_processed_signals()
                    self.cleanup_expired_cooldowns()

                time.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Auto-trade loop error: {e}")
                time.sleep(5)


# Singleton instance
_auto_trader = None


def get_auto_trader():
    """Get or create auto-trader instance"""
    global _auto_trader
    if _auto_trader is None:
        _auto_trader = AutoTrader()
    return _auto_trader


def start_auto_trader(enabled=False):
    """Start auto-trader in background thread"""
    trader = get_auto_trader()

    if enabled:
        trader.enable()

    thread = Thread(target=trader.auto_trade_loop, daemon=True)
    thread.start()
    logger.info("Auto-Trader thread started")
    return trader


if __name__ == '__main__':
    # Run standalone
    trader = AutoTrader()
    trader.enable()
    trader.auto_trade_loop()
