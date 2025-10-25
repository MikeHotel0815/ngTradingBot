# Adaptive Parameter Optimization System

## Overview

Fully automated parameter versioning and optimization system for the Heiken Ashi Trend indicator. The system continuously monitors performance, recommends parameter adjustments, and maintains a complete audit trail of all changes.

## Architecture

### 3-Phase Optimization Approach

```
Phase 1: Weekly Analysis (Every Friday 22:00 UTC)
└─> Performance Reports (7/30/90 day lookback)
    ├─> Symbol-specific metrics
    ├─> Baseline comparison
    ├─> Warning detection
    └─> No auto-changes (analysis only)

Phase 2: Monthly Optimization (Last Friday 23:00 UTC)
└─> Parameter Recommendations
    ├─> Data quality assessment
    ├─> Performance calculation
    ├─> Parameter tuning (±20% max)
    ├─> Safeguard checks
    └─> Manual approval required

Phase 3: Semi-Automatic Application
└─> Human Review & Approval
    ├─> Review recommendations
    ├─> Approve/Reject/Apply
    ├─> Auto-rollback support
    └─> Config file updates
```

## Database Schema

### Tables

#### 1. `indicator_parameter_versions`
Stores all parameter versions with full audit trail.

```sql
CREATE TABLE indicator_parameter_versions (
    id SERIAL PRIMARY KEY,
    indicator_name VARCHAR(100),
    symbol VARCHAR(20),
    timeframe VARCHAR(10),
    version INT,
    parameters JSONB NOT NULL,

    -- Backtest metrics
    backtest_win_rate DECIMAL(5,2),
    backtest_total_pnl DECIMAL(10,2),
    backtest_trades INT,

    -- Live metrics
    live_win_rate DECIMAL(5,2),
    live_total_pnl DECIMAL(10,2),
    live_trades INT,

    -- Status tracking
    status VARCHAR(20) DEFAULT 'proposed',
    approved_by VARCHAR(100),
    activated_at TIMESTAMP,

    UNIQUE(indicator_name, symbol, timeframe, version)
);
```

#### 2. `weekly_performance_reports`
Stores weekly analysis reports.

```sql
CREATE TABLE weekly_performance_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE,
    week_number INT,
    year INT,

    total_trades INT,
    total_win_rate DECIMAL(5,2),
    total_pnl DECIMAL(10,2),

    symbol_metrics JSONB,
    baseline_comparison JSONB,
    warnings JSONB,

    summary TEXT,
    recommendations TEXT,

    UNIQUE(report_date, report_type)
);
```

#### 3. `parameter_optimization_runs`
Stores monthly optimization recommendations.

```sql
CREATE TABLE parameter_optimization_runs (
    id SERIAL PRIMARY KEY,
    run_date TIMESTAMP,
    symbol VARCHAR(20),
    timeframe VARCHAR(10),

    -- Data quality
    data_days INT,
    data_trades INT,
    data_quality_score DECIMAL(5,2),

    -- Current vs Recommended
    current_parameters JSONB,
    recommended_parameters JSONB,

    -- Improvements
    improvement_win_rate DECIMAL(5,2),
    improvement_pnl DECIMAL(10,2),
    improvement_score DECIMAL(5,2),

    -- Safeguards
    safeguards_passed BOOLEAN,
    recommendation VARCHAR(20),  -- keep, adjust, disable
    confidence VARCHAR(20),      -- low, medium, high

    status VARCHAR(20) DEFAULT 'pending_review'
);
```

#### 4. `parameter_change_log`
Complete audit trail for all parameter changes.

```sql
CREATE TABLE parameter_change_log (
    id SERIAL PRIMARY KEY,
    changed_at TIMESTAMP,
    symbol VARCHAR(20),
    timeframe VARCHAR(10),

    old_version_id INT,
    new_version_id INT,

    changes JSONB,
    change_type VARCHAR(50),  -- manual, auto_optimization, rollback
    reason TEXT,
    changed_by VARCHAR(100)
);
```

## Components

### 1. Weekly Performance Analyzer
**File:** `weekly_performance_analyzer.py`

**Purpose:** Generates comprehensive performance reports every Friday.

**Features:**
- Analyzes 7/30/90 day performance windows
- Compares live vs backtest baseline
- Detects performance warnings
- Generates actionable recommendations

**Usage:**
```bash
# Manual run
python3 weekly_performance_analyzer.py

# View reports
SELECT * FROM weekly_performance_reports ORDER BY report_date DESC LIMIT 5;
```

**Warning Types:**
- **Critical:** Win rate < 35%
- **Warning:** >10% drop from baseline
- **Info:** Low sample size (< 10 trades)

### 2. Monthly Parameter Optimizer
**File:** `monthly_parameter_optimizer.py`

**Purpose:** Generates parameter optimization recommendations.

**Safeguards:**
1. Minimum 90 days data
2. Minimum 200 trades per symbol
3. Maximum ±20% parameter change
4. Data quality score ≥ 60/100

**Optimization Rules:**

| Condition | Action | Parameter Change |
|-----------|--------|------------------|
| WR > 45% but R/R < 1.5 | Increase TP | +20% (max 5.0) |
| WR < 40% & Trades < 50 | Lower confidence | -5 (min 50) |
| WR > 50% & Trades > 100 | Raise confidence | +5 (max 80) |
| Max DD > 20 EUR | Tighten SL | -10% (min 1.0) |
| R/R > 2.0 & Trades < 50 | Widen SL | +10% (max 3.0) |

**Usage:**
```bash
# Manual run
python3 monthly_parameter_optimizer.py

# View recommendations
SELECT * FROM parameter_optimization_runs
WHERE status = 'pending_review'
ORDER BY improvement_score DESC;
```

### 3. Parameter Optimization Scheduler
**File:** `parameter_optimization_scheduler.py`

**Purpose:** Automated scheduling for weekly and monthly jobs.

**Schedule:**
- **Weekly Analysis:** Every Friday 22:00 UTC
- **Monthly Optimization:** Last Friday of month 23:00 UTC

**Integration with Supervisor:**

Add to `supervisord.conf`:
```ini
[program:param_optimizer_scheduler]
command=python3 /app/parameter_optimization_scheduler.py
directory=/app
autostart=true
autorestart=true
user=root
stdout_logfile=/var/log/supervisor/param_optimizer.log
stderr_logfile=/var/log/supervisor/param_optimizer_err.log
```

**Usage:**
```bash
# Start scheduler
supervisorctl start param_optimizer_scheduler

# Check logs
supervisorctl tail -f param_optimizer_scheduler

# Manual trigger (for testing)
python3 weekly_performance_analyzer.py
python3 monthly_parameter_optimizer.py
```

### 4. Management Tool
**File:** `manage_parameter_optimizations.py`

**Purpose:** CLI tool for reviewing and applying optimization recommendations.

**Commands:**

```bash
# List pending reviews
python3 manage_parameter_optimizations.py list

# Show details
python3 manage_parameter_optimizations.py show <run_id>

# Approve recommendation
python3 manage_parameter_optimizations.py approve <run_id> --reviewer "admin" --notes "Looks good"

# Reject recommendation
python3 manage_parameter_optimizations.py reject <run_id> --reviewer "admin" --notes "Need more data"

# Apply approved recommendation
python3 manage_parameter_optimizations.py apply <run_id> --applied-by "admin"

# Rollback to previous version
python3 manage_parameter_optimizations.py rollback XAUUSD M5 <version_id> --reason "Performance degraded"
```

**Workflow:**

```
1. Monthly Optimizer runs → Creates optimization_run (status: pending_review)
2. Admin reviews: python3 manage_parameter_optimizations.py list
3. Admin approves: python3 manage_parameter_optimizations.py approve 123
4. Admin applies: python3 manage_parameter_optimizations.py apply 123
   ├─> Creates new parameter version
   ├─> Archives old version
   ├─> Logs change
   └─> Updates config file (manual step)
```

### 5. Seeding Script
**File:** `seed_heiken_ashi_parameters.py`

**Purpose:** Import initial parameters from `heiken_ashi_config.py`.

**Usage:**
```bash
# Seed initial versions (run once)
python3 seed_heiken_ashi_parameters.py
```

**Output:**
- Creates version 1 for each enabled symbol/timeframe
- Imports backtest metrics from config notes
- Sets status to 'active'

## Operational Procedures

### Initial Setup

1. **Run database migration:**
```bash
psql $DATABASE_URL -f migrations/create_parameter_versioning.sql
```

2. **Seed initial parameters:**
```bash
python3 seed_heiken_ashi_parameters.py
```

3. **Start scheduler:**
```bash
supervisorctl start param_optimizer_scheduler
```

### Weekly Review (Manual)

**Every Friday after 22:00 UTC:**

1. Check weekly report:
```bash
docker exec ngtradingbot_workers psql $DATABASE_URL -c "
SELECT
    report_date,
    total_trades,
    total_win_rate,
    total_pnl,
    jsonb_array_length(warnings::jsonb) as warning_count
FROM weekly_performance_reports
ORDER BY report_date DESC
LIMIT 1;
"
```

2. Review warnings:
```sql
SELECT
    report_date,
    jsonb_pretty(warnings::jsonb)
FROM weekly_performance_reports
WHERE jsonb_array_length(warnings::jsonb) > 0
ORDER BY report_date DESC
LIMIT 1;
```

3. Read summary:
```sql
SELECT summary, recommendations
FROM weekly_performance_reports
ORDER BY report_date DESC
LIMIT 1;
```

### Monthly Review (Manual)

**Last Friday of each month after 23:00 UTC:**

1. List pending optimizations:
```bash
python3 manage_parameter_optimizations.py list
```

2. Review each recommendation:
```bash
python3 manage_parameter_optimizations.py show <run_id>
```

3. For HIGH confidence + ADJUST recommendation:
```bash
# Approve
python3 manage_parameter_optimizations.py approve <run_id> --reviewer "your_name"

# Apply
python3 manage_parameter_optimizations.py apply <run_id> --applied-by "your_name"
```

4. For recommendations to DISABLE:
```bash
# Manually update heiken_ashi_config.py
# Set 'enabled': False for the symbol/timeframe

# Restart workers
supervisorctl restart signal_worker
```

### Rollback Procedure

If new parameters cause performance issues:

1. **Check recent changes:**
```sql
SELECT
    id, changed_at, symbol, timeframe,
    old_version_id, new_version_id, reason
FROM parameter_change_log
ORDER BY changed_at DESC
LIMIT 5;
```

2. **Rollback to previous version:**
```bash
python3 manage_parameter_optimizations.py rollback \
    XAUUSD M5 <old_version_id> \
    --reason "New parameters caused 5% WR drop"
```

3. **Verify rollback:**
```sql
SELECT symbol, timeframe, version, status, parameters
FROM indicator_parameter_versions
WHERE symbol = 'XAUUSD' AND timeframe = 'M5'
ORDER BY version DESC
LIMIT 3;
```

## Monitoring

### Key Metrics to Track

1. **Data Quality Scores:**
```sql
SELECT
    symbol,
    timeframe,
    data_quality_score,
    data_trades,
    data_days
FROM parameter_optimization_runs
WHERE run_date >= NOW() - INTERVAL '7 days'
ORDER BY data_quality_score ASC;
```

2. **Improvement Trends:**
```sql
SELECT
    symbol,
    timeframe,
    AVG(improvement_score) as avg_improvement,
    COUNT(*) as optimization_count
FROM parameter_optimization_runs
WHERE run_date >= NOW() - INTERVAL '90 days'
GROUP BY symbol, timeframe
ORDER BY avg_improvement DESC;
```

3. **Parameter Stability:**
```sql
SELECT
    symbol,
    timeframe,
    COUNT(*) as version_count,
    MAX(version) as latest_version
FROM indicator_parameter_versions
GROUP BY symbol, timeframe
ORDER BY version_count DESC;
```

4. **Safeguard Violations:**
```sql
SELECT
    symbol,
    timeframe,
    recommendation,
    safeguards_passed,
    safeguard_details
FROM parameter_optimization_runs
WHERE safeguards_passed = FALSE
AND run_date >= NOW() - INTERVAL '30 days';
```

### Alerts

Set up alerts for:

- **Critical Win Rate:** < 35% for any symbol
- **High Safeguard Failures:** > 3 in one month
- **No Trades:** Symbol has 0 trades for 7 days
- **Pending Reviews:** > 5 unreviewed optimizations

## Best Practices

### Do's ✅

1. **Always review before applying:** Never blindly apply optimization recommendations
2. **Check data quality:** Require score ≥ 80 for high-confidence changes
3. **Monitor after changes:** Track performance for 7 days post-change
4. **Document decisions:** Use --notes flag when approving/rejecting
5. **Keep history:** Never delete parameter versions or change logs

### Don'ts ❌

1. **Don't override safeguards:** They prevent overfitting
2. **Don't change multiple symbols at once:** Stagger deployments
3. **Don't ignore warnings:** Investigate all critical alerts
4. **Don't skip weekly reviews:** Catch issues early
5. **Don't auto-apply without testing:** Always test in staging first

## Troubleshooting

### Issue: "No active Heiken Ashi parameter versions found"

**Solution:**
```bash
python3 seed_heiken_ashi_parameters.py
```

### Issue: "Safeguards failed: Insufficient trades"

**Solution:** Wait for more data. Minimum 200 trades required for optimization.

### Issue: "Data quality too low"

**Causes:**
- Not enough trades (< 200)
- Too short period (< 90 days)
- Imbalanced directions (only BUY or only SELL)

**Solution:** Wait for more trading activity or check if symbol is enabled.

### Issue: "No improvement recommendations generated"

**Meaning:** Current parameters performing well, no changes needed.

**Action:** None - this is expected when parameters are optimal.

## Future Enhancements

### Planned Features

1. **Multi-Objective Optimization:**
   - Optimize for win rate + profit factor + Sharpe ratio
   - Pareto frontier analysis

2. **Machine Learning Integration:**
   - Train ML model on historical parameter performance
   - Predict optimal parameters based on market regime

3. **A/B Testing:**
   - Run two parameter sets in parallel (50/50 split)
   - Statistical significance testing

4. **Market Regime Detection:**
   - Auto-adjust parameters based on detected regime (trending/ranging)
   - Different parameter sets per regime

5. **Notification System:**
   - Email/Slack alerts for pending reviews
   - Weekly performance summaries
   - Critical warning notifications

6. **Web Dashboard:**
   - Visual parameter history
   - Interactive optimization review
   - One-click approve/apply workflow

## References

- **Heiken Ashi Indicator:** [HEIKEN_ASHI_TREND_INDICATOR.md](HEIKEN_ASHI_TREND_INDICATOR.md:1-353)
- **30-Day Backtest:** [HEIKEN_ASHI_30DAY_BACKTEST_REPORT.md](HEIKEN_ASHI_30DAY_BACKTEST_REPORT.md:1-319)
- **Current Config:** [heiken_ashi_config.py](heiken_ashi_config.py:1-232)

## Support

For issues or questions:
- Check logs: `docker logs ngtradingbot_workers | grep -i "parameter"`
- Review database state: `psql $DATABASE_URL`
- Manual testing: Run scripts with `--help` flag

---

**Last Updated:** 2025-10-25
**Version:** 1.0.0
**Status:** Production Ready
