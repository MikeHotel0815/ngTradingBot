"""
XGBoost Confidence Model

CPU-optimized ML model for trading signal confidence calibration.

Features:
- Binary classification: TRADE / NO_TRADE
- Input: 80-100 features from FeatureEngineer
- Output: Calibrated confidence score (0-100%)
- Training time: 15-30 minutes on CPU
- Inference time: <10ms per prediction

The model learns from historical trades to predict which signals are
likely to be profitable based on market conditions and technical indicators.

Usage:
    from ml.ml_confidence_model import XGBoostConfidenceModel

    model = XGBoostConfidenceModel()
    model.train(symbol='EURUSD', days_back=90)

    confidence = model.predict(features)
    # Returns: float 0-1 (e.g., 0.75 = 75% confidence)
"""

import logging
import os
import pickle
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sqlalchemy.orm import Session

# ML libraries
try:
    import xgboost as xgb
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.metrics import (
        accuracy_score, precision_score, recall_score,
        f1_score, roc_auc_score, classification_report
    )
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("XGBoost/sklearn not available. Install with: pip install xgboost scikit-learn")

from models import Trade
from ml.ml_features import FeatureEngineer

logger = logging.getLogger(__name__)


class XGBoostConfidenceModel:
    """XGBoost model for signal confidence prediction"""

    # Default hyperparameters (optimized for trading signals)
    DEFAULT_PARAMS = {
        'max_depth': 6,
        'learning_rate': 0.1,
        'n_estimators': 100,
        'min_child_weight': 1,
        'gamma': 0,
        'subsample': 0.8,
        'colsample_bytree': 0.8,
        'objective': 'binary:logistic',
        'eval_metric': 'logloss',
        'random_state': 42,
        'n_jobs': -1,  # Use all CPU cores
        'verbosity': 1
    }

    def __init__(
        self,
        db: Session,
        account_id: int = 1,
        model_dir: str = 'ml_models/xgboost'
    ):
        """
        Initialize XGBoost Confidence Model

        Args:
            db: Database session
            account_id: Account ID
            model_dir: Directory to save/load models
        """
        if not ML_AVAILABLE:
            raise ImportError("XGBoost/sklearn required. Run: pip install xgboost scikit-learn")

        self.db = db
        self.account_id = account_id
        self.model_dir = model_dir
        self.feature_engineer = FeatureEngineer(db, account_id)

        # Model components
        self.model = None
        self.scaler = None
        self.feature_names = []
        self.feature_importance = {}

        # Training metadata
        self.training_date = None
        self.validation_metrics = {}

    def prepare_training_data(
        self,
        symbol: Optional[str] = None,
        days_back: int = 90,
        min_trades: int = 100
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Prepare training data from historical trades

        Args:
            symbol: Optional symbol filter (None = all symbols)
            days_back: Days of history to use
            min_trades: Minimum trades required

        Returns:
            (X_features, y_labels)
        """
        logger.info(f"Preparing training data (symbol={symbol}, days={days_back})")

        cutoff_date = datetime.utcnow() - timedelta(days=days_back)

        # Query closed trades
        query = self.db.query(Trade).filter(
            Trade.account_id == self.account_id,
            Trade.status == 'closed',
            Trade.close_time >= cutoff_date,
            Trade.close_time != None
        )

        if symbol:
            query = query.filter(Trade.symbol == symbol)

        trades = query.all()

        if len(trades) < min_trades:
            raise ValueError(
                f"Insufficient training data: {len(trades)} trades (minimum: {min_trades}). "
                f"Collect more trade history before training."
            )

        logger.info(f"Found {len(trades)} trades for training")

        # Extract features for each trade
        X_data = []
        y_data = []
        skipped = 0

        for trade in trades:
            try:
                # Extract features at trade open time
                features = self.feature_engineer.extract_features(
                    symbol=trade.symbol,
                    timeframe='M15',  # Primary timeframe
                    timestamp=trade.open_time,
                    include_multi_timeframe=True
                )

                # Label: 1 if profitable, 0 if loss
                label = 1 if trade.profit > 0 else 0

                # Convert features to flat dict (remove metadata)
                feature_dict = {k: v for k, v in features.items()
                                if k not in ['symbol', 'timeframe', 'timestamp', 'feature_count']}

                X_data.append(feature_dict)
                y_data.append(label)

            except Exception as e:
                logger.warning(f"Skipping trade #{trade.id}: {e}")
                skipped += 1

        if skipped > 0:
            logger.warning(f"Skipped {skipped} trades due to missing data")

        # Convert to DataFrame
        X = pd.DataFrame(X_data)
        y = pd.Series(y_data)

        # Handle missing values (fill with 0)
        X = X.fillna(0)

        # Store feature names
        self.feature_names = list(X.columns)

        logger.info(f"Training data prepared: {len(X)} samples, {len(X.columns)} features")
        logger.info(f"Class distribution: {y.value_counts().to_dict()}")

        return X, y

    def train(
        self,
        symbol: Optional[str] = None,
        days_back: int = 90,
        test_size: float = 0.2,
        cross_validate: bool = True,
        save_model: bool = True
    ) -> Dict:
        """
        Train XGBoost model

        Args:
            symbol: Optional symbol filter
            days_back: Days of history
            test_size: Test set size (0.2 = 20%)
            cross_validate: Run 5-fold CV
            save_model: Save to disk

        Returns:
            Dict with training results
        """
        logger.info(f"\n{'='*60}")
        logger.info("XGBOOST MODEL TRAINING")
        logger.info(f"{'='*60}")

        start_time = datetime.now()

        # Prepare data
        X, y = self.prepare_training_data(symbol=symbol, days_back=days_back)

        # Train/test split
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=test_size, random_state=42, stratify=y
        )

        logger.info(f"Training set: {len(X_train)} samples")
        logger.info(f"Test set: {len(X_test)} samples")

        # Feature scaling
        self.scaler = StandardScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)

        # Train XGBoost
        logger.info("Training XGBoost...")
        self.model = xgb.XGBClassifier(**self.DEFAULT_PARAMS)

        self.model.fit(
            X_train_scaled, y_train,
            eval_set=[(X_test_scaled, y_test)],
            verbose=False
        )

        # Predictions
        y_pred = self.model.predict(X_test_scaled)
        y_pred_proba = self.model.predict_proba(X_test_scaled)[:, 1]

        # Metrics
        accuracy = accuracy_score(y_test, y_pred)
        precision = precision_score(y_test, y_pred, zero_division=0)
        recall = recall_score(y_test, y_pred, zero_division=0)
        f1 = f1_score(y_test, y_pred, zero_division=0)

        try:
            auc_roc = roc_auc_score(y_test, y_pred_proba)
        except:
            auc_roc = 0.0

        self.validation_metrics = {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1_score': f1,
            'auc_roc': auc_roc
        }

        # Feature importance
        importance = self.model.feature_importances_
        self.feature_importance = dict(zip(self.feature_names, importance))

        # Sort by importance
        sorted_importance = sorted(
            self.feature_importance.items(),
            key=lambda x: x[1],
            reverse=True
        )

        # Cross-validation (optional)
        cv_scores = []
        if cross_validate:
            logger.info("Running 5-fold cross-validation...")
            cv_scores = cross_val_score(
                self.model, X_train_scaled, y_train,
                cv=5, scoring='accuracy', n_jobs=-1
            )
            logger.info(f"CV Accuracy: {cv_scores.mean():.3f} (+/- {cv_scores.std():.3f})")

        duration = (datetime.now() - start_time).total_seconds()

        # Results
        results = {
            'symbol': symbol or 'ALL',
            'training_samples': len(X_train),
            'test_samples': len(X_test),
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1_score': f1,
            'auc_roc': auc_roc,
            'cv_mean': cv_scores.mean() if cross_validate else None,
            'cv_std': cv_scores.std() if cross_validate else None,
            'training_duration_seconds': duration,
            'feature_count': len(self.feature_names),
            'top_10_features': sorted_importance[:10]
        }

        # Print summary
        logger.info(f"\n{'='*60}")
        logger.info("TRAINING COMPLETE")
        logger.info(f"{'='*60}")
        logger.info(f"Accuracy:  {accuracy:.3f}")
        logger.info(f"Precision: {precision:.3f}")
        logger.info(f"Recall:    {recall:.3f}")
        logger.info(f"F1 Score:  {f1:.3f}")
        logger.info(f"AUC-ROC:   {auc_roc:.3f}")
        logger.info(f"Duration:  {duration:.1f}s")
        logger.info(f"\nTop 10 Important Features:")
        for i, (feature, importance) in enumerate(sorted_importance[:10], 1):
            logger.info(f"  {i:2d}. {feature:<30} {importance:.4f}")
        logger.info(f"{'='*60}\n")

        # Save model
        if save_model:
            self.save(symbol=symbol)

        self.training_date = datetime.now()

        return results

    def predict(self, features: Dict) -> float:
        """
        Predict confidence score for given features

        Args:
            features: Dict of features (from FeatureEngineer)

        Returns:
            Confidence score 0-1 (e.g., 0.75 = 75%)
        """
        if self.model is None:
            raise ValueError("Model not trained or loaded. Call train() or load() first.")

        # Convert features to DataFrame
        feature_dict = {k: v for k, v in features.items()
                        if k not in ['symbol', 'timeframe', 'timestamp', 'feature_count']}

        # Ensure all expected features are present
        for feature in self.feature_names:
            if feature not in feature_dict:
                feature_dict[feature] = 0.0  # Fill missing with 0

        # Select only features used in training (in same order)
        X = pd.DataFrame([feature_dict])[self.feature_names]

        # Scale
        X_scaled = self.scaler.transform(X)

        # Predict probability
        confidence = self.model.predict_proba(X_scaled)[0][1]

        return float(confidence)

    def save(self, symbol: Optional[str] = None):
        """
        Save model to disk

        Args:
            symbol: Optional symbol (for filename)
        """
        os.makedirs(self.model_dir, exist_ok=True)

        # Filename
        symbol_part = f"{symbol}_" if symbol else "global_"
        version = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{symbol_part}v{version}.pkl"
        filepath = os.path.join(self.model_dir, filename)

        # Save model + metadata
        model_data = {
            'model': self.model,
            'scaler': self.scaler,
            'feature_names': self.feature_names,
            'feature_importance': self.feature_importance,
            'validation_metrics': self.validation_metrics,
            'training_date': self.training_date,
            'symbol': symbol,
            'hyperparameters': self.DEFAULT_PARAMS
        }

        with open(filepath, 'wb') as f:
            pickle.dump(model_data, f)

        logger.info(f"✅ Model saved: {filepath}")

        # Also save as "latest"
        latest_path = os.path.join(self.model_dir, f"{symbol_part}latest.pkl")
        with open(latest_path, 'wb') as f:
            pickle.dump(model_data, f)

        logger.info(f"✅ Latest symlink: {latest_path}")

        return filepath

    def load(self, filepath: str):
        """
        Load model from disk

        Args:
            filepath: Path to .pkl file
        """
        logger.info(f"Loading model from {filepath}")

        with open(filepath, 'rb') as f:
            model_data = pickle.load(f)

        self.model = model_data['model']
        self.scaler = model_data['scaler']
        self.feature_names = model_data['feature_names']
        self.feature_importance = model_data.get('feature_importance', {})
        self.validation_metrics = model_data.get('validation_metrics', {})
        self.training_date = model_data.get('training_date')

        logger.info(f"✅ Model loaded: {len(self.feature_names)} features")
        logger.info(f"   Accuracy: {self.validation_metrics.get('accuracy', 0):.3f}")

    def get_feature_importance(self, top_n: int = 20) -> List[Tuple[str, float]]:
        """
        Get top N most important features

        Args:
            top_n: Number of features to return

        Returns:
            List of (feature_name, importance) tuples
        """
        sorted_features = sorted(
            self.feature_importance.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return sorted_features[:top_n]


# Convenience function for CLI
def train_model_cli(symbol: str = None, days: int = 90):
    """CLI entry point for training"""
    from database import ScopedSession

    db = ScopedSession()
    model = XGBoostConfidenceModel(db)

    results = model.train(symbol=symbol, days_back=days)

    print("\n" + "="*60)
    print("TRAINING RESULTS")
    print("="*60)
    for key, value in results.items():
        if key != 'top_10_features':
            print(f"{key:<30} {value}")
    print("="*60)

    return results


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='Train XGBoost Confidence Model')
    parser.add_argument('--symbol', help='Symbol to train on (default: all)')
    parser.add_argument('--days', type=int, default=90, help='Days of history (default: 90)')

    args = parser.parse_args()

    train_model_cli(symbol=args.symbol, days=args.days)
