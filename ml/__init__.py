"""
ML Trading Bot - Machine Learning Module

This module provides ML-powered signal enhancement and prediction capabilities.

Components:
- ml_features.py: Feature engineering (80+ features from market data)
- ml_confidence_model.py: XGBoost-based confidence scoring
- ml_model_manager.py: Model lifecycle management
- ml_training_pipeline.py: Automated training & retraining
- ml_ensemble.py: Multi-model voting (when LSTM available)

CPU-Only (Phase 1):
- XGBoost for confidence calibration
- Scikit-learn for preprocessing
- Fast inference (<10ms per prediction)

GPU-Required (Phase 2, November+):
- LSTM for price prediction
- Volatility forecasting
- Reinforcement Learning agent

Version: 1.0.0
Created: 2025-10-26
"""

__version__ = '1.0.0'
__author__ = 'ngTradingBot ML Team'

# Expose main classes for easy import
from .ml_features import FeatureEngineer
from .ml_confidence_model import XGBoostConfidenceModel
from .ml_model_manager import MLModelManager

__all__ = [
    'FeatureEngineer',
    'XGBoostConfidenceModel',
    'MLModelManager',
]
