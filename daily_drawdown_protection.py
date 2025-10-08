"""
Daily Drawdown Protection

Protects account from excessive daily losses by:
1. Tracking daily P&L
2. Disabling auto-trading when daily loss limit is reached
3. Logging decision for user visibility
4. Automatically re-enabling at start of next trading day

Configuration per account:
- max_daily_loss_percent: Maximum daily loss as % of balance (default: 2%)
- max_daily_loss_eur: Maximum daily loss in EUR (default: None)
- reset_time: Time to reset daily limit (default: 00:00 UTC)
"""

import logging
from datetime import datetime, timedelta, time
from typing import Optional, Dict
from sqlalchemy import Column, Integer, Numeric, Date, Boolean, func
from database import get_db, Base
from models import Account, Trade
from ai_decision_log import log_risk_limit

logger = logging.getLogger(__name__)


class DailyDrawdownLimit(Base):
    """Daily Drawdown Tracking"""
    __tablename__ = 'daily_drawdown_limits'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False, unique=True)

    # Configuration
    max_daily_loss_percent = Column(Numeric(5, 2), default=2.0)  # 2% default
    max_daily_loss_eur = Column(Numeric(10, 2))  # Optional absolute limit

    # Current day tracking
    tracking_date = Column(Date, default=datetime.utcnow().date)
    daily_pnl = Column(Numeric(10, 2), default=0.0)
    limit_reached = Column(Boolean, default=False)
    auto_trading_disabled_at = Column(Date)


class DailyDrawdownProtection:
    """Daily Drawdown Protection Manager"""

    def __init__(self, account_id: int):
        self.account_id = account_id
        self._ensure_limit_exists()

    def _ensure_limit_exists(self):
        """Ensure daily limit record exists for account"""
        db = next(get_db())

        try:
            limit = db.query(DailyDrawdownLimit).filter_by(
                account_id=self.account_id
            ).first()

            if not limit:
                limit = DailyDrawdownLimit(
                    account_id=self.account_id,
                    max_daily_loss_percent=2.0,  # 2% default
                    tracking_date=datetime.utcnow().date(),
                    daily_pnl=0.0,
                    limit_reached=False
                )
                db.add(limit)
                db.commit()
                logger.info(f"✅ Created daily drawdown limit for account {self.account_id}")

        except Exception as e:
            logger.error(f"Error ensuring daily limit exists: {e}")
            db.rollback()
        finally:
            db.close()

    def check_and_update(self, auto_trading_enabled: bool) -> Dict:
        """
        Check daily drawdown and update status

        Returns:
            Dict with:
                - allowed: bool - whether trading is allowed
                - daily_pnl: float - current daily P&L
                - limit_percent: float - configured limit
                - reason: str - reason if not allowed
        """
        db = next(get_db())

        try:
            limit = db.query(DailyDrawdownLimit).filter_by(
                account_id=self.account_id
            ).first()

            if not limit:
                return {'allowed': True, 'daily_pnl': 0.0, 'reason': 'No limit configured'}

            account = db.query(Account).filter_by(id=self.account_id).first()
            if not account:
                return {'allowed': False, 'reason': 'Account not found'}

            today = datetime.utcnow().date()

            # Reset if new day
            if limit.tracking_date != today:
                logger.info(f"📅 New trading day - resetting daily drawdown for account {self.account_id}")
                limit.tracking_date = today
                limit.daily_pnl = 0.0
                limit.limit_reached = False
                limit.auto_trading_disabled_at = None
                db.commit()

            # Calculate today's P&L
            today_start = datetime.combine(today, time.min)
            daily_pnl = db.query(Trade).filter(
                Trade.account_id == self.account_id,
                Trade.close_time >= today_start,
                Trade.status == 'closed'
            ).with_entities(
                func.sum(Trade.profit).label('total')
            ).scalar() or 0.0

            limit.daily_pnl = float(daily_pnl)

            # Check limits
            loss_limit_eur = None
            loss_limit_percent = limit.max_daily_loss_percent

            if limit.max_daily_loss_eur:
                loss_limit_eur = float(limit.max_daily_loss_eur)

            if loss_limit_percent:
                percent_limit = (float(account.balance) * float(loss_limit_percent)) / 100.0
                if loss_limit_eur:
                    loss_limit_eur = min(loss_limit_eur, percent_limit)
                else:
                    loss_limit_eur = percent_limit

            # Check if limit exceeded
            if loss_limit_eur and daily_pnl < -loss_limit_eur:
                if not limit.limit_reached:
                    limit.limit_reached = True
                    limit.auto_trading_disabled_at = today
                    db.commit()

                    # Log decision
                    log_risk_limit(
                        account_id=self.account_id,
                        limit_type='DAILY_DRAWDOWN',
                        reason=f'Daily loss limit reached: €{daily_pnl:.2f} (Limit: €{loss_limit_eur:.2f})',
                        details={
                            'daily_pnl': daily_pnl,
                            'limit_eur': loss_limit_eur,
                            'limit_percent': float(loss_limit_percent) if loss_limit_percent else None,
                            'account_balance': float(account.balance)
                        }
                    )

                    logger.warning(f"🛑 Daily drawdown limit REACHED for account {self.account_id}: €{daily_pnl:.2f}")

                return {
                    'allowed': False,
                    'daily_pnl': daily_pnl,
                    'limit_eur': loss_limit_eur,
                    'limit_percent': float(loss_limit_percent) if loss_limit_percent else None,
                    'reason': f'Daily loss limit reached (€{daily_pnl:.2f} < €{-loss_limit_eur:.2f})'
                }

            # Trading allowed
            db.commit()
            return {
                'allowed': True,
                'daily_pnl': daily_pnl,
                'limit_eur': loss_limit_eur,
                'limit_percent': float(loss_limit_percent) if loss_limit_percent else None,
                'remaining_eur': float(loss_limit_eur) + float(daily_pnl) if loss_limit_eur else None
            }

        except Exception as e:
            logger.error(f"Error checking daily drawdown: {e}")
            return {'allowed': True, 'reason': f'Error: {e}'}
        finally:
            db.close()

    def get_status(self) -> Dict:
        """Get current daily drawdown status"""
        db = next(get_db())

        try:
            limit = db.query(DailyDrawdownLimit).filter_by(
                account_id=self.account_id
            ).first()

            if not limit:
                return {'configured': False}

            return {
                'configured': True,
                'tracking_date': limit.tracking_date.isoformat() if limit.tracking_date else None,
                'daily_pnl': float(limit.daily_pnl) if limit.daily_pnl else 0.0,
                'limit_reached': limit.limit_reached,
                'max_daily_loss_percent': float(limit.max_daily_loss_percent) if limit.max_daily_loss_percent else None,
                'max_daily_loss_eur': float(limit.max_daily_loss_eur) if limit.max_daily_loss_eur else None
            }

        except Exception as e:
            logger.error(f"Error getting drawdown status: {e}")
            return {'error': str(e)}
        finally:
            db.close()

    def update_config(self, max_daily_loss_percent: Optional[float] = None,
                     max_daily_loss_eur: Optional[float] = None):
        """Update daily drawdown configuration"""
        db = next(get_db())

        try:
            limit = db.query(DailyDrawdownLimit).filter_by(
                account_id=self.account_id
            ).first()

            if not limit:
                self._ensure_limit_exists()
                limit = db.query(DailyDrawdownLimit).filter_by(
                    account_id=self.account_id
                ).first()

            if max_daily_loss_percent is not None:
                limit.max_daily_loss_percent = max_daily_loss_percent

            if max_daily_loss_eur is not None:
                limit.max_daily_loss_eur = max_daily_loss_eur

            db.commit()
            logger.info(f"✅ Updated daily drawdown config for account {self.account_id}")

        except Exception as e:
            logger.error(f"Error updating drawdown config: {e}")
            db.rollback()
        finally:
            db.close()


def get_drawdown_protection(account_id: int) -> DailyDrawdownProtection:
    """Get daily drawdown protection instance"""
    return DailyDrawdownProtection(account_id)
