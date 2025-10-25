#!/usr/bin/env python3
"""
Auto-Trading Engine for ngTradingBot
Automatically executes trades based on trading signals

TIMEZONE HANDLING:
- All internal timestamps in UTC (timezone-aware via timezone_manager)
- Database stores naive UTC timestamps
- Broker/MT5 timestamps converted from EET to UTC
- Session detection uses UTC time
- Logging shows both UTC and Broker time for clarity
"""

import logging
import time
import uuid
from datetime import datetime, timedelta
from threading import Thread
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from database import ScopedSession
from models import TradingSignal, Trade, Account, Command
from redis_client import get_redis
from timezone_manager import tz, log_with_timezone

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def calculate_max_trades_for_confidence(confidence: float) -> int:
    """
    ✅ SIMPLIFIED: Always allow exactly 1 trade per signal.

    PREVIOUS LOGIC WAS OVERENGINEERED:
    - 80% confidence → allowed 4 trades → Signal #80004 opened 6 trades!
    - Led to duplicate positions and overexposure

    NEW SIMPLE RULE:
    - Every signal = maximum 1 trade
    - Duplicate prevention happens at symbol level (see check below)

    Args:
        confidence: Signal confidence as percentage (50.0 = 50%)

    Returns:
        Always returns 1 (or 0 if below minimum threshold)
    """
    if confidence < 50.0:
        return 0  # Below minimum confidence threshold

    # ✅ SIMPLE: One signal = one trade, ALWAYS
    return 1


class AutoTrader:
    """Automated trading based on signals"""

    def __init__(self):
        self.redis = get_redis()
        self.check_interval = 10  # Check for new signals every 10 seconds

        # Track processed signals by hash (symbol+timeframe+type+entry_price)
        # This allows detecting when signals are updated with new values
        self.processed_signal_hashes = {}

        # Cooldown tracking after SL hits: symbol -> cooldown_until_time
        self.symbol_cooldowns = {}

        # Track pending commands and failure count
        self.pending_commands = {}
        self.failed_command_count = 0

        # ✅ UNIFIED PROTECTION: Load from database (single source of truth)
        # These will be loaded from daily_drawdown_limits table in _load_protection_settings()
        self.circuit_breaker_enabled = True  # Default fallback
        self.max_daily_loss_percent = 10.0  # Default fallback
        self.max_total_drawdown_percent = 20.0  # Default fallback
        self.circuit_breaker_tripped = False
        self.auto_pause_enabled = False  # Default fallback
        self.pause_after_consecutive_losses = 3  # Default fallback
        self.protection_enabled = True  # Master switch
        self.circuit_breaker_reason = None
        self.daily_loss_override = False  # Manual override for daily loss limit

        # Correlation limits - prevent over-exposure to correlated pairs
        self.max_correlated_positions = 2  # Max 2 positions in same currency group
        self.max_open_positions = 10  # Global limit to prevent overexposure

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

        # ✅ NEW: Load auto-trade status from database on startup
        self.enabled = True  # Default fallback
        self.min_autotrade_confidence = 60.0  # Default fallback
        self.risk_profile = 'normal'  # Default: moderate/normal/aggressive
        self._load_autotrade_status_from_db()
        self._load_protection_settings()  # ✅ Load unified protection settings from DB

        logger.info(
            f"Auto-Trader initialized (enabled={self.enabled}, risk_profile={self.risk_profile}, "
            f"min_confidence={self.min_autotrade_confidence}%, protection_enabled={self.protection_enabled}, "
            f"daily_loss_limit={self.max_daily_loss_percent}%)"
        )

    def _load_settings(self, db: Session):
        """Load global settings from database"""
        from models import GlobalSettings
        return GlobalSettings.get_settings(db)

    def _load_autotrade_status_from_db(self):
        """✅ NEW: Load auto-trade status from database on startup"""
        try:
            from models import GlobalSettings
            db = ScopedSession()
            try:
                settings = GlobalSettings.get_settings(db)
                self.enabled = settings.autotrade_enabled
                self.min_autotrade_confidence = float(settings.autotrade_min_confidence)
                self.risk_profile = settings.autotrade_risk_profile or 'normal'
                logger.info(
                    f"✅ Auto-Trade status loaded from DB: "
                    f"enabled={self.enabled}, risk_profile={self.risk_profile}, min_confidence={self.min_autotrade_confidence}%"
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"❌ Failed to load auto-trade status from DB: {e}")
            logger.info("Using default values: enabled=True, min_confidence=60%")

    def _save_autotrade_status_to_db(self):
        """✅ NEW: Save auto-trade status to database"""
        try:
            from models import GlobalSettings
            db = ScopedSession()
            try:
                settings = GlobalSettings.get_settings(db)
                settings.autotrade_enabled = self.enabled
                settings.autotrade_min_confidence = self.min_autotrade_confidence
                settings.autotrade_risk_profile = self.risk_profile
                db.commit()
                logger.info(
                    f"✅ Auto-Trade status saved to DB: "
                    f"enabled={self.enabled}, risk_profile={self.risk_profile}, min_confidence={self.min_autotrade_confidence}%"
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"❌ Failed to save auto-trade status to DB: {e}")

    def _load_protection_settings(self):
        """✅ NEW: Load unified protection settings from daily_drawdown_limits table"""
        try:
            from daily_drawdown_protection import DailyDrawdownLimit
            db = ScopedSession()
            try:
                # Load for default account (account_id=3 for testing, should be configurable)
                limit = db.query(DailyDrawdownLimit).filter_by(account_id=3).first()

                if limit:
                    self.protection_enabled = bool(limit.protection_enabled)
                    self.max_daily_loss_percent = float(limit.max_daily_loss_percent) if limit.max_daily_loss_percent else 10.0
                    self.max_total_drawdown_percent = float(limit.max_total_drawdown_percent) if limit.max_total_drawdown_percent else 20.0
                    self.circuit_breaker_tripped = bool(limit.circuit_breaker_tripped)
                    self.auto_pause_enabled = bool(limit.auto_pause_enabled)
                    self.pause_after_consecutive_losses = int(limit.pause_after_consecutive_losses) if limit.pause_after_consecutive_losses else 3

                    logger.info(
                        f"✅ Protection settings loaded from DB: "
                        f"enabled={self.protection_enabled}, daily_loss={self.max_daily_loss_percent}%, "
                        f"total_drawdown={self.max_total_drawdown_percent}%, auto_pause={self.auto_pause_enabled}, "
                        f"circuit_breaker_tripped={self.circuit_breaker_tripped}"
                    )
                else:
                    logger.warning("No protection settings found in DB, using defaults")

            finally:
                db.close()
        except Exception as e:
            logger.error(f"❌ Failed to load protection settings from DB: {e}")
            logger.info("Using default protection values")

    def _persist_circuit_breaker_status(self, db: Session, account_id: int, tripped: bool):
        """✅ Persist circuit breaker status to database"""
        try:
            from daily_drawdown_protection import DailyDrawdownLimit
            limit = db.query(DailyDrawdownLimit).filter_by(account_id=account_id).first()

            if limit:
                limit.circuit_breaker_tripped = tripped
                db.commit()
                logger.info(f"✅ Circuit breaker status persisted to DB: tripped={tripped}")

        except Exception as e:
            logger.error(f"❌ Failed to persist circuit breaker status: {e}")

    def set_min_confidence(self, min_confidence: float):
        """Set minimum confidence threshold for auto-trading"""
        self.min_autotrade_confidence = float(min_confidence)
        self._save_autotrade_status_to_db()  # ✅ Persist to DB
        logger.info(f"Auto-Trade min confidence set to {min_confidence}%")

    def set_risk_profile(self, risk_profile: str):
        """Set risk profile for dynamic confidence calculation"""
        if risk_profile not in ['moderate', 'normal', 'aggressive']:
            logger.error(f"Invalid risk profile: {risk_profile}")
            return

        self.risk_profile = risk_profile

        # ✅ FIX: Update min_autotrade_confidence based on risk profile
        # These values match DynamicConfidenceCalculator.base_confidence
        risk_profile_confidence = {
            'moderate': 65.0,    # Conservative: Only high-quality signals
            'normal': 55.0,      # Balanced: Standard risk
            'aggressive': 50.0   # Risk-seeking: More trades
        }

        self.min_autotrade_confidence = risk_profile_confidence.get(risk_profile, 55.0)

        self._save_autotrade_status_to_db()  # ✅ Persist to DB
        logger.info(f"🎯 Risk Profile set to: {risk_profile.upper()} (min_confidence: {self.min_autotrade_confidence}%)")

    def enable(self):
        """Enable auto-trading"""
        self.enabled = True
        self._save_autotrade_status_to_db()  # ✅ Persist to DB
        logger.info(f"🤖 Auto-Trading ENABLED (risk_profile={self.risk_profile}, min confidence: {self.min_autotrade_confidence}%)")

    def disable(self):
        """Disable auto-trading (kill-switch)"""
        self.enabled = False
        self._save_autotrade_status_to_db()  # ✅ Persist to DB
        logger.warning("🛑 Auto-Trading DISABLED (Kill-Switch)")

    def reset_circuit_breaker(self, override_daily_loss=False, account_id: int = 3):
        """
        Reset circuit breaker manually

        Args:
            override_daily_loss: If True, temporarily ignore daily loss limit for this session
            account_id: Account ID to reset circuit breaker for
        """
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = None
        self.failed_command_count = 0

        # ✅ Persist to database
        try:
            from daily_drawdown_protection import DailyDrawdownLimit
            db = ScopedSession()
            try:
                limit = db.query(DailyDrawdownLimit).filter_by(account_id=account_id).first()
                if limit:
                    limit.circuit_breaker_tripped = False
                    limit.limit_reached = False
                    db.commit()
                    logger.info(f"✅ Circuit breaker status persisted to DB: tripped=False")
            finally:
                db.close()
        except Exception as e:
            logger.error(f"❌ Failed to persist circuit breaker reset: {e}")

        if override_daily_loss:
            self.daily_loss_override = True
            logger.warning("⚠️ Circuit breaker reset with DAILY LOSS OVERRIDE enabled - trading will continue despite daily loss limit")
        else:
            self.daily_loss_override = False
            logger.info("Circuit breaker reset manually (failed_command_count reset to 0)")

    def check_circuit_breaker(self, db: Session, account_id: int) -> bool:
        """
        Check if circuit breaker should trip to prevent catastrophic losses.

        ✅ UNIFIED PROTECTION: Loads settings from daily_drawdown_limits table
        Circuit breaker trips if:
        1. Protection is enabled (protection_enabled=true)
        2. Daily loss exceeds max_daily_loss_percent
        3. Total drawdown exceeds max_total_drawdown_percent

        Returns:
            True if safe to trade, False if circuit breaker tripped
        """
        # ✅ Master switch: If protection disabled, allow all trading
        if not self.protection_enabled:
            return True

        if not self.circuit_breaker_enabled:
            return True  # Circuit breaker disabled

        if self.circuit_breaker_tripped:
            return False  # Already tripped

        try:
            account = db.query(Account).filter_by(id=account_id).first()
            if not account:
                logger.error("Account not found for circuit breaker check")
                return False

            # Check 1: Daily loss limit (skip if override is active)
            if hasattr(account, 'profit_today') and account.profit_today is not None:
                daily_loss_percent = (float(account.profit_today) / float(account.balance)) * 100

                if daily_loss_percent < -self.max_daily_loss_percent:
                    # Check if daily loss override is active
                    if hasattr(self, 'daily_loss_override') and self.daily_loss_override:
                        logger.warning(
                            f"⚠️ Daily loss limit exceeded ({daily_loss_percent:.2f}%) but OVERRIDE is active - continuing to trade"
                        )
                        # Don't trip circuit breaker, allow trading to continue
                    else:
                        self.circuit_breaker_tripped = True
                        self.circuit_breaker_reason = f"Daily loss exceeded {self.max_daily_loss_percent}%: ${account.profit_today:.2f} ({daily_loss_percent:.2f}%)"
                        self.enabled = False

                        # ✅ Persist to database
                        self._persist_circuit_breaker_status(db, account_id, tripped=True)

                        logger.critical(f"🚨 CIRCUIT BREAKER TRIPPED: {self.circuit_breaker_reason}")
                        logger.critical(f"🛑 Auto-trading STOPPED for safety")

                        # Log to AI Decision Log
                        from ai_decision_log import log_circuit_breaker
                        log_circuit_breaker(
                            account_id=account_id,
                            failed_count=0,  # Daily loss trigger
                            reason=self.circuit_breaker_reason,
                            details={
                                'trigger_type': 'daily_loss',
                                'daily_loss_percent': daily_loss_percent,
                                'profit_today': float(account.profit_today),
                                'balance': float(account.balance),
                                'max_daily_loss_percent': self.max_daily_loss_percent
                            }
                        )

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
                    
                    # Log to AI Decision Log
                    from ai_decision_log import log_circuit_breaker
                    log_circuit_breaker(
                        account_id=account_id,
                        failed_count=0,  # Total drawdown trigger
                        reason=self.circuit_breaker_reason,
                        details={
                            'trigger_type': 'total_drawdown',
                            'total_drawdown_percent': total_drawdown_percent,
                            'initial_balance': float(account.initial_balance),
                            'current_balance': float(account.balance),
                            'max_total_drawdown_percent': self.max_total_drawdown_percent
                        }
                    )

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

    def check_position_limits(self, db: Session, account_id: int) -> Dict:
        """
        ✅ NEW: Check if max open positions limit is reached
        
        Prevents overexposure by limiting total number of open positions.
        
        Args:
            db: Database session
            account_id: Account ID
            
        Returns:
            Dict with 'allowed' (bool) and 'reason' (str)
        """
        try:
            # Count current open positions
            open_count = db.query(Trade).filter(
                Trade.account_id == account_id,
                Trade.status == 'open'
            ).count()
            
            if open_count >= self.max_open_positions:
                logger.warning(
                    f"⚠️ Max positions limit reached: {open_count}/{self.max_open_positions}"
                )
                return {
                    'allowed': False,
                    'reason': f'Max open positions limit ({self.max_open_positions}) reached'
                }
            
            return {'allowed': True}
            
        except Exception as e:
            logger.error(f"Error checking position limits: {e}", exc_info=True)
            # Fail-safe: block trade on error
            return {'allowed': False, 'reason': f'Position limit check error: {str(e)}'}

    def calculate_position_size(self, db: Session, account_id: int, signal: TradingSignal) -> float:
        """Calculate position size based on risk management"""
        try:
            settings = self._load_settings(db)
            balance = self.get_account_balance(db, account_id)

            # ✅ FIX: Use proper position sizing instead of hard-coded 0.01
            # Delegate to PositionSizer for sophisticated volume calculation
            from position_sizer import get_position_sizer

            position_sizer = get_position_sizer()

            # Calculate SL distance in pips
            sl_price = getattr(signal, 'sl_price', None) or getattr(signal, 'sl', None)

            if sl_price and signal.entry_price:
                # Get broker symbol info for pip calculation
                from models import BrokerSymbol
                broker_symbol = db.query(BrokerSymbol).filter_by(
                    symbol=signal.symbol
                ).first()

                if broker_symbol:
                    # Calculate SL distance in pips
                    sl_distance = abs(float(signal.entry_price) - float(sl_price))
                    point = float(broker_symbol.point_value or 0.00001)
                    sl_distance_pips = sl_distance / (point * 10)  # Convert to pips

                    # Use position sizer
                    volume = position_sizer.calculate_lot_size(
                        db=db,
                        account_id=account_id,
                        symbol=signal.symbol,
                        confidence=float(signal.confidence) if signal.confidence else 50.0,
                        sl_distance_pips=sl_distance_pips,
                        entry_price=float(signal.entry_price)
                    )

                    # Apply safety limits (0.01 min, 1.0 max for safety)
                    volume = max(0.01, min(volume, 1.0))

                    logger.info(
                        f"📊 Position Size: {signal.symbol} | "
                        f"Confidence: {signal.confidence:.1f}% | "
                        f"SL Distance: {sl_distance_pips:.1f} pips | "
                        f"Volume: {volume:.2f} lot"
                    )

                    return volume

            # Fallback: minimum volume
            logger.warning(f"Position sizing fallback for {signal.symbol}: using 0.01 lot")
            return 0.01

        except Exception as e:
            logger.error(f"Error calculating position size: {e}", exc_info=True)
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

    def should_execute_signal(self, signal: TradingSignal, db: Session, account_id: int) -> Dict:
        """Determine if signal should be executed

        Args:
            signal: Trading signal (GLOBAL - no account_id field)
            db: Database session
            account_id: Account ID to execute signal for
        """
        # 🔒 CRITICAL: Redis lock to prevent race conditions on position checks
        # This prevents multiple workers from opening duplicate positions simultaneously
        # NOTE: Lock is NOT acquired here anymore - moved to process_new_signals()
        # to ensure lock is held until trade command is created
        try:

            settings = self._load_settings(db)

            # ✅ REMOVED: Age-based signal rejection - replaced by continuous validation
            # Signal validator worker now continuously checks indicator conditions
            # Signals are deleted immediately when conditions no longer hold
            # This allows signals to be traded as long as they remain valid

            # ✅ Check MARKET HOURS FIRST (prevent trading on closed markets)
            from market_hours import MarketHours
            if not MarketHours.is_market_open(signal.symbol):
                session = MarketHours.get_trading_session(signal.symbol)
                return {
                    'execute': False,
                    'reason': f'Market closed for {signal.symbol} (session: {session})'
                }

            # Check DAILY DRAWDOWN PROTECTION SECOND (most critical check)
            from daily_drawdown_protection import get_drawdown_protection
            dd_protection = get_drawdown_protection(account_id)
            dd_check = dd_protection.check_and_update(auto_trading_enabled=self.enabled)

            if not dd_check['allowed']:
                return {
                    'execute': False,
                    'reason': dd_check.get('reason', 'Daily drawdown limit reached')
                }

            # Check NEWS FILTER SECOND (prevent trading during high-impact news)
            from news_filter import get_news_filter
            news_filter = get_news_filter(account_id)
            news_check = news_filter.check_trading_allowed(signal.symbol)

            if not news_check['allowed']:
                return {
                    'execute': False,
                    'reason': news_check.get('reason', 'Trading paused due to news')
                }

            # Check circuit breaker THIRD
            if not self.check_circuit_breaker(db, account_id):
                return {
                    'execute': False,
                    'reason': f'Circuit breaker tripped: {self.circuit_breaker_reason}'
                }

            # ✅ NEW: Check max open positions limit FOURTH (prevent overexposure)
            position_limit_check = self.check_position_limits(db, account_id)
            if not position_limit_check['allowed']:
                return {
                    'execute': False,
                    'reason': position_limit_check['reason']
                }

            # Check correlation exposure FIFTH (prevent over-exposure to correlated pairs)
            correlation_check = self.check_correlation_exposure(db, account_id, signal.symbol)
            if not correlation_check['allowed']:
                return {
                    'execute': False,
                    'reason': correlation_check['reason']
                }

            # ✅ SIMPLIFIED: Check per-symbol position limit (prevent duplicate positions)
            # REMOVED: timeframe check - now checks ONLY symbol level
            # REASON: Prevent ANY duplicate on same symbol (even different timeframes)
            existing_positions = db.query(Trade).filter(
                and_(
                    Trade.account_id == account_id,
                    Trade.symbol == signal.symbol,  # ✅ Symbol only, no timeframe
                    Trade.status == 'open'
                )
            ).count()

            # ✅ CRITICAL: Also count pending/processing commands to prevent race conditions
            from models import Command
            pending_commands = db.query(Command).filter(
                and_(
                    Command.account_id == account_id,
                    Command.command_type == 'OPEN_TRADE',
                    Command.status.in_(['pending', 'processing']),
                    Command.payload['symbol'].astext == signal.symbol  # ✅ Symbol only, no timeframe
                )
            ).count()

            total_exposure = existing_positions + pending_commands

            # ✅ SIMPLIFIED: Max 1 trade per symbol (always)
            signal_confidence = float(signal.confidence) if signal.confidence else 50.0
            max_trades_allowed = 1  # ✅ SIMPLE: Always 1

            logger.info(f"🔍 Duplicate check: {signal.symbol} - Found {existing_positions} open + {pending_commands} pending = {total_exposure} (max: {max_trades_allowed})")

            if total_exposure >= max_trades_allowed:
                return {
                    'execute': False,
                    'reason': f'Already have open position for {signal.symbol} ({total_exposure} active)'
                }

            # ✅ NEW LOGIC: No age limit! Signals are valid as long as status='active'
            # A separate signal_validation_worker runs every 30s to deactivate invalid signals
            # This ensures only valid signals are traded, regardless of age

            # ✅ ENHANCED: Check SL-Hit Protection (automatic pause after multiple SL hits)
            from sl_hit_protection import get_sl_hit_protection
            sl_protection = get_sl_hit_protection()
            sl_check = sl_protection.check_sl_hits(db, account_id, signal.symbol, max_hits=2, timeframe_hours=4)

            if sl_check['should_pause']:
                logger.warning(f"🚨 {signal.symbol} auto-trade BLOCKED: {sl_check['reason']}")
                return {
                    'execute': False,
                    'reason': sl_check['reason']
                }

            # Check cooldown after SL hit (prevent revenge trading) - LEGACY SUPPORT
            if signal.symbol in self.symbol_cooldowns:
                cooldown_until = self.symbol_cooldowns[signal.symbol]
                if datetime.utcnow() < cooldown_until:
                    remaining = (cooldown_until - datetime.utcnow()).total_seconds() / 60
                    return {
                        'execute': False,
                        'reason': f'Symbol in cooldown ({remaining:.0f}min remaining)'
                    }

            # ✅ NEW: Symbol-Specific Dynamic Configuration Check
            # This checks per-symbol learned settings (confidence, risk, status, regime)
            try:
                from symbol_dynamic_manager import SymbolDynamicManager
                from technical_indicators import TechnicalIndicators

                symbol_manager = SymbolDynamicManager(account_id=account_id)

                # Get market regime for this symbol
                try:
                    ti = TechnicalIndicators(account_id, signal.symbol, signal.timeframe)
                    regime_info = ti.detect_market_regime()
                    market_regime = regime_info.get('regime', 'UNKNOWN')
                except Exception as e:
                    logger.debug(f"Could not detect market regime for {signal.symbol}: {e}")
                    market_regime = None

                # Check if symbol+direction config allows trading
                should_trade, reason, config = symbol_manager.should_trade_signal(
                    db, signal, market_regime
                )

                if not should_trade:
                    logger.info(
                        f"🚫 Symbol config blocked {signal.symbol} {signal.signal_type}: {reason}"
                    )
                    return {
                        'execute': False,
                        'reason': f'Symbol config: {reason}'
                    }

                # Use symbol-specific confidence threshold (dynamically adjusted)
                symbol_min_confidence = max(
                    self.min_autotrade_confidence,
                    float(config.min_confidence_threshold)
                )

                logger.debug(
                    f"📊 {signal.symbol} {signal.signal_type}: "
                    f"Config status={config.status}, conf≥{config.min_confidence_threshold}%, "
                    f"risk={config.risk_multiplier}x, WR={config.rolling_winrate or 0}%"
                )

            except Exception as e:
                logger.warning(f"Symbol dynamic config check failed: {e}")
                # Fallback to legacy symbol_config
                from symbol_config import get_symbol_min_confidence
                symbol_min_confidence = max(self.min_autotrade_confidence, get_symbol_min_confidence(signal.symbol))

            # ✅ DYNAMIC CONFIDENCE: Calculate context-aware minimum confidence
            # Uses: risk profile + symbol + session + volatility
            try:
                from dynamic_confidence_calculator import get_confidence_calculator
                from session_volatility_analyzer import SessionVolatilityAnalyzer
                
                calculator = get_confidence_calculator()
                analyzer = SessionVolatilityAnalyzer()
                
                # Get current session and volatility
                session_name, _ = analyzer.get_current_session()
                volatility = analyzer.calculate_recent_volatility(db, signal.symbol, account_id)
                
                # Calculate required confidence
                required_conf, breakdown = calculator.calculate_required_confidence(
                    symbol=signal.symbol,
                    risk_profile=self.risk_profile,
                    session=session_name,
                    volatility=volatility
                )
                
                # Use the higher of: static symbol config OR dynamic calculation
                symbol_min_confidence = max(symbol_min_confidence, required_conf)
                
                logger.debug(
                    f"🎯 Dynamic Confidence for {signal.symbol}: "
                    f"Required={required_conf:.1f}% (profile={self.risk_profile}, "
                    f"session={session_name}, volatility={volatility:.2f}x)"
                )
                
            except Exception as e:
                logger.debug(f"Dynamic confidence calculation skipped: {e}")
                # Continue with static symbol_min_confidence

            # Check confidence threshold (now using dynamically adjusted threshold)
            if signal.confidence and signal.confidence < symbol_min_confidence:
                return {
                    'execute': False,
                    'reason': f'Low confidence ({signal.confidence}% < {symbol_min_confidence}% for {signal.symbol})'
                }

            # Check if signal has required data (use sl_price/tp_price for DB compatibility)
            if not signal.entry_price or not signal.sl_price or not signal.tp_price:
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

    def _validate_tp_sl(self, signal: TradingSignal, adjusted_sl: float) -> bool:
        """
        Validate TP/SL values before creating trade command

        Ensures:
        - TP and SL are not zero (MT5 requirement)
        - TP/SL are in correct direction
        - SL is not too close to entry (minimum distance)
        - Risk/Reward ratio is reasonable

        Returns:
            True if valid, False otherwise
        """
        try:
            entry = float(signal.entry_price)
            # Use tp_price directly (DB column name) instead of property
            tp = getattr(signal, 'tp_price', None) or getattr(signal, 'tp', None)
            tp = float(tp) if tp else None
            sl = float(adjusted_sl)

            # Check 1: TP and SL must not be zero (MT5 EA rejects these)
            if tp == 0 or sl == 0 or tp is None or sl is None:
                logger.warning(f"TP/SL validation failed: TP={tp}, SL={sl} (must not be 0 or None)")
                return False

            # Check 2: Verify direction is correct
            if signal.signal_type == 'BUY':
                if tp <= entry:
                    logger.warning(f"BUY TP validation failed: TP ({tp}) must be > entry ({entry})")
                    return False
                if sl >= entry:
                    logger.warning(f"BUY SL validation failed: SL ({sl}) must be < entry ({entry})")
                    return False
            else:  # SELL
                if tp >= entry:
                    logger.warning(f"SELL TP validation failed: TP ({tp}) must be < entry ({entry})")
                    return False
                if sl <= entry:
                    logger.warning(f"SELL SL validation failed: SL ({sl}) must be > entry ({entry})")
                    return False

            # Check 3: Minimum SL distance (0.05% for forex, 0.2% for volatile assets)
            min_sl_distance_pct = 0.2 if signal.symbol in ['BTCUSD', 'ETHUSD', 'XAUUSD'] else 0.05
            sl_distance_pct = abs(entry - sl) / entry * 100

            if sl_distance_pct < min_sl_distance_pct:
                logger.warning(f"SL too tight: {sl_distance_pct:.2f}% (min: {min_sl_distance_pct}%)")
                return False

            # Check 4: Maximum TP distance - adjusted based on risk profile
            # Load risk profile from global settings
            risk_profile = 'normal'  # default
            try:
                from models import GlobalSettings
                from database import ScopedSession
                temp_db = ScopedSession()
                try:
                    settings = temp_db.query(GlobalSettings).first()
                    if settings:
                        risk_profile = settings.autotrade_risk_profile or 'normal'
                finally:
                    temp_db.close()
            except Exception as e:
                logger.debug(f"Could not load risk profile: {e}")

            # Base limits
            base_limit = 3.0 if signal.symbol in ['BTCUSD', 'ETHUSD', 'XAUUSD'] else 5.0

            # Adjust limits based on risk profile
            if risk_profile == 'moderate':
                max_tp_distance_pct = base_limit * 0.8  # 80% of base (conservative)
            elif risk_profile == 'aggressive':
                max_tp_distance_pct = base_limit * 4.0  # 400% of base (very aggressive)
            else:  # normal
                max_tp_distance_pct = base_limit * 1.5  # 150% of base

            tp_distance_pct = abs(tp - entry) / entry * 100

            if tp_distance_pct > max_tp_distance_pct:
                logger.warning(f"TP too far: {tp_distance_pct:.2f}% (max: {max_tp_distance_pct:.1f}% for {risk_profile} profile)")
                return False

            # Check 5: Risk/Reward ratio (minimum 1:1.2)
            risk = abs(entry - sl)
            reward = abs(tp - entry)
            risk_reward = reward / risk if risk > 0 else 0

            if risk_reward < 1.2:
                logger.warning(f"Risk/Reward too low: {risk_reward:.2f} (min: 1.2)")
                return False

            # All checks passed
            logger.debug(f"✅ TP/SL validation passed: R:R={risk_reward:.2f}, SL_dist={sl_distance_pct:.2f}%, TP_dist={tp_distance_pct:.2f}%")
            return True

        except Exception as e:
            logger.error(f"Error in TP/SL validation: {e}", exc_info=True)
            return False

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
                
                # Log spread rejection to AI Decision Log
                from ai_decision_log import log_spread_rejection
                log_spread_rejection(
                    account_id=account_id,
                    symbol=signal.symbol,
                    current_spread=spread_check.get('current_spread', 0),
                    max_spread=spread_check.get('max_spread', 0),
                    details={
                        'signal_id': signal.id,
                        'reason': spread_check['reason'],
                        'average_spread': spread_check.get('average_spread'),
                        'spread_multiple': spread_check.get('spread_multiple'),
                        'tick_age': spread_check.get('tick_age'),
                        'timeframe': signal.timeframe,
                        'signal_type': signal.signal_type
                    }
                )
                
                return None

            command_id = f"auto_{uuid.uuid4().hex[:8]}"

            # Apply symbol-specific SL multiplier OR use SuperTrend for dynamic SL
            from symbol_config import get_symbol_sl_multiplier
            sl_multiplier = get_symbol_sl_multiplier(signal.symbol)

            # Try to get SuperTrend-based dynamic SL for better risk management
            # Use sl_price directly (DB column name) instead of property
            sl_price = getattr(signal, 'sl_price', None) or getattr(signal, 'sl', None)
            adjusted_sl = sl_price
            use_supertrend_sl = False

            # ✅ Dynamic SuperTrend SL with maximum distance limits
            # Define max allowed SL distance per symbol type (in %)
            max_sl_distance_pct = {
                'XAGUSD': 2.5,   # Silver: max 2.5%
                'XAUUSD': 2.0,   # Gold: max 2.0%
                'FOREX': 1.5,    # Forex pairs: max 1.5%
                'CRYPTO': 3.0,   # Crypto: max 3.0%
                'INDEX': 1.5,    # Indices: max 1.5%
            }

            # Determine symbol category
            if signal.symbol in ['XAGUSD', 'XAUUSD', 'GOLD', 'SILVER']:
                max_sl_pct = max_sl_distance_pct.get(signal.symbol, 2.5)
            elif 'BTC' in signal.symbol or 'ETH' in signal.symbol:
                max_sl_pct = max_sl_distance_pct['CRYPTO']
            elif any(idx in signal.symbol for idx in ['US500', 'US30', 'NAS100', 'GER40']):
                max_sl_pct = max_sl_distance_pct['INDEX']
            else:
                max_sl_pct = max_sl_distance_pct['FOREX']

            try:
                from technical_indicators import TechnicalIndicators
                ti = TechnicalIndicators(account_id, signal.symbol, signal.timeframe)
                supertrend = ti.calculate_supertrend()

                if supertrend and supertrend['value']:
                    # Use SuperTrend as dynamic SL (better than fixed distance)
                    if signal.signal_type == 'BUY' and supertrend['direction'] == 'bullish':
                        # For BUY: Use SuperTrend value as SL (price below SuperTrend = exit)
                        # Verify SuperTrend is below entry (valid for BUY)
                        if float(supertrend['value']) < float(signal.entry_price):
                            st_distance_pct = abs(float(signal.entry_price) - float(supertrend['value'])) / float(signal.entry_price) * 100

                            # Check if SuperTrend SL is within acceptable range
                            if st_distance_pct <= max_sl_pct:
                                adjusted_sl = supertrend['value']
                                use_supertrend_sl = True
                                logger.info(f"🎯 {signal.symbol}: Using SuperTrend SL | Price: {signal.entry_price} | SuperTrend SL: {adjusted_sl:.5f} ({st_distance_pct:.2f}% distance, max: {max_sl_pct}%)")
                            else:
                                # SuperTrend too far - use max allowed distance instead
                                max_sl_distance = float(signal.entry_price) * (max_sl_pct / 100)
                                adjusted_sl = float(signal.entry_price) - max_sl_distance
                                use_supertrend_sl = True
                                logger.info(f"📏 {signal.symbol}: SuperTrend SL too wide ({st_distance_pct:.2f}% > {max_sl_pct}%), using max distance SL: {adjusted_sl:.5f} ({max_sl_pct}%)")
                        else:
                            logger.warning(f"⚠️ {signal.symbol} BUY: SuperTrend SL ({supertrend['value']:.5f}) above entry ({signal.entry_price}), using traditional SL")

                    elif signal.signal_type == 'SELL' and supertrend['direction'] == 'bearish':
                        # For SELL: Use SuperTrend value as SL (price above SuperTrend = exit)
                        # Verify SuperTrend is above entry (valid for SELL)
                        if float(supertrend['value']) > float(signal.entry_price):
                            st_distance_pct = abs(float(supertrend['value']) - float(signal.entry_price)) / float(signal.entry_price) * 100

                            # Check if SuperTrend SL is within acceptable range
                            if st_distance_pct <= max_sl_pct:
                                adjusted_sl = supertrend['value']
                                use_supertrend_sl = True
                                logger.info(f"🎯 {signal.symbol}: Using SuperTrend SL | Price: {signal.entry_price} | SuperTrend SL: {adjusted_sl:.5f} ({st_distance_pct:.2f}% distance, max: {max_sl_pct}%)")
                            else:
                                # SuperTrend too far - use max allowed distance instead
                                max_sl_distance = float(signal.entry_price) * (max_sl_pct / 100)
                                adjusted_sl = float(signal.entry_price) + max_sl_distance
                                use_supertrend_sl = True
                                logger.info(f"📏 {signal.symbol}: SuperTrend SL too wide ({st_distance_pct:.2f}% > {max_sl_pct}%), using max distance SL: {adjusted_sl:.5f} ({max_sl_pct}%)")
                        else:
                            logger.warning(f"⚠️ {signal.symbol} SELL: SuperTrend SL ({supertrend['value']:.5f}) below entry ({signal.entry_price}), using traditional SL")
            except Exception as e:
                logger.debug(f"SuperTrend SL calculation failed for {signal.symbol}, using traditional SL: {e}")

            # Fallback to symbol-specific multiplier if SuperTrend not available
            if not use_supertrend_sl:
                if sl_multiplier != 1.0 and signal.entry_price and sl_price:
                    sl_distance = abs(float(signal.entry_price) - float(sl_price))
                    adjusted_sl_distance = sl_distance * sl_multiplier

                    if signal.signal_type == 'BUY':
                        adjusted_sl = float(signal.entry_price) - adjusted_sl_distance
                    else:  # SELL
                        adjusted_sl = float(signal.entry_price) + adjusted_sl_distance

                    logger.info(f"📊 {signal.symbol}: Adjusted SL with multiplier {sl_multiplier} | Original: {sl_price} → Adjusted: {adjusted_sl:.5f}")

            # Use tp_price directly (DB column name) instead of property
            tp_price = getattr(signal, 'tp_price', None) or getattr(signal, 'tp', None)

            # ✅ ADJUST TP if SuperTrend SL is used (to maintain minimum R/R ratio)
            adjusted_tp_price = None
            logger.info(f"🔍 DEBUG: use_supertrend_sl={use_supertrend_sl}, tp_price={tp_price}")

            if use_supertrend_sl and tp_price:
                entry = float(signal.entry_price)
                sl_distance = abs(entry - float(adjusted_sl))
                tp_distance = abs(float(tp_price) - entry)

                # Calculate current R/R
                current_rr = tp_distance / sl_distance if sl_distance > 0 else 0
                min_rr = 1.5  # Minimum acceptable R/R

                logger.info(f"🔍 {signal.symbol}: SuperTrend SL active - Current R/R: {current_rr:.2f}, Min R/R: {min_rr:.2f}")

                if current_rr < min_rr:
                    # Adjust TP to meet minimum R/R
                    required_tp_distance = sl_distance * min_rr

                    if signal.signal_type == 'BUY':
                        adjusted_tp_price = entry + required_tp_distance
                    else:  # SELL
                        adjusted_tp_price = entry - required_tp_distance

                    logger.info(
                        f"📊 {signal.symbol}: Adjusted TP for SuperTrend SL | "
                        f"Original TP: {tp_price:.5f} (R/R: {current_rr:.2f}) → "
                        f"Adjusted TP: {adjusted_tp_price:.5f} (R/R: {min_rr:.2f})"
                    )
                    tp_price = adjusted_tp_price
                else:
                    logger.info(f"✅ {signal.symbol}: SuperTrend SL R/R already acceptable: {current_rr:.2f}")

            # ✅ CRITICAL VALIDATION: Ensure TP/SL are valid before sending to MT5
            # Create a temporary modified signal for validation if TP was adjusted
            if adjusted_tp_price:
                # Temporarily modify signal for validation
                original_tp = signal.tp_price
                signal.tp_price = adjusted_tp_price
                validation_result = self._validate_tp_sl(signal, adjusted_sl)
                signal.tp_price = original_tp  # Restore original

                if not validation_result:
                    logger.error(f"❌ TP/SL validation failed for {signal.symbol}: Invalid TP/SL values")
                    return None
            else:
                if not self._validate_tp_sl(signal, adjusted_sl):
                    logger.error(f"❌ TP/SL validation failed for {signal.symbol}: Invalid TP/SL values")
                    return None

            # Convert all numeric values to float to prevent Decimal JSON serialization errors
            adjusted_sl = float(adjusted_sl)
            tp_price = float(tp_price) if tp_price else None
            volume = float(volume)
            entry_price = float(signal.entry_price) if signal.entry_price else None

            # 🛑 CRITICAL FAILSAFE: Double-check for duplicate positions AND pending commands before creating command
            duplicate_trades = db.query(Trade).filter(
                and_(
                    Trade.account_id == account_id,
                    Trade.symbol == signal.symbol,
                    Trade.timeframe == signal.timeframe,
                    Trade.status == 'open'
                )
            ).count()

            # ✅ CRITICAL: Also check for pending commands (race condition prevention)
            duplicate_commands = db.query(Command).filter(
                and_(
                    Command.account_id == account_id,
                    Command.command_type == 'OPEN_TRADE',
                    Command.status.in_(['pending', 'processing']),
                    Command.payload['symbol'].astext == signal.symbol,
                    Command.payload['timeframe'].astext == signal.timeframe
                )
            ).count()

            duplicate_check = duplicate_trades + duplicate_commands

            if duplicate_check > 0:
                logger.error(f"🚨 FAILSAFE TRIGGERED: Prevented duplicate trade! {signal.symbol} {signal.timeframe} already has {duplicate_trades} open trade(s) + {duplicate_commands} pending command(s)")
                return  # ABORT command creation

            logger.info(f"✓ Duplicate check passed: No open {signal.symbol} {signal.timeframe} positions or pending commands")

            # ✅ CRITICAL: SL ENFORCEMENT - Validate SL before trade execution
            from sl_enforcement import get_sl_enforcement
            sl_enforcer = get_sl_enforcement()

            sl_validation = sl_enforcer.validate_trade_sl(
                db=db,
                symbol=signal.symbol,
                signal_type=signal.signal_type,
                entry_price=float(signal.entry_price),
                sl_price=float(adjusted_sl) if adjusted_sl else 0,
                volume=float(volume)
            )

            if not sl_validation['valid']:
                logger.error(
                    f"🚨 TRADE REJECTED: {signal.symbol} {signal.signal_type} | "
                    f"{sl_validation['reason']} | "
                    f"Potential Loss: {sl_validation['max_loss_eur']:.2f} EUR"
                )

                # Log to AI Decision Log
                from ai_decision_log import log_auto_trade_decision
                log_auto_trade_decision(
                    account_id=account_id,
                    symbol=signal.symbol,
                    timeframe=signal.timeframe,
                    signal_id=signal.id,
                    decision='REJECTED',
                    reason=f"SL Enforcement: {sl_validation['reason']}",
                    confidence=float(signal.confidence) if signal.confidence else 0,
                    details={
                        'entry_price': float(signal.entry_price),
                        'sl_price': float(adjusted_sl) if adjusted_sl else 0,
                        'volume': float(volume),
                        'max_loss_eur': sl_validation['max_loss_eur'],
                        'suggested_sl': sl_validation.get('suggested_sl')
                    }
                )

                return  # ABORT trade execution

            logger.info(
                f"✅ SL Validation passed: {signal.symbol} | "
                f"Max Loss: {sl_validation['max_loss_eur']:.2f} EUR | "
                f"SL: {adjusted_sl:.5f}"
            )

            # Store signal_id and timeframe in payload for trade linking
            payload_data = {
                'symbol': signal.symbol,
                'order_type': signal.signal_type,  # BUY or SELL
                'volume': volume,
                'sl': adjusted_sl,  # Use adjusted SL
                'tp': tp_price,
                'comment': f"Auto-Trade Signal #{signal.id} ({signal.timeframe})",
                'signal_id': signal.id,  # IMPORTANT: Link to signal
                'timeframe': signal.timeframe  # IMPORTANT: Store timeframe for limiting
            }

            command = Command(
                id=command_id,
                account_id=account_id,
                command_type='OPEN_TRADE',
                payload=payload_data,
                status='pending',
                created_at=datetime.utcnow()
            )

            db.add(command)
            db.commit()

            # Push to Redis command queue
            # CRITICAL FIX: Use adjusted_sl (not signal.sl_price) to match payload!
            command_data = {
                'id': command_id,
                'type': 'OPEN_TRADE',
                'symbol': signal.symbol,
                'order_type': signal.signal_type,
                'volume': volume,
                'sl': adjusted_sl,  # FIXED: Use adjusted SL
                'tp': tp_price,
                'comment': payload_data['comment']
            }

            self.redis.push_command(account_id, command_data)

            logger.info(f"✅ Trade command created: {command_id} - {signal.signal_type} {volume} {signal.symbol} @ {signal.entry_price} | SL: {adjusted_sl:.5f} | TP: {tp_price:.5f}")

            # Store command ID for execution tracking
            if not hasattr(self, 'pending_commands'):
                self.pending_commands = {}
            self.pending_commands[command_id] = {
                'signal_id': signal.id,
                'account_id': account_id,  # ✅ NEW: Store account_id for logging
                'symbol': signal.symbol,
                'created_at': datetime.utcnow(),
                'timeout_at': datetime.utcnow() + timedelta(minutes=5),
                'retry_count': 0  # ✅ NEW: Track retries
            }

            return command

        except Exception as e:
            logger.error(f"Error creating trade command: {e}")
            db.rollback()
            return None

    def _get_signal_hash(self, signal: TradingSignal) -> str:
        """
        Generate a hash for a signal based on its key properties.
        This allows detecting when a signal is updated with new values.

        ✅ FIX: Added signal ID and timestamp to prevent hash collisions
        """
        import hashlib

        # Create hash from key signal properties
        # Include signal ID and timestamp to ensure uniqueness
        # NOTE: Signals are GLOBAL (no account_id) since database migration
        timestamp_str = signal.created_at.isoformat() if signal.created_at else 'no_time'
        hash_string = (
            f"{signal.id}_{signal.symbol}_{signal.timeframe}_"
            f"{signal.signal_type}_{signal.confidence:.2f}_{signal.entry_price:.5f}_"
            f"{timestamp_str}"
        )
        return hashlib.md5(hash_string.encode()).hexdigest()

    def process_new_signals(self, db: Session):
        """Process new trading signals"""
        try:
            # ✅ FIX: Get account_id since signals are now GLOBAL (no account_id field)
            from models import Account
            account = db.query(Account).first()
            if not account:
                logger.error("❌ No account found in database - cannot process signals")
                return
            account_id = account.id

            # Get recent signals (last 10 minutes OR status='active')
            # This catches both new and updated signals
            cutoff_time = datetime.utcnow() - timedelta(minutes=10)

            signals = db.query(TradingSignal).filter(
                and_(
                    TradingSignal.signal_type.in_(['BUY', 'SELL']),
                    # Get signals that are either recent OR still active
                    or_(
                        TradingSignal.created_at >= cutoff_time,
                        TradingSignal.status == 'active'
                    )
                )
            ).order_by(TradingSignal.created_at.desc()).all()

            # Count how many are truly new (not seen before)
            new_count = 0
            signals_to_process = []
            
            for signal in signals:
                # Generate hash based on signal properties
                signal_hash = self._get_signal_hash(signal)

                # ✅ CRITICAL FIX: ALWAYS check if position exists for this signal
                # This prevents duplicates on container restart when processed_signal_hashes is empty
                # IMPORTANT: Check by symbol ONLY, not timeframe! Multiple timeframes can signal same symbol
                # but we only want ONE position per symbol at a time
                existing_position = db.query(Trade).filter(
                    and_(
                        Trade.account_id == account_id,
                        Trade.symbol == signal.symbol,
                        Trade.status == 'open'
                    )
                ).first()

                logger.debug(f"🔍 Position check for {signal.symbol} {signal.timeframe}: existing_position={existing_position is not None} (ticket={existing_position.ticket if existing_position else 'None'})")

                if existing_position:
                    # Position exists - skip signal and mark as processed
                    logger.info(f"⏭️  SKIPPING {signal.symbol} {signal.timeframe} signal - position #{existing_position.ticket} already open")
                    if signal_hash not in self.processed_signal_hashes:
                        # After restart, repopulate hash to prevent reprocessing
                        self.processed_signal_hashes[signal_hash] = {
                            'signal_id': signal.id,
                            'processed_at': datetime.utcnow(),
                            'symbol': signal.symbol,
                            'timeframe': signal.timeframe
                        }
                    continue

                # Check if we've already processed this signal hash
                if signal_hash in self.processed_signal_hashes:
                    # Position was closed - remove hash and re-evaluate signal
                    logger.info(f"♻️  Signal {signal.symbol} {signal.timeframe}: Position closed, re-evaluating signal")
                    del self.processed_signal_hashes[signal_hash]

                # This is a new/updated signal version OR position was closed
                new_count += 1
                signals_to_process.append(signal)
                
                # Mark this version as processed
                self.processed_signal_hashes[signal_hash] = {
                    'signal_id': signal.id,
                    'processed_at': datetime.utcnow(),
                    'symbol': signal.symbol,
                    'timeframe': signal.timeframe
                }

            logger.info(f"🔍 Auto-trader found {len(signals)} signals ({new_count} new/updated), {len(self.processed_signal_hashes)} tracked hashes")

            # Process new/updated signals
            for signal in signals_to_process:
                # 🔒 CRITICAL FIX: Acquire Redis lock BEFORE position checks and hold until trade command created
                # This prevents race conditions where multiple workers open duplicate positions
                lock_key = f"position_check:{account_id}:{signal.symbol}:{signal.timeframe}"
                lock_acquired = False

                try:
                    # Try to acquire lock with 60-second timeout (longer to cover entire trade creation)
                    lock_acquired = self.redis.client.set(
                        lock_key, "1", nx=True, ex=60
                    )

                    if not lock_acquired:
                        # Another worker is processing this symbol+timeframe - skip
                        logger.info(f"⏭️  Skipping signal #{signal.id} ({signal.symbol} {signal.timeframe}): Another worker is processing")
                        continue

                    logger.debug(f"🔒 Acquired lock for {signal.symbol} {signal.timeframe}")

                except Exception as lock_error:
                    logger.warning(f"Redis lock error for {signal.symbol} {signal.timeframe}: {lock_error}")
                    # Continue without lock (fail-open for availability)

                # Check if should execute
                should_exec = self.should_execute_signal(signal, db, account_id)
                if not should_exec['execute']:
                    logger.info(f"⏭️  Skipping signal #{signal.id} ({signal.symbol} {signal.timeframe}): {should_exec['reason']}")
                    # Release lock before continuing
                    if lock_acquired:
                        try:
                            self.redis.client.delete(lock_key)
                            logger.debug(f"🔓 Released lock for {signal.symbol} {signal.timeframe} (signal rejected)")
                        except Exception as e:
                            logger.error(f"Failed to release lock: {e}")
                    
                    # Log decision to AI Decision Log
                    from ai_decision_log import AIDecisionLogger
                    decision_logger = AIDecisionLogger()
                    decision_logger.log_decision(
                        account_id=account_id,
                        decision_type='SIGNAL_SKIP',
                        decision='REJECTED',
                        primary_reason=should_exec['reason'],
                        detailed_reasoning={
                            'signal_id': signal.id,
                            'symbol': signal.symbol,
                            'timeframe': signal.timeframe,
                            'signal_type': signal.signal_type,
                            'confidence': float(signal.confidence) if signal.confidence else None,
                            'entry_price': float(signal.entry_price) if signal.entry_price else None
                        },
                        symbol=signal.symbol,
                        timeframe=signal.timeframe,
                        signal_id=signal.id,
                        impact_level='LOW',
                        confidence_score=float(signal.confidence) if signal.confidence else None
                    )

                    # Check if symbol is disabled - create shadow trade
                    from models import SymbolPerformanceTracking
                    perf = db.query(SymbolPerformanceTracking).filter(
                        SymbolPerformanceTracking.account_id == account_id,
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

                # ✅ NEW: Check for opportunity cost - should we replace existing trades?
                from trade_replacement_manager import get_trade_replacement_manager

                trm = get_trade_replacement_manager()

                # Check if better signal warrants closing existing trades
                replacement_result = trm.process_opportunity_cost_management(
                    db=db,
                    account_id=account_id,
                    new_signal=signal
                )

                if replacement_result['trades_closed'] > 0:
                    logger.info(
                        f"🔄 Opportunity Cost: Closed {replacement_result['trades_closed']} trades "
                        f"for better signal #{signal.id} ({signal.symbol} {signal.confidence}%)"
                    )

                    # Log to AI Decision Log
                    from ai_decision_log import AIDecisionLogger
                    decision_logger = AIDecisionLogger()
                    decision_logger.log_decision(
                        account_id=account_id,
                        decision_type='TRADE_REPLACEMENT',
                        decision='APPROVED',
                        primary_reason=f"Replaced {replacement_result['trades_closed']} trades for better opportunity",
                        detailed_reasoning={
                            'signal_id': signal.id,
                            'symbol': signal.symbol,
                            'confidence': float(signal.confidence) if signal.confidence else None,
                            'trades_closed': replacement_result['trades_closed'],
                            'reasons': replacement_result['reasons']
                        },
                        symbol=signal.symbol,
                        impact_level='MEDIUM',
                        confidence_score=float(signal.confidence) if signal.confidence else None
                    )

                # Check for existing open position for same symbol+timeframe
                # (After potential replacement - there might still be positions we don't want to replace)
                # ✅ DYNAMIC LIMIT: Count existing trades and compare against confidence-based limit
                existing_trades_count = db.query(Trade).filter(
                    and_(
                        Trade.account_id == account_id,
                        Trade.symbol == signal.symbol,
                        Trade.timeframe == signal.timeframe,
                        Trade.status == 'open'
                    )
                ).count()

                # Calculate max allowed trades based on confidence
                signal_confidence = float(signal.confidence) if signal.confidence else 50.0
                max_trades_for_confidence = calculate_max_trades_for_confidence(signal_confidence)

                if existing_trades_count >= max_trades_for_confidence:
                    logger.info(
                        f"⏭️  Skipping signal #{signal.id} ({signal.symbol} {signal.timeframe}): "
                        f"Already have {existing_trades_count} open positions "
                        f"(max for {signal_confidence:.1f}% confidence: {max_trades_for_confidence})"
                    )
                    continue

                # Check risk limits
                risk_check = self.check_risk_limits(db, account_id)
                if not risk_check['allowed']:
                    logger.warning(f"⚠️  Risk limit blocked signal #{signal.id}: {risk_check['reason']}")
                    continue

                # Calculate position size with dynamic risk adjustment
                base_volume = self.calculate_position_size(db, account_id, signal)

                # ✅ NEW: Apply symbol-specific risk multiplier
                try:
                    from symbol_dynamic_manager import SymbolDynamicManager
                    symbol_manager = SymbolDynamicManager(account_id=account_id)
                    config = symbol_manager.get_config(db, signal.symbol, signal.signal_type)

                    # Apply risk multiplier
                    adjusted_volume = base_volume * float(config.risk_multiplier)

                    # Clamp to safe limits
                    volume = max(0.01, min(adjusted_volume, 1.0))

                    if config.risk_multiplier != 1.0:
                        logger.info(
                            f"📊 {signal.symbol} {signal.signal_type}: "
                            f"Volume adjusted by risk multiplier {config.risk_multiplier}x: "
                            f"{base_volume:.2f} → {volume:.2f}"
                        )
                except Exception as e:
                    logger.warning(f"Could not apply risk multiplier: {e}")
                    volume = base_volume

                # Create trade command
                command = self.create_trade_command(db, signal, volume)

                # 🔓 CRITICAL: Release lock IMMEDIATELY after trade command created
                # This prevents holding the lock unnecessarily and allows other workers to proceed
                if lock_acquired:
                    try:
                        self.redis.client.delete(lock_key)
                        logger.debug(f"🔓 Released lock for {signal.symbol} {signal.timeframe} (trade command created)")
                        lock_acquired = False  # Mark as released
                    except Exception as e:
                        logger.error(f"Failed to release lock: {e}")

                if command:
                    logger.info(f"🚀 Auto-Trade executed: Signal #{signal.id} → Command {command.id}")

                    # Log successful trade command to AI Decision Log
                    from ai_decision_log import AIDecisionLogger
                    decision_logger = AIDecisionLogger()
                    decision_logger.log_decision(
                        account_id=account_id,
                        decision_type='TRADE_OPEN',
                        decision='APPROVED',
                        primary_reason=f"Signal #{signal.id} approved for trading",
                        detailed_reasoning={
                            'signal_id': signal.id,
                            'command_id': command.id,
                            'symbol': signal.symbol,
                            'timeframe': signal.timeframe,
                            'signal_type': signal.signal_type,
                            'confidence': float(signal.confidence) if signal.confidence else None,
                            'entry_price': float(signal.entry_price) if signal.entry_price else None,
                            'volume': float(volume),
                            'sl': float(command.payload.get('sl')) if command.payload.get('sl') else None,
                            'tp': float(command.payload.get('tp')) if command.payload.get('tp') else None
                        },
                        symbol=signal.symbol,
                        timeframe=signal.timeframe,
                        signal_id=signal.id,
                        impact_level='HIGH',
                        confidence_score=float(signal.confidence) if signal.confidence else None
                    )

        except Exception as e:
            logger.error(f"Error processing signals: {e}")

    def cleanup_processed_signals(self):
        """
        Clean up old processed signal hashes to prevent unbounded memory growth.

        Keeps only hashes from the last hour to allow signal re-processing.
        Runs every auto-trade iteration (every 10 seconds).
        """
        if len(self.processed_signal_hashes) > 100:
            cutoff_time = datetime.utcnow() - timedelta(hours=1)
            
            # Remove old hashes
            hashes_to_remove = []
            for hash_key, hash_data in self.processed_signal_hashes.items():
                if hash_data['processed_at'] < cutoff_time:
                    hashes_to_remove.append(hash_key)
            
            for hash_key in hashes_to_remove:
                del self.processed_signal_hashes[hash_key]
            
            if hashes_to_remove:
                logger.debug(f"🧹 Cleaned up {len(hashes_to_remove)} old signal hashes (keeping last hour)")

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

                # ✅ ENHANCED: Circuit breaker with configurable threshold and cooldown
                # NOTE: Adjust thresholds based on connection reliability
                # - Lower threshold (3) = More sensitive, faster shutdown on issues
                # - Higher threshold (5-7) = More tolerant, allows temporary glitches
                CIRCUIT_BREAKER_THRESHOLD = 5  # Default: 5 consecutive failures
                CIRCUIT_BREAKER_COOLDOWN_MINUTES = 5  # Wait 5 min before auto-resume

                if self.failed_command_count >= CIRCUIT_BREAKER_THRESHOLD:
                    logger.critical(
                        f"🚨 CIRCUIT BREAKER TRIGGERED: {self.failed_command_count} consecutive command failures! "
                        f"(threshold: {CIRCUIT_BREAKER_THRESHOLD}) MT5 connection may be down. "
                        f"Disabling auto-trading for {CIRCUIT_BREAKER_COOLDOWN_MINUTES}min."
                    )
                    self.disable()
                    self.circuit_breaker_tripped = True
                    self.circuit_breaker_reason = (
                        f"{self.failed_command_count} consecutive command failures "
                        f"(threshold: {CIRCUIT_BREAKER_THRESHOLD})"
                    )
                    self.circuit_breaker_cooldown_until = (
                        datetime.utcnow() + timedelta(minutes=CIRCUIT_BREAKER_COOLDOWN_MINUTES)
                    )

                    # ✅ NEW: Log circuit breaker activation to AI Decision Log
                    try:
                        from ai_decision_log import log_circuit_breaker
                        log_circuit_breaker(
                            account_id=cmd_data.get('account_id', 1),
                            failed_count=self.failed_command_count,
                            reason=self.circuit_breaker_reason,
                            details={
                                'failed_commands': [cmd_id for cmd_id in commands_to_remove],
                                'last_error': error_msg if command and command.status == 'failed' else 'Timeout',
                                'timestamp': now.isoformat(),
                                'threshold': CIRCUIT_BREAKER_THRESHOLD,
                                'cooldown_minutes': CIRCUIT_BREAKER_COOLDOWN_MINUTES,
                                'cooldown_until': self.circuit_breaker_cooldown_until.isoformat()
                            }
                        )
                    except Exception as log_error:
                        logger.error(f"Failed to log circuit breaker to AI Decision Log: {log_error}")

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

    def check_stale_trades(self, db: Session):
        """
        ✅ NEW: Periodically check for trades that exceeded max hold time

        This runs independently of signal processing to ensure trades
        don't get stuck running too long.
        """
        try:
            from trade_replacement_manager import get_trade_replacement_manager
            from ai_decision_log import AIDecisionLogger

            # Get first account (in production you'd iterate over all accounts)
            from models import Account
            account = db.query(Account).first()
            if not account:
                return

            trm = get_trade_replacement_manager()

            # Check for stale trades (no new signal needed)
            result = trm.process_opportunity_cost_management(
                db=db,
                account_id=account.id,
                new_signal=None  # Just check max hold times
            )

            if result['trades_closed'] > 0:
                logger.warning(
                    f"⏰ Stale Trade Check: Closed {result['trades_closed']} trades "
                    f"exceeding max hold time"
                )

                # Log to AI Decision Log
                decision_logger = AIDecisionLogger()
                decision_logger.log_decision(
                    account_id=account.id,
                    decision_type='TRADE_TIMEOUT',
                    decision='FORCED_CLOSE',
                    primary_reason=f"Closed {result['trades_closed']} trades exceeding max hold time",
                    detailed_reasoning={
                        'trades_closed': result['trades_closed'],
                        'reasons': result['reasons'],
                        'check_type': 'periodic_stale_check'
                    },
                    impact_level='HIGH'
                )

        except Exception as e:
            logger.error(f"Error checking stale trades: {e}", exc_info=True)

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

            # Get latest tick for spread (NOTE: Ticks are now GLOBAL)
            latest_tick = db.query(Tick).filter_by(
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
                symbol=signal.symbol
            ).order_by(Tick.timestamp.desc()).limit(100).all()

            if len(recent_ticks) < 10:
                logger.warning(f"Insufficient tick history for {signal.symbol} spread check")
                return {'allowed': True}

            spreads = [abs(float(t.ask) - float(t.bid)) for t in recent_ticks]
            avg_spread = sum(spreads) / len(spreads)

            # Reject if spread is abnormally high (> 3x average for forex, 5x for metals)
            # Silver/Gold can have wider spreads than forex pairs
            MAX_SPREAD_MULTIPLIER = 5.0 if signal.symbol in ['XAGUSD', 'XAUUSD'] else 3.0
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
        """Get maximum allowed spread per symbol (from database configuration)"""
        from datetime import datetime
        from database import ScopedSession

        symbol_upper = symbol.upper()

        # Load risk profile for spread adjustment
        risk_profile = 'normal'
        db = None
        try:
            from models import GlobalSettings, SymbolSpreadConfig

            db = ScopedSession()

            settings = db.query(GlobalSettings).filter_by(id=1).first()
            if settings:
                risk_profile = settings.autotrade_risk_profile or 'normal'

            # Check if symbol has database configuration
            spread_config = db.query(SymbolSpreadConfig).filter_by(
                symbol=symbol_upper,
                enabled=True
            ).first()

            if spread_config:
                # Determine if it's Asian session (roughly 00:00-09:00 UTC)
                current_hour_utc = datetime.utcnow().hour
                is_asian_session = 0 <= current_hour_utc < 9

                # Determine if it's weekend (Saturday/Sunday)
                is_weekend = datetime.utcnow().weekday() >= 5

                # Use database configuration with session awareness
                max_spread = spread_config.get_max_spread(
                    risk_profile=risk_profile,
                    is_asian_session=is_asian_session,
                    is_weekend=is_weekend
                )

                logger.debug(
                    f"Spread limit for {symbol_upper}: {max_spread:.5f} "
                    f"(profile={risk_profile}, asian={is_asian_session}, weekend={is_weekend})"
                )
                return max_spread

        except Exception as e:
            logger.warning(f"Could not load spread config from database: {e}")
            # Fall through to hardcoded defaults
        finally:
            if db:
                db.close()

        # Fallback: Hardcoded spread limits (if no database config found)
        # Spread multiplier based on risk profile
        if risk_profile == 'moderate':
            multiplier = 0.8  # More conservative
        elif risk_profile == 'aggressive':
            multiplier = 2.0  # More tolerant of wide spreads
        else:  # normal
            multiplier = 1.2  # Slightly more tolerant than base

        # Base spread limits (fallback only)
        base_spread = 0.0

        # Forex major pairs: tight spreads expected
        if any(pair in symbol_upper for pair in ['EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF']):
            base_spread = 0.0003  # 3 pips

        # Forex minor pairs: wider spreads acceptable
        elif any(pair in symbol_upper for pair in ['EURGBP', 'EURJPY', 'GBPJPY']):
            base_spread = 0.0005  # 5 pips

        # Exotic pairs: even wider spreads
        elif any(curr in symbol_upper for curr in ['ZAR', 'TRY', 'MXN']):
            base_spread = 0.001  # 10 pips

        # Crypto: variable spreads (use percentage of price)
        elif any(crypto in symbol_upper for crypto in ['BTC', 'ETH', 'XRP']):
            base_spread = 100.0  # For crypto, allow larger absolute spreads

        # Gold/Silver (commodities have wider spreads)
        elif 'XAU' in symbol_upper:
            base_spread = 0.50  # $0.50
        elif 'XAG' in symbol_upper:
            base_spread = 0.10  # $0.10 (increased from 0.05 - silver has naturally wider spreads)

        # Indices
        elif any(idx in symbol_upper for idx in ['US30', 'US500', 'NAS100', 'DE40']):
            base_spread = 5.0  # 5 points

        # Default: conservative limit
        else:
            base_spread = 0.001  # 10 pips

        logger.debug(f"Spread limit for {symbol_upper}: {base_spread * multiplier:.5f} (fallback, profile={risk_profile})")

        # Apply risk profile multiplier
        return base_spread * multiplier

    def auto_trade_loop(self):
        """Main auto-trading loop"""
        logger.info(f"Auto-Trader loop started (interval: {self.check_interval}s)")

        while True:
            try:
                # ✅ NEW: Check circuit breaker cooldown for auto-resume
                if (self.circuit_breaker_tripped and
                    hasattr(self, 'circuit_breaker_cooldown_until') and
                    datetime.utcnow() >= self.circuit_breaker_cooldown_until):

                    logger.info(
                        f"⏰ Circuit breaker cooldown expired. Auto-resuming trading. "
                        f"Resetting failed command count from {self.failed_command_count} to 0."
                    )
                    self.circuit_breaker_tripped = False
                    self.circuit_breaker_reason = None
                    self.failed_command_count = 0
                    self.enable()  # Re-enable auto-trading

                if not self.enabled:
                    logger.debug("Auto-Trading disabled, waiting...")
                    time.sleep(self.check_interval)
                    continue

                db = ScopedSession()
                self.process_new_signals(db)
                self.check_pending_commands(db)  # Verify trade execution

                # ✅ NEW: Check for stale trades every 60 seconds
                if int(time.time()) % 60 < 10:
                    self.check_stale_trades(db)

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
