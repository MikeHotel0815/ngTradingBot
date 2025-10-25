-- Parameter Versioning System for Heiken Ashi Trend Indicator
-- Stores historical parameter versions with performance metrics

-- Table: indicator_parameter_versions
-- Stores versioned parameter sets with metadata
CREATE TABLE IF NOT EXISTS indicator_parameter_versions (
    id SERIAL PRIMARY KEY,
    indicator_name VARCHAR(100) NOT NULL,  -- e.g., 'HEIKEN_ASHI_TREND'
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    version INT NOT NULL,

    -- Parameters (JSON for flexibility)
    parameters JSONB NOT NULL,

    -- Performance metrics from backtest/live
    backtest_win_rate DECIMAL(5,2),
    backtest_total_pnl DECIMAL(10,2),
    backtest_avg_pnl DECIMAL(10,4),
    backtest_trades INT,
    backtest_period_days INT,

    live_win_rate DECIMAL(5,2),
    live_total_pnl DECIMAL(10,2),
    live_avg_pnl DECIMAL(10,4),
    live_trades INT,
    live_period_days INT,

    -- Metadata
    status VARCHAR(20) DEFAULT 'proposed',  -- proposed, approved, active, archived
    approved_by VARCHAR(100),
    approved_at TIMESTAMP,
    activated_at TIMESTAMP,
    deactivated_at TIMESTAMP,

    -- Audit trail
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(100) DEFAULT 'system',
    notes TEXT,

    -- Constraints
    UNIQUE(indicator_name, symbol, timeframe, version)
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_param_versions_symbol_tf
    ON indicator_parameter_versions(indicator_name, symbol, timeframe);

CREATE INDEX IF NOT EXISTS idx_param_versions_status
    ON indicator_parameter_versions(status);

CREATE INDEX IF NOT EXISTS idx_param_versions_active
    ON indicator_parameter_versions(indicator_name, symbol, timeframe, status)
    WHERE status = 'active';

-- Table: weekly_performance_reports
-- Stores weekly analysis reports
CREATE TABLE IF NOT EXISTS weekly_performance_reports (
    id SERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    week_number INT NOT NULL,
    year INT NOT NULL,

    -- Overall metrics
    total_trades INT,
    total_win_rate DECIMAL(5,2),
    total_pnl DECIMAL(10,2),

    -- Symbol-specific metrics (JSON)
    symbol_metrics JSONB,

    -- Comparison to baseline
    baseline_comparison JSONB,

    -- Warnings/Alerts
    warnings JSONB,

    -- Report generation metadata
    lookback_periods INT[] DEFAULT ARRAY[7, 30, 90],
    report_type VARCHAR(50) DEFAULT 'weekly',
    generated_at TIMESTAMP DEFAULT NOW(),

    -- Report content
    summary TEXT,
    recommendations TEXT,
    full_report JSONB,

    UNIQUE(report_date, report_type)
);

-- Index for date-based lookups
CREATE INDEX IF NOT EXISTS idx_weekly_reports_date
    ON weekly_performance_reports(report_date DESC);

-- Table: parameter_optimization_runs
-- Stores monthly optimization run results
CREATE TABLE IF NOT EXISTS parameter_optimization_runs (
    id SERIAL PRIMARY KEY,
    run_date TIMESTAMP DEFAULT NOW(),
    indicator_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    -- Data quality metrics
    data_days INT,
    data_trades INT,
    data_quality_score DECIMAL(5,2),

    -- Current parameters (active version)
    current_version_id INT REFERENCES indicator_parameter_versions(id),
    current_parameters JSONB,
    current_performance JSONB,

    -- Recommended new parameters
    recommended_parameters JSONB,
    recommended_performance JSONB,

    -- Optimization metrics
    improvement_win_rate DECIMAL(5,2),
    improvement_pnl DECIMAL(10,2),
    improvement_score DECIMAL(5,2),

    -- Safeguard checks
    safeguards_passed BOOLEAN DEFAULT FALSE,
    safeguard_details JSONB,

    -- Recommendation
    recommendation VARCHAR(20),  -- keep, adjust, disable
    confidence VARCHAR(20),      -- low, medium, high
    reason TEXT,

    -- Status
    status VARCHAR(20) DEFAULT 'pending_review',  -- pending_review, approved, rejected, applied
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMP,
    review_notes TEXT,

    UNIQUE(run_date, indicator_name, symbol, timeframe)
);

-- Index for lookups
CREATE INDEX IF NOT EXISTS idx_optimization_runs_date
    ON parameter_optimization_runs(run_date DESC);

CREATE INDEX IF NOT EXISTS idx_optimization_runs_status
    ON parameter_optimization_runs(status);

-- Table: parameter_change_log
-- Audit log for all parameter changes
CREATE TABLE IF NOT EXISTS parameter_change_log (
    id SERIAL PRIMARY KEY,
    changed_at TIMESTAMP DEFAULT NOW(),
    indicator_name VARCHAR(100) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,

    -- Version change
    old_version_id INT REFERENCES indicator_parameter_versions(id),
    new_version_id INT REFERENCES indicator_parameter_versions(id),

    -- Change details
    changes JSONB,
    change_type VARCHAR(50),  -- manual, auto_optimization, rollback

    -- Reason
    reason TEXT,
    changed_by VARCHAR(100),

    -- Impact tracking
    trades_before_change INT,
    trades_after_change INT,
    performance_impact JSONB
);

-- Index for audit trail
CREATE INDEX IF NOT EXISTS idx_param_changes_date
    ON parameter_change_log(changed_at DESC);

-- Function: Get active parameter version
CREATE OR REPLACE FUNCTION get_active_parameter_version(
    p_indicator_name VARCHAR,
    p_symbol VARCHAR,
    p_timeframe VARCHAR
) RETURNS JSONB AS $$
DECLARE
    result JSONB;
BEGIN
    SELECT parameters INTO result
    FROM indicator_parameter_versions
    WHERE indicator_name = p_indicator_name
      AND symbol = p_symbol
      AND timeframe = p_timeframe
      AND status = 'active'
    ORDER BY version DESC
    LIMIT 1;

    RETURN result;
END;
$$ LANGUAGE plpgsql;

-- Function: Create new parameter version
CREATE OR REPLACE FUNCTION create_parameter_version(
    p_indicator_name VARCHAR,
    p_symbol VARCHAR,
    p_timeframe VARCHAR,
    p_parameters JSONB,
    p_backtest_metrics JSONB DEFAULT NULL,
    p_created_by VARCHAR DEFAULT 'system',
    p_notes TEXT DEFAULT NULL
) RETURNS INT AS $$
DECLARE
    new_version INT;
    new_id INT;
BEGIN
    -- Get next version number
    SELECT COALESCE(MAX(version), 0) + 1 INTO new_version
    FROM indicator_parameter_versions
    WHERE indicator_name = p_indicator_name
      AND symbol = p_symbol
      AND timeframe = p_timeframe;

    -- Insert new version
    INSERT INTO indicator_parameter_versions (
        indicator_name, symbol, timeframe, version,
        parameters,
        backtest_win_rate, backtest_total_pnl, backtest_avg_pnl,
        backtest_trades, backtest_period_days,
        created_by, notes
    ) VALUES (
        p_indicator_name, p_symbol, p_timeframe, new_version,
        p_parameters,
        (p_backtest_metrics->>'win_rate')::DECIMAL,
        (p_backtest_metrics->>'total_pnl')::DECIMAL,
        (p_backtest_metrics->>'avg_pnl')::DECIMAL,
        (p_backtest_metrics->>'trades')::INT,
        (p_backtest_metrics->>'period_days')::INT,
        p_created_by, p_notes
    ) RETURNING id INTO new_id;

    RETURN new_id;
END;
$$ LANGUAGE plpgsql;

-- Function: Activate parameter version
CREATE OR REPLACE FUNCTION activate_parameter_version(
    p_version_id INT,
    p_approved_by VARCHAR DEFAULT 'system'
) RETURNS BOOLEAN AS $$
DECLARE
    v_indicator_name VARCHAR;
    v_symbol VARCHAR;
    v_timeframe VARCHAR;
    old_version_id INT;
BEGIN
    -- Get version details
    SELECT indicator_name, symbol, timeframe
    INTO v_indicator_name, v_symbol, v_timeframe
    FROM indicator_parameter_versions
    WHERE id = p_version_id;

    -- Deactivate current active version
    UPDATE indicator_parameter_versions
    SET status = 'archived',
        deactivated_at = NOW()
    WHERE indicator_name = v_indicator_name
      AND symbol = v_symbol
      AND timeframe = v_timeframe
      AND status = 'active'
    RETURNING id INTO old_version_id;

    -- Activate new version
    UPDATE indicator_parameter_versions
    SET status = 'active',
        approved_by = p_approved_by,
        approved_at = NOW(),
        activated_at = NOW()
    WHERE id = p_version_id;

    -- Log the change
    INSERT INTO parameter_change_log (
        indicator_name, symbol, timeframe,
        old_version_id, new_version_id,
        change_type, changed_by, reason
    ) VALUES (
        v_indicator_name, v_symbol, v_timeframe,
        old_version_id, p_version_id,
        'activation', p_approved_by, 'Parameter version activated'
    );

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE indicator_parameter_versions IS 'Versioned parameter storage for all indicators';
COMMENT ON TABLE weekly_performance_reports IS 'Weekly performance analysis reports';
COMMENT ON TABLE parameter_optimization_runs IS 'Monthly parameter optimization results';
COMMENT ON TABLE parameter_change_log IS 'Audit trail for all parameter changes';
