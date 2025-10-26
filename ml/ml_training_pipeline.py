"""
ML Training Pipeline

Automated training and retraining workflow for ML models.

Features:
- Scheduled daily/weekly training
- Auto-retraining when performance degrades
- Multi-symbol parallel training
- Training run tracking
- Email/webhook notifications (optional)

Usage:
    # Manual training
    python3 ml/ml_training_pipeline.py --symbol EURUSD --days 90

    # Train all symbols
    python3 ml/ml_training_pipeline.py --all-symbols --days 90

    # Schedule automatic retraining (via cron)
    # Run every Sunday at 2 AM:
    # 0 2 * * 0 cd /app && python3 ml/ml_training_pipeline.py --all-symbols --days 90
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
import json

from models import MLModel, MLTrainingRun, SymbolConfig
from ml.ml_confidence_model import XGBoostConfidenceModel
from ml.ml_model_manager import MLModelManager
from ml.ml_features import FeatureEngineer

logger = logging.getLogger(__name__)


class MLTrainingPipeline:
    """Automated ML training pipeline"""

    # Training configuration
    DEFAULT_TRAINING_DAYS = 90
    MIN_TRADES_REQUIRED = 100
    VALIDATION_SPLIT = 0.2

    # Retraining triggers
    RETRAIN_INTERVAL_DAYS = 7  # Retrain weekly
    RETRAIN_IF_ACCURACY_BELOW = 0.55  # Retrain if accuracy drops below 55%

    def __init__(
        self,
        db: Session,
        account_id: int = 1,
        model_dir: str = 'ml_models/xgboost'
    ):
        """
        Initialize training pipeline

        Args:
            db: Database session
            account_id: Account ID
            model_dir: Directory to save models
        """
        self.db = db
        self.account_id = account_id
        self.model_dir = model_dir
        self.model_manager = MLModelManager(db, account_id, model_dir)

    def should_retrain(self, symbol: Optional[str] = None) -> bool:
        """
        Check if model should be retrained

        Args:
            symbol: Symbol (None = global)

        Returns:
            True if retraining is needed
        """
        # Get active model
        query = self.db.query(MLModel).filter(
            MLModel.model_type == 'xgboost',
            MLModel.is_active == True
        )

        if symbol:
            query = query.filter(MLModel.symbol == symbol)
        else:
            query = query.filter(MLModel.symbol == None)

        model = query.first()

        if not model:
            logger.info(f"No active model for {symbol or 'GLOBAL'} - training needed")
            return True

        # Check if model is old
        days_since_training = (datetime.utcnow() - model.created_at).days
        if days_since_training >= self.RETRAIN_INTERVAL_DAYS:
            logger.info(f"Model is {days_since_training} days old - retraining needed")
            return True

        # Check if performance has degraded
        if model.status == 'needs_retraining':
            logger.info(f"Model marked for retraining")
            return True

        # Check recent performance
        perf = self.model_manager.get_model_performance(model.id, days_back=7)
        if perf['total_predictions'] >= 50 and perf['accuracy'] < self.RETRAIN_IF_ACCURACY_BELOW:
            logger.info(f"Model accuracy too low ({perf['accuracy']:.3f}) - retraining needed")
            return True

        logger.info(f"Model for {symbol or 'GLOBAL'} is performing well - no retraining needed")
        return False

    def train_model(
        self,
        symbol: Optional[str] = None,
        days_back: int = DEFAULT_TRAINING_DAYS,
        force: bool = False
    ) -> Optional[Dict]:
        """
        Train XGBoost model for symbol

        Args:
            symbol: Symbol (None = global)
            days_back: Days of training data
            force: Force training even if not needed

        Returns:
            Dict with training results or None if skipped
        """
        symbol_name = symbol or 'GLOBAL'

        logger.info(f"\n{'='*60}")
        logger.info(f"TRAINING PIPELINE: {symbol_name}")
        logger.info(f"{'='*60}")

        # Check if training needed
        if not force and not self.should_retrain(symbol):
            logger.info(f"Skipping training for {symbol_name} (not needed)")
            return None

        # Create training run record
        training_run = MLTrainingRun(
            model_type='xgboost',
            symbol=symbol,
            started_at=datetime.utcnow(),
            status='running',
            training_params={
                'days_back': days_back,
                'test_size': self.VALIDATION_SPLIT
            }
        )
        self.db.add(training_run)
        self.db.commit()

        try:
            # Initialize model
            model = XGBoostConfidenceModel(
                db=self.db,
                account_id=self.account_id,
                model_dir=self.model_dir
            )

            # Train
            logger.info(f"Training XGBoost model for {symbol_name}...")
            start_time = datetime.now()

            results = model.train(
                symbol=symbol,
                days_back=days_back,
                test_size=self.VALIDATION_SPLIT,
                cross_validate=True,
                save_model=False  # We'll save manually with registration
            )

            duration = (datetime.now() - start_time).total_seconds()

            # Save model
            logger.info("Saving model...")
            version = datetime.now().strftime("%Y%m%d_%H%M%S")
            symbol_part = f"{symbol}_" if symbol else "global_"
            filename = f"{symbol_part}v{version}.pkl"
            filepath = model.save(symbol=symbol)

            # Register in database
            logger.info("Registering model in database...")
            model_id = self.model_manager.register_new_model(
                model_type='xgboost',
                symbol=symbol,
                version=version,
                file_path=filename,
                validation_metrics={
                    'accuracy': results['accuracy'],
                    'precision': results['precision'],
                    'recall': results['recall'],
                    'f1_score': results['f1_score'],
                    'auc_roc': results['auc_roc']
                },
                hyperparameters=model.DEFAULT_PARAMS,
                feature_importance=dict(results['top_10_features']),
                is_active=True
            )

            # Update training run
            training_run.completed_at = datetime.utcnow()
            training_run.duration_seconds = duration
            training_run.status = 'completed'
            training_run.model_id = model_id
            training_run.training_samples = results['training_samples']
            training_run.validation_samples = results['test_samples']
            training_run.validation_accuracy = results['accuracy']
            training_run.validation_loss = 1.0 - results['accuracy']  # Approximation
            training_run.metadata = {
                'feature_count': results['feature_count'],
                'top_features': results['top_10_features']
            }
            self.db.commit()

            logger.info(f"✅ Training complete for {symbol_name}")
            logger.info(f"   Model ID: {model_id}")
            logger.info(f"   Accuracy: {results['accuracy']:.3f}")
            logger.info(f"   Duration: {duration:.1f}s")

            return results

        except Exception as e:
            logger.error(f"❌ Training failed for {symbol_name}: {e}", exc_info=True)

            # Update training run as failed
            training_run.completed_at = datetime.utcnow()
            training_run.status = 'failed'
            training_run.error_message = str(e)
            self.db.commit()

            return None

    def train_all_symbols(
        self,
        days_back: int = DEFAULT_TRAINING_DAYS,
        force: bool = False,
        include_global: bool = True
    ) -> Dict:
        """
        Train models for all active symbols

        Args:
            days_back: Days of training data
            force: Force training even if not needed
            include_global: Also train global model

        Returns:
            Dict with summary statistics
        """
        logger.info(f"\n{'='*60}")
        logger.info("BATCH TRAINING: ALL SYMBOLS")
        logger.info(f"{'='*60}")

        stats = {
            'total': 0,
            'trained': 0,
            'skipped': 0,
            'failed': 0,
            'results': []
        }

        # Get active symbols
        active_symbols = self.db.query(SymbolConfig).filter(
            SymbolConfig.account_id == self.account_id,
            SymbolConfig.status == 'active'
        ).all()

        symbols_to_train = [s.symbol for s in active_symbols]

        if include_global:
            symbols_to_train.append(None)  # Global model

        stats['total'] = len(symbols_to_train)

        # Train each symbol
        for symbol in symbols_to_train:
            result = self.train_model(
                symbol=symbol,
                days_back=days_back,
                force=force
            )

            if result is None:
                stats['skipped'] += 1
            elif result.get('accuracy', 0) > 0:
                stats['trained'] += 1
                stats['results'].append({
                    'symbol': symbol or 'GLOBAL',
                    'accuracy': result['accuracy'],
                    'precision': result['precision'],
                    'recall': result['recall']
                })
            else:
                stats['failed'] += 1

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info("BATCH TRAINING COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Total symbols: {stats['total']}")
        logger.info(f"Trained: {stats['trained']}")
        logger.info(f"Skipped: {stats['skipped']}")
        logger.info(f"Failed: {stats['failed']}")

        if stats['results']:
            logger.info(f"\nResults:")
            for r in stats['results']:
                logger.info(f"  {r['symbol']:<10} Accuracy: {r['accuracy']:.3f}, Precision: {r['precision']:.3f}")

        return stats

    def cleanup_old_models(self, keep_last_n: int = 3):
        """
        Clean up old model files (keep last N versions per symbol)

        Args:
            keep_last_n: Number of versions to keep
        """
        logger.info(f"Cleaning up old models (keeping last {keep_last_n} per symbol)...")

        # Get all symbols (including None for global)
        symbols = self.db.query(MLModel.symbol).distinct().all()
        symbols = [s[0] for s in symbols]

        deleted_count = 0

        for symbol in symbols:
            # Get all models for this symbol, ordered by creation date
            models = self.db.query(MLModel).filter(
                MLModel.symbol == symbol
            ).order_by(MLModel.created_at.desc()).all()

            # Keep last N, delete the rest
            to_delete = models[keep_last_n:]

            for model in to_delete:
                # Delete file if exists
                if model.file_path:
                    full_path = os.path.join(self.model_dir, model.file_path)
                    if os.path.exists(full_path):
                        try:
                            os.remove(full_path)
                            logger.info(f"Deleted old model file: {full_path}")
                            deleted_count += 1
                        except Exception as e:
                            logger.error(f"Error deleting {full_path}: {e}")

                # Delete database record
                self.db.delete(model)

        self.db.commit()
        logger.info(f"✅ Cleaned up {deleted_count} old model files")

    def get_training_history(self, symbol: Optional[str] = None, limit: int = 10) -> List[Dict]:
        """
        Get training history for symbol

        Args:
            symbol: Symbol (None = global)
            limit: Max results

        Returns:
            List of training run dicts
        """
        query = self.db.query(MLTrainingRun)

        if symbol is not None:
            query = query.filter(MLTrainingRun.symbol == symbol)

        runs = query.order_by(MLTrainingRun.started_at.desc()).limit(limit).all()

        history = []
        for run in runs:
            history.append({
                'id': run.id,
                'symbol': run.symbol or 'GLOBAL',
                'started_at': run.started_at,
                'completed_at': run.completed_at,
                'duration_seconds': run.duration_seconds,
                'status': run.status,
                'validation_accuracy': run.validation_accuracy,
                'training_samples': run.training_samples,
                'error_message': run.error_message
            })

        return history


# CLI entry point
if __name__ == '__main__':
    import argparse
    from database import get_session

    parser = argparse.ArgumentParser(description='ML Training Pipeline')
    parser.add_argument('--symbol', help='Symbol to train (default: global model)')
    parser.add_argument('--all-symbols', action='store_true', help='Train all active symbols')
    parser.add_argument('--days', type=int, default=90, help='Days of training data (default: 90)')
    parser.add_argument('--force', action='store_true', help='Force training even if not needed')
    parser.add_argument('--cleanup', action='store_true', help='Clean up old model files')
    parser.add_argument('--history', action='store_true', help='Show training history')

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Get database session
    db = next(get_session())
    pipeline = MLTrainingPipeline(db)

    if args.cleanup:
        pipeline.cleanup_old_models(keep_last_n=3)

    elif args.history:
        symbol = args.symbol if args.symbol else None
        history = pipeline.get_training_history(symbol=symbol, limit=20)

        print(f"\n{'='*80}")
        print(f"TRAINING HISTORY: {symbol or 'ALL SYMBOLS'}")
        print(f"{'='*80}")
        print(f"{'ID':<5} {'Symbol':<10} {'Started':<20} {'Duration':<10} {'Status':<12} {'Accuracy':<10}")
        print(f"{'='*80}")

        for run in history:
            started = run['started_at'].strftime('%Y-%m-%d %H:%M') if run['started_at'] else 'N/A'
            duration = f"{run['duration_seconds']:.1f}s" if run['duration_seconds'] else 'N/A'
            accuracy = f"{run['validation_accuracy']:.3f}" if run['validation_accuracy'] else 'N/A'

            print(f"{run['id']:<5} {run['symbol']:<10} {started:<20} {duration:<10} {run['status']:<12} {accuracy:<10}")

    elif args.all_symbols:
        stats = pipeline.train_all_symbols(
            days_back=args.days,
            force=args.force
        )

        print(f"\n✅ Batch training complete!")
        print(f"   Trained: {stats['trained']}/{stats['total']}")
        print(f"   Skipped: {stats['skipped']}")
        print(f"   Failed: {stats['failed']}")

    else:
        # Train single symbol (or global)
        symbol = args.symbol if args.symbol else None

        result = pipeline.train_model(
            symbol=symbol,
            days_back=args.days,
            force=args.force
        )

        if result:
            print(f"\n✅ Training complete!")
            print(f"   Symbol: {symbol or 'GLOBAL'}")
            print(f"   Accuracy: {result['accuracy']:.3f}")
            print(f"   Precision: {result['precision']:.3f}")
            print(f"   Recall: {result['recall']:.3f}")
            print(f"   F1 Score: {result['f1_score']:.3f}")
            print(f"   AUC-ROC: {result['auc_roc']:.3f}")
        else:
            print(f"\n⚠️ Training skipped or failed")
