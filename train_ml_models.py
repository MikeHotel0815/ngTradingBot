#!/usr/bin/env python3
"""
Quick ML Model Training Script

Trains XGBoost models using recent trade data.
Usage: docker exec ngtradingbot_workers python3 train_ml_models.py
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
import pickle
import numpy as np
from sklearn.model_selection import train_test_split
import xgboost as xgb

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Database connection
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    'postgresql://trader:tradingbot_secret_2025@postgres:5432/ngtradingbot'
)

def get_training_data(db, days_back=90, min_samples=50):
    """
    Fetch training data from completed trades

    Returns:
        X: Features (numpy array)
        y: Labels (1=profit>0, 0=profit<=0)
        feature_names: List of feature names
    """
    logger.info(f"📊 Fetching training data (last {days_back} days)...")

    query = text("""
        SELECT
            t.symbol,
            t.direction,
            t.open_price as entry_price,
            t.sl,
            t.tp,
            t.profit,
            t.volume,
            t.entry_confidence as confidence,
            EXTRACT(EPOCH FROM (t.close_time - t.open_time))/3600.0 as duration_hours
        FROM trades t
        WHERE t.status = 'closed'
            AND t.created_at > NOW() - INTERVAL '90 days'
            AND t.profit IS NOT NULL
            AND t.entry_confidence IS NOT NULL
            AND t.open_price IS NOT NULL
            AND t.close_time IS NOT NULL
        ORDER BY t.created_at DESC
    """)

    result = db.execute(query)
    rows = result.fetchall()

    if len(rows) < min_samples:
        logger.error(f"❌ Insufficient data: {len(rows)} samples (minimum: {min_samples})")
        return None, None, None

    logger.info(f"✅ Found {len(rows)} completed trades")

    # Extract features
    features = []
    labels = []

    for row in rows:
        try:
            entry_price = float(row.entry_price)
            tp = float(row.tp) if row.tp else entry_price * 1.01
            sl = float(row.sl) if row.sl else entry_price * 0.995

            # Simple feature set from trade data
            feature_vector = [
                float(row.confidence or 50.0),  # Signal confidence
                1.0 if row.direction == 'BUY' else 0.0,  # Direction
                abs(tp - entry_price) / entry_price * 100,  # TP distance %
                abs(entry_price - sl) / entry_price * 100,  # SL distance %
                float(row.volume or 0.01),  # Position size
                float(row.duration_hours or 1.0),  # Trade duration in hours
                abs(tp - entry_price) / abs(entry_price - sl) if abs(entry_price - sl) > 0 else 2.0,  # Risk/Reward ratio
            ]

            # Label: 1 if profitable, 0 if loss
            label = 1 if float(row.profit) > 0 else 0

            features.append(feature_vector)
            labels.append(label)
        except Exception as e:
            logger.warning(f"Skipping row due to error: {e}")
            continue

    feature_names = [
        'confidence',
        'is_buy',
        'tp_distance_pct',
        'sl_distance_pct',
        'volume',
        'duration_hours',
        'risk_reward_ratio'
    ]

    X = np.array(features)
    y = np.array(labels)

    logger.info(f"📈 Feature matrix: {X.shape}")
    logger.info(f"📊 Positive samples: {sum(y)}/{len(y)} ({100*sum(y)/len(y):.1f}%)")

    return X, y, feature_names


def train_xgboost_model(X, y, feature_names):
    """
    Train XGBoost model

    Returns:
        model: Trained XGBoost model
        metrics: Dictionary with performance metrics
    """
    logger.info(f"🤖 Training XGBoost model...")

    # Split data
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    logger.info(f"📊 Train: {len(X_train)} samples, Test: {len(X_test)} samples")

    # Train model
    model = xgb.XGBClassifier(
        n_estimators=100,
        max_depth=6,
        learning_rate=0.1,
        subsample=0.8,
        colsample_bytree=0.8,
        min_child_weight=1,
        gamma=0,
        random_state=42,
        eval_metric='logloss',
        verbosity=1
    )

    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=False
    )

    # Evaluate
    from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, roc_auc_score

    y_pred = model.predict(X_test)
    y_pred_proba = model.predict_proba(X_test)[:, 1]

    metrics = {
        'accuracy': accuracy_score(y_test, y_pred),
        'precision': precision_score(y_test, y_pred),
        'recall': recall_score(y_test, y_pred),
        'f1_score': f1_score(y_test, y_pred),
        'auc_roc': roc_auc_score(y_test, y_pred_proba),
        'train_samples': len(X_train),
        'test_samples': len(X_test)
    }

    logger.info(f"✅ Training complete!")
    logger.info(f"   Accuracy:  {metrics['accuracy']:.4f}")
    logger.info(f"   Precision: {metrics['precision']:.4f}")
    logger.info(f"   Recall:    {metrics['recall']:.4f}")
    logger.info(f"   F1-Score:  {metrics['f1_score']:.4f}")
    logger.info(f"   AUC-ROC:   {metrics['auc_roc']:.4f}")

    # Feature importance
    feature_importance = dict(zip(feature_names, model.feature_importances_))
    logger.info(f"\n📊 Feature Importance:")
    for feat, imp in sorted(feature_importance.items(), key=lambda x: x[1], reverse=True):
        logger.info(f"   {feat:20s}: {imp:.4f}")

    return model, metrics, feature_importance


def save_model(model, metrics, feature_importance, model_dir='ml_models/xgboost'):
    """Save trained model to disk and database"""

    # Create directory if not exists
    os.makedirs(model_dir, exist_ok=True)

    # Generate filename
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"global_v{timestamp}.pkl"
    filepath = os.path.join(model_dir, filename)

    # Feature names from the training
    feature_names = [
        'confidence', 'is_buy', 'tp_distance_pct',
        'sl_distance_pct', 'volume', 'duration_hours',
        'risk_reward_ratio'
    ]

    # Save model (compatible with ml_confidence_model format)
    model_data = {
        'model': model,
        'scaler': None,  # We don't use scaling for these features
        'feature_names': feature_names,
        'metrics': metrics,
        'feature_importance': feature_importance,
        'trained_at': datetime.now().isoformat(),
        'version': timestamp,
        'training_params': {
            'n_estimators': 100,
            'max_depth': 6,
            'learning_rate': 0.1
        }
    }

    with open(filepath, 'wb') as f:
        pickle.dump(model_data, f)

    logger.info(f"💾 Model saved: {filepath}")

    # Also save as latest.pkl
    latest_path = os.path.join(model_dir, 'global_latest.pkl')
    with open(latest_path, 'wb') as f:
        pickle.dump(model_data, f)

    logger.info(f"💾 Latest symlink: {latest_path}")

    return filepath, filename


def update_database(db, filename, metrics, feature_importance):
    """Update ml_models table with new model"""

    logger.info(f"💾 Updating database...")

    # Deactivate old models
    db.execute(text("""
        UPDATE ml_models
        SET is_active = false,
            retired_date = NOW()
        WHERE model_type = 'xgboost'
            AND symbol IS NULL
            AND is_active = true
    """))

    # Insert new model record
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    import json

    insert_query = text("""
        INSERT INTO ml_models (
            model_type, model_name, symbol, version, file_path,
            training_date, training_samples,
            validation_accuracy, validation_precision, validation_recall,
            validation_f1_score, validation_auc_roc,
            feature_importance, is_active, is_champion, created_by
        ) VALUES (
            'xgboost', 'xgboost_global', NULL, :version, :file_path,
            NOW(), :train_samples,
            :accuracy, :precision, :recall, :f1_score, :auc_roc,
            :feature_importance, true, false, 'auto_training'
        )
    """)

    import json

    # Convert numpy types to Python types
    feature_importance_json = {k: float(v) for k, v in feature_importance.items()}

    db.execute(insert_query, {
        'version': timestamp,
        'file_path': filename,
        'train_samples': int(metrics['train_samples']),
        'accuracy': float(metrics['accuracy']),
        'precision': float(metrics['precision']),
        'recall': float(metrics['recall']),
        'f1_score': float(metrics['f1_score']),
        'auc_roc': float(metrics['auc_roc']),
        'feature_importance': json.dumps(feature_importance_json)
    })

    db.commit()
    logger.info(f"✅ Database updated")


def main():
    """Main training pipeline"""

    logger.info(f"\n{'='*70}")
    logger.info(f"🤖 ML MODEL TRAINING PIPELINE")
    logger.info(f"{'='*70}\n")

    try:
        # Connect to database
        engine = create_engine(DATABASE_URL)
        Session = sessionmaker(bind=engine)
        db = Session()

        # 1. Fetch training data
        X, y, feature_names = get_training_data(db, days_back=90)

        if X is None:
            logger.error("❌ Cannot proceed without training data")
            return 1

        # 2. Train model
        model, metrics, feature_importance = train_xgboost_model(X, y, feature_names)

        # 3. Save model
        filepath, filename = save_model(model, metrics, feature_importance)

        # 4. Update database
        update_database(db, filename, metrics, feature_importance)

        logger.info(f"\n{'='*70}")
        logger.info(f"✅ TRAINING COMPLETE!")
        logger.info(f"{'='*70}")
        logger.info(f"📊 Model Performance:")
        logger.info(f"   Accuracy:  {metrics['accuracy']:.1%}")
        logger.info(f"   Precision: {metrics['precision']:.1%}")
        logger.info(f"   Recall:    {metrics['recall']:.1%}")
        logger.info(f"   F1-Score:  {metrics['f1_score']:.1%}")
        logger.info(f"   AUC-ROC:   {metrics['auc_roc']:.4f}")
        logger.info(f"\n💾 Model saved: {filename}")
        logger.info(f"🚀 Model is now ACTIVE and will be used for next trades!")
        logger.info(f"{'='*70}\n")

        db.close()
        return 0

    except Exception as e:
        logger.error(f"❌ Training failed: {e}", exc_info=True)
        return 1


if __name__ == '__main__':
    sys.exit(main())
