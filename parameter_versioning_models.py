"""
Parameter Versioning Models
Database models for indicator parameter versioning and optimization
"""

from sqlalchemy import (
    Column, Integer, String, DECIMAL, TIMESTAMP, Boolean,
    Text, ARRAY, ForeignKey, JSON, Date, UniqueConstraint
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime

Base = declarative_base()


class IndicatorParameterVersion(Base):
    """Versioned parameter storage for indicators"""
    __tablename__ = 'indicator_parameter_versions'

    id = Column(Integer, primary_key=True)
    indicator_name = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)
    version = Column(Integer, nullable=False)

    # Parameters (JSON for flexibility)
    parameters = Column(JSONB, nullable=False)

    # Backtest performance metrics
    backtest_win_rate = Column(DECIMAL(5, 2))
    backtest_total_pnl = Column(DECIMAL(10, 2))
    backtest_avg_pnl = Column(DECIMAL(10, 4))
    backtest_trades = Column(Integer)
    backtest_period_days = Column(Integer)

    # Live performance metrics
    live_win_rate = Column(DECIMAL(5, 2))
    live_total_pnl = Column(DECIMAL(10, 2))
    live_avg_pnl = Column(DECIMAL(10, 4))
    live_trades = Column(Integer)
    live_period_days = Column(Integer)

    # Metadata
    status = Column(String(20), default='proposed')
    approved_by = Column(String(100))
    approved_at = Column(TIMESTAMP)
    activated_at = Column(TIMESTAMP)
    deactivated_at = Column(TIMESTAMP)

    # Audit trail
    created_at = Column(TIMESTAMP, default=datetime.utcnow)
    created_by = Column(String(100), default='system')
    notes = Column(Text)

    __table_args__ = (
        UniqueConstraint('indicator_name', 'symbol', 'timeframe', 'version',
                        name='uq_param_version'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'indicator_name': self.indicator_name,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'version': self.version,
            'parameters': self.parameters,
            'backtest_metrics': {
                'win_rate': float(self.backtest_win_rate) if self.backtest_win_rate else None,
                'total_pnl': float(self.backtest_total_pnl) if self.backtest_total_pnl else None,
                'avg_pnl': float(self.backtest_avg_pnl) if self.backtest_avg_pnl else None,
                'trades': self.backtest_trades,
                'period_days': self.backtest_period_days
            },
            'live_metrics': {
                'win_rate': float(self.live_win_rate) if self.live_win_rate else None,
                'total_pnl': float(self.live_total_pnl) if self.live_total_pnl else None,
                'avg_pnl': float(self.live_avg_pnl) if self.live_avg_pnl else None,
                'trades': self.live_trades,
                'period_days': self.live_period_days
            },
            'status': self.status,
            'approved_by': self.approved_by,
            'approved_at': self.approved_at.isoformat() if self.approved_at else None,
            'activated_at': self.activated_at.isoformat() if self.activated_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'created_by': self.created_by,
            'notes': self.notes
        }


class WeeklyPerformanceReport(Base):
    """Weekly performance analysis reports"""
    __tablename__ = 'weekly_performance_reports'

    id = Column(Integer, primary_key=True)
    report_date = Column(Date, nullable=False)
    week_number = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)

    # Overall metrics
    total_trades = Column(Integer)
    total_win_rate = Column(DECIMAL(5, 2))
    total_pnl = Column(DECIMAL(10, 2))

    # Symbol-specific metrics (JSON)
    symbol_metrics = Column(JSONB)

    # Comparison to baseline
    baseline_comparison = Column(JSONB)

    # Warnings/Alerts
    warnings = Column(JSONB)

    # Report generation metadata
    lookback_periods = Column(ARRAY(Integer), default=[7, 30, 90])
    report_type = Column(String(50), default='weekly')
    generated_at = Column(TIMESTAMP, default=datetime.utcnow)

    # Report content
    summary = Column(Text)
    recommendations = Column(Text)
    full_report = Column(JSONB)

    __table_args__ = (
        UniqueConstraint('report_date', 'report_type',
                        name='uq_report_date_type'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'report_date': self.report_date.isoformat() if self.report_date else None,
            'week_number': self.week_number,
            'year': self.year,
            'total_trades': self.total_trades,
            'total_win_rate': float(self.total_win_rate) if self.total_win_rate else None,
            'total_pnl': float(self.total_pnl) if self.total_pnl else None,
            'symbol_metrics': self.symbol_metrics,
            'baseline_comparison': self.baseline_comparison,
            'warnings': self.warnings,
            'summary': self.summary,
            'recommendations': self.recommendations,
            'generated_at': self.generated_at.isoformat() if self.generated_at else None
        }


class ParameterOptimizationRun(Base):
    """Monthly parameter optimization results"""
    __tablename__ = 'parameter_optimization_runs'

    id = Column(Integer, primary_key=True)
    run_date = Column(TIMESTAMP, default=datetime.utcnow)
    indicator_name = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)

    # Data quality metrics
    data_days = Column(Integer)
    data_trades = Column(Integer)
    data_quality_score = Column(DECIMAL(5, 2))

    # Current parameters
    current_version_id = Column(Integer, ForeignKey('indicator_parameter_versions.id'))
    current_parameters = Column(JSONB)
    current_performance = Column(JSONB)

    # Recommended new parameters
    recommended_parameters = Column(JSONB)
    recommended_performance = Column(JSONB)

    # Optimization metrics
    improvement_win_rate = Column(DECIMAL(5, 2))
    improvement_pnl = Column(DECIMAL(10, 2))
    improvement_score = Column(DECIMAL(5, 2))

    # Safeguard checks
    safeguards_passed = Column(Boolean, default=False)
    safeguard_details = Column(JSONB)

    # Recommendation
    recommendation = Column(String(20))  # keep, adjust, disable
    confidence = Column(String(20))      # low, medium, high
    reason = Column(Text)

    # Status
    status = Column(String(20), default='pending_review')
    reviewed_by = Column(String(100))
    reviewed_at = Column(TIMESTAMP)
    review_notes = Column(Text)

    __table_args__ = (
        UniqueConstraint('run_date', 'indicator_name', 'symbol', 'timeframe',
                        name='uq_optimization_run'),
    )

    def to_dict(self):
        return {
            'id': self.id,
            'run_date': self.run_date.isoformat() if self.run_date else None,
            'indicator_name': self.indicator_name,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'data_quality': {
                'days': self.data_days,
                'trades': self.data_trades,
                'score': float(self.data_quality_score) if self.data_quality_score else None
            },
            'current_version_id': self.current_version_id,
            'current_parameters': self.current_parameters,
            'current_performance': self.current_performance,
            'recommended_parameters': self.recommended_parameters,
            'recommended_performance': self.recommended_performance,
            'improvements': {
                'win_rate': float(self.improvement_win_rate) if self.improvement_win_rate else None,
                'pnl': float(self.improvement_pnl) if self.improvement_pnl else None,
                'score': float(self.improvement_score) if self.improvement_score else None
            },
            'safeguards_passed': self.safeguards_passed,
            'safeguard_details': self.safeguard_details,
            'recommendation': self.recommendation,
            'confidence': self.confidence,
            'reason': self.reason,
            'status': self.status,
            'reviewed_by': self.reviewed_by,
            'reviewed_at': self.reviewed_at.isoformat() if self.reviewed_at else None
        }


class ParameterChangeLog(Base):
    """Audit trail for all parameter changes"""
    __tablename__ = 'parameter_change_log'

    id = Column(Integer, primary_key=True)
    changed_at = Column(TIMESTAMP, default=datetime.utcnow)
    indicator_name = Column(String(100), nullable=False)
    symbol = Column(String(20), nullable=False)
    timeframe = Column(String(10), nullable=False)

    # Version change
    old_version_id = Column(Integer, ForeignKey('indicator_parameter_versions.id'))
    new_version_id = Column(Integer, ForeignKey('indicator_parameter_versions.id'))

    # Change details
    changes = Column(JSONB)
    change_type = Column(String(50))  # manual, auto_optimization, rollback

    # Reason
    reason = Column(Text)
    changed_by = Column(String(100))

    # Impact tracking
    trades_before_change = Column(Integer)
    trades_after_change = Column(Integer)
    performance_impact = Column(JSONB)

    def to_dict(self):
        return {
            'id': self.id,
            'changed_at': self.changed_at.isoformat() if self.changed_at else None,
            'indicator_name': self.indicator_name,
            'symbol': self.symbol,
            'timeframe': self.timeframe,
            'old_version_id': self.old_version_id,
            'new_version_id': self.new_version_id,
            'changes': self.changes,
            'change_type': self.change_type,
            'reason': self.reason,
            'changed_by': self.changed_by,
            'trades_before': self.trades_before_change,
            'trades_after': self.trades_after_change,
            'performance_impact': self.performance_impact
        }
