-- ML Training Infrastructure Tables
-- Created: 2025-10-26
-- Purpose: Support ML model lifecycle (training, versioning, predictions)

-- ============================================================================
-- 1. ML Models Registry
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml_models (
    id SERIAL PRIMARY KEY,
    model_type VARCHAR(50) NOT NULL,           -- 'xgboost', 'lstm', 'rl', 'ensemble'
    model_name VARCHAR(100) NOT NULL,          -- 'xgboost_eurusd_v1', etc.
    symbol VARCHAR(20),                        -- NULL for global models
    timeframe VARCHAR(10),                     -- NULL for multi-timeframe models
    version VARCHAR(20) NOT NULL,              -- Semantic versioning: '1.0.0', '1.1.0'
    file_path TEXT NOT NULL,                   -- Relative path: 'ml_models/xgboost/EURUSD_v1.0.pkl'

    -- Training metadata
    training_date TIMESTAMP NOT NULL DEFAULT NOW(),
    training_duration_seconds INTEGER,         -- How long did training take
    training_samples INTEGER,                  -- Number of samples used

    -- Performance metrics
    validation_accuracy FLOAT,                 -- Accuracy on validation set
    validation_precision FLOAT,                -- Precision (TP / (TP + FP))
    validation_recall FLOAT,                   -- Recall (TP / (TP + FN))
    validation_f1_score FLOAT,                 -- F1 Score
    validation_auc_roc FLOAT,                  -- AUC-ROC

    -- Backtesting results (optional)
    backtest_win_rate FLOAT,                   -- Win rate on backtest
    backtest_profit_factor FLOAT,              -- Gross profit / Gross loss
    backtest_sharpe_ratio FLOAT,               -- Risk-adjusted return
    backtest_max_drawdown FLOAT,               -- Max drawdown %

    -- Model configuration
    hyperparameters JSONB,                     -- Full hyperparameters as JSON
    feature_names TEXT[],                      -- List of feature names used
    feature_importance JSONB,                  -- Feature importance scores

    -- Status
    is_active BOOLEAN DEFAULT FALSE,           -- Currently used in production
    is_champion BOOLEAN DEFAULT FALSE,         -- Best performing model (A/B testing winner)
    deployment_date TIMESTAMP,                 -- When deployed to production
    retired_date TIMESTAMP,                    -- When retired from production

    -- Metadata
    created_by VARCHAR(50) DEFAULT 'system',   -- 'system', 'manual', 'auto_retrain'
    notes TEXT,                                -- Human-readable notes
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Indices for fast queries
CREATE INDEX IF NOT EXISTS idx_ml_models_type ON ml_models(model_type);
CREATE INDEX IF NOT EXISTS idx_ml_models_symbol ON ml_models(symbol);
CREATE INDEX IF NOT EXISTS idx_ml_models_active ON ml_models(is_active) WHERE is_active = TRUE;
CREATE INDEX IF NOT EXISTS idx_ml_models_champion ON ml_models(is_champion) WHERE is_champion = TRUE;
CREATE INDEX IF NOT EXISTS idx_ml_models_version ON ml_models(model_type, symbol, version);

-- Unique constraint: Only one active model per type+symbol
CREATE UNIQUE INDEX IF NOT EXISTS idx_ml_models_unique_active
    ON ml_models(model_type, COALESCE(symbol, ''), COALESCE(timeframe, ''))
    WHERE is_active = TRUE;


-- ============================================================================
-- 2. ML Predictions Log
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml_predictions (
    id SERIAL PRIMARY KEY,
    model_id INTEGER REFERENCES ml_models(id) ON DELETE SET NULL,

    -- Context
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10),
    prediction_time TIMESTAMP NOT NULL DEFAULT NOW(),

    -- Prediction details
    prediction_type VARCHAR(50) NOT NULL,      -- 'trade_confidence', 'price_direction', 'volatility'
    predicted_value FLOAT NOT NULL,            -- Predicted value (e.g., 0.75 for 75% confidence)
    predicted_class VARCHAR(20),               -- For classification: 'BUY', 'SELL', 'HOLD'
    prediction_probability JSONB,              -- Class probabilities: {"BUY": 0.7, "SELL": 0.2, "HOLD": 0.1}

    -- Actual outcome (filled later)
    actual_value FLOAT,                        -- Actual outcome (e.g., 1 if trade won, 0 if lost)
    actual_class VARCHAR(20),                  -- Actual class if applicable
    outcome_timestamp TIMESTAMP,               -- When outcome was determined

    -- Performance tracking
    was_correct BOOLEAN,                       -- Prediction matched outcome
    prediction_error FLOAT,                    -- abs(predicted - actual) for regression

    -- Features used (for debugging)
    features JSONB,                            -- Full feature vector
    feature_count INTEGER,                     -- Number of features

    -- Execution metrics
    execution_time_ms FLOAT,                   -- Inference time in milliseconds

    -- Trade linkage (if prediction led to trade)
    trade_id INTEGER,                          -- Link to trades table
    signal_id INTEGER,                         -- Link to trading_signals table

    created_at TIMESTAMP DEFAULT NOW()
);

-- Indices for analytics
CREATE INDEX IF NOT EXISTS idx_ml_predictions_model ON ml_predictions(model_id);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_symbol ON ml_predictions(symbol);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_time ON ml_predictions(prediction_time DESC);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_trade ON ml_predictions(trade_id) WHERE trade_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ml_predictions_accuracy ON ml_predictions(was_correct) WHERE was_correct IS NOT NULL;

-- Partial index for predictions awaiting outcome
CREATE INDEX IF NOT EXISTS idx_ml_predictions_pending_outcome
    ON ml_predictions(prediction_time DESC)
    WHERE actual_value IS NULL;


-- ============================================================================
-- 3. ML Training Runs
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml_training_runs (
    id SERIAL PRIMARY KEY,
    model_id INTEGER REFERENCES ml_models(id) ON DELETE CASCADE,

    -- Training configuration
    model_type VARCHAR(50) NOT NULL,
    symbols TEXT[],                            -- Symbols included in training
    timeframes TEXT[],                         -- Timeframes used

    -- Time range
    start_time TIMESTAMP NOT NULL,
    end_time TIMESTAMP,
    duration_seconds INTEGER,

    -- Data statistics
    total_samples INTEGER,                     -- Total samples in dataset
    training_samples INTEGER,                  -- Samples used for training
    validation_samples INTEGER,                -- Samples used for validation
    test_samples INTEGER,                      -- Samples used for testing

    -- Training progress
    epochs_completed INTEGER,                  -- For iterative models
    final_training_loss FLOAT,
    final_validation_loss FLOAT,

    -- Performance metrics
    validation_metrics JSONB,                  -- Full validation metrics
    test_metrics JSONB,                        -- Test set metrics

    -- Resource usage
    cpu_usage_percent FLOAT,
    memory_usage_mb FLOAT,
    gpu_used BOOLEAN DEFAULT FALSE,
    gpu_memory_mb FLOAT,

    -- Status
    status VARCHAR(20) NOT NULL,               -- 'running', 'completed', 'failed', 'cancelled'
    error_message TEXT,                        -- If status = 'failed'

    -- Output
    model_file_path TEXT,                      -- Path to saved model
    training_logs TEXT,                        -- Condensed training logs

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_training_runs_model ON ml_training_runs(model_id);
CREATE INDEX IF NOT EXISTS idx_ml_training_runs_status ON ml_training_runs(status);
CREATE INDEX IF NOT EXISTS idx_ml_training_runs_time ON ml_training_runs(start_time DESC);


-- ============================================================================
-- 4. ML Feature Store (Optional - for caching)
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml_feature_cache (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMP NOT NULL,

    -- Features as JSON
    features JSONB NOT NULL,                   -- All calculated features
    feature_hash VARCHAR(64),                  -- MD5 hash for quick lookup

    -- Metadata
    feature_count INTEGER,
    calculation_time_ms FLOAT,

    created_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP                       -- TTL for cache invalidation
);

CREATE INDEX IF NOT EXISTS idx_ml_feature_cache_lookup
    ON ml_feature_cache(symbol, timeframe, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_ml_feature_cache_hash
    ON ml_feature_cache(feature_hash);
CREATE INDEX IF NOT EXISTS idx_ml_feature_cache_expiry
    ON ml_feature_cache(expires_at)
    WHERE expires_at IS NOT NULL;


-- ============================================================================
-- 5. ML A/B Testing Results
-- ============================================================================
CREATE TABLE IF NOT EXISTS ml_ab_testing (
    id SERIAL PRIMARY KEY,

    -- Experiment details
    experiment_name VARCHAR(100) NOT NULL,
    model_a_id INTEGER REFERENCES ml_models(id),
    model_b_id INTEGER REFERENCES ml_models(id),

    -- Configuration
    traffic_split_percent FLOAT DEFAULT 50.0,  -- % of traffic to Model A (rest to B)
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP,

    -- Results per model
    model_a_predictions INTEGER DEFAULT 0,
    model_a_correct INTEGER DEFAULT 0,
    model_a_accuracy FLOAT,
    model_a_profit FLOAT,

    model_b_predictions INTEGER DEFAULT 0,
    model_b_correct INTEGER DEFAULT 0,
    model_b_accuracy FLOAT,
    model_b_profit FLOAT,

    -- Statistical significance
    p_value FLOAT,                             -- Statistical significance
    confidence_level FLOAT,                    -- 95%, 99%, etc.
    winner VARCHAR(10),                        -- 'A', 'B', 'INCONCLUSIVE'

    -- Status
    status VARCHAR(20) DEFAULT 'running',      -- 'running', 'completed', 'stopped'

    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ml_ab_testing_status ON ml_ab_testing(status);
CREATE INDEX IF NOT EXISTS idx_ml_ab_testing_dates ON ml_ab_testing(start_date, end_date);


-- ============================================================================
-- Cleanup Jobs
-- ============================================================================

-- Auto-delete old predictions (keep 90 days)
-- Run daily via pg_cron or Python scheduler
CREATE OR REPLACE FUNCTION cleanup_old_ml_predictions() RETURNS void AS $$
BEGIN
    DELETE FROM ml_predictions
    WHERE created_at < NOW() - INTERVAL '90 days';
END;
$$ LANGUAGE plpgsql;

-- Auto-expire feature cache (keep 24 hours)
CREATE OR REPLACE FUNCTION cleanup_expired_features() RETURNS void AS $$
BEGIN
    DELETE FROM ml_feature_cache
    WHERE expires_at IS NOT NULL AND expires_at < NOW();
END;
$$ LANGUAGE plpgsql;


-- ============================================================================
-- Triggers
-- ============================================================================

-- Update updated_at timestamp on ml_models
CREATE OR REPLACE FUNCTION update_ml_models_timestamp() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_ml_models_updated
    BEFORE UPDATE ON ml_models
    FOR EACH ROW
    EXECUTE FUNCTION update_ml_models_timestamp();


-- ============================================================================
-- Initial Data / Examples
-- ============================================================================

-- Example: Insert dummy model for testing
-- INSERT INTO ml_models (
--     model_type, model_name, symbol, version, file_path,
--     training_samples, validation_accuracy, is_active,
--     hyperparameters, notes
-- ) VALUES (
--     'xgboost', 'xgboost_eurusd_v1', 'EURUSD', '1.0.0', 'ml_models/xgboost/EURUSD_v1.0.pkl',
--     5000, 0.75, TRUE,
--     '{"max_depth": 6, "learning_rate": 0.1, "n_estimators": 100}'::jsonb,
--     'Initial XGBoost model for EURUSD'
-- );


-- ============================================================================
-- Grants (adjust as needed)
-- ============================================================================

-- Grant permissions to trader user
GRANT SELECT, INSERT, UPDATE, DELETE ON ml_models TO trader;
GRANT SELECT, INSERT, UPDATE, DELETE ON ml_predictions TO trader;
GRANT SELECT, INSERT, UPDATE, DELETE ON ml_training_runs TO trader;
GRANT SELECT, INSERT, UPDATE, DELETE ON ml_feature_cache TO trader;
GRANT SELECT, INSERT, UPDATE, DELETE ON ml_ab_testing TO trader;

GRANT USAGE, SELECT ON SEQUENCE ml_models_id_seq TO trader;
GRANT USAGE, SELECT ON SEQUENCE ml_predictions_id_seq TO trader;
GRANT USAGE, SELECT ON SEQUENCE ml_training_runs_id_seq TO trader;
GRANT USAGE, SELECT ON SEQUENCE ml_feature_cache_id_seq TO trader;
GRANT USAGE, SELECT ON SEQUENCE ml_ab_testing_id_seq TO trader;


-- ============================================================================
-- Verification Queries
-- ============================================================================

-- Check tables created
-- SELECT table_name FROM information_schema.tables
-- WHERE table_schema = 'public' AND table_name LIKE 'ml_%';

-- Check indices
-- SELECT indexname FROM pg_indexes
-- WHERE tablename LIKE 'ml_%' ORDER BY tablename, indexname;
