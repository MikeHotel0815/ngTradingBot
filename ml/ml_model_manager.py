"""
ML Model Manager

Handles model lifecycle management for the trading bot:
- Loading/reloading models without bot restart
- Model versioning and rollback
- A/B testing (ML vs Rules)
- Performance tracking and auto-switching
- Symbol-specific model selection

Usage:
    from ml.ml_model_manager import MLModelManager

    manager = MLModelManager(db)

    # Get best model for symbol
    confidence = manager.predict(symbol='EURUSD', features=features)

    # Log prediction outcome
    manager.log_prediction_outcome(prediction_id, actual_profit)

    # Evaluate and switch models if needed
    manager.evaluate_and_switch_models()
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, Optional, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import text

from models import MLModel, MLPrediction, MLABTest
from ml.ml_confidence_model import XGBoostConfidenceModel

logger = logging.getLogger(__name__)


class MLModelManager:
    """Manages ML model lifecycle for trading bot"""

    # A/B Testing configuration
    AB_TEST_SPLIT = {
        'ml_only': 0.80,      # 80% use ML model
        'rules_only': 0.10,   # 10% use original rules
        'hybrid': 0.10        # 10% use hybrid (ML + rules)
    }

    # Performance thresholds for auto-switching
    MIN_PREDICTIONS = 50       # Minimum predictions before evaluating
    MIN_ACCURACY_THRESHOLD = 0.55  # Switch if accuracy < 55%
    EVALUATION_WINDOW_DAYS = 7     # Evaluate last 7 days

    def __init__(
        self,
        db: Session,
        account_id: int = 1,
        model_dir: str = 'ml_models/xgboost'
    ):
        """
        Initialize ML Model Manager

        Args:
            db: Database session
            account_id: Account ID
            model_dir: Directory containing models
        """
        self.db = db
        self.account_id = account_id
        self.model_dir = model_dir

        # Loaded models cache (symbol -> XGBoostConfidenceModel)
        self.loaded_models: Dict[str, XGBoostConfidenceModel] = {}

        # Track when models were loaded (for hot-reloading)
        self.model_load_times: Dict[str, datetime] = {}

    def get_active_model_path(self, symbol: Optional[str] = None) -> Optional[str]:
        """
        Get path to active model for symbol (or global)

        Args:
            symbol: Symbol (None = global model)

        Returns:
            Path to .pkl file or None if no active model
        """
        # Check database for active model
        query = self.db.query(MLModel).filter(
            MLModel.is_active == True,
            MLModel.model_type == 'xgboost'
        )

        if symbol:
            query = query.filter(MLModel.symbol == symbol)
        else:
            query = query.filter(MLModel.symbol == None)

        model_record = query.order_by(MLModel.created_at.desc()).first()

        if model_record and model_record.file_path:
            full_path = os.path.join(self.model_dir, model_record.file_path)
            if os.path.exists(full_path):
                return full_path
            else:
                logger.warning(f"Model file not found: {full_path}")

        # Fallback: look for latest.pkl
        symbol_part = f"{symbol}_" if symbol else "global_"
        latest_path = os.path.join(self.model_dir, f"{symbol_part}latest.pkl")

        if os.path.exists(latest_path):
            logger.info(f"Using fallback latest model: {latest_path}")
            return latest_path

        return None

    def load_model(self, symbol: Optional[str] = None, force_reload: bool = False) -> Optional[XGBoostConfidenceModel]:
        """
        Load ML model for symbol (cached)

        Args:
            symbol: Symbol (None = global model)
            force_reload: Force reload from disk

        Returns:
            XGBoostConfidenceModel or None if unavailable
        """
        cache_key = symbol or 'global'

        # Check if already loaded (and not forcing reload)
        if not force_reload and cache_key in self.loaded_models:
            return self.loaded_models[cache_key]

        # Get model path
        model_path = self.get_active_model_path(symbol)

        if not model_path:
            logger.debug(f"No active model for {cache_key}")
            return None

        try:
            # Load model
            model = XGBoostConfidenceModel(self.db, self.account_id, self.model_dir)
            model.load(model_path)

            # Cache it
            self.loaded_models[cache_key] = model
            self.model_load_times[cache_key] = datetime.now()

            logger.info(f"✅ Loaded model for {cache_key} from {model_path}")
            return model

        except Exception as e:
            logger.error(f"Error loading model for {cache_key}: {e}")
            return None

    def predict(
        self,
        symbol: str,
        features: Dict,
        use_global_fallback: bool = True
    ) -> Optional[float]:
        """
        Get ML confidence prediction for signal

        Args:
            symbol: Symbol
            features: Features dict from FeatureEngineer
            use_global_fallback: Use global model if symbol-specific unavailable

        Returns:
            Confidence score 0-1 or None if no model available
        """
        # Try symbol-specific model first
        model = self.load_model(symbol=symbol)

        # Fallback to global model if requested
        if model is None and use_global_fallback:
            model = self.load_model(symbol=None)

        if model is None:
            logger.debug(f"No ML model available for {symbol}")
            return None

        try:
            confidence = model.predict(features)
            return confidence
        except Exception as e:
            logger.error(f"Error predicting for {symbol}: {e}")
            return None

    def log_prediction(
        self,
        symbol: str,
        features: Dict,
        ml_confidence: float,
        rules_confidence: float,
        final_confidence: float,
        decision: str,
        ab_test_group: str
    ) -> Optional[int]:
        """
        Log ML prediction for later evaluation

        Args:
            symbol: Symbol
            features: Features used
            ml_confidence: ML model confidence
            rules_confidence: Rules-based confidence
            final_confidence: Final confidence used
            decision: 'trade' or 'no_trade'
            ab_test_group: 'ml_only', 'rules_only', or 'hybrid'

        Returns:
            prediction_id or None
        """
        try:
            # Get active model ID
            model_query = self.db.query(MLModel).filter(
                MLModel.is_active == True,
                MLModel.model_type == 'xgboost'
            )

            # Try symbol-specific, fallback to global
            model_record = model_query.filter(MLModel.symbol == symbol).first()
            if not model_record:
                model_record = model_query.filter(MLModel.symbol == None).first()

            if not model_record:
                logger.warning("No active model to log prediction against")
                return None

            prediction = MLPrediction(
                model_id=model_record.id,
                symbol=symbol,
                prediction_time=datetime.utcnow(),
                ml_confidence=ml_confidence,
                rules_confidence=rules_confidence,
                final_confidence=final_confidence,
                decision=decision,
                ab_test_group=ab_test_group,
                features_used=features
            )

            self.db.add(prediction)
            self.db.commit()

            return prediction.id

        except Exception as e:
            logger.error(f"Error logging prediction: {e}")
            self.db.rollback()
            return None

    def log_prediction_outcome(
        self,
        prediction_id: int,
        actual_outcome: str,
        actual_profit: Optional[float] = None,
        trade_id: Optional[int] = None
    ):
        """
        Update prediction with actual outcome

        Args:
            prediction_id: Prediction ID
            actual_outcome: 'win', 'loss', or 'no_trade'
            actual_profit: Actual profit/loss
            trade_id: Associated trade ID
        """
        try:
            prediction = self.db.query(MLPrediction).filter(
                MLPrediction.id == prediction_id
            ).first()

            if prediction:
                prediction.actual_outcome = actual_outcome
                prediction.actual_profit = actual_profit
                prediction.trade_id = trade_id
                prediction.outcome_time = datetime.utcnow()

                self.db.commit()
                logger.debug(f"Updated prediction #{prediction_id} with outcome: {actual_outcome}")
            else:
                logger.warning(f"Prediction #{prediction_id} not found")

        except Exception as e:
            logger.error(f"Error updating prediction outcome: {e}")
            self.db.rollback()

    def get_model_performance(
        self,
        model_id: int,
        days_back: int = 7
    ) -> Dict:
        """
        Calculate model performance metrics

        Args:
            model_id: Model ID
            days_back: Days to analyze

        Returns:
            Dict with performance metrics
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        # Query predictions with outcomes
        predictions = self.db.query(MLPrediction).filter(
            MLPrediction.model_id == model_id,
            MLPrediction.prediction_time >= cutoff_date,
            MLPrediction.actual_outcome != None
        ).all()

        if len(predictions) == 0:
            return {
                'total_predictions': 0,
                'accuracy': 0.0,
                'avg_confidence': 0.0,
                'win_rate': 0.0,
                'avg_profit': 0.0
            }

        # Calculate metrics
        correct = 0
        total_confidence = 0.0
        wins = 0
        total_profit = 0.0
        traded = 0

        for pred in predictions:
            # Accuracy: did we predict correctly?
            if pred.decision == 'trade' and pred.actual_outcome == 'win':
                correct += 1
                wins += 1
            elif pred.decision == 'no_trade' and pred.actual_outcome == 'no_trade':
                correct += 1

            total_confidence += pred.ml_confidence or 0.0

            if pred.actual_profit is not None:
                total_profit += pred.actual_profit
                traded += 1

        accuracy = correct / len(predictions)
        avg_confidence = total_confidence / len(predictions)
        win_rate = wins / traded if traded > 0 else 0.0
        avg_profit = total_profit / traded if traded > 0 else 0.0

        return {
            'total_predictions': len(predictions),
            'accuracy': accuracy,
            'avg_confidence': avg_confidence,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'total_profit': total_profit
        }

    def evaluate_and_switch_models(self):
        """
        Evaluate active models and switch if performance is poor

        Called periodically (e.g., daily) to check if models need updating
        """
        logger.info("Evaluating ML model performance...")

        # Get all active models
        active_models = self.db.query(MLModel).filter(
            MLModel.is_active == True
        ).all()

        for model in active_models:
            perf = self.get_model_performance(
                model.id,
                days_back=self.EVALUATION_WINDOW_DAYS
            )

            symbol_name = model.symbol or 'GLOBAL'

            logger.info(f"Model {model.id} ({symbol_name}):")
            logger.info(f"  Predictions: {perf['total_predictions']}")
            logger.info(f"  Accuracy: {perf['accuracy']:.3f}")
            logger.info(f"  Win Rate: {perf['win_rate']:.3f}")
            logger.info(f"  Avg Profit: {perf['avg_profit']:.2f}")

            # Decision: should we switch?
            if perf['total_predictions'] >= self.MIN_PREDICTIONS:
                if perf['accuracy'] < self.MIN_ACCURACY_THRESHOLD:
                    logger.warning(
                        f"⚠️ Model {model.id} accuracy too low ({perf['accuracy']:.3f}). "
                        f"Consider retraining or rolling back."
                    )

                    # Mark for retraining
                    model.status = 'needs_retraining'
                    self.db.commit()

                    # TODO: Auto-trigger retraining or rollback to previous version

    def get_ab_test_group(self, symbol: str) -> str:
        """
        Determine A/B test group for symbol

        Uses consistent hash to ensure same symbol always gets same group
        (important for fair comparison)

        Args:
            symbol: Symbol

        Returns:
            'ml_only', 'rules_only', or 'hybrid'
        """
        # Simple hash-based assignment
        hash_val = hash(symbol) % 100

        if hash_val < self.AB_TEST_SPLIT['ml_only'] * 100:
            return 'ml_only'
        elif hash_val < (self.AB_TEST_SPLIT['ml_only'] + self.AB_TEST_SPLIT['rules_only']) * 100:
            return 'rules_only'
        else:
            return 'hybrid'

    def get_hybrid_confidence(
        self,
        ml_confidence: Optional[float],
        rules_confidence: float,
        ab_test_group: str
    ) -> float:
        """
        Calculate final confidence based on A/B test group

        Args:
            ml_confidence: ML model confidence (or None if unavailable)
            rules_confidence: Rules-based confidence
            ab_test_group: 'ml_only', 'rules_only', or 'hybrid'

        Returns:
            Final confidence score 0-1
        """
        if ab_test_group == 'rules_only':
            return rules_confidence

        elif ab_test_group == 'ml_only':
            if ml_confidence is not None:
                return ml_confidence
            else:
                # Fallback to rules if ML unavailable
                logger.warning("ML unavailable in ml_only group, falling back to rules")
                return rules_confidence

        elif ab_test_group == 'hybrid':
            if ml_confidence is not None:
                # Weighted average: 60% ML, 40% rules
                return 0.6 * ml_confidence + 0.4 * rules_confidence
            else:
                return rules_confidence

        else:
            logger.error(f"Unknown A/B test group: {ab_test_group}")
            return rules_confidence

    def register_new_model(
        self,
        model_type: str,
        symbol: Optional[str],
        version: str,
        file_path: str,
        validation_metrics: Dict,
        hyperparameters: Dict,
        feature_importance: Optional[Dict] = None,
        is_active: bool = True
    ) -> int:
        """
        Register new trained model in database

        Args:
            model_type: 'xgboost', 'lstm', etc.
            symbol: Symbol (None = global)
            version: Version string
            file_path: Relative path to .pkl file
            validation_metrics: Dict with accuracy, precision, recall, etc.
            hyperparameters: Model hyperparameters
            feature_importance: Optional feature importance dict
            is_active: Set as active model

        Returns:
            model_id
        """
        try:
            # Deactivate previous models for this symbol if setting as active
            if is_active:
                previous_models = self.db.query(MLModel).filter(
                    MLModel.model_type == model_type,
                    MLModel.symbol == symbol,
                    MLModel.is_active == True
                ).all()

                for prev_model in previous_models:
                    prev_model.is_active = False
                    logger.info(f"Deactivated previous model #{prev_model.id}")

            # Create new model record
            model = MLModel(
                model_type=model_type,
                model_name=f"{model_type}_{symbol or 'global'}",
                symbol=symbol,
                version=version,
                file_path=file_path,
                accuracy=validation_metrics.get('accuracy', 0.0),
                precision=validation_metrics.get('precision', 0.0),
                recall=validation_metrics.get('recall', 0.0),
                f1_score=validation_metrics.get('f1_score', 0.0),
                auc_roc=validation_metrics.get('auc_roc', 0.0),
                hyperparameters=hyperparameters,
                feature_importance=feature_importance,
                is_active=is_active,
                created_at=datetime.utcnow()
            )

            self.db.add(model)
            self.db.commit()

            logger.info(f"✅ Registered new model #{model.id} ({model_type}, {symbol or 'GLOBAL'})")
            return model.id

        except Exception as e:
            logger.error(f"Error registering model: {e}")
            self.db.rollback()
            return -1

    def reload_all_models(self):
        """Force reload all models from disk (hot-reload)"""
        logger.info("Force reloading all models...")

        for cache_key in list(self.loaded_models.keys()):
            symbol = None if cache_key == 'global' else cache_key
            self.load_model(symbol=symbol, force_reload=True)

        logger.info(f"✅ Reloaded {len(self.loaded_models)} models")


# Convenience function for signal generator integration
def get_ml_enhanced_confidence(
    db: Session,
    symbol: str,
    features: Dict,
    rules_confidence: float,
    manager: Optional[MLModelManager] = None
) -> Tuple[float, Optional[int]]:
    """
    Get ML-enhanced confidence for signal

    Args:
        db: Database session
        symbol: Symbol
        features: Features from FeatureEngineer
        rules_confidence: Original rules-based confidence
        manager: Optional MLModelManager instance (for caching)

    Returns:
        (final_confidence, prediction_id)
    """
    if manager is None:
        manager = MLModelManager(db)

    # Get A/B test group
    ab_test_group = manager.get_ab_test_group(symbol)

    # Get ML prediction (if applicable)
    ml_confidence = None
    if ab_test_group in ['ml_only', 'hybrid']:
        ml_confidence = manager.predict(symbol, features)

    # Calculate final confidence
    final_confidence = manager.get_hybrid_confidence(
        ml_confidence,
        rules_confidence,
        ab_test_group
    )

    # Log prediction
    decision = 'trade' if final_confidence >= 0.60 else 'no_trade'
    prediction_id = manager.log_prediction(
        symbol=symbol,
        features=features,
        ml_confidence=ml_confidence or 0.0,
        rules_confidence=rules_confidence,
        final_confidence=final_confidence,
        decision=decision,
        ab_test_group=ab_test_group
    )

    return final_confidence, prediction_id


# CLI tool for model management
if __name__ == '__main__':
    import argparse
    from database import ScopedSession

    parser = argparse.ArgumentParser(description='ML Model Manager CLI')
    parser.add_argument('--evaluate', action='store_true', help='Evaluate active models')
    parser.add_argument('--reload', action='store_true', help='Reload all models')
    parser.add_argument('--list', action='store_true', help='List all models')
    parser.add_argument('--performance', type=int, help='Show performance for model ID')

    args = parser.parse_args()

    db = ScopedSession()
    manager = MLModelManager(db)

    if args.evaluate:
        manager.evaluate_and_switch_models()

    elif args.reload:
        manager.reload_all_models()

    elif args.list:
        models = db.query(MLModel).order_by(MLModel.created_at.desc()).all()
        print(f"\n{'='*80}")
        print(f"{'ID':<5} {'Type':<10} {'Symbol':<10} {'Version':<15} {'Active':<8} {'Accuracy':<10}")
        print(f"{'='*80}")
        for model in models:
            active = '✅' if model.is_active else '  '
            symbol = model.symbol or 'GLOBAL'
            print(f"{model.id:<5} {model.model_type:<10} {symbol:<10} {model.version:<15} {active:<8} {model.accuracy:.3f}")

    elif args.performance:
        perf = manager.get_model_performance(args.performance, days_back=7)
        print(f"\nModel #{args.performance} Performance (7 days):")
        print(f"  Total Predictions: {perf['total_predictions']}")
        print(f"  Accuracy: {perf['accuracy']:.3f}")
        print(f"  Win Rate: {perf['win_rate']:.3f}")
        print(f"  Avg Profit: {perf['avg_profit']:.2f}")
        print(f"  Total Profit: {perf['total_profit']:.2f}")

    else:
        parser.print_help()
