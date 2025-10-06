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
        self.enabled = False
        self.check_interval = 10  # Check for new signals every 10 seconds

        # Track processed signals
        self.processed_signals = set()

        # Cooldown tracking after SL hits: symbol -> cooldown_until_time
        self.symbol_cooldowns = {}

        # Auto-trade minimum confidence (controlled by UI slider)
        self.min_autotrade_confidence = 40  # Default 40%

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

            # Check circuit breaker FIRST (most critical check)
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

            # Check confidence threshold (use auto-trade slider value, not global settings)
            if signal.confidence and signal.confidence < self.min_autotrade_confidence:
                return {
                    'execute': False,
                    'reason': f'Low confidence ({signal.confidence}% < {self.min_autotrade_confidence}%)'
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
        """Create trade command from signal"""
        try:
            command_id = f"auto_{uuid.uuid4().hex[:8]}"

            command = Command(
                id=command_id,
                account_id=signal.account_id,
                command_type='OPEN_TRADE',
                symbol=signal.symbol,
                order_type=signal.signal_type,  # BUY or SELL
                volume=volume,
                sl=signal.sl,
                tp=signal.tp,
                comment=f"Auto-Trade Signal #{signal.id} ({signal.timeframe})",
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
                'comment': command.comment
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

            for signal in signals:
                # Skip already processed signals
                if signal.id in self.processed_signals:
                    continue

                # Mark as processed
                self.processed_signals.add(signal.id)

                # Check if should execute
                should_exec = self.should_execute_signal(signal, db)
                if not should_exec['execute']:
                    logger.debug(f"Skipping signal #{signal.id}: {should_exec['reason']}")
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
        Check if pending trade commands were executed by MT5.

        Verifies that commands sent to MT5 actually resulted in trades.
        Logs warnings for failed/timeout commands.
        """
        if not hasattr(self, 'pending_commands'):
            self.pending_commands = {}
            return

        now = datetime.utcnow()
        commands_to_remove = []

        for command_id, cmd_data in self.pending_commands.items():
            # Check if command resulted in a trade
            trade = db.query(Trade).filter_by(
                command_id=command_id
            ).first()

            if trade:
                # Command was executed successfully
                commands_to_remove.append(command_id)
                logger.info(f"✅ Command {command_id} executed: ticket #{trade.ticket}")
            elif now > cmd_data['timeout_at']:
                # Command timed out without execution
                commands_to_remove.append(command_id)
                logger.warning(
                    f"⚠️  Command {command_id} TIMEOUT: {cmd_data['symbol']} "
                    f"(sent {(now - cmd_data['created_at']).seconds}s ago) - "
                    f"Trade may not have been executed!"
                )

                # Check command status in database
                command = db.query(Command).filter_by(id=command_id).first()
                if command and command.status == 'failed':
                    logger.error(f"❌ Command {command_id} FAILED: {command.error_message}")

        # Clean up processed/timeout commands
        for cmd_id in commands_to_remove:
            del self.pending_commands[cmd_id]

        if commands_to_remove:
            logger.debug(f"🧹 Cleaned up {len(commands_to_remove)} pending commands")

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
