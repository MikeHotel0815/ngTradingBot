"""
Loss-Adaptive Signal Filter

Implements progressive signal restrictions after consecutive losses.
The more losses in a row, the higher the confidence requirements become.

Features:
1. Tracks consecutive losses per symbol
2. Progressively increases confidence requirements
3. Implements cooldown periods after losses
4. Auto-resets after successful trades

Configuration:
- Base increase: +5% confidence per consecutive loss
- Maximum penalty: +20% confidence requirement
- Cooldown: 1 hour after 3+ consecutive losses
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from decimal import Decimal
from sqlalchemy.orm import Session
from sqlalchemy import desc, and_, func
from models import Trade, SymbolTradingConfig
from database import get_db

logger = logging.getLogger(__name__)


class LossAdaptiveSignalFilter:
    """Progressively restricts signals after consecutive losses"""
    
    # Configuration
    BASE_CONFIDENCE_PENALTY = 5.0  # +5% confidence per consecutive loss
    MAX_CONFIDENCE_PENALTY = 20.0  # Maximum penalty: +20%
    COOLDOWN_AFTER_LOSSES = 3      # Cooldown after 3+ consecutive losses
    COOLDOWN_DURATION_HOURS = 1    # 1 hour cooldown
    
    def __init__(self, account_id: int = 1):
        self.account_id = account_id
    
    def should_allow_signal(
        self, 
        db: Session, 
        symbol: str, 
        signal_confidence: float,
        signal_type: str = None
    ) -> Tuple[bool, str, float]:
        """
        Check if signal should be allowed based on recent loss history
        
        Args:
            db: Database session
            symbol: Trading symbol
            signal_confidence: Original signal confidence (0-100)
            signal_type: 'BUY' or 'SELL' (optional for direction-specific tracking)
            
        Returns:
            (allowed, reason, adjusted_min_confidence)
        """
        try:
            # Get recent loss streak for this symbol
            consecutive_losses = self._get_consecutive_losses(db, symbol, signal_type)
            
            # Check if in cooldown period
            if consecutive_losses >= self.COOLDOWN_AFTER_LOSSES:
                last_loss_time = self._get_last_loss_time(db, symbol, signal_type)
                if last_loss_time:
                    time_since_loss = datetime.utcnow() - last_loss_time
                    if time_since_loss < timedelta(hours=self.COOLDOWN_DURATION_HOURS):
                        remaining_minutes = int((timedelta(hours=self.COOLDOWN_DURATION_HOURS) - time_since_loss).total_seconds() / 60)
                        return False, f"cooldown_after_{consecutive_losses}_losses_{remaining_minutes}min_remaining", 0
            
            # Calculate confidence penalty
            confidence_penalty = min(
                consecutive_losses * self.BASE_CONFIDENCE_PENALTY,
                self.MAX_CONFIDENCE_PENALTY
            )
            
            # Calculate adjusted minimum confidence requirement
            base_min_confidence = 45.0  # Match new minimum from signal_generator
            adjusted_min_confidence = base_min_confidence + confidence_penalty
            
            # Check if signal meets adjusted requirement
            if signal_confidence < adjusted_min_confidence:
                return False, (
                    f"confidence_too_low_after_{consecutive_losses}_losses_"
                    f"{signal_confidence:.1f}<{adjusted_min_confidence:.1f}"
                ), adjusted_min_confidence
            
            # Signal allowed
            reason = "allowed"
            if consecutive_losses > 0:
                reason += f"_after_{consecutive_losses}_losses_confidence_req_{adjusted_min_confidence:.1f}"
            
            return True, reason, adjusted_min_confidence
            
        except Exception as e:
            logger.error(f"Error in loss-adaptive filter for {symbol}: {e}")
            # On error, allow signal with base requirements
            return True, f"filter_error_{e}", 45.0
    
    def _get_consecutive_losses(self, db: Session, symbol: str, signal_type: str = None) -> int:
        """Get number of consecutive losses for symbol (optionally by direction)"""
        try:
            # Query recent trades, ordered by close time (most recent first)
            query = db.query(Trade).filter(
                and_(
                    Trade.account_id == self.account_id,
                    Trade.symbol == symbol,
                    Trade.status == 'closed',
                    Trade.close_time.isnot(None),
                    Trade.profit.isnot(None)
                )
            )
            
            # Optionally filter by direction
            if signal_type:
                direction = signal_type.lower()  # 'BUY' -> 'buy'
                query = query.filter(Trade.direction == direction)
            
            recent_trades = query.order_by(desc(Trade.close_time)).limit(20).all()
            
            # Count consecutive losses from most recent
            consecutive_losses = 0
            for trade in recent_trades:
                if trade.profit < 0:
                    consecutive_losses += 1
                else:
                    break  # Stop at first non-loss
            
            return consecutive_losses
            
        except Exception as e:
            logger.error(f"Error getting consecutive losses for {symbol}: {e}")
            return 0
    
    def _get_last_loss_time(self, db: Session, symbol: str, signal_type: str = None) -> Optional[datetime]:
        """Get timestamp of most recent loss for symbol"""
        try:
            query = db.query(Trade.close_time).filter(
                and_(
                    Trade.account_id == self.account_id,
                    Trade.symbol == symbol,
                    Trade.status == 'closed',
                    Trade.profit < 0,
                    Trade.close_time.isnot(None)
                )
            )
            
            if signal_type:
                direction = signal_type.lower()
                query = query.filter(Trade.direction == direction)
            
            last_loss = query.order_by(desc(Trade.close_time)).first()
            return last_loss[0] if last_loss else None
            
        except Exception as e:
            logger.error(f"Error getting last loss time for {symbol}: {e}")
            return None
    
    def get_symbol_loss_stats(self, db: Session, symbol: str) -> Dict:
        """Get detailed loss statistics for a symbol"""
        try:
            consecutive_losses = self._get_consecutive_losses(db, symbol)
            last_loss_time = self._get_last_loss_time(db, symbol)
            
            # Calculate current penalty
            confidence_penalty = min(
                consecutive_losses * self.BASE_CONFIDENCE_PENALTY,
                self.MAX_CONFIDENCE_PENALTY
            )
            
            # Check cooldown status
            in_cooldown = False
            cooldown_remaining_minutes = 0
            
            if consecutive_losses >= self.COOLDOWN_AFTER_LOSSES and last_loss_time:
                time_since_loss = datetime.utcnow() - last_loss_time
                if time_since_loss < timedelta(hours=self.COOLDOWN_DURATION_HOURS):
                    in_cooldown = True
                    cooldown_remaining_minutes = int(
                        (timedelta(hours=self.COOLDOWN_DURATION_HOURS) - time_since_loss).total_seconds() / 60
                    )
            
            return {
                'symbol': symbol,
                'consecutive_losses': consecutive_losses,
                'confidence_penalty': confidence_penalty,
                'adjusted_min_confidence': 45.0 + confidence_penalty,
                'in_cooldown': in_cooldown,
                'cooldown_remaining_minutes': cooldown_remaining_minutes,
                'last_loss_time': last_loss_time
            }
            
        except Exception as e:
            logger.error(f"Error getting loss stats for {symbol}: {e}")
            return {
                'symbol': symbol,
                'consecutive_losses': 0,
                'confidence_penalty': 0,
                'adjusted_min_confidence': 45.0,
                'in_cooldown': False,
                'cooldown_remaining_minutes': 0,
                'last_loss_time': None,
                'error': str(e)
            }


# Global instance
_loss_adaptive_filter = None

def get_loss_adaptive_filter(account_id: int = 1) -> LossAdaptiveSignalFilter:
    """Get singleton instance of LossAdaptiveSignalFilter"""
    global _loss_adaptive_filter
    if _loss_adaptive_filter is None or _loss_adaptive_filter.account_id != account_id:
        _loss_adaptive_filter = LossAdaptiveSignalFilter(account_id)
    return _loss_adaptive_filter


def check_loss_adaptive_limits(
    symbol: str, 
    signal_confidence: float,
    signal_type: str = None,
    account_id: int = 1,
    db: Session = None
) -> Tuple[bool, str, float]:
    """
    Convenience function to check loss-adaptive limits
    
    Returns:
        (allowed, reason, adjusted_min_confidence)
    """
    if db is None:
        db = next(get_db())
        close_db = True
    else:
        close_db = False
    
    try:
        filter_instance = get_loss_adaptive_filter(account_id)
        return filter_instance.should_allow_signal(db, symbol, signal_confidence, signal_type)
    finally:
        if close_db:
            db.close()