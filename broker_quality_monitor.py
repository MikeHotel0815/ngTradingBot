"""
Broker Quality Monitoring System

Tracks execution quality metrics to detect broker issues:
- Execution delays
- Slippage (difference between expected and actual fill price)
- Requotes (order rejections)
- Spread spikes
- Commission/swap tracking

Alerts when broker quality degrades below acceptable thresholds.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from sqlalchemy import Column, Integer, String, DateTime, Numeric, Boolean, Text
from sqlalchemy.orm import Session
from database import Base, ScopedSession
from models import Trade, Command, Tick

logger = logging.getLogger(__name__)


class BrokerQualityMetric(Base):
    """Broker execution quality metrics"""
    __tablename__ = 'broker_quality_metrics'

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(Integer, nullable=False)
    symbol = Column(String(20), nullable=False)

    # Time period
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)

    # Execution Metrics
    total_trades = Column(Integer, default=0)
    total_commands = Column(Integer, default=0)
    successful_executions = Column(Integer, default=0)
    failed_executions = Column(Integer, default=0)
    execution_rate = Column(Numeric(5, 2))  # Success rate %

    # Timing Metrics (in milliseconds)
    avg_execution_time_ms = Column(Integer)
    max_execution_time_ms = Column(Integer)
    min_execution_time_ms = Column(Integer)

    # Slippage Metrics (in pips)
    total_slippage_pips = Column(Numeric(10, 2))
    avg_slippage_pips = Column(Numeric(6, 2))
    max_slippage_pips = Column(Numeric(6, 2))
    positive_slippage_count = Column(Integer, default=0)  # Better than expected
    negative_slippage_count = Column(Integer, default=0)  # Worse than expected

    # Spread Metrics
    avg_spread = Column(Numeric(10, 5))
    max_spread = Column(Numeric(10, 5))
    spread_spike_count = Column(Integer, default=0)  # > 3x normal

    # Requote Metrics
    requote_count = Column(Integer, default=0)
    requote_rate = Column(Numeric(5, 2))  # % of trades

    # Commission/Swap
    total_commission = Column(Numeric(10, 2))
    total_swap = Column(Numeric(10, 2))

    # Quality Score (0-100)
    quality_score = Column(Numeric(5, 2))

    # Alerts
    quality_degraded = Column(Boolean, default=False)
    alert_reason = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)


class BrokerQualityMonitor:
    """Monitor and analyze broker execution quality"""

    def __init__(self, account_id: int):
        self.account_id = account_id
        self._ensure_table_exists()

        # Quality thresholds
        self.min_execution_rate = 95.0  # 95% success rate
        self.max_avg_slippage = 2.0  # 2 pips average
        self.max_avg_execution_time = 5000  # 5 seconds
        self.max_requote_rate = 5.0  # 5% requotes

    def _ensure_table_exists(self):
        """Create table if not exists"""
        import os
        from sqlalchemy import create_engine

        db_host = os.getenv('DB_HOST', 'postgres')
        db_port = os.getenv('DB_PORT', '5432')
        db_name = os.getenv('DB_NAME', 'ngtradingbot')
        db_user = os.getenv('DB_USER', 'trader')
        db_pass = os.getenv('DB_PASSWORD', 'tradingbot_secret_2025')

        database_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
        engine = create_engine(database_url)
        Base.metadata.create_all(engine, tables=[BrokerQualityMetric.__table__])

    def record_execution(self, command: Command, trade: Optional[Trade], execution_time_ms: int):
        """
        Record execution quality metrics for a command

        Args:
            command: Command that was executed
            trade: Resulting trade (None if failed)
            execution_time_ms: Time taken to execute in milliseconds
        """
        db = ScopedSession()

        try:
            symbol = command.payload.get('symbol') if command.payload else 'UNKNOWN'

            # Calculate slippage if trade executed
            slippage_pips = 0.0
            if trade and command.payload:
                expected_price = command.payload.get('price') or command.payload.get('entry_price')
                actual_price = float(trade.open_price) if trade.open_price else 0.0

                if expected_price and actual_price:
                    # Calculate slippage in pips
                    price_diff = abs(actual_price - expected_price)
                    # Convert to pips (assume 1 pip = 0.0001 for most pairs, 0.01 for JPY)
                    pip_value = 0.01 if 'JPY' in symbol else 0.0001
                    slippage_pips = price_diff / pip_value

                    logger.info(
                        f"📊 Execution quality: {symbol} - "
                        f"Expected: {expected_price:.5f}, Actual: {actual_price:.5f}, "
                        f"Slippage: {slippage_pips:.2f} pips, Time: {execution_time_ms}ms"
                    )

            # Get or create current period metric (hourly aggregation)
            now = datetime.utcnow()
            period_start = now.replace(minute=0, second=0, microsecond=0)
            period_end = period_start + timedelta(hours=1)

            metric = db.query(BrokerQualityMetric).filter(
                BrokerQualityMetric.account_id == self.account_id,
                BrokerQualityMetric.symbol == symbol,
                BrokerQualityMetric.period_start == period_start
            ).first()

            if not metric:
                metric = BrokerQualityMetric(
                    account_id=self.account_id,
                    symbol=symbol,
                    period_start=period_start,
                    period_end=period_end,
                    total_trades=0,
                    total_commands=0,
                    successful_executions=0,
                    failed_executions=0
                )
                db.add(metric)

            # Update metrics
            metric.total_commands += 1

            if trade:
                metric.successful_executions += 1
                metric.total_trades += 1

                # Update slippage
                if not metric.total_slippage_pips:
                    metric.total_slippage_pips = 0.0
                metric.total_slippage_pips += slippage_pips

                if slippage_pips > 0:
                    metric.negative_slippage_count = (metric.negative_slippage_count or 0) + 1
                elif slippage_pips < 0:
                    metric.positive_slippage_count = (metric.positive_slippage_count or 0) + 1

                # Update max slippage
                if not metric.max_slippage_pips or abs(slippage_pips) > metric.max_slippage_pips:
                    metric.max_slippage_pips = abs(slippage_pips)

                # Update commission/swap
                if trade.commission:
                    metric.total_commission = (metric.total_commission or 0) + float(trade.commission)
                if trade.swap:
                    metric.total_swap = (metric.total_swap or 0) + float(trade.swap)
            else:
                metric.failed_executions += 1

            # Update execution time
            if not metric.min_execution_time_ms or execution_time_ms < metric.min_execution_time_ms:
                metric.min_execution_time_ms = execution_time_ms
            if not metric.max_execution_time_ms or execution_time_ms > metric.max_execution_time_ms:
                metric.max_execution_time_ms = execution_time_ms

            # Calculate averages
            metric.execution_rate = (metric.successful_executions / metric.total_commands * 100) if metric.total_commands > 0 else 0
            metric.avg_execution_time_ms = int((metric.min_execution_time_ms + metric.max_execution_time_ms) / 2) if metric.min_execution_time_ms else execution_time_ms
            metric.avg_slippage_pips = (metric.total_slippage_pips / metric.successful_executions) if metric.successful_executions > 0 else 0

            # Calculate quality score
            metric.quality_score = self._calculate_quality_score(metric)

            # Check if quality degraded
            if metric.quality_score < 70.0:
                metric.quality_degraded = True
                metric.alert_reason = self._generate_quality_alert(metric)
                logger.warning(f"⚠️  Broker quality degraded for {symbol}: {metric.alert_reason}")

            db.commit()

        except Exception as e:
            logger.error(f"Error recording execution quality: {e}", exc_info=True)
            db.rollback()
        finally:
            db.close()

    def _calculate_quality_score(self, metric: BrokerQualityMetric) -> float:
        """
        Calculate overall quality score (0-100)

        Factors:
        - Execution rate: 40%
        - Slippage: 30%
        - Execution time: 20%
        - Requote rate: 10%
        """
        score = 0.0

        # Execution rate (40 points)
        if metric.execution_rate:
            score += (metric.execution_rate / 100) * 40

        # Slippage (30 points) - lower is better
        if metric.avg_slippage_pips is not None:
            slippage_score = max(0, 30 - (metric.avg_slippage_pips * 5))  # -5 points per pip
            score += slippage_score

        # Execution time (20 points) - faster is better
        if metric.avg_execution_time_ms:
            if metric.avg_execution_time_ms < 1000:
                score += 20  # < 1s = full points
            elif metric.avg_execution_time_ms < 3000:
                score += 15  # < 3s = 15 points
            elif metric.avg_execution_time_ms < 5000:
                score += 10  # < 5s = 10 points
            else:
                score += 5  # > 5s = 5 points

        # Requote rate (10 points) - lower is better
        if metric.requote_rate is not None:
            requote_score = max(0, 10 - (metric.requote_rate * 2))  # -2 points per %
            score += requote_score
        else:
            score += 10  # No requotes = full points

        return round(score, 2)

    def _generate_quality_alert(self, metric: BrokerQualityMetric) -> str:
        """Generate alert message describing quality issues"""
        issues = []

        if metric.execution_rate < self.min_execution_rate:
            issues.append(f"Low execution rate: {metric.execution_rate:.1f}% (min: {self.min_execution_rate}%)")

        if metric.avg_slippage_pips and metric.avg_slippage_pips > self.max_avg_slippage:
            issues.append(f"High slippage: {metric.avg_slippage_pips:.2f} pips (max: {self.max_avg_slippage} pips)")

        if metric.avg_execution_time_ms and metric.avg_execution_time_ms > self.max_avg_execution_time:
            issues.append(f"Slow execution: {metric.avg_execution_time_ms}ms (max: {self.max_avg_execution_time}ms)")

        if metric.requote_rate and metric.requote_rate > self.max_requote_rate:
            issues.append(f"High requote rate: {metric.requote_rate:.1f}% (max: {self.max_requote_rate}%)")

        return "; ".join(issues) if issues else "Quality score below threshold"

    def get_quality_report(self, hours: int = 24) -> Dict:
        """
        Get broker quality report for the last N hours

        Returns:
            Dict with quality metrics and alerts
        """
        db = ScopedSession()

        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)

            metrics = db.query(BrokerQualityMetric).filter(
                BrokerQualityMetric.account_id == self.account_id,
                BrokerQualityMetric.period_start >= cutoff
            ).all()

            if not metrics:
                return {'status': 'no_data', 'message': 'No execution data available'}

            # Aggregate metrics
            total_commands = sum(m.total_commands for m in metrics)
            total_trades = sum(m.total_trades for m in metrics)
            successful = sum(m.successful_executions for m in metrics)
            failed = sum(m.failed_executions for m in metrics)

            overall_execution_rate = (successful / total_commands * 100) if total_commands > 0 else 0

            # Average slippage
            total_slippage = sum(m.total_slippage_pips or 0 for m in metrics)
            overall_avg_slippage = (total_slippage / total_trades) if total_trades > 0 else 0

            # Quality score
            quality_scores = [m.quality_score for m in metrics if m.quality_score]
            overall_quality = sum(quality_scores) / len(quality_scores) if quality_scores else 0

            # Degraded symbols
            degraded_symbols = [m.symbol for m in metrics if m.quality_degraded]

            return {
                'status': 'ok' if overall_quality >= 70 else 'degraded',
                'period_hours': hours,
                'overall_quality_score': round(overall_quality, 2),
                'execution_rate': round(overall_execution_rate, 2),
                'avg_slippage_pips': round(overall_avg_slippage, 2),
                'total_commands': total_commands,
                'total_trades': total_trades,
                'successful_executions': successful,
                'failed_executions': failed,
                'degraded_symbols': degraded_symbols,
                'recommendation': self._get_recommendation(overall_quality, overall_execution_rate)
            }

        except Exception as e:
            logger.error(f"Error generating quality report: {e}", exc_info=True)
            return {'status': 'error', 'error': str(e)}
        finally:
            db.close()

    def _get_recommendation(self, quality_score: float, execution_rate: float) -> str:
        """Get recommendation based on quality metrics"""
        if quality_score >= 80 and execution_rate >= 95:
            return "✅ Broker quality is excellent. Continue trading."
        elif quality_score >= 70 and execution_rate >= 90:
            return "✓ Broker quality is acceptable. Monitor closely."
        elif quality_score >= 60:
            return "⚠️ Broker quality is degraded. Consider reducing position sizes or pausing trading."
        else:
            return "🚨 Broker quality is poor. STOP TRADING and investigate broker issues!"


def get_broker_quality_monitor(account_id: int) -> BrokerQualityMonitor:
    """Get broker quality monitor instance"""
    return BrokerQualityMonitor(account_id)
