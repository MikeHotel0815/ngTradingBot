#!/usr/bin/env python3
"""
Parameter Optimization Management Tool
Review, approve, and apply parameter optimization recommendations
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from typing import Optional, List
from decimal import Decimal
from tabulate import tabulate

from sqlalchemy import and_, desc, func

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal
from parameter_versioning_models import (
    ParameterOptimizationRun,
    IndicatorParameterVersion,
    ParameterChangeLog
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ParameterOptimizationManager:
    """Manage parameter optimization recommendations"""

    def __init__(self, db_session=None):
        self.session = db_session or SessionLocal()
        self.indicator_name = 'HEIKEN_ASHI_TREND'

    def list_pending_reviews(self) -> List[ParameterOptimizationRun]:
        """List all pending optimization reviews"""

        runs = self.session.query(ParameterOptimizationRun).filter(
            and_(
                ParameterOptimizationRun.indicator_name == self.indicator_name,
                ParameterOptimizationRun.status == 'pending_review'
            )
        ).order_by(desc(ParameterOptimizationRun.run_date)).all()

        return runs

    def display_optimization_run(self, run: ParameterOptimizationRun):
        """Display optimization run details"""

        print(f"\n{'='*80}")
        print(f"OPTIMIZATION RUN #{run.id}")
        print(f"{'='*80}")
        print(f"Symbol/Timeframe: {run.symbol} {run.timeframe}")
        print(f"Run Date: {run.run_date}")
        print(f"Status: {run.status}")
        print(f"\nDATA QUALITY:")
        print(f"  - Days: {run.data_days}")
        print(f"  - Trades: {run.data_trades}")
        print(f"  - Quality Score: {run.data_quality_score}/100")

        print(f"\nCURRENT PARAMETERS:")
        for key, value in run.current_parameters.items():
            print(f"  - {key}: {value}")

        print(f"\nCURRENT PERFORMANCE:")
        perf = run.current_performance
        print(f"  - Win Rate: {perf.get('win_rate', 0):.2f}%")
        print(f"  - Total P/L: {perf.get('total_pnl', 0):+.2f} EUR")
        print(f"  - Avg P/L: {perf.get('avg_pnl', 0):+.4f} EUR")
        print(f"  - R/R Ratio: {perf.get('rr_ratio', 0):.2f}")
        print(f"  - Max Drawdown: {perf.get('max_drawdown', 0):.2f} EUR")

        print(f"\nRECOMMENDED PARAMETERS:")
        for key, value in run.recommended_parameters.items():
            old_val = run.current_parameters.get(key, 'N/A')
            if old_val != value:
                print(f"  - {key}: {old_val} → {value} ✏️")
            else:
                print(f"  - {key}: {value}")

        print(f"\nEXPECTED PERFORMANCE:")
        exp_perf = run.recommended_performance
        print(f"  - Win Rate: {exp_perf.get('win_rate', 0):.2f}% ({run.improvement_win_rate:+.2f}%)")
        print(f"  - Total P/L: {exp_perf.get('total_pnl', 0):+.2f} EUR ({run.improvement_pnl:+.2f} EUR)")
        print(f"  - R/R Ratio: {exp_perf.get('rr_ratio', 0):.2f}")

        print(f"\nIMPROVEMENT SCORE: {run.improvement_score}/100")

        print(f"\nSAFEGUARDS:")
        print(f"  - Passed: {'✅ YES' if run.safeguards_passed else '❌ NO'}")
        if not run.safeguards_passed and run.safeguard_details:
            failures = run.safeguard_details.get('failures', [])
            for failure in failures:
                print(f"    • {failure}")

        print(f"\nRECOMMENDATION: {run.recommendation.upper()} (confidence: {run.confidence})")
        print(f"REASON: {run.reason}")
        print(f"{'='*80}\n")

    def approve_optimization(
        self,
        run_id: int,
        reviewer: str = 'admin',
        notes: Optional[str] = None
    ) -> bool:
        """Approve an optimization recommendation"""

        run = self.session.query(ParameterOptimizationRun).get(run_id)

        if not run:
            logger.error(f"Optimization run {run_id} not found")
            return False

        if run.status != 'pending_review':
            logger.error(f"Optimization run {run_id} is not pending review (status: {run.status})")
            return False

        # Mark as approved
        run.status = 'approved'
        run.reviewed_by = reviewer
        run.reviewed_at = datetime.utcnow()
        run.review_notes = notes

        self.session.commit()

        logger.info(f"✅ Optimization run {run_id} approved by {reviewer}")

        return True

    def reject_optimization(
        self,
        run_id: int,
        reviewer: str = 'admin',
        notes: Optional[str] = None
    ) -> bool:
        """Reject an optimization recommendation"""

        run = self.session.query(ParameterOptimizationRun).get(run_id)

        if not run:
            logger.error(f"Optimization run {run_id} not found")
            return False

        if run.status != 'pending_review':
            logger.error(f"Optimization run {run_id} is not pending review (status: {run.status})")
            return False

        # Mark as rejected
        run.status = 'rejected'
        run.reviewed_by = reviewer
        run.reviewed_at = datetime.utcnow()
        run.review_notes = notes

        self.session.commit()

        logger.info(f"❌ Optimization run {run_id} rejected by {reviewer}")

        return True

    def apply_optimization(
        self,
        run_id: int,
        applied_by: str = 'admin'
    ) -> bool:
        """Apply an approved optimization recommendation"""

        run = self.session.query(ParameterOptimizationRun).get(run_id)

        if not run:
            logger.error(f"Optimization run {run_id} not found")
            return False

        if run.status != 'approved':
            logger.error(f"Optimization run {run_id} is not approved (status: {run.status})")
            return False

        # Get current active version
        current_version = self.session.query(IndicatorParameterVersion).get(run.current_version_id)

        if not current_version:
            logger.error(f"Current version {run.current_version_id} not found")
            return False

        # Create new parameter version
        new_version_number = self.session.query(
            func.coalesce(func.max(IndicatorParameterVersion.version), 0) + 1
        ).filter(
            and_(
                IndicatorParameterVersion.indicator_name == run.indicator_name,
                IndicatorParameterVersion.symbol == run.symbol,
                IndicatorParameterVersion.timeframe == run.timeframe
            )
        ).scalar()

        new_version = IndicatorParameterVersion(
            indicator_name=run.indicator_name,
            symbol=run.symbol,
            timeframe=run.timeframe,
            version=new_version_number,
            parameters=run.recommended_parameters,
            status='proposed',
            created_by=applied_by,
            notes=f"Generated from optimization run #{run_id}"
        )

        self.session.add(new_version)
        self.session.flush()  # Get new_version.id

        # Deactivate current version
        current_version.status = 'archived'
        current_version.deactivated_at = datetime.utcnow()

        # Activate new version
        new_version.status = 'active'
        new_version.approved_by = applied_by
        new_version.approved_at = datetime.utcnow()
        new_version.activated_at = datetime.utcnow()

        # Log the change
        change_log = ParameterChangeLog(
            indicator_name=run.indicator_name,
            symbol=run.symbol,
            timeframe=run.timeframe,
            old_version_id=current_version.id,
            new_version_id=new_version.id,
            changes=run.recommended_parameters,
            change_type='auto_optimization',
            reason=f"Applied optimization run #{run_id}: {run.reason}",
            changed_by=applied_by
        )

        self.session.add(change_log)

        # Mark optimization run as applied
        run.status = 'applied'

        self.session.commit()

        logger.info(f"✅ Optimization applied: {run.symbol} {run.timeframe} → Version {new_version_number}")
        logger.info(f"   Old version: {current_version.id} (archived)")
        logger.info(f"   New version: {new_version.id} (active)")

        # Update heiken_ashi_config.py if it exists
        self._update_config_file(run.symbol, run.timeframe, run.recommended_parameters)

        return True

    def _update_config_file(self, symbol: str, timeframe: str, params: dict):
        """Update heiken_ashi_config.py with new parameters"""

        config_file = '/projects/ngTradingBot/heiken_ashi_config.py'

        try:
            # Read current config
            with open(config_file, 'r') as f:
                content = f.read()

            # Note: This is a simple implementation - in production, use ast module for proper parsing
            logger.info(f"ℹ️  Config file update skipped - manually update {config_file} with new parameters")
            logger.info(f"   {symbol} {timeframe}: {params}")

        except Exception as e:
            logger.warning(f"Could not update config file: {e}")

    def rollback_to_version(
        self,
        symbol: str,
        timeframe: str,
        version_id: int,
        rollback_by: str = 'admin',
        reason: str = 'Manual rollback'
    ) -> bool:
        """Rollback to a previous parameter version"""

        # Get target version
        target_version = self.session.query(IndicatorParameterVersion).get(version_id)

        if not target_version:
            logger.error(f"Version {version_id} not found")
            return False

        if target_version.symbol != symbol or target_version.timeframe != timeframe:
            logger.error(f"Version {version_id} is not for {symbol} {timeframe}")
            return False

        # Get current active version
        current_version = self.session.query(IndicatorParameterVersion).filter(
            and_(
                IndicatorParameterVersion.indicator_name == self.indicator_name,
                IndicatorParameterVersion.symbol == symbol,
                IndicatorParameterVersion.timeframe == timeframe,
                IndicatorParameterVersion.status == 'active'
            )
        ).first()

        if not current_version:
            logger.error(f"No active version found for {symbol} {timeframe}")
            return False

        if current_version.id == version_id:
            logger.warning(f"Version {version_id} is already active")
            return True

        # Deactivate current version
        current_version.status = 'archived'
        current_version.deactivated_at = datetime.utcnow()

        # Activate target version
        target_version.status = 'active'
        target_version.approved_by = rollback_by
        target_version.approved_at = datetime.utcnow()
        target_version.activated_at = datetime.utcnow()

        # Log the change
        change_log = ParameterChangeLog(
            indicator_name=self.indicator_name,
            symbol=symbol,
            timeframe=timeframe,
            old_version_id=current_version.id,
            new_version_id=target_version.id,
            changes=target_version.parameters,
            change_type='rollback',
            reason=reason,
            changed_by=rollback_by
        )

        self.session.add(change_log)
        self.session.commit()

        logger.info(f"✅ Rolled back to version {target_version.version} (ID: {version_id})")

        return True


def main():
    """CLI interface for parameter optimization management"""

    parser = argparse.ArgumentParser(description='Manage Heiken Ashi parameter optimizations')
    subparsers = parser.add_subparsers(dest='command', help='Command to execute')

    # List pending reviews
    subparsers.add_parser('list', help='List all pending optimization reviews')

    # Show details
    show_parser = subparsers.add_parser('show', help='Show optimization run details')
    show_parser.add_argument('run_id', type=int, help='Optimization run ID')

    # Approve
    approve_parser = subparsers.add_parser('approve', help='Approve an optimization')
    approve_parser.add_argument('run_id', type=int, help='Optimization run ID')
    approve_parser.add_argument('--reviewer', default='admin', help='Reviewer name')
    approve_parser.add_argument('--notes', help='Review notes')

    # Reject
    reject_parser = subparsers.add_parser('reject', help='Reject an optimization')
    reject_parser.add_argument('run_id', type=int, help='Optimization run ID')
    reject_parser.add_argument('--reviewer', default='admin', help='Reviewer name')
    reject_parser.add_argument('--notes', help='Review notes')

    # Apply
    apply_parser = subparsers.add_parser('apply', help='Apply an approved optimization')
    apply_parser.add_argument('run_id', type=int, help='Optimization run ID')
    apply_parser.add_argument('--applied-by', default='admin', help='Applicant name')

    # Rollback
    rollback_parser = subparsers.add_parser('rollback', help='Rollback to previous version')
    rollback_parser.add_argument('symbol', help='Symbol (e.g., XAUUSD)')
    rollback_parser.add_argument('timeframe', help='Timeframe (e.g., M5)')
    rollback_parser.add_argument('version_id', type=int, help='Version ID to rollback to')
    rollback_parser.add_argument('--rollback-by', default='admin', help='Rollback executor')
    rollback_parser.add_argument('--reason', default='Manual rollback', help='Rollback reason')

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    manager = ParameterOptimizationManager()

    if args.command == 'list':
        runs = manager.list_pending_reviews()

        if not runs:
            print("No pending optimization reviews")
            return 0

        table_data = []
        for run in runs:
            table_data.append([
                run.id,
                f"{run.symbol} {run.timeframe}",
                run.run_date.strftime('%Y-%m-%d'),
                f"{run.improvement_score}/100",
                run.recommendation,
                run.confidence,
                '✅' if run.safeguards_passed else '❌'
            ])

        print(f"\n📊 PENDING OPTIMIZATION REVIEWS ({len(runs)})")
        print(tabulate(
            table_data,
            headers=['ID', 'Symbol/TF', 'Date', 'Score', 'Recommendation', 'Confidence', 'Safeguards'],
            tablefmt='grid'
        ))
        print()

    elif args.command == 'show':
        run = manager.session.query(ParameterOptimizationRun).get(args.run_id)
        if run:
            manager.display_optimization_run(run)
        else:
            print(f"Optimization run {args.run_id} not found")
            return 1

    elif args.command == 'approve':
        success = manager.approve_optimization(args.run_id, args.reviewer, args.notes)
        return 0 if success else 1

    elif args.command == 'reject':
        success = manager.reject_optimization(args.run_id, args.reviewer, args.notes)
        return 0 if success else 1

    elif args.command == 'apply':
        success = manager.apply_optimization(args.run_id, args.applied_by)
        return 0 if success else 1

    elif args.command == 'rollback':
        success = manager.rollback_to_version(
            args.symbol,
            args.timeframe,
            args.version_id,
            args.rollback_by,
            args.reason
        )
        return 0 if success else 1

    return 0


if __name__ == '__main__':
    sys.exit(main())
