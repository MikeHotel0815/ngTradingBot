#!/usr/bin/env python3
"""
Train XGBoost ML Model
Run inside Docker container: docker exec ngtradingbot_server python train_ml_model.py
"""

import sys
import os

# Ensure we're in the app directory
os.chdir('/app')
sys.path.insert(0, '/app')

from database import ScopedSession
from ml.ml_confidence_model import XGBoostConfidenceModel
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("="*60)
    logger.info("TRAINING XGBOOST ML MODEL")
    logger.info("="*60)

    # Initialize database session
    db = ScopedSession()

    # Create model instance
    model = XGBoostConfidenceModel(
        db=db,
        account_id=3,  # Your account ID
        model_dir='ml_models/xgboost'
    )

    # Train model
    results = model.train(
        symbol=None,  # Train on all symbols
        days_back=90,
        test_size=0.2,
        cross_validate=True,
        save_model=True
    )

    # Print results
    logger.info("\n" + "="*60)
    logger.info("TRAINING RESULTS")
    logger.info("="*60)
    for key, value in results.items():
        if key != 'top_10_features':
            logger.info(f"{key:<30} {value}")

    logger.info("\nTop 10 Important Features:")
    for i, (feature, importance) in enumerate(results['top_10_features'], 1):
        logger.info(f"  {i:2d}. {feature:<30} {importance:.4f}")

    logger.info("="*60)
    logger.info("✅ Model training complete!")
    logger.info("="*60)

    db.close()

if __name__ == '__main__':
    main()
