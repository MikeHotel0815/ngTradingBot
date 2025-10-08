"""
AI Decision Log

Tracks all AI decisions and reasoning for transparency.
Allows user to see what the bot is "thinking" and why it makes certain decisions.

Decision Types:
- TRADE_OPEN: Why trade was opened (or rejected)
- TRADE_CLOSE: Why trade was closed
- SYMBOL_DISABLE: Why symbol was auto-disabled
- SYMBOL_ENABLE: Why symbol was re-enabled
- SIGNAL_SKIP: Why signal was skipped
- RISK_LIMIT: Why risk limit prevented action
- CORRELATION_BLOCK: Why correlation limit blocked trade
- NEWS_PAUSE: Why trading was paused due to news
- DD_LIMIT: Why daily drawdown limit was hit
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy import Column, Integer, String, DateTime, Text, Numeric, Boolean
from sqlalchemy.ext.declarative import declarative_base
from database import get_db, Base
from models import Account

logger = logging.getLogger(__name__)


class AIDecisionLog(Base):
    """AI Decision Log Entry"""
    __tablename__ = 'ai_decision_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Decision metadata
    decision_type = Column(String(50), nullable=False)  # TRADE_OPEN, TRADE_CLOSE, etc.
    decision = Column(String(50), nullable=False)  # APPROVED, REJECTED, EXECUTED, etc.
    symbol = Column(String(20))
    timeframe = Column(String(10))

    # Reasoning
    primary_reason = Column(String(500), nullable=False)
    detailed_reasoning = Column(Text)  # JSON with all factors

    # Related entities
    signal_id = Column(Integer)
    trade_id = Column(Integer)

    # Impact
    impact_level = Column(String(20))  # LOW, MEDIUM, HIGH, CRITICAL
    user_action_required = Column(Boolean, default=False)

    # Metrics at decision time
    confidence_score = Column(Numeric(5, 2))
    risk_score = Column(Numeric(5, 2))
    account_balance = Column(Numeric(15, 2))
    open_positions = Column(Integer)


class AIDecisionLogger:
    """Logs AI decisions for transparency"""

    DECISION_TYPES = {
        'TRADE_OPEN': '🔵 Trade Open Decision',
        'TRADE_CLOSE': '🔴 Trade Close Decision',
        'SIGNAL_SKIP': '⏭️ Signal Skipped',
        'SYMBOL_DISABLE': '⛔ Symbol Auto-Disabled',
        'SYMBOL_ENABLE': '✅ Symbol Re-Enabled',
        'RISK_LIMIT': '⚠️ Risk Limit Hit',
        'CORRELATION_BLOCK': '🔗 Correlation Block',
        'NEWS_PAUSE': '📰 News Trading Pause',
        'DD_LIMIT': '📉 Daily Drawdown Limit',
        'SUPERTREND_SL': '🎯 SuperTrend SL Applied',
        'MTF_CONFLICT': '📊 Multi-Timeframe Conflict',
        'BACKTEST_START': '🔬 Backtest Started',
        'BACKTEST_COMPLETE': '✅ Backtest Complete'
    }

    def __init__(self):
        self._ensure_table_exists()

    def _ensure_table_exists(self):
        """Create table if not exists"""
        import os
        from sqlalchemy import create_engine

        # Use environment variable or default to Docker service name
        db_host = os.getenv('DB_HOST', 'ngtradingbot_db')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME', 'ngtradingbot')
        db_user = os.getenv('DB_USER', 'trader')
        db_pass = os.getenv('DB_PASSWORD', 'tradingbot_secret_2025')

        database_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine = create_engine(database_url)
        Base.metadata.create_all(engine, tables=[AIDecisionLog.__table__])

    def log_decision(
        self,
        account_id: int,
        decision_type: str,
        decision: str,
        primary_reason: str,
        detailed_reasoning: Optional[Dict] = None,
        symbol: Optional[str] = None,
        timeframe: Optional[str] = None,
        signal_id: Optional[int] = None,
        trade_id: Optional[int] = None,
        impact_level: str = 'MEDIUM',
        user_action_required: bool = False,
        confidence_score: Optional[float] = None,
        risk_score: Optional[float] = None
    ) -> AIDecisionLog:
        """
        Log an AI decision

        Args:
            account_id: Account ID
            decision_type: Type of decision (TRADE_OPEN, TRADE_CLOSE, etc.)
            decision: Decision made (APPROVED, REJECTED, etc.)
            primary_reason: Short human-readable reason
            detailed_reasoning: Dict with detailed reasoning (stored as JSON)
            symbol: Optional symbol
            timeframe: Optional timeframe
            signal_id: Optional signal ID
            trade_id: Optional trade ID
            impact_level: LOW, MEDIUM, HIGH, CRITICAL
            user_action_required: Whether user should review this
            confidence_score: Optional confidence score (0-100)
            risk_score: Optional risk score (0-100)

        Returns:
            AIDecisionLog entry
        """

        db = next(get_db())

        try:
            # Get current account stats
            account = db.query(Account).filter(Account.id == account_id).first()
            open_positions_count = 0  # TODO: Get from database

            # Create log entry
            log_entry = AIDecisionLog(
                account_id=account_id,
                timestamp=datetime.utcnow(),
                decision_type=decision_type,
                decision=decision,
                symbol=symbol,
                timeframe=timeframe,
                primary_reason=primary_reason,
                detailed_reasoning=str(detailed_reasoning) if detailed_reasoning else None,
                signal_id=signal_id,
                trade_id=trade_id,
                impact_level=impact_level,
                user_action_required=user_action_required,
                confidence_score=confidence_score,
                risk_score=risk_score,
                account_balance=float(account.balance) if account else None,
                open_positions=open_positions_count
            )

            db.add(log_entry)
            db.commit()

            # Log to console with emoji
            emoji = self._get_emoji(decision_type, decision)
            logger.info(f"{emoji} AI Decision: {decision_type} → {decision} | {primary_reason}")

            if user_action_required:
                logger.warning(f"⚠️ USER ACTION REQUIRED: {primary_reason}")

            return log_entry

        except Exception as e:
            logger.error(f"Error logging AI decision: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def _get_emoji(self, decision_type: str, decision: str) -> str:
        """Get emoji for log entry"""
        emoji_map = {
            'TRADE_OPEN': '🔵' if decision == 'APPROVED' else '🚫',
            'TRADE_CLOSE': '🔴',
            'SIGNAL_SKIP': '⏭️',
            'SYMBOL_DISABLE': '⛔',
            'SYMBOL_ENABLE': '✅',
            'RISK_LIMIT': '⚠️',
            'CORRELATION_BLOCK': '🔗',
            'NEWS_PAUSE': '📰',
            'DD_LIMIT': '📉',
            'SUPERTREND_SL': '🎯',
            'MTF_CONFLICT': '📊'
        }
        return emoji_map.get(decision_type, '🤖')

    def get_recent_decisions(
        self,
        account_id: int,
        limit: int = 50,
        decision_type: Optional[str] = None,
        minutes: Optional[int] = None
    ) -> List[AIDecisionLog]:
        """
        Get recent AI decisions

        Args:
            account_id: Account ID
            limit: Max number of decisions to return
            decision_type: Optional filter by decision type
            minutes: Optional filter last N minutes

        Returns:
            List of AIDecisionLog entries
        """

        db = next(get_db())

        try:
            query = db.query(AIDecisionLog).filter(
                AIDecisionLog.account_id == account_id
            )

            if decision_type:
                query = query.filter(AIDecisionLog.decision_type == decision_type)

            if minutes:
                cutoff = datetime.utcnow() - timedelta(minutes=minutes)
                query = query.filter(AIDecisionLog.timestamp >= cutoff)

            decisions = query.order_by(
                AIDecisionLog.timestamp.desc()
            ).limit(limit).all()

            return decisions

        except Exception as e:
            logger.error(f"Error retrieving decisions: {e}")
            return []
        finally:
            db.close()

    def cleanup_old_decisions(self, hours: int = 24) -> int:
        """
        Delete decisions older than specified hours

        Args:
            hours: Number of hours to keep (default: 24)

        Returns:
            Number of decisions deleted
        """
        db = next(get_db())

        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            deleted = db.query(AIDecisionLog).filter(
                AIDecisionLog.timestamp < cutoff
            ).delete()

            db.commit()

            if deleted > 0:
                logger.info(f"🧹 Cleaned up {deleted} AI decision logs older than {hours}h")

            return deleted

        except Exception as e:
            logger.error(f"Error cleaning up old decisions: {e}")
            db.rollback()
            return 0
        finally:
            db.close()

    def get_decisions_requiring_action(self, account_id: int) -> List[AIDecisionLog]:
        """Get decisions that require user action"""

        db = next(get_db())

        try:
            decisions = db.query(AIDecisionLog).filter(
                AIDecisionLog.account_id == account_id,
                AIDecisionLog.user_action_required == True
            ).order_by(
                AIDecisionLog.timestamp.desc()
            ).limit(10).all()

            return decisions

        except Exception as e:
            logger.error(f"Error retrieving action-required decisions: {e}")
            return []
        finally:
            db.close()

    def get_decision_stats(self, account_id: int, hours: int = 24) -> Dict:
        """
        Get statistics about AI decisions

        Returns:
            Dict with decision statistics
        """

        db = next(get_db())

        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)

            # Total decisions
            total = db.query(AIDecisionLog).filter(
                AIDecisionLog.account_id == account_id,
                AIDecisionLog.timestamp >= cutoff
            ).count()

            # By type
            from sqlalchemy import func
            by_type = db.query(
                AIDecisionLog.decision_type,
                func.count(AIDecisionLog.id).label('count')
            ).filter(
                AIDecisionLog.account_id == account_id,
                AIDecisionLog.timestamp >= cutoff
            ).group_by(AIDecisionLog.decision_type).all()

            # Requiring action
            action_required = db.query(AIDecisionLog).filter(
                AIDecisionLog.account_id == account_id,
                AIDecisionLog.user_action_required == True
            ).count()

            return {
                'total_decisions': total,
                'decisions_by_type': {dt: count for dt, count in by_type},
                'action_required': action_required,
                'hours': hours
            }

        except Exception as e:
            logger.error(f"Error getting decision stats: {e}")
            return {'total_decisions': 0, 'decisions_by_type': {}, 'action_required': 0}
        finally:
            db.close()


# Global instance
_decision_logger = None


def get_decision_logger() -> AIDecisionLogger:
    """Get global decision logger instance"""
    global _decision_logger
    if _decision_logger is None:
        _decision_logger = AIDecisionLogger()
    return _decision_logger


# Convenience functions for common log types
def log_trade_decision(account_id: int, signal_id: int, approved: bool, reason: str, details: Dict):
    """Log trade open decision"""
    logger = get_decision_logger()
    logger.log_decision(
        account_id=account_id,
        decision_type='TRADE_OPEN',
        decision='APPROVED' if approved else 'REJECTED',
        primary_reason=reason,
        detailed_reasoning=details,
        signal_id=signal_id,
        symbol=details.get('symbol'),
        timeframe=details.get('timeframe'),
        impact_level='HIGH' if approved else 'MEDIUM',
        confidence_score=details.get('confidence')
    )


def log_symbol_disable(account_id: int, symbol: str, reason: str, metrics: Dict):
    """Log symbol auto-disable"""
    logger = get_decision_logger()
    logger.log_decision(
        account_id=account_id,
        decision_type='SYMBOL_DISABLE',
        decision='DISABLED',
        primary_reason=reason,
        detailed_reasoning=metrics,
        symbol=symbol,
        impact_level='HIGH',
        user_action_required=True
    )


def log_risk_limit(account_id: int, limit_type: str, reason: str, details: Dict):
    """Log risk limit hit"""
    logger = get_decision_logger()
    logger.log_decision(
        account_id=account_id,
        decision_type='RISK_LIMIT',
        decision='BLOCKED',
        primary_reason=reason,
        detailed_reasoning=details,
        impact_level='CRITICAL',
        user_action_required=True
    )
