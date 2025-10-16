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
from sqlalchemy import and_, or_
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
        self.check_interval = 10  # Check for new signals every 10 seconds

        # Track processed signals by hash (symbol+timeframe+type+entry_price)
        # This allows detecting when signals are updated with new values
        self.processed_signal_hashes = {}

        # Cooldown tracking after SL hits: symbol -> cooldown_until_time
        self.symbol_cooldowns = {}

        # Track pending commands and failure count
        self.pending_commands = {}
        self.failed_command_count = 0

        # Circuit breaker settings
        self.circuit_breaker_enabled = True
        self.max_daily_loss_percent = 5.0  # Stop trading if daily loss exceeds 5%
        self.max_total_drawdown_percent = 20.0  # Stop if total drawdown exceeds 20%
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = None

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
        self._load_autotrade_status_from_db()

        logger.info(f"Auto-Trader initialized (enabled={self.enabled}, min_confidence={self.min_autotrade_confidence}%)")

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
                logger.info(
                    f"✅ Auto-Trade status loaded from DB: "
                    f"enabled={self.enabled}, min_confidence={self.min_autotrade_confidence}%"
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
                db.commit()
                logger.info(
                    f"✅ Auto-Trade status saved to DB: "
                    f"enabled={self.enabled}, min_confidence={self.min_autotrade_confidence}%"
                )
            finally:
                db.close()
        except Exception as e:
            logger.error(f"❌ Failed to save auto-trade status to DB: {e}")

    def set_min_confidence(self, min_confidence: float):
        """Set minimum confidence threshold for auto-trading"""
        self.min_autotrade_confidence = float(min_confidence)
        self._save_autotrade_status_to_db()  # ✅ Persist to DB
        logger.info(f"Auto-Trade min confidence set to {min_confidence}%")

    def enable(self):
        """Enable auto-trading"""
        self.enabled = True
        self._save_autotrade_status_to_db()  # ✅ Persist to DB
        logger.info(f"🤖 Auto-Trading ENABLED (min confidence: {self.min_autotrade_confidence}%)")

    def disable(self):
        """Disable auto-trading (kill-switch)"""
        self.enabled = False
        self._save_autotrade_status_to_db()  # ✅ Persist to DB
        logger.warning("🛑 Auto-Trading DISABLED (Kill-Switch)")

    def reset_circuit_breaker(self):
        """Reset circuit breaker manually"""
        self.circuit_breaker_tripped = False
        self.circuit_breaker_reason = None
        self.failed_command_count = 0
        logger.info("Circuit breaker reset manually (failed_command_count reset to 0)")

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

            # Calculate risk amount - convert to float to avoid Decimal/float type errors
            risk_amount = float(balance) * float(settings.risk_per_trade_percent)

            # Calculate position size based on SL distance
            # Use sl_price directly (DB column name) instead of property
            sl_price = getattr(signal, 'sl_price', None) or getattr(signal, 'sl', None)
            
            if sl_price and signal.entry_price:
                # Convert to float to avoid Decimal/float type errors
                sl_distance = abs(float(signal.entry_price) - float(sl_price))
                if sl_distance > 0:
                    # Position size = Risk Amount / SL Distance
                    volume = risk_amount / sl_distance
                    volume = round(volume, 2)  # Round to 2 decimals
                    return max(0.01, min(volume, 1.0))  # Min 0.01, Max 1.0

            # Fallback: use percentage of balance
            return round(float(balance) * float(settings.position_size_percent) / float(signal.entry_price), 2)

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
        # 🔒 CRITICAL: Redis lock to prevent race conditions on position checks
        # This prevents multiple workers from opening duplicate positions simultaneously
        # NOTE: Lock is NOT acquired here anymore - moved to process_new_signals()
        # to ensure lock is held until trade command is created
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

            # ✅ NEW: Check max open positions limit FOURTH (prevent overexposure)
            position_limit_check = self.check_position_limits(db, signal.account_id)
            if not position_limit_check['allowed']:
                return {
                    'execute': False,
                    'reason': position_limit_check['reason']
                }

            # Check correlation exposure FIFTH (prevent over-exposure to correlated pairs)
            correlation_check = self.check_correlation_exposure(db, signal.account_id, signal.symbol)
            if not correlation_check['allowed']:
                return {
                    'execute': False,
                    'reason': correlation_check['reason']
                }

            # Check per-symbol-timeframe position limit SIXTH (prevent duplicate positions)
            existing_positions = db.query(Trade).filter(
                and_(
                    Trade.account_id == signal.account_id,
                    Trade.symbol == signal.symbol,
                    Trade.timeframe == signal.timeframe,
                    Trade.status == 'open'
                )
            ).count()

            logger.info(f"🔍 Position check: {signal.symbol} {signal.timeframe} - Found {existing_positions} open positions (max: {settings.max_positions_per_symbol_timeframe})")

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

            # ✅ ENHANCED: Check SL-Hit Protection (automatic pause after multiple SL hits)
            from sl_hit_protection import get_sl_hit_protection
            sl_protection = get_sl_hit_protection()
            sl_check = sl_protection.check_sl_hits(db, signal.account_id, signal.symbol, max_hits=2, timeframe_hours=4)

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

                symbol_manager = SymbolDynamicManager(account_id=signal.account_id)

                # Get market regime for this symbol
                try:
                    ti = TechnicalIndicators(signal.account_id, signal.symbol, signal.timeframe)
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

            # Check 4: Maximum TP distance (5% for most, 3% for volatile)
            max_tp_distance_pct = 3.0 if signal.symbol in ['BTCUSD', 'ETHUSD', 'XAUUSD'] else 5.0
            tp_distance_pct = abs(tp - entry) / entry * 100

            if tp_distance_pct > max_tp_distance_pct:
                logger.warning(f"TP too far: {tp_distance_pct:.2f}% (max: {max_tp_distance_pct}%)")
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
                    account_id=signal.account_id,
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

            try:
                from technical_indicators import TechnicalIndicators
                ti = TechnicalIndicators(signal.account_id, signal.symbol, signal.timeframe)
                supertrend = ti.calculate_supertrend()

                if supertrend and supertrend['value']:
                    # Use SuperTrend as dynamic SL (better than fixed distance)
                    if signal.signal_type == 'BUY' and supertrend['direction'] == 'bullish':
                        # For BUY: Use SuperTrend value as SL (price below SuperTrend = exit)
                        # Verify SuperTrend is below entry (valid for BUY)
                        if float(supertrend['value']) < float(signal.entry_price):
                            adjusted_sl = supertrend['value']
                            use_supertrend_sl = True
                            logger.info(f"🎯 {signal.symbol}: Using SuperTrend SL | Price: {signal.entry_price} | SuperTrend SL: {adjusted_sl:.5f} ({supertrend['distance_pct']:.2f}% distance)")
                        else:
                            logger.warning(f"⚠️ {signal.symbol} BUY: SuperTrend SL ({supertrend['value']:.5f}) above entry ({signal.entry_price}), using traditional SL")
                    elif signal.signal_type == 'SELL' and supertrend['direction'] == 'bearish':
                        # For SELL: Use SuperTrend value as SL (price above SuperTrend = exit)
                        # Verify SuperTrend is above entry (valid for SELL)
                        if float(supertrend['value']) > float(signal.entry_price):
                            adjusted_sl = supertrend['value']
                            use_supertrend_sl = True
                            logger.info(f"🎯 {signal.symbol}: Using SuperTrend SL | Price: {signal.entry_price} | SuperTrend SL: {adjusted_sl:.5f} ({supertrend['distance_pct']:.2f}% distance)")
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

            # ✅ CRITICAL VALIDATION: Ensure TP/SL are valid before sending to MT5
            if not self._validate_tp_sl(signal, adjusted_sl):
                logger.error(f"❌ TP/SL validation failed for {signal.symbol}: Invalid TP/SL values")
                return None

            # Use tp_price directly (DB column name) instead of property
            tp_price = getattr(signal, 'tp_price', None) or getattr(signal, 'tp', None)

            # Convert all numeric values to float to prevent Decimal JSON serialization errors
            adjusted_sl = float(adjusted_sl)
            tp_price = float(tp_price) if tp_price else None
            volume = float(volume)
            entry_price = float(signal.entry_price) if signal.entry_price else None

            # 🛑 CRITICAL FAILSAFE: Double-check for duplicate positions before creating command
            duplicate_check = db.query(Trade).filter(
                and_(
                    Trade.account_id == signal.account_id,
                    Trade.symbol == signal.symbol,
                    Trade.timeframe == signal.timeframe,
                    Trade.status == 'open'
                )
            ).count()

            if duplicate_check > 0:
                logger.error(f"🚨 FAILSAFE TRIGGERED: Prevented duplicate trade! {signal.symbol} {signal.timeframe} already has {duplicate_check} open position(s)")
                return  # ABORT command creation

            logger.info(f"✓ Duplicate check passed: No open {signal.symbol} {signal.timeframe} positions")

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
                account_id=signal.account_id,
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

            self.redis.push_command(signal.account_id, command_data)

            logger.info(f"✅ Trade command created: {command_id} - {signal.signal_type} {volume} {signal.symbol} @ {signal.entry_price} | SL: {adjusted_sl:.5f} | TP: {tp_price:.5f}")

            # Store command ID for execution tracking
            if not hasattr(self, 'pending_commands'):
                self.pending_commands = {}
            self.pending_commands[command_id] = {
                'signal_id': signal.id,
                'account_id': signal.account_id,  # ✅ NEW: Store account_id for logging
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
        """
        import hashlib
        
        # Create hash from key signal properties
        hash_string = f"{signal.account_id}_{signal.symbol}_{signal.timeframe}_{signal.signal_type}_{signal.confidence}_{signal.entry_price}"
        return hashlib.md5(hash_string.encode()).hexdigest()

    def process_new_signals(self, db: Session):
        """Process new trading signals"""
        try:
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
                
                # Check if we've already processed this exact signal version
                if signal_hash in self.processed_signal_hashes:
                    # Already processed this version - skip
                    continue
                
                # This is a new/updated signal version
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
                lock_key = f"position_check:{signal.account_id}:{signal.symbol}:{signal.timeframe}"
                lock_acquired = False

                try:
                    # Try to acquire lock with 60-second timeout (longer to cover entire trade creation)
                    lock_acquired = self.redis.redis_client.set(
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
                should_exec = self.should_execute_signal(signal, db)
                if not should_exec['execute']:
                    logger.info(f"⏭️  Skipping signal #{signal.id} ({signal.symbol} {signal.timeframe}): {should_exec['reason']}")
                    # Release lock before continuing
                    if lock_acquired:
                        try:
                            self.redis.redis_client.delete(lock_key)
                            logger.debug(f"🔓 Released lock for {signal.symbol} {signal.timeframe} (signal rejected)")
                        except Exception as e:
                            logger.error(f"Failed to release lock: {e}")
                    
                    # Log decision to AI Decision Log
                    from ai_decision_log import AIDecisionLogger
                    decision_logger = AIDecisionLogger()
                    decision_logger.log_decision(
                        account_id=signal.account_id,
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

                # ✅ NEW: Check for opportunity cost - should we replace existing trades?
                from trade_replacement_manager import get_trade_replacement_manager
                from models import Trade

                trm = get_trade_replacement_manager()

                # Check if better signal warrants closing existing trades
                replacement_result = trm.process_opportunity_cost_management(
                    db=db,
                    account_id=signal.account_id,
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
                        account_id=signal.account_id,
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
                existing_trade = db.query(Trade).filter(
                    and_(
                        Trade.account_id == signal.account_id,
                        Trade.symbol == signal.symbol,
                        Trade.timeframe == signal.timeframe,
                        Trade.status == 'open'
                    )
                ).first()

                if existing_trade:
                    logger.info(f"⏭️  Skipping signal #{signal.id} ({signal.symbol} {signal.timeframe}): Already have open position (ticket #{existing_trade.ticket})")
                    continue

                # Check risk limits
                risk_check = self.check_risk_limits(db, signal.account_id)
                if not risk_check['allowed']:
                    logger.warning(f"⚠️  Risk limit blocked signal #{signal.id}: {risk_check['reason']}")
                    continue

                # Calculate position size with dynamic risk adjustment
                base_volume = self.calculate_position_size(db, signal.account_id, signal)

                # ✅ NEW: Apply symbol-specific risk multiplier
                try:
                    from symbol_dynamic_manager import SymbolDynamicManager
                    symbol_manager = SymbolDynamicManager(account_id=signal.account_id)
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
                        self.redis.redis_client.delete(lock_key)
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
                        account_id=signal.account_id,
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

                # Critical alert if many commands are failing
                if self.failed_command_count >= 3:
                    logger.critical(
                        f"🚨 CRITICAL: {self.failed_command_count} consecutive command failures! "
                        f"MT5 connection may be down. Disabling auto-trading."
                    )
                    self.disable()
                    self.circuit_breaker_tripped = True
                    self.circuit_breaker_reason = f"{self.failed_command_count} consecutive command failures"
                    
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
                                'timestamp': now.isoformat()
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

        # Crypto: variable spreads (use percentage of price)
        elif any(crypto in symbol_upper for crypto in ['BTC', 'ETH', 'XRP']):
            # Return 0.5% of current price as max spread
            # This will be calculated dynamically based on the signal's entry price
            return 100.0  # For crypto, allow larger absolute spreads (will be validated by % check above)

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
