"""
Symbol Dynamic Manager
Manages per-symbol trading configurations with auto-adjusting risk and confidence thresholds

This module handles:
- Real-time performance tracking per symbol+direction
- Automatic confidence threshold adjustments
- Dynamic risk scaling based on rolling performance
- Auto-pause after consecutive losses
- Market regime preference learning
- Rolling 20-trade performance window
"""

import logging
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Dict, List, Optional, Tuple
from collections import deque
from sqlalchemy.orm import Session

from models import SymbolTradingConfig, Trade, TradingSignal
from database import ScopedSession

logger = logging.getLogger(__name__)


class SymbolDynamicManager:
    """Manages dynamic per-symbol trading configurations"""

    # Configuration constants - Enhanced for loss-adaptive trading
    MIN_CONFIDENCE_THRESHOLD = Decimal('45.0')  # Never go below 45% (raised from 40% to match new minimum)
    MAX_CONFIDENCE_THRESHOLD = Decimal('80.0')  # Never go above 80%
    MIN_RISK_MULTIPLIER = Decimal('0.1')  # Min 10% of normal risk
    MAX_RISK_MULTIPLIER = Decimal('2.0')  # Max 200% of normal risk

    # Adjustment rates - More aggressive loss protection
    CONFIDENCE_INCREASE_ON_LOSS = Decimal('5.0')  # Increase confidence req by 5% per loss (raised from 2%)
    CONFIDENCE_DECREASE_ON_WIN = Decimal('1.0')   # Decrease confidence req by 1% per win
    RISK_INCREASE_ON_WIN_STREAK = Decimal('0.05')  # Increase risk by 5% per win in streak
    RISK_DECREASE_ON_LOSS_STREAK = Decimal('0.1')  # Decrease risk by 10% per loss in streak

    # Status thresholds
    REDUCED_RISK_WINRATE_THRESHOLD = Decimal('40.0')  # Below 40% winrate = reduced risk
    ACTIVE_WINRATE_THRESHOLD = Decimal('50.0')  # Above 50% winrate = active

    def __init__(self, account_id: int = 1):
        """
        Initialize Symbol Dynamic Manager

        Args:
            account_id: Account ID (default: 1)
        """
        self.account_id = account_id

    def get_config(self, db: Session, symbol: str, direction: str = None) -> SymbolTradingConfig:
        """
        Get or create symbol trading config

        Args:
            db: Database session
            symbol: Trading symbol
            direction: Trade direction ('BUY', 'SELL', or None for both)

        Returns:
            SymbolTradingConfig instance
        """
        return SymbolTradingConfig.get_or_create(db, self.account_id, symbol, direction)

    def update_after_trade(
        self,
        db: Session,
        trade: Trade,
        market_regime: str = None
    ) -> SymbolTradingConfig:
        """
        Update symbol config after a trade closes

        This is the main entry point called after every trade.

        Args:
            db: Database session
            trade: Closed trade
            market_regime: Market regime at time of trade ('TRENDING', 'RANGING', etc.)

        Returns:
            Updated SymbolTradingConfig
        """
        # Get or create config for this symbol+direction
        config = self.get_config(db, trade.symbol, trade.direction.upper())

        # Determine trade result
        profit = float(trade.profit) if trade.profit else 0.0
        is_win = profit > 0
        is_loss = profit < 0
        is_breakeven = profit == 0

        logger.info(
            f"📊 Updating {config.symbol} {config.direction or 'BOTH'} after trade: "
            f"profit={profit:.2f} ({'WIN' if is_win else 'LOSS' if is_loss else 'BE'})"
        )

        # Update consecutive performance
        if is_win:
            config.consecutive_wins += 1
            config.consecutive_losses = 0
            config.last_trade_result = 'WIN'
        elif is_loss:
            config.consecutive_losses += 1
            config.consecutive_wins = 0
            config.last_trade_result = 'LOSS'
        else:
            config.consecutive_wins = 0
            config.consecutive_losses = 0
            config.last_trade_result = 'BREAKEVEN'

        # Update rolling window performance
        self._update_rolling_window(db, config, trade)

        # Update market regime performance
        if market_regime:
            self._update_regime_performance(config, is_win, market_regime)

        # Adjust confidence threshold based on performance
        self._adjust_confidence_threshold(config)

        # Adjust risk multiplier based on performance
        self._adjust_risk_multiplier(config)

        # Check auto-pause conditions
        self._check_auto_pause(config)

        # Update session stats
        self._update_session_stats(config, profit)

        # Update timestamps
        config.last_trade_at = datetime.utcnow()
        config.last_adjustment_at = datetime.utcnow()
        config.updated_by = 'symbol_dynamic_manager'

        db.commit()

        self._log_config_status(config)

        return config

    def _update_rolling_window(self, db: Session, config: SymbolTradingConfig, trade: Trade):
        """Update rolling 20-trade performance window"""
        # Get last N trades for this symbol+direction
        recent_trades_query = db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.symbol == config.symbol,
            Trade.direction == config.direction.lower() if config.direction else Trade.direction,
            Trade.status == 'closed',
            Trade.profit != None
        ).order_by(Trade.close_time.desc()).limit(config.rolling_window_size).all()

        if not recent_trades_query:
            return

        # CRITICAL: Extract ALL trade data to scalars IMMEDIATELY while session is active
        # This prevents DetachedInstanceError when accessing attributes later
        recent_trades = []
        for t in recent_trades_query:
            recent_trades.append({
                'profit': float(t.profit) if t.profit is not None else 0.0
            })

        # Calculate rolling metrics
        config.rolling_trades_count = len(recent_trades)
        config.rolling_wins = sum(1 for t in recent_trades if t['profit'] > 0)
        config.rolling_losses = sum(1 for t in recent_trades if t['profit'] < 0)
        config.rolling_breakeven = sum(1 for t in recent_trades if t['profit'] == 0)

        # Calculate profit metrics
        total_profit = sum(t['profit'] for t in recent_trades)
        config.rolling_profit = Decimal(str(total_profit))

        # Win rate
        if config.rolling_trades_count > 0:
            config.rolling_winrate = Decimal(
                str((config.rolling_wins / config.rolling_trades_count) * 100)
            ).quantize(Decimal('0.01'))

        # Average profit
        if config.rolling_trades_count > 0:
            config.rolling_avg_profit = Decimal(
                str(total_profit / config.rolling_trades_count)
            ).quantize(Decimal('0.01'))

        # Profit factor
        gross_profit = sum(t['profit'] for t in recent_trades if t['profit'] > 0)
        gross_loss = abs(sum(t['profit'] for t in recent_trades if t['profit'] < 0))
        if gross_loss > 0:
            config.rolling_profit_factor = Decimal(str(gross_profit / gross_loss)).quantize(Decimal('0.01'))

        logger.info(
            f"  📈 Rolling Window: {config.rolling_trades_count} trades, "
            f"{config.rolling_wins}W/{config.rolling_losses}L, "
            f"WR={config.rolling_winrate}%, P/L={config.rolling_profit}"
        )

    def _update_regime_performance(self, config: SymbolTradingConfig, is_win: bool, regime: str):
        """Update market regime preference learning"""
        regime = regime.upper()

        if regime == 'TRENDING':
            config.regime_trades_trending += 1
            if is_win:
                config.regime_wins_trending += 1

            if config.regime_trades_trending > 0:
                config.regime_performance_trending = Decimal(
                    str((config.regime_wins_trending / config.regime_trades_trending) * 100)
                ).quantize(Decimal('0.01'))

        elif regime == 'RANGING':
            config.regime_trades_ranging += 1
            if is_win:
                config.regime_wins_ranging += 1

            if config.regime_trades_ranging > 0:
                config.regime_performance_ranging = Decimal(
                    str((config.regime_wins_ranging / config.regime_trades_ranging) * 100)
                ).quantize(Decimal('0.01'))

        # Determine preferred regime (need at least 5 trades in each regime)
        if config.regime_trades_trending >= 5 and config.regime_trades_ranging >= 5:
            trending_wr = config.regime_performance_trending or Decimal('0')
            ranging_wr = config.regime_performance_ranging or Decimal('0')

            # If one regime is clearly better (>10% difference), prefer it
            if trending_wr - ranging_wr > 10:
                config.preferred_regime = 'TRENDING'
            elif ranging_wr - trending_wr > 10:
                config.preferred_regime = 'RANGING'
            else:
                config.preferred_regime = 'ANY'

    def _adjust_confidence_threshold(self, config: SymbolTradingConfig):
        """Adjust confidence threshold based on recent performance"""
        old_threshold = config.min_confidence_threshold

        # Increase threshold on losses (be more selective)
        if config.last_trade_result == 'LOSS':
            config.min_confidence_threshold = min(
                self.MAX_CONFIDENCE_THRESHOLD,
                config.min_confidence_threshold + self.CONFIDENCE_INCREASE_ON_LOSS
            )

        # Decrease threshold on wins (be more aggressive)
        elif config.last_trade_result == 'WIN':
            config.min_confidence_threshold = max(
                self.MIN_CONFIDENCE_THRESHOLD,
                config.min_confidence_threshold - self.CONFIDENCE_DECREASE_ON_WIN
            )

        # Also adjust based on rolling win rate
        if config.rolling_winrate and config.rolling_trades_count >= 10:
            if config.rolling_winrate < 40:
                # Poor performance - increase threshold significantly
                config.min_confidence_threshold = min(
                    self.MAX_CONFIDENCE_THRESHOLD,
                    config.min_confidence_threshold + Decimal('5.0')
                )
            elif config.rolling_winrate > 65:
                # Excellent performance - can be more aggressive
                config.min_confidence_threshold = max(
                    self.MIN_CONFIDENCE_THRESHOLD,
                    config.min_confidence_threshold - Decimal('2.0')
                )

        if config.min_confidence_threshold != old_threshold:
            logger.info(
                f"  🎯 Confidence threshold: {old_threshold}% → {config.min_confidence_threshold}%"
            )

    def _adjust_risk_multiplier(self, config: SymbolTradingConfig):
        """Adjust risk multiplier based on recent performance"""
        old_multiplier = config.risk_multiplier

        # Increase risk on win streaks
        if config.consecutive_wins >= 3:
            config.risk_multiplier = min(
                self.MAX_RISK_MULTIPLIER,
                config.risk_multiplier + self.RISK_INCREASE_ON_WIN_STREAK
            )

        # Decrease risk on loss streaks
        if config.consecutive_losses >= 2:
            config.risk_multiplier = max(
                self.MIN_RISK_MULTIPLIER,
                config.risk_multiplier - self.RISK_DECREASE_ON_LOSS_STREAK
            )

        # Also adjust based on rolling win rate
        if config.rolling_winrate and config.rolling_trades_count >= 10:
            if config.rolling_winrate < 40:
                # Poor performance - reduce risk
                config.risk_multiplier = max(
                    self.MIN_RISK_MULTIPLIER,
                    Decimal('0.5')  # Cap at 50% risk for poor performers
                )
            elif config.rolling_winrate > 65:
                # Excellent performance - can increase risk
                config.risk_multiplier = min(
                    self.MAX_RISK_MULTIPLIER,
                    Decimal('1.5')  # Cap at 150% risk even for great performers
                )

        if config.risk_multiplier != old_multiplier:
            logger.info(
                f"  💰 Risk multiplier: {old_multiplier}x → {config.risk_multiplier}x"
            )

    def _check_auto_pause(self, config: SymbolTradingConfig):
        """Check if symbol should be auto-paused"""
        if not config.auto_pause_enabled:
            return

        # Auto-pause on consecutive losses
        if config.consecutive_losses >= config.pause_after_consecutive_losses:
            if config.status != 'paused':
                config.status = 'paused'
                config.paused_at = datetime.utcnow()
                config.pause_reason = (
                    f"Auto-paused after {config.consecutive_losses} consecutive losses. "
                    f"Rolling winrate: {config.rolling_winrate}%. "
                    f"Will resume after {config.resume_after_cooldown_hours}h cooldown."
                )
                logger.warning(
                    f"⏸️  {config.symbol} {config.direction} AUTO-PAUSED: {config.pause_reason}"
                )

        # Check for reduced risk status
        elif config.rolling_winrate and config.rolling_winrate < self.REDUCED_RISK_WINRATE_THRESHOLD:
            if config.status == 'active':
                config.status = 'reduced_risk'
                logger.warning(
                    f"⚠️  {config.symbol} {config.direction} → REDUCED_RISK: "
                    f"WR={config.rolling_winrate}% < {self.REDUCED_RISK_WINRATE_THRESHOLD}%"
                )

        # Resume to active if performance improves
        elif config.rolling_winrate and config.rolling_winrate >= self.ACTIVE_WINRATE_THRESHOLD:
            if config.status == 'reduced_risk':
                config.status = 'active'
                logger.info(
                    f"✅ {config.symbol} {config.direction} → ACTIVE: "
                    f"WR={config.rolling_winrate}% >= {self.ACTIVE_WINRATE_THRESHOLD}%"
                )

    def _update_session_stats(self, config: SymbolTradingConfig, profit: float):
        """Update daily session statistics"""
        today = date.today()

        # Reset session if new day
        session_date_check = config.session_date.date() if isinstance(config.session_date, datetime) else config.session_date
        if not config.session_date or session_date_check != today:
            config.session_date = datetime.now()
            config.session_trades_today = 0
            config.session_profit_today = Decimal('0.0')

        # Update session stats
        config.session_trades_today += 1
        config.session_profit_today += Decimal(str(profit))

    def _log_config_status(self, config: SymbolTradingConfig):
        """Log current configuration status"""
        logger.info(
            f"✅ {config.symbol} {config.direction or 'BOTH'} CONFIG: "
            f"status={config.status}, "
            f"conf≥{config.min_confidence_threshold}%, "
            f"risk={config.risk_multiplier}x, "
            f"streak={'W' * config.consecutive_wins if config.consecutive_wins else 'L' * config.consecutive_losses}, "
            f"rolling={config.rolling_winrate}% ({config.rolling_trades_count} trades)"
        )

    def should_trade_signal(
        self,
        db: Session,
        signal: TradingSignal,
        market_regime: str = None
    ) -> Tuple[bool, str, SymbolTradingConfig]:
        """
        Determine if a signal should be traded based on symbol config
        WITH TREND-AWARE CONFIDENCE ADJUSTMENT (Phase 2 - 2025-10-28)

        Args:
            db: Database session
            signal: Trading signal
            market_regime: Current market regime

        Returns:
            (should_trade, reason, config)
        """
        logger.info(f"🔍 should_trade_signal CALLED: {signal.symbol} {signal.signal_type} | Confidence: {signal.confidence}%")
        config = self.get_config(db, signal.symbol, signal.signal_type)

        # 🔧 TREND-AWARE CONFIDENCE ADJUSTMENT (Phase 2 - 2025-10-28)
        # Temporarily adjust config.min_confidence_threshold based on trend alignment
        original_min_conf = config.min_confidence_threshold
        adjusted_min_conf = original_min_conf

        # 🔧 Convert to Decimal for arithmetic (config uses Decimal type)
        from decimal import Decimal

        try:
            from technical_indicators import TechnicalIndicators

            logger.info(f"🔍 Trend-aware START: {signal.symbol} {signal.signal_type} | Original threshold: {original_min_conf}%")
            # 🔧 FIX: TechnicalIndicators requires account_id as first argument
            indicators = TechnicalIndicators(self.account_id, signal.symbol, signal.timeframe)
            regime = indicators.detect_market_regime()
            trend_direction = regime.get('direction', 'neutral')
            logger.info(f"🔍 Trend detected: {signal.symbol} → {trend_direction}")

            # Check if signal aligns with trend
            is_with_trend = False
            if signal.signal_type == 'BUY' and trend_direction == 'bullish':
                is_with_trend = True
            elif signal.signal_type == 'SELL' and trend_direction == 'bearish':
                is_with_trend = True

            # Adjust confidence threshold (use Decimal for arithmetic)
            if is_with_trend:
                # WITH TREND: Lower confidence requirement (-15 points)
                adjusted_min_conf = max(Decimal('45.0'), original_min_conf - Decimal('15.0'))
                config.min_confidence_threshold = adjusted_min_conf  # Temporarily modify
                logger.info(
                    f"✅ WITH TREND: {signal.symbol} {signal.signal_type} aligned with {trend_direction} trend | "
                    f"Min Confidence: {original_min_conf:.0f}% → {adjusted_min_conf:.0f}% (-15)"
                )
            elif trend_direction != 'neutral':
                # AGAINST TREND: Higher confidence requirement (+20 points)
                adjusted_min_conf = min(Decimal('95.0'), original_min_conf + Decimal('20.0'))
                config.min_confidence_threshold = adjusted_min_conf  # Temporarily modify
                logger.warning(
                    f"⚠️ AGAINST TREND: {signal.symbol} {signal.signal_type} against {trend_direction} trend | "
                    f"Min Confidence: {original_min_conf:.0f}% → {adjusted_min_conf:.0f}% (+20)"
                )
            else:
                logger.info(f"➡️ NEUTRAL TREND: {signal.symbol} {signal.signal_type} - no adjustment | Threshold stays at {original_min_conf}%")

        except Exception as trend_err:
            logger.warning(f"⚠️ Trend-awareness check failed for {signal.symbol}: {trend_err}", exc_info=True)

        # Now check with adjusted confidence
        should_trade, reason = config.should_trade(
            signal_confidence=float(signal.confidence),
            market_regime=market_regime
        )

        # Restore original threshold (don't persist the temporary change)
        config.min_confidence_threshold = original_min_conf

        return should_trade, reason, config

    def get_all_configs(self, db: Session) -> List[SymbolTradingConfig]:
        """Get all symbol trading configs for this account"""
        return db.query(SymbolTradingConfig).filter_by(
            account_id=self.account_id
        ).order_by(
            SymbolTradingConfig.rolling_winrate.desc(),
            SymbolTradingConfig.rolling_profit.desc()
        ).all()

    def get_active_symbols(self, db: Session) -> List[str]:
        """Get list of symbols with active status"""
        results = db.query(SymbolTradingConfig.symbol).filter_by(
            account_id=self.account_id,
            status='active'
        ).distinct().all()

        return [r[0] for r in results]

    def get_paused_symbols(self, db: Session) -> List[SymbolTradingConfig]:
        """Get list of paused symbol configs"""
        return db.query(SymbolTradingConfig).filter_by(
            account_id=self.account_id,
            status='paused'
        ).all()

    def manually_resume_symbol(self, db: Session, symbol: str, direction: str = None) -> SymbolTradingConfig:
        """Manually resume a paused symbol"""
        config = self.get_config(db, symbol, direction)

        if config.status == 'paused':
            config.status = 'active'
            config.paused_at = None
            config.pause_reason = None
            config.consecutive_losses = 0  # Reset streak
            config.updated_by = 'manual_resume'
            db.commit()

            logger.info(f"▶️  {config.symbol} {config.direction} manually resumed")

        return config

    def check_and_resume_cooldowns(self, db: Session) -> List[SymbolTradingConfig]:
        """Check all paused symbols and resume if cooldown period passed"""
        paused_configs = self.get_paused_symbols(db)
        resumed = []

        for config in paused_configs:
            if config.paused_at:
                hours_paused = (datetime.utcnow() - config.paused_at).total_seconds() / 3600

                if hours_paused >= config.resume_after_cooldown_hours:
                    config.status = 'active'
                    config.consecutive_losses = 0  # Reset streak
                    config.updated_by = 'auto_resume_cooldown'
                    resumed.append(config)

                    logger.info(
                        f"▶️  {config.symbol} {config.direction} auto-resumed after "
                        f"{hours_paused:.1f}h cooldown"
                    )

        if resumed:
            db.commit()

        return resumed


# ========================================
# Convenience functions for easy access
# ========================================

def update_symbol_after_trade(ticket: int, market_regime: str = None) -> dict:
    """
    Convenience function to update symbol config after trade closes
    
    IMPORTANT: Takes ticket as scalar to avoid SQLAlchemy session binding issues.
    Will re-query the Trade internally with its own session.
    Returns dict instead of ORM object to completely avoid session issues.

    Args:
        ticket: Trade ticket number
        market_regime: Market regime at time of trade

    Returns:
        Dict with config data (symbol, direction, status, etc.)
    """
    db = ScopedSession()
    try:
        # Re-query trade with this session to avoid detachment issues
        trade = db.query(Trade).filter_by(ticket=ticket).first()
        if not trade:
            raise ValueError(f"Trade #{ticket} not found")
        
        manager = SymbolDynamicManager(account_id=trade.account_id)
        config = manager.update_after_trade(db, trade, market_regime)
        
        # Build performance streak string
        streak = 'W' * config.consecutive_wins if config.consecutive_wins else 'L' * config.consecutive_losses
        
        # Return dict to completely avoid session issues
        return {
            'symbol': config.symbol,
            'direction': config.direction,
            'status': config.status,
            'min_confidence_threshold': config.min_confidence_threshold,
            'risk_multiplier': config.risk_multiplier,
            'streak': streak
        }
    finally:
        db.close()



def get_symbol_config(account_id: int, symbol: str, direction: str = None) -> SymbolTradingConfig:
    """
    Convenience function to get symbol config

    Args:
        account_id: Account ID
        symbol: Trading symbol
        direction: Trade direction ('BUY', 'SELL', or None)

    Returns:
        SymbolTradingConfig
    """
    db = ScopedSession()
    try:
        manager = SymbolDynamicManager(account_id=account_id)
        return manager.get_config(db, symbol, direction)
    finally:
        db.close()
