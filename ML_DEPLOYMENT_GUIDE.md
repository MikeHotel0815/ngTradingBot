# ML Deployment Guide

**Complete step-by-step guide for deploying CPU-based ML capabilities**

Created: 2025-10-26
Status: Ready for Production
Phase: Phase 1 - CPU-only XGBoost

---

## Prerequisites

- Docker and Docker Compose running
- PostgreSQL 15 with TimescaleDB
- At least 100+ closed trades in database (for training)
- 4+ CPU cores recommended (XGBoost uses all cores)
- 8GB+ RAM

---

## Deployment Steps

### 1. Database Migration

Run SQL migration to create ML tables:

```bash
# From host (Unraid terminal)
docker exec -i ngTradingBot-postgres-1 psql -U trader -d ngtradingbot < /projects/ngTradingBot/migrations/add_ml_tables.sql
```

**Verify migration:**

```bash
docker exec -it ngTradingBot-postgres-1 psql -U trader -d ngtradingbot -c "\dt ml_*"
```

Expected output:
```
                List of relations
 Schema |       Name        | Type  | Owner
--------+-------------------+-------+-------
 public | ml_ab_testing     | table | trader
 public | ml_feature_cache  | table | trader
 public | ml_models         | table | trader
 public | ml_predictions    | table | trader
 public | ml_training_runs  | table | trader
(5 rows)
```

---

### 2. Install ML Dependencies

**Option A: Rebuild Docker image (recommended)**

Edit `docker-compose.yml` to trigger rebuild:

```bash
cd /projects/ngTradingBot
docker-compose build --no-cache
docker-compose up -d
```

**Option B: Install directly in running container**

```bash
docker exec -it ngTradingBot-server-1 pip install xgboost>=2.0.0 scikit-learn>=1.3.0
```

**Verify installation:**

```bash
docker exec -it ngTradingBot-server-1 python3 -c "import xgboost, sklearn; print('XGBoost:', xgboost.__version__); print('Scikit-learn:', sklearn.__version__)"
```

Expected output:
```
XGBoost: 2.0.x
Scikit-learn: 1.3.x
```

---

### 3. Import Historical Data (if needed)

Check if you have enough OHLC data for training:

```bash
docker exec -it ngTradingBot-postgres-1 psql -U trader -d ngtradingbot -c "
SELECT
    symbol,
    timeframe,
    COUNT(*) as candles,
    MIN(timestamp) as first_candle,
    MAX(timestamp) as last_candle
FROM ohlc_data
WHERE timeframe IN ('M5', 'M15', 'H1')
GROUP BY symbol, timeframe
ORDER BY symbol, timeframe;
"
```

**Requirements for ML training:**
- M5: 25,920+ candles (90 days)
- M15: 8,640+ candles (90 days)
- H1: 2,160+ candles (90 days)

**If insufficient data, import historical:**

```bash
# Import 90 days for active symbols
docker exec -it ngTradingBot-server-1 python3 import_historical_for_ml.py --days 90 --all-symbols
```

---

### 4. Train Initial Models

**Train global model (all symbols):**

```bash
docker exec -it ngTradingBot-server-1 python3 ml/ml_training_pipeline.py --days 90 --force
```

Expected output:
```
============================================================
XGBOOST MODEL TRAINING
============================================================
Preparing training data (symbol=None, days=90)
Found 150 trades for training
Training set: 120 samples
Test set: 30 samples
Training XGBoost...

============================================================
TRAINING COMPLETE
============================================================
Accuracy:  0.733
Precision: 0.750
Recall:    0.700
F1 Score:  0.724
AUC-ROC:   0.810
Duration:  15.3s

Top 10 Important Features:
   1. rsi_14                          0.0892
   2. macd_histogram                  0.0756
   3. atr_14                          0.0645
   4. ema_20_50_distance              0.0598
   ...
============================================================

✅ Model saved: ml_models/xgboost/global_v20251026_143022.pkl
✅ Latest symlink: ml_models/xgboost/global_latest.pkl
```

**Train symbol-specific models (recommended for major symbols):**

```bash
# Train for EURUSD
docker exec -it ngTradingBot-server-1 python3 ml/ml_training_pipeline.py --symbol EURUSD --days 90 --force

# Train for XAUUSD
docker exec -it ngTradingBot-server-1 python3 ml/ml_training_pipeline.py --symbol XAUUSD --days 90 --force

# Or train all active symbols at once
docker exec -it ngTradingBot-server-1 python3 ml/ml_training_pipeline.py --all-symbols --days 90 --force
```

---

### 5. Verify Models are Registered

```bash
docker exec -it ngTradingBot-server-1 python3 ml/ml_model_manager.py --list
```

Expected output:
```
================================================================================
ID    Type       Symbol     Version         Active   Accuracy
================================================================================
3     xgboost    XAUUSD     20251026_14350  ✅       0.756
2     xgboost    EURUSD     20251026_14320  ✅       0.733
1     xgboost    GLOBAL     20251026_14302  ✅       0.715
```

---

### 6. Restart Trading Bot

```bash
cd /projects/ngTradingBot
docker-compose restart server
```

**Monitor logs for ML initialization:**

```bash
docker logs -f ngTradingBot-server-1 | grep -i "ml\|xgboost\|model"
```

Expected log entries:
```
INFO - ML module initialized (XGBoost available)
INFO - FeatureEngineer initialized for EURUSD M15
INFO - Loaded model for EURUSD from ml_models/xgboost/EURUSD_latest.pkl
DEBUG - ML Enhancement: EURUSD BUY | Rules: 65.3% | ML: 72.1% | Final: 69.5% | Group: hybrid
```

---

### 7. Monitor ML Performance

**Check prediction logging:**

```bash
docker exec -it ngTradingBot-postgres-1 psql -U trader -d ngtradingbot -c "
SELECT
    symbol,
    ab_test_group,
    COUNT(*) as predictions,
    AVG(ml_confidence) as avg_ml_conf,
    AVG(rules_confidence) as avg_rules_conf,
    AVG(final_confidence) as avg_final_conf
FROM ml_predictions
WHERE prediction_time > NOW() - INTERVAL '24 hours'
GROUP BY symbol, ab_test_group
ORDER BY symbol, ab_test_group;
"
```

**Check model performance (after trades close):**

```bash
docker exec -it ngTradingBot-server-1 python3 ml/ml_model_manager.py --performance 1
```

Expected output:
```
Model #1 Performance (7 days):
  Total Predictions: 87
  Accuracy: 0.713
  Win Rate: 0.698
  Avg Profit: 1.23
  Total Profit: 42.50
```

---

## A/B Testing Configuration

The ML system automatically assigns symbols to test groups:

- **80% ML-only**: Uses XGBoost confidence score
- **10% Rules-only**: Uses original rules-based confidence
- **10% Hybrid**: Combines both (60% ML + 40% rules)

**Assignment is consistent per symbol** (hash-based), ensuring fair comparison.

**Check A/B group distribution:**

```bash
docker exec -it ngTradingBot-postgres-1 psql -U trader -d ngtradingbot -c "
SELECT
    ab_test_group,
    COUNT(DISTINCT symbol) as symbols,
    COUNT(*) as predictions,
    AVG(final_confidence) as avg_confidence
FROM ml_predictions
GROUP BY ab_test_group;
"
```

---

## Automated Retraining

**Setup weekly retraining (via cron):**

```bash
# Edit crontab on Unraid
crontab -e

# Add this line (retrain every Sunday at 2 AM)
0 2 * * 0 docker exec ngTradingBot-server-1 python3 ml/ml_training_pipeline.py --all-symbols --days 90
```

**Manual retraining (if performance degrades):**

```bash
# Check if retraining is needed
docker exec -it ngTradingBot-server-1 python3 ml/ml_model_manager.py --evaluate

# Force retrain all models
docker exec -it ngTradingBot-server-1 python3 ml/ml_training_pipeline.py --all-symbols --days 90 --force
```

---

## Troubleshooting

### Issue: "No module named 'xgboost'"

**Solution:**
```bash
docker exec -it ngTradingBot-server-1 pip install xgboost scikit-learn
docker-compose restart server
```

### Issue: "Insufficient training data: 45 trades (minimum: 100)"

**Solution:**
- Wait for more trades to accumulate (run bot for 1-2 weeks)
- OR reduce `days_back` parameter: `--days 30` (less reliable)
- OR train global model instead of symbol-specific

### Issue: "Model not trained or loaded"

**Solution:**
```bash
# Check if model files exist
docker exec -it ngTradingBot-server-1 ls -lh ml_models/xgboost/

# Retrain if missing
docker exec -it ngTradingBot-server-1 python3 ml/ml_training_pipeline.py --force
```

### Issue: ML predictions not appearing in logs

**Solution:**
```bash
# Check if ML module loaded
docker exec -it ngTradingBot-server-1 python3 -c "from ml.ml_model_manager import MLModelManager; print('ML OK')"

# Check signal generator
docker logs ngTradingBot-server-1 | grep "ML Enhancement"

# If no logs, ML might be disabled - check AB test group
docker exec -it ngTradingBot-postgres-1 psql -U trader -d ngtradingbot -c "SELECT DISTINCT ab_test_group FROM ml_predictions;"
```

---

## Performance Monitoring

**Daily ML performance report:**

```bash
docker exec -it ngTradingBot-server-1 python3 << 'EOF'
from database import get_session
from ml.ml_model_manager import MLModelManager

db = next(get_session())
manager = MLModelManager(db)

print("\n" + "="*60)
print("ML PERFORMANCE REPORT (7 days)")
print("="*60)

manager.evaluate_and_switch_models()

EOF
```

**Compare ML vs Rules performance:**

```sql
-- Run in PostgreSQL
WITH outcomes AS (
    SELECT
        p.ab_test_group,
        p.final_confidence,
        CASE
            WHEN t.profit > 0 THEN 'win'
            WHEN t.profit < 0 THEN 'loss'
            ELSE 'no_trade'
        END as outcome,
        t.profit
    FROM ml_predictions p
    LEFT JOIN trades t ON t.id = p.trade_id
    WHERE p.prediction_time > NOW() - INTERVAL '7 days'
      AND t.close_time IS NOT NULL
)
SELECT
    ab_test_group,
    COUNT(*) as trades,
    SUM(CASE WHEN outcome = 'win' THEN 1 ELSE 0 END)::float / COUNT(*) as win_rate,
    AVG(final_confidence) as avg_confidence,
    SUM(profit) as total_profit,
    AVG(profit) as avg_profit
FROM outcomes
GROUP BY ab_test_group
ORDER BY total_profit DESC;
```

---

## Next Steps (Phase 2 - GPU Required)

**Available from November 2025 (when RTX 3080 accessible):**

1. **LSTM Price Prediction**
   - Requires: TensorFlow/PyTorch with CUDA
   - Training time: 2-4 hours on GPU
   - Predicts next 5-15 candles

2. **Volatility Forecasting**
   - GRU-based volatility prediction
   - Dynamic SL/TP adjustment

3. **Reinforcement Learning Agent**
   - PPO/A3C for autonomous trading
   - Learns optimal entry/exit timing

---

## Support

- GitHub Issues: https://github.com/ngTradingBot/issues
- Documentation: See `docs/` folder
- ML Progress Tracker: `ML_IMPLEMENTATION_PROGRESS.md`

---

**Deployment Checklist:**

- [ ] Database migration complete (5 ML tables created)
- [ ] XGBoost and scikit-learn installed
- [ ] Historical data imported (90+ days)
- [ ] Global model trained (accuracy >60%)
- [ ] Symbol-specific models trained (optional)
- [ ] Models registered in database
- [ ] Server restarted
- [ ] ML predictions logging to database
- [ ] A/B testing active (3 groups)
- [ ] Weekly retraining scheduled

**Status: READY FOR PRODUCTION** ✅
