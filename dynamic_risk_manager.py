#!/usr/bin/env python3
"""
Dynamic Risk Manager - Automatically adjusts SL limits and R:R ratios based on:
1. Account balance (scales with growth/drawdown)
2. Global risk profile (conservative, moderate, aggressive)
3. Recent performance (adaptive risk)
4. Symbol-specific volatility

This ensures risk parameters are NEVER static and always appropriate for current conditions.
"""

import logging
from typing import Dict, Tuple
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import text
from models import Account, Trade
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RiskProfile:
    """Risk profile configuration"""
    name: str
    base_risk_percent: float  # % of account per trade
    max_loss_per_trade_percent: float  # Max % loss per trade
    max_daily_loss_percent: float  # Max % daily loss
    confidence_multiplier: float  # How much confidence affects risk

    # R:R Ratios (TP/SL multipliers)
    forex_tp_multiplier: float
    forex_sl_multiplier: float
    metals_tp_multiplier: float
    metals_sl_multiplier: float


class DynamicRiskManager:
    """
    Manages risk parameters dynamically based on account state and performance
    """

    # ========================================================================
    # RISK PROFILES
    # ========================================================================
    RISK_PROFILES = {
        'conservative': RiskProfile(
            name='conservative',
            base_risk_percent=0.5,  # 0.5% per trade
            max_loss_per_trade_percent=2.0,  # Max 2% per trade
            max_daily_loss_percent=5.0,  # Max 5% daily
            confidence_multiplier=1.0,  # Don't scale much with confidence
            forex_tp_multiplier=3.0,
            forex_sl_multiplier=0.7,
            metals_tp_multiplier=1.5,
            metals_sl_multiplier=0.4,
        ),
        'moderate': RiskProfile(
            name='moderate',
            base_risk_percent=1.0,  # 1% per trade (DEFAULT)
            max_loss_per_trade_percent=3.0,  # Max 3% per trade
            max_daily_loss_percent=8.0,  # Max 8% daily
            confidence_multiplier=1.2,  # Moderate confidence scaling
            forex_tp_multiplier=3.5,  # Current optimized values
            forex_sl_multiplier=0.8,
            metals_tp_multiplier=1.2,
            metals_sl_multiplier=0.4,
        ),
        'aggressive': RiskProfile(
            name='aggressive',
            base_risk_percent=2.0,  # 2% per trade
            max_loss_per_trade_percent=5.0,  # Max 5% per trade
            max_daily_loss_percent=12.0,  # Max 12% daily
            confidence_multiplier=1.5,  # Scale aggressively with confidence
            forex_tp_multiplier=4.0,
            forex_sl_multiplier=0.9,
            metals_tp_multiplier=1.5,
            metals_sl_multiplier=0.5,
        ),
    }

    def __init__(self, account_id: int, risk_profile: str = 'moderate'):
        """
        Initialize Dynamic Risk Manager

        Args:
            account_id: Account ID
            risk_profile: 'conservative', 'moderate', or 'aggressive'
        """
        self.account_id = account_id
        self.risk_profile_name = risk_profile

        if risk_profile not in self.RISK_PROFILES:
            logger.warning(f"Unknown risk profile '{risk_profile}', using 'moderate'")
            self.risk_profile_name = 'moderate'

        self.profile = self.RISK_PROFILES[self.risk_profile_name]

        # Cache for account info
        self._cached_balance = None
        self._cached_initial_balance = None
        self._cache_time = None
        self._cache_ttl = 300  # 5 minutes

    def _get_account_info(self, db: Session) -> Tuple[float, float]:
        """
        Get account balance and initial balance (with caching)

        Returns:
            (current_balance, initial_balance)
        """
        # Check cache
        if (self._cached_balance and self._cached_initial_balance
            and self._cache_time
            and (datetime.utcnow() - self._cache_time).total_seconds() < self._cache_ttl):
            return self._cached_balance, self._cached_initial_balance

        # Fetch from DB
        account = db.query(Account).filter_by(id=self.account_id).first()

        if not account:
            logger.error(f"Account {self.account_id} not found!")
            return 1000.0, 1000.0  # Fallback

        current_balance = float(account.balance or 1000.0)
        # Use balance as initial if initial_balance not available
        initial_balance = float(getattr(account, 'initial_balance', None) or current_balance)

        # Update cache
        self._cached_balance = current_balance
        self._cached_initial_balance = initial_balance
        self._cache_time = datetime.utcnow()

        return current_balance, initial_balance

    def get_account_growth_factor(self, db: Session) -> float:
        """
        Calculate account growth factor (1.0 = no growth, 1.5 = 50% growth, etc.)

        This is used to scale risk UP when account grows, and DOWN when it shrinks.
        """
        current, initial = self._get_account_info(db)

        if initial <= 0:
            return 1.0

        growth_factor = current / initial

        # Cap at reasonable limits
        growth_factor = max(0.5, min(3.0, growth_factor))

        return growth_factor

    def get_recent_performance_factor(self, db: Session, days: int = 7) -> float:
        """
        Calculate recent performance factor (0.5-1.5)

        Good performance (Profit Factor >1.5) → 1.2-1.5 (scale up)
        Neutral performance (PF ~1.0)         → 1.0 (no change)
        Bad performance (PF <0.7)            → 0.5-0.8 (scale down)
        """
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)

            # Get recent trades
            result = db.execute(text("""
                SELECT
                    SUM(CASE WHEN profit > 0 THEN profit ELSE 0 END) as total_wins,
                    SUM(CASE WHEN profit < 0 THEN profit ELSE 0 END) as total_losses,
                    COUNT(*) as trade_count
                FROM trades
                WHERE account_id = :account_id
                    AND created_at >= :cutoff
                    AND status = 'closed'
            """), {'account_id': self.account_id, 'cutoff': cutoff}).fetchone()

            if not result or result.trade_count < 10:
                # Not enough data, use neutral
                return 1.0

            total_wins = float(result.total_wins or 0)
            total_losses = abs(float(result.total_losses or 0))

            # Calculate Profit Factor
            if total_losses > 0:
                profit_factor = total_wins / total_losses
            else:
                profit_factor = 5.0 if total_wins > 0 else 1.0

            # Map Profit Factor to performance factor
            if profit_factor >= 2.0:
                performance_factor = 1.3  # Great performance, scale up
            elif profit_factor >= 1.5:
                performance_factor = 1.2
            elif profit_factor >= 1.0:
                performance_factor = 1.0  # Neutral
            elif profit_factor >= 0.7:
                performance_factor = 0.8  # Slightly bad
            else:
                performance_factor = 0.6  # Bad performance, scale down

            logger.info(
                f"📊 Recent Performance ({days}d): "
                f"PF={profit_factor:.2f}, Factor={performance_factor:.2f}"
            )

            return performance_factor

        except Exception as e:
            logger.error(f"Error calculating performance factor: {e}")
            return 1.0

    def get_dynamic_sl_limits(self, db: Session) -> Dict[str, float]:
        """
        Calculate dynamic SL limits based on account balance and risk profile

        Returns:
            Dict[symbol, max_loss_eur]
        """
        current_balance, _ = self._get_account_info(db)
        growth_factor = self.get_account_growth_factor(db)
        performance_factor = self.get_recent_performance_factor(db)

        # Combined adjustment factor
        adjustment_factor = growth_factor * performance_factor

        # Base max loss = account balance * max_loss_per_trade_percent / 100
        base_max_loss = current_balance * (self.profile.max_loss_per_trade_percent / 100)

        # Apply adjustment
        adjusted_max_loss = base_max_loss * adjustment_factor

        # Symbol-specific adjustments
        symbol_sl_limits = {
            'XAUUSD': adjusted_max_loss * 0.7,  # Gold: 70% of base (volatile)
            'XAGUSD': adjusted_max_loss * 0.6,  # Silver: 60% (very volatile)
            'BTCUSD': adjusted_max_loss * 1.2,  # Bitcoin: 120% (high WR, profitable)
            'ETHUSD': adjusted_max_loss * 0.9,
            'AUDUSD': adjusted_max_loss * 1.0,  # Forex majors: 100%
            'EURUSD': adjusted_max_loss * 1.0,
            'GBPUSD': adjusted_max_loss * 1.0,
            'USDJPY': adjusted_max_loss * 1.0,
            'US500.c': adjusted_max_loss * 0.8,  # Index: 80%
            'DE40.c': adjusted_max_loss * 0.7,
            'FOREX': adjusted_max_loss * 1.0,  # Default
            'DEFAULT': adjusted_max_loss * 0.8,
        }

        # Apply minimum limits (never go below these)
        min_limits = {
            'XAUUSD': 3.0,
            'XAGUSD': 2.5,
            'FOREX': 2.0,
            'DEFAULT': 2.5,
        }

        for symbol in symbol_sl_limits:
            min_limit = min_limits.get(symbol, min_limits['DEFAULT'])
            symbol_sl_limits[symbol] = max(min_limit, symbol_sl_limits[symbol])

        logger.info(
            f"💰 Dynamic SL Limits: "
            f"Balance={current_balance:.2f}, "
            f"Growth={growth_factor:.2f}x, "
            f"Performance={performance_factor:.2f}x, "
            f"Adjustment={adjustment_factor:.2f}x"
        )
        logger.info(f"   XAUUSD: ${symbol_sl_limits['XAUUSD']:.2f}, "
                   f"AUDUSD: ${symbol_sl_limits['AUDUSD']:.2f}, "
                   f"BTCUSD: ${symbol_sl_limits['BTCUSD']:.2f}")

        return symbol_sl_limits

    def get_dynamic_rr_ratios(self, db: Session) -> Dict[str, Dict[str, float]]:
        """
        Calculate dynamic R:R ratios (TP/SL multipliers) based on performance

        Returns:
            Dict with 'FOREX_MAJOR', 'METALS', etc. configurations
        """
        performance_factor = self.get_recent_performance_factor(db)

        # Scale TP/SL based on performance
        # Good performance → Wider TPs (let winners run)
        # Bad performance → Tighter TPs (take profits sooner)

        tp_scale = 1.0 + ((performance_factor - 1.0) * 0.3)  # +/- 30% max
        sl_scale = 1.0 - ((performance_factor - 1.0) * 0.15)  # +/- 15% max

        # Cap scaling
        tp_scale = max(0.8, min(1.3, tp_scale))
        sl_scale = max(0.85, min(1.15, sl_scale))

        configs = {
            'FOREX_MAJOR': {
                'atr_tp_multiplier': self.profile.forex_tp_multiplier * tp_scale,
                'atr_sl_multiplier': self.profile.forex_sl_multiplier * sl_scale,
                'max_tp_pct': 1.5,
                'min_sl_pct': 0.10,
            },
            'METALS': {
                'atr_tp_multiplier': self.profile.metals_tp_multiplier * tp_scale,
                'atr_sl_multiplier': self.profile.metals_sl_multiplier * sl_scale,
                'max_tp_pct': 1.5,
                'min_sl_pct': 0.2,
            },
        }

        logger.info(
            f"📐 Dynamic R:R Ratios (Profile: {self.profile.name}): "
            f"TP Scale={tp_scale:.2f}x, SL Scale={sl_scale:.2f}x"
        )
        logger.info(
            f"   FOREX: TP={configs['FOREX_MAJOR']['atr_tp_multiplier']:.2f}x, "
            f"SL={configs['FOREX_MAJOR']['atr_sl_multiplier']:.2f}x "
            f"(R:R={configs['FOREX_MAJOR']['atr_tp_multiplier']/configs['FOREX_MAJOR']['atr_sl_multiplier']:.2f}:1)"
        )
        logger.info(
            f"   METALS: TP={configs['METALS']['atr_tp_multiplier']:.2f}x, "
            f"SL={configs['METALS']['atr_sl_multiplier']:.2f}x "
            f"(R:R={configs['METALS']['atr_tp_multiplier']/configs['METALS']['atr_sl_multiplier']:.2f}:1)"
        )

        return configs

    def get_max_daily_loss_limit(self, db: Session) -> float:
        """
        Get dynamic max daily loss limit

        Returns:
            Max daily loss in EUR
        """
        current_balance, _ = self._get_account_info(db)
        return current_balance * (self.profile.max_daily_loss_percent / 100)

    def check_daily_loss_limit(self, db: Session) -> Tuple[bool, float, float]:
        """
        Check if daily loss limit is exceeded

        Returns:
            (is_exceeded, current_daily_loss, limit)
        """
        try:
            today = datetime.utcnow().date()

            result = db.execute(text("""
                SELECT COALESCE(SUM(profit), 0) as daily_pnl
                FROM trades
                WHERE account_id = :account_id
                    AND DATE(created_at) = :today
                    AND status = 'closed'
            """), {'account_id': self.account_id, 'today': today}).fetchone()

            daily_pnl = float(result.daily_pnl or 0)
            limit = self.get_max_daily_loss_limit(db)

            is_exceeded = daily_pnl < -limit

            if is_exceeded:
                logger.warning(
                    f"⚠️ Daily Loss Limit EXCEEDED! "
                    f"Loss: ${abs(daily_pnl):.2f} / Limit: ${limit:.2f}"
                )

            return is_exceeded, daily_pnl, limit

        except Exception as e:
            logger.error(f"Error checking daily loss limit: {e}")
            return False, 0.0, 0.0

    def get_position_size_multiplier(self, confidence: float) -> float:
        """
        Get position size multiplier based on confidence and risk profile

        Args:
            confidence: Signal confidence (0-100)

        Returns:
            Multiplier (0.5 - 1.5)
        """
        if confidence >= 85:
            return 1.0 * self.profile.confidence_multiplier
        elif confidence >= 75:
            return 0.9 * self.profile.confidence_multiplier
        elif confidence >= 65:
            return 0.8
        else:
            return 0.6


# ============================================================================
# GLOBAL SINGLETON
# ============================================================================
_risk_managers = {}


def get_risk_manager(account_id: int, risk_profile: str = 'moderate') -> DynamicRiskManager:
    """
    Get DynamicRiskManager instance (singleton per account)

    Args:
        account_id: Account ID
        risk_profile: 'conservative', 'moderate', or 'aggressive'
    """
    global _risk_managers

    key = f"{account_id}_{risk_profile}"

    if key not in _risk_managers:
        _risk_managers[key] = DynamicRiskManager(account_id, risk_profile)

    return _risk_managers[key]


def update_sl_enforcement_limits(db: Session, account_id: int, risk_profile: str = 'moderate'):
    """
    Update SL Enforcement limits dynamically

    Call this periodically (e.g., daily) to adjust limits based on account state
    """
    from sl_enforcement import SLEnforcement

    risk_manager = get_risk_manager(account_id, risk_profile)
    dynamic_limits = risk_manager.get_dynamic_sl_limits(db)

    # Update SL Enforcement limits (in-place modification)
    SLEnforcement.MAX_LOSS_PER_TRADE.update(dynamic_limits)

    logger.info("✅ SL Enforcement limits updated with dynamic values")


def update_smart_tpsl_ratios(db: Session, account_id: int, risk_profile: str = 'moderate'):
    """
    Update Smart TP/SL ratios dynamically

    Call this periodically (e.g., weekly) to adjust R:R ratios based on performance
    """
    from smart_tp_sl import SymbolConfig

    risk_manager = get_risk_manager(account_id, risk_profile)
    dynamic_ratios = risk_manager.get_dynamic_rr_ratios(db)

    # Update SymbolConfig (in-place modification)
    for asset_class, config in dynamic_ratios.items():
        if asset_class in SymbolConfig.ASSET_CLASSES:
            SymbolConfig.ASSET_CLASSES[asset_class].update(config)

    logger.info("✅ Smart TP/SL ratios updated with dynamic values")
